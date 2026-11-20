"""Festival greetings that look like a design studio made them.

Style reference: the Krypsos Diwali poster — a rich night scene, logo top-centre, a short quote line with one
highlighted word, a big gold script "Happy <Festival>" with a brush swoosh, and a two-line tagline bottom-right.

The background is either
  * a photo made by the image provider (IMAGE_PROVIDER=pollinations / openai / gemini), checked by the AI, or
  * a hand-built illustrated scene (sky, skyline, river, lanterns, diyas, fireworks, snow, kolam …) drawn with
    SVG/CSS — used when no provider is set or the photo fails / looks wrong.

The same scenes are animated for the festive opening of videos (scene_html with animate=True).
"""
from __future__ import annotations

import base64
import html as H
import json
import logging
import math
import random
import re
import shutil
from datetime import date
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageStat

from .. import llm, progress, storage
from ..config import ASSETS_DIR, company
from . import assets, rotation

log = logging.getLogger(__name__)
W, H_ = 1080, 1350
FONT_DIR = ASSETS_DIR / "fonts" / "festive"

# ── which drawing kit fits which festival ──────────────────────────────────
KITS = {
    "lights": "Diwali / Deepavali / Karthigai Deepam / Dev Deepawali: sky lanterns, brass lanterns, clay diyas, marigolds, lit skyline over a river",
    "devotional": "Ganesh Chaturthi / Navratri / Durga Puja / Dussehra / Janmashtami / Ram Navami: temple-like glow, marigold garlands, diyas, warm saffron light",
    "harvest": "Pongal / Makar Sankranti / Lohri / Onam / Baisakhi / Ugadi / Vishu: rising sun, sugarcane, clay pot, kolam pattern, kites",
    "colors": "Holi: clouds of colour powder (gulal) in pink, yellow, green, blue, purple",
    "crescent": "Eid al-Fitr / Eid al-Adha / Ramadan / Muharram: crescent moon, hanging lanterns, domes, stars",
    "christmas": "Christmas: glowing tree, warm string lights, snowfall, star",
    "fireworks": "New Year / celebrations / anniversaries / generic special days: fireworks, sparkles, city lights",
    "tricolor": "Independence Day / Republic Day / Gandhi Jayanti (India): saffron-white-green flowing waves, Ashoka chakra, fireworks",
}

_KEYWORDS = [
    ("lights", r"diwali|deepavali|deepawali|karthigai|kartik|deepam|dhanteras|bhai dooj|govardhan"),
    ("devotional", r"ganesh|vinayaka|navratri|durga|dussehra|dasara|vijaya|janmashtami|krishna|ram navami|"
                   r"hanuman|shivaratri|maha shivratri|raksha|rakhi|guru nanak|mahavir|buddha|easter|good friday"),
    ("harvest", r"pongal|sankranti|lohri|onam|baisakhi|vaisakhi|ugadi|vishu|bihu|gudi|puthandu|tamil new year|"
                r"chhath|makar|teej"),
    ("colors", r"holi"),
    ("crescent", r"eid|ramadan|ramzan|bakrid|muharram|milad|islamic"),
    ("christmas", r"christmas|xmas"),
    ("tricolor", r"independence|republic|gandhi|constitution|army day|navy day|air force day|kargil"),
    ("fireworks", r"new year|anniversary|founders|launch"),
]

# default colours per kit (the AI may tune them, within limits)
PALETTES = {
    "lights":     {"sky": ["#0B0E3B", "#2A1260", "#7B1E7A", "#F0734A"], "gold": ["#FFF6C2", "#FFD54A", "#F7A31C"], "hi": "#FFE24D"},
    "devotional": {"sky": ["#1A0711", "#4A0E1E", "#9C2A1A", "#F59E2E"], "gold": ["#FFF2C4", "#FFC94A", "#F08A1C"], "hi": "#FFD24D"},
    "harvest":    {"sky": ["#14243F", "#3E3C7A", "#D96A4B", "#FFC46B"], "gold": ["#FFF7D1", "#FFD36B", "#F59E2E"], "hi": "#FFE07A"},
    "colors":     {"sky": ["#170B2E", "#3A0F57", "#8E1B6B", "#E8505B"], "gold": ["#FFFFFF", "#FFE3F1", "#FFB3D9"], "hi": "#FFE24D"},
    "crescent":   {"sky": ["#03131F", "#06283D", "#0E4D5C", "#2E8B7A"], "gold": ["#FFF7D6", "#F3D27A", "#C9A24A"], "hi": "#F3D27A"},
    "christmas":  {"sky": ["#06131F", "#0C2B33", "#133F3A", "#2B5A3F"], "gold": ["#FFF7E0", "#FFD98A", "#E8A33C"], "hi": "#FFD24D"},
    "fireworks":  {"sky": ["#03030F", "#0B1340", "#2A1A6B", "#6B2A8C"], "gold": ["#FFFFFF", "#FFE58A", "#F7B733"], "hi": "#FFE24D"},
    "tricolor":   {"sky": ["#030B1F", "#0A1F4D", "#13306E", "#22427F"], "gold": ["#FFFFFF", "#FFE7C2", "#FF9933"], "hi": "#FF9933"},
}

LAYOUTS = ["center", "left"]
TAG_BOTTOM = {"tricolor": 250}   # keep the tagline off busy foregrounds


def kit_for(name: str) -> str:
    n = (name or "").lower()
    for kit, pat in _KEYWORDS:
        if re.search(pat, n):
            return kit
    return "fireworks"


# ── fonts (bundled, embedded as data: URIs so the HTML renders anywhere – also in the text editor) ─────
_FACES = [
    ("Great Vibes", 400, "normal", "great-vibes-latin-400-normal.woff2"),
    ("Kaushan Script", 400, "normal", "kaushan-script-latin-400-normal.woff2"),
    ("Allura", 400, "normal", "allura-latin-400-normal.woff2"),
    ("Playfair Display", 700, "normal", "playfair-display-latin-700-normal.woff2"),
    ("Playfair Display", 600, "italic", "playfair-display-latin-600-italic.woff2"),
    ("Cormorant Garamond", 600, "italic", "cormorant-garamond-latin-600-italic.woff2"),
    ("Montserrat", 400, "normal", "montserrat-latin-400-normal.woff2"),
    ("Montserrat", 500, "normal", "montserrat-latin-500-normal.woff2"),
    ("Montserrat", 600, "normal", "montserrat-latin-600-normal.woff2"),
    ("Montserrat", 700, "normal", "montserrat-latin-700-normal.woff2"),
    ("Montserrat", 800, "normal", "montserrat-latin-800-normal.woff2"),
]


@lru_cache(maxsize=1)
def font_css() -> str:
    out = []
    for fam, weight, style, file in _FACES:
        f = FONT_DIR / file
        if not f.is_file():
            continue
        b64 = base64.b64encode(f.read_bytes()).decode()
        out.append(f"@font-face{{font-family:'{fam}';font-weight:{weight};font-style:{style};font-display:block;"
                   f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "\n".join(out)


SCRIPTS = {"brush": "'Kaushan Script'", "elegant": "'Great Vibes'", "flowing": "'Allura'"}


def _e(s) -> str:
    return H.escape(str(s or ""))


def _hl(text: str, color: str) -> str:
    """'Let the {brighter} tomorrow' -> highlighted word in bold colour."""
    parts = re.split(r"(\{[^}]+\})", text or "")
    return "".join(f'<b class="hi">{_e(p[1:-1])}</b>' if p.startswith("{") and p.endswith("}") else _e(p)
                   for p in parts)


def _plain(text: str) -> str:
    return re.sub(r"[{}]", "", text or "")


# ── illustrated scenes ─────────────────────────────────────────────────────
def _sky(p: dict, w: int, h: int, horizon: float) -> str:
    s = p["sky"]
    return (f'<div class="L" style="background:linear-gradient(180deg,{s[0]} 0%,{s[1]} {horizon * 48:.0f}%,'
            f'{s[2]} {horizon * 82:.0f}%,{s[3]} {horizon * 100:.0f}%,{s[2]} {horizon * 100 + 6:.0f}%,{s[0]} 100%)"></div>'
            f'<div class="L" style="background:radial-gradient(ellipse 70% 22% at 50% {horizon * 100:.0f}%,{s[3]}cc,transparent 70%)"></div>')


def _stars(r: random.Random, w: int, h: int, top: float, n: int = 90, animate: bool = False) -> str:
    dots = []
    for i in range(n):
        x, y = r.uniform(0, w), r.uniform(0, h * top)
        rad = r.choice([0.8, 1, 1.2, 1.5, 2])
        op = r.uniform(.35, .95)
        tw = f' class="tw" style="animation-delay:-{r.uniform(0, 3):.2f}s"' if animate and i % 3 == 0 else ""
        dots.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rad}" fill="#fff" opacity="{op:.2f}"{tw}/>')
    return f'<svg class="L" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{"".join(dots)}</svg>'


