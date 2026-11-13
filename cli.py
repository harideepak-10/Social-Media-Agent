"""Command line helpers.

  python cli.py serve                      # dashboard + scheduler on http://localhost:8000
  python cli.py generate                   # generate today's content (per schedule)
  python cli.py generate --date 2026-11-24 --kind post
  python cli.py generate --days 7          # test: generate the next 7 days at once (per schedule)
  python cli.py login                      # log in to your web app once (session reused daily)
  python cli.py login --url https://app.example.com    # log in to any other site that needs it
  python cli.py from-url https://anywebsite.com                     # explainer video for ANY website
  python cli.py from-url https://anywebsite.com --kind post --notes "focus on pricing"
  python cli.py publish 12                 # publish item #12 (must be approved)
  python cli.py research                   # show what the agent sees: site, trends, festivals
  python cli.py doctor                     # health check before going live
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

try:  # emoji in Windows console output
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    g = sub.add_parser("generate")
    g.add_argument("--date", default="")
    g.add_argument("--kind", choices=["video", "post"], default=None)
    g.add_argument("--days", type=int, default=1, help="generate this many days starting at --date")
    p = sub.add_parser("publish")
    p.add_argument("item_id", type=int)
    sub.add_parser("research")
    dr = sub.add_parser("doctor")
    dr.add_argument("--quick", action="store_true", help="skip the AI / voice test calls")
    lg = sub.add_parser("login")
    lg.add_argument("--url", default=None)
    fu = sub.add_parser("from-url")
    fu.add_argument("url")
    fu.add_argument("--kind", choices=["video", "post"], default="video")
    fu.add_argument("--notes", default="", help="optional focus, e.g. 'explain the booking feature'")
    args = ap.parse_args()

    from app.db import init_db
    init_db()

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("app.main:app", host=args.host, port=args.port)
    elif args.cmd == "generate":
        from app import pipeline
        start = date.fromisoformat(args.date) if args.date else pipeline.today()
        for i in range(args.days):
            day = start + timedelta(days=i)
            item = pipeline.generate_for(day, args.kind, force=True)
            if item:
                print(f"\n{day:%a %d %b} #{item.id} [{item.status}] {item.kind} ({item.source}): {item.topic}"
                      f"\nmedia: {item.media_path}\n{item.error}")
            else:
                print(f"\n{day:%a %d %b}: nothing scheduled")
    elif args.cmd == "publish":
        from app import pipeline
        item = pipeline.publish_item(args.item_id)
        print(item.status, item.results)
    elif args.cmd == "doctor":
        from app.doctor import run
        sys.exit(0 if run(full=not args.quick) else 1)
    elif args.cmd == "login":
        from app.generators.browser import interactive_login
        interactive_login(args.url)
    elif args.cmd == "from-url":
        from app import pipeline
        item = pipeline.generate_from_url(args.url, args.kind, args.notes)
        print(f"\n#{item.id} [{item.status}] {item.kind}: {item.topic}\nmedia: {item.media_path}\n{item.error}")
    elif args.cmd == "research":
        from app.research import calendar, trends, website
        from app.generators.planner import kind_for
        print("=== WEBSITE ===\n", website.summary()[:3000])
        print("\n=== TRENDS ===\n", trends.as_text())
        today = date.today()
        print("\n=== NEXT 7 DAYS ===")
        for i in range(7):
            d = today + timedelta(days=i)
            print(f"{d:%a %d %b}: {kind_for(d):6} {', '.join(calendar.festivals_on(d))}")


if __name__ == "__main__":
    main()
