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


def _activity(src: Path, work: Path, secs: float) -> list[float]:
    """How much the screen changes in each second (small grey frames, 1 per second)."""
    d = work / "probe"
    d.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-i", str(src), "-t", str(min(secs, MAX_SECONDS)), "-vf", "fps=2,scale=160:-2,format=gray",
                str(d / "p%04d.png")])
    frames = sorted(d.glob("p*.png"))
    out, prev = [], None
    for f in frames:
        im = Image.open(f).convert("L")
        out.append(ImageStat.Stat(ImageChops.difference(im, prev)).mean[0] if prev is not None and prev.size == im.size else 0.0)
        prev = im
    # per second (2 probes per second)
    return [sum(out[i:i + 2]) for i in range(0, len(out), 2)]


def _windows(act: list[float], secs: float, n: int) -> list[tuple[float, float]]:
    """The busiest non-overlapping CLIP_S windows, in time order. Quiet stretches (nothing moves) are skipped."""
    if secs <= CLIP_S + 1.5:
        return [(0.0, secs)]
    span = int(round(CLIP_S))
    scores = [(sum(act[s:s + span]), s) for s in range(0, max(1, int(secs - CLIP_S)) + 1)]
    best = max((sc for sc, _ in scores), default=0) or 1
    picked: list[int] = []
    for sc, s in sorted(scores, reverse=True):
        if len(picked) >= n or sc < best * 0.15:
            break
        if all(abs(s - p) >= CLIP_S for p in picked):
            picked.append(s)
    if not picked:  # a static recording: just take evenly spaced moments
        step = secs / n
        picked = [int(i * step) for i in range(n)]
    out = []
    for s in sorted(picked):  # start ~1 s before the first movement in the window (not on a still screen)
        win = act[s:s + span] or [0]
        top = max(win) or 1
        first = next((i for i, v in enumerate(win) if v >= top * 0.1), 0)
        a = max(0.0, min(s + first - 1.0, secs - CLIP_S))
        if out and a < out[-1][1]:
            a = out[-1][1]
        if secs - a >= 2.5:
            out.append((a, min(secs, a + CLIP_S)))
    return out


def clips(path: Path, caption: str, rec_no: int, work: Path, max_clips: int = MAX_CLIPS) -> list[dict]:
    """Cut one recording into up to `max_clips` candidate clips (silent H.264, WIDTH px, FPS)."""
    work.mkdir(parents=True, exist_ok=True)
    secs = min(ffmpeg.duration(path), MAX_SECONDS)
    act = _activity(path, work, secs)
    out = []
    for k, (a, b) in enumerate(_windows(act, secs, max_clips)):
        clip = work / f"rec{rec_no}_clip{k}.mp4"
        ffmpeg.run(["-ss", f"{a:.2f}", "-i", str(path), "-t", f"{b - a:.2f}", "-an",
                    "-vf", f"fps={FPS},scale={WIDTH}:-2:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "22", "-pix_fmt", "yuv420p", str(clip)])
        poster = work / f"rec{rec_no}_clip{k}.jpg"  # the frame after the action (what the AI judges the clip by)
        ffmpeg.run(["-ss", f"{(b - a) * 0.75:.2f}", "-i", str(clip), "-frames:v", "1", "-q:v", "3", str(poster)])
        with Image.open(poster) as im:
            w, h = im.size
        label = caption or "the user's screen recording"
        out.append({"id": f"R{rec_no}c{k}", "path": poster, "w": w, "h": h, "page": "",
                    "text": f"{label} – moving clip {k + 1} ({a:.0f}s–{b:.0f}s of the recording)",
                    "clip_path": clip, "clip_s": round(b - a, 2), "user": True})
    log.info("recording %s: %.0fs -> %s clip(s)", path.name, secs, len(out))
    return out


def frames(clip: Path, dest: Path) -> int:
    """Clip -> JPEG frames for the frame-by-frame renderer. Returns the frame count."""
    dest.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-i", str(clip), "-vf", f"fps={FPS}", "-q:v", "3", str(dest / "f%04d.jpg")])
    return len(list(dest.glob("f*.jpg")))


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in (".mp4", ".mov", ".webm", ".mkv")


__all__ = ["clips", "frames", "is_video", "FPS"]