def _bokeh(r: random.Random, w: int, h: int, colors: list[str], n: int = 26, y0: float = 0, y1: float = 1) -> str:
    out = []
    for _ in range(n):
        size = r.uniform(10, 46)
        c = r.choice(colors)
        out.append(f'<i class="bk" style="left:{r.uniform(0, w):.0f}px;top:{r.uniform(h * y0, h * y1):.0f}px;width:{size:.0f}px;'
                   f'height:{size:.0f}px;background:radial-gradient(circle,{c}cc,{c}00 70%);opacity:{r.uniform(.3, .85):.2f}"></i>')
    return "".join(out)


def _skyline(r: random.Random, w: int, h: int, base: float, color: str, lit: str, temple: bool) -> str:
    """Procedural city silhouette with lit windows; optional palace/temple domes in the middle."""
    y0 = h * base
    parts, windows = [], []
    x = -10
    while x < w + 10:
        bw = r.uniform(w * .025, w * .065)
        bh = r.uniform(h * .018, h * .075) * (1.25 if r.random() < .18 else 1)
        if temple and w * .38 < x < w * .62:
            bh *= .5
        parts.append(f'<rect x="{x:.0f}" y="{y0 - bh:.0f}" width="{bw:.0f}" height="{bh + 2:.0f}"/>')
        for wy in range(int(y0 - bh + 8), int(y0 - 4), 11):
            for wx in range(int(x + 5), int(x + bw - 5), 10):
                if r.random() < .16:
                    windows.append(f'<rect x="{wx}" y="{wy}" width="2.5" height="3.5" opacity="{r.uniform(.4, 1):.2f}"/>')
        x += bw + r.uniform(0, 6)
    temple_svg = ""
    if temple:
        cx, s = w * .5, w / 1080
        dome = lambda dx, rad, top: (f'<path d="M{cx + dx - rad:.0f},{y0 - top:.0f} q{rad:.0f},{-rad * 1.5:.0f} {rad * 2:.0f},0 z"/>'
                                     f'<rect x="{cx + dx - rad:.0f}" y="{y0 - top:.0f}" width="{rad * 2:.0f}" height="{top:.0f}"/>'
                                     f'<rect x="{cx + dx - 1.5:.0f}" y="{y0 - top - rad * 1.5 - 14:.0f}" width="3" height="16"/>')
        temple_svg = (f'<g fill="{color}">{dome(0, 34 * s, 70 * s)}{dome(-70 * s, 20 * s, 46 * s)}{dome(70 * s, 20 * s, 46 * s)}'
                      f'{dome(-125 * s, 13 * s, 30 * s)}{dome(125 * s, 13 * s, 30 * s)}'
                      f'<rect x="{cx - 150 * s:.0f}" y="{y0 - 22 * s:.0f}" width="{300 * s:.0f}" height="{24 * s:.0f}"/></g>'
                      f'<g fill="{lit}">' + "".join(
                          f'<circle cx="{cx + dx:.0f}" cy="{y0 - yy:.0f}" r="2.2"/>'
                          for dx in range(int(-140 * s), int(141 * s), 9) for yy in (6, 16)) + '</g>'
                      f'<ellipse cx="{cx:.0f}" cy="{y0 - 40:.0f}" rx="{230 * s:.0f}" ry="{90 * s:.0f}" fill="{lit}" opacity=".18" filter="url(#bl)"/>')
    return (f'<svg class="L" viewBox="0 0 {w} {h}" width="{w}" height="{h}"><defs>'
            f'<linearGradient id="sk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{color}" stop-opacity=".82"/><stop offset="1" stop-color="{color}"/></linearGradient></defs>'
            f'<g fill="url(#sk)">{"".join(parts)}</g><g fill="{lit}" style="filter:drop-shadow(0 0 3px {lit})">{"".join(windows)}</g>{temple_svg}</svg>')


def _water(r: random.Random, w: int, h: int, top: float, bottom: float, p: dict, warm: str) -> str:
    y0, y1 = h * top, h * bottom
    streaks = "".join(
        f'<i class="st" style="left:{r.uniform(0, w):.0f}px;top:{y0 + 2:.0f}px;height:{r.uniform(.35, 1) * (y1 - y0):.0f}px;'
        f'width:{r.uniform(2, 6):.0f}px;background:linear-gradient({warm},{warm}00);opacity:{r.uniform(.45, .95):.2f}"></i>'
        for _ in range(int(w / 14)))
    return (f'<div class="L" style="top:{y0:.0f}px;height:{y1 - y0:.0f}px;background:linear-gradient(180deg,{p["sky"][3]}aa,{p["sky"][1]} 45%,{p["sky"][0]})"></div>'
            f'<div class="L" style="top:{y0:.0f}px;height:{y1 - y0:.0f}px;overflow:hidden;filter:blur(1.2px);mix-blend-mode:screen">{streaks}</div>')


def _ledge(w: int, h: int, top: float, warm: str) -> str:
    return (f'<div class="L" style="top:{h * top:.0f}px;background:linear-gradient(180deg,#3a2418,#1d120c 40%,#0d0806)"></div>'
            f'<div class="L" style="top:{h * top:.0f}px;height:6px;background:linear-gradient(90deg,{warm}00,{warm}aa 35%,{warm}55 70%,{warm}00)"></div>'
            f'<div class="L" style="top:{h * top:.0f}px;background:radial-gradient(ellipse 45% 60% at 28% 10%,{warm}55,transparent 70%)"></div>')


def _sky_lantern(x, y, size, blur=0, anim="", delay=0.0) -> str:
    return (f'<div class="sl{(" " + anim) if anim else ""}" style="left:{x:.0f}px;top:{y:.0f}px;width:{size:.0f}px;height:{size * 1.22:.0f}px;'
            f'{f"filter:blur({blur:.1f}px);" if blur else ""}animation-delay:-{delay:.2f}s"><i></i></div>')


