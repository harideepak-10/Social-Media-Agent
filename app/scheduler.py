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
    day = pipeline.today() + timedelta(days=1)
    log.info("scheduled generation for %s", day)
    pipeline.generate_for(day)


def _catch_up():
    """On startup: make sure today's and tomorrow's content exist (e.g. if the server was asleep)."""
    for offset in (0, 1):
        try:
            pipeline.generate_for(pipeline.today() + timedelta(days=offset), only_if_missing=True)
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
    sch.start()
    threading.Thread(target=_catch_up, daemon=True).start()
    _scheduler = sch
    log.info("scheduler started: generate at %02d:%02d, publish check every 5 min (%s)", gh, gm, tz)
    return sch
