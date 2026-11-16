"""Generates an image post: captions per platform + a branded 1080x1350 creative."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from .. import llm
from .. import storage
from ..config import company
from . import browser, graphics
from .planner import SYSTEM, _brand_block

log = logging.getLogger(__name__)
SIZE = (1080, 1350)  # 4:5 works on Instagram, Facebook and LinkedIn


def write_copy(plan: dict, day: date) -> dict:
    c = company()
    prompt = f"""{_brand_block()}

WEBSITE CONTENT (facts you may use):
{plan['site_summary'][:3500]}

POST PLAN
- date: {day:%A %d %B %Y}
- source: {plan['source']}  {plan['context']}
- topic: {plan['topic']}
- angle: {plan['angle']}
- hook: {plan['hook']}
- trend used: {plan.get('trend_used') or '-'}

Write today's image post.
Rules:
- Festival posts: warm, respectful wishes first, brand second; no hard selling.
- Trend posts: connect the trend to a real benefit from the website; be timely.
- Website posts: one feature/benefit, problem -> solution -> CTA.
- Image text must be SHORT (headline max 8 words, subline max 14 words).
- Captions: Instagram (hook line, short lines, emojis ok, CTA "link in bio"), Facebook (friendly, 2-4 short
  paragraphs, include website {c.get('website')}), LinkedIn (professional insight, 3-6 short paragraphs,
  include website, max 3 emojis).
- 8-12 relevant hashtags mixing broad + niche + India-specific; LinkedIn uses only 3-5 of them.

Return JSON:
{{
  "headline": "...",
  "subline": "...",
  "badge": "small label like 'Happy Diwali' / 'New Feature' / 'Trending' (max 3 words)",
  "visual": "festival | feature | trend",
  "screenshot_url": "a website page URL to show inside the image, or empty",
  "captions": {{"instagram": "...", "facebook": "...", "linkedin": "..."}},
  "hashtags": ["#...", "#..."]
}}"""
    return llm.complete_json(prompt, SYSTEM, max_tokens=3000)


def render_image(copy: dict, out: Path) -> Path:
    w, h = SIZE
    img = graphics.gradient(SIZE)
    d = ImageDraw.Draw(img)
    col = graphics.colors()
    pad = 80

    graphics.paste_logo(img, "top-left", max_h=70, margin=pad)

    # badge pill
    y = 210
    badge = (copy.get("badge") or "").upper()
    if badge:
        bf = graphics.font(34, True)
        bw = d.textlength(badge, font=bf) + 48
        d.rounded_rectangle((pad, y, pad + bw, y + 62), 31, fill=(255, 255, 255, 235))
        d.text((pad + 24, y + 11), badge, font=bf, fill=col["primary"])
        y += 100

    shot_path = None
    if copy.get("screenshot_url") and copy.get("visual") != "festival":
        shot_path = browser.screenshot(copy["screenshot_url"], out.with_suffix(".shot.png"))

    head_h = 330 if shot_path else 520
    hf, hl = graphics.fit_text(d, copy.get("headline", ""), w - 2 * pad, head_h, start=104)
    y = graphics.draw_lines(d, hl, hf, pad, y, col["text"])
    sf, sl = graphics.fit_text(d, copy.get("subline", ""), w - 2 * pad, 150, start=46, bold=False)
    y = graphics.draw_lines(d, sl, sf, pad, y + 20, (255, 255, 255, 225), shadow=False)

    if shot_path:
        shot = graphics.rounded_screenshot(Image.open(shot_path), w - 2 * pad)
        avail = h - int(y) - 60 - 130
        if shot.height > avail:
            shot = shot.crop((0, 0, shot.width, max(avail, 200)))
        shadow = Image.new("RGBA", (shot.width + 40, shot.height + 40), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((20, 26, shot.width + 20, shot.height + 26), 28, fill=(0, 0, 0, 80))
        img.alpha_composite(shadow, (pad - 20, int(y) + 40))
        img.alpha_composite(shot, (pad, int(y) + 50))
    elif copy.get("visual") == "festival":
        # decorative festive dots
        import random
        rnd = random.Random(copy.get("headline", ""))
        for _ in range(70):
            r = rnd.randint(3, 10)
            x0, y0 = rnd.randint(0, w), rnd.randint(int(h * 0.55), h - 160)
            d.ellipse((x0, y0, x0 + r, y0 + r), fill=(255, 220, 120, rnd.randint(120, 230)))

    # footer bar
    bar = Image.new("RGBA", (w, 120), (0, 0, 0, 70))
    img.alpha_composite(bar, (0, h - 120))
    d = ImageDraw.Draw(img)
    ff = graphics.font(36, False)
    site = (company().get("website") or "").replace("https://", "").replace("http://", "").rstrip("/")
    d.text((pad, h - 82), site, font=ff, fill=(255, 255, 255, 240))
    cta = company().get("name", "")
    d.text((w - pad - d.textlength(cta, font=ff), h - 82), cta, font=ff, fill=(255, 255, 255, 240))

    img.convert("RGB").save(out, quality=95)
    if shot_path:
        shot_path.unlink(missing_ok=True)
    return out


def generate(plan: dict, day: date, item_id: int) -> dict:
    copy = write_copy(plan, day)
    out = render_image(copy, storage.poster_path(day, item_id, plan, "simple"))
    tags = [t if t.startswith("#") else f"#{t}" for t in copy.get("hashtags", [])]
    return {"copy": copy, "media": out, "thumb": out, "hashtags": " ".join(tags)}
