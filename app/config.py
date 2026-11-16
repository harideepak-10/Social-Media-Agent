"""Loads .env secrets and config/*.yaml settings."""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# DATA_DIR: where everything that changes lives (database, media, settings edits, logo, music, cache).
# Default = the project folder. On a server, point it at a persistent disk, e.g. DATA_DIR=/var/data
DATA_DIR = Path(os.getenv("DATA_DIR", "").strip() or BASE_DIR)
CONFIG_DIR = DATA_DIR / "config"
MEDIA_DIR = DATA_DIR / "media"
ASSETS_DIR = DATA_DIR / "assets"
CACHE_DIR = DATA_DIR / ".cache"

for _d in (MEDIA_DIR, CACHE_DIR, CONFIG_DIR, ASSETS_DIR / "music", ASSETS_DIR / "fonts"):
    _d.mkdir(parents=True, exist_ok=True)

if DATA_DIR != BASE_DIR:  # first start on a fresh disk: copy the default config & assets from the repo
    import shutil as _sh
    for _src_dir, _dst_dir in ((BASE_DIR / "config", CONFIG_DIR), (BASE_DIR / "assets", ASSETS_DIR)):
        for _f in _src_dir.rglob("*"):
            _dst = _dst_dir / _f.relative_to(_src_dir)
            if _f.is_file() and not _dst.exists():
                _dst.parent.mkdir(parents=True, exist_ok=True)
                _sh.copy2(_f, _dst)

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def settings() -> dict:
    return _load_yaml("settings.yaml")


def reload_settings() -> dict:
    settings.cache_clear()
    return settings()


_write_lock = threading.Lock()


def _rt_yaml():
    from ruamel.yaml import YAML
    y = YAML()  # round-trip: keeps the comments in your yaml files
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def update_yaml(name: str, patch: dict, replace_keys: tuple[str, ...] = ()) -> dict:
    """Merge `patch` into config/<name> keeping comments. Keys in `replace_keys` are replaced whole
    (lists such as products), everything else is merged key by key."""
    path = CONFIG_DIR / name
    y = _rt_yaml()
    with _write_lock:
        data = y.load(path.read_text(encoding="utf-8")) if path.exists() else None
        if data is None:
            from ruamel.yaml.comments import CommentedMap
            data = CommentedMap()

        def merge(dst, src, top=False):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict) and not (top and k in replace_keys):
                    merge(dst[k], v)
                else:
                    dst[k] = v

        merge(data, patch, top=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            y.dump(data, f)
        tmp.replace(path)
    try:  # cloud mode: keep a copy in the database so the edit survives restarts
        from .db import save_config_file
        save_config_file(name, path.read_text(encoding="utf-8"))
    except Exception as e:  # never block a settings save
        import logging
        logging.getLogger(__name__).warning("could not store %s in the database: %s", name, e)
    return reload_settings() if name == "settings.yaml" else _load_yaml(name)


def save_schedule(schedule: dict) -> None:
    """Persist an edited weekly schedule back to settings.yaml (keeps other keys and comments)."""
    update_yaml("settings.yaml", {"schedule": {d: schedule.get(d, "none") for d in WEEKDAYS}})


def events_config() -> dict:
    return _load_yaml("events.yaml")


_brand_override: ContextVar[dict | None] = ContextVar("brand_override", default=None)


def company() -> dict:
    """Brand in use: your company from settings.yaml, or another website's brand during a
    'generate from any URL' run (see `use_brand`)."""
    return _brand_override.get() or settings().get("company", {})


@contextmanager
def use_brand(brand: dict):
    token = _brand_override.set(brand)
    try:
        yield
    finally:
        _brand_override.reset(token)


def public_url(path: Path | str) -> str:
    """Public URL for a file inside MEDIA_DIR (served at /media)."""
    rel = Path(path).resolve().relative_to(MEDIA_DIR.resolve()).as_posix()
    return f"{env('PUBLIC_BASE_URL', 'http://localhost:8000').rstrip('/')}/media/{rel}"
