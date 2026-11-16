"""Festivals, special days, AI-suggested days and your events — and whether to post for them.

Nothing festive is posted unless it is approved:
  * a decision for that occurrence (✅ approved / ❌ skipped), or
  * a remembered rule for that name (always / never / ask), or
  * it's your own special day or event (approved unless paused).
Unapproved days are treated like normal days (the usual product/trend post).
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import holidays
from sqlalchemy import select

from .config import events_config, settings, update_yaml
from .db import OccasionDecision, OccasionRule, OccasionSuggestion, get_session

log = logging.getLogger(__name__)

# Seeded once as "always" – the big ones most Indian businesses greet for. Change any time in the dashboard.
DEFAULT_ALWAYS = ["diwali", "deepavali", "pongal", "christmas", "independence day", "republic day",
                  "new year", "gandhi jayanti"]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:120]


@dataclass
class Occasion:
    date: str
    name: str
    kind: str                 # festival | special | suggestion | event
    status: str               # approved | skipped | pending | paused
    rule: str = "ask"         # always | never | ask   (festival / special only)
    timing: int = 1           # post this many days early
    note: str = ""
    source: str = ""          # "rule" | "decision" | "yours" | "default"
    key: str = ""             # decision key / suggestion id / event id
    reason: str = ""          # suggestions: why it fits
    product: str = ""
    post_date: str = ""
    extra: dict = field(default_factory=dict)


# ── raw calendars ──────────────────────────────────────────────────────────
def _holiday_names(day: date) -> list[str]:
    country = settings().get("country_holidays", "IN")
    try:
        cal = holidays.country_holidays(country, years=day.year, categories=("public", "optional"))
    except Exception:
        cal = holidays.country_holidays(country, years=day.year)
    return [n.strip() for n in cal.get(day, "").split(";") if n.strip()] if day in cal else []


def _special_days() -> dict[str, str]:
    return {str(k): str(v) for k, v in (events_config().get("special_days") or {}).items()}


def _events() -> list[dict]:
    out = []
    for idx, e in enumerate(events_config().get("events") or []):
        try:
            d = date.fromisoformat(str(e.get("date")))
        except ValueError:
            continue
        out.append({"id": idx, "date": d, "title": e.get("title", ""), "details": e.get("details", ""),
                    "remind_days_before": int(e.get("remind_days_before", 0)), "paused": bool(e.get("paused", False))})
    return out


# ── rules & decisions ──────────────────────────────────────────────────────
_seed_lock = threading.Lock()
_seeded = False


def _seed_rules() -> None:
    global _seeded
    if _seeded:
        return
    with _seed_lock, get_session() as s:
        if _seeded or s.scalar(select(OccasionRule.key).limit(1)) is not None:
            _seeded = True
            return
        year = date.today().year
        names: set[str] = set()
        for y in (year, year + 1):
            d = date(y, 1, 1)
            while d.year == y:
                names.update(_holiday_names(d))
                d += timedelta(days=1)
        names.update(["New Year's Day"])
        keys: dict[str, str] = {}
        for n in sorted(names):
            low = n.lower()
            if any(k in low for k in DEFAULT_ALWAYS) and not low.endswith(" eve"):
                keys.setdefault(slug(n), n)
        for k, n in keys.items():
            s.merge(OccasionRule(key=k, name=n, rule="always"))
        try:
            s.commit()
        except Exception:  # another process seeded at the same time – fine
            s.rollback()
        _seeded = True


def _rules() -> dict[str, OccasionRule]:
    _seed_rules()
    with get_session() as s:
        return {r.key: r for r in s.scalars(select(OccasionRule)).all()}


def _decisions(start: date, end: date) -> dict[str, OccasionDecision]:
    with get_session() as s:
        rows = s.scalars(select(OccasionDecision).where(OccasionDecision.day.between(start, end))).all()
        return {r.key: r for r in rows}


def default_timing() -> int:
    return int(settings().get("festival_lookahead_days", 1))


def occasions_between(start: date, end: date) -> list[Occasion]:
    """Every festival / special day / suggestion / event between two dates, with its status."""
    rules = _rules()
    decisions = _decisions(start, end)
    specials = _special_days()
    with get_session() as s:
        suggestions = s.scalars(select(OccasionSuggestion).where(
            OccasionSuggestion.day.between(start, end), OccasionSuggestion.status != "dismissed")).all()
    out: list[Occasion] = []
    d = start
    while d <= end:
        names = [(n, "festival") for n in _holiday_names(d)]
        sp = specials.get(d.strftime("%m-%d"))
        if sp and slug(sp) not in {slug(n) for n, _ in names}:
            names.append((sp, "special"))
        for name, kind in names:
            k = slug(name)
            rule = rules.get(k)
            dec = decisions.get(f"{d.isoformat()}|{k}")
            timing = dec.timing if dec and dec.timing is not None else (
                rule.timing if rule and rule.timing is not None else default_timing())
            note = (dec.note if dec and dec.note else "") or (rule.note if rule else "")
            if dec and dec.status in ("approved", "skipped"):
                status, source = dec.status, "decision"
            elif rule and rule.rule in ("always", "never"):
                status, source = ("approved" if rule.rule == "always" else "skipped"), "rule"
            else:
                status, source = "pending", "default"
            out.append(Occasion(date=d.isoformat(), name=name, kind=kind, status=status,
                                rule=rule.rule if rule else "ask", timing=timing, note=note, source=source,
                                key=f"{d.isoformat()}|{k}", post_date=(d - timedelta(days=timing)).isoformat()))
        d += timedelta(days=1)

    for sg in suggestions:
        k = f"{sg.day.isoformat()}|{slug(sg.name)}"
        dec = decisions.get(k)
        timing = dec.timing if dec and dec.timing is not None else default_timing()
        decided = dec and dec.status in ("approved", "skipped")
        status = dec.status if decided else ("approved" if sg.status == "accepted" else "pending")
        out.append(Occasion(date=sg.day.isoformat(), name=sg.name, kind="suggestion", status=status,
                            timing=timing, note=dec.note if dec else "", source="decision" if dec else "ai",
                            key=str(sg.id), reason=sg.reason, product=sg.product,
                            post_date=(sg.day - timedelta(days=timing)).isoformat()))

    for e in _events():
        first = e["date"] - timedelta(days=e["remind_days_before"])
        if e["date"] < start or first > end:
            continue
        out.append(Occasion(date=e["date"].isoformat(), name=e["title"], kind="event",
                            status="paused" if e["paused"] else "approved", note=e["details"], source="yours",
                            key=str(e["id"]), timing=e["remind_days_before"], post_date=first.isoformat()))
    out.sort(key=lambda o: (o.date, ["festival", "special", "suggestion", "event"].index(o.kind)))
    return out


# ── what the planner uses ─────────────────────────────────────────────────
def festive_for(day: date) -> Occasion | None:
    """Approved festival/special day/suggestion whose greeting should go out on `day`."""
    for o in occasions_between(day, day + timedelta(days=7)):
        if o.kind != "event" and o.status == "approved" and o.post_date == day.isoformat():
            return o
    return None


def event_for(day: date) -> dict | None:
    """Your (not paused) event to announce on `day`."""
    for e in _events():
        if not e["paused"] and e["date"] - timedelta(days=e["remind_days_before"]) <= day <= e["date"]:
            return {**e, "date": e["date"].isoformat(), "days_left": (e["date"] - day).days}
    return None


def pending_soon(days: int = 7, today: date | None = None) -> list[Occasion]:
    today = today or date.today()
    return [o for o in occasions_between(today, today + timedelta(days=days))
            if o.status == "pending" and o.post_date >= today.isoformat()]


# ── changes from the dashboard ────────────────────────────────────────────
def decide(key: str, status: str, timing: int | None = None, note: str | None = None) -> None:
    """status: approved | skipped | clear (back to the rule)."""
    day_s, k = key.split("|", 1)
    day = date.fromisoformat(day_s)
    with get_session() as s:
        row = s.get(OccasionDecision, key)
        if status == "clear":
            if row:
                s.delete(row)
            s.commit()
            return
        name = next((o.name for o in occasions_between(day, day) if o.key == key or slug(o.name) == k), k)
        if not row:
            row = OccasionDecision(key=key, day=day, name=name)
            s.add(row)
        row.status = status
        if timing is not None:
            row.timing = timing
        if note is not None:
            row.note = note
        s.commit()


def set_rule(name: str, rule: str, timing: int | None = None, note: str | None = None) -> None:
    k = slug(name)
    with get_session() as s:
        row = s.get(OccasionRule, k) or OccasionRule(key=k, name=name)
        row.rule = rule
        if timing is not None:
            row.timing = timing
        if note is not None:
            row.note = note
        s.merge(row)
        s.commit()


def suggestion_status(sid: int, status: str) -> None:
    with get_session() as s:
        row = s.get(OccasionSuggestion, sid)
        if row:
            row.status = status
            s.commit()


def add_special_day(mmdd: str, name: str) -> None:
    """Your own special day: repeats every year and is approved (rule 'always')."""
    days = _special_days()
    days[mmdd] = name
    update_yaml("events.yaml", {"special_days": dict(sorted(days.items()))}, replace_keys=("special_days",))
    set_rule(name, "always")


def remove_special_day(mmdd: str) -> None:
    days = _special_days()
    days.pop(mmdd, None)
    update_yaml("events.yaml", {"special_days": dict(sorted(days.items()))}, replace_keys=("special_days",))


def set_event_paused(event_id: int, paused: bool) -> None:
    items = events_config().get("events") or []
    if not 0 <= event_id < len(items):
        raise KeyError(event_id)
    items = [dict(e) for e in items]
    items[event_id]["paused"] = paused
    update_yaml("events.yaml", {"events": items}, replace_keys=("events",))


def suggest_with_ai(days: int = 90) -> int:
    """Ask the AI for well-known observance days that fit your products. Returns how many were added."""
    from . import llm
    from .config import company
    products = settings().get("products") or []
    today = date.today()
    known = {o.name.lower() for o in occasions_between(today, today + timedelta(days=days))}
    prompt = f"""Company: {company().get('name')} — {company().get('industry')}. Audience: {company().get('audience')}.
