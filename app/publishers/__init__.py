"""Routes a content item to each platform's publisher. Unconfigured platforms run in dry-run."""
from __future__ import annotations

import logging
from pathlib import Path

from . import linkedin, meta

log = logging.getLogger(__name__)

PLATFORMS = {
    "facebook": (meta.fb_configured, lambda kind, media, caption, url: meta.facebook_publish(kind, media, caption)),
    "instagram": (meta.ig_configured, meta.instagram_publish),
    "linkedin": (linkedin.configured, lambda kind, media, caption, url: linkedin.publish(kind, media, caption)),
}


def publish(platform: str, kind: str, media_ref: str | Path, caption: str) -> dict:
    """media_ref: local path or cloud URL of the file to post."""
    configured, fn = PLATFORMS[platform]
    if not configured():
        log.info("[dry-run] %s %s not configured – skipped", platform, kind)
        return {"ok": True, "dry_run": True, "id": "", "error": ""}
    try:
        from .. import storage
        local = storage.local_file(media_ref)
        url = str(media_ref) if storage.is_url(str(media_ref)) else None
        post = fn(kind, local, caption, url)
        if isinstance(post, dict):  # {"id", "url"}
            return {"ok": True, "dry_run": False, "id": str(post.get("id", "")), "url": post.get("url", ""), "error": ""}
        return {"ok": True, "dry_run": False, "id": post, "error": ""}
    except Exception as e:
        log.exception("publish to %s failed", platform)
        return {"ok": False, "dry_run": False, "id": "", "error": str(e)[:800]}


def status() -> dict:
    return {name: cfg() for name, (cfg, _) in PLATFORMS.items()}
