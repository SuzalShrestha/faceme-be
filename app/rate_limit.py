from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import (
    RATE_LIMIT_AUTH_MAX_REQUESTS,
    RATE_LIMIT_AUTH_WINDOW_SECONDS,
    RATE_LIMIT_WRITE_MAX_REQUESTS,
    RATE_LIMIT_WRITE_WINDOW_SECONDS,
    SESSION_COOKIE_NAME,
)


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    max_requests: int
    window_seconds: int
    methods: tuple[str, ...]
    path_prefixes: tuple[str, ...]

    def matches(self, request: Request) -> bool:
        return request.method in self.methods and any(
            request.url.path.startswith(prefix) for prefix in self.path_prefixes
        )


class InMemoryRateLimiter:
    def __init__(self, rules: list[RateLimitRule]) -> None:
        self.rules = [rule for rule in rules if rule.max_requests > 0 and rule.window_seconds > 0]
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, request: Request) -> tuple[RateLimitRule, int] | None:
        rule = next((item for item in self.rules if item.matches(request)), None)
        if rule is None:
            return None

        bucket_key = (rule.name, self._identify_client(request))
        now = monotonic()
        window_start = now - rule.window_seconds

        with self._lock:
            timestamps = self._requests[bucket_key]
            while timestamps and timestamps[0] <= window_start:
                timestamps.popleft()

            if len(timestamps) >= rule.max_requests:
                retry_after = max(1, int(timestamps[0] + rule.window_seconds - now + 0.999))
                return rule, retry_after

            timestamps.append(now)
        return None

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()

    def _identify_client(self, request: Request) -> str:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token:
            return f"session:{session_token}"

        forwarded_for = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded_for:
            return f"ip:{forwarded_for}"

        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.limiter = rate_limiter

    async def dispatch(self, request: Request, call_next):
        limit = self.limiter.check(request)
        if limit is not None:
            rule, retry_after = limit
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(rule.max_requests),
                    "X-RateLimit-Window": str(rule.window_seconds),
                },
            )
        return await call_next(request)


rate_limiter = InMemoryRateLimiter(
    [
        RateLimitRule(
            name="auth",
            max_requests=RATE_LIMIT_AUTH_MAX_REQUESTS,
            window_seconds=RATE_LIMIT_AUTH_WINDOW_SECONDS,
            methods=("POST",),
            path_prefixes=("/api/auth/",),
        ),
        RateLimitRule(
            name="write",
            max_requests=RATE_LIMIT_WRITE_MAX_REQUESTS,
            window_seconds=RATE_LIMIT_WRITE_WINDOW_SECONDS,
            methods=("POST", "PUT", "PATCH"),
            path_prefixes=(
                "/api/uploads/",
                "/api/import/",
                "/api/pipeline",
                "/api/clusters/",
            ),
        ),
    ]
)
