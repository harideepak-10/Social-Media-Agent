"""Database for generated content and its approval / publishing state.

- On your PC: SQLite (the agent.db file) – nothing to set up.
- In the cloud: set DATABASE_URL (e.g. Supabase Postgres) and everything is stored there instead,
  so it survives restarts on hosts like Render's free plan.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import CONFIG_DIR, DATA_DIR, env

log = logging.getLogger(__name__)


def database_url() -> str:
    url = env("DATABASE_URL")
    if not url:
        return f"sqlite:///{DATA_DIR / 'agent.db'}"
    # Supabase / Heroku style URLs -> SQLAlchemy + psycopg 3 driver
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def is_cloud_db() -> bool:
    return not database_url().startswith("sqlite")


if is_cloud_db():
    # prepare_threshold=None keeps it working through Supabase's connection pooler (PgBouncer)
    engine = create_engine(database_url(), pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5,
                           connect_args={"prepare_threshold": None, "connect_timeout": 15})
else:
    engine = create_engine(database_url(), connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Status flow: generating -> pending_approval -> approved -> published
#                                             \-> rejected        \-> failed / partial
class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(10))              # video | post
    source: Mapped[str] = mapped_column(String(20), default="")  # festival | event | trend | website | url
    source_url: Mapped[str] = mapped_column(String(500), default="")  # set for "any website" items
    notes: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(40), default="")    # post format / video style used
    theme: Mapped[str] = mapped_column(String(40), default="")     # visual theme used
    product: Mapped[str] = mapped_column(String(100), default="")  # product featured
    media_alt_path: Mapped[str] = mapped_column(String(500), default="")  # vertical 9:16 version of a video
    stage: Mapped[str] = mapped_column(String(200), default="")    # live progress text while generating
    progress: Mapped[int] = mapped_column(Integer, default=0)      # 0-100
    topic: Mapped[str] = mapped_column(String(300), default="")
    angle: Mapped[str] = mapped_column(Text, default="")
    captions_json: Mapped[str] = mapped_column(Text, default="{}")   # {platform: caption}
    hashtags: Mapped[str] = mapped_column(Text, default="")
    script_json: Mapped[str] = mapped_column(Text, default="")       # video script / post design
    media_path: Mapped[str] = mapped_column(String(500), default="")
    thumb_path: Mapped[str] = mapped_column(String(500), default="")
    platforms: Mapped[str] = mapped_column(String(100), default="")  # comma separated
    status: Mapped[str] = mapped_column(String(20), default="generating", index=True)
    results_json: Mapped[str] = mapped_column(Text, default="{}")    # {platform: {ok, id, error}}
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # helpers ------------------------------------------------------------
    @property
    def captions(self) -> dict:
        return json.loads(self.captions_json or "{}")

    @captions.setter
    def captions(self, value: dict) -> None:
        self.captions_json = json.dumps(value, ensure_ascii=False)

    @property
    def results(self) -> dict:
        return json.loads(self.results_json or "{}")

    @results.setter
    def results(self, value: dict) -> None:
        self.results_json = json.dumps(value, ensure_ascii=False)

    @property
    def platform_list(self) -> list[str]:
        return [p for p in self.platforms.split(",") if p]


# ── festival / special-day approvals ───────────────────────────────────────
class OccasionRule(Base):
    """Remembered choice for a recurring festival/special day: always | never | ask (+ options)."""
    __tablename__ = "occasion_rules"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)   # slug of the name
    name: Mapped[str] = mapped_column(String(200), default="")
    rule: Mapped[str] = mapped_column(String(10), default="ask")
    timing: Mapped[int | None] = mapped_column(Integer, nullable=True)  # days early (None = global default)
    note: Mapped[str] = mapped_column(Text, default="")


class OccasionDecision(Base):
    """Decision for one occurrence (e.g. Pongal 2027-01-14): approved | skipped."""
    __tablename__ = "occasion_decisions"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)   # "<date>|<slug>"
    day: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(10), default="approved")
    timing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    reminded: Mapped[int] = mapped_column(Integer, default=0)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OccasionSuggestion(Base):
    """Days the AI suggested for your products (e.g. World Health Day for Clinic) – wait for you."""
    __tablename__ = "occasion_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text, default="")
    product: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | accepted | dismissed


class Connection(Base):
    """Social account connections and app credentials (encrypted JSON)."""
    __tablename__ = "connections"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)    # meta | linkedin | meta_app | linkedin_app | *_pending
    data: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StoredFile(Base):
    """Copies of config/*.yaml kept in the cloud database, so dashboard edits survive restarts."""
    __tablename__ = "stored_files"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


_initialized = False


def init_db() -> None:
    global _initialized
    if _initialized:
        return
    Base.metadata.create_all(engine)
    # tiny migration for databases created by older versions
    cols = {c["name"] for c in inspect(engine).get_columns("content_items")}
    with engine.begin() as conn:
        for name, ddl in (("source_url", "VARCHAR(500) DEFAULT ''"), ("notes", "TEXT DEFAULT ''"),
                          ("format", "VARCHAR(40) DEFAULT ''"), ("theme", "VARCHAR(40) DEFAULT ''"),
                          ("product", "VARCHAR(100) DEFAULT ''"), ("media_alt_path", "VARCHAR(500) DEFAULT ''"),
                          ("stage", "VARCHAR(200) DEFAULT ''"), ("progress", "INTEGER DEFAULT 0")):
            if name not in cols:
                conn.execute(text(f"ALTER TABLE content_items ADD COLUMN {name} {ddl}"))
    if is_cloud_db():
        restore_config_files()
    _initialized = True


# ── config files in the cloud DB ───────────────────────────────────────────
def save_config_file(name: str, content: str) -> None:
    """Called after every dashboard edit of config/<name> (cloud mode only)."""
    if not is_cloud_db():
        return
    with get_session() as s:
        row = s.get(StoredFile, name)
        if row:
            row.content = content
        else:
            s.add(StoredFile(name=name, content=content))
        s.commit()


def restore_config_files() -> None:
    """On start-up in the cloud: bring back the settings/events edited in the dashboard."""
    from .config import reload_settings
    with get_session() as s:
        rows = s.scalars(select(StoredFile)).all()
    for row in rows:
        if row.name.endswith(".yaml") and "/" not in row.name and row.content.strip():
            (CONFIG_DIR / row.name).write_text(row.content, encoding="utf-8")
            log.info("restored config/%s from the database", row.name)
    if rows:
        reload_settings()


def get_session() -> Session:
    return SessionLocal()


def last_source(kind: str) -> str:
    with get_session() as s:
        row = s.scalars(select(ContentItem).where(ContentItem.kind == kind, ContentItem.source_url == "")
                        .order_by(ContentItem.id.desc()).limit(1)).first()
        return row.source if row else ""


def recent_topics(limit: int = 30) -> list[str]:
    with get_session() as s:
        rows = s.scalars(select(ContentItem).where(ContentItem.source_url == "")
                         .order_by(ContentItem.id.desc()).limit(limit)).all()
        return [r.topic for r in rows if r.topic]
