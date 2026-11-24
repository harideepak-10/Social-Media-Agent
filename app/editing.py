"""Edit a finished item without making a new one.

Posters: the design is kept as HTML (posters/source/<name>.html). The dashboard edits its text in the browser and
sends the HTML back; we re-render it (≈10 s) into a new file version and swap it in.

Videos: the storyboard (texts, voice lines, theme) and the captured screens are kept in videos/source/<name>/.
The dashboard edits texts / picks another voice; the video is rebuilt from that (on this server, or queued for
the PC worker when VIDEO_RENDERER=pc).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from PIL import Image

from . import pipeline, progress, storage
from .config import company, settings
from .db import ContentItem, get_session

log = logging.getLogger(__name__)
EDITABLE_STATUSES = ("pending_approval", "approved", "failed", "rejected", "partial", "outline")


class EditError(Exception):
    pass


# ── posters ────────────────────────────────────────────────────────────────
def poster_html(item: ContentItem) -> str:
    if item.kind != "post" or not item.media_path:
        raise EditError("Only posts have an editable design")
    ref = storage.media_ref_for(storage.poster_source_key(item.media_path), like=item.media_path)
    html = storage.read_text_ref(ref)
    if not html:
        raise EditError("This poster was made before text editing was available – use Regenerate instead")
    return html


def _restore_logo(html: str, work: Path, theme_name: str) -> None:
    """Older designs refer to logo.png in the (deleted) work folder – put the current brand logo back."""
    if "logo.png" not in html:
        return
    from .creative import assets
    from .creative.catalog import POST_THEMES
    logo = assets.brand_logo(company())
    if logo:
        key = (POST_THEMES.get(theme_name) or {}).get("logo", "dark")
        src = logo.get(key) or next(iter(v for v in logo.values() if isinstance(v, (str, Path))), None)
        if src:
            shutil.copy(src, work / "logo.png")


def save_poster(item_id: int, html: str) -> tuple[ContentItem, list[str]]:
    from .creative import post_designer, quality
    if len(html) > 8_000_000 or "<html" not in html.lower():
        raise EditError("That doesn't look like a complete poster design")
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if not item or item.kind != "post":
            raise EditError("Item not found")
        if item.status not in EDITABLE_STATUSES:
            raise EditError(f"Can't edit an item that is {item.status}")
        old_media, theme, captions, tags, topic, platforms = (item.media_path, item.theme, item.captions,
                                                              item.hashtags, item.topic, item.platform_list)
    work = storage.WORK_DIR / f"edit_{item_id}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        _restore_logo(html, work, theme)
        preview = work / "render.png"
        issues = post_designer.render_design(html, work, preview)
        stem = storage.next_version(storage.ref_stem(old_media))
        out = storage.POSTERS_DIR / f"{stem}.jpg"
        Image.open(preview).convert("RGB").save(out, quality=94)
        src = storage.POSTER_SOURCES_DIR / f"{stem}.html"
        src.write_text(post_designer.inline_assets(html, work), encoding="utf-8")
        new_ref = storage.persist(out)
        storage.save_file(src, storage.poster_source_key(str(out)), like=new_ref)
        qa = {}
        try:
            qa = quality.check("post", {"media": out, "copy": {"captions": captions}, "hashtags": tags},
                               platforms, topic, work / "qa")
        except Exception as e:
            log.warning("quality check after edit failed: %s", e)
        with get_session() as s:
            item = s.get(ContentItem, item_id)
            item.media_path = item.thumb_path = new_ref
            if qa:
                item.quality = qa
            s.commit()
            s.refresh(item)
        if new_ref != old_media:
            storage.delete_media(old_media)  # also removes its old HTML source
        return item, issues
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── videos ─────────────────────────────────────────────────────────────────
def source_loc(item: ContentItem) -> tuple[str, str]:
    """(storage prefix, reference "like") of a video's storyboard – the finished video's, or the outline's."""
    if item.kind == "video" and item.media_path:
        return storage.video_source_prefix(item.media_path), item.media_path
    ref = item.options.get("outline_ref") if item.kind == "video" else ""
    if ref:
        return storage.outline_prefix(item.id), ref
    raise EditError("Only videos have a storyboard")


def _source_dir(item: ContentItem, work: Path) -> Path:
    """Bring storyboard.json + screens of this video into `work` (from the cloud if needed)."""
    prefix, like = source_loc(item)
    work.mkdir(parents=True, exist_ok=True)
    ref = storage.media_ref_for(f"{prefix}/storyboard.json", like=like)
    text = storage.read_text_ref(ref)
    if not text:
        raise EditError("This video was made before scene editing was available – use Regenerate instead")
    (work / "storyboard.json").write_text(text, encoding="utf-8")
    for sc in json.loads(text).get("scenes") or []:
        f = (sc.get("_block") or {}).get("file")
        if f and not (work / f).exists():
            local = storage.local_file(storage.media_ref_for(f"{prefix}/{f}", like=like))
            shutil.copy(local, work / f)
    return work


