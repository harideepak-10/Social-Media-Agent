"""Playwright helpers: logged-in sessions, page screenshots and high-res scene captures.

Works with JavaScript apps (React/Vue SPAs): waits until the page has really rendered,
expands inner scroll panels (e.g. <main class="overflow-y-auto">) so the whole page can be captured,
and reuses a saved login session (`python cli.py login`).
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright

from ..config import CACHE_DIR, company, settings

log = logging.getLogger(__name__)

AUTH_STATE = CACHE_DIR / "auth_state.json"
MAX_PAGE_CSS_HEIGHT = 7000

# Viewports per orientation (CSS px). Pages are captured at `video` width resolution.
VIEWPORTS = {
    "vertical": {"viewport": {"width": 414, "height": 736}, "video": {"width": 1080, "height": 1920}, "mobile": True},
    "square": {"viewport": {"width": 900, "height": 900}, "video": {"width": 1080, "height": 1080}, "mobile": False},
    "landscape": {"viewport": {"width": 1280, "height": 720}, "video": {"width": 1920, "height": 1080}, "mobile": False},
}


class LoginRequired(RuntimeError):
    pass


def site_cfg() -> dict:
    return settings().get("site") or {}


_HIDE_POPUPS_JS = """
() => {
  const kill = ['cookie','consent','gdpr','newsletter','popup','chat-widget','intercom','crisp','tawk'];
  document.querySelectorAll('div,section,aside,iframe').forEach(el => {
    const s = ((el.id||'') + ' ' + (el.className||'')).toString().toLowerCase();
    const st = getComputedStyle(el);
    if (kill.some(k => s.includes(k)) && (st.position === 'fixed' || st.position === 'sticky')) el.remove();
  });
  document.documentElement.style.scrollBehavior = 'auto';
}
"""

# Dashboards often scroll inside a panel instead of the page. Make the biggest such panel
# (and its ancestors) grow to full height so a full-page screenshot contains everything.
_EXPAND_SCROLL_PANELS_JS = """
() => {
  const panels = [...document.querySelectorAll('*')].filter(e => {
    const s = getComputedStyle(e);
    return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 40 && e.clientWidth > innerWidth * 0.5;
  }).sort((a, b) => b.scrollHeight - a.scrollHeight);
  const main = panels[0];
  if (!main) return 0;
  let el = main;
  while (el && el !== document.documentElement) {
    el.style.height = 'auto'; el.style.maxHeight = 'none'; el.style.minHeight = '0';
    el.style.overflow = 'visible'; el.style.flex = 'none'; el = el.parentElement;
  }
  document.documentElement.style.height = 'auto'; document.body.style.height = 'auto';
  document.documentElement.style.overflow = 'visible'; document.body.style.overflow = 'visible';
  return main.scrollHeight;
}
"""


def warmup() -> None:
    """Wake sleeping backends (e.g. Render free plan) before capturing pages."""
    for url in site_cfg().get("warmup_urls") or []:
        t0 = time.time()
        while time.time() - t0 < 150:
            try:
                r = httpx.get(url, timeout=60)
                log.info("warm-up %s -> %s (%.0fs)", url, r.status_code, time.time() - t0)
                if r.status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(5)


@contextmanager
def browser_context(orientation: str | None = None, headless: bool = True, **extra):
    """Chromium context with the saved login session; saves refreshed session on exit."""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        opts = dict(extra)
        if orientation:
            cfg = VIEWPORTS.get(orientation, VIEWPORTS["vertical"])
            opts.update(viewport=cfg["viewport"], is_mobile=cfg["mobile"], has_touch=cfg["mobile"],
                        device_scale_factor=cfg["video"]["width"] / cfg["viewport"]["width"])
        if AUTH_STATE.exists():
            opts["storage_state"] = str(AUTH_STATE)
        ctx = b.new_context(**opts)
        try:
            yield ctx
            if AUTH_STATE.exists():  # keep refreshed tokens for tomorrow's run (all sites)
                old = json.loads(AUTH_STATE.read_text(encoding="utf-8"))
                AUTH_STATE.write_text(json.dumps(_merge_state(old, ctx.storage_state())), encoding="utf-8")
        finally:
            ctx.close()
            b.close()


def _wait_ready(page, timeout: float = 120) -> None:
    """Wait for network idle, loading messages to disappear and the text to stop changing."""
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    gone = [t.lower() for t in site_cfg().get("wait_text_gone") or []]
    t0, last, stable = time.time(), "", 0
    while time.time() - t0 < timeout:
        try:
            text = page.evaluate("document.body ? document.body.innerText : ''")
        except Exception:
            text = ""
        busy = any(g in text.lower() for g in gone)
        if not busy and text == last and len(text) > 20:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        last = text
        page.wait_for_timeout(700)
    page.wait_for_timeout(500)


LOGIN_MARKERS = ["/login", "/signin", "/sign-in", "/sign_in", "/auth/", "/account/login", "accounts.google.com"]


def _check_login(page, requested: str) -> None:
    """Raise if we asked for a normal page but were redirected to a login page."""
    markers = site_cfg().get("login_url_markers") or LOGIN_MARKERS
    asked_login = any(m in requested.lower() for m in markers)
    if not asked_login and any(m in page.url.lower() for m in markers):
        origin = f"{urlparse(requested).scheme}://{urlparse(requested).netloc}"
        raise LoginRequired(f"{requested} needs a login – run `python cli.py login --url {origin}` on this PC")


def open_page(page, url: str) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        page.goto(url, wait_until="commit", timeout=60000)
    _wait_ready(page)
    _check_login(page, url)
    try:
        page.evaluate(_HIDE_POPUPS_JS)
    except Exception:
        pass


def page_text(url: str) -> tuple[str, str, list[str]]:
    """(title, visible text, same-site links) of a JS-rendered page."""
    with browser_context(viewport={"width": 1280, "height": 900}) as ctx:
        page = ctx.new_page()
        open_page(page, url)
        links = page.evaluate("[...new Set([...document.querySelectorAll('a[href]')].map(a => a.href))]")
        return page.title(), page.evaluate("document.body.innerText"), links


def screenshot(url: str, out: Path, width: int = 1280, height: int = 800) -> Path | None:
    try:
        with browser_context(viewport={"width": width, "height": height}, device_scale_factor=1.5) as ctx:
            page = ctx.new_page()
            open_page(page, url)
            page.screenshot(path=str(out))
        return out
    except Exception as e:
        log.warning("screenshot failed for %s: %s", url, e)
        return None


def capture_scene(url: str, out: Path, orientation: str = "vertical", scroll: float = 0.35,
                  highlight: str = "") -> tuple[Path, float, float]:
    """High-res full-page screenshot used for an animated scroll.

    Returns (png, start_y_ratio, end_y_ratio) — where the camera starts and ends,
    as a fraction of the full page height. If `highlight` text is found it is outlined
    and the camera ends centred on it.
    """
    cfg = VIEWPORTS.get(orientation, VIEWPORTS["vertical"])
    vw, vh = cfg["viewport"]["width"], cfg["viewport"]["height"]
    with browser_context(orientation) as ctx:
        page = ctx.new_page()
        open_page(page, url)
        # trigger lazy-loaded images / scroll animations, then go back to top
        page.evaluate("""async () => { const h = document.body.scrollHeight;
            for (let y = 0; y < h; y += innerHeight / 2) { scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); }
            scrollTo(0, 0); }""")
        page.evaluate(_EXPAND_SCROLL_PANELS_JS)
        page.wait_for_timeout(600)
        full_h = min(page.evaluate("document.documentElement.scrollHeight"), MAX_PAGE_CSS_HEIGHT)
        end_y = max(0, (full_h - vh) * max(0.0, min(1.0, scroll)))
        if highlight:
            try:
                loc = page.get_by_text(highlight, exact=False).first
                box = loc.bounding_box(timeout=3000)
                if box:
                    loc.evaluate("el => { el.style.outline='5px solid #FACC15'; el.style.outlineOffset='6px';"
                                 " el.style.borderRadius='10px'; el.style.background='rgba(250,204,21,.18)'; }")
                    end_y = max(0, min(full_h - vh, box["y"] - vh * 0.3))
            except Exception:
                pass
        page.screenshot(path=str(out), full_page=True,
                        clip={"x": 0, "y": 0, "width": vw, "height": full_h})
    return out, 0.0, end_y / full_h if full_h else 0.0


_BRAND_JS = """
() => {
  const meta = n => (document.querySelector(`meta[property="${n}"],meta[name="${n}"]`) || {}).content || '';
  const out = [];
  const sel = 'header,nav,button,a,[class*="btn"],[class*="button"],[class*="hero"],[class*="banner"],h1,h2,section';
  document.querySelectorAll(sel).forEach(el => {
    const r = el.getBoundingClientRect(); const area = Math.min(r.width * r.height, 200000);
    if (area < 200) return;
    const st = getComputedStyle(el);
    out.push([st.backgroundColor, area]);
    if (/^(A|BUTTON|H1|H2)$/.test(el.tagName)) out.push([st.color, area / 4]);
  });
  return { site_name: meta('og:site_name') || meta('application-name'), title: document.title,
           description: meta('description') || meta('og:description'), theme: meta('theme-color'), colors: out };
}
"""


def _parse_rgb(c: str):
    import re
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?", c or "")
    if not m or (m.group(4) is not None and float(m.group(4)) < 0.5):
        return None
    return tuple(int(m.group(i)) for i in (1, 2, 3))


def _vivid(rgb) -> bool:
    mx, mn = max(rgb), min(rgb)
    return mx - mn > 50 and 40 < mx  # saturated, not grey/white/black


def brand_info(url: str) -> dict:
    """Name, description and main brand colours of any website (read in a real browser)."""
    with browser_context(viewport={"width": 1366, "height": 900}) as ctx:
        page = ctx.new_page()
        open_page(page, url)
        data = page.evaluate(_BRAND_JS)
    weights: dict[tuple, float] = {}
    for c, area in data.get("colors", []):
        rgb = _parse_rgb(c)
        if rgb and _vivid(rgb):
            key = tuple(v // 12 * 12 for v in rgb)  # bucket similar shades
            weights[key] = weights.get(key, 0) + area
    ranked = [k for k, _ in sorted(weights.items(), key=lambda kv: -kv[1])]
    theme = data.get("theme", "")
    if theme.startswith("#") and len(theme) in (4, 7):
        if len(theme) == 4:
            theme = "#" + "".join(ch * 2 for ch in theme[1:])
        ranked.insert(0, tuple(int(theme[i:i + 2], 16) for i in (1, 3, 5)))
    ranked = [c for c in ranked if _vivid(c)]
    to_hex = lambda c: "#%02X%02X%02X" % c
    primary = ranked[0] if ranked else (79, 70, 229)
    lum = lambda c: (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255
    if lum(primary) > 0.62:  # very light brand colour (yellow, cyan…) -> darken so white text stays readable
        primary = tuple(int(v * 0.6) for v in primary)
    # secondary: next colour that differs enough, else a darker shade of primary
    secondary = next((c for c in ranked[1:] if sum(abs(a - b) for a, b in zip(c, primary)) > 90),
                     tuple(int(v * 0.55) for v in primary))
    return {"site_name": data.get("site_name", ""), "title": data.get("title", ""),
            "description": data.get("description", ""),
            "brand_colors": {"primary": to_hex(primary), "secondary": to_hex(secondary), "text": "#FFFFFF"}}


def _merge_state(old: dict, new: dict) -> dict:
    cookies = {(c["name"], c["domain"], c["path"]): c for c in old.get("cookies", []) + new.get("cookies", [])}
    origins = {o["origin"]: o for o in old.get("origins", []) + new.get("origins", [])}
    return {"cookies": list(cookies.values()), "origins": list(origins.values())}


def interactive_login(url: str | None = None) -> None:
    """Open a visible browser so the user can log in to a website once.
    Sessions for several websites are kept together, so you can log in to many sites."""
    url = url or site_cfg().get("login_url") or company().get("website")
    old = json.loads(AUTH_STATE.read_text(encoding="utf-8")) if AUTH_STATE.exists() else {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        ctx = b.new_context(viewport={"width": 1280, "height": 860},
                            storage_state=str(AUTH_STATE) if AUTH_STATE.exists() else None)
        page = ctx.new_page()
        page.goto(url)
        input(f"\n>>> Log in to {url} in the browser window (use a DEMO account with sample data),\n"
              "    wait until you see the logged-in page, then press Enter here... ")
        new = ctx.storage_state()
        b.close()
    AUTH_STATE.write_text(json.dumps(_merge_state(old, new)), encoding="utf-8")
    print(f"Saved login session for {url} to {AUTH_STATE}")
