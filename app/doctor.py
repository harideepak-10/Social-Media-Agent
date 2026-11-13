"""`python cli.py doctor` — checks everything the agent needs before going live."""
from __future__ import annotations

import importlib
import sys
import time

OK, WARN, FAIL = "✅", "⚠️ ", "❌"


def _line(icon: str, name: str, detail: str = "") -> str:
    print(f"{icon} {name}{' — ' + detail if detail else ''}")
    return icon


def run(full: bool = True) -> bool:
    results = []
    print("\nDigital Marketing Agent — health check\n" + "─" * 44)

    # Python & packages
    v = sys.version_info
    results.append(_line(OK if v >= (3, 10) else FAIL, "Python", f"{v.major}.{v.minor}.{v.micro}"
                         + ("" if v >= (3, 10) else " (need 3.10 or newer)")))
    missing = []
    for mod in ("fastapi", "uvicorn", "sqlalchemy", "apscheduler", "httpx", "bs4", "feedparser", "holidays",
                "anthropic", "edge_tts", "PIL", "playwright", "yaml", "dotenv", "jinja2"):
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(mod)
    results.append(_line(FAIL if missing else OK, "Python packages",
                         f"missing: {', '.join(missing)} → run setup_windows.bat" if missing else "all installed"))
    if missing:
        return False

    from .config import ASSETS_DIR, env, settings
    from .generators import ffmpeg

    # ffmpeg
    try:
        import subprocess
        out = subprocess.run([ffmpeg.FFMPEG, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        results.append(_line(OK, "ffmpeg", out[:60]))
    except Exception:
        results.append(_line(FAIL, "ffmpeg", "not found → run setup_windows.bat, then open a NEW terminal"))

    # Chromium
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        results.append(_line(OK, "Chromium (Playwright)", "launches"))
    except Exception as e:
        results.append(_line(FAIL, "Chromium (Playwright)", f"{str(e)[:120]} → run: python -m playwright install chromium"))

    # LLM
    key = env("ANTHROPIC_API_KEY")
    if env("LLM_PROVIDER", "anthropic") == "anthropic" and not key:
        results.append(_line(FAIL, "Anthropic API key", "ANTHROPIC_API_KEY is empty in .env"))
    elif full:
        from . import llm
        for label, design in (("AI model", False), ("AI design model", True)):
            try:
                t = time.time()
                txt = llm.complete("Reply with the single word OK.", max_tokens=5, temperature=0, design=design)
                model = env("ANTHROPIC_DESIGN_MODEL" if design else "ANTHROPIC_MODEL", "")
                results.append(_line(OK if "ok" in txt.lower() else WARN, label, f"{model} answered in {time.time() - t:.1f}s"))
            except Exception as e:
                results.append(_line(FAIL, label, str(e)[:160]))

    # Voice
    if env("TTS_PROVIDER", "edge") == "edge" and full:
        try:
            from pathlib import Path
            import tempfile
            from .generators import tts
            with tempfile.TemporaryDirectory() as d:
                _, secs = tts.speak("Hello from Krypsos.", Path(d) / "t")
            results.append(_line(OK if secs > 0.5 else WARN, "AI voice (edge-tts)", f"{secs:.1f}s sample"))
        except Exception as e:
            results.append(_line(WARN, "AI voice (edge-tts)", f"{str(e)[:100]} — videos will be silent"))

    # Internet resources
    import httpx
    site = (settings().get("company") or {}).get("website", "")
    for name, url, icon_fail in (("Company website", site, FAIL),
                                 ("Google Fonts", "https://fonts.googleapis.com/css2?family=Manrope", WARN),
                                 ("Google Trends feed", "https://trends.google.com/trending/rss?geo=IN", WARN)):
        try:
            r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            results.append(_line(OK if r.status_code < 400 else icon_fail, name, f"{url} → {r.status_code}"))
        except Exception as e:
            results.append(_line(icon_fail, name, f"{url} unreachable ({type(e).__name__})"))

    # Brand assets
    logo = ASSETS_DIR / "logo.png"
    results.append(_line(OK if logo.exists() else WARN, "Logo",
                         "assets/logo.png" if logo.exists() else "not yet — captured from the website on first run "
                         "(better: put your transparent PNG at assets/logo.png)"))
    music = list((ASSETS_DIR / "music").glob("*.mp3"))
    results.append(_line(OK if music else WARN, "Background music",
                         f"{len(music)} track(s)" if music else "none in assets/music/ — videos will have voice only"))

    # Settings
    sch = settings().get("schedule") or {}
    plan = ", ".join(f"{d[:3].title()}={k}" for d, k in sch.items())
    results.append(_line(OK, "Weekly plan", plan))
    results.append(_line(OK, "Daily times", f"prepare {settings().get('generate_time')} · publish {settings().get('publish_time')} "
                                            f"({settings().get('timezone')})"))
    if env("DASHBOARD_PASSWORD", "change-me") == "change-me":
        results.append(_line(WARN, "Dashboard password", "still 'change-me' — set DASHBOARD_PASSWORD in .env"))
    from . import publishers
    st = publishers.status()
    results.append(_line(OK, "Publishing", ", ".join(f"{k}: {'live' if v else 'dry-run'}" for k, v in st.items())))

    print("─" * 44)
    ok = FAIL not in results
    print("Ready to go live! Start it with run_agent.bat" if ok else "Fix the ❌ items above, then run this again.")
    return ok
