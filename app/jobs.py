from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from .config import settings
from .diff_engine import chunk_by_items, diff_sections, stable_hash
from .emailer import emailer
from .models import Alert, Company, DiffSection, Filing, User, Watchlist
from .sec_client import sec_client

MAX_RECENT_FILINGS_PER_REFRESH = 12
TICKER_REFRESH_TTL_MIN = 30

def _engine():
    from .db import engine
    return engine()

def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def _unsubscribe_token_for_user(s: Session, user_id: int) -> str:
    from .auth import make_unsubscribe_token
    user = s.get(User, user_id)
    if not user:
        return ""
    if not user.unsub_token_salt:
        import os
        user.unsub_token_salt = os.urandom(16).hex()
        s.add(user)
        s.commit()
        s.refresh(user)
    return make_unsubscribe_token(user)

async def refresh_ticker(symbol: str) -> None:
    symbol = symbol.upper().strip()
    with Session(_engine()) as s:
        company = s.exec(select(Company).where(Company.symbol == symbol)).first()

    if not company:
        info = await sec_client.lookup_company(symbol)
        if not info:
            return
        with Session(_engine()) as s:
            company = Company(symbol=info.symbol, cik=info.cik, name=info.name, last_refreshed_at=None)
            s.add(company)
            s.commit()
            s.refresh(company)

    if company.last_refreshed_at and (datetime.utcnow() - company.last_refreshed_at) < timedelta(minutes=TICKER_REFRESH_TTL_MIN):
        return

    info = await sec_client.lookup_company(symbol)
    if not info:
        return

    metas = await sec_client.get_recent_filings(info, limit=MAX_RECENT_FILINGS_PER_REFRESH)
    metas_sorted = sorted(metas, key=lambda m: m.filed_at)

    for meta in metas_sorted:
        await ingest_filing(meta)

    with Session(_engine()) as s:
        company_db = s.exec(select(Company).where(Company.symbol == symbol)).first()
        if company_db:
            company_db.last_refreshed_at = datetime.utcnow()
            s.add(company_db)
            s.commit()

async def ingest_filing(meta) -> Optional[int]:
    with Session(_engine()) as s:
        existing = s.exec(select(Filing).where(Filing.accession_no == meta.accession_no)).first()
        if existing:
            return None

    raw_text = await sec_client.download_filing_text(meta.filing_txt_url)
    raw_hash = stable_hash(raw_text)

    with Session(_engine()) as s:
        prev = s.exec(
            select(Filing)
            .where(Filing.symbol == meta.symbol)
            .where(Filing.form_type == meta.form_type)
            .order_by(Filing.filed_at.desc())
        ).first()

        filing = Filing(
            symbol=meta.symbol,
            cik=meta.cik,
            form_type=meta.form_type,
            filed_at=meta.filed_at,
            accession_no=meta.accession_no,
            filing_url=meta.filing_index_url,
            primary_doc=meta.primary_doc,
            raw_text=raw_text,
            raw_text_hash=raw_hash,
            prev_filing_id=prev.id if prev else None,
            unstructured=False,
        )
        s.add(filing)
        s.commit()
        s.refresh(filing)
        
        filing_id = filing.id
        prev_id = prev.id if prev else None

    if not prev_id:
        return filing_id

    await compute_and_store_diffs(filing_id=filing_id, previous_id=prev_id)
    await maybe_send_alerts(filing_id)
    return filing_id

async def compute_and_store_diffs(filing_id: int, previous_id: int) -> None:
    with Session(_engine()) as s:
        filing = s.get(Filing, filing_id)
        prev = s.get(Filing, previous_id)
        if not filing or not prev:
            return

        new_chunk = chunk_by_items(filing.form_type, filing.raw_text)
        old_chunk = chunk_by_items(filing.form_type, prev.raw_text)

        filing.unstructured = bool(new_chunk.unstructured or old_chunk.unstructured)
        s.add(filing)
        s.commit()

        changed = diff_sections(old_chunk.chunks, new_chunk.chunks)
        for section_key, title, html in changed:
            ds = DiffSection(
                filing_id=filing.id,
                previous_filing_id=prev.id,
                section_key=section_key,
                section_title=title,
                diff_html=html,
            )
            s.add(ds)
        s.commit()

async def maybe_send_alerts(filing_id: int) -> None:
    with Session(_engine()) as s:
        filing = s.get(Filing, filing_id)
        if not filing:
            return
        diffs = s.exec(select(DiffSection).where(DiffSection.filing_id == filing_id)).all()
        if not diffs:
            return

        watchers = s.exec(select(Watchlist).where(Watchlist.symbol == filing.symbol)).all()
        if not watchers:
            return

        changed_sections = [d.section_title or d.section_key for d in diffs]
        subject = f"{filing.symbol} filed a new {filing.form_type} — {len(changed_sections)} change(s) detected"
        filing_link = f"{settings.base_url}/filing/{filing.id}"
        ticker_link = f"{settings.base_url}/ticker/{filing.symbol}"

        for w in watchers:
            user = s.get(User, w.user_id)
            if not user or user.unsubscribed:
                continue
            already = s.exec(select(Alert).where(Alert.user_id == user.id).where(Alert.filing_id == filing_id)).first()
            if already:
                continue

            unsubscribe_token = _unsubscribe_token_for_user(s, user.id)
            unsub_link = f"{settings.base_url}/unsubscribe/{unsubscribe_token}"
            sections_html = "".join(f"<li>{_escape(x)}</li>" for x in changed_sections)

            html = f"""
            <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.4">
              <p><strong>{_escape(filing.symbol)}</strong> filed a new <strong>{_escape(filing.form_type)}</strong> on {filing.filed_at.date().isoformat()}.</p>
              <p>Changed sections:</p>
              <ul>{sections_html}</ul>
              <p>
                View filing changes:
                <a href="{filing_link}">{filing_link}</a><br/>
                Ticker page:
                <a href="{ticker_link}">{ticker_link}</a>
              </p>
              <hr/>
              <p style="color:#555;font-size:12px">
                Informational only. Not investment advice.<br/>
                <a href="{unsub_link}">Unsubscribe</a>
              </p>
            </div>
            """.strip()

            result = await emailer.send_html(user.email, subject, html)
            status = "sent" if result.ok else "failed"
            detail = (result.detail or "")[:512]
            s.add(Alert(user_id=user.id, filing_id=filing_id, status=status, detail=detail))
            s.commit()

async def poll_watchlists_once() -> None:
    with Session(_engine()) as s:
        symbols = sorted({w.symbol for w in s.exec(select(Watchlist)).all()})
    for sym in symbols:
        try:
            await refresh_ticker(sym)
        except Exception as e:
            print(f"[poll] error for {sym}: {e!r}")
            continue
