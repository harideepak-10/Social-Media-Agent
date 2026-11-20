"""Social account connections (Facebook Page + Instagram via Meta, LinkedIn Company Page).

Connect from the dashboard (Settings → Connections):
  * "Connect with Facebook / LinkedIn" – OAuth using your own developer app (App ID + secret entered once), or
  * paste tokens manually.
Everything is stored encrypted in the database (key = SECRET_KEY or .cache/secret.key).
Values in .env (META_PAGE_ID, LINKEDIN_ACCESS_TOKEN, …) still work as a fallback.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .config import env
from .db import Connection, get_session

META_SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "instagram_basic",
               "instagram_content_publish", "business_management",
               "read_insights", "instagram_manage_insights"]   # reach / views on the Results page
LINKEDIN_SCOPES = ["w_organization_social", "r_organization_social", "rw_organization_admin"]


# ── endpoints (overridable for testing) ────────────────────────────────────
def graph_base() -> str:
    return f"{env('META_GRAPH_BASE', 'https://graph.facebook.com').rstrip('/')}/{env('META_GRAPH_VERSION', 'v21.0')}"


def graph_video_base() -> str:
    default = env("META_GRAPH_BASE", "https://graph-video.facebook.com").replace("graph.facebook", "graph-video.facebook")
    return f"{default.rstrip('/')}/{env('META_GRAPH_VERSION', 'v21.0')}"


def fb_dialog_base() -> str:
    return env("META_DIALOG_BASE", "https://www.facebook.com").rstrip("/")


def li_oauth_base() -> str:
    return env("LINKEDIN_OAUTH_BASE", "https://www.linkedin.com/oauth/v2").rstrip("/")


def li_api_base() -> str:
    return env("LINKEDIN_API_BASE", "https://api.linkedin.com/rest").rstrip("/")


def li_version() -> str:
    return env("LINKEDIN_API_VERSION", "202510")


# ── encrypted storage ──────────────────────────────────────────────────────
def _fernet() -> Fernet:
    from .auth import _secret
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"connections|" + _secret()).digest()))


def get(key: str) -> dict | None:
    with get_session() as s:
        row = s.get(Connection, key)
        if not row or not row.data:
            return None
    try:
        return json.loads(_fernet().decrypt(row.data.encode()).decode())
    except (InvalidToken, ValueError):
        return None  # secret key changed – reconnect needed


def save(key: str, data: dict) -> None:
    token = _fernet().encrypt(json.dumps(data).encode()).decode()
    with get_session() as s:
        row = s.get(Connection, key)
        if row:
            row.data = token
        else:
            s.add(Connection(key=key, data=token))
        s.commit()


def delete(key: str) -> None:
    with get_session() as s:
        row = s.get(Connection, key)
        if row:
            s.delete(row)
            s.commit()


# ── credentials used by the publishers ─────────────────────────────────────
def meta_creds() -> dict:
    c = get("meta")
    if c and c.get("page_token"):
        return {**c, "source": "dashboard"}
    if env("META_PAGE_ACCESS_TOKEN"):
        return {"page_id": env("META_PAGE_ID"), "page_token": env("META_PAGE_ACCESS_TOKEN"),
                "ig_user_id": env("META_IG_USER_ID"), "page_name": "", "ig_username": "", "source": "env"}
    return {}


def linkedin_creds() -> dict:
    c = get("linkedin")
    if c and c.get("access_token"):
        return {**c, "source": "dashboard"}
    if env("LINKEDIN_ACCESS_TOKEN"):
        return {"access_token": env("LINKEDIN_ACCESS_TOKEN"), "org_id": env("LINKEDIN_ORG_ID"),
                "org_name": "", "expires_at": None, "source": "env"}
    return {}


def app_creds(platform: str) -> dict:
    c = get(f"{platform}_app") or {}
    if platform == "meta":
        return {"id": c.get("id") or env("META_APP_ID"), "secret": c.get("secret") or env("META_APP_SECRET")}
    return {"id": c.get("id") or env("LINKEDIN_CLIENT_ID"), "secret": c.get("secret") or env("LINKEDIN_CLIENT_SECRET")}


def redirect_uri(platform: str) -> str:
    return f"{env('PUBLIC_BASE_URL', 'http://localhost:8000').rstrip('/')}/api/connections/{platform}/callback"


# ── OAuth state (signed, 15 min) ───────────────────────────────────────────
def make_state(platform: str) -> str:
    from .auth import _secret
    payload = f"{platform}|{int(time.time()) + 900}|{secrets.token_hex(8)}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def check_state(state: str, platform: str) -> bool:
    from .auth import _secret
    try:
        plat, exp, nonce, sig = base64.urlsafe_b64decode(state.encode()).decode().split("|")
    except Exception:
        return False
    good = hmac.new(_secret(), f"{plat}|{exp}|{nonce}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, good) and plat == platform and int(exp) > time.time()


def _ok(r: httpx.Response, what: str) -> dict:
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        err = data.get("error") if isinstance(data, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else data.get("error_description") or err) or r.text[:200]
        raise RuntimeError(f"{what}: {msg}")
    return data


# ── Meta (Facebook Page + Instagram) ──────────────────────────────────────
def meta_auth_url() -> str:
    app = app_creds("meta")
    if not app["id"]:
        raise RuntimeError("Add your Meta App ID and secret first")
    q = {"client_id": app["id"], "redirect_uri": redirect_uri("meta"), "state": make_state("meta"),
         "scope": ",".join(META_SCOPES), "response_type": "code"}
    return f"{fb_dialog_base()}/{env('META_GRAPH_VERSION', 'v21.0')}/dialog/oauth?{urlencode(q)}"


def meta_callback(code: str) -> list[dict]:
    """Exchange the code → long-lived user token → list the Pages you manage (with their IG accounts)."""
    app = app_creds("meta")
    with httpx.Client(timeout=60) as c:
        short = _ok(c.get(f"{graph_base()}/oauth/access_token", params={
            "client_id": app["id"], "client_secret": app["secret"], "redirect_uri": redirect_uri("meta"),
            "code": code}), "Facebook login")["access_token"]
        long = _ok(c.get(f"{graph_base()}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": app["id"], "client_secret": app["secret"],
            "fb_exchange_token": short}), "Facebook token exchange")["access_token"]
        pages = _ok(c.get(f"{graph_base()}/me/accounts", params={
            "access_token": long, "limit": 100,
            "fields": "id,name,access_token,picture{url},instagram_business_account{id,username}"}),
            "Facebook pages").get("data", [])
    choices = [{"id": p["id"], "name": p.get("name", ""), "token": p.get("access_token", ""),
                "picture": ((p.get("picture") or {}).get("data") or {}).get("url", ""),
                "ig_user_id": (p.get("instagram_business_account") or {}).get("id", ""),
                "ig_username": (p.get("instagram_business_account") or {}).get("username", "")} for p in pages]
    if not choices:
        raise RuntimeError("No Facebook Pages found – make sure you are an admin of the company Page "
                           "and allowed access to it in the login window")
    save("meta_pending", {"choices": choices, "at": int(time.time())})
    if len(choices) == 1:
        meta_select(choices[0]["id"])
    return choices


def meta_select(page_id: str) -> dict:
    pending = (get("meta_pending") or {}).get("choices") or []
    page = next((p for p in pending if p["id"] == page_id), None)
    if not page:
        raise RuntimeError("That Page isn't in the list – connect again")
    data = {"page_id": page["id"], "page_name": page["name"], "page_token": page["token"],
            "picture": page.get("picture", ""), "ig_user_id": page["ig_user_id"],
            "ig_username": page["ig_username"], "connected_at": int(time.time()), "method": "oauth"}
    save("meta", data)
    delete("meta_pending")
    return data


def meta_manual(page_id: str, page_token: str, ig_user_id: str = "") -> dict:
    info = meta_lookup(page_id, page_token)
    data = {"page_id": page_id, "page_name": info["name"], "page_token": page_token, "picture": info["picture"],
            "ig_user_id": ig_user_id or info["ig_user_id"], "ig_username": info["ig_username"],
            "connected_at": int(time.time()), "method": "manual"}
    if ig_user_id and ig_user_id != info["ig_user_id"]:
        data["ig_username"] = ""
    save("meta", data)
    return data


def meta_lookup(page_id: str, token: str) -> dict:
    with httpx.Client(timeout=30) as c:
        p = _ok(c.get(f"{graph_base()}/{page_id}", params={
            "access_token": token, "fields": "id,name,picture{url},instagram_business_account{id,username}"}),
            "Facebook Page")
    ig = p.get("instagram_business_account") or {}
    return {"name": p.get("name", ""), "picture": ((p.get("picture") or {}).get("data") or {}).get("url", ""),
            "ig_user_id": ig.get("id", ""), "ig_username": ig.get("username", "")}


def meta_test() -> dict:
    c = meta_creds()
    if not c:
        raise RuntimeError("Not connected")
    info = meta_lookup(c["page_id"], c["page_token"])
    out = {"facebook": f"Page “{info['name']}” – ready to post"}
    if c.get("ig_user_id"):
        with httpx.Client(timeout=30) as h:
            ig = _ok(h.get(f"{graph_base()}/{c['ig_user_id']}", params={
                "access_token": c["page_token"], "fields": "username"}), "Instagram account")
        out["instagram"] = f"@{ig.get('username', '?')} – ready to post"
    else:
        out["instagram"] = "No Instagram Business account linked to this Page"
    return out


# ── LinkedIn (Company Page) ───────────────────────────────────────────────
def _li_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "LinkedIn-Version": li_version(), "X-Restli-Protocol-Version": "2.0.0"}


def linkedin_auth_url() -> str:
    app = app_creds("linkedin")
    if not app["id"]:
        raise RuntimeError("Add your LinkedIn Client ID and secret first")
    q = {"response_type": "code", "client_id": app["id"], "redirect_uri": redirect_uri("linkedin"),
         "state": make_state("linkedin"), "scope": " ".join(LINKEDIN_SCOPES)}
    return f"{li_oauth_base()}/authorization?{urlencode(q)}"


def _li_orgs(token: str) -> list[dict]:
    with httpx.Client(timeout=60) as c:
        acls = _ok(c.get(f"{li_api_base()}/organizationAcls", headers=_li_headers(token),
                         params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"}),
                   "LinkedIn pages").get("elements", [])
        out = []
        for a in acls:
            urn = a.get("organization") or a.get("organizationTarget") or ""
            oid = urn.rsplit(":", 1)[-1]
            if not oid:
                continue
            try:
                org = _ok(c.get(f"{li_api_base()}/organizations/{oid}", headers=_li_headers(token)), "LinkedIn page")
                name = org.get("localizedName") or (org.get("name") or {}).get("localized", {}).get("en_US", "")
            except RuntimeError:
                name = ""
            out.append({"id": oid, "name": name or f"Organization {oid}"})
    return out


def linkedin_callback(code: str) -> list[dict]:
    app = app_creds("linkedin")
    with httpx.Client(timeout=60) as c:
        tok = _ok(c.post(f"{li_oauth_base()}/accessToken", data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri("linkedin"),
            "client_id": app["id"], "client_secret": app["secret"]}), "LinkedIn login")
    token = tok["access_token"]
    meta = {"access_token": token, "expires_at": int(time.time()) + int(tok.get("expires_in", 5184000)),
            "refresh_token": tok.get("refresh_token", ""),
            "refresh_expires_at": int(time.time()) + int(tok.get("refresh_token_expires_in", 0) or 0) or None}
    orgs = _li_orgs(token)
    if not orgs:
        raise RuntimeError("No LinkedIn Company Pages found where you are an admin")
    save("linkedin_pending", {**meta, "choices": orgs})
    if len(orgs) == 1:
        linkedin_select(orgs[0]["id"])
    return orgs


def linkedin_select(org_id: str) -> dict:
    pending = get("linkedin_pending") or {}
    org = next((o for o in pending.get("choices", []) if o["id"] == org_id), None)
    if not org:
        raise RuntimeError("That Page isn't in the list – connect again")
    data = {k: pending.get(k) for k in ("access_token", "expires_at", "refresh_token", "refresh_expires_at")}
    data.update(org_id=org["id"], org_name=org["name"], connected_at=int(time.time()), method="oauth")
    save("linkedin", data)
    delete("linkedin_pending")
    return data


def linkedin_manual(access_token: str, org_id: str) -> dict:
    with httpx.Client(timeout=30) as c:
        org = _ok(c.get(f"{li_api_base()}/organizations/{org_id}", headers=_li_headers(access_token)), "LinkedIn page")
    data = {"access_token": access_token, "org_id": org_id, "org_name": org.get("localizedName", f"Organization {org_id}"),
            "expires_at": int(time.time()) + 60 * 86400, "refresh_token": "", "connected_at": int(time.time()),
            "method": "manual"}
    save("linkedin", data)
    return data


def linkedin_refresh_if_needed() -> None:
    """LinkedIn tokens last 60 days – refresh automatically a week before expiry when possible."""
    c = get("linkedin")
    if not c or not c.get("refresh_token") or not c.get("expires_at") or c["expires_at"] - time.time() > 7 * 86400:
        return
    app = app_creds("linkedin")
    with httpx.Client(timeout=60) as h:
        tok = _ok(h.post(f"{li_oauth_base()}/accessToken", data={
            "grant_type": "refresh_token", "refresh_token": c["refresh_token"],
            "client_id": app["id"], "client_secret": app["secret"]}), "LinkedIn token refresh")
    c.update(access_token=tok["access_token"], expires_at=int(time.time()) + int(tok.get("expires_in", 5184000)),
             refresh_token=tok.get("refresh_token", c["refresh_token"]))
    save("linkedin", c)


def linkedin_test() -> dict:
    c = linkedin_creds()
    if not c:
        raise RuntimeError("Not connected")
    with httpx.Client(timeout=30) as h:
        org = _ok(h.get(f"{li_api_base()}/organizations/{c['org_id']}", headers=_li_headers(c["access_token"])),
                  "LinkedIn page")
    return {"linkedin": f"Page “{org.get('localizedName', c['org_id'])}” – ready to post"}


# ── overview for the dashboard ────────────────────────────────────────────
def status() -> dict:
    m, l = meta_creds(), linkedin_creds()
    now = time.time()
    li_exp = l.get("expires_at")
    return {
        "public_url": env("PUBLIC_BASE_URL", "http://localhost:8000"),
        "meta": {
            "app_configured": bool(app_creds("meta")["id"] and app_creds("meta")["secret"]),
            "app_id": app_creds("meta")["id"] or "",
            "redirect_uri": redirect_uri("meta"),
            "connected": bool(m), "source": m.get("source", ""), "method": m.get("method", ""),
            "page_id": m.get("page_id", ""), "page_name": m.get("page_name", ""), "picture": m.get("picture", ""),
            "ig_user_id": m.get("ig_user_id", ""), "ig_username": m.get("ig_username", ""),
            "connected_at": m.get("connected_at"),
            "pending_choices": [{k: p[k] for k in ("id", "name", "picture", "ig_username")}
                                for p in (get("meta_pending") or {}).get("choices", [])],
        },
        "linkedin": {
            "app_configured": bool(app_creds("linkedin")["id"] and app_creds("linkedin")["secret"]),
            "app_id": app_creds("linkedin")["id"] or "",
            "redirect_uri": redirect_uri("linkedin"),
            "connected": bool(l), "source": l.get("source", ""), "method": l.get("method", ""),
            "org_id": l.get("org_id", ""), "org_name": l.get("org_name", ""),
            "expires_at": li_exp, "expires_in_days": int((li_exp - now) / 86400) if li_exp else None,
            "auto_refresh": bool(l.get("refresh_token")), "connected_at": l.get("connected_at"),
            "pending_choices": (get("linkedin_pending") or {}).get("choices", []),
        },
    }
