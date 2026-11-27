"""Finds and captures the 'visual blocks' of a web page — product UI mockups, dashboards, feature
cards, hero sections — as crisp element screenshots the AI can choose from for videos and posts."""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from ..generators import browser

log = logging.getLogger(__name__)

# Marks candidate blocks with data-dma-block="N" and returns their info.
_FIND_BLOCKS_JS = """
(maxBlocks) => {
  const vw = innerWidth;
  const bad = el => el.closest('nav,footer,[role="navigation"],[class*="menu"],[class*="offcanvas"],[class*="cookie"],form');
  const visible = el => {
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.2 &&
           r.left >= -5 && r.right <= vw + 5;
  };
  const deco = el => {
    const s = getComputedStyle(el), ps = getComputedStyle(el.parentElement || el);
    return s.borderRadius !== '0px' || s.boxShadow !== 'none' ||
           (s.backgroundColor !== 'rgba(0, 0, 0, 0)' && s.backgroundColor !== ps.backgroundColor) ||
           s.backgroundImage !== 'none' || /shot|mock|screen|dashboard|window|preview|app|device|card|hero/i.test(el.className);
  };
  const cands = [...document.querySelectorAll('body *')].filter(e => {
    if (['SCRIPT','STYLE','svg','PATH','IMG','VIDEO'].includes(e.tagName)) return false;
    const r = e.getBoundingClientRect();
    if (r.width < Math.min(420, vw * 0.3) || r.height < 200 || r.height > 1300) return false;
    if (bad(e) || !visible(e) || !deco(e)) return false;
    return e.querySelectorAll('*').length >= 12 && e.innerText.trim().length > 20;
  });
  // keep outermost candidates that are still reasonably sized
  let top = cands.filter(e => !cands.some(o => o !== e && o.contains(e) && o.getBoundingClientRect().height < 1100));
  // also allow large images (screenshots / illustrations)
  const imgs = [...document.querySelectorAll('img')].filter(i => {
    const r = i.getBoundingClientRect(); return r.width > 380 && r.height > 220 && visible(i) && !bad(i) && !top.some(t => t.contains(i));
  });
  top = top.concat(imgs);
  top.sort((a, b) => (a.getBoundingClientRect().top + scrollY) - (b.getBoundingClientRect().top + scrollY));
  return top.slice(0, maxBlocks).map((e, i) => {
    e.setAttribute('data-dma-block', String(i));
    const r = e.getBoundingClientRect();
    return { id: i, w: Math.round(r.width), h: Math.round(r.height), y: Math.round(r.top + scrollY),
             text: (e.innerText || e.alt || '').replace(/\\s+/g, ' ').trim().slice(0, 400) };
  });
}
"""


MAX_FULL_H = 7000   # px of the page (CSS) kept for the scrolling "page tour" shot


