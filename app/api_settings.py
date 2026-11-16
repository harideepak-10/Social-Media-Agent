"""JSON API for the Schedule & calendar and Settings & status screens."""
from __future__ import annotations

import calendar as cal
import hashlib
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import auth, publishers, scheduler
from .config import ASSETS_DIR, CACHE_DIR, MEDIA_DIR, WEEKDAYS, env, events_config, settings, update_yaml
from .creative.catalog import POST_FORMATS, POST_THEMES, VIDEO_THEMES
from .db import ContentItem, get_session
from .generators import planner
from .research import calendar as festcal

router = APIRouter(prefix="/api")
public = APIRouter()
User = Depends(auth.require_user)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
KINDS = ("video", "post", "none")
VOICES = [
    {"id": "en-IN-PrabhatNeural", "label": "Prabhat – Indian English, male"},
    {"id": "en-IN-NeerjaNeural", "label": "Neerja – Indian English, female"},
    {"id": "en-US-GuyNeural", "label": "Guy – US English, male"},
    {"id": "en-US-AriaNeural", "label": "Aria – US English, female"},
    {"id": "en-US-JennyNeural", "label": "Jenny – US English, female"},
    {"id": "en-GB-RyanNeural", "label": "Ryan – British English, male"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia – British English, female"},
    {"id": "en-AU-WilliamNeural", "label": "William – Australian English, male"},
    {"id": "ta-IN-ValluvarNeural", "label": "Valluvar – Tamil, male"},
    {"id": "ta-IN-PallaviNeural", "label": "Pallavi – Tamil, female"},
    {"id": "hi-IN-MadhurNeural", "label": "Madhur – Hindi, male"},
    {"id": "hi-IN-SwaraNeural", "label": "Swara – Hindi, female"},
]


# ── schedule ──────────────────────────────────────────────────────────────
def _schedule_payload() -> dict:
    s = settings()
    return {
        "schedule": {d: (s.get("schedule") or {}).get(d, "none") for d in WEEKDAYS},
        "generate_time": s.get("generate_time", "18:00"),
        "publish_time": s.get("publish_time", "10:00"),
        "timezone": s.get("timezone", "Asia/Kolkata"),
        "always_post_on_festivals": bool(s.get("always_post_on_festivals", True)),
        "festival_lookahead_days": int(s.get("festival_lookahead_days", 1)),
        "post_priority": s.get("post_priority") or ["festival", "event", "trend", "website"],
        "next_runs": scheduler.next_runs(),
    }


@router.get("/schedule")
def get_schedule(_: str = User):
    return _schedule_payload()


class ScheduleIn(BaseModel):
    schedule: dict[str, str] | None = None
    generate_time: str | None = None
    publish_time: str | None = None
    always_post_on_festivals: bool | None = None
    festival_lookahead_days: int | None = Field(None, ge=0, le=3)
    post_priority: list[str] | None = None


@router.put("/schedule")
def put_schedule(body: ScheduleIn, _: str = User):
    patch: dict = {}
    if body.schedule is not None:
        if any(d not in WEEKDAYS or k not in KINDS for d, k in body.schedule.items()):
            raise HTTPException(400, "schedule values must be video, post or none")
        current = settings().get("schedule") or {}
        patch["schedule"] = {d: body.schedule.get(d, current.get(d, "none")) for d in WEEKDAYS}
    for key in ("generate_time", "publish_time"):
        v = getattr(body, key)
        if v is not None:
            if not TIME_RE.match(v):
                raise HTTPException(400, f"{key} must be HH:MM (24h)")
            patch[key] = v
    if body.always_post_on_festivals is not None:
        patch["always_post_on_festivals"] = body.always_post_on_festivals
    if body.festival_lookahead_days is not None:
        patch["festival_lookahead_days"] = body.festival_lookahead_days
    if body.post_priority is not None:
        allowed = {"festival", "event", "trend", "website"}
        if set(body.post_priority) - allowed or len(set(body.post_priority)) != len(body.post_priority):
            raise HTTPException(400, f"post_priority items must be unique and one of {sorted(allowed)}")
        patch["post_priority"] = body.post_priority
    if patch:
        update_yaml("settings.yaml", patch)
        if "generate_time" in patch:
            scheduler.reschedule()
    return _schedule_payload()


# ── calendar ──────────────────────────────────────────────────────────────
@router.get("/calendar")
def month_calendar(month: str | None = None, _: str = User):
    """Monday-first month grid: planned type, festivals, your events and content already made."""
    first = date.fromisoformat((month or date.today().strftime("%Y-%m")) + "-01")
    last = first.replace(day=cal.monthrange(first.year, first.month)[1])
    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=6 - last.weekday())
    with get_session() as s:
        rows = s.scalars(select(ContentItem).where(ContentItem.run_date.between(start, end),
                                                   ContentItem.status != "rejected")).all()
    by_day: dict[date, list] = {}
    for i in rows:
        by_day.setdefault(i.run_date, []).append(
            {"id": i.id, "kind": i.kind, "status": i.status, "topic": i.topic, "source_url": i.source_url,
             "thumb": _media_url(i.thumb_path)})
    events = _events()
    days, d = [], start
    while d <= end:
        days.append({
            "date": d.isoformat(), "in_month": d.month == first.month,
            "kind": planner.kind_for(d), "festivals": festcal.festivals_on(d),
            "events": [e for e in events if e["date"] == d.isoformat()],
            "items": by_day.get(d, []),
        })
        d += timedelta(days=1)
    return {"month": first.strftime("%Y-%m"), "days": days}


