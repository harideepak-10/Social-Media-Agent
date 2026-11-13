"""Glue: generate content for a day, and publish approved content."""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from . import notify, publishers
from .config import env, settings, use_brand
from .db import ContentItem, get_session
from .creative import engine, rotation
from .generators import browser, planner

log = logging.getLogger(__name__)
_lock = threading.Lock()  # one heavy generation at a time


def tz() -> ZoneInfo:
    return ZoneInfo(settings().get("timezone", "Asia/Kolkata"))


def today() -> date:
    return datetime.now(tz()).date()


def generate_for(day: date, kind: str | None = None, force: bool = False,
                 only_if_missing: bool = False) -> ContentItem | None:
    """Create the content item for `day`. Returns None if nothing is scheduled.
    only_if_missing: skip if ANY item exists for the day (used by start-up catch-up)."""
    kind = kind or planner.kind_for(day)
    if kind not in ("video", "post"):
        log.info("%s: nothing scheduled", day)
        return None

    with get_session() as s:
        q = select(ContentItem).where(ContentItem.run_date == day, ContentItem.kind == kind,
                                      ContentItem.source_url == "")
        if not only_if_missing:
            q = q.where(ContentItem.status.notin_(["rejected", "failed"]))
        existing = s.scalars(q).first()
        if existing and not force:
            log.info("%s: %s already exists (#%s)", day, kind, existing.id)
            return existing
        item = ContentItem(run_date=day, kind=kind, status="generating",
                           platforms=",".join((settings().get("platforms") or {}).get(kind, [])))
        s.add(item)
        s.commit()
        item_id = item.id

    with _lock:
        try:
            if (settings().get("site") or {}).get("render_js"):
                browser.warmup()
            product = rotation.pick_product(kind)
            plan = planner.plan(day, kind, product)
            gen = engine.create(plan, day, item_id, kind, own=True)
            copy = gen["copy"]
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                _save_creative(item, gen)
                item.source = plan["source"]
                item.topic = plan["topic"]
                item.angle = plan["angle"] + (f"\nTrend: {plan['trend_used']}" if plan.get("trend_used") else "")
                item.captions = copy.get("captions", {})
                item.hashtags = gen["hashtags"]
                item.script_json = gen.get("script_json") or json.dumps(
                    {k: v for k, v in copy.items() if k not in ("captions", "hashtags")}, ensure_ascii=False, indent=2)
                item.media_path = str(gen["media"])
                item.thumb_path = str(gen["thumb"])
                item.status = "pending_approval"
                s.commit()
            _notify_new(item)
            return item
        except Exception as e:
            log.exception("generation failed")
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                item.status, item.error = "failed", str(e)[:2000]
                s.commit()
            notify.telegram(f"⚠️ Content generation failed for {day} ({kind}): {e}")
            return item


def _save_creative(item: ContentItem, gen: dict) -> None:
    item.format = gen.get("format", "")
    item.theme = gen.get("theme", "")
    item.product = gen.get("product", "")
    item.media_alt_path = str(gen["alt"]) if gen.get("alt") else ""
    item.error = gen.get("warning", "")


def _normalize_url(url: str) -> str:
    """Add a scheme if missing (try https first, then http)."""
    import httpx

    url = url.strip()
    if url.startswith(("http://", "https://")):
        return url
    for scheme in ("https://", "http://"):
        try:
            httpx.head(scheme + url, timeout=10, follow_redirects=True)
            return scheme + url
        except httpx.HTTPError:
            continue
    return "https://" + url