def _diya(x, y, size, anim=False) -> str:
    fl = ' class="fl"' if anim else ""
    return f"""<svg style="position:absolute;left:{x - size / 2:.0f}px;top:{y - size * .9:.0f}px;overflow:visible" width="{size:.0f}" height="{size:.0f}" viewBox="0 0 200 200">
<defs><radialGradient id="dg{int(x)}" cx="50%" cy="20%" r="80%"><stop offset="0" stop-color="#E9894A"/><stop offset=".55" stop-color="#9A3E17"/><stop offset="1" stop-color="#4A1A08"/></radialGradient>
<radialGradient id="fg{int(x)}" cx="50%" cy="70%" r="60%"><stop offset="0" stop-color="#FFFFFF"/><stop offset=".35" stop-color="#FFF3A0"/><stop offset=".7" stop-color="#FFB020"/><stop offset="1" stop-color="#FF6A00" stop-opacity="0"/></radialGradient></defs>
<ellipse cx="100" cy="95" rx="{95}" ry="60" fill="#FFB347" opacity=".28" filter="url(#bl)"/>
<path d="M18,128 Q100,118 182,128 Q170,186 100,190 Q30,186 18,128 Z" fill="url(#dg{int(x)})"/>
<path d="M18,128 Q100,140 182,128" stroke="#F7C26B" stroke-width="3" fill="none" opacity=".85"/>
<path d="M30,150 Q100,162 170,150" stroke="#F7C26B" stroke-width="2" fill="none" stroke-dasharray="2 7" opacity=".8"/>
<g{fl} style="transform-origin:100px 125px"><path d="M100,40 C112,70 124,92 114,112 C108,124 92,124 86,112 C76,92 88,70 100,40 Z" fill="url(#fg{int(x)})"/>
<ellipse cx="100" cy="106" rx="6" ry="11" fill="#fff"/></g></svg>"""


def _brass_lantern(x, y, hgt, anim=False) -> str:
    w = hgt * .48
    fl = ' class="fl"' if anim else ""
    return f"""<svg style="position:absolute;left:{x:.0f}px;top:{y:.0f}px;overflow:visible" width="{w:.0f}" height="{hgt:.0f}" viewBox="0 0 96 200" preserveAspectRatio="none">
<defs><radialGradient id="lg{int(x)}" cx="50%" cy="55%" r="60%"><stop offset="0" stop-color="#FFF4C4"/><stop offset=".35" stop-color="#FFB547"/><stop offset="1" stop-color="#B4531A"/></radialGradient>
<pattern id="lp{int(x)}" width="14" height="22" patternUnits="userSpaceOnUse"><path d="M7,0 L14,11 L7,22 L0,11 Z" fill="none" stroke="#3B1D0C" stroke-width="2.4"/><circle cx="7" cy="11" r="2" fill="#3B1D0C"/></pattern>
<linearGradient id="bm{int(x)}" x1="0" x2="1"><stop offset="0" stop-color="#5A2E10"/><stop offset=".5" stop-color="#C98A3A"/><stop offset="1" stop-color="#4A240C"/></linearGradient></defs>
<ellipse cx="48" cy="110" rx="90" ry="110" fill="#FF9A3C" opacity=".22" filter="url(#bl)"/>
<path d="M44,0 h8 v10 h-8z M30,14 Q48,0 66,14 L72,30 H24 Z" fill="url(#bm{int(x)})"/>
<rect x="18" y="30" width="60" height="10" rx="2" fill="url(#bm{int(x)})"/>
<g{fl} style="transform-origin:48px 110px"><rect x="22" y="40" width="52" height="120" fill="url(#lg{int(x)})"/></g>
<rect x="22" y="40" width="52" height="120" fill="url(#lp{int(x)})" opacity=".9"/>
<rect x="18" y="40" width="6" height="120" fill="url(#bm{int(x)})"/><rect x="72" y="40" width="6" height="120" fill="url(#bm{int(x)})"/>
<rect x="14" y="160" width="68" height="12" rx="2" fill="url(#bm{int(x)})"/><path d="M20,172 h56 l-6,16 h-44z" fill="#3B1D0C"/></svg>"""


def _marigold(x, y, size, c1="#FF9F1C", c2="#FFBF3C") -> str:
    petals = "".join(f'<ellipse cx="0" cy="-{size * .3:.1f}" rx="{size * .16:.1f}" ry="{size * .26:.1f}" fill="{c1 if i % 2 else c2}" '
                     f'transform="rotate({i * 30})"/>' for i in range(12))
    return (f'<svg style="position:absolute;left:{x - size / 2:.0f}px;top:{y - size / 2:.0f}px;overflow:visible" width="{size:.0f}" height="{size:.0f}">'
            f'<g transform="translate({size / 2:.1f},{size / 2:.1f}) scale(1,.55)">{petals}<circle r="{size * .14:.1f}" fill="#E0660F"/></g></svg>')


def _firework(cx, cy, rad, color, rr: random.Random, anim=False, delay=0.0) -> str:
    rays = []
    n = rr.randint(26, 40)
    for i in range(n):
        a = 2 * math.pi * i / n + rr.uniform(-.05, .05)
        r0, r1 = rad * rr.uniform(.15, .3), rad * rr.uniform(.75, 1)
        rays.append(f'<line x1="{cx + r0 * math.cos(a):.0f}" y1="{cy + r0 * math.sin(a):.0f}" x2="{cx + r1 * math.cos(a):.0f}" '
                    f'y2="{cy + r1 * math.sin(a):.0f}"/><circle cx="{cx + r1 * 1.06 * math.cos(a):.0f}" cy="{cy + r1 * 1.06 * math.sin(a):.0f}" r="2.6"/>')
    cls = ' class="fw"' if anim else ""
    return (f'<g{cls} style="transform-origin:{cx:.0f}px {cy:.0f}px;animation-delay:{delay:.2f}s" stroke="{color}" fill="{color}" '
            f'stroke-width="2.2" stroke-linecap="round"><circle cx="{cx:.0f}" cy="{cy:.0f}" r="{rad * .9:.0f}" fill="{color}" '
            f'opacity=".10" stroke="none" filter="url(#bl)"/>{"".join(rays)}</g>')


def _fireworks(r: random.Random, w, h, colors, n, top, anim) -> str:
    """Bursts on the left/right edges so the centred text stays clean."""
    spots = []
    for i in range(n):
        side = i % 2
        x = r.uniform(w * (.03 if not side else .84), w * (.16 if not side else .97))
        y = r.uniform(h * .02, h * .1) if i < 2 else r.uniform(h * .57, h * top)
        spots.append((x, y))
    out = "".join(_firework(x, y, r.uniform(w * .05, w * .1), r.choice(colors), r, anim, i * .45)
                  for i, (x, y) in enumerate(spots))
    return (f'<svg class="L" viewBox="0 0 {w} {h}" width="{w}" height="{h}" style="filter:drop-shadow(0 0 6px #fff6)">'
            f'<defs><filter id="bl"><feGaussianBlur stdDeviation="22"/></filter></defs>{out}</svg>')


def _snow(r: random.Random, w, h, n, anim) -> str:
    flakes = "".join(f'<i class="sn{" fall" if anim else ""}" style="left:{r.uniform(0, w):.0f}px;top:{r.uniform(-h * .05, h):.0f}px;'
                     f'width:{(s := r.uniform(3, 9)):.0f}px;height:{s:.0f}px;opacity:{r.uniform(.4, .95):.2f};animation-delay:-{r.uniform(0, 6):.2f}s"></i>'
                     for _ in range(n))
    return f'<div class="L" style="overflow:hidden">{flakes}</div>'


