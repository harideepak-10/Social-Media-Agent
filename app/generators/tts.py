"""Text-to-speech for voice-overs.

Providers (env TTS_PROVIDER):
  edge     – Microsoft Edge neural voices via edge-tts (free, natural, needs internet)  [default]
  pyttsx3  – offline system voice (Windows SAPI) – robotic, used as automatic fallback
  silent   – no voice, timing estimated from word count (for testing the pipeline)
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..config import env, settings
from .ffmpeg import duration, run

log = logging.getLogger(__name__)


def speak(text: str, out: Path, voice: str | None = None) -> tuple[Path, float]:
    """Writes an audio file for `text`; returns (path, seconds)."""
    provider = env("TTS_PROVIDER", "edge").lower()
    voice = voice or (settings().get("video") or {}).get("voice", "en-IN-PrabhatNeural")
    out = out.with_suffix(".mp3")
    if provider == "edge":
        try:
            _edge(text, out, voice)
            return out, duration(out)
        except Exception as e:
            log.warning("edge-tts failed (%s) – falling back to offline voice", e)
            provider = "pyttsx3"
    if provider == "pyttsx3":
        try:
            _pyttsx3(text, out)
            return out, duration(out)
        except Exception as e:
            log.warning("pyttsx3 failed (%s) – using silent track", e)
    return _silent(text, out)


def _edge(text: str, out: Path, voice: str) -> None:
    import edge_tts

    async def _run():
        await edge_tts.Communicate(text, voice, rate="+8%").save(str(out))

    asyncio.run(_run())
    if not out.exists() or out.stat().st_size < 1000:
        raise RuntimeError("empty audio from edge-tts")


def _pyttsx3(text: str, out: Path) -> None:
    import pyttsx3

    wav = out.with_suffix(".wav")
    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    engine.save_to_file(text, str(wav))
    engine.runAndWait()
    run(["-i", str(wav), "-q:a", "3", str(out)])
    wav.unlink(missing_ok=True)


def _silent(text: str, out: Path) -> tuple[Path, float]:
    secs = max(1.5, len(text.split()) / 2.6)
    run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{secs:.2f}", "-q:a", "5", str(out)])
    return out, secs