def generate_from_url(url: str, kind: str = "video", notes: str = "", day: date | None = None,
                      item_id: int | None = None) -> ContentItem:
    """Create a video or post about ANY website. Goes to the same approval queue."""
    url = _normalize_url(url)
    day = day or today()
    with get_session() as s:
        item = s.get(ContentItem, item_id) if item_id else None
        if item is None:
            item = ContentItem(run_date=day, kind=kind, source="url", source_url=url, notes=notes,
                               topic=f"{url} …", platforms=",".join((settings().get("platforms") or {}).get(kind, [])))
            s.add(item)
        item.status, item.error = "generating", ""
        s.commit()
        item_id = item.id

    with _lock:
        try:
            brand = planner.brand_for_url(url)
            with use_brand(brand):
                plan = planner.plan_for_url(url, kind, day, notes)
                gen = engine.create(plan, day, item_id, kind, own=False)
            copy = gen["copy"]
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                _save_creative(item, gen)
                item.topic = f"{brand['name']}: {plan['topic']}"[:300]
                item.angle = plan["angle"]
                item.captions = copy.get("captions", {})
                item.hashtags = gen["hashtags"]
                item.script_json = gen.get("script_json") or json.dumps(
                    {k: v for k, v in copy.items() if k not in ("captions", "hashtags")}, ensure_ascii=False, indent=2)
                item.media_path, item.thumb_path = str(gen["media"]), str(gen["thumb"])
                item.status = "pending_approval"
                s.commit()
            _notify_new(item)
            return item
        except Exception as e:
            log.exception("generation from %s failed", url)
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                item.status, item.error = "failed", str(e)[:2000]
                s.commit()
            return item


def _notify_new(item: ContentItem) -> None:
    base = env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    notify.telegram(
        f"📝 New <b>{item.kind}</b> for {item.run_date:%a %d %b} waiting for approval\n"
        f"<b>{item.topic}</b>\n{base}/item/{item.id}",
        photo_path=item.thumb_path or None,
    )


def full_caption(item: ContentItem, platform: str) -> str:
    cap = item.captions.get(platform) or next(iter(item.captions.values()), "")
    tags = item.hashtags.split()
    if platform == "linkedin":
        tags = tags[:5]
    missing = [t for t in tags if t.lower() not in cap.lower()]
    return (cap.rstrip() + ("\n\n" + " ".join(missing) if missing else "")).strip()


def publish_item(item_id: int) -> ContentItem:
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if item.status not in ("approved", "partial"):
            raise ValueError(f"item #{item_id} is {item.status}, not approved")
        results = item.results
        for platform in item.platform_list:
            media = Path(item.media_path)
            if item.media_alt_path and platform in ("instagram", "facebook"):
                media = Path(item.media_alt_path)  # 9:16 version for Reels
            if results.get(platform, {}).get("ok") and not results[platform].get("dry_run"):
                continue  # already posted (retry case)
            results[platform] = publishers.publish(platform, item.kind, media, full_caption(item, platform))
        item.results = results
        oks = [r["ok"] for r in results.values()]
        item.status = "published" if all(oks) else ("partial" if any(oks) else "failed")
        if all(r.get("dry_run") for r in results.values()):
            item.status = "dry_run"  # nothing was really posted (no platform credentials yet)
        item.error = "\n".join(f"{p}: {r['error']}" for p, r in results.items() if r["error"])
        item.published_at = datetime.utcnow()
        s.commit()
    msg = ", ".join(f"{p}: {'✅' if r['ok'] else '❌'}{' (dry-run)' if r.get('dry_run') else ''}" for p, r in results.items())
    notify.telegram(f"📣 Published #{item.id} {item.topic}\n{msg}")
    return item


def publish_due() -> list[int]:
    """Publish approved items whose day has come and publish_time has passed."""
    now = datetime.now(tz())
    hh, mm = map(int, settings().get("publish_time", "10:00").split(":"))
    done = []
    with get_session() as s:
        due = s.scalars(select(ContentItem).where(ContentItem.status == "approved",
                                                  ContentItem.run_date <= now.date())).all()
        ids = [i.id for i in due if i.run_date < now.date() or (now.hour, now.minute) >= (hh, mm)]
    for item_id in ids:
        publish_item(item_id)
        done.append(item_id)
    return done