def storyboard(item_id: int) -> dict:
    from .creative import video_studio
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if not item:
            raise EditError("Item not found")
        work = storage.WORK_DIR / f"sb_{item_id}"
        try:
            board, theme, product = video_studio.load_source(_source_dir(item, work))
            prefix, like = source_loc(item)
            for sc in board.get("scenes") or []:
                b = sc.pop("_block", None) or {}
                f = b.get("file")
                sc["screen"] = storage.web_url(storage.media_ref_for(f"{prefix}/{f}", like=like)) if f else ""
                sc["screen_tall"] = bool(b.get("h", 0) > 2 * max(1, b.get("w", 1)))
                sc.setdefault("type", "feature")
            board["voice_name"] = board.get("voice_name") or (settings().get("video") or {}).get("voice", "")
            board["_seconds"] = video_studio.estimate_seconds(board)
            return {"board": board, "theme": theme, "product": product}
        finally:
            shutil.rmtree(work, ignore_errors=True)


def rewrite(item_id: int, part: str, instruction: str) -> dict:
    from .creative import video_studio
    if not re.fullmatch(r"(festive|intro|grid|outro|scene:\d+)", part):
        raise EditError("Unknown part")
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if not item:
            raise EditError("Item not found")
        work = storage.WORK_DIR / f"sb_{item_id}"
        try:
            board, _, _ = video_studio.load_source(_source_dir(item, work))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return video_studio.rewrite_part(board, part, instruction)


TEXT_LIMIT = 400


