"""Results after posting: likes, comments, shares and reach from each platform, plus "what worked best".

- fetch_metrics(item): asks Facebook / Instagram / LinkedIn for the numbers of the posts this item made
  (post ids are stored in item.results by the publishers). Every number is best effort: a platform that
  refuses one metric (permissions, deprecated metric) still returns the others.
- refresh_recent(): every 6 hours for items published in the last 30 days.
- report(days): totals, top posts and averages by format / theme / product / kind / weekday.
- write_summary(): the AI reads the report and writes a short "what worked best" + tips. The newest tips are
  added to the planner's prompt so new content leans towards what performs.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import select

from . import llm
from .config import env
from .db import ContentItem, InsightSummary, get_session

log = logging.getLogger(__name__)
NUMBERS = ("likes", "comments", "shares", "reach", "views", "clicks")


# ── fetching ───────────────────────────────────────────────────────────────
def _get(client: httpx.Client, url: str, **params) -> dict:
    r = client.get(url, params=params or None, timeout=30)  # params={} would wipe a query already in `url`
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message") or r.json().get("message") or r.text
        except ValueError:
            msg = r.text
        raise RuntimeError(f"{r.status_code}: {str(msg)[:160]}")
    return r.json()


def _facebook(post_id: str, kind: str) -> dict:
    from .connections import graph_base, meta_creds
    token = meta_creds().get("page_token") or meta_creds().get("page_access_token") or ""
    out: dict = {}
    with httpx.Client() as c:
        base = graph_base()
        if kind == "video":  # page videos are posted to /videos -> a video id
            d = _get(c, f"{base}/{post_id}", access_token=token,
                     fields="likes.summary(true).limit(0),comments.summary(true).limit(0)")
            out["likes"] = (d.get("likes") or {}).get("summary", {}).get("total_count", 0)
            out["comments"] = (d.get("comments") or {}).get("summary", {}).get("total_count", 0)
            try:
                ins = _get(c, f"{base}/{post_id}/video_insights", access_token=token,
                           metric="total_video_views,total_video_impressions_unique")
                for m in ins.get("data", []):
                    v = (m.get("values") or [{}])[0].get("value", 0)
                    if m.get("name") == "total_video_views":
                        out["views"] = v
                    elif m.get("name") == "total_video_impressions_unique":
                        out["reach"] = v
            except RuntimeError as e:
                out.setdefault("_notes", []).append(f"views: {e}")
        else:
            d = _get(c, f"{base}/{post_id}", access_token=token,
                     fields="reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0),shares")
            out["likes"] = (d.get("reactions") or {}).get("summary", {}).get("total_count", 0)
            out["comments"] = (d.get("comments") or {}).get("summary", {}).get("total_count", 0)
            out["shares"] = (d.get("shares") or {}).get("count", 0)
            try:
                ins = _get(c, f"{base}/{post_id}/insights", access_token=token, metric="post_impressions_unique")
                for m in ins.get("data", []):
                    out["reach"] = (m.get("values") or [{}])[0].get("value", 0)
            except RuntimeError as e:
                out.setdefault("_notes", []).append(f"reach: {e}")
    return out


def _instagram(media_id: str, kind: str) -> dict:
    from .connections import instagram_target
    t = instagram_target()
    token = t.get("token", "")
    out: dict = {}
    with httpx.Client() as c:
        base = t.get("base", "")
        d = _get(c, f"{base}/{media_id}", access_token=token, fields="like_count,comments_count")
        out["likes"], out["comments"] = d.get("like_count", 0), d.get("comments_count", 0)
        for metric in ("reach", "views", "shares"):  # one call each: a refused metric must not hide the others
            try:
                ins = _get(c, f"{base}/{media_id}/insights", access_token=token, metric=metric)
                for m in ins.get("data", []):
                    out[metric] = (m.get("values") or [{}])[0].get("value", 0) if m.get("values") \
                        else (m.get("total_value") or {}).get("value", 0)
            except RuntimeError as e:
                out.setdefault("_notes", []).append(f"{metric}: {e}")
    return out


def _linkedin(urn: str, kind: str) -> dict:
    from .connections import li_api_base, linkedin_creds, linkedin_refresh_if_needed
    from .publishers.linkedin import _headers
    try:
        linkedin_refresh_if_needed()
    except Exception:
        pass
    org = linkedin_creds().get("org_id", "")
    out: dict = {}
    with httpx.Client(headers=_headers(json_body=False)) as c:
        base = li_api_base()
        try:
            d = _get(c, f"{base}/socialActions/{quote(urn, safe='')}")
            out["likes"] = (d.get("likesSummary") or {}).get("totalLikes", 0)
            out["comments"] = (d.get("commentsSummary") or {}).get("totalFirstLevelComments", 0)
        except RuntimeError as e:
            out.setdefault("_notes", []).append(f"likes/comments: {e}")
        field = "ugcPosts" if ":ugcPost:" in urn else "shares"
        try:
            # the List(...) syntax must stay unencoded apart from the URN itself
            url = (f"{base}/organizationalEntityShareStatistics?q=organizationalEntity"
                   f"&organizationalEntity={quote(f'urn:li:organization:{org}', safe='')}&{field}=List({quote(urn, safe='')})")
            d = _get(c, url)
            st = ((d.get("elements") or [{}])[0]).get("totalShareStatistics") or {}
            out["reach"] = st.get("uniqueImpressionsCount", st.get("impressionCount", 0))
            out["views"] = st.get("impressionCount", 0)
            out["clicks"] = st.get("clickCount", 0)
            out["shares"] = st.get("shareCount", 0)
            out.setdefault("likes", st.get("likeCount", 0))
            out.setdefault("comments", st.get("commentCount", 0))
        except RuntimeError as e:
            out.setdefault("_notes", []).append(f"reach: {e}")
    return out


FETCHERS = {"facebook": _facebook, "instagram": _instagram, "linkedin": _linkedin}


def fetch_metrics(item: ContentItem) -> dict:
    """{platform: {likes, comments, shares, reach, views, clicks, fetched_at, error?, notes?}} for one item."""
    from .publishers import status as connected
    live = connected()
    out = {}
    for platform, res in (item.results or {}).items():
        if not res.get("ok") or res.get("dry_run") or not res.get("id") or platform not in FETCHERS:
            continue
        if not live.get(platform):  # disconnected now – don't ask (and don't overwrite what we have)
            continue
        try:
            m = FETCHERS[platform](str(res["id"]), item.kind)
            notes = m.pop("_notes", [])
            m = {k: int(v or 0) for k, v in m.items() if k in NUMBERS}
            if notes:
                m["notes"] = "; ".join(notes)[:300]
            if not m.get("notes") and not any(k in m for k in NUMBERS):
                m["error"] = "No numbers returned"
            elif not any(k in m for k in NUMBERS):
                m["error"] = m.pop("notes")
        except Exception as e:
            m = {"error": str(e)[:300]}
        m["fetched_at"] = datetime.utcnow().isoformat() + "Z"
        out[platform] = m
    return out


def refresh_item(item_id: int) -> dict:
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if not item:
            return {}
        new = fetch_metrics(item)
        if new:
            merged = dict(item.metrics or {})
            for platform, m in new.items():
                if any(k in m for k in NUMBERS):
                    merged[platform] = m
                else:  # a failed fetch never wipes good numbers – keep them and show the problem
                    merged[platform] = {**merged.get(platform, {}), "error": m.get("error", "No numbers returned")}
            item.metrics = merged
            s.commit()
        return item.metrics


def refresh_recent(days: int = 30) -> int:
    """Refresh the numbers of everything published in the last `days` days (scheduler, every 6 h)."""
    since = datetime.utcnow() - timedelta(days=days)
    with get_session() as s:
        ids = s.scalars(select(ContentItem.id).where(ContentItem.status.in_(["published", "partial"]),
                                                     ContentItem.published_at >= since)).all()
    for item_id in ids:
        try:
            refresh_item(item_id)
        except Exception:
            log.exception("metrics refresh failed for #%s", item_id)
    return len(ids)


# ── reporting ──────────────────────────────────────────────────────────────
def totals(metrics: dict) -> dict:
    t = {k: 0 for k in NUMBERS}
    for m in (metrics or {}).values():
        for k in NUMBERS:
            t[k] += int(m.get(k, 0) or 0)
    t["engagement"] = t["likes"] + t["comments"] + t["shares"]
    return t


def report(days: int = 30) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    with get_session() as s:
        rows = s.scalars(select(ContentItem).where(ContentItem.status.in_(["published", "partial"]),
                                                   ContentItem.published_at >= since)
                         .order_by(ContentItem.published_at.desc())).all()
    posts = []
    for i in rows:
        t = totals(i.metrics)
        posts.append({"id": i.id, "kind": i.kind, "topic": i.topic, "format": i.format or "", "theme": i.theme or "",
                      "product": i.product or "", "source": i.source or "", "date": i.run_date.isoformat(),
                      "weekday": i.run_date.strftime("%A"), "thumb": i.thumb_path, "has_metrics": bool(i.metrics),
                      "per_platform": {p: {k: v for k, v in m.items() if k in NUMBERS} for p, m in (i.metrics or {}).items()},
                      **t})
    measured = [p for p in posts if p["has_metrics"]]
    total = {k: sum(p[k] for p in measured) for k in (*NUMBERS, "engagement")}

    def by(key: str) -> list[dict]:
        groups: dict[str, list] = defaultdict(list)
        for p in measured:
            if p[key]:
                groups[p[key]].append(p)
        out = [{"name": k, "posts": len(v), "avg_engagement": round(sum(x["engagement"] for x in v) / len(v), 1),
                "avg_reach": round(sum(x["reach"] for x in v) / len(v), 1)} for k, v in groups.items()]
        return sorted(out, key=lambda g: -g["avg_engagement"])

    per_platform = defaultdict(lambda: {k: 0 for k in NUMBERS})
    for p in measured:
        for plat, m in p["per_platform"].items():
            for k in NUMBERS:
                per_platform[plat][k] += m.get(k, 0)
    return {
        "days": days, "published": len(posts), "measured": len(measured), "totals": total,
        "per_platform": dict(per_platform),
        "top": sorted(measured, key=lambda p: -p["engagement"])[:5],
        "by_format": by("format"), "by_theme": by("theme"), "by_product": by("product"),
        "by_kind": by("kind"), "by_source": by("source"), "by_weekday": by("weekday"),
        "summary": latest_summary(),
    }


def latest_summary() -> dict | None:
    with get_session() as s:
        row = s.scalars(select(InsightSummary).order_by(InsightSummary.id.desc()).limit(1)).first()
        if not row:
            return None
        return {"text": row.summary, "tips": row.tips, "created_at": row.created_at.isoformat() + "Z", "days": row.days}


def write_summary(days: int = 30) -> dict | None:
    """AI 'what worked best' from the numbers. Needs a few measured posts to say anything useful."""
    rep = report(days)
    if rep["measured"] < 3:
        return None
    data = {k: rep[k] for k in ("totals", "per_platform", "by_format", "by_theme", "by_product", "by_kind",
                                "by_source", "by_weekday")}
    data["top_posts"] = [{k: p[k] for k in ("topic", "kind", "format", "theme", "product", "weekday", "engagement", "reach")}
                         for p in rep["top"]]
    out = llm.complete_json(
        "These are the real results of our company's social media posts from the last "
        f"{days} days ({rep['measured']} posts measured):\n{json.dumps(data, ensure_ascii=False)[:6000]}\n\n"
        "Write for a busy, non-technical marketing owner. Return JSON {\"summary\": \"3-5 short sentences: what worked "
        "best and what didn't, with the numbers that show it\", \"tips\": \"3 short, concrete instructions for the next "
        "posts (formats, topics, products, days) – one line each\"}. Only claim what the numbers support; "
        "if the sample is small, say so.",
        "You are a pragmatic social media analyst.", max_tokens=900)
    summary, tips = str(out.get("summary", "")).strip(), str(out.get("tips", "")).strip()
    if isinstance(out.get("tips"), list):
        tips = "\n".join(str(t) for t in out["tips"])
    if not summary:
        return None
    with get_session() as s:
        s.add(InsightSummary(days=days, summary=summary[:3000], tips=tips[:1500]))
        s.commit()
    return latest_summary()


def planner_hint() -> str:
    """Short 'what works' block for the planner prompt (empty until there are results)."""
    try:
        latest = latest_summary()
    except Exception:
        return ""
    if not latest or not latest.get("tips"):
        return ""
    return f"WHAT WORKED LATELY (from our real post results – lean towards this):\n{latest['tips'][:700]}"


def weekly_job() -> None:
    try:
        refresh_recent(30)
        write_summary(30)
    except Exception:
        log.exception("weekly insights failed")
