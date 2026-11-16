"""Website explainer video: script -> voice-over -> screen recording -> captions -> final MP4."""
from __future__ import annotations

import json
import logging
import random
import shutil
from datetime import date
from pathlib import Path

from PIL import Image

from .. import llm
from .. import storage
from ..config import ASSETS_DIR, company, settings
from . import browser, ffmpeg, graphics, tts
from .planner import SYSTEM, _brand_block

log = logging.getLogger(__name__)

SIZES = {"vertical": (1080, 1920), "square": (1080, 1080), "landscape": (1920, 1080)}


def write_script(plan: dict, day: date) -> dict:
    vcfg = settings().get("video") or {}
    max_s = int(vcfg.get("max_seconds", 45))
    words = int(max_s * 2.4)
    c = company()
    prompt = f"""{_brand_block()}

WEBSITE CONTENT (only use facts from here):
{plan['site_summary'][:4500]}

VIDEO PLAN
- date: {day:%A %d %B %Y}
- topic: {plan['topic']}
- angle: {plan['angle']}
- hook idea: {plan['hook']}
- trend used: {plan.get('trend_used') or '-'}
- {plan.get('context') or ''}
- pages to show: {plan['page_urls']}

Write a short, viral-style explainer video script with voice-over that walks through the website.
Structure:
1. HOOK (2-3 s): a scroll-stopping question or bold claim shown on a title card.
2. 2-4 SCENES: each shows one website page (URL from 'pages to show') while the voice explains the
   functionality / benefit. Conversational, simple English, second person ("you"), short sentences.
3. OUTRO (3-4 s): clear call to action with the website.
Total voice-over must be <= {words} words (about {max_s} seconds).
For each scene give "highlight": an exact short text (2-5 words) that appears on that page to highlight, or "".
"scroll": how far down the page to scroll during the scene (0.0 = stay at top, 1.0 = bottom).
"caption": on-screen subtitle (max 9 words) summarising the line.

Captions: Instagram (hook + 2-3 short lines + CTA "link in bio"), Facebook (friendly + website {c.get('website')}),
LinkedIn (professional, value-focused, include website). 8-12 hashtags incl. trending/niche ones.

Return JSON:
{{
  "hook": {{"title": "max 7 words", "subtitle": "max 10 words", "voice": "spoken hook line"}},
  "scenes": [{{"url": "https://...", "voice": "...", "caption": "...", "highlight": "...", "scroll": 0.3}}],
  "outro": {{"title": "CTA max 6 words", "voice": "spoken CTA"}},
  "captions": {{"instagram": "...", "facebook": "...", "linkedin": "..."}},
  "hashtags": ["#..."]
}}"""
    script = llm.complete_json(prompt, SYSTEM, max_tokens=3500)
    allowed = set(plan["page_urls"])
    for sc in script.get("scenes", []):
        if sc.get("url") not in allowed and plan["page_urls"]:
            sc["url"] = plan["page_urls"][0]
    script["scenes"] = script.get("scenes", [])[:4]
    return script


def _prepare_page(shot: Path, end_ratio: float, size: tuple[int, int]) -> tuple[Path, int]:
    """Resize the full-page capture to video width and crop to just the part the camera travels."""
    w, h = size
    img = Image.open(shot).convert("RGB")
    img = img.resize((w, max(1, round(img.height * w / img.width))), Image.LANCZOS)
    if img.height < h:
        canvas = Image.new("RGB", (w, h), "white")
        canvas.paste(img, (0, 0))
        img = canvas
    end_px = int(min(end_ratio * img.height, img.height - h))
    img = img.crop((0, 0, w, end_px + h))
    # even dimensions for yuv420p
    out = shot.with_name(shot.stem + "_v.png")
    img.save(out)
    return out, max(0, end_px)


def build(script: dict, out: Path, orientation: str = "vertical") -> Path:
    size = SIZES.get(orientation, SIZES["vertical"])
    from .. import storage
    work = storage.WORK_DIR / f"simple_{out.stem}"
    work.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    site = (company().get("website") or "").replace("https://", "").replace("http://", "").rstrip("/")

    # 1) hook card
    hook = script.get("hook") or {}
    audio, secs = tts.speak(hook.get("voice") or hook.get("title", ""), work / "hook")
    card = graphics.text_card(work / "hook.jpg", size, hook.get("title", ""), hook.get("subtitle", ""))
    clips.append(ffmpeg.image_clip(card, audio, secs + 0.4, size, work / "c00_hook.mp4"))

    # 2) website scenes
    for i, sc in enumerate(script.get("scenes") or [], start=1):
        audio, secs = tts.speak(sc["voice"], work / f"s{i}")
        seconds = secs + 0.5
        try:
            shot, _, end_ratio = browser.capture_scene(sc["url"], work / f"shot{i}.png", orientation,
                                                       float(sc.get("scroll", 0.35) or 0), sc.get("highlight", ""))
            page_img, end_px = _prepare_page(shot, end_ratio, size)
        except browser.LoginRequired:
            raise
        except Exception as e:
            log.warning("capture failed for %s (%s) – using a text card instead", sc.get("url"), e)
            card = graphics.text_card(work / f"s{i}.jpg", size, sc.get("caption", ""), "")
            clips.append(ffmpeg.image_clip(card, audio, seconds, size, work / f"c{i:02d}.mp4"))
            continue
        overlay = graphics.caption_overlay(work / f"cap{i}.png", size, sc.get("caption", "")) if sc.get("caption") else None
        clips.append(ffmpeg.scroll_clip(page_img, end_px, audio, overlay, seconds, size, work / f"c{i:02d}.mp4"))

    # 3) outro card
    outro = script.get("outro") or {}
    audio, secs = tts.speak(outro.get("voice") or outro.get("title", ""), work / "outro")
    card = graphics.text_card(work / "outro.jpg", size, outro.get("title", ""), site, company().get("name", ""))
    clips.append(ffmpeg.image_clip(card, audio, secs + 0.8, size, work / "c99_outro.mp4"))

    joined = ffmpeg.concat(clips, work / "joined.mp4")

    # 4) optional background music
    music = sorted((ASSETS_DIR / "music").glob("*.mp3"))
    if (settings().get("video") or {}).get("background_music") and music:
        ffmpeg.add_music(joined, random.choice(music), out)
    else:
        shutil.move(str(joined), out)
    shutil.rmtree(work, ignore_errors=True)
    return out


def generate(plan: dict, day: date, item_id: int) -> dict:
    script = write_script(plan, day)
    orientation = (settings().get("video") or {}).get("orientation", "vertical")
    out = build(script, storage.video_paths(day, item_id, plan, "simple")[orientation], orientation)
    thumb = ffmpeg.thumbnail(out, storage.thumb_path(out), at=0.8)
    tags = [t if t.startswith("#") else f"#{t}" for t in script.get("hashtags", [])]
    return {"copy": script, "media": out, "thumb": thumb, "hashtags": " ".join(tags),
            "script_json": json.dumps(script, ensure_ascii=False, indent=2)}