def _tree(x, y, hgt, anim) -> str:
    w = hgt * .7
    lights = []
    twc = ' class="tw"'
    rr = random.Random(int(x))
    for i in range(46):
        t = rr.uniform(.1, .95)
        half = w / 2 * t
        lights.append(f'<circle cx="{w / 2 + rr.uniform(-half, half):.0f}" cy="{hgt * (.08 + t * .8):.0f}" r="{rr.uniform(3, 6):.1f}" '
                      f'fill="{rr.choice(["#FFE08A", "#FF6B6B", "#FFFFFF", "#8AD7FF", "#FFD24D"])}"{twc if anim and i % 2 else ""} '
                      f'style="animation-delay:-{rr.uniform(0, 2):.1f}s"/>')
    tiers = "".join(f'<path d="M{w / 2},{hgt * a:.0f} L{w / 2 + w * b:.0f},{hgt * c:.0f} L{w / 2 - w * b:.0f},{hgt * c:.0f} Z" fill="url(#tg)"/>'
                    for a, b, c in [(.06, .22, .36), (.2, .32, .58), (.36, .42, .86)])
    return f"""<svg style="position:absolute;left:{x:.0f}px;top:{y:.0f}px;overflow:visible" width="{w:.0f}" height="{hgt:.0f}">
<defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1F6B45"/><stop offset="1" stop-color="#0B3B26"/></linearGradient></defs>
<ellipse cx="{w / 2}" cy="{hgt * .5}" rx="{w * .8}" ry="{hgt * .6}" fill="#FFC76B" opacity=".14" filter="url(#bl)"/>
<rect x="{w / 2 - 10}" y="{hgt * .85}" width="20" height="{hgt * .1}" fill="#3B2412"/>{tiers}
<g style="filter:drop-shadow(0 0 6px #FFE08A)">{''.join(lights)}</g>
<path d="M{w / 2},{-hgt * .02} l9,19 21,3 -15,14 4,21 -19,-10 -19,10 4,-21 -15,-14 21,-3z" fill="#FFD24D" style="filter:drop-shadow(0 0 14px #FFD24D)"/></svg>"""


def _crescent(cx, cy, rad, color, w, h) -> str:
    return (f'<svg class="L" viewBox="0 0 {w} {h}" width="{w}" height="{h}"><defs><mask id="mm"><rect x="0" y="0" width="100%" height="100%" fill="#fff"/>'
            f'<circle cx="{cx + rad * .42:.0f}" cy="{cy - rad * .18:.0f}" r="{rad * .86:.0f}" fill="#000"/></mask>'
            f'<filter id="bl2"><feGaussianBlur stdDeviation="30"/></filter></defs>'
            f'<circle cx="{cx}" cy="{cy}" r="{rad * 1.6:.0f}" fill="{color}" opacity=".16" filter="url(#bl2)"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{rad}" fill="{color}" mask="url(#mm)" style="filter:drop-shadow(0 0 18px {color})"/></svg>')


def _hanging_lanterns(r, w, h, n, anim) -> str:
    out = []
    xs = [w * f for f in (.05, .12, .19, .9)][:n]
    for i, x in enumerate(xs):
        drop = r.uniform(h * .03, h * .13)
        s = r.uniform(.7, 1.1)
        out.append(f'<div class="hang{" sway" if anim else ""}" style="left:{x:.0f}px;animation-delay:-{r.uniform(0, 3):.1f}s">'
                   f'<i style="height:{drop:.0f}px"></i>{_brass_lantern(-24 * s, drop, 110 * s, anim)}</div>')
    return "".join(out)


def _waves(w, h, top) -> str:
    y = h * top
    def band(c, off, amp, op):
        return (f'<path d="M0,{y + off:.0f} C{w * .25:.0f},{y + off - amp:.0f} {w * .55:.0f},{y + off + amp:.0f} {w},{y + off - amp * .4:.0f} '
                f'L{w},{h} L0,{h} Z" fill="{c}" opacity="{op}"/>')
    return (f'<svg class="L" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{band("#FF9933", 0, 34, .96)}{band("#FFFFFF", 52, 30, .97)}'
            f'{band("#138808", 104, 26, .97)}</svg>')


def _chakra(cx, cy, rad) -> str:
    spokes = "".join(f'<line x1="0" y1="0" x2="0" y2="-{rad * .92:.0f}" transform="rotate({i * 15})"/>' for i in range(24))
    return (f'<svg style="position:absolute;left:{cx - rad:.0f}px;top:{cy - rad:.0f}px;overflow:visible" width="{rad * 2:.0f}" height="{rad * 2:.0f}">'
            f'<g transform="translate({rad},{rad})" stroke="#1F3FA8" fill="none" stroke-width="{max(2, rad * .03):.1f}"><circle r="{rad * .97:.0f}" stroke-width="{rad * .06:.0f}"/>'
            f'{spokes}<circle r="{rad * .12:.0f}" fill="#1F3FA8"/></g></svg>')


def _powder(r, w, h, n) -> str:
    cols = ["#FF3D8B", "#FFD23F", "#2EC4B6", "#3A86FF", "#8338EC", "#FB5607", "#06D6A0"]
    spots = [(r.uniform(-w * .2, w * .9), r.uniform(h * .55, h * .95)) for _ in range(n)] + \
            [(r.uniform(-w * .25, -w * .05), r.uniform(-h * .1, h * .4)) for _ in range(3)] + \
            [(r.uniform(w * .75, w * .95), r.uniform(-h * .1, h * .4)) for _ in range(3)]
    return "".join(f'<i class="pw" style="left:{x:.0f}px;top:{y:.0f}px;'
                   f'width:{(s := r.uniform(w * .25, w * .55)):.0f}px;height:{s * .8:.0f}px;'
                   f'background:radial-gradient(closest-side,{(c := r.choice(cols))}ee,{c}66 55%,{c}00);transform:rotate({r.uniform(0, 180):.0f}deg)"></i>'
                   for x, y in spots)


def _kolam(cx, cy, size, color) -> str:
    n = 5
    step = size / n
    dots = "".join(f'<circle cx="{(i - (n - 1) / 2) * step:.0f}" cy="{(j - (n - 1) / 2) * step:.0f}" r="3.5"/>'
                   for i in range(n) for j in range(n) if abs(i - 2) + abs(j - 2) <= 3)
    loops = "".join(f'<rect x="{-step * k:.0f}" y="{-step * k:.0f}" width="{step * 2 * k:.0f}" height="{step * 2 * k:.0f}" rx="{step * k * .45:.0f}" '
                    f'transform="rotate(45)"/>' for k in (0.7, 1.4, 2.1))
    return (f'<svg style="position:absolute;left:{cx - size:.0f}px;top:{cy - size * .45:.0f}px;overflow:visible" width="{size * 2:.0f}" height="{size:.0f}">'
            f'<g transform="translate({size:.0f},{size * .45:.0f}) scale(1,.45)" stroke="{color}" fill="none" stroke-width="4" opacity=".9">{loops}'
            f'<g fill="{color}" stroke="none">{dots}</g></g></svg>')


def _sun(cx, cy, rad) -> str:
    return (f'<div style="position:absolute;left:{cx - rad * 3:.0f}px;top:{cy - rad * 3:.0f}px;width:{rad * 6:.0f}px;height:{rad * 6:.0f}px;'
            f'border-radius:50%;background:radial-gradient(circle,#FFF4C2 0%,#FFD36B {100 / 6:.0f}%,#FF9F43 {100 / 5:.0f}%,#FF7F5000 60%)"></div>')


def _pot(x, y, size) -> str:
    return f"""<svg style="position:absolute;left:{x - size / 2:.0f}px;top:{y - size:.0f}px;overflow:visible" width="{size:.0f}" height="{size:.0f}" viewBox="0 0 200 200">
<defs><radialGradient id="pg" cx="40%" cy="35%" r="75%"><stop offset="0" stop-color="#E58A4E"/><stop offset=".6" stop-color="#A2461C"/><stop offset="1" stop-color="#5A220A"/></radialGradient></defs>
<g fill="#FFF8EC">{''.join(f'<circle cx="{70 + i * 12}" cy="{38 - (i % 3) * 7}" r="{11 - (i % 2) * 3}"/>' for i in range(6))}</g>
<path d="M60,48 h80 q-4,14 6,22 q48,26 36,78 q-12,46 -82,48 q-70,-2 -82,-48 q-12,-52 36,-78 q10,-8 6,-22z" fill="url(#pg)"/>
<path d="M44,98 q56,18 112,0" stroke="#FFD36B" stroke-width="5" fill="none"/><path d="M40,112 q60,18 120,0" stroke="#3FA34D" stroke-width="5" fill="none"/>
<path d="M46,126 q54,16 108,0" stroke="#E63946" stroke-width="5" fill="none"/></svg>"""


