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
from .. import occasions
from ..research import trends, website

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
    if kind == "none" and settings().get("always_post_on_festivals") and occasions.festive_for(day):
        return "post"  # only APPROVED festivals / special days
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


def _results_hint() -> str:
    from .. import insights
    return insights.planner_hint()


def plan(day: date, kind: str, product: dict | None = None, notes: str = "") -> dict:
    """Return {source, topic, angle, hook, page_urls, context, product}.
    notes: optional instructions typed by the user in "Generate now" – they come first."""
    fest = occasions.festive_for(day)        # approved festival / special day / accepted suggestion
    festival = (fest.name, date.fromisoformat(fest.date)) if fest else None
    event = occasions.event_for(day)         # your events (paused ones are skipped)
    recent = recent_topics(20)
    snap = trends.snapshot()
    site = _product_summary(product)

    # Pick the source in priority order. Videos always explain the website,
    # optionally framed by a festival/trend; posts follow post_priority.
    source, context = "website", ""
    notes = (notes or "").strip()
    if notes:
        source = "request"
        context = f"USER'S REQUEST (most important – follow it closely): {notes}"
        if festival and kind == "post":
            context += f"\n(For reference only: {festival[0]} is on {festival[1]:%d %b}.)"
    elif kind == "post":
        for src in settings().get("post_priority", ["festival", "event", "trend", "website"]):
            if src == "festival" and festival:
                name, fdate = festival
                source, context = "festival", f"Festival/special day: {name} on {fdate:%d %b %Y}"
                if fest.note:
                    context += f". Your note for this greeting: {fest.note}"
                if fest.kind == "suggestion" and fest.product:
                    context += f". Tie it gently to {fest.product}: {fest.reason}"
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
    elif festival:
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

{_results_hint()}

Plan today's {kind}. If the source is 'request', build the whole piece around the user's request above
(topic, angle and hook must follow it). If the source is 'trend', pick the ONE trending topic or news item that best connects to what
the company offers and explain the connection. If 'website', pick one feature/service/benefit from the website.
For videos, choose 2-4 website pages (exact URLs from WEBSITE CONTENT) to show on screen.

Return JSON:
{{
  "topic": "short topic title",
  "angle": "1-2 sentences: the idea and why the audience will care / share it",
  "hook": "scroll-stopping first line (max 10 words)",
  "trend_used": "the trend/news item used or empty",
  "page_urls": ["https://..."]{',' if source == 'request' else ''}
{'  "festival": "ONLY if the user asks for a festival / holiday / special-day greeting: its name (e.g. Diwali, Christmas, New Year), else empty"' if source == 'request' else ''}
}}"""
    data = llm.complete_json(prompt, SYSTEM)
    urls = [u for u in data.get("page_urls") or [] if isinstance(u, str) and u.startswith("http")]
    if product and product.get("url"):
        urls = [product["url"]] + [u for u in urls if u != product["url"]]
    if kind == "video" and not urls:
        urls = website.page_urls(company().get("website"))[:3] or [company().get("website")]
    greeting = ""
    if kind == "post":
        if source == "festival" and festival:
            greeting = festival[0]
        elif source == "request":
            greeting = str(data.get("festival") or "").strip()[:60]
    return {
        "source": source,
        "festival": greeting,                                    # post = festival greeting design
        "festive_frame": festival[0] if (festival and kind == "video" and not notes) else "",  # video opening
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
def brand_for_url(url: str, force: bool = False, knowledge: dict | None = None) -> dict:
    """Work out the brand (name, tagline, audience, colours) of any website. Cached per URL."""
    from . import browser

    key = hashlib.md5(url.encode()).hexdigest()[:12]
    cache = CACHE_DIR / f"brand_{key}.json"
    hero = CACHE_DIR / f"brand_{key}_hero.jpg"
    if cache.exists() and not force:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("design_v") == 2:  # older cache entries have no design system yet -> read the site again
            return cached
    try:
        info = browser.brand_info(url, hero=hero)
    except browser.LoginRequired:
        raise
    except Exception as e:
        log.warning("brand detection failed for %s: %s", url, e)
        info = {"site_name": "", "title": "", "description": "",
                "brand_colors": settings().get("company", {}).get("brand_colors", {}), "design": {}}
    if knowledge:
        from ..research import explorer
        site = explorer.as_text(knowledge, max_chars=4000)
    else:
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
        "design": info.get("design") or {},          # the site's own look: colours, fonts, buttons, radius
        "hero": str(hero) if hero.exists() else "",  # homepage screenshot the designer matches
        "design_v": 2,
    }
    cache.write_text(json.dumps(brand, ensure_ascii=False, indent=2), encoding="utf-8")
    return brand


PROMPT_MAX = 8000


def _prompt(notes: str) -> str:
    return (notes or "").strip()[:PROMPT_MAX]


def _context(notes: str) -> str:
    """The user's prompt travels with the plan into the storyboard / poster brief."""
    p = _prompt(notes)
    return f"\nUSER'S PROMPT (follow it closely – subject, audience, tone, what to show and say):\n{p}\n" if p else ""


