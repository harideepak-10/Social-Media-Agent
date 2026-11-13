"""Thin ffmpeg/ffprobe helpers (ffmpeg must be on PATH)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

def _find(name: str) -> str:
    """ffmpeg on PATH, or where winget installs it on Windows (PATH only refreshes in new terminals)."""
    found = shutil.which(name)
    if found:
        return found
    import os
    from glob import glob
    base = os.environ.get("LOCALAPPDATA", "")
    hits = glob(os.path.join(base, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "*", "bin", f"{name}.exe")) if base else []
    return hits[0] if hits else name


FFMPEG = _find("ffmpeg")
FFPROBE = _find("ffprobe")


class FFmpegError(RuntimeError):
    pass


def run(args: list[str]) -> None:
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed: {proc.stderr[-1500:]}")


def duration(path: Path) -> float:
    proc = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except Exception as e:
        raise FFmpegError(f"could not read duration of {path}: {proc.stderr}") from e


VIDEO_OUT = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]


def image_clip(image: Path, audio: Path, seconds: float, size: tuple[int, int], out: Path) -> Path:
    """Still image with slow zoom (Ken Burns) + voice-over."""
    w, h = size
    frames = int(seconds * 30) + 1
    vf = (f"scale={w * 2}:{h * 2},zoompan=z='min(zoom+0.0007,1.08)':x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=30")
    run(["-loop", "1", "-i", str(image), "-i", str(audio), "-vf", vf, "-t", f"{seconds:.2f}",
         "-af", "apad", *VIDEO_OUT, str(out)])
    return out


def scroll_clip(image: Path, end_px: int, audio: Path, overlay: Path | None, seconds: float,
                size: tuple[int, int], out: Path) -> Path:
    """Animated, eased camera scroll down a tall page image (already `size[0]` wide) + voice-over.

    Holds at the top for 0.6 s, glides down to `end_px`, then holds on the end position."""
    w, h = size
    T = max(seconds, 1.5)
    move = max(T - 1.4, 0.5)
    p = f"clip((t-0.6)/{move:.3f},0,1)"
    y = f"{end_px}*({p})*({p})*(3-2*({p}))"
    crop = f"crop={w}:{h}:0:'{y}'"
    args = ["-loop", "1", "-framerate", "30", "-i", str(image), "-i", str(audio)]
    if overlay:
        args += ["-i", str(overlay)]
        fc = f"[0:v]{crop},setsar=1,format=yuv420p[v0];[v0][2:v]overlay=0:0[v]"
    else:
        fc = f"[0:v]{crop},setsar=1,format=yuv420p[v]"
    run([*args, "-filter_complex", fc, "-map", "[v]", "-map", "1:a", "-af", "apad",
         "-t", f"{T:.2f}", *VIDEO_OUT, str(out)])
    return out


def concat(clips: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{c.resolve().as_posix()}'\n" for c in clips), encoding="utf-8")
    run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)])
    lst.unlink(missing_ok=True)
    return out


def add_music(video: Path, music: Path, out: Path, volume: float = 0.12) -> Path:
    run(["-i", str(video), "-stream_loop", "-1", "-i", str(music),
         "-filter_complex",
         f"[1:a]volume={volume},afade=t=in:d=1[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", str(out)])
    return out


def thumbnail(video: Path, out: Path, at: float = 1.0) -> Path:
    run(["-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out)])
    return out
