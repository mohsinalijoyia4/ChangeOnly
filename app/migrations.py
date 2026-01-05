from __future__ import annotations

from sqlmodel import Session, text

from .db import engine
from .models import MigrationState

MIGRATIONS: list[tuple[str, str]] = [
    (
        "001_init",
        '''
        CREATE TABLE IF NOT EXISTS migration_state (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_login_at TEXT,
            unsubscribed INTEGER NOT NULL DEFAULT 0,
            unsub_token_salt TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS magic_links (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_magic_links_email ON magic_links(email);
        CREATE INDEX IF NOT EXISTS ix_magic_links_token_hash ON magic_links(token_hash);

        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            cik TEXT NOT NULL,
            name TEXT NOT NULL,
            last_refreshed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_companies_symbol ON companies(symbol);
        CREATE INDEX IF NOT EXISTS ix_companies_cik ON companies(cik);
        CREATE INDEX IF NOT EXISTS ix_companies_name ON companies(name);

        CREATE TABLE IF NOT EXISTS filings (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            cik TEXT NOT NULL,
            form_type TEXT NOT NULL,
            filed_at TEXT NOT NULL,
            accession_no TEXT NOT NULL UNIQUE,
            filing_url TEXT NOT NULL,
            primary_doc TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL,
            raw_text_hash TEXT NOT NULL,
            prev_filing_id INTEGER,
            unstructured INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_filings_symbol_form_date ON filings(symbol, form_type, filed_at);
        CREATE INDEX IF NOT EXISTS ix_filings_symbol ON filings(symbol);
        CREATE INDEX IF NOT EXISTS ix_filings_cik ON filings(cik);
        CREATE INDEX IF NOT EXISTS ix_filings_form_type ON filings(form_type);
        CREATE INDEX IF NOT EXISTS ix_filings_filed_at ON filings(filed_at);

        CREATE TABLE IF NOT EXISTS diff_sections (
            id INTEGER PRIMARY KEY,
            filing_id INTEGER NOT NULL,
            previous_filing_id INTEGER NOT NULL,
            section_key TEXT NOT NULL,
            section_title TEXT NOT NULL DEFAULT '',
            diff_html TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(filing_id, section_key)
        );
        CREATE INDEX IF NOT EXISTS ix_diffs_filing ON diff_sections(filing_id);
        CREATE INDEX IF NOT EXISTS ix_diffs_section_key ON diff_sections(section_key);

        CREATE TABLE IF NOT EXISTS watchlists (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, symbol)
        );
        CREATE INDEX IF NOT EXISTS ix_watchlists_user_id ON watchlists(user_id);
        CREATE INDEX IF NOT EXISTS ix_watchlists_symbol ON watchlists(symbol);

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            filing_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'sent',
            detail TEXT NOT NULL DEFAULT '',
            sent_at TEXT NOT NULL,
            UNIQUE(user_id, filing_id)
        );
        CREATE INDEX IF NOT EXISTS ix_alerts_user_sent ON alerts(user_id, sent_at);
        '''
    ),
]

def apply_migrations() -> None:
    with Session(engine()) as s:
        s.exec(
            text(
                '''
                CREATE TABLE IF NOT EXISTS migration_state (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    applied_at TEXT NOT NULL
                );
                '''
            )
        )
        s.commit()

        applied = {row[0] for row in s.exec(text("SELECT name FROM migration_state")).all()}
        for name, sql in MIGRATIONS:
            if name in applied:
                continue
            # SQLite doesn't support executing multiple statements via s.exec(text(sql))
            # So we split by ; and execute them one by one.
            for statement in sql.split(";"):
                clean_stmt = statement.strip()
                if clean_stmt:
                    s.exec(text(clean_stmt))
            s.add(MigrationState(name=name))
            s.commit()
