"""Routes a content item to each platform's publisher. Unconfigured platforms run in dry-run."""
from __future__ import annotations

import logging
from pathlib import Path

from . import linkedin, meta

log = logging.getLogger(__name__)

PLATFORMS = {
    "facebook": (meta.fb_configured, meta.facebook_publish),
    "instagram": (meta.ig_configured, meta.instagram_publish),
    "linkedin": (linkedin.configured, lambda kind, media, caption: linkedin.publish(kind, media, caption)),
}


def publish(platform: str, kind: str, media: Path, caption: str) -> dict:
    configured, fn = PLATFORMS[platform]
    if not configured():
        log.info("[dry-run] %s %s not configured – skipped", platform, kind)
        return {"ok": True, "dry_run": True, "id": "", "error": ""}
    try:
        post_id = fn(kind, media, caption)
        return {"ok": True, "dry_run": False, "id": post_id, "error": ""}
    except Exception as e:
        log.exception("publish to %s failed", platform)
        return {"ok": False, "dry_run": False, "id": "", "error": str(e)[:800]}


def status() -> dict:
    return {name: cfg() for name, (cfg, _) in PLATFORMS.items()}
