from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        max_requests: int,
        window_seconds: int,
        exempt_paths: Iterable[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.default_max_requests = max_requests
        self.default_window_seconds = window_seconds
        self.default_exempt_paths = set(exempt_paths or [])
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.exempt_paths = set(self.default_exempt_paths)
        self.buckets: dict[str, deque[float]] = defaultdict(deque)

        underlying = app
        self._app_state = None
        while underlying is not None and not hasattr(underlying, "state"):
            underlying = getattr(underlying, "app", None)
        if underlying is not None and hasattr(underlying, "state"):
            self._app_state = underlying.state
            self._app_state.rate_limiter = self

    def reset(self) -> None:
        self.buckets.clear()
        self.max_requests = self.default_max_requests
        self.window_seconds = self.default_window_seconds
        self.exempt_paths = set(self.default_exempt_paths)

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.exempt_paths)

    async def dispatch(self, request, call_next):
        if self._app_state is None and hasattr(request.app, "state"):
            self._app_state = request.app.state
            self._app_state.rate_limiter = self

        if self.max_requests <= 0 or self.window_seconds <= 0 or self._is_exempt(request.url.path):
            return await call_next(request)

        key = request.client.host or "anonymous"
        now = time.monotonic()
        bucket = self.buckets[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self.max_requests:
            return JSONResponse(
                {"detail": "Rate limit exceeded. Try again later."},
                status_code=429,
            )

        bucket.append(now)
        return await call_next(request)
