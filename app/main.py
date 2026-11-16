"""FastAPI app: approval dashboard + API + media hosting + scheduler."""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from . import pipeline, publishers, scheduler
from .api import router as api_router
from .api_settings import public as brand_router
from .api_settings import router as settings_router
from .auth import require_basic
from .config import BASE_DIR, MEDIA_DIR, WEEKDAYS, env, save_schedule, settings
from .db import ContentItem, get_session, init_db
from .generators import planner
from .generators.browser import AUTH_STATE
from .research import calendar

if sys.platform == "win32":  # Playwright needs the Proactor loop for its browser subprocess on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if env("DISABLE_SCHEDULER", "").lower() not in ("1", "true", "yes"):
        scheduler.start()
    yield


app = FastAPI(title="Digital Marketing Agent", lifespan=lifespan)
# media must stay public: Instagram fetches images/videos from here
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.include_router(api_router)
app.include_router(settings_router)
app.include_router(brand_router)
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
classic = APIRouter(prefix="/classic")  # the simple server-rendered dashboard (works without Node/React)
auth = require_basic
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


def media_url(path: str) -> str:
    if not path:
        return ""
    try:
        return "/media/" + str(Path(path).resolve().relative_to(MEDIA_DIR.resolve()).as_posix())
    except ValueError:
        return ""


templates.env.globals["media_url"] = media_url


def _bg(fn, *args, **kw):
    threading.Thread(target=fn, args=args, kwargs=kw, daemon=True).start()


# ── pages ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"ok": True}


@classic.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: str = Depends(auth)):
    today = pipeline.today()
    week = []
    for i in range(7):
        d = today + timedelta(days=i)
        week.append({"date": d, "kind": planner.kind_for(d), "festivals": calendar.festivals_on(d),
                     "event": calendar.company_event(d)})
    with get_session() as s:
        items = s.scalars(select(ContentItem).order_by(ContentItem.run_date.desc(), ContentItem.id.desc()).limit(60)).all()
    return templates.TemplateResponse(request, "dashboard.html", {
        "week": week, "items": items, "platforms": publishers.status(),
        "upcoming": calendar.next_festivals(today, 45), "settings": settings(), "weekdays": WEEKDAYS,
        "login_needed": bool((settings().get("site") or {}).get("login_required")) and not AUTH_STATE.exists(),
    })


@classic.get("/item/{item_id}", response_class=HTMLResponse)
def item_page(request: Request, item_id: int, _: str = Depends(auth)):
    with get_session() as s:
        item = s.get(ContentItem, item_id)
    if not item:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "item.html", {
        "item": item, "captions": item.captions, "results": item.results,
        "previews": {p: pipeline.full_caption(item, p) for p in item.platform_list} if item.captions else {},
    })


# ── actions ───────────────────────────────────────────────────────────────
@classic.post("/generate")
def generate(day: str = Form(...), kind: str = Form("auto"), _: str = Depends(auth)):
    d = date.fromisoformat(day)
    _bg(pipeline.generate_for, d, None if kind == "auto" else kind, True)
    return RedirectResponse("/classic/?msg=Generating+in+background+-+refresh+in+a+minute", 303)


@classic.post("/from-url")
def from_url(url: str = Form(...), kind: str = Form("video"), notes: str = Form(""), _: str = Depends(auth)):
    if kind not in ("video", "post"):
        raise HTTPException(400, "kind must be video or post")
    _bg(pipeline.generate_from_url, url, kind, notes)
    return RedirectResponse("/classic/?msg=Reading+the+website+and+creating+your+" + kind +
                            "+%E2%80%94+takes+1-3+minutes.+Refresh+to+see+it.", 303)


@classic.post("/item/{item_id}/save")
async def save_item(item_id: int, request: Request, _: str = Depends(auth)):
    form = await request.form()
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        item.captions = {k[8:]: v for k, v in form.items() if k.startswith("caption_")}
        item.hashtags = form.get("hashtags", item.hashtags)
        item.platforms = ",".join(form.getlist("platforms")) or item.platforms
        s.commit()
    return RedirectResponse(f"/classic/item/{item_id}", 303)


@classic.post("/item/{item_id}/approve")
def approve(item_id: int, _: str = Depends(auth)):
    _set_status(item_id, "approved")
    return RedirectResponse(f"/classic/item/{item_id}", 303)


@classic.post("/item/{item_id}/reject")
def reject(item_id: int, _: str = Depends(auth)):
    _set_status(item_id, "rejected")
    return RedirectResponse(f"/classic/item/{item_id}", 303)


@classic.post("/item/{item_id}/regenerate")
def regenerate(item_id: int, _: str = Depends(auth)):
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if item.source_url:  # "any website" item: rebuild it in place
            url, kind, notes = item.source_url, item.kind, item.notes
        else:
            item.status = "rejected"
            day, kind = item.run_date, item.kind
        s.commit()
    if item.source_url:
        _bg(pipeline.generate_from_url, url, kind, notes, None, item_id)
    else:
        _bg(pipeline.generate_for, day, kind, True)
    return RedirectResponse("/classic/?msg=Regenerating+in+background", 303)


@classic.post("/item/{item_id}/publish")
def publish_now(item_id: int, _: str = Depends(auth)):
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if item.status in ("pending_approval", "failed", "partial"):
            item.status = "approved"
            s.commit()
    _bg(pipeline.publish_item, item_id)
    return RedirectResponse(f"/classic/item/{item_id}", 303)


@classic.post("/schedule")
async def update_schedule(request: Request, _: str = Depends(auth)):
    form = await request.form()
    save_schedule({d: form.get(d, "none") for d in WEEKDAYS})
    return RedirectResponse("/classic/?msg=Schedule+saved", 303)


def _set_status(item_id: int, status: str) -> None:
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if not item:
            raise HTTPException(404)
        item.status = status
        s.commit()


app.include_router(classic)


# ── React dashboard (frontend/dist, built with `npm run build`) ────────────
if (FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="spa-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "media/", "classic", "brand/")):
            raise HTTPException(404)
        f = FRONTEND_DIST / path
        if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/classic/")
