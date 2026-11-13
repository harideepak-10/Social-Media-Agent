"""Decides WHAT to talk about: festival, company event, trend, website feature — or any given URL."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from urllib.parse import urlparse

from .. import llm
from ..config import CACHE_DIR, company, settings
from ..db import last_source, recent_topics
from ..research import calendar, trends, website

log = logging.getLogger(__name__)

SYSTEM = (
    "You are a senior social media strategist for Indian businesses. You know what makes "
    "short-form content go viral on Instagram Reels, LinkedIn and Facebook: a strong hook in the first "
    "2 seconds, one clear idea, relatable pain points, curiosity, and a clear call to action. "
    "You never invent product features that are not on the website."
)


def kind_for(day: date) -> str:
    """video | post | none, from the weekly schedule.
    With `always_post_on_festivals`, a festival on a 'none' day still gets a greeting post."""
    kind = (settings().get("schedule") or {}).get(day.strftime("%A").lower(), "none")
    if kind == "none" and settings().get("always_post_on_festivals") and calendar.festivals_on(day):
        return "post"
    return kind


def _brand_block() -> str:
    c = company()
    return (
        f"COMPANY: {c.get('name')} — {c.get('tagline')}\nWEBSITE: {c.get('website')}\n"
        f"INDUSTRY: {c.get('industry')}\nAUDIENCE: {c.get('audience')}\nTONE: {c.get('tone')}"
    )


def _product_summary(product: dict | None) -> str:
    """Facts about the featured product (its page) + the company home page."""
    parts = []
    if product and product.get("url"):
        try:
            pages = website.crawl(product["url"], max_pages=1)
            if pages:
                p = pages[0]
                parts.append(f"PRODUCT PAGE {p['url']}\nTITLE: {p['title']}\nTEXT: {p['text'][:2500]}")
        except Exception as e:
            log.warning("product page read failed: %s", e)
    parts.append(website.summary(company().get("website"), max_chars=3500))
    return "\n\n".join(x for x in parts if x)


def plan(day: date, kind: str, product: dict | None = None) -> dict:
    """Return {source, topic, angle, hook, page_urls, context, product}."""
    festival = calendar.upcoming_festival(day)
    event = calendar.company_event(day)
    recent = recent_topics(20)
    snap = trends.snapshot()
    site = _product_summary(product)

    # Pick the source in priority order. Videos always explain the website,
    # optionally framed by a festival/trend; posts follow post_priority.
    source, context = "website", ""
    if kind == "post":
        for src in settings().get("post_priority", ["festival", "event", "trend", "website"]):
            if src == "festival" and festival:
                name, fdate = festival
                source, context = "festival", f"Festival/special day: {name} on {fdate:%d %b %Y}"
                break
            if src == "event" and event:
                source, context = "event", f"Company event: {event['title']} on {event['date']} ({event['days_left']} days left). Details: {event.get('details', '')}"
                break
            # alternate trend / website posts so the feed stays balanced
            if src == "trend" and (snap["trending_searches"] or snap["industry_news"]) and last_source("post") != "trend":
                source, context = "trend", "Use a trend below that genuinely relates to our business."
                break
            if src == "website":
                source = "website"
                break
    else:
        if festival:
            context = f"Optional festive framing: {festival[0]} is on {festival[1]:%d %b}."

    prompt = f"""{_brand_block()}

WEBSITE CONTENT:
{site or '(website could not be crawled — use the company info above)'}

{trends.as_text(snap)}

TODAY: {day:%A %d %B %Y}
CONTENT TYPE: {kind}  ({'30-45s vertical explainer video with voice-over showing the website' if kind == 'video' else 'single image post with caption'})
SOURCE CHOSEN: {source}
{context}
PRODUCT TO FEATURE: {(product or {}).get('name', 'any') } — {(product or {}).get('description', '')} {(product or {}).get('url', '')}
(For festival posts the product is optional — the greeting comes first.)

TOPICS USED RECENTLY (do not repeat): {recent or 'none'}

Plan today's {kind}. If the source is 'trend', pick the ONE trending topic or news item that best connects to what
the company offers and explain the connection. If 'website', pick one feature/service/benefit from the website.
For videos, choose 2-4 website pages (exact URLs from WEBSITE CONTENT) to show on screen.

