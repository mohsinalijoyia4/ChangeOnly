from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "ChangeOnly")
    base_url: str = os.getenv("BASE_URL", "http://127.0.0.1:8000")
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./changeonly.db")

    sec_user_agent: str = os.getenv("SEC_USER_AGENT", "").strip()

    resend_api_key: str = os.getenv("RESEND_API_KEY", "").strip()
    resend_from: str = os.getenv("RESEND_FROM", "ChangeOnly <no-reply@example.com>").strip()

    poll_interval_minutes: int = int(os.getenv("POLL_INTERVAL_MINUTES", "45"))

    public_rate_limit_per_min: int = int(os.getenv("PUBLIC_RATE_LIMIT_PER_MIN", "60"))
    auth_rate_limit_per_min: int = int(os.getenv("AUTH_RATE_LIMIT_PER_MIN", "10"))

settings = Settings()