Products: {[{'name': p['name'], 'what': p.get('description', '')} for p in products]}
Today: {today.isoformat()}. Window: the next {days} days.

List well-known international or Indian observance days (e.g. World Health Day, World Food Day, Data Privacy Day,
National Doctors' Day) in this window that are a natural fit for one of these products. Only include days with a
fixed, widely published date that you are sure about. Skip: {sorted(known)[:40]}.
Return JSON: {{"days": [{{"date": "YYYY-MM-DD", "name": "...", "product": "one product name", "reason": "one line why it fits"}}]}}"""
    data = llm.complete_json(prompt, "You are a careful social media planner. Never invent observance days.", max_tokens=1500)
    added = 0
    with get_session() as s:
        existing = {(r.day, slug(r.name)) for r in s.scalars(select(OccasionSuggestion)).all()}
        for d in (data.get("days") or [])[:15]:
            try:
                day = date.fromisoformat(str(d.get("date")))
            except ValueError:
                continue
            name = str(d.get("name", "")).strip()
            if not name or not today <= day <= today + timedelta(days=days) or (day, slug(name)) in existing \
                    or name.lower() in known:
                continue
            s.add(OccasionSuggestion(day=day, name=name[:200], reason=str(d.get("reason", ""))[:500],
                                     product=str(d.get("product", ""))[:100]))
            added += 1
        s.commit()
    return added


def remind_pending() -> None:
    """Daily: one Telegram reminder per undecided day coming up in the next week."""
    from . import notify
    for o in pending_soon(7):
        if o.kind not in ("festival", "special"):
            continue
        with get_session() as s:
            row = s.get(OccasionDecision, o.key)
            if row and row.reminded:
                continue
        notify.telegram(f"🎉 <b>{o.name}</b> is on {date.fromisoformat(o.date):%a %d %b}. "
                        f"Post a greeting? Decide in the dashboard → Schedule.")
        # remember that we reminded, without deciding
        with get_session() as s:
            row = s.get(OccasionDecision, o.key)
            if not row:
                s.add(OccasionDecision(key=o.key, day=date.fromisoformat(o.date), name=o.name,
                                       status="pending", reminded=1))
            else:
                row.reminded = 1
            s.commit()


def as_dict(o: Occasion) -> dict:
    return asdict(o)
