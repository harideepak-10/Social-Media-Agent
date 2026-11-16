"""Live progress for long generations (shown in the dashboard while an item is 'generating')."""
from __future__ import annotations

import time
from contextvars import ContextVar

_item: ContextVar[int | None] = ContextVar("progress_item", default=None)
_last: dict[int, float] = {}


def bind(item_id: int) -> None:
    """Call at the start of a generation (in the worker thread)."""
    _item.set(item_id)


def report(stage: str, pct: int | None = None, throttle: float = 0.0) -> None:
    item_id = _item.get()
    if not item_id:
        return
    now = time.time()
    if throttle and now - _last.get(item_id, 0) < throttle:
        return
    _last[item_id] = now
    from .db import ContentItem, get_session
    try:
        with get_session() as s:
            item = s.get(ContentItem, item_id)
            if item and item.status == "generating":
                item.stage = stage[:200]
                if pct is not None:
                    item.progress = max(0, min(100, int(pct)))
                s.commit()
    except Exception:
        pass  # progress is cosmetic – never break generation
