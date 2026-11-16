"""Chooses format/theme (no repeats), gathers visuals, runs the post designer / video studio,
and falls back to the simple generators if the premium engine fails."""
from __future__ import annotations

import logging
import shutil
from datetime import date

from ..config import MEDIA_DIR, settings
from ..generators import post as simple_post
from ..generators import video as simple_video
from .. import progress
from . import assets, post_designer, rotation, video_studio, visuals

log = logging.getLogger(__name__)


def create(plan: dict, day: date, item_id: int, kind: str, own: bool = True) -> dict:
    """Returns the generator result plus 'format', 'theme', 'product', 'alt', 'warning'."""
    product = plan.get("product")
    try:
        if kind == "video":
            theme = rotation.pick_video_theme(own)
            gen = video_studio.generate(plan, day, item_id, theme, product)
            gen.update(format="promo", theme=theme)
        else:
            gen = _post(plan, day, item_id, product, own)
        gen.update(product=(product or {}).get("name", ""), warning="")
        return gen
    except Exception as e:
        if not (settings().get("creative") or {}).get("fallback", True):
            raise
        log.exception("premium %s engine failed – using the simple generator", kind)
        progress.report("Premium design failed – making the simple version", 60)
        gen = simple_video.generate(plan, day, item_id) if kind == "video" else simple_post.generate(plan, day, item_id)
        gen.update(format="simple", theme="", alt=None, product=(product or {}).get("name", ""),
                   warning=f"Premium design failed, simple version used: {e}"[:600])
        return gen


def _post(plan: dict, day: date, item_id: int, product: dict | None, own: bool) -> dict:
    source = plan["source"]
    available = set()
    if product:
        available.add("product")
        if product.get("url"):
            available.add("shot")
    if source == "festival":
        available.add("festival")
    if source == "event":
        available.add("event")
    if source == "trend" or plan.get("trend_used"):
        available.add("trend")
    if assets.image_provider():
        available.add("photo")

    fmt = rotation.pick_post_format(source, available, own)
    shots = []
    progress.report(f"Format: {fmt.replace('_', ' ')}", 12)
    if fmt == "ui_showcase":
        progress.report("Capturing product screenshots", 15)
        cap = visuals.capture(product["url"], MEDIA_DIR / f"{day:%Y-%m-%d}" / f"_cap_{item_id}")
        # the most "screen-like" blocks: biggest area first
        shots = sorted(cap["blocks"], key=lambda b: -(b["w"] * b["h"]))[:2]
        if not shots:
            fmt = rotation.pick_post_format(source, available - {"shot"}, own)
    theme = rotation.pick_post_theme(fmt, own)
    review = (settings().get("post") or {}).get("self_review", True)
    log.info("post #%s: format=%s theme=%s product=%s", item_id, fmt, theme, (product or {}).get("name"))
    try:
        gen = post_designer.generate(plan, day, item_id, fmt, theme, product, shots, review=review)
    finally:
        shutil.rmtree(MEDIA_DIR / f"{day:%Y-%m-%d}" / f"_cap_{item_id}", ignore_errors=True)
    gen.update(format=fmt, theme=theme, alt=None)
    return gen