def _sugarcane(x, y, hgt, lean) -> str:
    n = int(hgt / 40)
    seg = "".join(f'<rect x="-9" y="{-(i + 1) * 40:.0f}" width="18" height="38" rx="6" fill="url(#cane)"/>'
                  f'<rect x="-10" y="{-(i + 1) * 40 - 3:.0f}" width="20" height="5" rx="2" fill="#2B1430"/>' for i in range(n))
    top = -n * 40
    leaves = "".join(f'<path d="M0,{top + 10} C{dx * .4:.0f},{top - 60} {dx * .8:.0f},{top - 40} {dx:.0f},{top + dy:.0f}" stroke="#4CAF50" '
                     f'stroke-width="9" fill="none" stroke-linecap="round"/>' for dx, dy in ((-120, 20), (110, 40), (-60, -90), (70, -70), (-150, 90)))
    return (f'<svg style="position:absolute;left:{x:.0f}px;top:{y - hgt:.0f}px;overflow:visible" width="20" height="{hgt:.0f}">'
            f'<defs><linearGradient id="cane" x1="0" x2="1"><stop offset="0" stop-color="#3A1640"/><stop offset=".45" stop-color="#7A3A6E"/>'
            f'<stop offset="1" stop-color="#2E1033"/></linearGradient></defs>'
            f'<g transform="translate(10,{hgt:.0f}) rotate({lean})">{seg}{leaves}</g></svg>')


def _fields(w, h, hz) -> str:
    y = h * hz
    return (f'<svg class="L" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<path d="M0,{y - 30:.0f} C{w * .2:.0f},{y - 70:.0f} {w * .35:.0f},{y - 20:.0f} {w * .55:.0f},{y - 40:.0f} S{w * .85:.0f},{y - 80:.0f} {w},{y - 35:.0f} L{w},{h} L0,{h}Z" fill="#3B3466" opacity=".8"/>'
            f'<path d="M0,{y:.0f} C{w * .3:.0f},{y - 25:.0f} {w * .6:.0f},{y + 10:.0f} {w},{y - 15:.0f} L{w},{h} L0,{h}Z" fill="#2E5A2E"/>'
            f'<path d="M0,{y + 60:.0f} C{w * .35:.0f},{y + 30:.0f} {w * .65:.0f},{y + 75:.0f} {w},{y + 45:.0f} L{w},{h} L0,{h}Z" fill="#244A24"/>'
            f'<path d="M0,{y + 150:.0f} C{w * .4:.0f},{y + 120:.0f} {w * .7:.0f},{y + 160:.0f} {w},{y + 130:.0f} L{w},{h} L0,{h}Z" fill="#5A3A22"/>'
            f'<path d="M0,{y + 175:.0f} C{w * .4:.0f},{y + 150:.0f} {w * .7:.0f},{y + 185:.0f} {w},{y + 160:.0f} L{w},{h} L0,{h}Z" fill="#3A2414"/></svg>')


def scene_html(kit: str, p: dict, w: int, h: int, seed: int, animate: bool = False, focus: str = "center") -> str:
    """The illustrated background (no text). focus='left' keeps the left/top area calmer for left-aligned text."""
    r = random.Random(seed)
    warm = p["gold"][2]
    hz = {"lights": .70, "devotional": .72, "harvest": .70, "crescent": .74, "christmas": .74,
          "fireworks": .76, "tricolor": .74, "colors": .74}.get(kit, .72)
    layers = ['<svg width="0" height="0" style="position:absolute"><defs><filter id="bl" x="-50%" y="-50%" width="200%" height="200%">'
              '<feGaussianBlur stdDeviation="26"/></filter></defs></svg>', _sky(p, w, h, hz)]
    if kit not in ("colors",):
        layers.append(_stars(r, w, h, hz * .8, 110 if kit in ("crescent", "christmas", "fireworks", "tricolor") else 70, animate))
    vert = h > w * 1.2
    sx = min(w, h) / 1080 * (1.15 if h > w * 1.5 else 1)  # scale motifs with the canvas

    if kit in ("lights", "devotional"):
        layers.append(_skyline(r, w, h, hz, "#160A24" if kit == "lights" else "#1E0A0A", "#FFC46B", temple=True))
        layers.append(_water(r, w, h, hz, .86, p, warm))
        lans = []
        for i in range(14 if vert else 18):
            big = i < 4
            size = (r.choice([70, 84, 100]) if big else r.choice([18, 24, 30, 38, 46])) * sx
            if focus == "center":
                x = r.uniform(w * .8, w * .93) if big else (r.uniform(w * .72, w * .96) if i % 3 else r.uniform(w * .03, w * .18))
            elif focus == "left":
                x = r.uniform(w * .62, w * .92) if big else r.uniform(w * .55, w * .97)
            else:
                x = r.uniform(w * .02, w * .97)
            y = r.uniform(h * .03, h * (.5 if big else .6))
            lans.append(_sky_lantern(x, y, size, blur=0 if size > 50 * sx else 1.2, anim="rise" if animate else "", delay=r.uniform(0, 8)))
        layers.append("".join(lans))
        layers.append(_ledge(w, h, .86, warm))
        lx = w * .05 if focus != "left" else w - 340 * sx
        layers.append(_brass_lantern(lx, h * .86 - 330 * sx, 330 * sx, animate))
        layers.append(_brass_lantern(lx + 160 * sx, h * .86 - 250 * sx, 250 * sx, animate))
        dx = lx + 390 * sx if focus != "left" else lx - 150 * sx
        layers.append(_diya(dx, h * .885, 220 * sx, animate))
        if not vert:
            layers.append(_diya(w * .82, h * .9, 150 * sx, animate))
        cols = ("#FF9F1C", "#FFBF3C") if kit == "lights" else ("#FF7B00", "#FFB703")
        mx0 = min(lx, dx - 120 * sx) - 20 * sx
        layers.append("".join(_marigold(r.uniform(mx0, mx0 + 560 * sx), r.uniform(h * .872, h * .905), r.uniform(24, 40) * sx, *cols)
                              for _ in range(14)))
        if kit == "devotional":  # marigold garland swag across the top
            garland = "".join(_marigold(w * t, h * (.006 + .022 * math.sin(math.pi * t)), 30 * sx, "#FF7B00", "#FFB703")
                              for t in [i / 26 for i in range(27)])
            layers.append(garland)
        layers.append(_bokeh(r, w, h, ["#FFB347", "#FFD27A", "#FF7AC8"], 22, .5, .95))
    elif kit == "harvest":
        layers.append(_sun(w * .5, h * hz, w * .08))
        layers.append(_fields(w, h, hz))
        layers.append(_kolam(w * .52, h * .93, 230 * sx, "#FFF6E0"))
        layers.append(_sugarcane(w * .05, h * .97, 560 * sx, -7))
        layers.append(_sugarcane(w * .12, h * .975, 500 * sx, 4))
        layers.append(_pot(w * .27, h * .96, 250 * sx))
        layers.append(_bokeh(r, w, h, ["#FFD36B", "#FF9F43"], 16, .4, .9))
    elif kit == "colors":
        layers.append(_powder(r, w, h, 16))
        layers.append(_bokeh(r, w, h, ["#FFFFFF", "#FFD23F", "#FF3D8B"], 30, .05, .95))
    elif kit == "crescent":
        layers.append(_crescent(w * .84, h * .075, 52 * sx, p["gold"][1], w, h))
        layers.append(_skyline(r, w, h, hz, "#03111A", "#F3D27A", temple=True))
        layers.append(_water(r, w, h, hz, 1, p, p["gold"][1]))
        layers.append(_hanging_lanterns(r, w, h, 5, animate))
    elif kit == "christmas":
        layers.append(_skyline(r, w, h, hz, "#061A1F", "#FFD98A", temple=False))
        layers.append(f'<div class="L" style="top:{h * hz:.0f}px;background:linear-gradient(#8FA9B8,#4C6676 40%,#22343F)"></div>')
        layers.append(_tree(w * (.04 if focus != "left" else .62), h * .58, h * .36, animate))
        layers.append(_bokeh(r, w, h, ["#FFD98A", "#FF6B6B", "#FFFFFF"], 24, .3, .95))
        layers.append(_snow(r, w, h, 120, animate))
    elif kit == "tricolor":
        layers.append(_skyline(r, w, h, .8, "#050E24", "#FFE7C2", temple=False))
        layers.append(_fireworks(r, w, h, ["#FF9933", "#FFFFFF", "#22C55E"], 4, .7, animate))
        layers.append(_waves(w, h, .845))
        layers.append(_chakra(w * .5, h * .925, 40 * sx))
    else:  # fireworks
        layers.append(_skyline(r, w, h, hz, "#05051A", "#FFD36B", temple=False))
        layers.append(_water(r, w, h, hz, 1, p, "#FFD36B"))
        layers.append(_fireworks(r, w, h, ["#FFD24D", "#FF5CA8", "#7DD3FC", "#A78BFA", "#FFFFFF"], 6, .68, animate))
        layers.append(_bokeh(r, w, h, ["#FFD24D", "#FF5CA8", "#7DD3FC"], 20, .3, .95))
    return "\n".join(layers)


