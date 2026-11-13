"""Reads any website (static or JavaScript app) and builds a compact knowledge summary of its pages.

- Your own site (company.website in settings.yaml) uses `showcase_pages` and the `site:` options.
- Any other URL is auto-detected: plain HTML is fetched directly, JS apps (React/Vue/Angular) are read
  with a real browser.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import CACHE_DIR, settings

log = logging.getLogger(__name__)
CACHE_TTL = 24 * 3600
SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".mp4", ".webp", ".css", ".js", ".xml")
SKIP_WORDS = ("login", "signin", "sign-in", "signup", "sign-up", "register", "logout", "privacy", "terms",
              "cookie", "cart", "checkout", "wp-admin", "wp-login", "/tag/", "/author/", "mailto:", "tel:")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"}


def own_site() -> str:
    return (settings().get("company") or {}).get("website", "")


def is_own(url: str) -> bool:
    return bool(own_site()) and urlparse(url).netloc == urlparse(own_site()).netloc


def _cache_file(start_url: str):
    return CACHE_DIR / f"site_{hashlib.md5(start_url.encode()).hexdigest()[:12]}.json"


def _extract(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    meta = soup.find("meta", attrs={"name": "description"})
    headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])][:20]
    text = " ".join(soup.get_text(" ", strip=True).split())
    links = [urldefrag(urljoin(url, a["href"]))[0] for a in soup.find_all("a", href=True)]
    return {"url": url, "title": title, "description": (meta.get("content", "") if meta else "").strip(),
            "headings": [h for h in headings if h], "text": text[:2500], "links": links}


def _good_link(link: str, domain: str, seen: set) -> bool:
    low = link.lower()
    return (urlparse(link).netloc == domain and link not in seen and not low.endswith(SKIP_EXT)
            and not any(w in low for w in SKIP_WORDS))


def _rank(links: list[str]) -> list[str]:
    """Shallow, short paths first (main menu pages: /features, /pricing …) before deep ones."""
    uniq = list(dict.fromkeys(l.rstrip("/") for l in links))
    return sorted(uniq, key=lambda l: (urlparse(l).path.count("/"), len(urlparse(l).path)))


def needs_browser(start_url: str) -> bool:
    """True if the page is a JS app (little or no text in the raw HTML)."""
    if is_own(start_url) and (settings().get("site") or {}).get("render_js"):
        return True
    try:
        r = httpx.get(start_url, headers=UA, follow_redirects=True, timeout=25)
        if "text/html" not in r.headers.get("content-type", ""):
            return True
        page = _extract(r.text, str(r.url))
        return len(page["text"]) < 250 or (len(page["headings"]) == 0 and len(page["links"]) < 3)
    except httpx.HTTPError:
        return True


def _crawl_js(start_url: str, max_pages: int) -> list[dict]:
    from ..generators import browser

    configured = (settings().get("showcase_pages") or []) if is_own(start_url) else []
    if is_own(start_url):
        browser.warmup()
    names = {p["url"]: p for p in configured}
    queue = [p["url"] for p in configured] or [start_url]
    domain = urlparse(start_url).netloc
    seen, pages = set(), []
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            title, text, links = browser.page_text(url)
        except browser.LoginRequired:
            if not pages:
                raise
            continue
        except Exception as e:
            log.warning("js crawl failed %s: %s", url, e)
            continue
        info = names.get(url, {})
        pages.append({"url": url, "title": info.get("name") or title, "description": info.get("description", ""),
                      "headings": [], "text": " ".join(text.split())[:2500]})
        if not configured:
            queue += [l for l in _rank(links) if _good_link(l, domain, seen) and l not in queue]
    return pages


def _crawl_html(start_url: str, max_pages: int) -> list[dict]:
    configured = (settings().get("showcase_pages") or []) if is_own(start_url) else []
    names = {p["url"]: p for p in configured}
    domain = urlparse(start_url).netloc
    queue = [start_url] + [p["url"] for p in configured]
    seen, pages = set(), []
    with httpx.Client(headers=UA, follow_redirects=True, timeout=20) as client:
        while queue and len(pages) < max_pages:
            url = queue.pop(0).rstrip("/") or start_url
            if url in seen:
                continue
            seen.add(url)
            try:
                r = client.get(url)
                if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
                    continue
            except httpx.HTTPError as e:
                log.warning("crawl failed %s: %s", url, e)
                continue
            page = _extract(r.text, str(r.url))
            new = [l for l in _rank(page.pop("links")) if _good_link(l, domain, seen) and l not in queue]
            queue += new
            if url in names:
                page["title"] = names[url].get("name") or page["title"]
                page["description"] = names[url].get("description") or page["description"]
            pages.append(page)
    return pages


def crawl(start_url: str | None = None, max_pages: int = 10, force: bool = False) -> list[dict]:
    """Read up to `max_pages` pages of a site. Cached for 24h per start URL."""
    start_url = (start_url or own_site()).strip()
    if not start_url:
        return []
    cache = _cache_file(start_url)
    if not force and cache.exists() and time.time() - cache.stat().st_mtime < CACHE_TTL:
        return json.loads(cache.read_text(encoding="utf-8"))["pages"]
    js = needs_browser(start_url)
    log.info("reading %s (%s)", start_url, "browser" if js else "html")
    pages = _crawl_js(start_url, max_pages) if js else _crawl_html(start_url, max_pages)
    if pages:
        cache.write_text(json.dumps({"start": start_url, "js": js, "pages": pages}, ensure_ascii=False),
                         encoding="utf-8")
    return pages


def summary(start_url: str | None = None, max_chars: int = 6000) -> str:
    """Compact text the LLM can use to understand the website."""
    parts = []
    for p in crawl(start_url):
        parts.append(
            f"PAGE: {p['url']}\nTITLE: {p['title']}\nDESC: {p['description']}\n"
            f"HEADINGS: {' | '.join(p['headings'][:10])}\nTEXT: {p['text'][:900]}"
        )
    return "\n\n".join(parts)[:max_chars]


def page_urls(start_url: str | None = None) -> list[str]:
    start_url = start_url or own_site()
    if is_own(start_url) and settings().get("showcase_pages"):
        return [p["url"] for p in settings()["showcase_pages"]]
    return [p["url"] for p in crawl(start_url)]
