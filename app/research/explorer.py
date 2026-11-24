"""Site explorer for "Create from URL": reads a WHOLE website, not just its front page.

1. wake()      – free hosts (Render, Railway, Heroku …) sleep and show a "waking up" page first: wait and retry
                 until the real site answers, with a clear error if it never does.
2. discover()  – find the pages: robots.txt / sitemap.xml, the top menu and footer, then links on those pages.
                 Login, legal, cart and single blog-post pages are skipped. Up to MAX_PAGES.
3. read        – read every page (plain HTML directly, JavaScript apps in ONE shared browser session).
4. understand  – the AI sorts each page (product, feature, how-it-works, pricing, case study …) and writes notes:
                 what it is for, features, workflow steps, benefits and real numbers.
5. remember    – stored in the database (shared by the server and the PC worker), refreshed after a week.

Local addresses (localhost, 192.168.x.x, *.local) work too – the PC worker reads those (see pipeline).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urldefrag, urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .. import llm, progress
from ..db import SiteKnowledge, get_session
from . import website

log = logging.getLogger(__name__)

MAX_PAGES = 40
KEEP_DAYS = 7
VERSION = 1
UA = website.UA
SKIP_PATH = re.compile(
    r"(login|log-in|signin|sign-in|signup|sign-up|register|logout|account|password|privacy|terms|cookie|legal|"
    r"gdpr|cart|checkout|basket|wp-admin|wp-login|/feed|/tag/|/tags/|/author/|/category/|/page/\d|\?replytocom|"
    r"/cdn-cgi/|/search)", re.I)
BLOG_POST = re.compile(r"/(blog|news|posts?|articles?|insights|stories)/[^/]+/?$|/\d{4}/\d{2}/", re.I)
SKIP_EXT = website.SKIP_EXT
PAGE_TYPES = ("home", "product", "feature", "solution", "industry", "how_it_works", "pricing", "case_study",
              "integrations", "about", "contact", "docs", "blog", "careers", "other")


class SiteAsleep(RuntimeError):
    pass


class SiteUnreachable(RuntimeError):
    pass


# ── local / LAN addresses ──────────────────────────────────────────────────
def is_local(url: str) -> bool:
    """localhost, 127.x, private LAN IPs and *.local / *.lan names – only the PC can open these."""
    host = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
    if host in ("localhost", "0.0.0.0") or host.endswith((".local", ".lan", ".localhost", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


# ── 1. wake sleeping free hosts ─────────────────────────────────────────────
_WAKING_HINTS = re.compile(r"waking|wake up|spinning up|spin up|starting up|is starting|booting|coming online|"
                           r"service unavailable|application loading|please wait while", re.I)
_HOST_NAMES = re.compile(r"render|railway|heroku|fly\.io|glitch|replit|koyeb|vercel|netlify|cyclic", re.I)


def _looks_asleep(r: httpx.Response) -> bool:
    if r.status_code in (502, 503, 504, 522, 523, 524):
        return True
    ctype = r.headers.get("content-type", "")
    if "text/html" not in ctype:
        return False
    body = r.text[:40000]
    # a small page that talks about waking/starting and names a hosting provider = the host's placeholder
    return len(body) < 40000 and bool(_WAKING_HINTS.search(body)) and bool(_HOST_NAMES.search(body)) \
        and len(re.sub(r"<[^>]+>", " ", body).split()) < 400


def wake(url: str, attempts: int = 8, wait: float = 20) -> str:
    """Return the final URL once the real site answers. Free hosts get ~2.5 minutes to wake up."""
    last = ""
    for i in range(attempts):
        try:
            r = httpx.get(url, headers=UA, follow_redirects=True, timeout=45)
            if not _looks_asleep(r):
                return str(r.url)
            last = f"the host answered {r.status_code} with a 'starting up' page"
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            if is_local(url):
                raise SiteUnreachable(f"Couldn't open {url} – make sure the site is running on this PC "
                                      f"(and the address/port is right). ({e.__class__.__name__})")
            last = f"no connection ({e.__class__.__name__})"
        except httpx.HTTPError as e:
            last = f"{e.__class__.__name__}"
        if i == 0:
            progress.report("The website is asleep (free hosting) – waking it up", 3)
        else:
            progress.report(f"Still waking the website up… ({int((i + 1) * wait)}s)", 3)
        progress.check()
        time.sleep(wait)
    raise SiteAsleep(f"The website {url} didn't wake up ({last}). Open it once in your browser, wait until it "
                     f"loads, then try again.")


# ── 2. discover pages ────────────────────────────────────────────────────────
def _norm(u: str) -> str:
    u = urldefrag(u)[0]
    p = urlparse(u)
    path = re.sub(r"/index\.(html?|php)$", "/", p.path) or "/"
    return f"{p.scheme}://{p.netloc}{path.rstrip('/') or ''}{('?' + p.query) if p.query else ''}" or u


def _same_site(u: str, host: str) -> bool:
    h = (urlparse(u).hostname or "").lower().removeprefix("www.")
    return h == host


def _wanted(u: str, host: str) -> bool:
    low = u.lower()
    return (u.startswith("http") and _same_site(u, host) and not low.split("?")[0].endswith(SKIP_EXT)
            and not SKIP_PATH.search(urlparse(u).path + ("?" + urlparse(u).query if urlparse(u).query else ""))
            and "mailto:" not in low and "tel:" not in low)


def _sitemap_urls(start: str, client: httpx.Client, limit: int = 400) -> list[str]:
    root = f"{urlparse(start).scheme}://{urlparse(start).netloc}"
    maps = []
    try:
        r = client.get(root + "/robots.txt", timeout=15)
        if r.status_code == 200:
            maps += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)
    except httpx.HTTPError:
        pass
    maps += [root + "/sitemap.xml", root + "/sitemap_index.xml", root + "/wp-sitemap.xml"]
    seen, urls = set(), []
    while maps and len(urls) < limit and len(seen) < 12:
        m = maps.pop(0)
        if m in seen:
            continue
        seen.add(m)
        try:
            r = client.get(m, timeout=20)
            if r.status_code != 200 or "<" not in r.text[:200]:
                continue
            tree = ElementTree.fromstring(r.content)
        except Exception:
            continue
        for loc in tree.iter():
            if loc.tag.endswith("loc") and loc.text:
                t = loc.text.strip()
                (maps if t.lower().endswith(".xml") else urls).append(t)
    return urls[:limit]


def _nav_links(html: str, base: str) -> tuple[list[str], list[str]]:
    """(menu/footer links, all links) of a page."""
    soup = BeautifulSoup(html, "html.parser")
    menu = []
    for box in soup.select("header, nav, footer, [role=navigation], [class*=menu], [class*=navbar], [id*=menu]"):
        menu += [urljoin(base, a["href"]) for a in box.find_all("a", href=True)]
    every = [urljoin(base, a["href"]) for a in soup.find_all("a", href=True)]
    return menu, every


def _rank(urls: list[str], menu: set[str], sitemap: set[str]) -> list[str]:
    """Menu pages first, then short paths, sitemap pages, deep pages; single blog posts last."""
    def score(u):
        path = urlparse(u).path
        return (0 if u in menu else 1, 1 if BLOG_POST.search(path) else 0, path.count("/"),
                0 if u in sitemap else 1, len(path))
    return sorted(dict.fromkeys(urls), key=score)


# ── 3. read pages ────────────────────────────────────────────────────────────
def _extract(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    for tag in soup.select("header, nav, footer, [role=navigation], [class*=cookie]"):
        tag.decompose()  # menus repeat on every page – keep only the page's own content
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    heads = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    steps = [li.get_text(" ", strip=True) for ol in soup.find_all("ol") for li in ol.find_all("li")][:12]
    text = " ".join(soup.get_text(" ", strip=True).split())
    return {"url": url, "title": title[:150], "description": (meta.get("content", "") if meta else "").strip()[:300],
            "headings": [h[:120] for h in heads if h][:24], "steps": steps, "text": text[:3500]}


def _read_html(urls: list[str], client: httpx.Client, cap: int, done: int = 0) -> tuple[list[dict], list[str]]:
    pages, more = [], []
    for i, u in enumerate(urls):
        if len(pages) >= cap:
            break
        progress.report(f"Reading page {done + len(pages) + 1} – {urlparse(u).path or '/'}", 4 + int(3 * len(pages) / cap))
        progress.check()
        try:
            r = client.get(u, timeout=25)
        except httpx.HTTPError as e:
            log.info("explorer: %s failed: %s", u, e)
            continue
        if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
            continue
        page = _extract(r.text, str(r.url))
        if len(page["text"]) < 80:
            continue
        pages.append(page)
        more += _nav_links(r.text, str(r.url))[1]
    return pages, more


def _read_js(urls: list[str], cap: int, done: int = 0) -> tuple[list[dict], list[str]]:
    """JavaScript sites: one browser for all pages (much faster than one per page)."""
    from ..generators import browser
    pages, more = [], []
    with browser.browser_context(viewport={"width": 1366, "height": 900}) as ctx:
        page = ctx.new_page()
        for u in urls:
            if len(pages) >= cap:
                break
            progress.report(f"Reading page {done + len(pages) + 1} – {urlparse(u).path or '/'}", 4 + int(3 * len(pages) / cap))
            progress.check()
            try:
                browser.open_page(page, u)
                html = page.content()
            except browser.LoginRequired:
                continue
            except Exception as e:
                log.info("explorer (browser): %s failed: %s", u, e)
                continue
            data = _extract(html, page.url)
            if len(data["text"]) < 80:
                continue
            pages.append(data)
            more += _nav_links(html, page.url)[1]
    return pages, more


def _read_site(start: str, max_pages: int) -> tuple[list[dict], bool, int]:
    """Returns (pages, js, found) – found = how many candidate pages exist."""
    host = (urlparse(start).hostname or "").lower().removeprefix("www.")
    js = website.needs_browser(start)
    with httpx.Client(headers=UA, follow_redirects=True) as client:
        progress.report("Looking for all pages (sitemap, menu, links)", 4)
        sitemap = [_norm(u) for u in _sitemap_urls(start, client) if _wanted(u, host)]
        try:
            home = client.get(start, timeout=30)
            menu, every = _nav_links(home.text, str(home.url)) if "text/html" in home.headers.get("content-type", "") else ([], [])
        except httpx.HTTPError:
            menu, every = [], []
        if js and not menu:  # JS menus only exist after rendering
            from ..generators import browser
            try:
                with browser.browser_context(viewport={"width": 1366, "height": 900}) as ctx:
                    pg = ctx.new_page()
                    browser.open_page(pg, start)
                    menu, every = _nav_links(pg.content(), pg.url)
            except Exception as e:
                log.info("explorer: menu read failed: %s", e)
        menu_n = {_norm(u) for u in menu if _wanted(u, host)}
        cands = [_norm(start)] + _rank([_norm(u) for u in menu + every + sitemap if _wanted(u, host)],
                                       menu_n, set(sitemap))
        cands = list(dict.fromkeys(cands))
        found = len(cands)
        # blog/news: keep the index page, not every single post
        cands = [u for u in cands if not BLOG_POST.search(urlparse(u).path)] + \
                [u for u in cands if BLOG_POST.search(urlparse(u).path)][:2]
        progress.report(f"Found {found} pages – reading the useful ones", 5)
        if js:
            max_pages = min(max_pages, 25)  # a real browser per page is slower – keep it to the 25 most useful
        pages, more = (_read_js(cands[:max_pages + 10], max_pages) if js
                       else _read_html(cands[:max_pages + 10], client, max_pages))
        # sites without a sitemap/menu: follow links found on the pages we read
        if len(pages) < max_pages // 2:
            have = {_norm(p["url"]) for p in pages} | set(cands)
            posts = sum(1 for u in have if BLOG_POST.search(urlparse(u).path))
            extra = [u for u in _rank([_norm(u) for u in more if _wanted(u, host)], menu_n, set(sitemap))
                     if u not in have]
            extra = [u for u in extra if not BLOG_POST.search(urlparse(u).path)] + \
                    [u for u in extra if BLOG_POST.search(urlparse(u).path)][:max(0, 2 - posts)]
            if extra:
                more_pages, _ = (_read_js(extra[:max_pages], max_pages - len(pages), len(pages)) if js
                                 else _read_html(extra[:max_pages], client, max_pages - len(pages), len(pages)))
                pages += more_pages
                found += len(extra)
    # same page under two addresses (redirects) -> once
    uniq, seen = [], set()
    for p in pages:
        k = _norm(p["url"])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq, js, found


# ── 4. understand ────────────────────────────────────────────────────────────
NOTES_SYSTEM = ("You are a product marketer who studies a company's website page by page to explain the product "
                "to customers. Be specific and factual: use only what the page says, never invent numbers.")


def _notes(pages: list[dict], site_name: str) -> list[dict]:
    out: list[dict] = []
    batch = 6
    for i in range(0, len(pages), batch):
        chunk = pages[i:i + batch]
        progress.report(f"Understanding the pages ({min(i + batch, len(pages))} of {len(pages)})",
                        6 + int(2 * i / max(1, len(pages))))
        progress.check()
        body = "\n\n".join(
            f"[{j}] URL: {p['url']}\nTITLE: {p['title']}\nDESCRIPTION: {p['description']}\n"
            f"HEADINGS: {' | '.join(p['headings'][:16])}\n"
            + (f"NUMBERED STEPS ON THE PAGE: {' | '.join(p['steps'][:10])}\n" if p.get("steps") else "")
            + f"TEXT: {p['text'][:2600]}" for j, p in enumerate(chunk))
        prompt = f"""Website: {site_name}