def plan_from_prompt(kind: str, day: date, notes: str, uploads: list[dict] | None = None, length: str = "") -> dict:
    """"Create" without a website link: the user's prompt (+ their screenshots/recordings) is the brief, for our own brand."""
    shots = "\n".join(f"- {'screen recording' if u.get('video') else 'screenshot'}: {u.get('caption') or '(no caption)'}"
                       for u in uploads or [])
    prompt = f"""{_brand_block()}

TODAY: {day:%A %d %B %Y}
CONTENT TYPE: {kind}{f' ({length} walkthrough)' if kind == 'video' and length else ''}
USER'S PROMPT:
{_prompt(notes) or '(none – make the most compelling piece about our main product)'}

THE USER'S OWN SCREENSHOTS / RECORDINGS:
{shots or '(none)'}
TOPICS USED RECENTLY (do not repeat): {recent_topics(20) or 'none'}

Plan this {kind} from the prompt. Never invent features or numbers the prompt or brand info doesn't give.
Return JSON:
{{"topic": "short topic title", "angle": "1-2 sentences: the idea and why viewers will care",
  "hook": "scroll-stopping first line (max 10 words)",
  "story": ["{'one line per scene/beat' if kind == 'video' else 'the 2-4 points the post makes'}"]}}"""
    data = llm.complete_json(prompt, SYSTEM, max_tokens=1800)
    c = company()
    return {"source": "url", "topic": str(data.get("topic", ""))[:300] or "From your prompt", "angle": data.get("angle", ""),
            "hook": data.get("hook", ""), "trend_used": "", "page_urls": [],
            "story": [str(x)[:200] for x in data.get("story") or []][:10],
            "product": {"name": c.get("name", ""), "url": c.get("website", ""), "description": c.get("tagline", "")},
            "context": _context(notes), "pages_meta": [],
            "site_summary": f"ABOUT: {c.get('name', '')} – {c.get('tagline', '')}\n\nUSER'S PROMPT:\n{_prompt(notes)}"}


def plan_for_url(url: str, kind: str, day: date, notes: str = "", knowledge: dict | None = None,
                 length: str = "", focus_url: str = "") -> dict:
    """Plan a video/post about any website. `notes` = optional focus from the user.
    knowledge: the site explorer's notes on every page (explorer.explore) – the plan can use any page."""
    if knowledge:
        from ..research import explorer
        return _plan_from_knowledge(url, kind, day, notes, knowledge, explorer, length, focus_url)
    site = website.summary(url)
    if not site:
        raise RuntimeError(f"Could not read any content from {url}")
    prompt = f"""{_brand_block()}

WEBSITE CONTENT:
{site}

TODAY: {day:%A %d %B %Y}
CONTENT TYPE: {kind}  ({'30-45s vertical explainer video with voice-over showing the website' if kind == 'video' else 'single image post with caption'})
USER'S PROMPT: {_prompt(notes) or '(none – choose the most compelling feature or overall value of the website)'}

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
            "context": _context(notes), "site_summary": site}


def _plan_from_knowledge(url: str, kind: str, day: date, notes: str, k: dict, explorer, length: str = "",
                         focus_url: str = "") -> dict:
    """Plan with the WHOLE website understood: pick the pages that tell the story, in customer-journey order.
    length "full" = a long walkthrough (more pages); focus_url = one part of a series (that page only)."""
    focus_page = explorer.page_for(k, focus_url) if focus_url else None
    if focus_page:
        notes = (notes + " | " if notes else "") + f"This video is about ONE page only: {focus_page['name']} ({focus_page['url']})"
    site = explorer.as_text(k, max_chars=14000, focus=notes)
    used = recent_topics(20)
    n_pages = ("1" if focus_page else "5-8" if length == "full" else "3-6") if kind == "video" else "1-2"
    prompt = f"""{_brand_block()}

