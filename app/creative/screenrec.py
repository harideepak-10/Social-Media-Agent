"""Screen recordings -> a product tour (the way a person would edit one).

A raw recording is a person clicking through their app: splash, sign-in, dashboard, inbox, tasks ...
This module finds those PAGES in it (the screen changes a lot = navigation), takes one crisp still of each page once it
has finished loading, finds the panels / card groups on that still to spotlight (image analysis, no website needed),
remembers where in the sidebar the person clicked to get there, and keeps short "action" clips where something happens
in place (typing a request, signing in). tour.py then turns that into the same full-screen spotlight tour it makes from
a website link – in the recording's own colours.

Pure Pillow (no numpy / OpenCV), so the PC worker needs nothing new."""
from __future__ import annotations

import logging
from collections import Counter, deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from ..generators import ffmpeg
from . import recording

log = logging.getLogger(__name__)

PROBE_FPS = 4          # analysis frames per second
PW, PH = 480, 270      # analysis size
MOVING = 0.18          # structure (edges) changed this much within 1 s = the page is changing (navigation, loading)
SAME_PAGE = 0.30       # two page stills whose structure differs less than this are the same page
MIN_PAGE_S = 1.0       # shorter calm stretches are transitions / loading animations
MAX_SECONDS = 305


# ── analysis ────────────────────────────────────────────────────────────────
class Probe:
    """The recording at PROBE_FPS, kept light in memory (a 5-minute recording = 1,200 probes): small grey frames for
    colour changes, 1-bit edge maps for structure; the full-colour probe is read from disk only when needed."""
    def __init__(self, files: list[Path]):
        self.files = files
        self.gray, self.edges = [], []
        for f in files:
            with Image.open(f) as im:
                rgb = im.convert("RGB")
            self.edges.append(_edges(rgb))
            self.gray.append(rgb.convert("L").resize((PW // 2, PH // 2)))

    def __len__(self):
        return len(self.files)

    def rgb(self, i: int) -> Image.Image:
        with Image.open(self.files[i]) as im:
            return im.convert("RGB")


def _probe(src: Path, work: Path, secs: float) -> Probe:
    d = work / "probe"
    d.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["-i", str(src), "-t", f"{min(secs, MAX_SECONDS):.2f}", "-vf",
                f"fps={PROBE_FPS},scale={PW}:{PH}:force_original_aspect_ratio=disable", str(d / "p%05d.png")])
    return Probe(sorted(d.glob("p*.png")))


def _edges(im: Image.Image) -> Image.Image:
    """Text, borders and icons as a 1-bit map – thin UI text survives here, unlike in a plain colour diff."""
    return im.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0).convert("1")


def _count(im: Image.Image) -> int:
    return im.convert("L").histogram()[255]


def _structure_diff(a: Image.Image, b: Image.Image) -> float:
    """0 = same layout and text, 1 = completely different (share of edge pixels that differ)."""
    u = _count(ImageChops.logical_or(a, b)) or 1
    return _count(ImageChops.logical_xor(a, b)) / u


def _changed(a: Image.Image, b: Image.Image, thr: int = 16) -> tuple[float, tuple | None]:
    """Share of pixels whose colour changed, and the box around them."""
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > thr else 0)
    return diff.histogram()[255] / (a.width * a.height), diff.getbbox()


def segments(frames: Probe) -> list[dict]:
    """Calm stretches (a page that has finished loading) between navigations: [{a, b, acts}] in probe indexes."""
    edges = frames.edges
    gap = PROBE_FPS  # compare with one second earlier: catches slow fades and slide-ins
    moving = [False] * len(frames)
    for i in range(1, len(frames)):
        if _structure_diff(edges[max(0, i - gap)], edges[i]) > MOVING:
            moving[i] = True
    segs, start = [], None
    for i, m in enumerate(moving + [True]):
        if not m and start is None:
            start = i
        elif m and start is not None:
            if (i - start) / PROBE_FPS >= MIN_PAGE_S:
                acts = []
                for k in range(start + 1, i):
                    frac, box = _changed(frames.gray[k - 1], frames.gray[k])
                    if box:  # grey probes are half size
                        acts.append((k, frac, tuple(v * 2 for v in box)))
                segs.append({"a": start, "b": i, "acts": acts})
            start = None
    return segs


