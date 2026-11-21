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


def agent_state() -> dict:
    """Pause switch (settings.yaml → agent: {paused, paused_until}). paused_until is the last paused day."""
    a = settings().get("agent") or {}
    until = str(a.get("paused_until") or "")
    return {"paused": bool(a.get("paused")), "paused_until": until}


def agent_paused(day: date | None = None) -> bool:
    """True if automatic generating/posting is off for `day` (default: today)."""
    st = agent_state()
    if not st["paused"]:
        return False
    if st["paused_until"]:
        try:
            return (day or today()) <= date.fromisoformat(st["paused_until"])
        except ValueError:
            return True
    return True


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
        existing = s.scalars(select(ContentItem).where(ContentItem.run_date == day, ContentItem.deleted_at.is_(None),
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
    recover_stuck_publishing(startup=True)
    return _recover_generating()


def _recover_generating() -> int:
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
            if it.job == "rebuild" and it.media_path:  # previous version is still there
                it.status, it.stage, it.job = "pending_approval", "", ""
                it.error = "The server restarted while rebuilding your edit – the previous version is kept."
                continue
            it.status, it.stage, it.job = "failed", "", ""
        s.commit()
        return len(items)


BIN_DAYS = 7


def purge_bin(days: int = BIN_DAYS) -> int:
    """Delete for good what has been in the bin longer than `days` (files too)."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    with get_session() as s:
        old = s.scalars(select(ContentItem).where(ContentItem.deleted_at.is_not(None),
                                                  ContentItem.deleted_at < cutoff)).all()
        for item in old:
            delete_files(item)
            s.delete(item)
        s.commit()
    if old:
        log.info("emptied %s item(s) from the bin", len(old))
    return len(old)


def delete_files(item: ContentItem) -> None:
    for ref in {item.media_path, item.media_alt_path, item.thumb_path}:
        storage.delete_media(ref)
    if item.kind == "video" and item.media_path:  # the editable storyboard + screens kept for video edits
        storage.delete_video_source(item.media_path)


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
    _persist_sources(gen, media)
    return media, thumb


def _persist_sources(gen: dict, media_ref: str) -> None:
    """Keep what's needed to edit the piece later: a poster's HTML design, a video's storyboard + screens."""
    try:
        src = Path(gen["media"]).parent / "source" / f"{Path(gen['media']).stem}.html"
        if src.exists():
            storage.save_file(src, storage.poster_source_key(str(gen["media"])), like=media_ref)
        vsrc = gen.get("video_source")  # local folder with storyboard.json + screens (video_studio)
        if vsrc and Path(vsrc).is_dir():
            prefix = storage.video_source_prefix(str(gen["media"]))
            for f in Path(vsrc).iterdir():
                storage.save_file(f, f"{prefix}/{f.name}", like=media_ref)
            shutil.rmtree(vsrc, ignore_errors=True)
    except Exception as e:  # editing is a bonus – never fail the item for it
        log.warning("could not store the editable source: %s", e)


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


def claim_for_publishing(item_id: int) -> bool:
    """approved/partial -> publishing (atomic), so the 5-minute check and "Publish now" never post twice
    and the dashboard can show "Posting now…"."""
    from sqlalchemy import update
    with get_session() as s:
        n = s.execute(update(ContentItem).where(ContentItem.id == item_id,
                                                ContentItem.status.in_(["approved", "partial"]))
                      .values(status="publishing", stage="Posting now", progress=0,
                              published_at=datetime.utcnow())).rowcount
        s.commit()
        return bool(n)


def publish_item(item_id: int, claimed: bool = False) -> ContentItem:
    if not claimed and not claim_for_publishing(item_id):
        with get_session() as s:
            item = s.get(ContentItem, item_id)
            raise ValueError(f"item #{item_id} is {item.status if item else 'missing'}, not approved")
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        results = item.results
        platforms = item.platform_list
        try:
            for n, platform in enumerate(platforms):
                media = item.media_path
                if item.media_alt_path and platform in ("instagram", "facebook"):
                    media = item.media_alt_path  # 9:16 version for Reels
                if results.get(platform, {}).get("ok") and not results[platform].get("dry_run"):
                    continue  # already posted (retry case)
                item.stage, item.progress = f"Posting to {platform.title()}", int(100 * n / max(1, len(platforms)))
                s.commit()
                results[platform] = publishers.publish(platform, item.kind, media, full_caption(item, platform))
                item.results = dict(results)  # keep what's done even if a later platform crashes
                s.commit()
        except Exception as e:  # unexpected crash: never leave it stuck in "publishing"
            log.exception("publishing #%s crashed", item_id)
            item.results = results
            item.status = "partial" if any(r.get("ok") and not r.get("dry_run") for r in results.values()) else "failed"
            item.stage, item.error = "", f"Posting stopped: {e}"[:2000]
            s.commit()
            return item
        item.results = results
        oks = [r["ok"] for r in results.values()]
        item.status = "published" if all(oks) else ("partial" if any(oks) else "failed")
        if all(r.get("dry_run") for r in results.values()):
            item.status = "dry_run"  # nothing was really posted (no platform credentials yet)
        item.error = "\n".join(f"{p}: {r['error']}" for p, r in results.items() if r["error"])
        item.published_at = datetime.utcnow()
        item.stage, item.progress = "", 100
        s.commit()
    msg = ", ".join(f"{p}: {'✅' if r['ok'] else '❌'}{' (dry-run)' if r.get('dry_run') else ''}" for p, r in results.items())
    notify.telegram(f"📣 Published #{item.id} {item.topic}\n{msg}")
    return item


def publish_due() -> list[int]:
    """Publish approved items whose day has come and whose time (own publish_time, else the default) has passed.
    Only today's and yesterday's items (yesterday = the server was asleep at posting time); older approved
    items are 'missed' and wait for a new date instead of all going out at once. Nothing while paused."""
    from datetime import timedelta
    now = datetime.now(tz())
    if agent_paused(now.date()):
        return []
    default = settings().get("publish_time", "10:00")
    done = []
    with get_session() as s:
        recover_stuck_publishing()
        due = s.scalars(select(ContentItem).where(ContentItem.status == "approved", ContentItem.deleted_at.is_(None),
                                                  ContentItem.run_date <= now.date(),
                                                  ContentItem.run_date >= now.date() - timedelta(days=1))).all()
        ids = []
        for i in due:
            hh, mm = map(int, (i.publish_time or default).split(":"))
            if i.run_date < now.date() or (now.hour, now.minute) >= (hh, mm):
                ids.append(i.id)
    for item_id in ids:
        if not claim_for_publishing(item_id):
            continue  # someone clicked "Publish now" meanwhile
        try:
            publish_item(item_id, claimed=True)
        except Exception:
            log.exception("publishing #%s failed", item_id)
        done.append(item_id)
    return done


PUBLISH_STUCK_MIN = 20


def recover_stuck_publishing(startup: bool = False) -> int:
    """Items left in 'publishing' (server restarted mid-post): never re-post blindly – the platform may already
    have it. Mark them so you can check and press Publish now (platforms that already succeeded are skipped)."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=0 if startup else PUBLISH_STUCK_MIN)
    with get_session() as s:
        items = s.scalars(select(ContentItem).where(ContentItem.status == "publishing",
                                                    ContentItem.published_at <= cutoff)).all()
        for it in items:
            done = [p for p, r in (it.results or {}).items() if r.get("ok") and not r.get("dry_run")]
            it.status = "partial" if done else "failed"
            it.stage = ""
            it.error = ("Posting was interrupted (the server restarted). "
                        + (f"Already posted: {', '.join(done)}. " if done else "")
                        + "Check the account, then press Publish now to finish – posted platforms are skipped.")
        s.commit()
        return len(items)
