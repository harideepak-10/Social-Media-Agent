"""Brand assets (logo in light/dark variants) and optional AI image generation."""
from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path

import httpx
from PIL import Image

from ..config import ASSETS_DIR, CACHE_DIR, DATA_DIR, env, settings

log = logging.getLogger(__name__)

_FIND_LOGO_JS = """
() => {
  const imgs = [...document.querySelectorAll('header img, nav img, [class*="logo"] img, img[class*="logo"], img[alt*="logo" i], img[src*="logo" i], header svg, [class*="logo"] svg')];
  const vis = imgs.filter(e => { const r = e.getBoundingClientRect(); return r.width > 30 && r.height > 12 && r.top < 400; });
  const el = vis[0];
  if (!el) return null;
  el.setAttribute('data-dma-logo', '1');
  // make everything behind the logo transparent so the screenshot keeps only the logo
  let a = el; while (a) { a.style.setProperty('background', 'transparent', 'important'); a.style.setProperty('box-shadow', 'none', 'important'); a = a.parentElement; }
  return { src: el.tagName === 'IMG' ? (el.currentSrc || el.src) : '' };
}
"""


def _luminance_of_logo(img: Image.Image) -> tuple[float, bool]:
    """(mean luminance of visible pixels 0..1, has_transparency)."""
    rgba = img.convert("RGBA")
    small = rgba.resize((max(1, rgba.width // 4), max(1, rgba.height // 4)))
    px = [p for p in small.getdata() if p[3] > 128]
    transparent = any(p[3] < 20 for p in small.getdata())
    if not px:
        return 0.5, transparent
    lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _ in px) / (255 * len(px))
    return lum, transparent


def _recolor(img: Image.Image, rgb: tuple[int, int, int]) -> Image.Image:
    rgba = img.convert("RGBA")
    solid = Image.new("RGBA", rgba.size, rgb + (255,))
    solid.putalpha(rgba.getchannel("A"))
    return solid


def logo_variants(src: Path, out_dir: Path) -> dict:
    """Make 'dark' (for light backgrounds) and 'light' (for dark backgrounds) versions of a logo.
    Opaque logos (no transparency) are returned as 'boxed' – templates place them on a white chip."""
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    lum, transparent = _luminance_of_logo(img)
    dark, light = out_dir / "logo_dark.png", out_dir / "logo_light.png"
    if not transparent:
        img.save(dark)
        img.save(light)
        return {"dark": dark, "light": light, "boxed": True}
    if lum < 0.55:          # dark logo -> keep for light bg, make a white version for dark bg
        img.save(dark)
        _recolor(img, (255, 255, 255)).save(light)
    else:                   # light logo -> keep for dark bg, make a near-black version for light bg
        img.save(light)
        _recolor(img, (20, 20, 20)).save(dark)
    return {"dark": dark, "light": light, "boxed": False}


def capture_logo(url: str, out: Path) -> Path | None:
    """Screenshot the website's logo element with a transparent background."""
    from ..generators import browser

    try:
        with browser.browser_context(viewport={"width": 1366, "height": 900}, device_scale_factor=3) as ctx:
            page = ctx.new_page()
            browser.open_page(page, url)
            found = page.evaluate(_FIND_LOGO_JS)
            if not found:
                return None
            # prefer the original image file (keeps real transparency); svg/webp -> element screenshot
            src = found.get("src", "")
            if src and src.split("?")[0].lower().endswith(".png"):
                try:
                    r = httpx.get(src, timeout=30, follow_redirects=True)
                    r.raise_for_status()
                    out.write_bytes(r.content)
                    Image.open(out).verify()
                    return out
                except Exception:
                    pass
            page.locator("[data-dma-logo]").first.screenshot(path=str(out), omit_background=True)
        return out
    except Exception as e:
        log.warning("logo capture failed for %s: %s", url, e)
        return None


def brand_logo(brand: dict) -> dict | None:
    """Logo variants for the brand in use: configured logo_path, else captured from its website."""
    configured = DATA_DIR / (brand.get("logo_path") or "") if brand.get("logo_path") else None
    key = hashlib.md5((brand.get("website") or brand.get("name", "")).encode()).hexdigest()[:10]
    out_dir = CACHE_DIR / f"logo_{key}"
    if configured and configured.is_file():
        return logo_variants(configured, out_dir)
    if (out_dir / "logo_dark.png").exists():
        lum, transparent = _luminance_of_logo(Image.open(out_dir / "logo_dark.png"))
        return {"dark": out_dir / "logo_dark.png", "light": out_dir / "logo_light.png", "boxed": not transparent}
    if brand.get("website"):
        out_dir.mkdir(parents=True, exist_ok=True)
        raw = capture_logo(brand["website"], out_dir / "logo_raw.png")
        if raw:
            own = (settings().get("company") or {}).get("website") == brand.get("website")
            if own and not (ASSETS_DIR / "logo.png").exists():  # keep a copy you can check / replace
                (ASSETS_DIR / "logo.png").write_bytes(raw.read_bytes())
            return logo_variants(raw, out_dir)
    return None


# ── optional AI images (festive backgrounds, meme / photo styles) ───────────
def image_provider(purpose: str = "general") -> str:
    """openai | gemini | pollinations | '' (none). `purpose` is kept for callers (festive / general)."""
    p = env("IMAGE_PROVIDER", "none").lower()
    if p == "openai" and env("OPENAI_API_KEY"):
        return "openai"
    if p == "gemini" and env("GEMINI_API_KEY"):
        return "gemini"
    if p == "pollinations" and env("POLLINATIONS_API_KEY"):
        return "pollinations"
    return ""


def _pollinations(prompt: str, out: Path, size: tuple[int, int], seed: int | None) -> Path:
    """Pollinations.ai (Flux) – free key from enter.pollinations.ai. (The old keyless endpoint gives small,
    watermarked images that ignore most of the prompt, so it is not used.)"""
    from urllib.parse import quote

    w, h = size
    params = {"width": w, "height": h, "model": env("POLLINATIONS_MODEL", "flux"), "nologo": "true",
              "enhance": "false", "safe": "true", "seed": seed if seed is not None else 42}
    r = httpx.get(f"https://gen.pollinations.ai/image/{quote(prompt[:1500], safe='')}", params=params,
                  headers={"Authorization": f"Bearer {env('POLLINATIONS_API_KEY')}"}, timeout=240, follow_redirects=True)
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"Pollinations returned {r.headers.get('content-type')}: {r.text[:200]}")
    out.write_bytes(r.content)
    im = Image.open(out).convert("RGB")
    if im.width < 500 or im.height < 500:
        raise RuntimeError(f"image too small ({im.width}x{im.height})")
    im.save(out, quality=95)
    return out


def generate_image(prompt: str, out: Path, portrait: bool = True, size: tuple[int, int] | None = None,
                   seed: int | None = None, purpose: str = "general") -> Path | None:
    provider = image_provider(purpose)
    if not provider:
        return None
    try:
        if provider == "pollinations":
            return _pollinations(prompt, out, size or ((1080, 1350) if portrait else (1350, 1080)), seed)
        if provider == "openai":
            r = httpx.post("https://api.openai.com/v1/images/generations", timeout=180,
                           headers={"Authorization": f"Bearer {env('OPENAI_API_KEY')}"},
                           json={"model": env("OPENAI_IMAGE_MODEL", "gpt-image-1"), "prompt": prompt,
                                 "size": "1024x1536" if portrait else "1536x1024", "n": 1})
            r.raise_for_status()
            out.write_bytes(base64.b64decode(r.json()["data"][0]["b64_json"]))
        else:
            model = env("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
            body = {"contents": [{"parts": [{"text": prompt}]}]}
            if size:
                body["generationConfig"] = {"imageConfig": {"aspectRatio": "4:5" if size[1] > size[0] else "16:9"}}
            r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                           params={"key": env("GEMINI_API_KEY")}, timeout=180, json=body)
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            data = next(p["inlineData"]["data"] for p in parts if "inlineData" in p)
            out.write_bytes(base64.b64decode(data))
        return out
    except Exception as e:
        log.warning("AI image generation failed (%s): %s", provider, e)
        return None
