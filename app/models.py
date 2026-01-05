from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, UniqueConstraint, Index


class MigrationState(SQLModel, table=True):
    __tablename__ = "migration_state"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    applied_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)

    email: str = Field(index=True, unique=True, max_length=320)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = None

    unsubscribed: bool = Field(default=False)
    unsub_token_salt: str = Field(default="", max_length=64)


class MagicLink(SQLModel, table=True):
    __tablename__ = "magic_links"
    id: Optional[int] = Field(default=None, primary_key=True)

    email: str = Field(index=True, max_length=320)
    token_hash: str = Field(index=True, unique=True, max_length=128)
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Company(SQLModel, table=True):
    __tablename__ = "companies"
    id: Optional[int] = Field(default=None, primary_key=True)

    symbol: str = Field(index=True, unique=True, max_length=16)
    cik: str = Field(index=True, max_length=16)
    name: str = Field(index=True, max_length=256)

    last_refreshed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Filing(SQLModel, table=True):
    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("accession_no", name="uq_filings_accession"),
        Index("ix_filings_symbol_form_date", "symbol", "form_type", "filed_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    symbol: str = Field(index=True, max_length=16)
    cik: str = Field(index=True, max_length=16)

    form_type: str = Field(index=True, max_length=16)
    filed_at: datetime = Field(index=True)

    accession_no: str = Field(max_length=32)
    filing_url: str = Field(max_length=512)
    primary_doc: str = Field(default="", max_length=256)

    raw_text: str = Field(default="", sa_column_kwargs={"nullable": False})
    raw_text_hash: str = Field(index=True, max_length=64)

    prev_filing_id: Optional[int] = Field(default=None, index=True)
    unstructured: bool = Field(default=False)

    created_at: datetime = Field(default_factory=datetime.utcnow)


class DiffSection(SQLModel, table=True):
    __tablename__ = "diff_sections"
    __table_args__ = (
        UniqueConstraint("filing_id", "section_key", name="uq_diffs_filing_section"),
        Index("ix_diffs_filing", "filing_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    filing_id: int = Field(index=True)
    previous_filing_id: int = Field(index=True)

    section_key: str = Field(index=True, max_length=64)
    section_title: str = Field(default="", max_length=256)

    diff_html: str = Field(default="", sa_column_kwargs={"nullable": False})
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Watchlist(SQLModel, table=True):
    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
        Index("ix_watchlist_symbol", "symbol"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    symbol: str = Field(index=True, max_length=16)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("user_id", "filing_id", name="uq_alerts_user_filing"),
        Index("ix_alerts_user_sent", "user_id", "sent_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    filing_id: int = Field(index=True)

    status: str = Field(default="sent", max_length=32)
    detail: str = Field(default="", max_length=512)
    sent_at: datetime = Field(default_factory=datetime.utcnow)
