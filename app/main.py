from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .config import settings
from .migrations import apply_migrations
from .models import User, Company, Filing, DiffSection, Watchlist, Alert
from .db import engine
from .security import SecurityHeadersMiddleware
from .rate_limit import rate_limit_or_429
from .sec_client import sec_client
from .auth import (
    issue_magic_link,
    consume_magic_link,
    get_current_user,
    set_session,
    verify_unsubscribe_token,
    clear_session,
)
from .emailer import emailer
from .jobs import refresh_ticker, poll_watchlists_once

app = FastAPI(title=settings.app_name)
app.add_middleware(SecurityHeadersMiddleware)

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

scheduler: Optional[AsyncIOScheduler] = None

def require_sec_user_agent() -> None:
    if not settings.sec_user_agent or "contact" not in settings.sec_user_agent.lower():
        raise RuntimeError(
            "SEC_USER_AGENT must be set and include contact info, e.g. "
            "'ChangeOnly MVP (contact: you@example.com)'"
        )

@app.on_event("startup")
async def on_startup():
    require_sec_user_agent()
    apply_migrations()
    global scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: poll_watchlists_once(), "interval", minutes=settings.poll_interval_minutes, max_instances=1)
    scheduler.start()

@app.on_event("shutdown")
async def on_shutdown():
    if scheduler:
        scheduler.shutdown(wait=False)
    await sec_client.close()

def _user(s: Session, request: Request) -> Optional[User]:
    return get_current_user(s, request)

def _is_valid_symbol(sym: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9\.\-]{1,16}", sym))

# ---------------- Public ----------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, q: str = ""):
    rl = rate_limit_or_429(request, "public", settings.public_rate_limit_per_min)
    if rl:
        return rl
    results = []
    if q.strip():
        results = await sec_client.search_companies(q.strip(), limit=20)
    return templates.TemplateResponse("home.html", {"request": request, "q": q, "results": results, "now": datetime.utcnow()})

@app.get("/ticker/{symbol}", response_class=HTMLResponse)
async def ticker_page(request: Request, symbol: str):
    rl = rate_limit_or_429(request, "public", settings.public_rate_limit_per_min)
    if rl:
        return rl

    symbol = symbol.upper().strip()
    if not _is_valid_symbol(symbol):
        return templates.TemplateResponse("error.html", {"request": request, "message": "Ticker not found."}, status_code=404)

    try:
        await refresh_ticker(symbol)
    except Exception as e:
        print(f"[ticker] refresh error {symbol}: {e!r}")

    with Session(engine()) as s:
        company = s.exec(select(Company).where(Company.symbol == symbol)).first()
        if not company:
            return templates.TemplateResponse("error.html", {"request": request, "message": "Ticker not found."}, status_code=404)

        filings = s.exec(select(Filing).where(Filing.symbol == symbol).order_by(Filing.filed_at.desc()).limit(5)).all()
        filing_ids = [f.id for f in filings if f.id]
        diffs = []
        if filing_ids:
            diffs = s.exec(select(DiffSection).where(DiffSection.filing_id.in_(filing_ids))).all()

        diffs_by_filing: dict[int, list[DiffSection]] = {}
        for d in diffs:
            diffs_by_filing.setdefault(d.filing_id, []).append(d)
        for fid in diffs_by_filing:
            diffs_by_filing[fid].sort(key=lambda x: x.section_key)

        return templates.TemplateResponse(
            "ticker.html",
            {
                "request": request,
                "company": company,
                "filings": filings,
                "diffs_by_filing": diffs_by_filing,
                "canonical_symbol": symbol,
                "now": datetime.utcnow(),
            },
        )

@app.get("/filing/{id}", response_class=HTMLResponse)
async def filing_view(request: Request, id: int):
    rl = rate_limit_or_429(request, "public", settings.public_rate_limit_per_min)
    if rl:
        return rl

    with Session(engine()) as s:
        filing = s.get(Filing, id)
        if not filing:
            return templates.TemplateResponse("error.html", {"request": request, "message": "Filing not found."}, status_code=404)

        company = s.exec(select(Company).where(Company.symbol == filing.symbol)).first()
        diffs = s.exec(select(DiffSection).where(DiffSection.filing_id == id).order_by(DiffSection.section_key)).all()

        return templates.TemplateResponse(
            "filing.html",
            {"request": request, "filing": filing, "company": company, "diffs": diffs, "now": datetime.utcnow()},
        )

# HTMX: lazy-load diff HTML (keeps initial page light + fast)
@app.get("/diff/{diff_id}", response_class=HTMLResponse)
async def diff_partial(request: Request, diff_id: int):
    rl = rate_limit_or_429(request, "public", settings.public_rate_limit_per_min)
    if rl:
        return rl
    with Session(engine()) as s:
        d = s.get(DiffSection, diff_id)
        if not d:
            return HTMLResponse("<div class='muted small'>Missing diff.</div>", status_code=404)
        # Returned fragment includes the diffbox wrapper
        return HTMLResponse(f"<div class='diffbox'>{d.diff_html}</div>")

@app.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe(request: Request, token: str):
    with Session(engine()) as s:
        user = verify_unsubscribe_token(s, token)
        if not user:
            return templates.TemplateResponse("error.html", {"request": request, "message": "Invalid unsubscribe link."}, status_code=400)
        user.unsubscribed = True
        s.add(user)
        s.commit()
    return templates.TemplateResponse("error.html", {"request": request, "message": "You are unsubscribed. You will no longer receive alerts."}, status_code=200)

