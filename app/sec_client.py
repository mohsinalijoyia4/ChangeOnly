from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from .config import settings

SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

SUPPORTED_FORMS = {"10-K", "10-Q", "8-K"}

@dataclass
class CompanyInfo:
    symbol: str
    cik: str
    name: str

@dataclass
class SecFilingMeta:
    cik: str
    symbol: str
    form_type: str
    filed_at: datetime
    accession_no: str
    primary_doc: str
    filing_txt_url: str
    filing_index_url: str

class SecClient:
    def __init__(self) -> None:
        self._ticker_cache: dict[str, CompanyInfo] = {}
        self._ticker_cache_loaded_at: Optional[datetime] = None
        self._http = httpx.AsyncClient(timeout=30, headers=self._headers())
        self._global_next_ok = 0.0  # throttle

    def _headers(self) -> dict[str, str]:
        ua = settings.sec_user_agent.strip() or "ChangeOnly (missing SEC_USER_AGENT; set env var)"
        return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate", "Accept": "application/json,text/plain,*/*"}

    async def close(self) -> None:
        await self._http.aclose()

    async def _throttle(self) -> None:
        now = time.time()
        if now < self._global_next_ok:
            await asyncio.sleep(self._global_next_ok - now)
        self._global_next_ok = time.time() + 0.2  # ~5 rps max

    async def _get_with_backoff(self, url: str, expect_json: bool = True) -> Any:
        delay = 0.5
        for _attempt in range(6):
            await self._throttle()
            resp = await self._http.get(url)
            if resp.status_code == 200:
                return resp.json() if expect_json else resp.text
            if resp.status_code in (403, 429, 500, 502, 503, 504):
                await asyncio.sleep(delay)
                delay = min(10.0, delay * 2)
                continue
            raise RuntimeError(f"SEC GET failed {resp.status_code}: {url} ({resp.text[:120]})")
        raise RuntimeError(f"SEC GET failed after retries: {url}")

    async def load_ticker_map(self, force: bool = False) -> dict[str, CompanyInfo]:
        if (not force) and self._ticker_cache_loaded_at and (datetime.utcnow() - self._ticker_cache_loaded_at) < timedelta(hours=24):
            return self._ticker_cache
        data = await self._get_with_backoff(SEC_TICKER_MAP_URL, expect_json=True)
        cache: dict[str, CompanyInfo] = {}
        for _, row in data.items():
            sym = str(row.get("ticker", "")).upper().strip()
            cik = str(row.get("cik_str", "")).strip()
            name = str(row.get("title", "")).strip()
            if not sym or not cik:
                continue
            cache[sym] = CompanyInfo(symbol=sym, cik=str(cik).zfill(10), name=name)
        self._ticker_cache = cache
        self._ticker_cache_loaded_at = datetime.utcnow()
        return cache

    async def lookup_company(self, symbol: str) -> Optional[CompanyInfo]:
        symbol = symbol.upper().strip()
        m = await self.load_ticker_map()
        return m.get(symbol)

    async def search_companies(self, query: str, limit: int = 20) -> list[CompanyInfo]:
        q = query.strip().upper()
        if not q:
            return []
        m = await self.load_ticker_map()
        out: list[CompanyInfo] = []
        for sym, info in m.items():
            if q in sym or q in info.name.upper():
                out.append(info)
                if len(out) >= limit:
                    break
        return out

    async def get_recent_filings(self, company: CompanyInfo, limit: int = 10) -> list[SecFilingMeta]:
        url = SEC_SUBMISSIONS_URL.format(cik=company.cik)
        sub = await self._get_with_backoff(url, expect_json=True)

        filings = sub.get("filings", {}).get("recent", {})
        forms = filings.get("form", []) or []
        accession = filings.get("accessionNumber", []) or []
        filed_dates = filings.get("filingDate", []) or []
        primary_docs = filings.get("primaryDocument", []) or []

        items: list[SecFilingMeta] = []
        for i in range(min(len(forms), len(accession), len(filed_dates), len(primary_docs))):
            form = str(forms[i]).strip()
            if form not in SUPPORTED_FORMS:
                continue
            acc = str(accession[i]).strip()
            date_str = str(filed_dates[i]).strip()
            doc = str(primary_docs[i]).strip()

            try:
                dt = datetime.fromisoformat(date_str)
            except Exception:
                dt = datetime.strptime(date_str, "%Y-%m-%d")

            acc_nodash = acc.replace("-", "")
            filing_txt_url = f"https://www.sec.gov/Archives/edgar/data/{int(company.cik)}/{acc_nodash}/{acc}.txt"
            filing_index_url = f"https://www.sec.gov/Archives/edgar/data/{int(company.cik)}/{acc_nodash}/{acc}-index.html"

            items.append(
                SecFilingMeta(
                    cik=company.cik,
                    symbol=company.symbol,
                    form_type=form,
                    filed_at=dt,
                    accession_no=acc,
                    primary_doc=doc,
                    filing_txt_url=filing_txt_url,
                    filing_index_url=filing_index_url,
                )
            )
            if len(items) >= limit:
                break
        return items

    async def download_filing_text(self, filing_txt_url: str) -> str:
        txt = await self._get_with_backoff(filing_txt_url, expect_json=False)
        return self._extract_reasonable_text(txt)

    def _extract_reasonable_text(self, raw: str) -> str:
        raw = raw.replace("\x00", " ")
        raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
        raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
        raw = re.sub(r"(?is)<[^>]+>", " ", raw)
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        raw = re.sub(r"[ \t]{2,}", " ", raw)
        return raw.strip()

sec_client = SecClient()
