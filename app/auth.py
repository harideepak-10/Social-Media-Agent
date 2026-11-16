"""Dashboard auth: signed bearer tokens for the React app, HTTP Basic for the classic pages."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import CACHE_DIR, env

TOKEN_TTL = 14 * 24 * 3600
basic = HTTPBasic(auto_error=False)


def _secret() -> bytes:
    if env("SECRET_KEY"):
        return env("SECRET_KEY").encode()
    f = CACHE_DIR / "secret.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip().encode()


def check_password(username: str, password: str) -> bool:
    ok_user = secrets.compare_digest(username, env("DASHBOARD_USER", "admin"))
    ok_pass = secrets.compare_digest(password, env("DASHBOARD_PASSWORD", "change-me"))
    return ok_user and ok_pass


def make_token(username: str) -> str:
    payload = f"{username}|{int(time.time()) + TOKEN_TTL}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def read_token(token: str) -> str | None:
    try:
        user, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().rsplit("|", 2)
    except Exception:
        return None
    good = hmac.new(_secret(), f"{user}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good) or int(exp) < time.time():
        return None
    # a changed DASHBOARD_USER invalidates old tokens
    return user if user == env("DASHBOARD_USER", "admin") else None


def require_user(request: Request, creds: HTTPBasicCredentials | None = Depends(basic)) -> str:
    """Bearer token (React app) or HTTP Basic (classic pages / scripts / n8n)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        user = read_token(header[7:].strip())
        if user:
            return user
        raise HTTPException(401, "Session expired – please log in again")
    if creds and check_password(creds.username, creds.password):
        return creds.username
    raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Basic"})


def require_basic(creds: HTTPBasicCredentials | None = Depends(basic)) -> str:
    """Classic HTML pages: browser login prompt."""
    if creds and check_password(creds.username, creds.password):
        return creds.username
    raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Basic"})