def capture(url: str, out_dir: Path, max_blocks: int = 14, width: int = 1440, full: bool = False) -> dict:
    """Returns {url, title, text, hero: Path, blocks: [{id, path, w, h, text}], full: {path, w, h} | None}.
    full=True also takes a screenshot of the whole page (for the scrolling page-tour scene)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"url": url, "title": "", "text": "", "hero": None, "blocks": [], "full": None}
    with browser.browser_context(viewport={"width": width, "height": 900}, device_scale_factor=2) as ctx:
        page = ctx.new_page()
        browser.open_page(page, url)
        # scroll through once so lazy content / reveal animations render
        page.evaluate("""async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) {
            scrollTo(0, y); await new Promise(r => setTimeout(r, 90)); } scrollTo(0, 0); }""")
        page.wait_for_timeout(800)
        result["title"] = page.title()
        result["text"] = " ".join(page.evaluate("document.body.innerText").split())[:6000]
        hero = out_dir / "hero.png"
        page.screenshot(path=str(hero))
        result["hero"] = hero
        if full:
            try:
                h = min(int(page.evaluate("document.documentElement.scrollHeight")), MAX_FULL_H)
                fp = out_dir / "full.jpg"
                page.screenshot(path=str(fp), clip={"x": 0, "y": 0, "width": width, "height": max(900, h)},
                                full_page=True, type="jpeg", quality=82)
                im = Image.open(fp)
                if im.width > 1800:  # 2x screenshot -> keep the file small, still crisp in a 1040 px window
                    im = im.resize((1800, round(im.height * 1800 / im.width)), Image.LANCZOS)
                    im.convert("RGB").save(fp, quality=84)
                result["full"] = {"path": fp, "w": im.width, "h": im.height}
            except Exception as e:
                log.warning("full-page screenshot failed on %s: %s", url, e)
        try:
            infos = page.evaluate(_FIND_BLOCKS_JS, max_blocks)
        except Exception as e:
            log.warning("block detection failed on %s: %s", url, e)
            infos = []
        for info in infos:
            path = out_dir / f"block_{info['id']}.png"
            try:
                loc = page.locator(f'[data-dma-block="{info["id"]}"]').first
                loc.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(250)
                loc.screenshot(path=str(path), timeout=10000)
                if _is_blank(path):
                    continue
                result["blocks"].append({**info, "path": path})
            except Exception as e:
                log.debug("block %s capture failed: %s", info["id"], e)
    if not result["blocks"] and result["hero"]:
        result["blocks"].append({"id": 0, "path": result["hero"], "w": width, "h": 900, "text": result["text"][:400]})
    return result


def _is_blank(path: Path) -> bool:
    im = Image.open(path).convert("L").resize((40, 40))
    lo, hi = im.getextrema()
    return hi - lo < 12


def contact_sheet(blocks: list[dict], out: Path, thumb_w: int = 460) -> Path:
    """One image with numbered thumbnails (B0, B1, …) so the AI can see all blocks at once."""
    from ..generators import graphics

    if len(blocks) > 15:  # many screens (the user's uploads): smaller thumbnails, more per row
        thumb_w = min(thumb_w, 340)
    thumbs = []
    for b in blocks:
        im = Image.open(b["path"]).convert("RGB")
        im.thumbnail((thumb_w, 340 if thumb_w > 400 else 250))
        thumbs.append((b["id"], im))
    cols = 3 if len(thumbs) <= 15 else 4 if len(thumbs) <= 24 else 5
    cell_w, cell_h = thumb_w + 20, (340 if thumb_w > 400 else 250) + 50
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, max(1, rows) * cell_h), "white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(sheet)
    f = graphics.font(28, True)
    for i, (bid, im) in enumerate(thumbs):
        x, y = (i % cols) * cell_w + 10, (i // cols) * cell_h + 10
        d.text((x, y), bid if isinstance(bid, str) else f"B{bid}", font=f, fill=(220, 38, 38))  # U0 / R0c1 = the user's
        sheet.paste(im, (x, y + 38))
    sheet.save(out, quality=88)
    return out


# ── "product tour" capture: full screens + the sections to spotlight on each (rects in viewport %) ─────────
TOUR_VW, TOUR_VH, TOUR_DPR = 1440, 810, 4 / 3          # 16:9 -> 1920x1080 screenshots

_FIND_SPOTS_JS = """
(maxSpots, loose) => {
  const vw = innerWidth, vh = innerHeight, area = vw * vh;
  const chrome = el => el.closest('nav,header,footer,aside,[role="navigation"],[class*="sidebar"],[class*="Sidebar"],[class*="cookie"],[class*="toast"]');
  const shown = el => { const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.3; };
  const deco = el => { const s = getComputedStyle(el), ps = getComputedStyle(el.parentElement || el);
    return s.borderRadius !== '0px' || s.boxShadow !== 'none' || s.borderTopWidth !== '0px' || s.backgroundImage !== 'none' ||
      (s.backgroundColor !== 'rgba(0, 0, 0, 0)' && s.backgroundColor !== ps.backgroundColor); };
  const inView = r => r.top >= -2 && r.left >= -2 && r.bottom <= vh + 2 && r.right <= vw + 2;
  const kids = el => [...el.children].filter(c => { const r = c.getBoundingClientRect(); return r.width > 40 && r.height > 24 && shown(c); });
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (['SCRIPT','STYLE','svg','path','IMG','VIDEO','BUTTON','INPUT','A','SPAN','P','H1','H2','H3','LI','TD','TR'].includes(el.tagName)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 260 || r.height < 44 || !inView(r)) continue;
    const a = r.width * r.height;
    if (a < area * 0.025 || a > area * 0.62 || r.height > vh * 0.82) continue;
    if (chrome(el) || !shown(el)) continue;
    const txt = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (txt.length < 8) continue;
    const ks = kids(el), s = getComputedStyle(el);
    const group = ks.length >= 2 && (s.display.includes('grid') || s.display.includes('flex')) && ks.filter(deco).length >= 2;
    const card = deco(el) && el.querySelectorAll('*').length >= 4;
    const section = el.querySelector('h1,h2,h3') && txt.length > 30 && r.width > vw * 0.4;   // plain landing-page sections
    if (!group && !card && !(loose && section)) continue;
    // a group of cards beats one card; mid-sized beats huge
    const score = (group ? 3 : 1) + Math.min(ks.length, 6) * 0.25 - Math.abs(a / area - 0.18) * 3;
    out.push({ el, r, score, txt });
  }
  const iou = (a, b) => { const x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
    const y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)); const i = x * y;
    return i / Math.min(a.width * a.height, b.width * b.height); };
  out.sort((a, b) => b.score - a.score);
  const picked = [];
  for (const c of out) {
    if (picked.length >= maxSpots) break;
    if (picked.some(p => iou(p.r, c.r) > 0.2)) continue;
    picked.push(c);
  }
  picked.sort((a, b) => a.r.top - b.r.top || a.r.left - b.r.left);
  return picked.map((c, i) => ({ id: i, x: c.r.left / vw, y: c.r.top / vh, w: c.r.width / vw, h: c.r.height / vh,
                                 text: c.txt.slice(0, 260) }));
}
"""

_LINKS_JS = """
() => [...document.querySelectorAll('a[href]')].map(a => { const r = a.getBoundingClientRect();
  return { href: a.href, x: r.left / innerWidth, y: r.top / innerHeight, w: r.width / innerWidth, h: r.height / innerHeight,
           text: (a.innerText || a.title || '').trim().slice(0, 40) }; })
  .filter(l => l.w > 0 && l.h > 0 && l.y >= 0 && l.y + l.h <= 1 && l.x >= 0 && l.x + l.w <= 1)
