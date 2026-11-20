"""JSON API for the first-time setup wizard (company → logo → products → schedule → connections).

The wizard saves each step through the normal settings endpoints; this file only adds:
- POST /api/setup/analyze  – read a website and suggest company details, brand colours and products
- POST /api/setup/finish   – mark setup as done (the wizard stops opening by itself)
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, llm
from .config import update_yaml

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
User = Depends(auth.require_user)


class AnalyzeIn(BaseModel):
    website: str = Field(..., min_length=4, max_length=300)


@router.post("/setup/analyze")
def analyze(body: AnalyzeIn, _: str = User):
    from .generators import planner
    from .pipeline import _normalize_url
    from .research import website
    url = _normalize_url(body.website)
    try:
        brand = planner.brand_for_url(url, force=True)
    except Exception as e:
        raise HTTPException(400, f"Couldn't read {url}: {str(e)[:200]}")
    pages = website.crawl(url)
    page_lines = "\n".join(f"- {p['url']} | {p['title']} | {' / '.join(p['headings'][:4])}" for p in pages[:15])
    products: list[dict] = []
    try:
        data = llm.complete_json(
            f"Website {url} of '{brand['name']}' ({brand.get('industry', '')}). Its pages:\n{page_lines}\n\n"
            f"Site content:\n{website.summary(url, max_chars=3500)}\n\n"
            "List the main products or services it sells (max 8) – the things worth featuring in social media "
            "posts. Use the page that best shows each one. Return JSON {\"products\": [{\"name\": \"short name\", "
            "\"url\": \"exact page URL from the list\", \"description\": \"1 sentence: what it does and for whom\"}]}",
            "You are a marketing analyst.", max_tokens=1500)
        known = {p["url"] for p in pages}
        for p in (data.get("products") or [])[:8]:
            name = str(p.get("name", "")).strip()[:60]
            if len(name) < 2 or any(x["name"].lower() == name.lower() for x in products):
                continue
            link = str(p.get("url", "")).strip()
            products.append({"name": name, "url": link if link in known or link.startswith("http") else url,
                             "description": str(p.get("description", "")).strip()[:300]})
    except Exception as e:
        log.warning("product suggestions failed: %s", e)
    company = {k: brand.get(k, "") for k in ("name", "tagline", "website", "industry", "audience", "tone",
                                              "call_to_action")}
    return {"company": company, "brand_colors": brand.get("brand_colors") or {}, "products": products}


@router.post("/setup/finish")
def finish(_: str = User):
    update_yaml("settings.yaml", {"setup_done": True})
    return {"ok": True}


@router.post("/setup/restart")
def restart(_: str = User):
    """Open the wizard again (e.g. for a new brand or client)."""
    update_yaml("settings.yaml", {"setup_done": False})
    return {"ok": True}


__all__ = ["router", "json"]
