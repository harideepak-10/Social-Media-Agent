"""AI art director for image posts.

The design model writes a complete HTML/CSS poster (1080x1350) following the Krypsos style guide,
a chosen FORMAT and THEME. We render it with Chromium, check for overflow/broken images,
optionally let the model look at the result and fix it, and export a JPG.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import date
from pathlib import Path

from PIL import Image

from .. import llm, progress
from .. import storage
from ..config import company
from ..generators import browser
from . import assets, brandfix, rotation
from .catalog import POST_FORMATS, POST_THEMES

log = logging.getLogger(__name__)
W, H = 1080, 1350

STYLE_GUIDE = """You are the senior art director of a premium tech brand. Your posts look like the work of a top
design studio — editorial, confident, calm — never like a template or clip-art.

REFERENCE STYLE (the brand's own best posts):
1) Cream editorial explainer: warm cream background (#ECE4D8), huge heavy black headline split over 2 lines
   ('No more manual / invoice entry.') with a translucent red highlighter bar behind ONE key word, a grey one-line
   subhead, a slightly rotated white invoice card (soft shadow, yellow highlighter on key fields, a red rotated
   'APPROVED' stamp), and on the right 4 numbered red square badges with bold step titles + grey descriptions,
   joined to the card by dashed red curved lines. Footer: small logo left, 'Fewer errors · faster cycles · site'.
2) Festive night: deep purple, logo top-left, centered elegant serif 2-line headline ('Tradition inspires.
   Technology reimagines.'), italic gold quote, a large glowing neon mandala (pink/violet/gold) built from SVG
   with diyas and a binary-text ring, bokeh dots, tiny monospace body text, 'Happy Diwali from Team <brand>'.
3) Dark tech humour: dark navy, logo top-left, handwritten-style green tagline top-right, two stacked panels
   'EXPECTATION:' (mint chip) vs 'REALITY:' (coral chip) with short funny lines, a terminal card listing red
   error rows, bottom bar with 3 icon+label pillars ('Better Developers | Smarter Solutions | Together We Build').
4) Everyday-object metaphor: solid tomato-red background (#E04A30), giant white heavy serif headline
   'Your receipt is ready.', a slightly rotated thermal-paper receipt with zigzag torn edges and a soft shadow:
   centred logo + brand, dashed rules, 'ORDER: YOUR BUSINESS   TABLE: 01', monospace rows with dotted leaders
   ('1x Custom software ........ ✓', 'Manual work ....... REMOVED', 'Late nights ....... 0'), an inverted black
   'TOTAL  YOUR TIME BACK' box, a CSS barcode, 'THANK YOU FOR AUTOMATING WITH US' and the website. Witty, instantly
   readable, one clever idea.
5) Brand infographic: light mint/white with deep forest green (#0F4D3A), logo top-left, huge 'Why Choose
   <Brand>?', a handwritten green note top-right ('Smarter Ideas. Better Solutions.' with a hand-drawn underline),
   a realistic laptop mock showing the website UI built in CSS, 3 icon rows ('Your Goals. / Our Focus.'), an
   'Our Services' section with 6 icon cards in a 3x2 grid, and a dark green footer band with a pill CTA
   'Let's Build Together →'. (Only show numbers like '100+ projects' if they are on the website.)

RULES
- Canvas exactly 1080x1350. html,body {margin:0;width:1080px;height:1350px;overflow:hidden}. Safe margin ≥ 72px.
- Strong hierarchy: headline 84–130px, tight line-height (0.95–1.05) and letter-spacing (-0.02 to -0.04em);
  supporting text 28–40px; small labels 20–24px. Max ~45 words of visible text total (festive ≤ 35).
- Build ALL visuals with HTML/CSS/inline SVG: UI mocks, documents, chat bubbles, phones, charts, icons,
  line art. They must look realistic and polished (real-looking sample data: names, items, amounts in ₹ for
  India). Sample data must look illustrative, never like real customer data.
- Use only these images if provided: logo.png (always include it once, small, ~44-64px tall – it already
  contains the brand name, so never type the brand name as a text logo/wordmark),
  shot1.png… (real product screenshots), ai1.png… (photos). No other external images. Fonts: Google Fonts
  <link> only for the theme fonts. No JavaScript.
- Never invent statistics, client names, awards, testimonials or prices. Numbers inside mock UIs are fine.
- Personality is welcome: small cartoon characters drawn in inline SVG (simple round faces, expressive eyes,
  a laptop, a coffee mug), big emoji used as reaction stickers (Noto Color Emoji is installed), sticky notes,
  stamps, hand-drawn arrows/underlines (SVG paths). Keep it classy — one playful element, not clutter.
- Excellent contrast. Nothing may overflow or touch the canvas edge unintentionally. Align to a clear grid.
- One idea per post. The headline must be fresh — never reuse a headline/hook from the 'already used' list.
"""


def _font_links(theme: dict) -> str:
    """One <link> per family: a font Google doesn't have (a website's own font) must not break the other."""
    out, seen = [], set()
    for key in ("heading_font", "body_font"):
        name, _, weights = theme[key].partition(":")
        if name in seen:
            continue
        seen.add(name)
        ws = sorted({int(w) for w in (weights or "400").replace(";", ",").split(",") if w.strip().isdigit()})
        fam = f"family={name.replace(' ', '+')}:wght@{';'.join(map(str, ws))}"
        out.append(f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{fam}&display=swap">')
    return "\n".join(out)


def _site_block(theme: dict) -> str:
    """Extra rules when the post is for another website ("Create from URL"): match THEIR design."""
    if not theme.get("_site"):
        return ""
    return f"""