SCENE_CSS = """
.L{position:absolute;left:0;top:0;width:100%;height:100%}
.bk,.st,.sn,.pw{position:absolute;display:block;border-radius:50%}
.st{border-radius:3px}
.sn{background:#fff;box-shadow:0 0 6px #fff}
.pw{filter:blur(16px);mix-blend-mode:screen;opacity:.95}
.sl{position:absolute;border-radius:46% 46% 22% 22%/40% 40% 16% 16%;
 background:radial-gradient(ellipse 60% 55% at 50% 78%,#FFFBE0 0%,#FFD36B 22%,#FF9A2E 50%,#D9571A 82%,#9C2F0E 100%);
 box-shadow:0 0 22px 6px rgba(255,150,40,.55),0 0 70px 26px rgba(255,120,30,.22)}
.sl i{position:absolute;left:30%;right:30%;bottom:-4%;height:12%;border-radius:50%;background:#FFF4B0;box-shadow:0 0 14px 6px #FFD36B}
.hang{position:absolute;top:0}
.hang>i{display:block;position:absolute;left:0;top:0;width:2px;background:#C9A24A99}
@keyframes rise{from{transform:translateY(0) rotate(-2deg)}to{transform:translateY(-140px) rotate(2deg)}}
@keyframes flick{0%,100%{transform:scale(1,1)}25%{transform:scale(.94,1.06)}50%{transform:scale(1.04,.96)}75%{transform:scale(.97,1.03)}}
@keyframes tw{0%,100%{opacity:.25}50%{opacity:1}}
@keyframes fall{from{transform:translateY(-60px)}to{transform:translateY(240px)}}
@keyframes sway{0%,100%{transform:rotate(-3deg)}50%{transform:rotate(3deg)}}
@keyframes burst{0%{transform:scale(.1);opacity:0}12%{opacity:1}70%{opacity:.9}100%{transform:scale(1.08);opacity:0}}
.rise{animation:rise 12s linear infinite alternate}
.fl{animation:flick .9s ease-in-out infinite}
.tw{animation:tw 2.4s ease-in-out infinite}
.fall{animation:fall 7s linear infinite}
.sway{transform-origin:0 0;animation:sway 4s ease-in-out infinite}
.fw{animation:burst 2.6s ease-out infinite both}
"""


# ── the poster ─────────────────────────────────────────────────────────────
def _brush_swoosh(width: float, gold: list[str], uid: str = "sw") -> str:
    return (f'<svg width="{width:.0f}" height="{width * .09:.0f}" viewBox="0 0 1000 90" preserveAspectRatio="none" style="display:block;overflow:visible">'
            f'<defs><linearGradient id="{uid}" x1="0" x2="1"><stop offset="0" stop-color="{gold[1]}" stop-opacity="0"/>'
            f'<stop offset=".25" stop-color="{gold[1]}"/><stop offset=".8" stop-color="{gold[0]}"/><stop offset="1" stop-color="{gold[0]}" stop-opacity=".2"/></linearGradient></defs>'
            f'<path d="M10,82 C240,40 560,14 990,6 C640,26 330,52 30,88 Z" fill="url(#{uid})" style="filter:drop-shadow(0 0 10px {gold[1]}88)"/></svg>')


_FIT_JS = """<script>
document.fonts.ready.then(()=>{document.querySelectorAll('[data-fit]').forEach(el=>{
  const max=parseFloat(el.dataset.fit);let fs=parseFloat(getComputedStyle(el).fontSize);
  while(el.scrollWidth>max&&fs>40){fs-=4;el.style.fontSize=fs+'px'}});document.body.dataset.ready=1});
</script>"""


def _name_size(name: str, script: str) -> int:
    """Starting font size for the festival name (the fit script trims it further if needed)."""
    longest = max((len(w) for w in name.split()), default=6)
    total = len(name)
    base = 255 if script != "elegant" else 290
    if total > 9:
        base = int(base * (9 / total) ** .55)
    if longest > 10:
        base = int(base * (10 / longest) ** .7)
    return max(110, min(base, 300))


def poster_html(d: dict, bg_file: str | None, kit: str, p: dict, layout: str, seed: int,
                logo_file: str | None, website: str = "") -> str:
    """d: {greeting, name, quote, tagline: [2 lines], script}. Returns the complete HTML document (1080x1350)."""
    gold, hi = p["gold"], p.get("hi", "#FFE24D")
    script = SCRIPTS.get(d.get("script"), SCRIPTS["brush"])
    name = d.get("name") or "Celebrations"
    fs = _name_size(name, d.get("script", "brush"))
    left = layout == "left"
    bg = (f'<img class="L" src="{bg_file}" style="object-fit:cover">' if bg_file
          else scene_html(kit, p, W, H_, seed, focus="left" if left else "center"))
    shade = d.get("_shade", .55)
    overlay = (f'<div class="L" style="background:linear-gradient(180deg,rgba(5,4,20,{shade}) 0%,rgba(5,4,20,{shade * .55:.2f}) 34%,'
               f'rgba(5,4,20,0) 60%,rgba(5,4,20,0) 78%,rgba(5,4,20,{shade * .8:.2f}) 100%)"></div>')
    if left:
        overlay += f'<div class="L" style="background:linear-gradient(90deg,rgba(5,4,20,{shade * .7:.2f}),rgba(5,4,20,0) 62%)"></div>'
    logo = (f'<img src="{logo_file}" style="height:{104 if left else 120}px;width:auto;filter:drop-shadow(0 2px 10px rgba(0,0,0,.45))">' if logo_file
            else f'<div style="font:700 44px Montserrat;letter-spacing:.18em">{_e(company().get("name", "").upper())}</div>')
    tag = d.get("tagline") or []
    tag_html = "".join(f'<div>{_hl(t, hi)}</div>' for t in tag[:2])
    block_x = "left:84px;right:auto;align-items:flex-start;text-align:left" if left else "left:60px;right:60px;align-items:center;text-align:center"
    greet_offset = "margin-left:6px" if left else "margin-left:-260px"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{font_css()}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{W}px;height:{H_}px;overflow:hidden;background:{p['sky'][0]};color:#fff;font-family:Montserrat,'Segoe UI',Arial,sans-serif;-webkit-font-smoothing:antialiased}}
{SCENE_CSS}
.hi{{color:{hi};font-weight:700}}
.logo{{position:absolute;top:66px;{'left:84px' if left else 'left:0;right:0'};display:flex;justify-content:{'flex-start' if left else 'center'}}}
.quote{{font-weight:500;font-size:36px;line-height:1.32;letter-spacing:-.005em;text-shadow:0 2px 14px rgba(0,0,0,.65);max-width:{820 if left else 900}px}}
.block{{position:absolute;top:{262 if not left else 250}px;{block_x};display:flex;flex-direction:column}}
.greet{{font-family:'Great Vibes',cursive;font-size:{150 if not left else 140}px;line-height:.9;color:#fff;
 text-shadow:0 4px 24px rgba(0,0,0,.55);{greet_offset};margin-top:44px}}
