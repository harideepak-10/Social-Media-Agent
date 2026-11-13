"""Festivals, national days and company events for a given date."""
from __future__ import annotations

from datetime import date, timedelta

import holidays

from ..config import events_config, settings

# Popular Indian festivals that the `holidays` package may label differently or miss
# (dates vary yearly; add exact dates to config/events.yaml special_days if needed).


def festivals_on(day: date) -> list[str]:
    cfg = settings()
    country = cfg.get("country_holidays", "IN")
    names: list[str] = []
    try:
        cal = holidays.country_holidays(country, years=day.year, categories=("public", "optional"))
    except Exception:
        cal = holidays.country_holidays(country, years=day.year)
    if day in cal:
        names += [n.strip() for n in cal.get(day).split(";")]
    special = (events_config().get("special_days") or {}).get(day.strftime("%m-%d"))
    if special:
        names.append(special)
    return list(dict.fromkeys(names))


def upcoming_festival(day: date) -> tuple[str, date] | None:
    """Festival on `day` or within lookahead days (to post wishes early)."""
    look = int(settings().get("festival_lookahead_days", 0))
    for offset in range(0, look + 1):
        d = day + timedelta(days=offset)
        names = festivals_on(d)
        if names:
            return names[0], d
    return None


def company_event(day: date) -> dict | None:
    for ev in events_config().get("events") or []:
        try:
            ev_date = date.fromisoformat(str(ev["date"]))
        except (KeyError, ValueError):
            continue
        before = int(ev.get("remind_days_before", 0))
        if ev_date - timedelta(days=before) <= day <= ev_date:
            return {**ev, "days_left": (ev_date - day).days}
    return None


def next_festivals(day: date, days: int = 30) -> list[tuple[date, str]]:
    out = []
    for i in range(days):
        d = day + timedelta(days=i)
        for n in festivals_on(d):
            out.append((d, n))
    return out
