"""Loads .env secrets and config/*.yaml settings."""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
MEDIA_DIR = BASE_DIR / "media"
ASSETS_DIR = BASE_DIR / "assets"
CACHE_DIR = BASE_DIR / ".cache"

for _d in (MEDIA_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

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


def save_schedule(schedule: dict) -> None:
    """Persist an edited weekly schedule back to settings.yaml (keeps other keys)."""
    path = CONFIG_DIR / "settings.yaml"
    data = _load_yaml("settings.yaml")
    data["schedule"] = {d: schedule.get(d, "none") for d in WEEKDAYS}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    reload_settings()


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
