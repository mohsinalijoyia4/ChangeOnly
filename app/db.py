from __future__ import annotations

from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.engine import Engine

from .config import settings

_engine: Engine | None = None

def engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        _engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)
    return _engine

def session() -> Session:
    return Session(engine())

def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine())
