"""Quality check of a finished post or video, before it goes to the approval queue.

1. Technical checks (no AI): right size, not blank, video length, audio track, captions present and within limits.
2. AI check: the model looks at the poster (or frames sampled from the video) together with the captions,
   like an editor would, and lists concrete problems.
Never blocks the item – the result is shown on the item so the reviewer knows what to look at.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageStat

from .. import llm, progress
from ..config import company, settings
from ..generators import ffmpeg

log = logging.getLogger(__name__)

POST_SIZE = (1080, 1350)
VIDEO_SIZES = {"landscape": (1920, 1080), "vertical": (1080, 1920)}
NAMES = {"linkedin": "LinkedIn", "instagram": "Instagram", "facebook": "Facebook"}
CAPTION_LIMITS = {"instagram": 2200, "facebook": 5000, "linkedin": 3000}
PLACEHOLDER = re.compile(r"lorem ipsum|\[(company|product|name|link|url)\]|\{\{|TODO|INSERT ", re.I)


def _check(name: str, ok: bool, detail: str = "", warn: bool = False) -> dict:
    return {"name": name, "status": "ok" if ok else ("warn" if warn else "fail"), "detail": detail}


def _blank(im: Image.Image) -> bool:
    """Almost a single colour (empty render, black frame)."""
    st = ImageStat.Stat(im.convert("L").resize((64, 64)))
    return st.stddev[0] < 6


def _probe(path: Path) -> dict:
    out = subprocess.run([ffmpeg.FFPROBE, "-v", "error", "-show_entries",
                          "stream=codec_type,width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True)
    return json.loads(out.stdout or "{}")


def _frames(video: Path, n: int, out_dir: Path, tag: str) -> list[Path]:
    dur = ffmpeg.duration(video)
    frames = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        f = out_dir / f"qa_{tag}_{i}.jpg"
        subprocess.run([ffmpeg.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=640:-2", str(f)], capture_output=True)
        if f.exists():
            frames.append(f)
    return frames


def _grid(frames: list[Path], out: Path, cols: int) -> Path:
    ims = [Image.open(f).convert("RGB") for f in frames]
    w, h = ims[0].size
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), "white")
    for i, im in enumerate(ims):
        sheet.paste(im.resize((w, h)), ((i % cols) * w, (i // cols) * h))
    sheet.save(out, quality=85)
    return out


def _caption_checks(captions: dict, hashtags: str, platforms: list[str]) -> list[dict]:
    out = []
    for p in platforms:
        text = (captions or {}).get(p, "")
        full = f"{text}\n\n{hashtags}".strip()
        if not text.strip():
            out.append(_check(f"{NAMES.get(p, p.title())} caption", False, "missing"))
        elif len(full) > CAPTION_LIMITS.get(p, 3000):
            out.append(_check(f"{NAMES.get(p, p.title())} caption", False, f"{len(full)} characters – limit is {CAPTION_LIMITS[p]}"))
        elif PLACEHOLDER.search(text):
            out.append(_check(f"{NAMES.get(p, p.title())} caption", False, "contains placeholder text"))
        else:
            out.append(_check(f"{NAMES.get(p, p.title())} caption", True, f"{len(full)} characters"))
    n = len([t for t in hashtags.split() if t.startswith("#")])
    out.append(_check("Hashtags", 1 <= n <= 30, f"{n} hashtags", warn=True))
    return out


def _ai_review(images: list[Path], kind: str, captions: dict, topic: str) -> dict:
    brand = company().get("name", "")
    what = ("this social media poster" if kind == "post" else
            "frames sampled in order from this marketing video (left→right, top→bottom; "
            "the last row may be the vertical 9:16 version)")
    prompt = (
        f"You are the final quality check before {what} is published for the brand '{brand}'. Topic: {topic!r}.\n"
        f"Captions:\n{json.dumps(captions, ensure_ascii=False)[:3000]}\n\n"
        "Check strictly but practically and list ONLY concrete problems a reviewer must fix:\n"
        "- text clipped, cut off at the edges, overlapping, or too small/low-contrast to read\n"
        "- spelling mistakes or broken words in the visual\n"
        "- blank, black or broken frames/sections, missing images, broken mockups\n"
        "- wrong or misspelled brand/product name\n"
        "- caption doesn't match what the visual shows, or makes a doubtful claim (fake numbers, guarantees)\n"
        "Return JSON {\"score\": 1-10, \"summary\": \"one sentence\", \"problems\": [\"...\"]}. "
        "9-10 = publish-ready, 7-8 = minor issues, below 7 = must fix.")
    data = llm.complete_json(prompt, "You are a meticulous senior editor and art director.",
                             max_tokens=900, images=images)
    try:
        score = max(1, min(10, int(data.get("score", 0)))) or None
    except (TypeError, ValueError):
        score = None
    return {"score": score, "summary": str(data.get("summary", ""))[:300],
            "problems": [str(p)[:300] for p in (data.get("problems") or []) if p][:8]}


def check(kind: str, gen: dict, platforms: list[str], topic: str, work: Path) -> dict:
    """gen: the generator result (media, alt, thumb, copy, hashtags)."""
    progress.report("AI quality check", 97)
    work.mkdir(parents=True, exist_ok=True)
    checks: list[dict] = []
    review_images: list[Path] = []
    media = Path(gen["media"]) if gen.get("media") else None

    if not media or not media.exists() or media.stat().st_size < 10_000:
        checks.append(_check("File", False, "missing or empty"))
    elif kind == "post":
        im = Image.open(media)
        checks.append(_check("Size", im.size == POST_SIZE, f"{im.size[0]}×{im.size[1]}", warn=True))
        checks.append(_check("Not blank", not _blank(im), "has content" if not _blank(im) else "looks empty"))
        review_images = [media]
    else:
        vcfg = settings().get("video") or {}
        max_s = int(vcfg.get("max_seconds", 75))
        for label, path, size in (("16:9", media, VIDEO_SIZES["landscape"]),
                                  ("9:16", Path(gen["alt"]) if gen.get("alt") else None, VIDEO_SIZES["vertical"])):
            if not path:
                continue
            info = _probe(path)
            streams = info.get("streams", [])
            v = next((x for x in streams if x.get("codec_type") == "video"), {})
            dur = float((info.get("format") or {}).get("duration") or 0)
            checks.append(_check(f"Video {label} size", (v.get("width"), v.get("height")) == size,
                                 f"{v.get('width')}×{v.get('height')}", warn=True))
            checks.append(_check(f"Video {label} length", 8 <= dur <= max_s + 15, f"{dur:.0f}s"))
            if vcfg.get("voiceover", True):
                checks.append(_check(f"Video {label} sound", any(x.get("codec_type") == "audio" for x in streams),
                                     "has audio" if any(x.get("codec_type") == "audio" for x in streams) else "no audio track"))
            frames = _frames(path, 6 if label == "16:9" else 3, work, label.replace(":", "x"))
            blanks = sum(_blank(Image.open(f)) for f in frames)
            checks.append(_check(f"Video {label} frames", blanks == 0, f"{blanks} blank of {len(frames)} sampled"
                                 if blanks else f"{len(frames)} sampled, none blank", warn=blanks == 1))
            if label == "16:9" and frames:
                review_images.append(_grid(frames, work / "qa_grid_16x9.jpg", 3))
            elif frames:
                review_images.append(_grid(frames, work / "qa_grid_9x16.jpg", 3))

    checks += _caption_checks((gen.get("copy") or {}).get("captions", {}), gen.get("hashtags", ""), platforms)

    ai = {"score": None, "summary": "", "problems": []}
    if review_images and llm.vision_available():
        try:
            ai = _ai_review(review_images, kind, (gen.get("copy") or {}).get("captions", {}), topic)
        except progress.Stopped:
            raise
        except Exception as e:  # the check must never lose a finished item
            log.warning("AI quality review failed: %s", e)
            ai["summary"] = f"AI review couldn't run: {str(e)[:150]}"

    fails = [c for c in checks if c["status"] == "fail"]
    passed = not fails and (ai["score"] is None or ai["score"] >= 7)
    return {"passed": passed, "score": ai["score"], "summary": ai["summary"], "problems": ai["problems"],
            "checks": checks}
