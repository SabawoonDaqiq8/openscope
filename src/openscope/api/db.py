"""Persistence: SQLAlchemy models.

Calculation results and classified lines are stored as JSON documents next to a few
indexed columns used for filtering. The library's Pydantic models remain the source of
truth for their shape, so the database never drifts from the engine.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Inventory(Base):
    __tablename__ = "inventories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    source: Mapped[str] = mapped_column(String(32))  # upload | demo | classification
    gwp_set: Mapped[str] = mapped_column(String(8))
    reporting_year: Mapped[int | None]
    summary: Mapped[dict[str, Any]]
    errors: Mapped[list[Any]]

    lines: Mapped[list[ResultLine]] = relationship(
        back_populates="inventory", cascade="all, delete-orphan", order_by="ResultLine.id"
    )


class ResultLine(Base):
    __tablename__ = "result_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    inventory_id: Mapped[int] = mapped_column(
        ForeignKey("inventories.id", ondelete="CASCADE"), index=True
    )
    activity_id: Mapped[str] = mapped_column(String(200))
    scope: Mapped[int]
    co2e_kg: Mapped[float]
    activity: Mapped[dict[str, Any]]
    result: Mapped[dict[str, Any]]

    inventory: Mapped[Inventory] = relationship(back_populates="lines")


class ClassificationRun(Base):
    __tablename__ = "classification_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    threshold: Mapped[float]
    used_llm: Mapped[bool]
    llm_usage: Mapped[dict[str, Any]]

    lines: Mapped[list[RunLine]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunLine.id"
    )
    audit: Mapped[list[AuditEntry]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AuditEntry.id"
    )


class RunLine(Base):
    __tablename__ = "run_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("classification_runs.id", ondelete="CASCADE"), index=True
    )
    line_id: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[float]
    data: Mapped[dict[str, Any]]  # ClassifiedLine.model_dump(mode="json")

    run: Mapped[ClassificationRun] = relationship(back_populates="lines")


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("classification_runs.id", ondelete="CASCADE"), index=True
    )
    line_id: Mapped[str] = mapped_column(String(200))
    timestamp: Mapped[str] = mapped_column(String(40))
    reviewer: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(32))
    before: Mapped[dict[str, Any]]
    after: Mapped[dict[str, Any]]
    note: Mapped[str] = mapped_column(String(2000), default="")

    run: Mapped[ClassificationRun] = relationship(back_populates="audit")


class SupplierMemoryRow(Base):
    __tablename__ = "supplier_memory"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    data: Mapped[dict[str, Any]]


class Database:
    def __init__(self, url: str) -> None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, connect_args=connect_args)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_fk_on)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s


def _sqlite_fk_on(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