"""


def tour_capture(url: str, out_dir: Path, max_screens: int = 3, max_spots: int = 4) -> dict:
    """Full 1920x1080 screens of a page (top first, then further down) and, on each, the sections worth a spotlight.
    Returns {url, title, text, screens: [{id, path, w, h, spots: [{id, x, y, w, h, text}]}], links: [...]}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {"url": url, "title": "", "text": "", "screens": [], "links": []}
    with browser.browser_context(viewport={"width": TOUR_VW, "height": TOUR_VH}, device_scale_factor=TOUR_DPR) as ctx:
        page = ctx.new_page()
        browser.open_page(page, url)
        page.evaluate("""async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) {
            scrollTo(0, y); await new Promise(r => setTimeout(r, 80)); } scrollTo(0, 0); }""")
        page.wait_for_timeout(900)
        res["title"] = page.title()
        res["text"] = " ".join(page.evaluate("document.body.innerText").split())[:6000]
        try:
            res["links"] = page.evaluate(_LINKS_JS)[:120]
        except Exception:
            pass
        total = int(page.evaluate("document.documentElement.scrollHeight") or TOUR_VH)
        y, seen, last = 0, 0, None
        while len(res["screens"]) < max_screens and y < total:
            page.evaluate(f"scrollTo(0, {y})")
            page.wait_for_timeout(450)
            actual = int(page.evaluate("scrollY"))
            if last is not None and actual <= last + TOUR_VH * 0.3:
                break  # the page doesn't scroll (much) further, e.g. an app with its own scroll areas
            last = actual
            try:
                spots = page.evaluate(f"({_FIND_SPOTS_JS})({max_spots}, false)") or \
                    page.evaluate(f"({_FIND_SPOTS_JS})({max_spots}, true)")  # no cards: use plain sections
            except Exception as e:
                log.debug("spot detection failed on %s: %s", url, e)
                spots = []
            if spots or not res["screens"]:
                p = out_dir / f"screen_{seen}.jpg"
                page.screenshot(path=str(p), type="jpeg", quality=86)
                res["screens"].append({"id": seen, "path": p, "w": round(TOUR_VW * TOUR_DPR), "h": round(TOUR_VH * TOUR_DPR),
                                       "scroll": actual, "spots": spots})
                seen += 1
            y = actual + int(TOUR_VH * 0.92)
    return res
