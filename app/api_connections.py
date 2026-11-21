"""JSON API for Settings → Connections (Facebook Page, Instagram, LinkedIn Company Page)."""
from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import auth, connections

router = APIRouter(prefix="/api/connections")
User = Depends(auth.require_user)
PLATFORMS = ("instagram", "meta", "linkedin")


def _platform(p: str) -> str:
    if p not in PLATFORMS:
        raise HTTPException(404, "Unknown platform")
    return p


@router.get("")
def status(_: str = User):
    return connections.status()


class AppIn(BaseModel):
    id: str = Field(min_length=3, max_length=200)
    secret: str = Field(min_length=6, max_length=300)
    config_id: str = Field("", max_length=100)   # Instagram Unified login configuration


@router.put("/apps/{platform}")
def set_app(platform: str, body: AppIn, _: str = User):
    _platform(platform)
    data = {"id": body.id.strip(), "secret": body.secret.strip()}
    if platform == "instagram" and body.config_id.strip():
        data["config_id"] = body.config_id.strip()
    connections.save(f"{platform}_app", data)
    return connections.status()


@router.delete("/apps/{platform}")
def delete_app(platform: str, _: str = User):
    connections.delete(f"{_platform(platform)}_app")
    return connections.status()


@router.get("/{platform}/start")
def start(platform: str, _: str = User):
    """Returns the login URL; the dashboard sends the browser there."""
    try:
        url = {"meta": connections.meta_auth_url, "linkedin": connections.linkedin_auth_url,
               "instagram": connections.instagram_auth_url}[_platform(platform)]()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"url": url, "redirect_uri": connections.redirect_uri(platform)}


@router.get("/{platform}/callback", include_in_schema=False)
def callback(platform: str, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    """Facebook / LinkedIn send the browser back here after login (no dashboard token on this request,
    so it's protected by the signed `state` instead)."""
    _platform(platform)
    back = "/settings?tab=connections&platform=" + platform

    def done(result: str, msg: str = ""):
        return RedirectResponse(f"{back}&result={result}" + (f"&msg={quote(msg[:300])}" if msg else ""), 303)

    if error:
        return done("error", error_description or error)
    if not connections.check_state(state, platform):
        return done("error", "The login link expired or was not started from this dashboard. Please try again.")
    try:
        choices = {"meta": connections.meta_callback, "linkedin": connections.linkedin_callback,
                   "instagram": connections.instagram_callback}[platform](code)
    except Exception as e:
        return done("error", str(e))
    return done("ok" if len(choices) == 1 else "choose")


class SelectIn(BaseModel):
    id: str


@router.post("/{platform}/select")
def select(platform: str, body: SelectIn, _: str = User):
    try:
        if _platform(platform) == "meta":
            connections.meta_select(body.id)
        elif platform == "linkedin":
            connections.linkedin_select(body.id)
        else:
            connections.instagram_select(body.id)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return connections.status()


class MetaManualIn(BaseModel):
    page_id: str = Field(min_length=3)
    page_token: str = Field(min_length=20)
    ig_user_id: str = ""


class LinkedInManualIn(BaseModel):
    access_token: str = Field(min_length=20)
    org_id: str = Field(min_length=2)


@router.put("/meta/manual")
def meta_manual(body: MetaManualIn, _: str = User):
    try:
        connections.meta_manual(body.page_id.strip(), body.page_token.strip(), body.ig_user_id.strip())
    except Exception as e:
        raise HTTPException(400, f"Couldn't verify these details – {e}")
    return connections.status()


class InstagramManualIn(BaseModel):
    access_token: str = Field(min_length=20)


@router.put("/instagram/manual")
def instagram_manual(body: InstagramManualIn, _: str = User):
    try:
        connections.instagram_manual(body.access_token.strip())
    except Exception as e:
        raise HTTPException(400, f"Couldn't verify this token – {e}")
    return connections.status()


@router.put("/linkedin/manual")
def linkedin_manual(body: LinkedInManualIn, _: str = User):
    m = re.search(r"(\d{3,})", body.org_id)  # accepts the number, a URN or the Page admin URL
    if not m:
        raise HTTPException(400, "Couldn't find the Page ID – paste the number from linkedin.com/company/<ID>/admin")
    org = m.group(1)
    try:
        connections.linkedin_manual(body.access_token.strip(), org)
    except Exception as e:
        raise HTTPException(400, f"Couldn't verify these details – {e}")
    return connections.status()


@router.post("/{platform}/test")
def test(platform: str, _: str = User):
    try:
        return {"ok": True, "results": {"meta": connections.meta_test, "linkedin": connections.linkedin_test,
                                        "instagram": connections.instagram_test}[_platform(platform)]()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.delete("/{platform}")
def disconnect(platform: str, _: str = User):
    connections.delete(_platform(platform))
    connections.delete(f"{platform}_pending")
    return connections.status()
