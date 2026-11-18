"""Where generated files are saved.

media/
  posters/            2026-11-18_restaurant-pos_before-after_12.jpg
    source/           …the HTML each poster was designed from (open in a browser to tweak)
  videos/             2026-11-20_clinic_promo_14_16x9.mp4  +  …_9x16.mp4
  thumbnails/         video cover images used by the dashboard
  .work/              temporary files while rendering (cleaned up automatically)
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .config import MEDIA_DIR

POSTERS_DIR = MEDIA_DIR / "posters"
POSTER_SOURCES_DIR = POSTERS_DIR / "source"
VIDEOS_DIR = MEDIA_DIR / "videos"
THUMBS_DIR = MEDIA_DIR / "thumbnails"
WORK_DIR = MEDIA_DIR / ".work"

for _d in (POSTERS_DIR, POSTER_SOURCES_DIR, VIDEOS_DIR, THUMBS_DIR, WORK_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len].rstrip("-") or "content"


def base_name(day: date, item_id: int, plan: dict | None = None, label: str = "") -> str:
    """e.g. 2026-11-18_restaurant-pos_before-after_12"""
    plan = plan or {}
    what = (plan.get("product") or {}).get("name") or plan.get("topic") or plan.get("source") or ""
    parts = [f"{day:%Y-%m-%d}", slug(what, 30)]
    if label:
        parts.append(slug(label, 20))
    parts.append(str(item_id))
    return "_".join(p for p in parts if p)


def poster_path(day: date, item_id: int, plan: dict | None = None, label: str = "") -> Path:
    return POSTERS_DIR / f"{base_name(day, item_id, plan, label)}.jpg"


def poster_source_path(poster: Path) -> Path:
    return POSTER_SOURCES_DIR / f"{poster.stem}.html"


def video_paths(day: date, item_id: int, plan: dict | None = None, label: str = "") -> dict[str, Path]:
    name = base_name(day, item_id, plan, label)
    return {"landscape": VIDEOS_DIR / f"{name}_16x9.mp4", "vertical": VIDEOS_DIR / f"{name}_9x16.mp4",
            "square": VIDEOS_DIR / f"{name}_1x1.mp4"}


def thumb_path(video: Path) -> Path:
    return THUMBS_DIR / f"{video.stem.rsplit('_', 1)[0]}.jpg"


def work_dir(kind: str, item_id: int) -> Path:
    d = WORK_DIR / f"{kind}_{item_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def organize_existing() -> int:
    """Move files from the old layout (media/<date>/post_12.jpg …) into the new folders and fix the DB."""
    import shutil
    from datetime import date as _date

    from .db import ContentItem, get_session

    moved = 0
    with get_session() as s:
        for item in s.query(ContentItem).all():
            plan = {"product": {"name": item.product}, "topic": item.topic, "source": item.source}
            changes = {}
            for attr in ("media_path", "media_alt_path", "thumb_path"):
                old = Path(getattr(item, attr) or "")
                if not old.is_file() or old.parent in (POSTERS_DIR, VIDEOS_DIR, THUMBS_DIR):
                    continue
                if attr == "thumb_path" and item.kind == "post":
                    continue  # posts use the poster itself as thumbnail
                if item.kind == "post":
                    new = poster_path(item.run_date or _date.today(), item.id, plan, item.format)
                elif attr == "thumb_path":
                    new = THUMBS_DIR / f"{base_name(item.run_date, item.id, plan, 'promo')}.jpg"
                else:
                    paths = video_paths(item.run_date, item.id, plan, "promo")
                    new = paths["vertical"] if attr == "media_alt_path" or "vertical" in old.stem else paths["landscape"]
                shutil.move(str(old), new)
                changes[attr] = str(new)
                moved += 1
                html = old.with_suffix(".html")
                if item.kind == "post" and html.is_file():
                    shutil.move(str(html), poster_source_path(new))
            if item.kind == "post" and "media_path" in changes:
                changes["thumb_path"] = changes["media_path"]
            for k, v in changes.items():
                setattr(item, k, v)
        s.commit()
    # remove empty dated folders left behind
    for d in MEDIA_DIR.iterdir():
        if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name):
            try:
                d.rmdir()
            except OSError:
                pass
    return moved


# ── Cloud file storage (Supabase Storage) ─────────────────────────────────
# Set SUPABASE_URL + SUPABASE_SERVICE_KEY (+ optional SUPABASE_BUCKET, default "media") and every finished
# poster/video/thumbnail is uploaded to a public bucket. The database then stores the public URL, so
# files survive restarts and Instagram can fetch them directly. Without these settings files stay local.
import logging as _logging
import mimetypes as _mt

import httpx as _httpx

from .config import ASSETS_DIR, env

_log = _logging.getLogger(__name__)
_bucket_ready = False


def remote_enabled() -> bool:
    return bool(env("SUPABASE_URL") and env("SUPABASE_SERVICE_KEY"))


def _sb() -> tuple[str, str, dict]:
    # Accept the URL however it was copied (e.g. ".../rest/v1/" from the Data API page): keep only https://<ref>.supabase.co
    from urllib.parse import urlsplit
    u = urlsplit(env("SUPABASE_URL").strip().strip('"'))
    base = f"{u.scheme or 'https'}://{u.netloc or u.path.split('/')[0]}"
    key = env("SUPABASE_SERVICE_KEY").strip().strip('"')
    headers = {"apikey": key}
    if key.startswith("eyJ"):  # classic service_role JWT; new sb_secret_… keys go in the apikey header only
        headers["Authorization"] = f"Bearer {key}"
    return base, env("SUPABASE_BUCKET", "media"), headers


def _ensure_bucket() -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    base, bucket, h = _sb()
    r = _httpx.get(f"{base}/storage/v1/bucket/{bucket}", headers=h, timeout=30)
    if r.status_code == 200:
        if not r.json().get("public"):
            _httpx.put(f"{base}/storage/v1/bucket/{bucket}", headers=h, timeout=30,
                       json={"id": bucket, "name": bucket, "public": True})
    else:
        r = _httpx.post(f"{base}/storage/v1/bucket", headers=h, timeout=30,
                        json={"id": bucket, "name": bucket, "public": True})
        if r.status_code >= 400 and "already exists" not in r.text.lower():
            raise RuntimeError(f"Supabase: could not create bucket '{bucket}': {r.status_code} {r.text[:200]}")
    _bucket_ready = True


def remote_url(key: str) -> str:
    base, bucket, _ = _sb()
    return f"{base}/storage/v1/object/public/{bucket}/{key}"


def upload(local: Path, key: str) -> str:
    """Upload a file to the bucket (overwrites) and return its public URL."""
    _ensure_bucket()
    base, bucket, h = _sb()
    ctype = _mt.guess_type(local.name)[0] or "application/octet-stream"
    with open(local, "rb") as f:
        r = _httpx.post(f"{base}/storage/v1/object/{bucket}/{key}", content=f.read(), timeout=600,
                        headers={**h, "Content-Type": ctype, "x-upsert": "true", "cache-control": "3600"})
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase upload failed for {key}: {r.status_code} {r.text[:300]}")
    return remote_url(key)


def delete_remote(key: str) -> None:
    if not remote_enabled():
        return
    base, bucket, h = _sb()
    _httpx.request("DELETE", f"{base}/storage/v1/object/{bucket}", headers=h, json={"prefixes": [key]}, timeout=60)


def list_remote(prefix: str) -> list[str]:
    _ensure_bucket()
    base, bucket, h = _sb()
    r = _httpx.post(f"{base}/storage/v1/object/list/{bucket}", headers=h, timeout=60,
                    json={"prefix": prefix, "limit": 1000, "offset": 0})
    r.raise_for_status()
    return [f"{prefix.rstrip('/')}/{o['name']}" for o in r.json() if o.get("id")]  # folders have no id


def persist(path: Path | str | None) -> str:
    """Finished media file -> what the database stores: a public URL (cloud) or the local path."""
    if not path:
        return ""
    p = Path(path)
    if not remote_enabled() or not p.is_file():
        return str(path)
    try:
        key = p.resolve().relative_to(MEDIA_DIR.resolve()).as_posix()
    except ValueError:
        key = f"misc/{p.name}"
    try:
        return upload(p, key)
    except Exception as e:  # keep working locally if the upload fails
        _log.warning("upload to Supabase failed, keeping local file: %s", e)
        return str(path)


def is_url(ref: str | None) -> bool:
    return bool(ref) and str(ref).startswith(("http://", "https://"))


def local_file(ref: str | Path) -> Path:
    """A local copy of a stored media file (downloads it from the bucket if needed)."""
    if not is_url(str(ref)):
        return Path(ref)
    name = str(ref).split("/storage/v1/object/public/", 1)[-1].split("/", 1)[-1]
    dest = WORK_DIR / "downloads" / name
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with _httpx.stream("GET", str(ref), timeout=600, follow_redirects=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    return dest


def web_url(ref: str | None) -> str:
    """URL the dashboard uses: the public cloud URL, or /media/… for local files."""
    if not ref:
        return ""
    if is_url(ref):
        return str(ref)
    try:
        return "/media/" + Path(ref).resolve().relative_to(MEDIA_DIR.resolve()).as_posix()
    except ValueError:
        return ""


def display_path(ref: str | None, data_dir: Path) -> str:
    """Where a file lives, for people: media/posters/… or supabase:media/posters/…"""
    if not ref:
        return ""
    if is_url(ref):
        return "supabase: " + str(ref).split("/storage/v1/object/public/", 1)[-1]
    try:
        return Path(ref).resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return Path(ref).name


# brand assets (logo + music) — also kept in the bucket in cloud mode
def persist_brand_file(local: Path) -> None:
    if remote_enabled():
        rel = local.resolve().relative_to(ASSETS_DIR.resolve()).as_posix()
        upload(local, f"brand/{rel}")


def delete_brand_file(rel: str) -> None:
    delete_remote(f"brand/{rel}")


def sync_brand_assets() -> int:
    """On start-up in the cloud: download the logo and music uploaded earlier."""
    if not remote_enabled():
        return 0
    n = 0
    try:
        keys = list_remote("brand") + list_remote("brand/music")
        for key in keys:
            rel = key.split("/", 1)[1]
            dest = ASSETS_DIR / rel
            if dest.suffix and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                r = _httpx.get(remote_url(key), timeout=300)
                if r.status_code == 200:
                    dest.write_bytes(r.content)
                    n += 1
    except Exception as e:
        _log.warning("brand asset sync from Supabase failed: %s", e)
    return n