def _sim(a: Image.Image, b: Image.Image) -> float:
    """1.0 = the same picture."""
    return 1 - ImageStat.Stat(ImageChops.difference(a, b).convert("L")).mean[0] / 255


def _blur_diff(a: Image.Image, b: Image.Image) -> float:
    """Average brightness difference of two blurred thumbnails (0-255): small = the same screen overall."""
    def small(im):
        return im.convert("L").resize((160, 90)).filter(ImageFilter.GaussianBlur(2))
    return ImageStat.Stat(ImageChops.difference(small(a), small(b))).mean[0]


def _quiet_index(frames: list[Image.Image], seg: dict) -> int:
    """The calmest probe of a page (nothing animating, cursor still) – near the end, once everything has loaded."""
    best, best_i = None, seg["b"] - 1
    for i in range(max(seg["a"], seg["b"] - PROBE_FPS * 6), seg["b"] - 1):
        d = 1 - _sim(frames.gray[i], frames.gray[i + 1])
        if best is None or d <= best + 1e-4:
            best, best_i = d, i
    return best_i


# ── panels to spotlight (image analysis) ───────────────────────────────────
def _bg(im: Image.Image) -> tuple[int, int, int]:
    q = Counter(tuple(c // 6 * 6 for c in px) for px in im.getdata())
    return q.most_common(1)[0][0]


def _dist(c1, c2) -> int:
    return abs(c1[0] - c2[0]) + abs(c1[1] - c2[1]) + abs(c1[2] - c2[2])


def _components(mask: Image.Image) -> list[tuple[int, int, int, int, int]]:
    """Connected white areas of a small 1-bit mask: (x0, y0, x1, y1, pixels)."""
    w, h = mask.size
    px = mask.load()
    seen = bytearray(w * h)
    out = []
    for y in range(h):
        for x in range(w):
            if not px[x, y] or seen[y * w + x]:
                continue
            q = deque([(x, y)])
            seen[y * w + x] = 1
            x0 = x1 = x
            y0 = y1 = y
            n = 0
            while q:
                cx, cy = q.popleft()
                n += 1
                x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and px[nx, ny] and not seen[ny * w + nx]:
                        seen[ny * w + nx] = 1
                        q.append((nx, ny))
            out.append((x0, y0, x1 + 1, y1 + 1, n))
    return out


def _chrome(im: Image.Image, bg) -> tuple[int, int]:
    """Width of a left sidebar and height of a top bar (columns / rows that are almost entirely 'not page background')."""
    w, h = im.size
    px = im.load()
    def col_full(x):
        return sum(_dist(px[x, y], bg) > 14 for y in range(0, h, 3)) / len(range(0, h, 3)) > 0.82
    def row_full(y):
        return sum(_dist(px[x, y], bg) > 14 for x in range(0, w, 3)) / len(range(0, w, 3)) > 0.9
    left = 0
    while left < w * 0.3 and col_full(left):
        left += 1
    top = 0
    while top < h * 0.3 and row_full(top):
        top += 1
    # a sidebar is a narrow strip; a full-width banner at the top is a "top bar" only if it's short
    if left >= w * 0.3:
        left = 0
    if top >= h * 0.3:
        top = 0
    return left, top


def panels(still: Path, max_spots: int = 4) -> list[dict]:
    """Card groups / panels on an app screenshot, as [{x, y, w, h}] fractions, top-left to bottom-right.
    XY-cut: the content is split along empty gaps into bands (a row of KPI cards, a list, a grid), a too-big band is
    split again into columns and those into bands – the way a designer would point at a screen."""
    with Image.open(still) as src:
        im = src.convert("RGB").resize((PW, PH), Image.BILINEAR)
    if recording.is_blank(im):
        return []
    bg = _bg(im)
    left, top = _chrome(im, bg)
    mask = _mask(im, bg)
    edges = im.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 50 else 0)
    edge = 4  # the frame border (window edge, scrollbar) is never content
    ImageDraw.Draw(mask).rectangle([0, 0, PW - 1, PH - 1], outline=0, width=edge)
    boxes = _xycut(mask, (left, top, PW, PH), depth=0)
    area = (PW - left) * (PH - top)
    spots = []
    for x0, y0, x1, y1 in boxes:
        bw, bh = x1 - x0, y1 - y0
        a = bw * bh
        if a < area * 0.02 or bw < PW * 0.12 or bh < PH * 0.06 or a > area * 0.8:
            continue
        ink = _ink(mask, (x0, y0, x1, y1))
        detail = _ink(edges, (x0, y0, x1, y1))
        if ink < 0.04 or detail < 0.012:   # almost nothing inside (an empty area, a soft background glow, a spinner)
            continue
        spots.append({"x": x0, "y": y0, "w": bw, "h": bh,
                      "score": min(a / area, 0.35) * 2 + min(ink, 0.5) - (0.4 if bh < PH * 0.09 else 0)})
    if not spots and left:  # one big grid fills the page: spotlight the content area (right of the sidebar, under a banner)
        y = top
        px = im.load()
        while y < PH * 0.4 and sum(_dist(px[x, y], bg) > 14 for x in range(left, PW, 4)) > (PW - left) / 4 * 0.85:
            y += 1
        box = (left + 6, y + 6, PW - 6, PH - 6)
        found = mask.crop(box).getbbox()
        if found:
            x0, y0, x1, y1 = box[0] + found[0], box[1] + found[1], box[0] + found[2], box[1] + found[3]
            if (x1 - x0) * (y1 - y0) > area * 0.1 and _ink(edges, (x0, y0, x1, y1)) > 0.02:
                spots.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "score": 0.1})
    spots.sort(key=lambda s: -s["score"])
    spots = spots[:max_spots]
    spots.sort(key=lambda s: (s["y"], s["x"]))
    pad = 3
    return [{"x": round(max(0, s["x"] - pad) / PW, 4), "y": round(max(0, s["y"] - pad) / PH, 4),
             "w": round(min(PW, s["w"] + 2 * pad) / PW, 4), "h": round(min(PH, s["h"] + 2 * pad) / PH, 4),
             "score": round(s["score"], 3)} for s in spots]


