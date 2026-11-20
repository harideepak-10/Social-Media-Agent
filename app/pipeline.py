"""Glue: generate content for a day, and publish approved content."""
from __future__ import annotations

import json
import shutil
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from . import notify, progress, publishers, storage
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


def video_on_pc() -> bool:
    """VIDEO_RENDERER=pc (set on small servers): videos are queued and made by the PC worker (cli.py worker)."""
    return env("VIDEO_RENDERER", "").strip().lower() == "pc"


def worker_name() -> str:
    import os
    import socket
    return (env("WORKER_NAME", "") or ("server" if os.environ.get("RENDER") else socket.gethostname()))[:80]


QUEUED_STAGE = "Waiting for your PC to make this video"


def _queue_for_pc(item_id: int) -> ContentItem:
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        item.status, item.stage, item.progress, item.error, item.worker = "queued", QUEUED_STAGE, 0, "", ""
        s.commit()
        log.info("video #%s queued for the PC worker", item_id)
        return item


def generate_for(day: date, kind: str | None = None, force: bool = False,
                 only_if_missing: bool = False, origin: str = "schedule", notes: str = "") -> ContentItem | None:
    """Create the content item for `day`. Returns None if nothing is scheduled.
    only_if_missing: skip if ANY item exists for the day (used by start-up catch-up)."""
    kind = kind or planner.kind_for(day)
    if kind not in ("video", "post"):
        log.info("%s: nothing scheduled", day)
        return None

    with get_session() as s:
        # Automatic runs make at most ONE item per day (any kind, even if it failed or was rejected/stopped).
        # "Generate now" / Regenerate pass force=True and always make a new one.
        existing = s.scalars(select(ContentItem).where(ContentItem.run_date == day,
                                                       ContentItem.source_url == "")).first()
        if existing and not force:
            log.info("%s: already has an item (#%s, %s) – automatic runs make one per day", day, existing.id, existing.status)
            return existing
        item = ContentItem(run_date=day, kind=kind, status="generating", origin=origin[:20], worker=worker_name(),
                           notes=(notes or "").strip()[:1000],
                           platforms=",".join((settings().get("platforms") or {}).get(kind, [])))
        s.add(item)
        s.commit()
        item_id = item.id

    if kind == "video" and video_on_pc():
        return _queue_for_pc(item_id)
    return generate_own(item_id, day, kind)


def generate_own(item_id: int, day: date, kind: str) -> ContentItem:
    """Make the brand's own scheduled post/video for an existing queue row."""
    progress.bind(item_id)
    progress.report("Waiting for the previous job to finish…", 1)
    with _lock:
        try:
            progress.report("Researching festivals, trends and products", 3)
            if (settings().get("site") or {}).get("render_js"):
                browser.warmup()
            with get_session() as s:
                notes = (s.get(ContentItem, item_id).notes or "").strip()
            product = _product_named_in(notes) or rotation.pick_product(kind)
            plan = planner.plan(day, kind, product, notes)
            progress.report(f"Planned: {plan['topic']}", 8)
            gen = engine.create(plan, day, item_id, kind, own=True)
            qa = _quality(kind, gen, plan["topic"], item_id)
            copy = gen["copy"]
            progress.check()
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                _save_creative(item, gen)
                item.quality = qa
                item.source = plan["source"]
                item.topic = plan["topic"]
                item.angle = plan["angle"] + (f"\nTrend: {plan['trend_used']}" if plan.get("trend_used") else "")
                item.captions = copy.get("captions", {})
                item.hashtags = gen["hashtags"]
                item.script_json = gen.get("script_json") or json.dumps(
                    {k: v for k, v in copy.items() if k not in ("captions", "hashtags")}, ensure_ascii=False, indent=2)
                item.media_path, item.thumb_path = _persist_media(gen)
                item.status, item.stage, item.progress = "pending_approval", "", 100
                s.commit()
            _notify_new(item)
            return item
        except progress.Stopped:
            return _stopped(item_id)
        except Exception as e:
            log.exception("generation failed")
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                item.status, item.error, item.stage = "failed", str(e)[:2000], ""
                s.commit()
            notify.telegram(f"⚠️ Content generation failed for {day} ({kind}): {e}")
            return item


def _product_named_in(text: str) -> dict | None:
    """'make a post about the Clinic software' -> the Clinic product (longest matching name wins)."""
    if not text:
        return None
    low = text.lower()
    hits = [p for p in settings().get("products") or [] if p.get("name") and p["name"].lower() in low]
    return max(hits, key=lambda p: len(p["name"])) if hits else None