def _media_url(path: str) -> str:
    if not path:
        return ""
    try:
        return "/media/" + Path(path).resolve().relative_to(MEDIA_DIR.resolve()).as_posix()
    except ValueError:
        return ""


# ── events ────────────────────────────────────────────────────────────────
def _events() -> list[dict]:
    out = []
    for idx, e in enumerate(events_config().get("events") or []):
        out.append({"id": idx, "date": str(e.get("date", "")), "title": e.get("title", ""),
                    "details": e.get("details", ""), "remind_days_before": int(e.get("remind_days_before", 0))})
    return out


class EventIn(BaseModel):
    date: str
    title: str = Field(min_length=2, max_length=120)
    details: str = Field("", max_length=600)
    remind_days_before: int = Field(0, ge=0, le=14)


def _save_events(items: list[dict]) -> list[dict]:
    clean = [{"date": e["date"], "title": e["title"], "details": e.get("details", ""),
              "remind_days_before": int(e.get("remind_days_before", 0))}
             for e in sorted(items, key=lambda e: e["date"])]
    update_yaml("events.yaml", {"events": clean}, replace_keys=("events",))
    return _events()


def _valid_event(body: EventIn) -> dict:
    try:
        date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    return body.model_dump()


@router.get("/events")
def list_events(_: str = User):
    special = events_config().get("special_days") or {}
    return {"events": _events(), "special_days": [{"date": k, "name": v} for k, v in sorted(special.items())]}


@router.post("/events")
def add_event(body: EventIn, _: str = User):
    return {"events": _save_events(_events() + [_valid_event(body)])}


@router.put("/events/{idx}")
def edit_event(idx: int, body: EventIn, _: str = User):
    items = _events()
    if not 0 <= idx < len(items):
        raise HTTPException(404, "Event not found")
    items[idx] = _valid_event(body)
    return {"events": _save_events(items)}


@router.delete("/events/{idx}")
def delete_event(idx: int, _: str = User):
    items = _events()
    if not 0 <= idx < len(items):
        raise HTTPException(404, "Event not found")
    items.pop(idx)
    return {"events": _save_events(items)}


# ── settings ──────────────────────────────────────────────────────────────
@router.get("/settings")
def get_settings(_: str = User):
    s = settings()
    return {
        "company": s.get("company") or {},
        "products": s.get("products") or [],
        "video": s.get("video") or {},
        "post": s.get("post") or {},
        "creative": s.get("creative") or {},
        "catalog": {
            "post_formats": [{"id": k, "label": v["label"], "needs": sorted(v["needs"])} for k, v in POST_FORMATS.items()],
            "post_themes": [{"id": k, "label": v["label"], "bg": v["bg"], "surface": v["surface"], "ink": v["ink"],
                             "accent": v["accent"], "accent2": v["accent2"]} for k, v in POST_THEMES.items()],
            "video_themes": [{"id": k, "bg": v["bg"], "bg2": v["bg2"], "ink": v["ink"], "accent": v["accent"],
                              "accent2": v["accent2"]} for k, v in VIDEO_THEMES.items()],
            "voices": VOICES,
        },
        "engine": {
            "llm_provider": env("LLM_PROVIDER", "anthropic"),
            "model": env("ANTHROPIC_MODEL", "claude-haiku-4-5"),
            "design_model": env("ANTHROPIC_DESIGN_MODEL", env("ANTHROPIC_MODEL", "claude-haiku-4-5")),
            "image_provider": env("IMAGE_PROVIDER", "none"),
            "tts_provider": env("TTS_PROVIDER", "edge"),
            "anthropic_key": bool(env("ANTHROPIC_API_KEY")),
        },
    }


