"""`python cli.py doctor` — checks everything the agent needs before going live."""
from __future__ import annotations

import os
import importlib
import sys
import threading
import time

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
_LEVEL = {OK: "ok", WARN: "warn", FAIL: "fail"}
_collected: list[dict] | None = None
_quiet = False


def _where() -> str:
    return "Render → Environment" if os.environ.get("RENDER") else ".env"


def _line(icon: str, name: str, detail: str = "") -> str:
    if _collected is not None:
        _collected.append({"name": name, "status": _LEVEL[icon], "detail": detail})
    if not _quiet:
        print(f"{icon} {name}{' — ' + detail if detail else ''}")
    return icon


_checks_lock = threading.Lock()


def checks(full: bool = False) -> list[dict]:
    """Same checks as `cli.py doctor`, returned as [{name, status: ok|warn|fail, detail}] for the dashboard.
    One at a time: the results are collected in module state, and a quick + full check running together
    would wipe each other's list (the dashboard then got `checks: null`)."""
    global _collected, _quiet
    with _checks_lock:
        _collected, _quiet = [], True
        try:
            _run(full)
            return list(_collected)
        finally:
            _collected, _quiet = None, False


def run(full: bool = True) -> bool:
    return _run(full)


def _run(full: bool) -> bool:
    results = []
    if not _quiet:
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
        results.append(_line(FAIL, "Anthropic API key", f"ANTHROPIC_API_KEY is empty – add it in {_where()}"))
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
            r = httpx.get(url, timeout=8, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            results.append(_line(OK if r.status_code < 400 else icon_fail, name, f"{url} → {r.status_code}"))
        except Exception as e:
            results.append(_line(icon_fail, name, f"{url} unreachable ({type(e).__name__})"))

    # Database & cloud storage
    try:
        from sqlalchemy import text as _t
        from .db import engine, is_cloud_db
        with engine.connect() as conn:
            conn.execute(_t("SELECT 1"))
        if is_cloud_db():
            results.append(_line(OK, "Database", "cloud Postgres (DATABASE_URL)"))
        elif os.environ.get("RENDER"):
            results.append(_line(FAIL, "Database", "local SQLite – wiped on every deploy/restart. Set DATABASE_URL in Render → Environment"))
        else:
            results.append(_line(OK, "Database", "SQLite file agent.db (local)"))
    except Exception as e:
        results.append(_line(FAIL, "Database", f"cannot connect: {str(e)[:140]}"))
    from . import storage
    if storage.remote_enabled():
        try:
            storage._ensure_bucket()
            results.append(_line(OK, "File storage", f"Supabase bucket '{env('SUPABASE_BUCKET', 'media')}' (public)"))
        except Exception as e:
            hint = storage.key_problem()
            results.append(_line(FAIL, "File storage", f"SUPABASE_SERVICE_KEY: {hint}" if hint else f"Supabase: {str(e)[:140]}"))
    else:
        if os.environ.get("RENDER"):
            results.append(_line(FAIL, "File storage", "local disk – files wiped on every deploy. Set SUPABASE_URL + SUPABASE_SERVICE_KEY in Render → Environment"))
        else:
            results.append(_line(OK, "File storage", "local media/ folder"))

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
        results.append(_line(WARN, "Dashboard password", f"still 'change-me' — set DASHBOARD_PASSWORD in {_where()}"))
    from . import publishers
    st = publishers.status()
    results.append(_line(OK, "Publishing", ", ".join(f"{k}: {'live' if v else 'dry-run'}" for k, v in st.items())))
    from . import pipeline
    if pipeline.video_on_pc():
        try:
            from . import worker
            w = worker.status()
            if w["online"]:
                results.append(_line(OK, "Video maker", f"your PC '{w['name']}' is online ({w['state'] or 'idle'})"))
            else:
                seen = f"last seen {w['last_seen'][:16].replace('T', ' ')} UTC" if w["last_seen"] else "never connected"
                results.append(_line(WARN, "Video maker", f"your PC is offline ({seen}) – videos wait until you start run_video_worker.bat"))
        except Exception as e:
            results.append(_line(WARN, "Video maker", f"can't read the PC status: {str(e)[:100]}"))
    elif os.environ.get("RENDER") and env("LOW_MEMORY", ""):
        results.append(_line(WARN, "Video maker", "this 512 MB server – videos may run out of memory. Set VIDEO_RENDERER=pc and run run_video_worker.bat on your PC"))

    ok = FAIL not in results
    if not _quiet:
        print("─" * 44)
        print("Ready to go live! Start it with run_agent.bat" if ok else "Fix the ❌ items above, then run this again.")
    return ok
