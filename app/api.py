"""JSON API used by the React dashboard (frontend/) — also handy for n8n / Super Agent."""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
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
DELETABLE = ("rejected", "failed", "outline")


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


def _metrics_summary(i: ContentItem) -> dict | None:
    m = i.metrics
    if not m:
        return None
    from . import insights
    return insights.totals(m)


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
        "publish_time": i.publish_time or "", "job": i.job or "",
        "deleted_at": i.deleted_at.isoformat() + "Z" if i.deleted_at else None,
        "missed": i.status == "approved" and i.run_date < pipeline.today() - timedelta(days=1),
        "metrics": _metrics_summary(i),
        "options": _options_summary(i),
    }
    if full:
        try:
            script = json.loads(i.script_json) if i.script_json else None
        except ValueError:
            script = i.script_json
        data.update(files=[f for f in (saved_as(i.media_path), saved_as(i.media_alt_path)) if f],
                    quality_report=i.quality, metrics_detail=i.metrics, editable=_editable(i), angle=i.angle, captions=i.captions, hashtags=i.hashtags, results=i.results, script=script,
                    previews={p: pipeline.full_caption(i, p) for p in i.platform_list} if i.captions else {})
    return data


def _options_summary(i: ContentItem) -> dict:
    o = i.options
    out = {k: o[k] for k in ("length", "outline", "series_part", "series_total", "series_of") if k in o}
    if o.get("screenshots"):
        out["screenshots"] = len(o["screenshots"])
    return out


def _editable(i: ContentItem) -> dict:
    """Which in-place editors are available for this item."""
    from . import storage
    poster = bool(i.kind == "post" and i.media_path and i.format != "simple"
                  and (storage.is_url(i.media_path) or (DATA_DIR / "media" / storage.poster_source_key(i.media_path)).exists()))
    video = bool(i.kind == "video" and i.format != "simple" and (i.media_path or (i.status == "outline" and i.options.get("outline_ref"))))
    return {"poster_text": poster, "video_scenes": video}


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


def _to_bin(item: ContentItem) -> None:
    if item.status not in DELETABLE:
        raise HTTPException(409, "Only rejected, stopped or failed items can be deleted")
    item.deleted_at = datetime.utcnow()


def _purge(s, item: ContentItem) -> None:
    if item.deleted_at is None:
        raise HTTPException(409, "Move it to the bin first")
    pipeline.delete_files(item)
    s.delete(item)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, forever: bool = False, _: str = User):
    """Moves a rejected/failed item to the bin (restorable for 7 days); forever=true empties it from the bin."""
    with get_session() as s:
        item = _get(s, item_id)
        if forever:
            _purge(s, item)
        else:
            _to_bin(item)
        s.commit()
    return {"ok": True}


@router.post("/items/delete-rejected")
def delete_rejected(_: str = User):
    with get_session() as s:
        items = s.scalars(select(ContentItem).where(ContentItem.status.in_(DELETABLE),
                                                    ContentItem.deleted_at.is_(None))).all()
        for item in items:
            _to_bin(item)
        s.commit()
    return {"deleted": len(items)}


@router.post("/items/{item_id}/restore")
def restore_item(item_id: int, _: str = User):
    with get_session() as s:
        item = _get(s, item_id)
        item.deleted_at = None
        s.commit()
        return serialize(item, full=True)


@router.post("/bin/empty")
def empty_bin(_: str = User):
    with get_session() as s:
        items = s.scalars(select(ContentItem).where(ContentItem.deleted_at.is_not(None))).all()
        for item in items:
            _purge(s, item)
        s.commit()
    return {"deleted": len(items)}


class BulkIn(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=200)
    action: str