DESIGN SOURCE – IMPORTANT: this post is for the client's website, so it must look like THEIR brand, not like
the Krypsos reference styles above. {"The attached image is a screenshot of their homepage – match its look. " if theme.get("_hero") else ""}
Use exactly their palette (the Palette line above), their fonts (with a similar fallback, e.g. '{theme['heading_font'].split(':')[0]}',
{'Georgia, serif' if theme.get('_serif') else 'Inter, Arial, sans-serif'}), corner radius about {theme.get('_radius', 12)}px on cards,
buttons/pills {'fully rounded' if theme.get('_btn_radius', 0) >= 18 else f"with {theme.get('_btn_radius', 8)}px corners"} in {theme['accent']}
with {theme.get('_btn_text', '#FFFFFF')} text{', headings in UPPERCASE' if theme.get('_uppercase') else ''}. Keep their spacing, imagery
feel and level of decoration (minimal sites stay minimal). Recreate UI mock-ups in their style.
"""


def _brief(plan: dict, fmt: str, theme_name: str, theme: dict, product: dict | None, shots: list[dict],
           ai_ok: bool, day: date) -> str:
    c, t, f = company(), theme, POST_FORMATS[fmt]
    shot_lines = "\n".join(f"- shot{i + 1}.png ({s['w']}x{s['h']} px): {s['text'][:160]}" for i, s in enumerate(shots))
    return f"""BRAND: {c.get('name')} — {c.get('tagline')} | website: {c.get('website')}
AUDIENCE: {c.get('audience')} | TONE: {c.get('tone')}
PRODUCT IN FOCUS: {(product or {}).get('name', '-')} — {(product or {}).get('description', '')}
DATE: {day:%A %d %B %Y}

CONTENT PLAN
- source: {plan['source']} {plan.get('context', '')}
- topic: {plan['topic']}
- angle: {plan['angle']}
- hook idea: {plan['hook']}
- trend: {plan.get('trend_used') or '-'}

FACTS YOU MAY USE (from the website):
{plan['site_summary'][:3500]}

FORMAT: {fmt} — {f['label']}
{f['brief']}

THEME: {theme_name} — {t['mood']}
Palette: bg {t['bg']}, surface {t['surface']}, ink {t['ink']}, muted {t['muted']}, accent {t['accent']}, accent2 {t['accent2']}
Fonts: headline "{t['heading_font'].split(':')[0]}", body "{t['body_font'].split(':')[0]}" — load with
{_font_links(t)}{_site_block(t)}
Logo file: logo.png ({'boxed: place it on a small white rounded chip' if t.get('_boxed') else 'transparent, already coloured for this background'})
Product screenshots available: {shot_lines or 'none'}
Photo generation: {'available — you may request up to 2 photos (ai1.png, ai2.png) via ai_images' if ai_ok else 'NOT available — do not use photos'}

ALREADY USED RECENTLY (do NOT repeat these headlines, hooks or jokes):
{rotation.recent_creative_memory()}

