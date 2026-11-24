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

    thumbs = []
    for b in blocks:
        im = Image.open(b["path"]).convert("RGB")
        im.thumbnail((thumb_w, 340))
        thumbs.append((b["id"], im))
    cols = 3
    cell_w, cell_h = thumb_w + 20, 340 + 50
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, max(1, rows) * cell_h), "white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(sheet)
    f = graphics.font(28, True)
    for i, (bid, im) in enumerate(thumbs):
        x, y = (i % cols) * cell_w + 10, (i // cols) * cell_h + 10
        d.text((x, y), f"B{bid}", font=f, fill=(220, 38, 38))
        sheet.paste(im, (x, y + 38))
    sheet.save(out, quality=88)
    return out
