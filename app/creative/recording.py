"""Screen recordings uploaded on "Create from URL": find the moments where something happens and cut them into short,
silent clips that play inside the browser window of a video scene.

Runs on the PC worker (ffmpeg + Pillow only). Each clip becomes a "block" like a captured screen, so the AI picks it
from the contact sheet the same way: {id "R0c2", path (poster frame), w, h, text, clip_path, clip_s}."""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from ..generators import ffmpeg

log = logging.getLogger(__name__)

WIDTH = 1280          # clips are scaled to this width (the browser window in a scene is ~1040 px)
FPS = 15              # screen recordings look smooth at 15 fps and the frames stay light
CLIP_S = 6.5          # length of one clip
MAX_CLIPS = 6         # per recording
MAX_SECONDS = 305     # recordings can be up to 5 minutes


def is_blank(im: Image.Image) -> bool:
    """An empty screen: one flat colour (white page scrolled past the content, black, loading screen)."""
    g = im.convert("L")
    if g.width > 160:
        g = g.resize((160, max(1, round(g.height * 160 / g.width))))
    lo, hi = g.getextrema()
    return hi - lo < 14 or ImageStat.Stat(g).stddev[0] < 3.0


def _activity(src: Path, work: Path, secs: float) -> tuple[list[float], list[bool]]:
    """How much the screen changes in each second, and which seconds show an empty screen."""
    d = work / "probe"
    d.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-i", str(src), "-t", str(min(secs, MAX_SECONDS)), "-vf", "fps=2,scale=160:-2,format=gray",
                str(d / "p%04d.png")])
    frames = sorted(d.glob("p*.png"))
    out, blanks, prev = [], [], None
    for f in frames:
        im = Image.open(f).convert("L")
        out.append(ImageStat.Stat(ImageChops.difference(im, prev)).mean[0] if prev is not None and prev.size == im.size else 0.0)
        blanks.append(is_blank(im))
        prev = im
    # per second (2 probes per second); a second is empty when both probes are
    return ([sum(out[i:i + 2]) for i in range(0, len(out), 2)],
            [all(blanks[i:i + 2]) for i in range(0, len(blanks), 2)])


def _windows(act: list[float], secs: float, n: int, blank: list[bool] | None = None) -> list[tuple[float, float]]:
    """The busiest non-overlapping moments (up to CLIP_S each), in time order. Clips never contain an empty screen:
    they are taken only from stretches where something is on screen, and quiet stretches score nothing."""
    total = max(1, int(secs + 0.999))
    blank = (blank or []) + [False] * (total - len(blank or []))
    act = act + [0.0] * (total - len(act))
    # stretches of seconds with something on screen
    runs, start = [], None
    for k in range(total + 1):
        ok = k < total and not blank[k]
        if ok and start is None:
            start = k
        if not ok and start is not None:
            runs.append((start, min(k, secs)))
            start = None
    cands = []
    for a0, b0 in runs:
        length = b0 - a0
        if length < 2.5:
            continue
        span = min(CLIP_S, length)
        s = float(a0)
        while s + span <= b0 + 1e-6:
            score = sum(act[int(s) + 1:int(s + span)])  # change INTO the window's first second doesn't count
            cands.append((score, s, s + span))
            s += 1.0
    if not cands:
        return []
    best = max(c[0] for c in cands) or 1
    picked: list[tuple[float, float]] = []
    for score, a, b in sorted(cands, key=lambda c: (-c[0], c[1])):
        if len(picked) >= n:
            break
        if score < best * 0.15 and picked:
            break
        if all(b <= pa or a >= pb for pa, pb in picked):
            picked.append((a, b))
    return sorted(picked)