@router.post("/items/bulk")
def bulk(body: BulkIn, _: str = User):
    """Approve / reject / delete / restore / delete-forever several items at once. Skips the ones that can't."""
    if body.action not in ("approve", "reject", "delete", "restore", "purge"):
        raise HTTPException(400, "Unknown action")
    done, skipped = [], []
    with get_session() as s:
        for item_id in body.ids:
            item = s.get(ContentItem, item_id)
            if not item:
                skipped.append({"id": item_id, "reason": "not found"})
                continue
            try:
                if body.action == "approve":
                    if item.status not in ("pending_approval", "rejected", "failed", "partial") or not item.media_path \
                            or item.deleted_at:
                        raise HTTPException(409, f"is {item.status}")
                    item.status = "approved"
                elif body.action == "reject":
                    if item.status not in ("pending_approval", "approved") or item.deleted_at:
                        raise HTTPException(409, f"is {item.status}")
                    item.status = "rejected"
                elif body.action == "delete":
                    _to_bin(item)
                elif body.action == "restore":
                    item.deleted_at = None
                else:
                    _purge(s, item)
                done.append(item_id)
            except HTTPException as e:
                skipped.append({"id": item_id, "reason": str(e.detail)})
        s.commit()
    return {"done": done, "skipped": skipped}


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
        counts = dict(s.execute(select(ContentItem.status, func.count()).where(ContentItem.deleted_at.is_(None))
                                .group_by(ContentItem.status)).all())
        counts["bin"] = s.scalar(select(func.count()).select_from(ContentItem).where(ContentItem.deleted_at.is_not(None))) or 0
        counts["missed"] = s.scalar(select(func.count()).select_from(ContentItem).where(
            ContentItem.status == "approved", ContentItem.deleted_at.is_(None),
            ContentItem.run_date < pipeline.today() - timedelta(days=1))) or 0
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
        "agent": {**pipeline.agent_state(), "active_today": not pipeline.agent_paused()},
        "setup_done": bool(settings().get("setup_done", True)),
    }


# ── results after posting ──────────────────────────────────────────────────
@router.get("/insights")
def get_insights(days: int = 30, _: str = User):
    from . import insights
    return insights.report(min(max(days, 7), 365))


@router.post("/insights/refresh")
def refresh_insights(days: int = 30, _: str = User):
    """Fetch the latest numbers for recent posts and let the AI write a new 'what worked best'."""
    from . import insights
    n = insights.refresh_recent(min(max(days, 7), 365))
    try:
        summary = insights.write_summary(days)
    except Exception as e:
        raise HTTPException(400, f"Numbers updated for {n} post(s), but the AI summary failed: {str(e)[:150]}")
    return {"refreshed": n, "summary": summary, "report": insights.report(days)}


class AgentIn(BaseModel):
    paused: bool
    paused_until: str = ""   # last paused day (YYYY-MM-DD); empty = until you resume


@router.put("/agent")
def set_agent(body: AgentIn, _: str = User):
    """Pause / resume all automatic work (preparing content and posting). Manual buttons keep working."""
    from .config import update_yaml
    until = body.paused_until.strip() if body.paused else ""
    if until:
        try:
            if date.fromisoformat(until) < pipeline.today():
                raise HTTPException(400, "Pick today or a later day")
        except ValueError:
            raise HTTPException(400, "paused_until must be YYYY-MM-DD")
    update_yaml("settings.yaml", {"agent": {"paused": body.paused, "paused_until": until}})
    return {**pipeline.agent_state(), "active_today": not pipeline.agent_paused()}


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
               limit: int = 60, offset: int = 0, bin: bool = False, _: str = User):
    with get_session() as s:
        query = select(ContentItem).where(ContentItem.deleted_at.is_not(None) if bin else ContentItem.deleted_at.is_(None))
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
    date: str | None = None            # move to another day (YYYY-MM-DD)
    publish_time: str | None = None    # "HH:MM", or "" for the default posting time


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
        if body.date is not None:
            try:
                new_day = date.fromisoformat(body.date)
            except ValueError:
                raise HTTPException(400, "date must be YYYY-MM-DD")
            if new_day < pipeline.today() and item.status in ("approved", "pending_approval"):
                raise HTTPException(400, "Pick today or a later day")
            item.run_date = new_day
        if body.publish_time is not None:
            t = body.publish_time.strip()
            if t and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
                raise HTTPException(400, "time must be HH:MM (24h), e.g. 18:00")
            item.publish_time = t
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
        if item.status == "publishing":
            raise HTTPException(409, "It's being posted right now – wait a moment")
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
            if item.job == "render":  # making a video from an outline: go back to the outline
                item.status, item.stage, item.progress, item.error, item.job = "outline", "", 0, "Stopped by you", ""
            else:
                item.status, item.stage, item.progress, item.error = "rejected", "", 0, "Stopped by you"
        elif action == "regenerate":
            url, kind, notes, day = item.source_url, item.kind, item.notes, item.run_date
            from_link = bool(url) or item.source == "prompt"
            if from_link:
                item.status, item.stage, item.progress = "generating", "Queued", 0
            else:
                item.status = "rejected"
        elif action == "publish":
            if item.status in ("published", "dry_run"):
                raise HTTPException(409, "Already published")
            if not item.media_path:
                raise HTTPException(409, "Nothing to publish yet")
            if item.status not in ("approved", "partial"):
                item.status = "approved"
        s.commit()
        if action == "publish":
            pipeline.claim_for_publishing(item_id)  # shows "Posting now…" immediately
            s.refresh(item)
        result = serialize(item, full=True)

    if action == "check":
        return _run_check(item_id)
    if action == "regenerate":
        if from_link:
            _bg(pipeline.generate_from_url, url, kind, notes, None, item_id)
        else:
            _bg(pipeline.generate_for, day, kind, True, origin="regenerate", notes=notes)
    elif action == "publish":
        _bg(pipeline.publish_item, item_id, claimed=True)
    return result


