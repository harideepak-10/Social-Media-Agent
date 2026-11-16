"""Facebook Page + Instagram Business publishing via the Meta Graph API.

Docs:
  FB photos  – POST /{page-id}/photos          (source=file upload)
  FB videos  – POST /{page-id}/videos          (source=file upload)  [graph-video host]
  IG image   – POST /{ig-user-id}/media (image_url) -> /media_publish
  IG reel    – POST /{ig-user-id}/media (media_type=REELS, video_url) -> poll status -> /media_publish
Instagram downloads media from a PUBLIC URL, so PUBLIC_BASE_URL must be reachable from the internet.
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from ..config import env, public_url


def _v() -> str:
    return env("META_GRAPH_VERSION", "v21.0")


def _check(r: httpx.Response) -> dict:
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Meta API error {r.status_code}: {data.get('error', data)}")
    return data


def fb_configured() -> bool:
    return bool(env("META_PAGE_ID") and env("META_PAGE_ACCESS_TOKEN"))


def ig_configured() -> bool:
    return bool(env("META_IG_USER_ID") and env("META_PAGE_ACCESS_TOKEN"))


def facebook_publish(kind: str, media: Path, caption: str) -> str:
    page, token = env("META_PAGE_ID"), env("META_PAGE_ACCESS_TOKEN")
    with httpx.Client(timeout=600) as c, open(media, "rb") as f:
        if kind == "video":
            r = c.post(f"https://graph-video.facebook.com/{_v()}/{page}/videos",
                       data={"description": caption, "access_token": token},
                       files={"source": (media.name, f, "video/mp4")})
        else:
            r = c.post(f"https://graph.facebook.com/{_v()}/{page}/photos",
                       data={"caption": caption, "access_token": token},
                       files={"source": (media.name, f, "image/jpeg")})
    data = _check(r)
    return str(data.get("post_id") or data.get("id"))


def instagram_publish(kind: str, media: Path, caption: str, url: str | None = None) -> str:
    ig, token = env("META_IG_USER_ID"), env("META_PAGE_ACCESS_TOKEN")
    base = f"https://graph.facebook.com/{_v()}/{ig}"
    url = url or public_url(media)  # cloud storage URL when available, else served by this app
    if "localhost" in url or "127.0.0.1" in url:
        raise RuntimeError("Instagram needs a public media URL – set PUBLIC_BASE_URL to your deployed app URL")
    params = {"caption": caption[:2200], "access_token": token}
    if kind == "video":
        params |= {"media_type": "REELS", "video_url": url, "share_to_feed": "true"}
    else:
        params |= {"image_url": url}
    with httpx.Client(timeout=120) as c:
        container = _check(c.post(f"{base}/media", data=params))["id"]
        # wait until Instagram has processed the media
        for _ in range(60):
            st = _check(c.get(f"https://graph.facebook.com/{_v()}/{container}",
                              params={"fields": "status_code,status", "access_token": token}))
            if st.get("status_code") == "FINISHED":
                break
            if st.get("status_code") == "ERROR":
                raise RuntimeError(f"Instagram processing failed: {st.get('status')}")
            time.sleep(10)
        else:
            raise RuntimeError("Instagram processing timed out")
        pub = _check(c.post(f"{base}/media_publish", data={"creation_id": container, "access_token": token}))
    return str(pub["id"])
