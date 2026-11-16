"""Pillow helpers: fonts, brand gradients, wrapped text, cards and caption overlays."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import ASSETS_DIR, DATA_DIR, company

_FONT_CANDIDATES = {
    True: [  # bold
        "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
    False: [
        "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
}


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    custom = sorted((ASSETS_DIR / "fonts").glob("*Bold*.ttf" if bold else "*Regular*.ttf"))
    for path in [str(p) for p in custom] + _FONT_CANDIDATES[bold]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def colors() -> dict:
    c = company().get("brand_colors") or {}
    return {
        "primary": hex_rgb(c.get("primary", "#4F46E5")),
        "secondary": hex_rgb(c.get("secondary", "#0EA5E9")),
        "text": hex_rgb(c.get("text", "#FFFFFF")),
    }


def gradient(size: tuple[int, int], c1=None, c2=None) -> Image.Image:
    c = colors()
    c1, c2 = c1 or c["primary"], c2 or c["secondary"]
    w, h = size
    base = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        base.putpixel((0, y), tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)))
    img = base.resize((w + h, w + h)).rotate(35, resample=Image.BICUBIC)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    img = img.crop((left, top, left + w, top + h))
    # soft glow circles for depth
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((-w * 0.3, -h * 0.2, w * 0.6, h * 0.45), fill=(255, 255, 255, 40))
    d.ellipse((w * 0.5, h * 0.6, w * 1.4, h * 1.3), fill=(0, 0, 0, 50))
    glow = glow.filter(ImageFilter.GaussianBlur(w // 8))
    return Image.alpha_composite(img.convert("RGBA"), glow)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=fnt) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_text(draw, text, max_width, max_height, start=110, min_size=36, bold=True, spacing=1.15):
    size = start
    while size >= min_size:
        fnt = font(size, bold)
        lines = wrap(draw, text, fnt, max_width)
        if len(lines) * size * spacing <= max_height:
            return fnt, lines
        size -= 4
    fnt = font(min_size, bold)
    return fnt, wrap(draw, text, fnt, max_width)


def draw_lines(draw, lines, fnt, x, y, fill, center_width=None, spacing=1.15, shadow=True):
    size = fnt.size
    for i, ln in enumerate(lines):
        lx = x
        if center_width:
            lx = x + (center_width - draw.textlength(ln, font=fnt)) / 2
        ly = y + i * size * spacing
        if shadow:
            draw.text((lx + 3, ly + 3), ln, font=fnt, fill=(0, 0, 0, 90))
        draw.text((lx, ly), ln, font=fnt, fill=fill)
    return y + len(lines) * size * spacing


def paste_logo(img: Image.Image, pos="top-left", max_h=90, margin=60) -> None:
    path = DATA_DIR / (company().get("logo_path") or "")
    if path.is_file():
        logo = Image.open(path).convert("RGBA")
        ratio = max_h / logo.height
        logo = logo.resize((int(logo.width * ratio), max_h))
        x = margin if "left" in pos else img.width - logo.width - margin
        y = margin if "top" in pos else img.height - logo.height - margin
        img.alpha_composite(logo, (x, y))
    else:  # brand name as text
        d = ImageDraw.Draw(img)
        fnt = font(44, True)
        name = company().get("name", "")
        x = margin if "left" in pos else img.width - d.textlength(name, font=fnt) - margin
        y = margin if "top" in pos else img.height - 60 - margin
        d.text((x, y), name, font=fnt, fill=colors()["text"])


def rounded_screenshot(shot: Image.Image, width: int, radius: int = 28) -> Image.Image:
    ratio = width / shot.width
    shot = shot.convert("RGBA").resize((width, int(shot.height * ratio)))
    mask = Image.new("L", shot.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *shot.size), radius, fill=255)
    out = Image.new("RGBA", shot.size, (0, 0, 0, 0))
    out.paste(shot, (0, 0), mask)
    return out


def text_card(path: Path, size: tuple[int, int], title: str, subtitle: str = "", footer: str = "") -> Path:
    """Full-screen branded card (video intro/outro)."""
    w, h = size
    img = gradient(size)
    d = ImageDraw.Draw(img)
    pad = int(w * 0.09)
    fnt, lines = fit_text(d, title, w - 2 * pad, h * 0.35, start=int(w * 0.11))
    block_h = len(lines) * fnt.size * 1.15
    y = (h - block_h) / 2 - (h * 0.05 if subtitle else 0)
    y = draw_lines(d, lines, fnt, pad, y, colors()["text"], center_width=w - 2 * pad)
    if subtitle:
        sf, sl = fit_text(d, subtitle, w - 2 * pad, h * 0.15, start=int(w * 0.05), bold=False)
        draw_lines(d, sl, sf, pad, y + h * 0.03, (255, 255, 255, 230), center_width=w - 2 * pad)
    if footer:
        ff = font(int(w * 0.035), False)
        d.text(((w - d.textlength(footer, font=ff)) / 2, h - pad - ff.size), footer, font=ff, fill=(255, 255, 255, 220))
    paste_logo(img, "top-left", max_h=int(w * 0.07), margin=pad // 2)
    img.convert("RGB").save(path, quality=95)
    return path


def caption_overlay(path: Path, size: tuple[int, int], text: str) -> Path:
    """Transparent PNG with a subtitle pill near the bottom-third (Reels safe area)."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    max_w = int(w * 0.84)
    fnt, lines = fit_text(d, text, max_w - 40, h * 0.16, start=int(w * 0.055), min_size=int(w * 0.035))
    line_h = fnt.size * 1.2
    box_h = len(lines) * line_h + 40
    box_w = max(d.textlength(ln, font=fnt) for ln in lines) + 60
    x0 = (w - box_w) / 2
    y0 = h * 0.70 - box_h / 2
    d.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), 24, fill=(0, 0, 0, 200))
    for i, ln in enumerate(lines):
        lx = (w - d.textlength(ln, font=fnt)) / 2
        d.text((lx, y0 + 20 + i * line_h), ln, font=fnt, fill=(255, 255, 255, 255))
    img.save(path)
    return path
