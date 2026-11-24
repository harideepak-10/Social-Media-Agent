"""JSON API: edit a poster's text, edit a video's scenes / voice, results after posting.
Registered before app/api.py's generic /items/{id}/{action} route so these paths win."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, editing, pipeline
from .db import ContentItem, get_session

router = APIRouter(prefix="/api")
User = Depends(auth.require_user)


def _serialize(item_id: int) -> dict:
    from .api import serialize
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        return serialize(item, full=True)


def _item(item_id: int) -> ContentItem:
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        s.expunge(item)
        return item


# ── poster text ────────────────────────────────────────────────────────────
@router.get("/items/{item_id}/design")
def get_design(item_id: int, _: str = User):
    try:
        return {"html": editing.poster_html(_item(item_id))}
    except editing.EditError as e:
        raise HTTPException(409, str(e))


class DesignIn(BaseModel):
    html: str = Field(..., min_length=50)


@router.put("/items/{item_id}/design")
def put_design(item_id: int, body: DesignIn, _: str = User):
    try:
        _, issues = editing.save_poster(item_id, body.html)
    except editing.EditError as e:
        raise HTTPException(409, str(e))
    return {"item": _serialize(item_id), "issues": issues}


# ── video scenes ───────────────────────────────────────────────────────────
@router.get("/items/{item_id}/storyboard")
def get_storyboard(item_id: int, _: str = User):
    try:
        return editing.storyboard(item_id)
    except editing.EditError as e:
        raise HTTPException(409, str(e))


class RewriteIn(BaseModel):
    part: str
    instruction: str = Field("", max_length=500)


@router.post("/items/{item_id}/storyboard/rewrite")
def rewrite_part(item_id: int, body: RewriteIn, _: str = User):
    try:
        return {"part": body.part, "texts": editing.rewrite(item_id, body.part, body.instruction)}
    except editing.EditError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(400, f"The AI couldn't rewrite it: {str(e)[:150]}")


class StoryboardIn(BaseModel):
    edits: dict = {}
    voice_name: str = ""
    render: bool = True    # outline: False = just save it, True = "Make video"


@router.put("/items/{item_id}/storyboard")
def put_storyboard(item_id: int, body: StoryboardIn, _: str = User):
    try:
        item = editing.save_storyboard(item_id, body.edits, body.voice_name, body.render)
    except editing.EditError as e:
        raise HTTPException(409, str(e))
    if item.status == "generating":  # this server renders it; otherwise the PC worker picks it up
        threading.Thread(target=editing.rebuild_video, args=(item_id,), daemon=True).start()
    return _serialize(item_id)


# ── results after posting ──────────────────────────────────────────────────
@router.post("/items/{item_id}/metrics")
def refresh_metrics(item_id: int, _: str = User):
    from . import insights
    if _item(item_id).status not in ("published", "partial"):
        raise HTTPException(409, "Results are available once it's posted")
    insights.refresh_item(item_id)
    return _serialize(item_id)
