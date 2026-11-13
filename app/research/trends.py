"""Current market / social trends from public feeds (no API key needed)."""
from __future__ import annotations

import logging
from urllib.parse import quote_plus

import feedparser
import httpx

from ..config import company, settings

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (DigitalMarketingAgent/1.0)"}


def _fetch_feed(url: str):
    try:
        r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except Exception as e:  # network / parse issues should never break generation
        log.warning("feed failed %s: %s", url, e)
        return None


def google_trending(limit: int = 15) -> list[dict]:
    """Today's top Google searches for the configured country."""
    geo = settings().get("trends_geo", "IN")
    feed = _fetch_feed(f"https://trends.google.com/trending/rss?geo={geo}")
    out = []
    for e in (feed.entries if feed else [])[:limit]:
        out.append({"title": e.get("title", ""), "traffic": e.get("ht_approx_traffic", "")})
    return out


def industry_news(limit: int = 10) -> list[dict]:
    """Latest news headlines for the company's industry (Google News RSS)."""
    q = quote_plus(f"{company().get('industry', 'technology')} trends")
    geo = settings().get("trends_geo", "IN")
    feed = _fetch_feed(f"https://news.google.com/rss/search?q={q}&hl=en-{geo}&gl={geo}&ceid={geo}:en")
    return [{"title": e.get("title", ""), "link": e.get("link", "")} for e in (feed.entries if feed else [])[:limit]]


def snapshot() -> dict:
    return {"trending_searches": google_trending(), "industry_news": industry_news()}


def as_text(snap: dict | None = None) -> str:
    snap = snap or snapshot()
    lines = ["TRENDING SEARCHES TODAY:"]
    lines += [f"- {t['title']} ({t['traffic']})" for t in snap["trending_searches"]] or ["- (unavailable)"]
    lines.append("INDUSTRY NEWS:")
    lines += [f"- {n['title']}" for n in snap["industry_news"]] or ["- (unavailable)"]
    return "\n".join(lines)
