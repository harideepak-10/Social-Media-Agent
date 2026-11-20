"""JSON API used by the React dashboard (frontend/) — also handy for n8n / Super Agent."""
from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select

from . import auth, pipeline, publishers
from .config import DATA_DIR, MEDIA_DIR, company, settings
from .db import ContentItem, get_session
from .generators import planner
from .research import calendar

router = APIRouter(prefix="/api")
User = Depends(auth.require_user)
ACTIONS = ("approve", "reject", "regenerate", "publish", "stop", "check")
DELETABLE = ("rejected", "failed")


def _bg(fn, *args, **kw):
    threading.Thread(target=fn, args=args, kwargs=kw, daemon=True).start()


def media_url(path: str) -> str:
    from . import storage
    return storage.web_url(path)


def saved_as(path: str) -> str:
    """e.g. media/posters/2026-11-18_clinic_myth-fact_7.jpg  (or supabase: media/posters/… in the cloud)"""
    from . import storage
    return storage.display_path(path, DATA_DIR)


def _quality_summary(i: ContentItem) -> dict | None:
    q = i.quality
    if not q:
        return None
    return {"passed": q.get("passed"), "score": q.get("score"),
            "issues": len(q.get("problems") or []) + sum(c.get("status") == "fail" for c in q.get("checks") or [])}


def serialize(i: ContentItem, full: bool = False) -> dict:
    data = {
        "id": i.id, "date": i.run_date.isoformat(), "kind": i.kind, "status": i.status,
        "source": i.source, "source_url": i.source_url, "notes": i.notes,
        "topic": i.topic, "product": i.product, "format": i.format, "theme": i.theme,
        "media": media_url(i.media_path), "media_vertical": media_url(i.media_alt_path),
        "thumb": media_url(i.thumb_path), "platforms": i.platform_list,
        "stage": i.stage, "progress": i.progress, "error": i.error,
        "quality": _quality_summary(i), "origin": i.origin or ("url" if i.source_url else ""),
        "created_at": i.created_at.isoformat() + "Z" if i.created_at else None,
        "published_at": i.published_at.isoformat() + "Z" if i.published_at else None,
    }
    if full:
        try:
            script = json.loads(i.script_json) if i.script_json else None
        except ValueError:
            script = i.script_json
        data.update(files=[f for f in (saved_as(i.media_path), saved_as(i.media_alt_path)) if f],
                    quality_report=i.quality, angle=i.angle, captions=i.captions, hashtags=i.hashtags, results=i.results, script=script,
                    previews={p: pipeline.full_caption(i, p) for p in i.platform_list} if i.captions else {})
    return data