class Product(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    url: str = ""
    description: str = Field("", max_length=400)


class SettingsIn(BaseModel):
    company: dict | None = None
    products: list[Product] | None = None
    video: dict | None = None
    post: dict | None = None


COMPANY_KEYS = {"name", "tagline", "website", "industry", "audience", "tone", "call_to_action", "brand_colors"}
VIDEO_KEYS = {"formats", "max_seconds", "fps", "voiceover", "voice", "background_music", "themes"}
POST_KEYS = {"self_review", "formats", "themes"}


@router.put("/settings")
def put_settings(body: SettingsIn, _: str = User):
    patch: dict = {}
    if body.company is not None:
        bad = set(body.company) - COMPANY_KEYS
        if bad:
            raise HTTPException(400, f"unknown company fields: {sorted(bad)}")
        if body.company.get("website") and not str(body.company["website"]).startswith(("http://", "https://")):
            raise HTTPException(400, "website must start with http:// or https://")
        patch["company"] = body.company
    if body.products is not None:
        names = [p.name.strip() for p in body.products]
        if len(set(names)) != len(names):
            raise HTTPException(400, "product names must be unique")
        patch["products"] = [p.model_dump() for p in body.products]
    if body.video is not None:
        bad = set(body.video) - VIDEO_KEYS
        if bad:
            raise HTTPException(400, f"unknown video fields: {sorted(bad)}")
        v = dict(body.video)
        if "formats" in v and (not v["formats"] or set(v["formats"]) - {"landscape", "vertical"}):
            raise HTTPException(400, "video formats: pick landscape and/or vertical")
        if "themes" in v and (not v["themes"] or set(v["themes"]) - set(VIDEO_THEMES)):
            raise HTTPException(400, "pick at least one valid video look")
        if "max_seconds" in v and not 20 <= int(v["max_seconds"]) <= 180:
            raise HTTPException(400, "max_seconds must be between 20 and 180")
        patch["video"] = v
    if body.post is not None:
        bad = set(body.post) - POST_KEYS
        if bad:
            raise HTTPException(400, f"unknown post fields: {sorted(bad)}")
        p = dict(body.post)
        if "formats" in p and (len(p["formats"]) < 3 or set(p["formats"]) - set(POST_FORMATS)):
            raise HTTPException(400, "keep at least 3 valid post formats so posts don't repeat")
        if "themes" in p and (len(p["themes"]) < 2 or set(p["themes"]) - set(POST_THEMES)):
            raise HTTPException(400, "keep at least 2 valid post themes")
        patch["post"] = p
    if patch:
        update_yaml("settings.yaml", patch, replace_keys=("products",))
    return get_settings(_)


# ── brand assets ──────────────────────────────────────────────────────────
MUSIC_DIR = ASSETS_DIR / "music"


def _assets() -> dict:
    logo = ASSETS_DIR / "logo.png"
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "logo": f"/brand/logo.png?v={int(logo.stat().st_mtime)}" if logo.exists() else None,
        "music": [{"name": f.name, "size": f.stat().st_size, "url": f"/brand/music/{f.name}"}
                  for f in sorted(MUSIC_DIR.glob("*.mp3"))],
    }


@router.get("/assets")
def get_assets(_: str = User):
    return _assets()


@router.post("/assets/logo")
async def upload_logo(file: UploadFile = File(...), _: str = User):
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(400, "Logo must be under 5 MB")
    from io import BytesIO
    from PIL import Image
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception:
        raise HTTPException(400, "Upload a PNG (transparent background works best)")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    img.convert("RGBA").save(ASSETS_DIR / "logo.png")
    for d in CACHE_DIR.glob("logo_*"):  # rebuild light/dark variants on next use
        shutil.rmtree(d, ignore_errors=True)
    return _assets()


@router.post("/assets/music")
async def upload_music(file: UploadFile = File(...), _: str = User):
    name = re.sub(r"[^\w.\- ]", "", Path(file.filename or "track.mp3").name).strip() or "track.mp3"
    if not name.lower().endswith(".mp3"):
        raise HTTPException(400, "Upload .mp3 files")
    data = await file.read()
    if len(data) > 25_000_000:
        raise HTTPException(400, "Track must be under 25 MB")
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    (MUSIC_DIR / name).write_bytes(data)
    return _assets()


@router.delete("/assets/music/{name}")
def delete_music(name: str, _: str = User):
    f = MUSIC_DIR / Path(name).name
    if not f.is_file():
        raise HTTPException(404, "Track not found")
    f.unlink()
    return _assets()


@public.get("/brand/logo.png", include_in_schema=False)
def brand_logo():
    f = ASSETS_DIR / "logo.png"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


@public.get("/brand/music/{name}", include_in_schema=False)
def brand_music(name: str):
    f = MUSIC_DIR / Path(name).name
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/mpeg")


# ── voice preview & health ────────────────────────────────────────────────
class VoiceIn(BaseModel):
    voice: str
    text: str = Field("", max_length=300)


@router.post("/voice-preview")
def voice_preview(body: VoiceIn, _: str = User):
    from .generators import tts
    text = body.text.strip() or f"Hi! I'm the voice of {(settings().get('company') or {}).get('name', 'your brand')}. Book a free demo today."
    key = hashlib.md5(f"{body.voice}|{text}".encode()).hexdigest()[:12]
    out_dir = MEDIA_DIR / ".work" / "voice-previews"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{key}.mp3"
    if not out.exists():
        path, _secs = tts.speak(text, out_dir / key, voice=body.voice)
        if path != out:
            shutil.move(str(path), out)
    return {"url": _media_url(str(out))}


@router.get("/health")
def health(full: bool = False, _: str = User):
    from . import doctor
    return {"checks": doctor.checks(full), "platforms": publishers.status(), "next_runs": scheduler.next_runs()}