.name{{font-family:{script},cursive;font-size:{fs}px;line-height:1.08;white-space:nowrap;padding:0 .14em .06em;margin-top:-.1em;
 background:linear-gradient(175deg,{gold[0]} 8%,{gold[1]} 46%,{gold[2]} 92%);-webkit-background-clip:text;background-clip:text;color:transparent;
 filter:drop-shadow(0 4px 18px rgba(0,0,0,.55)) drop-shadow(0 0 26px {gold[1]}55);transform:rotate(-3deg);transform-origin:{'left' if left else 'center'} center}}
.swoosh{{margin-top:-34px;{'margin-left:10px' if left else ''}}}
.tag{{position:absolute;{'left:84px' if left else 'right:66px'};bottom:{TAG_BOTTOM.get(kit, 72)}px;text-align:{'left' if left else 'right'};font-weight:600;font-size:31px;letter-spacing:.16em;line-height:1.45;
 text-transform:uppercase;text-shadow:0 2px 12px rgba(0,0,0,.7)}}
.tag .hi{{font-weight:700}}
.site{{position:absolute;{'right:66px' if left else 'left:66px'};bottom:76px;font-weight:600;font-size:22px;letter-spacing:.12em;opacity:.85;text-shadow:0 2px 10px rgba(0,0,0,.7)}}
</style></head><body>
{bg}
{overlay}
<div class="logo">{logo}</div>
<div class="block">
 <div class="quote">{_hl(d.get('quote', ''), hi)}</div>
 <div class="greet">{_e(d.get('greeting') or 'Happy')}</div>
 <div class="name" data-fit="{900 if not left else 880}">{_e(name)}</div>
 <div class="swoosh">{_brush_swoosh(760 if not left else 680, gold)}</div>
</div>
<div class="tag">{tag_html}</div>
{f'<div class="site">{_e(website)}</div>' if website else ''}
{_FIT_JS}
</body></html>"""


# ── the AI brief ───────────────────────────────────────────────────────────
SYSTEM = """You are the creative director of a premium technology brand, writing festival greetings.
Warm, respectful, culturally accurate, never salesy. Short lines that look beautiful in big type."""


def _brief(plan: dict, festival: str, kit: str, layout: str) -> str:
    c = company()
    used = rotation.recent_creative_memory(limit=20)
    return f"""BRAND: {c.get('name')} — {c.get('tagline')} | {c.get('website')} | audience: {c.get('audience')}
FESTIVAL / SPECIAL DAY: {festival}
{plan.get('context', '')}
DRAWING KIT suggested: {kit} ({KITS.get(kit, '')})
LAYOUT: {layout} ({'text centred, photo subject in the lower third' if layout == 'center' else 'text on the left half, photo subject on the right'})