def _get(s, item_id: int) -> ContentItem:
    item = s.get(ContentItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


def _run_check(item_id: int) -> dict:
    """Run the technical + AI quality check on an existing item's files."""
    import shutil
    from . import storage
    from .config import settings
    from .creative import quality
    with get_session() as s:
        item = _get(s, item_id)
        kind, media, alt, captions, tags, topic = (item.kind, item.media_path, item.media_alt_path, item.captions,
                                                   item.hashtags, item.topic)
        platforms = item.platform_list or (settings().get("platforms") or {}).get(kind, [])
    work = storage.WORK_DIR / f"qa_{item_id}"
    try:
        gen = {"media": storage.local_file(media), "alt": storage.local_file(alt) if alt else None,
               "copy": {"captions": captions}, "hashtags": tags}
        report = quality.check(kind, gen, platforms, topic, work)
    except Exception as e:
        raise HTTPException(400, f"Quality check failed: {str(e)[:200]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with get_session() as s:
        item = _get(s, item_id)
        item.quality = report
        s.commit()
        return serialize(item, full=True)


def _delete_item(s, item: ContentItem) -> None:
    from . import storage
    for ref in {item.media_path, item.media_alt_path, item.thumb_path}:
        storage.delete_media(ref)
    s.delete(item)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, _: str = User):
    with get_session() as s:
        item = _get(s, item_id)
        if item.status not in DELETABLE:
            raise HTTPException(409, "Only rejected, stopped or failed items can be deleted")
        _delete_item(s, item)
        s.commit()
    return {"ok": True}


@router.post("/items/delete-rejected")
def delete_rejected(_: str = User):
    with get_session() as s:
        items = s.scalars(select(ContentItem).where(ContentItem.status.in_(DELETABLE))).all()
        for item in items:
            _delete_item(s, item)
        s.commit()
    return {"deleted": len(items)}


# ── auth ──────────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginIn):
    if not auth.check_password(body.username, body.password):
        raise HTTPException(401, "Wrong username or password")
    return {"token": auth.make_token(body.username), "user": body.username}


@router.get("/me")
def me(user: str = User):
    return {"user": user}


# ── overview ──────────────────────────────────────────────────────────────
@router.get("/meta")
def meta(_: str = User):
    today = pipeline.today()
    with get_session() as s:
        counts = dict(s.execute(select(ContentItem.status, func.count()).group_by(ContentItem.status)).all())
    from datetime import timedelta
    from . import occasions
    occ = occasions.occasions_between(today, today + timedelta(days=6))
    week = [{"date": (today + timedelta(days=n)).isoformat(),
             "kind": planner.kind_for(today + timedelta(days=n)),
             "festivals": calendar.festivals_on(today + timedelta(days=n)),
             "occasions": [{"name": o.name, "status": o.status, "kind": o.kind} for o in occ
                           if o.date == (today + timedelta(days=n)).isoformat() and o.kind != "event"]}
            for n in range(7)]
    c = company()
    return {
        "company": {"name": c.get("name"), "website": c.get("website"), "tagline": c.get("tagline")},
        "platforms": publishers.status(),
        "products": [p["name"] for p in settings().get("products") or []],
        "counts": counts, "week": week,
        "times": {"generate": settings().get("generate_time"), "publish": settings().get("publish_time"),
                  "timezone": settings().get("timezone")},
        "video": {"formats": (settings().get("video") or {}).get("formats", []),
                  "voiceover": (settings().get("video") or {}).get("voiceover", True)},
        "video_worker": _video_worker(),
    }


def _video_worker() -> dict:
    """Where videos are made: on this server, or by the PC worker (with its online status)."""
    if not pipeline.video_on_pc():
        return {"mode": "server"}
    from . import worker
    try:
        worker.recover_stale()
        return {"mode": "pc", **worker.status()}
    except Exception:
        return {"mode": "pc", "online": False, "name": "", "last_seen": None, "state": ""}


# ── content queue ─────────────────────────────────────────────────────────
@router.get("/items")
def list_items(status: str | None = None, kind: str | None = None, q: str | None = None,
               limit: int = 60, offset: int = 0, _: str = User):
    with get_session() as s:
        query = select(ContentItem)
        if status:
            query = query.where(ContentItem.status.in_(status.split(",")))
        if kind:
            query = query.where(ContentItem.kind == kind)
        if q:
            like = f"%{q}%"
            query = query.where(or_(ContentItem.topic.ilike(like), ContentItem.product.ilike(like),
                                    ContentItem.source_url.ilike(like), ContentItem.format.ilike(like)))
        total = s.scalar(select(func.count()).select_from(query.subquery()))
        generating_first = case((ContentItem.status.in_(["generating", "queued"]), 0), else_=1)
        rows = s.scalars(query.order_by(generating_first, ContentItem.run_date.desc(), ContentItem.id.desc())
                         .limit(min(limit, 200)).offset(offset)).all()
        return {"total": total, "items": [serialize(i) for i in rows]}


@router.get("/items/{item_id}")
def get_item(item_id: int, _: str = User):
    with get_session() as s:
        return serialize(_get(s, item_id), full=True)


class ItemPatch(BaseModel):
    captions: dict[str, str] | None = None
    hashtags: str | None = None
    platforms: list[str] | None = None


@router.patch("/items/{item_id}")
def update_item(item_id: int, body: ItemPatch, _: str = User):
    with get_session() as s:
        item = _get(s, item_id)
        if item.status in ("published", "generating"):
            raise HTTPException(409, f"Item is {item.status} and can't be edited")
        if body.captions is not None:
            item.captions = body.captions
        if body.hashtags is not None:
            item.hashtags = " ".join(t if t.startswith("#") else f"#{t}" for t in body.hashtags.split())
        if body.platforms is not None:
            valid = [p for p in body.platforms if p in publishers.PLATFORMS]
            if not valid:
                raise HTTPException(400, "Pick at least one platform")
            item.platforms = ",".join(valid)
        s.commit()
        return serialize(item, full=True)


@router.post("/items/{item_id}/{action}")
def item_action(item_id: int, action: str, _: str = User):
    if action not in ACTIONS:
        raise HTTPException(404, "Unknown action")
    with get_session() as s:
        item = _get(s, item_id)
        if item.status in ("generating", "queued") and action not in ("reject", "stop"):
            raise HTTPException(409, "Still being made – wait until it's ready, or press Stop")
        if action == "approve":
            if item.status not in ("pending_approval", "rejected", "failed", "partial"):
                raise HTTPException(409, f"Can't approve an item that is {item.status}")
            item.status = "approved"
        elif action == "reject":
            item.status = "rejected"
        elif action == "check":
            if not item.media_path:
                raise HTTPException(409, "Nothing to check yet")
        elif action == "stop":
            if item.status not in ("generating", "queued"):
                raise HTTPException(409, "This item isn't being made")
            item.status, item.stage, item.progress, item.error = "rejected", "", 0, "Stopped by you"
        elif action == "regenerate":
            url, kind, notes, day = item.source_url, item.kind, item.notes, item.run_date
            if url:
                item.status, item.stage, item.progress = "generating", "Queued", 0
            else:
                item.status = "rejected"
        elif action == "publish":
            if item.status in ("published", "dry_run"):
                raise HTTPException(409, "Already published")
            if not item.media_path:
                raise HTTPException(409, "Nothing to publish yet")
            item.status = "approved"
        s.commit()
        result = serialize(item, full=True)

    if action == "check":
        return _run_check(item_id)
    if action == "regenerate":
        if url:
            _bg(pipeline.generate_from_url, url, kind, notes, None, item_id)
        else:
            _bg(pipeline.generate_for, day, kind, True, origin="regenerate", notes=notes)
    elif action == "publish":
        _bg(pipeline.publish_item, item_id)
    return result


# ── create ────────────────────────────────────────────────────────────────
class FromUrlIn(BaseModel):
    url: str = Field(min_length=4)
    kind: str = "video"
    notes: str = ""


@router.post("/from-url")
def from_url(body: FromUrlIn, _: str = User):
    if body.kind not in ("video", "post"):
        raise HTTPException(400, "kind must be video or post")
    item_id = pipeline.create_url_item(body.url, body.kind, body.notes.strip())
    _bg(pipeline.generate_from_url, body.url, body.kind, body.notes.strip(), None, item_id)
    return {"id": item_id}


class GenerateIn(BaseModel):
    date: str | None = None
    kind: str | None = None
    notes: str = Field("", max_length=1000)   # optional instructions ("prompt") from Generate now


@router.post("/generate")
def generate(body: GenerateIn, _: str = User):
    day = date.fromisoformat(body.date) if body.date else pipeline.today()
    kind = body.kind if body.kind in ("video", "post") else None
    if not kind and planner.kind_for(day) not in ("video", "post"):
        raise HTTPException(400, f"Nothing is scheduled on {day:%A} – pick video or post")
    _bg(pipeline.generate_for, day, kind, True, origin="manual", notes=body.notes.strip())
    return {"ok": True, "date": day.isoformat()}