def _focus(clip: Path, work: Path) -> list[float] | None:
    """Where on screen the action is in this clip (the area that keeps changing), as [x, y, w, h] fractions –
    for the spotlight. None when the whole screen changes (page switch) or nothing does."""
    d = work / f"focus_{clip.stem}"
    d.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-i", str(clip), "-vf", "fps=4,scale=320:-2,format=gray", str(d / "f%03d.png")])
    frames = [Image.open(f).convert("L") for f in sorted(d.glob("f*.png"))]
    if len(frames) < 3:
        return None
    w, h = frames[0].size
    acc = Image.new("L", (w, h), 0)
    changes = 0
    for a, b in zip(frames, frames[1:]):
        diff = ImageChops.difference(a, b).point(lambda v: 40 if v > 18 else 0)
        box = diff.getbbox()
        if not box or (box[2] - box[0]) * (box[3] - box[1]) > w * h * 0.8:  # nothing, or a full page change
            continue
        acc = ImageChops.add(acc, diff)
        changes += 1
    box = acc.point(lambda v: 255 if v >= 80 else 0).getbbox() or acc.getbbox()  # changed in >= 2 frames
    if not changes or not box:
        return None
    x0, y0, x1, y1 = box
    pad_x, pad_y = w * 0.04, h * 0.05
    x0, y0, x1, y1 = max(0, x0 - pad_x), max(0, y0 - pad_y), min(w, x1 + pad_x), min(h, y1 + pad_y)
    if (x1 - x0) * (y1 - y0) > w * h * 0.7 or (x1 - x0) < w * 0.12 or (y1 - y0) < h * 0.08:
        return None
    return [round(x0 / w, 4), round(y0 / h, 4), round((x1 - x0) / w, 4), round((y1 - y0) / h, 4)]


def clips(path: Path, caption: str, rec_no: int, work: Path, max_clips: int = MAX_CLIPS) -> list[dict]:
    """Cut one recording into up to `max_clips` candidate clips (silent H.264, WIDTH px, FPS)."""
    work.mkdir(parents=True, exist_ok=True)
    secs = min(ffmpeg.duration(path), MAX_SECONDS)
    act, blank = _activity(path, work, secs)
    out = []
    for k, (a, b) in enumerate(_windows(act, secs, max_clips, blank)):
        clip = work / f"rec{rec_no}_clip{k}.mp4"
        ffmpeg.run(["-ss", f"{a:.2f}", "-i", str(path), "-t", f"{b - a:.2f}", "-an",
                    "-vf", f"fps={FPS},scale={WIDTH}:-2:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "22", "-pix_fmt", "yuv420p", str(clip)])
        poster = work / f"rec{rec_no}_clip{k}.jpg"  # the frame after the action (what the AI judges the clip by)
        ffmpeg.run(["-ss", f"{(b - a) * 0.75:.2f}", "-i", str(clip), "-frames:v", "1", "-q:v", "3", str(poster)])
        with Image.open(poster) as im:
            w, h = im.size
            empty = is_blank(im)
        if empty:  # the moment ends on an empty screen – not worth showing
            log.info("clip %s skipped: empty screen", clip.name)
            continue
        try:
            focus = _focus(clip, work)
        except Exception as e:
            log.debug("focus of %s failed: %s", clip.name, e)
            focus = None
        label = caption or "the user's screen recording"
        out.append({"id": f"R{rec_no}c{k}", "path": poster, "w": w, "h": h, "page": "",
                    "text": f"{label} – moving clip {k + 1} ({a:.0f}s–{b:.0f}s of the recording)",
                    "clip_path": clip, "clip_s": round(b - a, 2), "user": True, "focus": focus})
    log.info("recording %s: %.0fs -> %s clip(s)", path.name, secs, len(out))
    return out


def frames(clip: Path, dest: Path) -> int:
    """Clip -> JPEG frames for the frame-by-frame renderer. Returns how many to play: an empty screen at the end is
    cut off, and a clip that is mostly empty plays nothing (0)."""
    dest.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-i", str(clip), "-vf", f"fps={FPS}", "-q:v", "3", str(dest / "f%04d.jpg")])
    files = sorted(dest.glob("f*.jpg"))
    empty, spread = [], []
    for f in files:
        with Image.open(f) as im:
            im.draft("L", (160, 90))  # fast JPEG decode at low size
            empty.append(is_blank(im))
            spread.append(ImageStat.Stat(im.convert("L")).stddev[0])
    if spread:  # "nearly empty": far less on screen than usual in this clip (scrolled past the content)
        typical = sorted(spread)[len(spread) // 2] or 1
        empty = [e or v < typical * 0.35 for e, v in zip(empty, spread)]
    if not files or sum(empty) > len(files) * 0.4:
        return 0
    n = len(files)
    while n > FPS and empty[n - 1]:
        n -= 1
    return n


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in (".mp4", ".mov", ".webm", ".mkv")


__all__ = ["clips", "frames", "is_video", "FPS"]