Return JSON:
{{
  "topic": "short topic title",
  "angle": "1-2 sentences: the idea and why the audience will care / share it",
  "hook": "scroll-stopping first line (max 10 words)",
  "trend_used": "the trend/news item used or empty",
  "page_urls": ["https://..."]
}}"""
    data = llm.complete_json(prompt, SYSTEM)
    urls = [u for u in data.get("page_urls") or [] if isinstance(u, str) and u.startswith("http")]
    if product and product.get("url"):
        urls = [product["url"]] + [u for u in urls if u != product["url"]]
    if kind == "video" and not urls:
        urls = website.page_urls(company().get("website"))[:3] or [company().get("website")]
    return {
        "source": source,
        "topic": data.get("topic", "")[:300],
        "angle": data.get("angle", ""),
        "hook": data.get("hook", ""),
        "trend_used": data.get("trend_used", ""),
        "page_urls": urls,
        "context": context,
        "site_summary": site,
        "product": product,
    }


# ── "any website" mode ─────────────────────────────────────────────────────
def brand_for_url(url: str, force: bool = False) -> dict:
    """Work out the brand (name, tagline, audience, colours) of any website. Cached per URL."""
    from . import browser

    cache = CACHE_DIR / f"brand_{hashlib.md5(url.encode()).hexdigest()[:12]}.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        info = browser.brand_info(url)
    except browser.LoginRequired:
        raise
    except Exception as e:
        log.warning("brand detection failed for %s: %s", url, e)
        info = {"site_name": "", "title": "", "description": "",
                "brand_colors": settings().get("company", {}).get("brand_colors", {})}
    site = website.summary(url, max_chars=4000)
    if not site:
        raise RuntimeError(f"Could not read any content from {url} – check the link opens in a browser")
    prompt = f"""Website: {url}
Site name tag: {info['site_name']}
Page title: {info['title']}
Meta description: {info['description']}

WEBSITE CONTENT:
{site}

Identify this website's brand for a social media campaign. Return JSON:
{{"name": "brand / product name as customers know it",
  "tagline": "short tagline (from the site if it has one)",
  "industry": "what kind of business / product it is",
  "audience": "who the target customers are",
  "tone": "fitting voice for its social media",
  "call_to_action": "best CTA, e.g. 'Book a free demo at <site>'"}}"""
    data = llm.complete_json(prompt, SYSTEM, max_tokens=600)
    host = urlparse(url).netloc.replace("www.", "")
    brand = {
        "name": data.get("name") or info["site_name"] or host,
        "tagline": data.get("tagline", ""),
        "website": url,
        "industry": data.get("industry", ""),
        "audience": data.get("audience", ""),
        "tone": data.get("tone") or "Friendly, clear, modern",
        "call_to_action": data.get("call_to_action") or f"Visit {host}",
        "brand_colors": info["brand_colors"],
        "logo_path": "",
    }
    cache.write_text(json.dumps(brand, ensure_ascii=False, indent=2), encoding="utf-8")
    return brand


def plan_for_url(url: str, kind: str, day: date, notes: str = "") -> dict:
    """Plan a video/post about any website. `notes` = optional focus from the user."""
    site = website.summary(url)
    if not site:
        raise RuntimeError(f"Could not read any content from {url}")
    prompt = f"""{_brand_block()}

WEBSITE CONTENT:
{site}

TODAY: {day:%A %d %B %Y}
CONTENT TYPE: {kind}  ({'30-45s vertical explainer video with voice-over showing the website' if kind == 'video' else 'single image post with caption'})
USER'S FOCUS: {notes or '(none – choose the most compelling feature or overall value of the website)'}

Plan a {kind} that explains what this website/product does and why the audience should care.
For videos, choose 2-4 pages (exact URLs from WEBSITE CONTENT) that best SHOW the functionality on screen,
in a logical order (overview first, then features/how it works, then pricing/contact if useful).

Return JSON:
{{"topic": "short topic title", "angle": "1-2 sentences: the idea and why viewers will care",
  "hook": "scroll-stopping first line (max 10 words)", "page_urls": ["https://..."]}}"""
    data = llm.complete_json(prompt, SYSTEM)
    known = {u.rstrip("/"): u for u in website.page_urls(url)}
    urls = [known[u.rstrip("/")] for u in data.get("page_urls") or []
            if isinstance(u, str) and u.rstrip("/") in known] or list(known.values())[:3] or [url]
    return {"source": "url", "topic": data.get("topic", "")[:300], "angle": data.get("angle", ""),
            "hook": data.get("hook", ""), "trend_used": "", "page_urls": urls,
            "product": {"name": company().get("name", ""), "url": url, "description": company().get("tagline", "")},
            "context": f"User's focus: {notes}" if notes else "", "site_summary": site}