Reference (the brand's best greeting): logo on top, quote 'Let the lights of Diwali guide us towards a
{{brighter}} tomorrow.', then a script 'Happy' and a huge gold brush-script 'Diwali', and bottom-right
'{{Bigger}} dreams. / {{Brighter}} future.'

Recently used (do NOT repeat these lines):
{used}

Write the greeting. Wrap exactly ONE word of the quote in {{curly braces}} (it gets a highlight colour), and the
first word of each tagline line too.
Return JSON:
{{
 "kit": "one of {list(KITS)} (keep '{kit}' unless it clearly does not fit this festival)",
 "greeting": "the small word(s) before the name, e.g. 'Happy', 'Merry', 'Eid', 'Wishing you a' (max 3 words)",
 "name": "the festival name as it should appear big, e.g. 'Diwali', 'Pongal', 'Christmas', 'New Year' (max 2 words)",
 "quote": "1 sentence, 8-14 words, links the festival's meaning to progress/technology/people subtly",
 "tagline": ["{{Word}} word.", "{{Word}} word."],
 "script": "brush | elegant | flowing (brush = bold like the reference; elegant for calm festivals)",
 "photo_prompt": "a detailed prompt for a PHOTOREALISTIC background photo for this festival: real objects and
   places typical of how it is celebrated in India (for Indian festivals), rich colours, cinematic night/golden-hour
   light, shallow depth of field; composition: {'main objects in the lower 40% and at the sides, the upper-middle 55% is calm open sky/background for text' if layout == 'center' else 'main objects on the RIGHT half and bottom, the left half is calm dark background for text'};
   absolutely NO text, letters, logos, watermarks or people's faces",
 "captions": {{
   "instagram": "warm greeting, 2-3 short lines, emojis ok, no selling",
   "facebook": "warm 2-3 short paragraphs from Team {c.get('name')}, may end with {c.get('website')}",
   "linkedin": "professional, heartfelt 3-4 short paragraphs connecting the festival's meaning to the team and clients, max 2 emojis"
 }},
 "hashtags": ["8-12 tags: the festival, India, the brand, tech"]
}}"""


def _cover(src: Path, out: Path, size: tuple[int, int]) -> Path:
    im = Image.open(src).convert("RGB")
    tw, th = size
    scale = max(tw / im.width, th / im.height)
    im = im.resize((max(tw, round(im.width * scale)), max(th, round(im.height * scale))), Image.LANCZOS)
    left, top = (im.width - tw) // 2, (im.height - th) // 2
    im.crop((left, top, left + tw, top + th)).save(out, quality=93)
    return out


def _shade_for(img: Path, layout: str) -> float:
    """Darker overlay when the text area of the photo is bright."""
    im = Image.open(img).convert("L")
    box = (0, int(im.height * .12), int(im.width * (.6 if layout == "left" else 1)), int(im.height * .56))
    lum = ImageStat.Stat(im.crop(box)).mean[0] / 255
    return round(min(.82, max(.38, .25 + lum * .9)), 2)


def _photo_ok(img: Path, festival: str) -> tuple[bool, str]:
    if not llm.vision_available():
        return True, ""
    try:
        data = llm.complete_json(
            f"This is a candidate background photo for a '{festival}' greeting poster (text will be added on top). "
            "Reject it if it contains any text/letters/watermark/logo, deformed or ugly objects, faces, if it does "
            f"not clearly look like {festival}, or if it looks cheap/low quality. "
            'Return JSON {"ok": true|false, "reason": "short"}.',
            "You are a strict photo editor.", max_tokens=300, images=[img])
        return bool(data.get("ok", True)), str(data.get("reason", ""))
    except Exception as e:
        log.warning("photo review failed: %s", e)
        return True, ""


def _pick_layout(own: bool = True) -> str:
    used = [i.theme.replace("festive_", "") for i in rotation._history("post", own_only=own) if (i.theme or "").startswith("festive_")]
    return rotation._lru(LAYOUTS, used, avoid_last=1)


def festival_name(plan: dict) -> str:
    return plan.get("festival") or re.sub(r"^Festival/special day:\s*|\s+on\s+\d.*$", "", plan.get("context", "")).strip() \
        or plan.get("topic", "")


def generate(plan: dict, day: date, item_id: int, product: dict | None = None, own: bool = True) -> dict:
    from . import post_designer

    work = storage.work_dir("post", item_id)
    festival = festival_name(plan)
    kit = kit_for(festival + " " + plan.get("topic", ""))
    layout = _pick_layout(own)
    progress.report(f"Writing the {festival or 'festival'} greeting", 20)
    data = llm.complete_json(_brief(plan, festival, kit, layout), SYSTEM, max_tokens=2500, design=True)
    if data.get("kit") in KITS:
        kit = data["kit"]
    p = dict(PALETTES[kit])
    d = {"greeting": str(data.get("greeting") or "Happy")[:40], "name": str(data.get("name") or festival)[:28],
         "quote": str(data.get("quote") or "")[:140],
         "tagline": [str(t)[:30] for t in (data.get("tagline") or [])][:2], "script": data.get("script", "brush")}
    seed = item_id * 7919 + day.toordinal()

    logo = assets.brand_logo(company())
    logo_file = None
    if logo:
        shutil.copy(logo["light"], work / "logo.png")
        logo_file = "logo.png"

    # background photo (optional) – checked, retried once, else the illustrated scene
    bg_file = None
    if assets.image_provider(purpose="festive") and data.get("photo_prompt"):
        prompt = (f"{data['photo_prompt']}. Photorealistic, professional photography, cinematic lighting, high detail, "
                  "8k, no text, no letters, no watermark, no logo")
        for attempt in range(2):
            progress.report("Creating the festive background photo" + (" (second try)" if attempt else ""), 35 + attempt * 12)
            raw = assets.generate_image(prompt, work / "raw.jpg", size=(W, H_), seed=seed + attempt * 101,
                                        purpose="festive")
            if not raw:
                break
            _cover(raw, work / "ai1.jpg", (W, H_))
            ok, why = _photo_ok(work / "ai1.jpg", festival)
            if ok:
                bg_file = "ai1.jpg"
                d["_shade"] = _shade_for(work / "ai1.jpg", layout)
                break
            log.info("festive photo rejected (%s): %s", festival, why)
    progress.report("Designing the greeting" + (" on the photo" if bg_file else " (illustrated scene)"), 60)

    html = poster_html(d, bg_file, kit, p, layout, seed, logo_file, (company().get("website") or "").replace("https://", "").replace("http://", "").strip("/"))
    preview = work / "render.png"
    issues = post_designer.render_design(html, work, preview)
    if issues:
        log.info("festive post #%s layout notes: %s", item_id, issues)

    out = storage.poster_path(day, item_id, plan, "festive")
    Image.open(preview).convert("RGB").save(out, quality=94)
    storage.poster_source_path(out).write_text(post_designer.inline_assets(html, work), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)

    tags = [t if t.startswith("#") else f"#{t}" for t in data.get("hashtags", [])]
    headline = f"{d['greeting']} {d['name']}"
    design = {"headline": headline, "format": "festive_greeting", "theme": f"festive_{layout}", "kit": kit,
              "background": "photo" if bg_file else "illustration", "product": "",
              "greeting": {k: v for k, v in d.items() if not k.startswith("_")}}
    return {"copy": {"captions": data.get("captions", {}), "hashtags": tags, **design},
            "media": out, "thumb": out, "hashtags": " ".join(tags), "format": "festive_greeting",
            "theme": f"festive_{layout}", "script_json": json.dumps(design, ensure_ascii=False, indent=2)}


# ── animated festive opening for videos ──────────────────────────────────────
def video_scene(d: dict, kit: str, size: tuple[int, int], dur: float, logo_file: str | None, seed: int) -> str:
    """A 5-6 s animated greeting (lanterns rising, flames flickering, fireworks …) with the text revealed."""
    w, h = size
    vert = h > w
    p = dict(PALETTES.get(kit, PALETTES["fireworks"]))
    gold, hi = p["gold"], p["hi"]
    script = SCRIPTS.get(d.get("script"), SCRIPTS["brush"])
    name = d.get("name") or "Celebrations"
    fs = int(_name_size(name, d.get("script", "brush")) * (1.15 if vert else .7))
    logo = f'<img src="{logo_file}" style="height:{100 if vert else 84}px">' if logo_file else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{font_css()}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{w}px;height:{h}px;overflow:hidden;background:{p['sky'][0]};color:#fff;font-family:Montserrat,Arial,sans-serif}}
{SCENE_CSS}
.hi{{color:{hi};font-weight:700}}
@keyframes up{{from{{opacity:0;transform:translateY(30px)}}to{{opacity:1;transform:none}}}}
@keyframes ink{{from{{opacity:0;transform:rotate(-3deg) scale(.82) translateY(24px)}}60%{{opacity:1}}to{{opacity:1;transform:rotate(-3deg)}}}}
@keyframes zoom{{from{{transform:scale(1.08)}}to{{transform:scale(1)}}}}
@keyframes out{{to{{opacity:0}}}}
.bgz{{position:absolute;inset:0;animation:zoom {dur:.2f}s ease-out both}}
.a{{animation:up .9s cubic-bezier(.2,.8,.2,1) both}}
.stage{{position:absolute;inset:0;animation:out .5s ease-in {dur - .5:.2f}s both}}
.box{{position:absolute;left:0;right:0;top:{h * (.14 if vert else .06):.0f}px;display:flex;flex-direction:column;align-items:center;text-align:center;gap:{18 if vert else 4}px}}
.name{{font-family:{script},cursive;font-size:{fs}px;line-height:1.1;white-space:nowrap;padding:0 .14em .06em;
 background:linear-gradient(175deg,{gold[0]} 8%,{gold[1]} 46%,{gold[2]} 92%);-webkit-background-clip:text;background-clip:text;color:transparent;
 filter:drop-shadow(0 4px 18px rgba(0,0,0,.55)) drop-shadow(0 0 26px {gold[1]}66);animation:ink 1.4s cubic-bezier(.3,.7,.2,1) 1.1s both}}
.greet{{font-family:'Great Vibes',cursive;font-size:{160 if vert else 96}px;line-height:.9;text-shadow:0 4px 24px rgba(0,0,0,.55)}}
.quote{{font-weight:500;font-size:{46 if vert else 31}px;max-width:{w - 160}px;line-height:1.35;text-shadow:0 2px 14px rgba(0,0,0,.7)}}
</style></head><body>
<div class="bgz">{scene_html(kit, p, w, h, seed, animate=True)}</div>
<div class="L" style="background:linear-gradient(180deg,rgba(5,4,20,.55),rgba(5,4,20,.15) 55%,rgba(5,4,20,0) 70%)"></div>
<div class="stage"><div class="box">
 <div class="a" style="animation-delay:.2s">{logo}</div>
 <div class="greet a" style="animation-delay:.6s;margin-top:{40 if vert else 6}px">{_e(d.get('greeting') or 'Happy')}</div>
 <div class="name">{_e(name)}</div>
 <div class="a" style="animation-delay:2.2s">{_brush_swoosh(w * (.6 if vert else .42), gold, 'vs')}</div>
 <div class="quote a" style="animation-delay:2.6s">{_hl(d.get('quote', ''), hi)}</div>
</div></div>
</body></html>"""


def video_greeting(plan: dict, festival: str) -> dict:
    """Short greeting texts for a video's festive opening."""
    kit = kit_for(festival)
    data = llm.complete_json(
        f"Festival: {festival}. Brand: {company().get('name')} ({company().get('tagline')}).\n"
        "Write the opening card of a short promo video released on this festival. Return JSON "
        '{"greeting": "Happy|Merry|… (max 3 words)", "name": "festival name, max 2 words", '
        '"quote": "one warm sentence, 8-12 words, with ONE {highlighted} word", "script": "brush|elegant|flowing", '
        '"voice": "one short spoken line wishing the audience, max 14 words"}',
        SYSTEM, max_tokens=600)
    return {"greeting": str(data.get("greeting") or "Happy")[:40], "name": str(data.get("name") or festival)[:28],
            "quote": str(data.get("quote") or "")[:120], "script": data.get("script", "brush"),
            "voice": str(data.get("voice") or "")[:160], "kit": kit}
