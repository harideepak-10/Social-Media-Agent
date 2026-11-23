"""Turns a website's own design system into a post theme and a video theme ("Create from URL").

browser.brand_info() reads the page in a real browser: background colours sampled across the first two
screens, heading/body fonts and colours, the main button (colour, text colour, corner radius) and a card.
Here that becomes the same theme shape as catalog.POST_THEMES / VIDEO_THEMES, with readable contrast
guaranteed, so the poster or video looks like it came from the client's own design team.
"""
from __future__ import annotations

import re
from collections import Counter

SYSTEM_FONTS = {"system-ui", "-apple-system", "blinkmacsystemfont", "segoe ui", "helvetica", "helvetica neue",
                "arial", "sans-serif", "serif", "monospace", "ui-sans-serif", "ui-serif", "apple color emoji",
                "segoe ui emoji", "segoe ui symbol", "noto color emoji", "times", "times new roman", "georgia",
                "verdana", "tahoma", "trebuchet ms", "courier new", "inherit", "initial"}


def _rgb(c) -> tuple[int, int, int] | None:
    if not c:
        return None
    c = str(c).strip()
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?", c)
    if m:
        if m.group(4) is not None and float(m.group(4)) < 0.5:
            return None
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.match(r"#([0-9a-f]{3}|[0-9a-f]{6})$", c, re.I)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return None


def _hex(c) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(v)))) for v in c)


def _lin(v: float) -> float:
    v /= 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def lum(c) -> float:
    r, g, b = c
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a, b) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a, b, t: float):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def vivid(c) -> bool:
    return max(c) - min(c) > 45 and max(c) > 40


def _readable(c, bg, need: float):
    """Darken/lighten c until it reaches the contrast `need` against bg."""
    if contrast(c, bg) >= need:
        return c
    target = (0, 0, 0) if lum(bg) > 0.35 else (255, 255, 255)
    for t in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9):
        cc = mix(c, target, t)
        if contrast(cc, bg) >= need:
            return cc
    return target


def _font(stack: str, fallback: str) -> tuple[str, bool]:
    """First real font family of a CSS stack -> (name, is_serif)."""
    parts = [p.strip().strip("'\"") for p in (stack or "").split(",") if p.strip()]
    serif = any(p.lower() == "serif" for p in parts) or any(re.search(r"serif|garamond|playfair|georgia|times|lora|merriweather", p, re.I)
                                                            and "sans" not in p.lower() for p in parts[:1])
    for p in parts:
        if p.lower() not in SYSTEM_FONTS and not p.lower().startswith("var("):
            return p, serif
    return ("Playfair Display" if serif else fallback), serif


def _px(v, default: int) -> int:
    try:
        return int(round(float(str(v).replace("px", ""))))
    except (TypeError, ValueError):
        return default


def build(design: dict, colors: dict | None = None) -> tuple[dict, dict] | None:
    """(post_theme, video_theme) or None when the site couldn't be read well enough."""
    design = design or {}
    colors = colors or {}
    bgs = [c for c in (_rgb(x) for x in design.get("bgs") or []) if c]
    if not bgs and not colors:
        return None
    bucket = Counter(tuple(v // 8 * 8 for v in c) for c in bgs)  # similar shades count together…
    if bucket:
        top = bucket.most_common(1)[0][0]
        bg = Counter(c for c in bgs if tuple(v // 8 * 8 for v in c) == top).most_common(1)[0][0]  # …exact colour wins
    else:
        bg = (255, 255, 255)
    # a page that is mostly a big coloured hero still counts: prefer the most common NEUTRAL-ish colour if close
    dark = lum(bg) < 0.3

    head = design.get("heading") or {}
    body = design.get("body") or {}
    ink = _rgb(head.get("color")) or _rgb(body.get("color")) or ((245, 245, 245) if dark else (20, 20, 20))
    ink = _readable(ink, bg, 7)
    muted = _rgb(body.get("color"))
    if not muted or contrast(muted, bg) < 3.5 or muted == ink:
        muted = mix(ink, bg, 0.38)
    muted = _readable(muted, bg, 4)

    btn = design.get("button") or {}
    accent = _rgb(btn.get("bg"))
    primary = _rgb(colors.get("primary"))
    if not accent or not vivid(accent) or contrast(accent, bg) < 1.6:
        accent = primary if primary and vivid(primary) else (accent or (79, 70, 229))
    accent = _readable(accent, bg, 2.6)
    btn_text = _rgb(btn.get("color"))
    if not btn_text or contrast(btn_text, accent) < 2.2:  # keep the site's own button text colour when it's legible
        btn_text = (255, 255, 255) if contrast((255, 255, 255), accent) >= contrast((17, 17, 17), accent) else (17, 17, 17)
    accent2 = _rgb(colors.get("secondary"))
    if not accent2 or sum(abs(a - b) for a, b in zip(accent2, accent)) < 60:
        accent2 = mix(accent, ink, 0.35)

    card = design.get("card") or {}
    surface = _rgb(card.get("bg"))
    if not surface or surface == bg or contrast(surface, ink) < 4.5:
        surface = mix(bg, (255, 255, 255) if dark else ink, 0.08 if dark else 0.035)
        if not dark and lum(bg) < 0.9:
            surface = mix(bg, (255, 255, 255), 0.6)
    radius = _px(card.get("radius") or btn.get("radius"), 12)
    btn_radius = _px(btn.get("radius"), radius)

    hf, h_serif = _font(head.get("family", ""), "Inter")
    bf, _ = _font(body.get("family", ""), "Inter")
    hw = _px(head.get("weight"), 700)
    hw = 700 if hw < 500 else min(hw, 900)
    upper = (head.get("transform") or "") == "uppercase"

    feel = (f"the client's own website look: {'dark' if dark else 'light'} {_hex(bg)} background, {hf} "
            f"{'serif ' if h_serif else ''}headings{' in UPPERCASE' if upper else ''}, {bf} body text, "
            f"{radius}px rounded cards, {'pill' if btn_radius >= 18 else f'{btn_radius}px'} buttons in {_hex(accent)} "
            f"with {_hex(btn_text)} text{(' saying ' + repr(btn.get('text'))) if btn.get('text') else ''}, "
            f"{'soft shadows' if card.get('shadow') else 'flat cards'}")
    post = {"label": "Website's own design", "bg": _hex(bg), "surface": _hex(surface), "ink": _hex(ink),
            "muted": _hex(muted), "accent": _hex(accent), "accent2": _hex(accent2), "logo": "light" if dark else "dark",
            "heading_font": f"{hf}:{hw}", "body_font": f"{bf}:400,600", "mood": feel,
            "_site": True, "_radius": radius, "_btn_radius": btn_radius, "_btn_text": _hex(btn_text),
            "_uppercase": upper, "_serif": h_serif}
    video = {"bg": _hex(bg), "bg2": _hex(mix(bg, accent, 0.16 if dark else 0.08)), "panel": _hex(surface),
             "ink": _hex(ink), "muted": _hex(muted), "accent": _hex(accent), "accent2": _hex(accent2),
             "heading": hf, "head_weight": hw, "body": bf, "serif": h_serif, "logo": "light" if dark else "dark",
             "btn_text": _hex(btn_text), "_site": True}
    return post, video