THE WEBSITE, PAGE BY PAGE (read by our site explorer):
{site}

TODAY: {day:%A %d %B %Y}
CONTENT TYPE: {kind}  ({'explainer video that walks through the product: its pages, how it works and the benefits' if kind == 'video' else 'single image post with caption'})
USER'S PROMPT: {_prompt(notes) or '(none – choose the most compelling story about the product)'}
TOPICS USED RECENTLY (do not repeat): {used or 'none'}

Plan a {kind}. Use the page notes above – not just the home page.
- Choose {n_pages} pages (exact URLs from above) that best tell the story{' in the order a new customer should see them: overview -> core features -> how it works -> proof/pricing' if kind == 'video' else ''}.
- If the user gave a prompt, it decides the subject, audience, tone and what to show – follow it closely and
  build around the pages that match it.
- Use the real workflow steps and benefits from the notes; never invent features or numbers.

Return JSON:
{{"topic": "short topic title", "angle": "1-2 sentences: the idea and why viewers will care",
  "hook": "scroll-stopping first line (max 10 words)", "page_urls": ["https://..."],
  "story": ["{'one line per scene/beat: which page and what it shows/explains' if kind == 'video' else 'the 2-4 points the post makes'}"]}}"""
    data = llm.complete_json(prompt, SYSTEM, max_tokens=1800)
    known = {explorer._norm(p["url"]): p["url"] for p in k["pages"]}
    urls = [known[explorer._norm(u)] for u in data.get("page_urls") or []
            if isinstance(u, str) and explorer._norm(u) in known]
    if not urls:  # fall back to the most important pages
        urls = [p["url"] for p in sorted(k["pages"], key=lambda p: -p["importance"])][:4 if kind == "video" else 1]
    if focus_page:
        urls = [focus_page["url"]]
    chosen = [explorer.page_for(k, u) for u in urls]
    facts = "\n\n".join(
        f"PAGE {p['name']} ({p['url']}): {p['purpose']}\nFeatures: {'; '.join(p['features'])}\n"
        f"How it works: {' -> '.join(p['workflow'])}\nBenefits: {'; '.join(p['benefits'])}\n"
        f"Numbers: {'; '.join(p['numbers'])}\nText: {p['text'][:900]}" for p in chosen if p)
    overview = (k.get("overview") or {}).get("what", "")
    return {"source": "url", "topic": data.get("topic", "")[:300], "angle": data.get("angle", ""),
            "hook": data.get("hook", ""), "trend_used": "", "page_urls": urls,
            "story": [str(x)[:200] for x in data.get("story") or []][:10],
            "product": {"name": company().get("name", ""), "url": urls[0], "description": overview or company().get("tagline", "")},
            "context": _context(notes),
            "pages_meta": [{"url": p["url"], "name": p["name"]} for p in chosen if p],
            "site_summary": (f"ABOUT: {overview}\n\n" if overview else "") + facts}


def series_pages(k: dict, n: int = 5) -> list[dict]:
    """The pages a "Series" covers (one short Reel each): the customer journey first, then by importance;
    no legal/login/blog pages."""
    skip = {"blog", "careers", "contact", "docs", "other"}
    good = [p for p in k["pages"] if str(p.get("type", "")).lower() not in skip and p.get("importance", 0) >= 3]
    journey = (k.get("overview") or {}).get("journey") or []
    order = {name: i for i, name in enumerate(journey)}
    good.sort(key=lambda p: (order.get(p["name"], 99), -p.get("importance", 0)))
    return good[:n]