def _quality(kind: str, gen: dict, topic: str, item_id: int) -> dict:
    """Technical + AI check of the finished files (never fails the item)."""
    from .creative import quality
    work = storage.WORK_DIR / f"qa_{item_id}"
    try:
        platforms = (settings().get("platforms") or {}).get(kind, [])
        return quality.check(kind, gen, platforms, topic, work)
    except progress.Stopped:
        raise
    except Exception as e:
        log.exception("quality check failed")
        return {"passed": None, "score": None, "summary": f"Quality check couldn't run: {str(e)[:200]}",
                "problems": [], "checks": []}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def recover_interrupted() -> int:
    """At start-up nothing can be generating yet: items still marked 'generating' were cut off by a restart
    (on Render's free plan usually because a video ran out of memory). Mark them failed so they can be retried."""
    from .generators.ffmpeg import low_memory
    with get_session() as s:
        items = s.scalars(select(ContentItem).where(ContentItem.status == "generating",
                                                    ContentItem.worker.in_([worker_name(), ""]))).all()
        for it in items:
            hint = (" On a small server this usually means it ran out of memory while making the video – "
                    "videos need about 1 GB; try again, or make videos on your PC." if it.kind == "video" and low_memory()
                    else "")
            it.error = (f"The server restarted while this was being made (stopped at {it.progress}%: "
                        f"{it.stage or 'starting'}).{hint}")[:2000]
            it.status, it.stage = "failed", ""
        s.commit()
        return len(items)


def _stopped(item_id: int) -> ContentItem | None:
    """User pressed Stop: leave the item as the API marked it and clean up half-made files."""
    log.info("generation #%s stopped by the user", item_id)
    for d in storage.WORK_DIR.glob(f"*_{item_id}"):
        shutil.rmtree(d, ignore_errors=True)
    with get_session() as s:
        return s.get(ContentItem, item_id)


def _persist_media(gen: dict) -> tuple[str, str]:
    """Upload finished files to cloud storage when configured; returns (media, thumbnail) references."""
    if gen.get("media") or gen.get("thumb"):
        progress.report("Saving files", 98)
    media = storage.persist(gen["media"])
    thumb = media if str(gen.get("thumb")) == str(gen.get("media")) else storage.persist(gen.get("thumb"))
    return media, thumb


def _save_creative(item: ContentItem, gen: dict) -> None:
    item.format = gen.get("format", "")
    item.theme = gen.get("theme", "")
    item.product = gen.get("product", "")
    item.media_alt_path = storage.persist(gen["alt"]) if gen.get("alt") else ""
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


def create_url_item(url: str, kind: str = "video", notes: str = "") -> int:
    """Create the queue row right away (so the UI can open it) – then call generate_from_url(item_id=…)."""
    url = _normalize_url(url)
    with get_session() as s:
        item = ContentItem(run_date=today(), kind=kind, source="url", origin="url", source_url=url, notes=notes,
                           topic=f"{url} …", status="generating", stage="Queued",
                           platforms=",".join((settings().get("platforms") or {}).get(kind, [])))
        s.add(item)
        s.commit()
        return item.id


def generate_from_url(url: str, kind: str = "video", notes: str = "", day: date | None = None,
                      item_id: int | None = None, on_worker: bool = False) -> ContentItem:
    """Create a video or post about ANY website. Goes to the same approval queue."""
    url = _normalize_url(url)
    day = day or today()
    with get_session() as s:
        item = s.get(ContentItem, item_id) if item_id else None
        if item is None:
            item = ContentItem(run_date=day, kind=kind, source="url", origin="url", source_url=url, notes=notes,
                               topic=f"{url} …", platforms=",".join((settings().get("platforms") or {}).get(kind, [])))
            s.add(item)
        item.status, item.error, item.stage, item.progress = "generating", "", "Queued", 0
        item.worker = worker_name()
        s.commit()
        item_id = item.id
    if kind == "video" and video_on_pc() and not on_worker:
        return _queue_for_pc(item_id)

    progress.bind(item_id)
    progress.report("Waiting for the previous job to finish…", 1)
    with _lock:
        try:
            progress.report("Reading the website and its brand", 3)
            brand = planner.brand_for_url(url)
            with use_brand(brand):
                plan = planner.plan_for_url(url, kind, day, notes)
                progress.report(f"Planned: {plan['topic']}", 8)
                gen = engine.create(plan, day, item_id, kind, own=False)
                qa = _quality(kind, gen, plan["topic"], item_id)
            copy = gen["copy"]
            progress.check()
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                _save_creative(item, gen)
                item.quality = qa
                item.topic = f"{brand['name']}: {plan['topic']}"[:300]
                item.angle = plan["angle"]
                item.captions = copy.get("captions", {})
                item.hashtags = gen["hashtags"]
                item.script_json = gen.get("script_json") or json.dumps(
                    {k: v for k, v in copy.items() if k not in ("captions", "hashtags")}, ensure_ascii=False, indent=2)
                item.media_path, item.thumb_path = _persist_media(gen)
                item.status, item.stage, item.progress = "pending_approval", "", 100
                s.commit()
            _notify_new(item)
            return item
        except progress.Stopped:
            return _stopped(item_id)
        except Exception as e:
            log.exception("generation from %s failed", url)
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                item.status, item.error, item.stage = "failed", str(e)[:2000], ""
                s.commit()
            return item


def _notify_new(item: ContentItem) -> None:
    base = env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    notify.telegram(
        f"📝 New <b>{item.kind}</b> for {item.run_date:%a %d %b} waiting for approval\n"
        f"<b>{item.topic}</b>\n{base}/items/{item.id}",
        photo_path=str(storage.local_file(item.thumb_path)) if item.thumb_path else None,
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
            media = item.media_path
            if item.media_alt_path and platform in ("instagram", "facebook"):
                media = item.media_alt_path  # 9:16 version for Reels
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
