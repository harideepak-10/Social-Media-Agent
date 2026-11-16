"""Where generated files are saved.

media/
  posters/            2026-11-18_restaurant-pos_before-after_12.jpg
    source/           …the HTML each poster was designed from (open in a browser to tweak)
  videos/             2026-11-20_clinic_promo_14_16x9.mp4  +  …_9x16.mp4
  thumbnails/         video cover images used by the dashboard
  .work/              temporary files while rendering (cleaned up automatically)
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .config import MEDIA_DIR

POSTERS_DIR = MEDIA_DIR / "posters"
POSTER_SOURCES_DIR = POSTERS_DIR / "source"
VIDEOS_DIR = MEDIA_DIR / "videos"
THUMBS_DIR = MEDIA_DIR / "thumbnails"
WORK_DIR = MEDIA_DIR / ".work"

for _d in (POSTERS_DIR, POSTER_SOURCES_DIR, VIDEOS_DIR, THUMBS_DIR, WORK_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len].rstrip("-") or "content"


def base_name(day: date, item_id: int, plan: dict | None = None, label: str = "") -> str:
    """e.g. 2026-11-18_restaurant-pos_before-after_12"""
    plan = plan or {}
    what = (plan.get("product") or {}).get("name") or plan.get("topic") or plan.get("source") or ""
    parts = [f"{day:%Y-%m-%d}", slug(what, 30)]
    if label:
        parts.append(slug(label, 20))
    parts.append(str(item_id))
    return "_".join(p for p in parts if p)


def poster_path(day: date, item_id: int, plan: dict | None = None, label: str = "") -> Path:
    return POSTERS_DIR / f"{base_name(day, item_id, plan, label)}.jpg"


def poster_source_path(poster: Path) -> Path:
    return POSTER_SOURCES_DIR / f"{poster.stem}.html"


def video_paths(day: date, item_id: int, plan: dict | None = None, label: str = "") -> dict[str, Path]:
    name = base_name(day, item_id, plan, label)
    return {"landscape": VIDEOS_DIR / f"{name}_16x9.mp4", "vertical": VIDEOS_DIR / f"{name}_9x16.mp4",
            "square": VIDEOS_DIR / f"{name}_1x1.mp4"}


def thumb_path(video: Path) -> Path:
    return THUMBS_DIR / f"{video.stem.rsplit('_', 1)[0]}.jpg"


def work_dir(kind: str, item_id: int) -> Path:
    d = WORK_DIR / f"{kind}_{item_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def organize_existing() -> int:
    """Move files from the old layout (media/<date>/post_12.jpg …) into the new folders and fix the DB."""
    import shutil
    from datetime import date as _date

    from .db import ContentItem, get_session

    moved = 0
    with get_session() as s:
        for item in s.query(ContentItem).all():
            plan = {"product": {"name": item.product}, "topic": item.topic, "source": item.source}
            changes = {}
            for attr in ("media_path", "media_alt_path", "thumb_path"):
                old = Path(getattr(item, attr) or "")
                if not old.is_file() or old.parent in (POSTERS_DIR, VIDEOS_DIR, THUMBS_DIR):
                    continue
                if attr == "thumb_path" and item.kind == "post":
                    continue  # posts use the poster itself as thumbnail
                if item.kind == "post":
                    new = poster_path(item.run_date or _date.today(), item.id, plan, item.format)
                elif attr == "thumb_path":
                    new = THUMBS_DIR / f"{base_name(item.run_date, item.id, plan, 'promo')}.jpg"
                else:
                    paths = video_paths(item.run_date, item.id, plan, "promo")
                    new = paths["vertical"] if attr == "media_alt_path" or "vertical" in old.stem else paths["landscape"]
                shutil.move(str(old), new)
                changes[attr] = str(new)
                moved += 1
                html = old.with_suffix(".html")
                if item.kind == "post" and html.is_file():
                    shutil.move(str(html), poster_source_path(new))
            if item.kind == "post" and "media_path" in changes:
                changes["thumb_path"] = changes["media_path"]
            for k, v in changes.items():
                setattr(item, k, v)
        s.commit()
    # remove empty dated folders left behind
    for d in MEDIA_DIR.iterdir():
        if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name):
            try:
                d.rmdir()
            except OSError:
                pass
    return moved
