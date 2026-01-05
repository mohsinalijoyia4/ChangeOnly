from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from .config import settings


@dataclass
class EmailResult:
    ok: bool
    detail: str = ""


class Emailer:
    async def send_html(self, to_email: str, subject: str, html: str) -> EmailResult:
        if not settings.resend_api_key:
            print("\n=== EMAIL_STUB ===")
            print("TO:", to_email)
            print("SUBJECT:", subject)
            print("HTML:\n", html)
            print("=== /EMAIL_STUB ===\n")
            return EmailResult(ok=True, detail="stubbed")

        url = "https://api.resend.com/emails"
        headers = {"Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json"}
        payload = {"from": settings.resend_from, "to": [to_email], "subject": subject, "html": html}

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(url, headers=headers, content=json.dumps(payload))
                if 200 <= resp.status_code < 300:
                    return EmailResult(ok=True, detail="sent")
                return EmailResult(ok=False, detail=f"resend_error:{resp.status_code}:{resp.text[:200]}")
        except Exception as e:
            return EmailResult(ok=False, detail=f"exception:{e!r}")


emailer = Emailer()