@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse("legal_terms.html", {"request": request, "now": datetime.utcnow()})

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("legal_privacy.html", {"request": request, "now": datetime.utcnow()})

# ---------------- Auth ----------------

@app.get("/auth/request", response_class=HTMLResponse)
async def auth_request_form(request: Request):
    rl = rate_limit_or_429(request, "auth", settings.auth_rate_limit_per_min)
    if rl:
        return rl
    return templates.TemplateResponse("auth_request.html", {"request": request, "sent": False})

@app.post("/auth/request", response_class=HTMLResponse)
async def auth_request_send(request: Request, email: str = Form(...)):
    rl = rate_limit_or_429(request, "auth", settings.auth_rate_limit_per_min)
    if rl:
        return rl

    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return templates.TemplateResponse("auth_request.html", {"request": request, "sent": False, "error": "Invalid email."}, status_code=400)

    with Session(engine()) as s:
        token = issue_magic_link(s, email, minutes=15)

    link = f"{settings.base_url}/auth/verify?token={token}"
    html = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif">
      <p>Your ChangeOnly login link (valid for 15 minutes):</p>
      <p><a href="{link}">{link}</a></p>
      <hr/>
      <p style="color:#555;font-size:12px">Informational only. Not investment advice.</p>
    </div>
    """.strip()

    await emailer.send_html(email, "Your ChangeOnly login link", html)
    return templates.TemplateResponse("auth_request.html", {"request": request, "sent": True})

@app.get("/auth/verify", response_class=HTMLResponse)
async def auth_verify(request: Request, token: str = ""):
    rl = rate_limit_or_429(request, "auth", settings.auth_rate_limit_per_min)
    if rl:
        return rl

    if not token:
        return templates.TemplateResponse("auth_verify.html", {"request": request, "ok": False, "message": "Missing token."}, status_code=400)

    with Session(engine()) as s:
        user = consume_magic_link(s, token)
        if not user:
            return templates.TemplateResponse("auth_verify.html", {"request": request, "ok": False, "message": "Link expired or invalid."}, status_code=400)

        resp = RedirectResponse(url="/dashboard", status_code=302)
        set_session(resp, user.id)
        return resp

@app.post("/auth/logout")
async def logout(request: Request):
    resp = RedirectResponse(url="/", status_code=302)
    clear_session(resp)
    return resp

# ---------------- Dashboard ----------------

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    with Session(engine()) as s:
        user = _user(s, request)
        if not user:
            return RedirectResponse(url="/auth/request", status_code=302)

        watch = s.exec(select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.created_at.desc())).all()

        alerts = s.exec(select(Alert).where(Alert.user_id == user.id).order_by(Alert.sent_at.desc()).limit(20)).all()
        filings_by_id = {}
        if alerts:
            ids = [a.filing_id for a in alerts]
            fs = s.exec(select(Filing).where(Filing.id.in_(ids))).all()
            filings_by_id = {f.id: f for f in fs}

        return templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "user": user, "watch": watch, "alerts": alerts, "filings_by_id": filings_by_id, "now": datetime.utcnow(), "max_watch": 30},
        )

@app.post("/dashboard/watch/add")
async def watch_add(request: Request, symbol: str = Form(...)):
    with Session(engine()) as s:
        user = _user(s, request)
        if not user:
            return RedirectResponse(url="/auth/request", status_code=302)

        symbol = symbol.upper().strip()
        if not _is_valid_symbol(symbol):
            return RedirectResponse(url="/dashboard?err=bad_symbol", status_code=302)

        count = len(s.exec(select(Watchlist).where(Watchlist.user_id == user.id)).all())
        if count >= 30:
            return RedirectResponse(url="/dashboard?err=watch_limit", status_code=302)

        info = await sec_client.lookup_company(symbol)
        if not info:
            return RedirectResponse(url="/dashboard?err=bad_symbol", status_code=302)

        comp = s.exec(select(Company).where(Company.symbol == symbol)).first()
        if not comp:
            s.add(Company(symbol=info.symbol, cik=info.cik, name=info.name))
            s.commit()

        existing = s.exec(select(Watchlist).where(Watchlist.user_id == user.id).where(Watchlist.symbol == symbol)).first()
        if not existing:
            s.add(Watchlist(user_id=user.id, symbol=symbol))
            s.commit()

    try:
        await refresh_ticker(symbol)
    except Exception as e:
        print(f"[watch_add] refresh error {symbol}: {e!r}")

    return RedirectResponse(url="/dashboard", status_code=302)

@app.post("/dashboard/watch/remove")
async def watch_remove(request: Request, symbol: str = Form(...)):
    with Session(engine()) as s:
        user = _user(s, request)
        if not user:
            return RedirectResponse(url="/auth/request", status_code=302)

        symbol = symbol.upper().strip()
        w = s.exec(select(Watchlist).where(Watchlist.user_id == user.id).where(Watchlist.symbol == symbol)).first()
        if w:
            s.delete(w)
            s.commit()
    return RedirectResponse(url="/dashboard", status_code=302)

@app.post("/dashboard/email/toggle")
async def email_toggle(request: Request):
    with Session(engine()) as s:
        user = _user(s, request)
        if not user:
            return RedirectResponse(url="/auth/request", status_code=302)
        user.unsubscribed = not bool(user.unsubscribed)
        s.add(user)
        s.commit()
    return RedirectResponse(url="/dashboard", status_code=302)
