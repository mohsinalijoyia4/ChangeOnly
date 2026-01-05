from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Tuple

from fastapi import Request
from starlette.responses import Response


@dataclass
class Bucket:
    capacity: int
    refill_per_sec: float
    tokens: float
    last: float


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self.buckets: Dict[str, Bucket] = {}

    def _get_bucket(self, key: str, capacity: int, per_min: int) -> Bucket:
        now = time.time()
        refill_per_sec = per_min / 60.0
        b = self.buckets.get(key)
        if not b:
            b = Bucket(capacity=capacity, refill_per_sec=refill_per_sec, tokens=float(capacity), last=now)
            self.buckets[key] = b
        return b

    def allow(self, key: str, per_min: int, capacity: int | None = None) -> Tuple[bool, int]:
        if capacity is None:
            capacity = per_min
        b = self._get_bucket(key, capacity=capacity, per_min=per_min)
        now = time.time()
        elapsed = max(0.0, now - b.last)
        b.last = now
        b.tokens = min(b.capacity, b.tokens + elapsed * b.refill_per_sec)
        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return True, int(b.tokens)
        return False, int(b.tokens)

rate_limiter = InMemoryRateLimiter()

def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def rate_limit_or_429(request: Request, group: str, per_min: int) -> Response | None:
    ip = client_ip(request)
    key = f"{group}:{ip}"
    ok, _ = rate_limiter.allow(key, per_min=per_min)
    if ok:
        return None
    return Response("Too Many Requests", status_code=429, headers={"Retry-After": "60"})
