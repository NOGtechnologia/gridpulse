"""Dependencies: repository, settings, clock, API keys and rate limiting."""

from __future__ import annotations

import hmac
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from gridpulse.settings import Settings
from gridpulse.storage.repository import Repository, hash_api_key

API_KEY_HEADER = "X-API-Key"


@dataclass
class AppState:
    settings: Settings
    repo: Repository
    clock: Callable[[], datetime]
    limiter: RateLimiter


def state(request: Request) -> AppState:
    app_state: AppState = request.app.state.gridpulse
    return app_state


StateDep = Annotated[AppState, Depends(state)]


def get_repo(s: StateDep) -> Repository:
    return s.repo


def now(s: StateDep) -> datetime:
    return s.clock()


RepoDep = Annotated[Repository, Depends(get_repo)]
NowDep = Annotated[datetime, Depends(now)]


@dataclass
class RateLimiter:
    """Fixed-window limiter per client key (in-process; one API replica per limit)."""

    per_minute: int
    window_seconds: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _hits: dict[str, tuple[float, int]] = field(default_factory=dict)

    def hit(self, key: str, weight: float = 1.0) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = self.clock()
        window_start, count = self._hits.get(key, (now, 0))
        if now - window_start >= self.window_seconds:
            window_start, count = now, 0
        limit = int(self.per_minute * weight)
        if count >= limit:
            return False, max(1, math.ceil(self.window_seconds - (now - window_start)))
        self._hits[key] = (window_start, count + 1)
        if len(self._hits) > 50_000:  # bound memory under abuse
            cutoff = now - self.window_seconds
            self._hits = {k: v for k, v in self._hits.items() if v[0] >= cutoff}
        return True, 0


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def guard(
    request: Request,
    s: StateDep,
    x_api_key: Annotated[str | None, Header(alias=API_KEY_HEADER)] = None,
) -> None:
    """API key check (optional or required) and rate limiting for every /api/v1 route."""
    key_ok = False
    if x_api_key:
        if not await s.repo.is_valid_api_key(x_api_key):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
        key_ok = True
    elif s.settings.require_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"{API_KEY_HEADER} header required")
    bucket = (
        f"key:{hash_api_key(x_api_key)}"
        if key_ok and x_api_key
        else (f"ip:{client_ip(request, s.settings.trust_proxy_headers)}")
    )
    allowed, retry_after = s.limiter.hit(bucket, weight=10.0 if key_ok else 1.0)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


def require_admin(s: StateDep, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    token = s.settings.admin_token
    if token is None or not token.get_secret_value():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "admin endpoints disabled (GRIDPULSE_ADMIN_TOKEN unset)"
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token, token.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin token")
