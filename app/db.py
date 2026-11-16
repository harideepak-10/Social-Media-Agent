"""SQLite storage for generated content and its approval / publishing state."""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import BASE_DIR

engine = create_engine(f"sqlite:///{BASE_DIR / 'agent.db'}", connect_args={"check_same_thread": False})
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


def init_db() -> None:
    Base.metadata.create_all(engine)
    # tiny migration for databases created by older versions
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(content_items)")}
        for name, ddl in (("source_url", "VARCHAR(500) DEFAULT ''"), ("notes", "TEXT DEFAULT ''"),
                          ("format", "VARCHAR(40) DEFAULT ''"), ("theme", "VARCHAR(40) DEFAULT ''"),
                          ("product", "VARCHAR(100) DEFAULT ''"), ("media_alt_path", "VARCHAR(500) DEFAULT ''"),
                          ("stage", "VARCHAR(200) DEFAULT ''"), ("progress", "INTEGER DEFAULT 0")):
            if name not in cols:
                conn.exec_driver_sql(f"ALTER TABLE content_items ADD COLUMN {name} {ddl}")


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
