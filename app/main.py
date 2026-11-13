"""FastAPI app: approval dashboard + API + media hosting + scheduler."""
from __future__ import annotations

import asyncio
import logging
import secrets
import sys
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from . import pipeline, publishers, scheduler
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
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
security = HTTPBasic()


def auth(creds: HTTPBasicCredentials = Depends(security)) -> str:
    ok_user = secrets.compare_digest(creds.username, env("DASHBOARD_USER", "admin"))
    ok_pass = secrets.compare_digest(creds.password, env("DASHBOARD_PASSWORD", "change-me"))
    if not (ok_user and ok_pass):
        raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return creds.username


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


@app.get("/", response_class=HTMLResponse)
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


@app.get("/item/{item_id}", response_class=HTMLResponse)
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
@app.post("/generate")
def generate(day: str = Form(...), kind: str = Form("auto"), _: str = Depends(auth)):
    d = date.fromisoformat(day)
    _bg(pipeline.generate_for, d, None if kind == "auto" else kind, True)
    return RedirectResponse("/?msg=Generating+in+background+-+refresh+in+a+minute", 303)


@app.post("/from-url")
def from_url(url: str = Form(...), kind: str = Form("video"), notes: str = Form(""), _: str = Depends(auth)):
    if kind not in ("video", "post"):
        raise HTTPException(400, "kind must be video or post")
    _bg(pipeline.generate_from_url, url, kind, notes)
    return RedirectResponse("/?msg=Reading+the+website+and+creating+your+" + kind +
                            "+%E2%80%94+takes+1-3+minutes.+Refresh+to+see+it.", 303)


@app.post("/item/{item_id}/save")
async def save_item(item_id: int, request: Request, _: str = Depends(auth)):
    form = await request.form()
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        item.captions = {k[8:]: v for k, v in form.items() if k.startswith("caption_")}
        item.hashtags = form.get("hashtags", item.hashtags)
        item.platforms = ",".join(form.getlist("platforms")) or item.platforms
        s.commit()
    return RedirectResponse(f"/item/{item_id}", 303)


@app.post("/item/{item_id}/approve")
def approve(item_id: int, _: str = Depends(auth)):
    _set_status(item_id, "approved")
    return RedirectResponse(f"/item/{item_id}", 303)


@app.post("/item/{item_id}/reject")
def reject(item_id: int, _: str = Depends(auth)):
    _set_status(item_id, "rejected")
    return RedirectResponse(f"/item/{item_id}", 303)


@app.post("/item/{item_id}/regenerate")
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
    return RedirectResponse("/?msg=Regenerating+in+background", 303)


@app.post("/item/{item_id}/publish")
def publish_now(item_id: int, _: str = Depends(auth)):
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if item.status in ("pending_approval", "failed", "partial"):
            item.status = "approved"
            s.commit()
    _bg(pipeline.publish_item, item_id)
    return RedirectResponse(f"/item/{item_id}", 303)


@app.post("/schedule")
async def update_schedule(request: Request, _: str = Depends(auth)):
    form = await request.form()
    save_schedule({d: form.get(d, "none") for d in WEEKDAYS})
    return RedirectResponse("/?msg=Schedule+saved", 303)


def _set_status(item_id: int, status: str) -> None:
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if not item:
            raise HTTPException(404)
        item.status = status
        s.commit()


# ── JSON API (for Super Agent Platform / n8n integration) ─────────────────
@app.get("/api/items")
def api_items(status: str | None = None, _: str = Depends(auth)):
    with get_session() as s:
        q = select(ContentItem).order_by(ContentItem.id.desc()).limit(100)
        if status:
            q = q.where(ContentItem.status == status)
        return [{"id": i.id, "date": i.run_date.isoformat(), "kind": i.kind, "source": i.source,
                 "source_url": i.source_url, "topic": i.topic,
                 "status": i.status, "media": media_url(i.media_path), "captions": i.captions,
                 "results": i.results} for i in s.scalars(q).all()]


@app.post("/api/from-url")
def api_from_url(payload: dict, _: str = Depends(auth)):
    """{"url": "...", "kind": "video|post", "notes": "optional focus"} -> starts generation."""
    _bg(pipeline.generate_from_url, payload["url"], payload.get("kind", "video"), payload.get("notes", ""))
    return {"ok": True, "message": "generation started"}


@app.post("/api/items/{item_id}/approve")
def api_approve(item_id: int, _: str = Depends(auth)):
    _set_status(item_id, "approved")
    return {"ok": True}