# ── create ────────────────────────────────────────────────────────────────
class ShotIn(BaseModel):
    ref: str = Field(min_length=4, max_length=600)
    caption: str = Field("", max_length=200)


class FromUrlIn(BaseModel):
    url: str = ""                  # optional: without a link the prompt (+ uploads) is the brief
    kind: str = "video"
    notes: str = Field("", max_length=8000)   # the prompt – can be long
    length: str = "short"          # video: short | full | series
    outline: bool = True           # video: show the scene outline first, render after "Make video"
    screenshots: list[ShotIn] = Field(default_factory=list, max_length=25)   # images and screen recordings


UPLOAD_KEY = re.compile(r"uploads/(shots/[0-9a-f]{32}\.(png|jpg)|recordings/[0-9a-f]{32}(\.(mp4|mov|webm|mkv)|/manifest\.json))$")
REC_MAX_MB, REC_MAX_S, REC_MAX = 600, 300, 5       # per recording: 600 MB, 5 minutes; up to 5 recordings
SHOTS_MAX = 25                                     # screenshots + recordings per item
REC_EXT = (".mp4", ".mov", ".webm", ".mkv")


@router.post("/uploads/screenshot")
async def upload_screenshot(file: UploadFile = File(...), _: str = User):
    """A screenshot for Create from URL (e.g. inside the app, behind a login). Returns {ref, url}."""
    import uuid
    from io import BytesIO
    from PIL import Image
    from . import storage
    data = await file.read()
    if len(data) > 10_000_000:
        raise HTTPException(400, "Screenshots must be under 10 MB")
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception:
        raise HTTPException(400, "That isn't an image – upload a PNG or JPG screenshot")
    if img.width < 300 or img.height < 200:
        raise HTTPException(400, "That image is too small – upload a real screenshot")
    if img.width > 2600:  # keep the files light
        img = img.resize((2600, round(img.height * 2600 / img.width)))
    key = f"uploads/shots/{uuid.uuid4().hex}"
    tmp = storage.WORK_DIR / "uploads"
    tmp.mkdir(parents=True, exist_ok=True)
    if img.mode in ("RGBA", "LA", "P"):
        key += ".png"
        img.convert("RGBA").save(tmp / Path(key).name, optimize=True)
    else:
        key += ".jpg"
        img.convert("RGB").save(tmp / Path(key).name, quality=90)
    ref = storage.save_file(tmp / Path(key).name, key)
    (tmp / Path(key).name).unlink(missing_ok=True)
    return {"ref": ref, "url": storage.web_url(ref), "w": img.width, "h": img.height}


# Screen recordings arrive in pieces (≤ 16 MB per request): no proxy/body limits, a progress bar, retries per piece,
# and no single file over Supabase's 50 MB per-file limit. The PC joins the pieces back into the original file.
REC_CHUNK = 16 << 20
REC_ID = re.compile(r"^[0-9a-f]{32}$")


class RecStartIn(BaseModel):
    name: str = Field(max_length=300)
    size: int = Field(gt=0)


@router.post("/uploads/recording/start")
def recording_start(body: RecStartIn, _: str = User):
    import uuid
    ext = Path(body.name).suffix.lower()
    if ext not in REC_EXT:
        raise HTTPException(400, "Upload an MP4, MOV, WebM or MKV screen recording")
    if body.size > REC_MAX_MB << 20:
        raise HTTPException(400, f"Recordings must be under {REC_MAX_MB} MB")
    return {"id": uuid.uuid4().hex, "ext": ext, "chunk_size": REC_CHUNK}


def _rec_dir(rec_id: str) -> Path:
    from . import storage
    if not REC_ID.match(rec_id):
        raise HTTPException(400, "Bad upload id")
    return storage.WORK_DIR / "uploads" / rec_id