Study these pages. For EACH page return an object (same order, same index):
{{"i": index, "type": one of {list(PAGE_TYPES)},
 "name": "short page name as a customer would say it (e.g. 'Inventory', 'Pricing')",
 "purpose": "1 sentence: what this page/feature is for",
 "features": ["up to 6 concrete features or capabilities on the page"],
 "workflow": ["the steps of how it works, if the page describes a process (else [])"],
 "benefits": ["up to 4 customer benefits"],
 "numbers": ["real figures exactly as written on the page (prices, %, counts) – else []"],
 "audience": "who it is for, if stated",
 "importance": 1-5 (5 = core product/feature page a demo video must show; 1 = minor)}}

PAGES:
{body}

Return JSON: {{"pages": [ ... ]}}"""
        try:
            data = llm.complete_json(prompt, NOTES_SYSTEM, max_tokens=3500)
            notes = {int(n.get("i", -1)): n for n in data.get("pages") or [] if isinstance(n, dict)}
        except Exception as e:
            log.warning("explorer notes failed: %s", e)
            notes = {}
        for j, p in enumerate(chunk):
            n = notes.get(j, {})
            ptype = n.get("type") if n.get("type") in PAGE_TYPES else ("home" if i + j == 0 else "other")
            out.append({
                "url": p["url"], "title": p["title"], "type": ptype,
                "name": str(n.get("name") or p["title"] or urlparse(p["url"]).path)[:80],
                "purpose": str(n.get("purpose") or p["description"])[:300],
                "features": [str(x)[:140] for x in (n.get("features") or [])][:6],
                "workflow": [str(x)[:160] for x in (n.get("workflow") or p.get("steps") or [])][:8],
                "benefits": [str(x)[:140] for x in (n.get("benefits") or [])][:4],
                "numbers": [str(x)[:80] for x in (n.get("numbers") or [])][:6],
                "audience": str(n.get("audience") or "")[:160],
                "importance": max(1, min(5, int(n.get("importance") or 2))) if str(n.get("importance", "")).isdigit() else 2,
                "headings": p["headings"][:10], "text": p["text"][:1500],
            })
    return out


def _overview(pages: list[dict], site_name: str) -> dict:
    lines = "\n".join(f"- {p['name']} ({p['type']}, importance {p['importance']}): {p['purpose']}" for p in pages)
    try:
        d = llm.complete_json(
            f"Website: {site_name}\nPages:\n{lines}\n\nSummarise the business for a marketer. Return JSON "
            '{"what": "1-2 sentences: what the company/product is", "for_whom": "target customers", '
            '"journey": ["page names in the order a new customer should see them to understand the product '
            '(overview -> core features -> how it works -> proof -> pricing/contact)"]}',
            NOTES_SYSTEM, max_tokens=900)
    except Exception as e:
        log.warning("explorer overview failed: %s", e)
        d = {}
    names = {p["name"] for p in pages}
    journey = [n for n in d.get("journey") or [] if n in names]
    return {"what": str(d.get("what") or "")[:400], "for_whom": str(d.get("for_whom") or "")[:300], "journey": journey}


# ── 5. remember ──────────────────────────────────────────────────────────────
def _key(url: str) -> str:
    p = urlparse(url)
    return hashlib.md5(f"{(p.hostname or '').lower().removeprefix('www.')}{p.path.rstrip('/')}".encode()).hexdigest()[:16]


def load(url: str) -> dict | None:
    with get_session() as s:
        row = s.get(SiteKnowledge, _key(url))
        if not row or not row.data:
            return None
        try:
            data = json.loads(row.data)
        except ValueError:
            return None
        if data.get("v") != VERSION or row.updated_at < datetime.utcnow() - timedelta(days=KEEP_DAYS):
            return None
        return data


def _save(url: str, data: dict) -> None:
    with get_session() as s:
        row = s.get(SiteKnowledge, _key(url))
        if row:
            row.data, row.start_url, row.updated_at = json.dumps(data, ensure_ascii=False), url, datetime.utcnow()
        else:
            s.add(SiteKnowledge(key=_key(url), start_url=url, data=json.dumps(data, ensure_ascii=False)))
        s.commit()


def explore(url: str, site_name: str = "", force: bool = False, max_pages: int = MAX_PAGES) -> dict:
    """The whole site, understood: {start, js, found, pages: [notes…], overview}. Cached for a week."""
    if not force:
        cached = load(url)
        if cached:
            progress.report(f"Using what I learned about this website ({len(cached['pages'])} pages)", 7)
            return cached
    start = wake(url)
    pages, js, found = _read_site(start, max_pages)
    if not pages:
        raise RuntimeError(f"Could not read any content from {url} – check the link opens in a browser")
    site_name = site_name or urlparse(start).hostname or url
    notes = _notes(pages, site_name)
    data = {"v": VERSION, "start": start, "js": js, "found": found, "pages": notes,
            "overview": _overview(notes, site_name), "read_at": datetime.utcnow().isoformat() + "Z"}
    _save(url, data)
    log.info("explorer: %s – %s pages read (%s found)", url, len(notes), found)
    return data


def as_text(k: dict, max_chars: int = 14000, focus: str = "") -> str:
    """Compact text for the planner: overview, then every page with its notes (important pages first)."""
    ov = k.get("overview") or {}
    head = (f"WHAT IT IS: {ov.get('what', '')}\nFOR: {ov.get('for_whom', '')}\n"
            f"SUGGESTED CUSTOMER JOURNEY: {' -> '.join(ov.get('journey') or [])}\n"
            f"PAGES READ: {len(k['pages'])} (of {k.get('found', len(k['pages']))} found)\n")
    words = {w for w in re.findall(r"\w{4,}", focus.lower())}
    def rank(p):
        hit = sum(w in (p["name"] + " " + p["purpose"]).lower() for w in words)
        return (-hit, -p["importance"])
    parts = []
    for p in sorted(k["pages"], key=rank):
        s = (f"\nPAGE: {p['name']} [{p['type']}, importance {p['importance']}] {p['url']}\n"
             f"  purpose: {p['purpose']}\n")
        if p["features"]:
            s += f"  features: {'; '.join(p['features'])}\n"
        if p["workflow"]:
            s += f"  how it works: {' -> '.join(p['workflow'])}\n"
        if p["benefits"]:
            s += f"  benefits: {'; '.join(p['benefits'])}\n"
        if p["numbers"]:
            s += f"  numbers on the page: {'; '.join(p['numbers'])}\n"
        parts.append(s)
    out = head
    for s in parts:
        if len(out) + len(s) > max_chars:
            break
        out += s
    return out


def page_for(k: dict, url: str) -> dict | None:
    n = _norm(url)
    return next((p for p in k["pages"] if _norm(p["url"]) == n), None)
