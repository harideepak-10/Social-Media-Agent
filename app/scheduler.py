"""Background jobs: prepare tomorrow's content every evening, publish approved content on time."""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import pipeline
from .config import settings

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _generate_tomorrow():
    try:
        from . import occasions
        occasions.remind_pending()   # "Pongal is in 5 days – post a greeting?" (Telegram, once each)
    except Exception:
        log.exception("festival reminder failed")
    day = pipeline.today() + timedelta(days=1)
    log.info("scheduled generation for %s", day)
    pipeline.generate_for(day, origin="schedule")


def catch_up_days(now=None) -> list:
    """Only what a sleeping server actually missed:
    - today's item, if it's still before publish time (after that it's too late to post today);
    - tomorrow's item, if the evening generation time has already passed.
    Never a second item for a day that already has one (generate_for checks that)."""
    from datetime import datetime
    cfg = settings()
    now = now or datetime.now(pipeline.tz())
    ph, pm = map(int, cfg.get("publish_time", "10:00").split(":"))
    gh, gm = map(int, cfg.get("generate_time", "18:00").split(":"))
    days = []
    if (now.hour, now.minute) < (ph, pm):
        days.append(now.date())
    if (now.hour, now.minute) >= (gh, gm):
        days.append(now.date() + timedelta(days=1))
    return days


def _catch_up():
    """On startup (e.g. the free server woke up): make only the content the schedule missed."""
    for day in catch_up_days():
        try:
            pipeline.generate_for(day, only_if_missing=True, origin="catch_up")
        except Exception:
            log.exception("catch-up generation failed")


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler:
        return _scheduler
    cfg = settings()
    tz = cfg.get("timezone", "Asia/Kolkata")
    gh, gm = map(int, cfg.get("generate_time", "18:00").split(":"))
    sch = BackgroundScheduler(timezone=tz)
    sch.add_job(_generate_tomorrow, CronTrigger(hour=gh, minute=gm, timezone=tz), id="generate",
                max_instances=1, coalesce=True, misfire_grace_time=3 * 3600)
    sch.add_job(pipeline.publish_due, "interval", minutes=5, id="publish", max_instances=1, coalesce=True)
    if pipeline.video_on_pc():  # videos left half-made by a PC that went offline -> failed, so they can be retried
        from . import worker
        sch.add_job(worker.recover_stale, "interval", minutes=5, id="stale_videos", max_instances=1, coalesce=True)
    sch.start()
    threading.Thread(target=_catch_up, daemon=True).start()
    _scheduler = sch
    log.info("scheduler started: generate at %02d:%02d, publish check every 5 min (%s)", gh, gm, tz)
    return sch


def reschedule() -> None:
    """Apply a changed generate_time / timezone without restarting the app."""
    if not _scheduler:
        return
    cfg = settings()
    tz = cfg.get("timezone", "Asia/Kolkata")
    gh, gm = map(int, cfg.get("generate_time", "18:00").split(":"))
    _scheduler.reschedule_job("generate", trigger=CronTrigger(hour=gh, minute=gm, timezone=tz))
    log.info("rescheduled generation to %02d:%02d (%s)", gh, gm, tz)


def next_runs() -> dict:
    if not _scheduler:
        return {}
    out = {}
    for job in _scheduler.get_jobs():
        out[job.id] = job.next_run_time.isoformat() if job.next_run_time else None
    return out
