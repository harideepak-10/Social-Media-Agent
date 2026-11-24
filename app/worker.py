"""Video worker: runs on your PC and makes the videos the website queued.

The website (Render, VIDEO_RENDERER=pc) can't render videos on its 512 MB server, so it queues them with
status "queued". This worker shares the same database and file storage (DATABASE_URL + SUPABASE_* in the
PC's .env), picks queued videos up one at a time, renders them and uploads the files. Progress, Stop and the
quality check work exactly as on the server.

Start it with run_video_worker.bat (or `python cli.py worker`).
"""
from __future__ import annotations

import json
import logging
import platform
import time
from datetime import datetime, timedelta

from sqlalchemy import select, update

from . import pipeline
from .db import ContentItem, WorkerStatus, get_session, init_db, is_cloud_db

log = logging.getLogger(__name__)
ONLINE_SECONDS = 90  # the website shows the PC as online if it was seen this recently


def heartbeat(state: str = "idle", item_id: int | None = None) -> None:
    info = json.dumps({"state": state, "item": item_id, "os": platform.platform(terse=True)})
    with get_session() as s:
        row = s.get(WorkerStatus, pipeline.worker_name())
        if row is None:
            row = WorkerStatus(name=pipeline.worker_name())
            s.add(row)
        row.last_seen, row.info = datetime.utcnow(), info
        s.commit()


def status() -> dict:
    """For the website: is a video PC online?"""
    with get_session() as s:
        rows = s.scalars(select(WorkerStatus).order_by(WorkerStatus.last_seen.desc())).all()
    if not rows:
        return {"online": False, "name": "", "last_seen": None, "state": ""}
    row = rows[0]
    try:
        info = json.loads(row.info or "{}")
    except ValueError:
        info = {}
    online = datetime.utcnow() - row.last_seen < timedelta(seconds=ONLINE_SECONDS)
    return {"online": online, "name": row.name, "last_seen": row.last_seen.isoformat() + "Z",
            "state": info.get("state", "") if online else "", "item": info.get("item") if online else None}


def recover_stale(minutes: int = 5) -> int:
    """Videos a PC was making when it was switched off / its window closed: that PC stops sending heartbeats.
    Called by the website, so they don't stay on 'generating' forever."""
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    me = pipeline.worker_name()
    n = 0
    with get_session() as s:
        alive = {w.name for w in s.scalars(select(WorkerStatus).where(WorkerStatus.last_seen >= cutoff)).all()}
        known = {w.name for w in s.scalars(select(WorkerStatus)).all()}
        items = s.scalars(select(ContentItem).where(ContentItem.status == "generating",
                                                    ContentItem.worker.notin_([me, ""]))).all()
        for it in items:
            if it.worker in known and it.worker not in alive and it.job == "render":
                it.status, it.stage, it.job = "outline", "", ""
                it.error = f"Your PC ({it.worker}) stopped while making this video – your outline is kept, press Make video again."
                n += 1
            elif it.worker in known and it.worker not in alive and it.job == "rebuild" and it.media_path:
                it.status, it.stage, it.job = "pending_approval", "", ""
                it.error = f"Your PC ({it.worker}) stopped while rebuilding your edit – the previous version is kept."
                n += 1
            elif it.worker in known and it.worker not in alive:
                it.error = (f"Your PC ({it.worker}) stopped while making this video (at {it.progress}%: {it.stage}). "
                            "It was probably switched off or the worker window was closed. Click Regenerate to try again.")[:2000]
                it.status, it.stage = "failed", ""
                n += 1
        s.commit()
    if n:
        log.warning("marked %s video(s) from an offline PC as failed", n)
    return n


def claim() -> ContentItem | None:
    """Take the oldest queued video. The conditional UPDATE makes sure two workers never take the same one."""
    with get_session() as s:
        ids = s.scalars(select(ContentItem.id).where(ContentItem.status == "queued")
                        .order_by(ContentItem.id).limit(5)).all()
        for item_id in ids:
            res = s.execute(update(ContentItem)
                            .where(ContentItem.id == item_id, ContentItem.status == "queued")
                            .values(status="generating", worker=pipeline.worker_name(),
                                    stage="Starting on your PC", progress=1))
            s.commit()
            if res.rowcount == 1:
                return s.get(ContentItem, item_id)
    return None


def run_one(item: ContentItem) -> None:
    import threading
    log.info("making %s #%s on this PC", item.kind, item.id)
    done = threading.Event()

    def beat():  # keep showing "online" on the website during a long render
        while not done.wait(30):
            try:
                heartbeat("working", item.id)
            except Exception:
                pass

    heartbeat("working", item.id)
    t = threading.Thread(target=beat, daemon=True)
    t.start()
    try:
        if item.job in ("rebuild", "render"):  # render = an approved outline, made for the first time
            from . import editing
            editing.rebuild_video(item.id)
        elif item.source_url:
            pipeline.generate_from_url(item.source_url, item.kind, item.notes, item.run_date, item.id, on_worker=True)
        else:
            pipeline.generate_own(item.id, item.run_date, item.kind)
    finally:
        done.set()


def run_forever(poll: int = 20) -> None:
    init_db()
    if not is_cloud_db():
        log.warning("DATABASE_URL is not set: this worker only sees the local agent.db, not the website. "
                    "Put the same DATABASE_URL and SUPABASE_* values as on Render into this PC's .env.")
    stuck = pipeline.recover_interrupted()  # videos this PC was making when it was switched off
    if stuck:
        log.warning("marked %s interrupted video(s) as failed", stuck)
    log.info("video worker '%s' started – checking for queued videos every %ss (Ctrl+C to stop)",
             pipeline.worker_name(), poll)
    while True:
        try:
            heartbeat("idle")
            item = claim()
            if item:
                run_one(item)
                continue  # look for the next one straight away
        except KeyboardInterrupt:
            raise
        except Exception:
            log.exception("worker loop error – retrying")
        time.sleep(poll)
