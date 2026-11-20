"""Anti-repetition: picks the post format, theme and product that were used least recently,
and collects recent headlines so the AI never reuses a hook."""
from __future__ import annotations

import json
import random

from sqlalchemy import select

from ..config import settings
from ..db import ContentItem, get_session
from .catalog import FESTIVE_THEMES, POST_FORMATS, POST_THEMES, VIDEO_THEMES


def _history(kind: str | None = None, limit: int = 40, own_only: bool = True) -> list[ContentItem]:
    with get_session() as s:
        q = select(ContentItem).where(ContentItem.status.notin_(["failed", "rejected"]))
        if kind:
            q = q.where(ContentItem.kind == kind)
        if own_only:
            q = q.where(ContentItem.source_url == "")
        return list(s.scalars(q.order_by(ContentItem.id.desc()).limit(limit)).all())


def _lru(options: list[str], used: list[str], avoid_last: int) -> str:
    """Least-recently-used option, never one of the last `avoid_last`, random among ties."""
    blocked = set(used[:avoid_last])
    pool = [o for o in options if o not in blocked] or options
    never = [o for o in pool if o not in used]
    if never:
        return random.choice(never)
    return max(pool, key=lambda o: used.index(o))  # used longest ago


# Added after people already saved their format/theme lists: switched on for them automatically
# (settings post.catalog_version < 2). Once the list is saved again from Settings it is respected as is.
NEW_V2 = {"formats": ["object_metaphor", "services_overview"], "themes": ["receipt_red", "forest_mint"]}


def allowed(key: str, catalog: dict) -> list[str]:
    cfg = (settings().get("post") or {})
    lst = list(cfg.get(key) or catalog)
    if cfg.get(key) and int(cfg.get("catalog_version") or 1) < 2:
        lst += [x for x in NEW_V2[key] if x not in lst]
    return [x for x in lst if x in catalog]


def pick_post_format(source: str, available: set[str], own: bool = True) -> str:
    """available: capabilities we have today, e.g. {"product", "shot", "festival", "trend", "photo"}."""
    ok = allowed("formats", POST_FORMATS)
    options = [f for f, spec in POST_FORMATS.items()
               if f in ok and source in spec["sources"] and spec["needs"] <= available]
    if not options:
        options = ["big_statement"]
    used = [i.format for i in _history("post", own_only=own) if i.format]
    return _lru(options, used, avoid_last=min(4, max(1, len(options) - 1)))


def pick_post_theme(fmt: str, own: bool = True) -> str:
    ok = allowed("themes", POST_THEMES)
    options = [t for t in (FESTIVE_THEMES if fmt == "festive_greeting" else list(POST_THEMES)) if t in ok]
    if fmt != "festive_greeting":
        options = [t for t in options if t != "midnight_violet"] or options
    used = [i.theme for i in _history("post", own_only=own) if i.theme]
    return _lru(options or list(POST_THEMES), used, avoid_last=2)


def pick_video_theme(own: bool = True) -> str:
    allowed = (settings().get("video") or {}).get("themes") or list(VIDEO_THEMES)
    used = [i.theme for i in _history("video", own_only=own) if i.theme]
    return _lru([t for t in VIDEO_THEMES if t in allowed] or list(VIDEO_THEMES), used, avoid_last=1)


def pick_product(kind: str) -> dict | None:
    products = settings().get("products") or []
    if not products:
        return None
    used = [i.product for i in _history(None) if i.product]
    name = _lru([p["name"] for p in products], used, avoid_last=min(2, len(products) - 1))
    return next(p for p in products if p["name"] == name)


def recent_creative_memory(limit: int = 15, own: bool = True) -> str:
    """Headlines / hooks / formats used lately — the AI must not repeat them."""
    lines = []
    for i in _history(None, limit, own_only=own):
        head = ""
        try:
            data = json.loads(i.script_json or "{}")
            head = data.get("headline") or (data.get("intro") or {}).get("headline", "")
        except Exception:
            pass
        lines.append(f"- {i.run_date} {i.kind}/{i.format or '-'}: {i.topic} | headline: {head}")
    return "\n".join(lines) or "- (nothing yet)"