def _mask(im: Image.Image, bg) -> Image.Image:
    """'Something is here': colour different from the page background, or an edge (text, borders, icons)."""
    w, h = im.size
    px = im.load()
    m = Image.new("L", (w, h), 0)
    mp = m.load()
    for y in range(h):
        for x in range(w):
            if _dist(px[x, y], bg) > 14:
                mp[x, y] = 255
    edges = im.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 50 else 0)
    return ImageChops.lighter(m, edges)


def _ink(mask: Image.Image, box) -> float:
    c = mask.crop(box)
    return c.histogram()[255] / max(1, c.width * c.height)


def _runs(profile: list[int], min_gap: int, min_fill: int = 1) -> list[tuple[int, int]]:
    out, start, gap = [], None, 0
    for i, v in enumerate(profile + [0] * (min_gap + 1)):
        if v >= min_fill:
            if start is None:
                start = i
            gap = 0
            end = i + 1
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                out.append((start, end))
                start = None
    return [(a, min(b, len(profile))) for a, b in out]


def _xycut(mask: Image.Image, box, depth: int) -> list[tuple[int, int, int, int]]:
    x0, y0, x1, y1 = box
    sub = mask.crop(box)
    w, h = sub.size
    if w < 8 or h < 8:
        return []
    px = sub.load()
    rows = [sum(1 for x in range(0, w, 2) if px[x, y]) for y in range(h)]
    bands = _runs(rows, min_gap=3, min_fill=max(1, w // 120))
    out = []
    for a, b in bands:
        cols = [sum(1 for y in range(a, b) if px[x, y]) for x in range(w)]
        need = max(1, int((b - a) * 0.04))
        parts = [(ca, cb) for ca, cb in _runs(cols, min_gap=4, min_fill=need) if cb - ca >= 4]  # no hairlines / scrollbars
        if not parts:
            continue
        band = (x0 + parts[0][0], y0 + a, x0 + parts[-1][1], y0 + b)
        bw, bh = band[2] - band[0], band[3] - band[1]
        if depth < 3 and bw * bh > PW * PH * 0.3:
            # a big block: split it into columns, then each column into bands again
            if len(parts) > 1:
                for ca, cb in parts:
                    out += _xycut(mask, (x0 + ca, y0 + a, x0 + cb, y0 + b), depth + 1)
                continue
            inner = _xycut(mask, (band[0] + 3, band[1] + 3, band[2] - 3, band[3] - 3), depth + 1) if depth < 2 else []
            if len(inner) > 1:
                out += inner
                continue
        out.append(band)
    return out


def _selected_item(im: Image.Image) -> list[float] | None:
    """The highlighted item of a left sidebar (the current page): a filled 'pill' row. Fractions [x, y, w, h]."""
    w, h = im.size
    side = _chrome(im, _bg(im))[0]
    if side < w * 0.05:
        return None
    strip = im.crop((int(side * 0.05), 0, int(side * 0.95), h))
    sw = strip.width
    sbg = _bg(strip)
    px = strip.load()
    rows = []
    for y in range(h):
        n = sum(1 for x in range(0, sw, 2) if _dist(px[x, y], sbg) > 10)
        rows.append(n / max(1, len(range(0, sw, 2))))
    bands, start = [], None
    for y, f in enumerate(rows + [0]):
        if f > 0.55 and start is None:
            start = y
        elif f <= 0.55 and start is not None:
            if 0.02 * h <= y - start <= 0.08 * h and start > h * 0.08:
                bands.append((start, y))
            start = None
    if not bands:
        return None
    y0, y1 = bands[0]
    return [round(side * 0.05 / w, 4), round(y0 / h, 4), round(side * 0.9 / w, 4), round((y1 - y0) / h, 4)]


def _nav_click(prev: Image.Image, cur: Image.Image) -> list[float] | None:
    """Where the person clicked to get from one page to the next: the sidebar item that is highlighted on the new
    page (and wasn't on the old one). Fractions [x, y, w, h], or None."""
    new = _selected_item(cur)
    if not new or _chrome(prev, _bg(prev))[0] < prev.width * 0.05:
        return None
    old = _selected_item(prev)
    if old and abs(old[1] - new[1]) < 0.01:
        return None   # same item still selected: not a sidebar navigation
    return new


# ── the tour material ───────────────────────────────────────────────────────
def analyze(src: Path, caption: str, rec_no: int, work: Path, max_pages: int = 24) -> dict:
    """{screens: [...like tour.capture screens...], media: [action clips]}. Screens keep the recording's order."""
    work.mkdir(parents=True, exist_ok=True)
    secs = min(ffmpeg.duration(src), MAX_SECONDS)
    frames = _probe(src, work, secs)
    edges = frames.edges
    segs = segments(frames)
    pages, prev_still = [], None
    for seg in segs:
        qi = _quiet_index(frames, seg)
        small = frames.rgb(qi)
        if recording.is_blank(small):
            continue
        # the same page again (typing, a popup, a little scrolling, an animated background) -> one page.
        # A click in the sidebar always means a new page.
        nav = _nav_click(prev_still, small) if prev_still is not None else None
        if pages and ((nav is None and _blur_diff(pages[-1]["small"], small) < 8) or
                      _structure_diff(edges[pages[-1]["qi"]], edges[qi]) < SAME_PAGE):
            pages[-1]["b"] = seg["b"]
            pages[-1]["acts"] += seg["acts"]
            if _count(edges[qi]) > _count(edges[pages[-1]["qi"]]) * 1.3:  # it finished loading: keep the fuller view
                pages[-1]["small"], pages[-1]["qi"] = small, qi
            continue
        pages.append({"small": small, "qi": qi, "a": seg["a"], "b": seg["b"], "acts": seg["acts"], "nav": nav})
        prev_still = small
    if len(pages) > max_pages:  # keep the longest-viewed pages (the person spent time there = it matters)
        keep = sorted(sorted(pages, key=lambda p: -(p["b"] - p["a"]))[:max_pages], key=lambda p: p["a"])
        pages = keep
    screens, media = [], []
    for k, p in enumerate(pages):
        t = p["qi"] / PROBE_FPS
        still = work / f"rec{rec_no}_page{k}.jpg"
        ffmpeg.run(["-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-vf", "scale=1920:-2", "-q:v", "2", str(still)])
        with Image.open(still) as im:
            w, h = im.size
        spots = panels(still)
        sid = f"R{rec_no}S{k}"
        screens.append({"id": sid, "path": still, "w": w, "h": h, "url": "", "page": f"{caption or 'recording'} at {int(t // 60)}:{int(t % 60):02d}",
                        "spots": [{**s, "text": ""} for s in spots], "links": [], "text": "", "nav_in": p["nav"],
                        "rec": rec_no, "t": round(t, 2)})
        clip = _action_clip(src, p, k, rec_no, work)
        if clip:
            clip["after"] = sid
            media.append(clip)
    log.info("recording %s: %.0fs -> %s page(s), %s action clip(s)", src.name, secs, len(screens), len(media))
    return {"screens": screens, "media": media}


def _action_clip(src: Path, page: dict, k: int, rec_no: int, work: Path) -> dict | None:
    """Something happens in place on this page (typing, a form filling in, a list updating): a short clip of it.
    Tiny changes (the cursor moving) don't count."""
    acts = [(i, f, box) for i, f, box in page["acts"] if f > 0.002 and box and
            (box[2] - box[0]) * (box[3] - box[1]) > PW * PH * 0.006]
    if len(acts) < PROBE_FPS * 1.2:  # at least ~1.2 s of real change
        return None
    a = max(page["a"], acts[0][0] - PROBE_FPS) / PROBE_FPS
    b = min(page["b"], acts[-1][0] + PROBE_FPS) / PROBE_FPS
    if b - a < 2.0:
        return None
    b = min(b, a + 9.0)
    x0 = min(bx[0] for _, _, bx in acts)
    y0 = min(bx[1] for _, _, bx in acts)
    x1 = max(bx[2] for _, _, bx in acts)
    y1 = max(bx[3] for _, _, bx in acts)
    focus = None
    if (x1 - x0) * (y1 - y0) < PW * PH * 0.55:
        pad = 6
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(PW, x1 + pad), min(PH, y1 + pad)
        focus = [round(x0 / PW, 4), round(y0 / PH, 4), round((x1 - x0) / PW, 4), round((y1 - y0) / PH, 4)]
    clip = work / f"rec{rec_no}_action{k}.mp4"
    ffmpeg.run(["-ss", f"{a:.2f}", "-i", str(src), "-t", f"{b - a:.2f}", "-an", "-vf",
                f"fps={recording.FPS},scale=1280:-2:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-pix_fmt", "yuv420p", str(clip)])
    poster = work / f"rec{rec_no}_action{k}.jpg"
    ffmpeg.run(["-ss", f"{(b - a) * 0.8:.2f}", "-i", str(clip), "-frames:v", "1", "-q:v", "3", str(poster)])
    with Image.open(poster) as im:
        w, h = im.size
        if recording.is_blank(im):
            return None
    return {"id": f"R{rec_no}A{k}", "path": poster, "w": w, "h": h, "user": True, "clip_path": clip,
            "clip_s": round(b - a, 2), "focus": focus, "text": f"something happening on page R{rec_no}S{k} (e.g. typing)"}


# ── colours ─────────────────────────────────────────────────────────────────
def palette(stills: list[Path]) -> dict | None:
    """The recording's own colours: page background + the strongest brand colour (buttons, highlights)."""
    bgs, vivid = Counter(), Counter()
    for p in stills[:12]:
        with Image.open(p) as src:
            im = src.convert("RGB").resize((160, 90))
        for c in im.getdata():
            q = tuple(v // 8 * 8 for v in c)
            bgs[q] += 1
            if max(c) - min(c) > 70 and max(c) > 70:
                vivid[q] += 1
    if not bgs:
        return None
    def hx(c):
        return "#%02X%02X%02X" % c
    primary = vivid.most_common(1)[0][0] if vivid else None
    second = next((c for c, _ in vivid.most_common(8) if primary and _dist(c, primary) > 90), None)
    return {"bgs": [f"rgb{c}" for c, _ in bgs.most_common(6) for _ in range(3)],
            "colors": {"primary": hx(primary) if primary else None, "secondary": hx(second) if second else None}}
