"""Small LLM wrapper: Anthropic (default) or Groq, with a JSON helper."""
from __future__ import annotations

import json
import os
import logging
import re

from .config import env

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def complete(prompt: str, system: str = "", max_tokens: int = 2000, temperature: float = 0.8,
             images: list | None = None, design: bool = False) -> str:
    """images: optional list of image file paths (Anthropic only) — lets the model SEE screenshots.
    design=True uses ANTHROPIC_DESIGN_MODEL (a stronger model for layouts / storyboards)."""
    provider = env("LLM_PROVIDER", "anthropic").lower()
    if provider == "groq" and not images and not (design and env("ANTHROPIC_API_KEY")):
        return _groq(prompt, system, max_tokens, temperature)
    return _anthropic(prompt, system, max_tokens, temperature, images, design)


def vision_available() -> bool:
    return bool(env("ANTHROPIC_API_KEY"))


def _image_block(path, max_side: int = 1400) -> dict:
    """Downscaled JPEG of an image file (keeps vision requests small and fast)."""
    import base64
    import io

    from PIL import Image

    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(buf.getvalue()).decode()}}


def _missing(name: str) -> str:
    where = "Render → your service → Environment" if os.environ.get("RENDER") else "the .env file"
    return f"{name} is not set – add it in {where}, then restart"


def _anthropic(prompt, system, max_tokens, temperature, images=None, design=False) -> str:
    key = (env("ANTHROPIC_API_KEY") or "").strip().strip('"')
    if not key:
        raise LLMError(_missing("ANTHROPIC_API_KEY"))
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    model = env("ANTHROPIC_MODEL", "claude-haiku-4-5")
    if design:
        model = env("ANTHROPIC_DESIGN_MODEL", model)
    content = [_image_block(p) for p in (images or [])] + [{"type": "text", "text": prompt}]
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system or "You are a helpful assistant.",
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _groq(prompt, system, max_tokens, temperature) -> str:
    key = env("GROQ_API_KEY")
    if not key:
        raise LLMError(_missing("GROQ_API_KEY"))
    from groq import Groq

    client = Groq(api_key=key)
    resp = client.chat.completions.create(
        model=env("GROQ_MODEL", "llama-3.3-70b-versatile"),
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "system", "content": system or "You are a helpful assistant."},
                  {"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


def complete_json(prompt: str, system: str = "", max_tokens: int = 2500, retries: int = 2,
                  images: list | None = None, design: bool = False) -> dict:
    """Ask for JSON and parse it robustly (strips code fences / surrounding prose)."""
    sys_msg = (system + "\n\n" if system else "") + "Reply with ONLY valid JSON. No markdown, no commentary."
    last_err = None
    for attempt in range(retries + 1):
        raw = complete(prompt, sys_msg, max_tokens=max_tokens, temperature=0.8 if attempt == 0 else 0.4,
                       images=images, design=design)
        try:
            return _parse_json(raw)
        except ValueError as e:
            last_err = e
            log.warning("LLM returned invalid JSON (attempt %s): %s", attempt + 1, raw[:200])
    raise LLMError(f"LLM did not return valid JSON: {last_err}")


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError("no JSON object found")
