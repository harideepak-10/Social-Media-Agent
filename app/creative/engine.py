"""Chooses format/theme (no repeats), gathers visuals, runs the post designer / video studio,
and falls back to the simple generators if the premium engine fails."""
from __future__ import annotations

import logging
import shutil
from datetime import date
from pathlib import Path

from .. import storage
from ..config import settings
from ..generators import post as simple_post
from ..generators import video as simple_video
from .. import progress
from ..config import company
from . import assets, festive, post_designer, rotation, sitetheme, video_studio, visuals

log = logging.getLogger(__name__)


def create(plan: dict, day: date, item_id: int, kind: str, own: bool = True, options: dict | None = None) -> dict:
    """Returns the generator result plus 'format', 'theme', 'product', 'alt', 'warning'.
    options (Create from URL): length short|full|series, outline (stop at the storyboard), uploads
    [{path, caption}] = the user's own screenshots."""
    options = options or {}
    product = plan.get("product")
    uploads = options.get("uploads") or []
    if kind == "post":  # recordings are for videos
        uploads = [u for u in uploads if not u.get("video")]
    length = {"series": "short"}.get(options.get("length", ""), options.get("length", ""))
    vkw = dict(length=length, uploads=uploads, outline_only=bool(options.get("outline") and (length or uploads)),
               style=options.get("style") or "tour")
    site = None if own else sitetheme.build((company() or {}).get("design") or {}, (company() or {}).get("brand_colors"))
    try:
        if kind == "video":
            if site:
                gen = video_studio.generate(plan, day, item_id, "website", product, theme_spec=site[1], **vkw)
                gen.update(format="walkthrough" if length else "promo", theme="website")
            else:
                theme = rotation.pick_video_theme(own)
                gen = video_studio.generate(plan, day, item_id, theme, product, **vkw)
                gen.update(format="walkthrough" if length else "promo", theme=theme)
        else:
            gen = _post(plan, day, item_id, product, own, site[0] if site else None, uploads)
        gen.update(product=(product or {}).get("name", ""), warning="")
        return gen
    except Exception as e:
        if not (settings().get("creative") or {}).get("fallback", True) or vkw["outline_only"]:
            raise
        log.exception("premium %s engine failed – using the simple generator", kind)
        shutil.rmtree(storage.WORK_DIR / f"{kind}_{item_id}", ignore_errors=True)
        progress.report("Premium design failed – making the simple version", 60)
        gen = simple_video.generate(plan, day, item_id) if kind == "video" else simple_post.generate(plan, day, item_id)
        gen.update(format="simple", theme="", alt=None, product=(product or {}).get("name", ""),
                   warning=f"Premium design failed, simple version used: {e}"[:600])
        return gen


def _post(plan: dict, day: date, item_id: int, product: dict | None, own: bool, site_theme: dict | None = None,
          uploads: list[dict] | None = None) -> dict:
    source = plan["source"]
    if source == "festival" or plan.get("festival"):
        # festival greetings use the dedicated designer (photo or illustrated scene + script lettering)
        progress.report("Format: festival greeting", 12)
        gen = festive.generate(plan, day, item_id, product, own)
        gen.update(alt=None)
        return gen
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

    user_shots = []
    for up in uploads or []:  # the user's own screenshots: always shown as the screen in the post
        try:
            from PIL import Image
            with Image.open(up["path"]) as im:
                user_shots.append({"id": f"U{len(user_shots)}", "path": Path(up["path"]), "w": im.width,
                                   "h": im.height, "text": up.get("caption", "")})
        except Exception as e:
            log.warning("uploaded screenshot skipped: %s", e)
    if user_shots:
        available.add("shot")
    fmt = "ui_showcase" if user_shots else rotation.pick_post_format(source, available, own)
    shots = []
    progress.report(f"Format: {fmt.replace('_', ' ')}", 12)
    if fmt == "ui_showcase" and user_shots:
        shots = user_shots[:2]
    elif fmt == "ui_showcase":
        progress.report("Capturing product screenshots", 15)
        cap = visuals.capture(product["url"], storage.WORK_DIR / f"cap_{item_id}")
        # the most "screen-like" blocks: biggest area first
        shots = sorted(cap["blocks"], key=lambda b: -(b["w"] * b["h"]))[:2]
        if not shots:
            fmt = rotation.pick_post_format(source, available - {"shot"}, own)
    theme = "website" if site_theme else rotation.pick_post_theme(fmt, own)
    review = (settings().get("post") or {}).get("self_review", True)
    log.info("post #%s: format=%s theme=%s product=%s", item_id, fmt, theme, (product or {}).get("name"))
    try:
        gen = post_designer.generate(plan, day, item_id, fmt, theme, product, shots, review=review,
                                     theme_spec=site_theme)
    finally:
        shutil.rmtree(storage.WORK_DIR / f"cap_{item_id}", ignore_errors=True)
    gen.update(format=fmt, theme=theme, alt=None)
    return gen