@router.put("/uploads/recording/{rec_id}/{n}")
async def recording_part(rec_id: str, n: int, request: Request, _: str = User):
    from . import storage
    if not 0 <= n < (REC_MAX_MB << 20) // REC_CHUNK + 2:
        raise HTTPException(400, "Too many pieces")
    d = _rec_dir(rec_id)
    d.mkdir(parents=True, exist_ok=True)
    part, size = d / f"part{n:04d}", 0
    with open(part, "wb") as out:
        async for chunk in request.stream():
            size += len(chunk)
            if size > REC_CHUNK + (1 << 20):
                raise HTTPException(400, "Piece too big")
            out.write(chunk)
    key = f"uploads/recordings/{rec_id}/part{n:04d}"
    ref = storage.save_file(part, key)
    if storage.is_url(ref):  # in the cloud now – keep only the copy needed to check the whole file at the end
        (storage.MEDIA_DIR / key).unlink(missing_ok=True)
    return {"ok": True, "n": n, "size": size}


class RecFinishIn(BaseModel):
    parts: int = Field(gt=0, le=64)
    ext: str


@router.post("/uploads/recording/{rec_id}/finish")
def recording_finish(rec_id: str, body: RecFinishIn, _: str = User):
    """All pieces are in: check it's a readable video of the allowed length, then write its manifest."""
    import shutil
    import subprocess
    from . import storage
    from .generators import ffmpeg
    d = _rec_dir(rec_id)
    parts = [d / f"part{i:04d}" for i in range(body.parts)]
    if body.ext not in REC_EXT or not all(p.is_file() for p in parts):
        raise HTTPException(400, "Some pieces are missing – upload it again")
    try:
        size = sum(p.stat().st_size for p in parts)
        proc = subprocess.run([ffmpeg.FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json",
                               "concat:" + "|".join(str(p) for p in parts)], capture_output=True, text=True, timeout=120)
        try:
            secs = float(json.loads(proc.stdout)["format"]["duration"])
        except Exception:
            raise HTTPException(400, "That file isn't a video this agent can read")
        if secs > REC_MAX_S + 5:
            raise HTTPException(400, f"Recordings can be up to {REC_MAX_S // 60} minutes – this one is {int(secs // 60)}:{int(secs % 60):02d}")
        if secs < 2:
            raise HTTPException(400, "That recording is too short")
        man = d / "manifest.json"
        man.write_text(json.dumps({"ext": body.ext, "parts": body.parts, "size": size, "seconds": round(secs, 1)}))
        ref = storage.save_file(man, f"uploads/recordings/{rec_id}/manifest.json")
    except HTTPException:
        storage.delete_video_source(storage.remote_url("x") if storage.remote_enabled() else "", prefix=f"uploads/recordings/{rec_id}")
        raise
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return {"ref": ref, "url": "", "seconds": round(secs, 1)}


@router.post("/from-url")
def from_url(body: FromUrlIn, _: str = User):
    if body.kind not in ("video", "post"):
        raise HTTPException(400, "kind must be video or post")
    if body.length not in ("short", "full", "series"):
        raise HTTPException(400, "length must be short, full or series")
    shots = []
    for sh in body.screenshots:
        key = sh.ref.split("/storage/v1/object/public/", 1)[-1].split("/", 1)[-1] if sh.ref.startswith("http") \
            else sh.ref.replace("\\", "/")
        m = UPLOAD_KEY.search(key)
        if not m:  # only files that came from /uploads/screenshot
            raise HTTPException(400, "Unknown screenshot – upload it again")
        from . import storage
        ref = storage.remote_url(m.group(0)) if storage.remote_enabled() else str(MEDIA_DIR / m.group(0))
        shots.append({"ref": ref, "caption": sh.caption.strip(),
                      **({"video": True} if m.group(0).startswith("uploads/recordings/") else {})})
    if sum(1 for s in shots if s.get("video")) > REC_MAX:
        raise HTTPException(400, f"Up to {REC_MAX} screen recordings")
    url = body.url.strip()
    if url and not re.fullmatch(r"(https?://)?[\w.-]+(:\d+)?(/\S*)?", url):
        raise HTTPException(400, "That doesn't look like a website link")
    if not url and not body.notes.strip() and not shots:
        raise HTTPException(400, "Add a website link, a prompt, or some screenshots / recordings")
    if not url and not shots and body.kind == "video" and not (company().get("website") or "").strip():
        raise HTTPException(400, "For a video without a link, upload screenshots or a screen recording to show")
    if body.kind == "post" and any(s.get("video") for s in shots):
        raise HTTPException(400, "Screen recordings are for videos – for a post, add a screenshot")
    options = {"screenshots": shots} if shots else {}
    if body.kind == "video":
        options.update(length=body.length, outline=body.outline)
    item_id = pipeline.create_url_item(url, body.kind, body.notes.strip(), options)
    _bg(pipeline.generate_from_url, url, body.kind, body.notes.strip(), None, item_id)
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
