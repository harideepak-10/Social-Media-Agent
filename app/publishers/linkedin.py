"""LinkedIn Company Page publishing via the versioned REST API (Posts, Images, Videos).

Needs an access token with `w_organization_social` for an admin of the page
(LinkedIn "Community Management API" product).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import env

def _creds() -> dict:
    from ..connections import linkedin_creds
    return linkedin_creds()


def _token() -> str:
    return _creds().get("access_token", "")


def configured() -> bool:
    c = _creds()
    return bool(c.get("access_token") and c.get("org_id"))


def _api() -> str:
    from ..connections import li_api_base
    return li_api_base()


def _headers(json_body: bool = True) -> dict:
    h = {
        "Authorization": f"Bearer {_token()}",
        "LinkedIn-Version": env("LINKEDIN_API_VERSION", "202510"),
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _check(r: httpx.Response) -> httpx.Response:
    if r.status_code >= 400:
        raise RuntimeError(f"LinkedIn API error {r.status_code}: {r.text[:500]}")
    return r


def _owner() -> str:
    return f"urn:li:organization:{_creds().get('org_id', '')}"


def _upload_image(c: httpx.Client, media: Path) -> str:
    init = _check(c.post(f"{_api()}/images?action=initializeUpload", headers=_headers(),
                         json={"initializeUploadRequest": {"owner": _owner()}})).json()["value"]
    _check(c.put(init["uploadUrl"], content=media.read_bytes(),
                 headers={"Authorization": f"Bearer {_token()}"}))
    return init["image"]


def _upload_video(c: httpx.Client, media: Path) -> str:
    size = media.stat().st_size
    init = _check(c.post(f"{_api()}/videos?action=initializeUpload", headers=_headers(), json={
        "initializeUploadRequest": {"owner": _owner(), "fileSizeBytes": size,
                                    "uploadCaptions": False, "uploadThumbnail": False}})).json()["value"]
    video_urn = init["video"]
    etags = []
    with open(media, "rb") as f:
        for part in init["uploadInstructions"]:
            f.seek(part["firstByte"])
            chunk = f.read(part["lastByte"] - part["firstByte"] + 1)
            r = _check(c.put(part["uploadUrl"], content=chunk,
                             headers={"Content-Type": "application/octet-stream"}))
            etags.append(r.headers.get("etag", "").strip('"'))
    _check(c.post(f"{_api()}/videos?action=finalizeUpload", headers=_headers(), json={
        "finalizeUploadRequest": {"video": video_urn, "uploadToken": init.get("uploadToken", ""),
                                  "uploadedPartIds": etags}}))
    # wait for processing
    for _ in range(60):
        st = _check(c.get(f"{_api()}/videos/{quote(video_urn, safe='')}", headers=_headers()))
        status = st.json().get("status")
        if status == "AVAILABLE":
            break
        if status == "PROCESSING_FAILED":
            raise RuntimeError("LinkedIn video processing failed")
        time.sleep(10)
    return video_urn


def publish(kind: str, media: Path, caption: str, title: str = "") -> str:
    try:
        from ..connections import linkedin_refresh_if_needed
        linkedin_refresh_if_needed()
    except Exception:
        pass  # the post attempt below reports a clear error if the token is invalid
    with httpx.Client(timeout=600) as c:
        urn = _upload_video(c, media) if kind == "video" else _upload_image(c, media)
        body = {
            "author": _owner(),
            "commentary": _escape(caption)[:3000],
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "content": {"media": {"id": urn, "title": title[:200]} if kind == "video" else {"id": urn}},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        r = _check(c.post(f"{_api()}/posts", headers=_headers(), json=body))
    return r.headers.get("x-restli-id", "")


def _escape(text: str) -> str:
    """LinkedIn 'little text' format reserves these characters."""
    for ch in "\\|{}@[]()<>#*_~":
        text = text.replace(ch, "\\" + ch)
    # keep hashtags clickable
    return re.sub(r"\\#(\w+)", r"{hashtag|\\#|\1}", text)