def save_storyboard(item_id: int, edits: dict, voice_name: str, render: bool = True) -> ContentItem:
    """Apply text edits, scene order/removal + voice, store the new storyboard and start (or queue) the
    rebuild. For an outline, render=False only saves it ("Save outline"); render=True is "Make video"."""
    from .creative import video_studio
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        if not item or item.kind != "video":
            raise EditError("Item not found")
        if item.status not in EDITABLE_STATUSES:
            raise EditError(f"Can't edit an item that is {item.status}")
        work = storage.WORK_DIR / f"sb_{item_id}"
        try:
            src = _source_dir(item, work)
            board = json.loads((src / "storyboard.json").read_text(encoding="utf-8"))

            def apply(dst: dict, new: dict, kind: str):
                for k in video_studio.EDITABLE[kind]:
                    if k in (new or {}):
                        dst[k] = str(new[k])[:TEXT_LIMIT]
                if kind == "scene" and isinstance((new or {}).get("bullets"), list):
                    dst["bullets"] = [{"icon": str(b.get("icon", "check"))[:20], "text": str(b.get("text", ""))[:160]}
                                      for b in new["bullets"][:5] if isinstance(b, dict)]
                if kind == "scene" and isinstance((new or {}).get("steps"), list):
                    dst["steps"] = [{"icon": str(b.get("icon", "check"))[:20], "title": str(b.get("title", ""))[:60],
                                     "desc": str(b.get("desc", ""))[:120]}
                                    for b in new["steps"][:6] if isinstance(b, dict) and b.get("title")] or dst.get("steps")

            for kind in ("festive", "intro", "grid", "outro"):
                if kind in edits and isinstance(board.get(kind), dict):
                    apply(board[kind], edits[kind], kind)
            for i, sc in enumerate(edits.get("scenes") or []):
                if i < len(board.get("scenes") or []):
                    apply(board["scenes"][i], sc, "scene")
            order = edits.get("order")
            if isinstance(order, list):  # new order of the ORIGINAL scene numbers; a missing number = removed
                old = board.get("scenes") or []
                keep = [int(i) for i in order if str(i).lstrip("-").isdigit() and 0 <= int(i) < len(old)]
                keep = list(dict.fromkeys(keep))
                if not keep:
                    raise EditError("Keep at least one scene")
                board["scenes"] = [old[i] for i in keep]
            if "grid" in edits and edits["grid"] is None:
                board.pop("grid", None)
            from .generators import tts
            board["voice_name"] = tts.english_voice((voice_name or "").strip()[:60])
            (src / "storyboard.json").write_text(json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8")
            prefix, like = source_loc(item)
            storage.save_file(src / "storyboard.json", f"{prefix}/storyboard.json", like=like)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if item.status == "outline" and not render:
            s.refresh(item)
            return item
        item.job, item.error, item.progress = ("render" if item.status == "outline" else "rebuild"), "", 0
        first = item.job == "render"
        if pipeline.video_on_pc():
            item.status, item.worker = "queued", ""
            item.stage = "Waiting for your PC to make this video" if first else "Waiting for your PC to rebuild this video"
        else:
            item.status, item.worker = "generating", pipeline.worker_name()
            item.stage = "Making the video from your outline" if first else "Rebuilding with your edits"
        s.commit()
        s.refresh(item)
        return item


def rebuild_video(item_id: int) -> ContentItem | None:
    """Re-render an edited video from its stored storyboard (runs on the server or the PC worker)."""
    from .creative import quality, video_studio
    from .generators import ffmpeg
    progress.bind(item_id)
    with get_session() as s:
        item = s.get(ContentItem, item_id)
        old = {"media": item.media_path, "alt": item.media_alt_path, "thumb": item.thumb_path}
        captions, tags, topic, platforms = item.captions, item.hashtags, item.topic, item.platform_list
        first = not item.media_path  # an approved outline: the video is made for the first time
        old_prefix, old_like = source_loc(item)
        run_date = item.run_date
        work = storage.WORK_DIR / f"rebuild_{item_id}"
        shutil.rmtree(work, ignore_errors=True)
        src = _source_dir(item, work / "src")
    try:
        with pipeline._lock:
            progress.report("Loading your edited storyboard", 5)
            board, theme, product = video_studio.load_source(src)
            for sc in board.get("scenes") or []:  # screens must sit next to the scene HTML
                b = sc.get("_block")
                if b and b.get("path"):
                    shutil.copy(b["path"], work / Path(b["path"]).name)
            vcfg = settings().get("video") or {}
            orientations = vcfg.get("formats") or ["landscape", "vertical"]
            if first:
                base = storage.base_name(run_date, item_id, {"topic": topic.split(":", 1)[-1]}, "walkthrough")
            else:
                base = storage.next_version(re.sub(r"_(16x9|9x16|1x1)$", "", storage.ref_stem(old["media"])))
            targets = {"landscape": storage.VIDEOS_DIR / f"{base}_16x9.mp4",
                       "vertical": storage.VIDEOS_DIR / f"{base}_9x16.mp4"}
            files = video_studio.build(board, theme or "amber_noir", work, targets, product, orientations,
                                       bool(vcfg.get("voiceover", True)), board.get("voice_name") or None)
            main = files[orientations[0]]
            alt = files.get("vertical") if orientations[0] != "vertical" else None
            thumb = ffmpeg.thumbnail(main, storage.thumb_path(main), at=1.6)
            progress.report("Checking the new version", 97)
            qa = {}
            try:
                qa = quality.check("video", {"media": main, "alt": alt, "copy": {"captions": captions}, "hashtags": tags},
                                   platforms, topic, work / "qa")
            except Exception as e:
                log.warning("quality check after rebuild failed: %s", e)
            progress.check()
            progress.report("Saving files", 98)
            new_media = storage.persist(main)
            new_alt = storage.persist(alt) if alt else ""
            new_thumb = storage.persist(thumb)
            # the storyboard + screens follow the new file name
            new_prefix = storage.video_source_prefix(str(main))
            storage.save_file(src / "storyboard.json", f"{new_prefix}/storyboard.json", like=new_media)
            for f in src.iterdir():
                if f.name != "storyboard.json":
                    storage.save_file(f, f"{new_prefix}/{f.name}", like=new_media)
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                item.media_path, item.media_alt_path, item.thumb_path = new_media, new_alt, new_thumb
                item.status, item.stage, item.progress, item.job, item.error = "pending_approval", "", 100, "", ""
                if qa:
                    item.quality = qa
                s.commit()
            for ref in (old["media"], old["alt"], old["thumb"]):
                if ref and ref not in (new_media, new_alt, new_thumb):
                    storage.delete_media(ref)
            if old["media"]:
                storage.delete_video_source(old["media"])
            else:  # the outline's own copy
                storage.delete_video_source(old_like, prefix=old_prefix)
            with get_session() as s:
                item = s.get(ContentItem, item_id)
                if first:
                    opts = item.options
                    opts.pop("outline_ref", None)
                    item.options = opts
                    s.commit()
                    pipeline._notify_new(item)
                return item
    except progress.Stopped:
        log.info("rebuild of #%s stopped by the user", item_id)
        with get_session() as s:
            item = s.get(ContentItem, item_id)
            if first:  # back to the outline, nothing is lost
                item.status, item.stage, item.error = "outline", "", ""
            item.job = ""
            s.commit()
            return item
    except Exception as e:
        log.exception("rebuild failed")
        with get_session() as s:
            item = s.get(ContentItem, item_id)
            # the previous files are untouched – go back to them
            if first:
                item.status, item.stage, item.job = "outline", "", ""
                item.error = f"Making the video failed – your outline is kept, try again. ({str(e)[:300]})"
            else:
                item.status, item.stage, item.job = "pending_approval", "", ""
                item.error = f"Rebuilding with your edits failed – the previous version is kept. ({str(e)[:300]})"
            s.commit()
            return item
    finally:
        shutil.rmtree(work, ignore_errors=True)
