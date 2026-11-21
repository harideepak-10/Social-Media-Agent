"""Guards against the AI misspelling the brand name ('krypso', 'Kripsos', 'KRYPOS' …).

The design model sometimes drops or swaps a letter of the brand name in the visual or the captions. This fixes
near-misses deterministically (no AI) while keeping the original casing style, before the poster is rendered.
"""
from __future__ import annotations

import re

from ..config import company

_WORD = re.compile(r"[A-Za-z][A-Za-z]{2,}")


def _dist(a: str, b: str, limit: int = 3) -> int:
    """Levenshtein distance (small strings, early exit)."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _names() -> list[str]:
    """Brand words to protect: the company name and the main word of the website domain."""
    c = company()
    out = []
    for raw in (c.get("name") or "", re.sub(r"^https?://(www\.)?", "", c.get("website") or "").split(".")[0]):
        for w in re.findall(r"[A-Za-z]{5,}", raw):
            if w.lower() not in [x.lower() for x in out]:
                out.append(w)
    return out


def _cased(token: str, brand: str) -> str:
    if token.isupper():
        return brand.upper()
    if token.islower():
        return brand.lower()
    return brand[0].upper() + brand[1:].lower() if brand.islower() or brand.isupper() else brand


def _near(token: str, brand: str) -> bool:
    t, b = token.lower(), brand.lower()
    if t == b or t[:2] != b[:2]:
        return False
    d = _dist(t, b)
    return d == 1 or (d == 2 and len(b) >= 7 and abs(len(t) - len(b)) <= 1)


def fix_text(text: str, names: list[str] | None = None) -> tuple[str, list[str]]:
    """Returns (fixed text, list of 'wrong → right' changes)."""
    names = names if names is not None else _names()
    if not names or not text:
        return text, []
    changes: list[str] = []

    def sub(m: re.Match) -> str:
        tok = m.group(0)
        for b in names:
            if _near(tok, b):
                new = _cased(tok, b)
                changes.append(f"{tok} → {new}")
                return new
        return tok

    return _WORD.sub(sub, text), changes


_TAG = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)", re.S | re.I)


def fix_html(html: str) -> tuple[str, list[str]]:
    """Fix the brand name in visible text only (never inside tags, CSS, scripts, data: URIs)."""
    names = _names()
    if not names:
        return html, []
    out, changes = [], []
    for part in _TAG.split(html):
        if not part or part.startswith("<"):
            out.append(part)
            continue
        fixed, ch = fix_text(part, names)
        out.append(fixed)
        changes += ch
    return "".join(out), changes


def fix_captions(captions: dict) -> dict:
    return {k: fix_text(v)[0] if isinstance(v, str) else v for k, v in (captions or {}).items()}


def fix_obj(obj):
    """Fix every string inside a JSON-like structure (storyboards, greetings)."""
    if isinstance(obj, str):
        return fix_text(obj)[0]
    if isinstance(obj, list):
        return [fix_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: (fix_obj(v) if not k.startswith("_") else v) for k, v in obj.items()}
    return obj