Return JSON:
{{
  "headline": "the main headline text as shown",
  "html": "<!DOCTYPE html>… complete document …",
  "ai_images": [{{"file": "ai1.png", "prompt": "detailed photo prompt, no text in image"}}],
  "captions": {{
     "instagram": "hook line + 2-4 short lines + CTA 'link in bio' (emojis ok)",
     "facebook": "friendly 2-4 short paragraphs incl. {c.get('website')}",
     "linkedin": "professional insight 3-6 short paragraphs incl. {c.get('website')}, max 3 emojis"
  }},
  "hashtags": ["#…", "8-12 relevant tags, broad + niche + India"]
}}"""


_CHECK_JS = """
() => {
  const W = 1080, H = 1350, issues = [];
  const de = document.documentElement;
  if (de.scrollWidth > W + 2 || de.scrollHeight > H + 2) issues.push(`page is ${de.scrollWidth}x${de.scrollHeight}, must be 1080x1350`);
  document.querySelectorAll('img').forEach(i => { if (!i.complete || i.naturalWidth === 0) issues.push(`image failed to load: ${i.getAttribute('src')}`); });
  const textEls = [...document.querySelectorAll('body *')].filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1));
  for (const e of textEls) {
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) === 0) continue;
    const label = e.textContent.trim().slice(0, 40);
    if (r.right > W - 24 || r.bottom > H - 16 || r.left < 16 || r.top < 12) issues.push(`text too close to/over the edge: "${label}"`);
    if ((s.overflow === 'hidden' || s.textOverflow === 'ellipsis') && (e.scrollHeight > e.clientHeight + 3 || e.scrollWidth > e.clientWidth + 3)) issues.push(`text is clipped: "${label}"`);
  }
  // letters cut off by a clipping parent (overflow hidden / clip-path) even when the element itself looks fine
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const txt = n.textContent.trim();
    if (txt.length < 2 || !n.parentElement) continue;
    const ps = getComputedStyle(n.parentElement);
    if (ps.visibility === 'hidden' || ps.display === 'none' || parseFloat(ps.opacity) === 0) continue;
    const rg = document.createRange(); rg.selectNodeContents(n);
    const r = rg.getBoundingClientRect();
    if (!r.width) continue;
    for (let a = n.parentElement; a && a !== document.body; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.overflow === 'visible' && cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
      const ar = a.getBoundingClientRect();
      if (r.right > ar.right + 2 || r.left < ar.left - 2 || r.bottom > ar.bottom + 4 || r.top < ar.top - 4) {
        issues.push(`letters are cut off by a container: "${txt.slice(0, 40)}"`); break;
      }
    }
  }
  return [...new Set(issues)].slice(0, 12);
}
"""


def inline_assets(html: str, work: Path) -> str:
    """Embed the images the design uses (logo.png, shot1.png, ai1.png …) as data: URIs, so the saved HTML
    renders on its own later (text edits) even after the work folder is gone."""
    import base64
    import io
    import re as _re

    def data_uri(name: str) -> str | None:
        f = work / name
        if not f.is_file():
            return None
        raw = f.read_bytes()
        mime = "image/png"
        if f.suffix.lower() in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif not name.startswith("logo") and len(raw) > 250_000:  # big screenshots/photos -> JPEG to keep it small
            im = Image.open(f).convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=86)
            raw, mime = buf.getvalue(), "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    cache: dict[str, str | None] = {}

    def sub(m):
        name = m.group(2)
        if name not in cache:
            cache[name] = data_uri(name)
        return f"{m.group(1)}{cache[name]}{m.group(3)}" if cache[name] else m.group(0)

    pattern = r"""(src=["']|url\(["']?)((?:logo|shot\d+|ai\d+)[\w-]*\.(?:png|jpe?g|webp))(["')])"""
    return _re.sub(pattern, sub, html)


def render_design(html: str, work: Path, out_png: Path) -> list[str]:
    """Public wrapper for edits: render an HTML poster to a 1080×1350 PNG, return layout issues."""
    return _render(html, work, out_png)


def _render(html: str, work: Path, out_png: Path) -> list[str]:
    (work / "post.html").write_text(html, encoding="utf-8")
    with browser.browser_context(viewport={"width": W, "height": H}, device_scale_factor=1) as ctx:
        page = ctx.new_page()
        page.goto((work / "post.html").resolve().as_uri(), wait_until="load", timeout=60000)
        try:
            page.evaluate("document.fonts.ready.then(() => true)")
        except Exception:
            pass
        page.wait_for_timeout(500)
        issues = page.evaluate(_CHECK_JS)
        page.screenshot(path=str(out_png), clip={"x": 0, "y": 0, "width": W, "height": H})
    return issues


def _fix(html: str, issues: list[str], preview: Path | None, fmt: str, theme: str) -> str:
    prompt = f"""This poster HTML ({fmt}, theme {theme}) has problems. Fix them while keeping the design idea,
copy and quality. Problems:
{chr(10).join('- ' + i for i in issues) or '- see the image'}

{"The attached image is how it currently renders." if preview else ""}

CURRENT HTML:
{html}

Return JSON: {{"html": "<!DOCTYPE html>… fixed complete document …"}}"""
    data = llm.complete_json(prompt, STYLE_GUIDE, max_tokens=12000, design=True,
                             images=[preview] if preview and llm.vision_available() else None)
    return data.get("html") or html


def _review(preview: Path) -> list[str]:
    """Let the model look at the rendered poster like an art director would."""
    if not llm.vision_available():
        return []
    brand = company().get("name", "")
    data = llm.complete_json(
        "You are reviewing this social media poster before it is published. Be strict but practical. "
        f"The brand is spelled exactly '{brand}' – any other spelling or a word with missing/cut-off letters is a "
        "problem. Read every word letter by letter. "
        "Return JSON {\"score\": 1-10, \"problems\": [\"concrete visual problems only: overlapping or clipped "
        "text, letters cut off, misspelled words, unreadable/low-contrast text, awkward empty areas, misaligned "
        "elements, broken mockups\"]}. "
        "If it is publish-ready, return an empty problems list.",
        "You are a meticulous senior art director.", max_tokens=800, images=[preview])
    probs = [p for p in data.get("problems", []) if isinstance(p, str)]
    return probs if int(data.get("score", 10)) < 8 else []


def generate(plan: dict, day: date, item_id: int, fmt: str, theme_name: str, product: dict | None,
             shots: list[dict] | None = None, review: bool = True, theme_spec: dict | None = None) -> dict:
    work = storage.work_dir("post", item_id)
    theme = dict(theme_spec or POST_THEMES[theme_name])
    hero = Path(company().get("hero") or "") if theme.get("_site") else None
    hero = hero if hero and hero.is_file() and llm.vision_available() else None
    theme["_hero"] = bool(hero)

    logo = assets.brand_logo(company())
    if logo:
        shutil.copy(logo[theme["logo"]], work / "logo.png")
        theme["_boxed"] = logo["boxed"]
    shots = (shots or [])[:2]
    for i, s in enumerate(shots):
        shutil.copy(s["path"], work / f"shot{i + 1}.png")
    ai_ok = bool(assets.image_provider())

    brief = _brief(plan, fmt, theme_name, theme, product, shots, ai_ok, day)
    progress.report(f"AI art director is designing the post ({theme_name.replace('_', ' ')})", 25)
    data = llm.complete_json(brief, STYLE_GUIDE, max_tokens=14000, design=True, images=[hero] if hero else None)
    html = data.get("html", "")
    if "<html" not in html.lower():
        raise RuntimeError("design model did not return HTML")
    html, fixed = brandfix.fix_html(html)
    if fixed:
        log.info("post #%s brand name fixed: %s", item_id, fixed)

    for img in (data.get("ai_images") or [])[:2] if ai_ok else []:
        fname = Path(img.get("file", "ai1.png")).name
        if not assets.generate_image(img.get("prompt", ""), work / fname):
            html = html.replace(fname, "logo.png")  # graceful fallback

    preview = work / "render.png"
    progress.report("Rendering and checking the design", 60)
    issues = _render(html, work, preview)
    for round_ in range(2):
        if review:
            progress.report("AI is reviewing the rendered post", 66 + round_ * 12)
        problems = issues + (_review(preview) if review else [])
        if (work / "logo.png").exists() and "logo.png" not in html:
            problems.append("the logo image (logo.png) is not used – add it once; never type the brand name as a text logo")
        if not problems:
            break
        log.info("post #%s round %s fixing: %s", item_id, round_ + 1, problems)
        progress.report(f"Fixing design issues (round {round_ + 1})", 70 + round_ * 12)
        html = brandfix.fix_html(_fix(html, problems, preview, fmt, theme_name))[0]
        issues = _render(html, work, preview)

    out = storage.poster_path(day, item_id, plan, fmt)
    Image.open(preview).convert("RGB").save(out, quality=94)
    storage.poster_source_path(out).write_text(inline_assets(html, work), encoding="utf-8")  # editable later
    shutil.rmtree(work, ignore_errors=True)
    tags = [t if t.startswith("#") else f"#{t}" for t in data.get("hashtags", [])]
    design = {"headline": data.get("headline", ""), "format": fmt, "theme": theme_name,
              "product": (product or {}).get("name", "")}
    return {"copy": {"captions": brandfix.fix_captions(data.get("captions", {})), "hashtags": tags, **design},
            "media": out, "thumb": out, "hashtags": " ".join(tags),
            "script_json": json.dumps(design, ensure_ascii=False, indent=2)}
