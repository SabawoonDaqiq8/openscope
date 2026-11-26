"""Protection for a publicly reachable deployment.

* :class:`SecurityHeadersMiddleware` (always on): standard hardening headers.
* :class:`WriteRateLimitMiddleware` (public demo only): limits state-changing requests
  (POST/PUT/PATCH/DELETE) per client in a sliding window, so a single visitor cannot flood
  the demo with uploads or reviews.

The rate limiter is in-memory and per process, which is enough for a single-instance demo.
A multi-instance deployment would need a shared store (e.g. Redis) or a gateway limit.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# The Angular build inlines no scripts; ECharts draws on canvas. Inline styles are used by
# Angular style bindings, so 'unsafe-inline' is allowed for styles only. /docs (Swagger UI)
# loads assets from a CDN and gets a relaxed policy.
APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        csp = DOCS_CSP if request.url.path in ("/docs", "/docs/oauth2-redirect") else APP_CSP
        h.setdefault("Content-Security-Policy", csp)
        return response


class WriteRateLimitMiddleware(BaseHTTPMiddleware):
    """Allow at most ``limit`` write requests per client per ``window`` seconds."""

    def __init__(
        self,
        app: ASGIApp,
        limit: int = 30,
        window: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(app)
        self.limit = limit
        self.window = window
        self.clock = clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def _client(self, request: Request) -> str:
        # uvicorn --proxy-headers already resolves X-Forwarded-For into request.client
        return request.client.host if request.client else "unknown"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in WRITE_METHODS or not request.url.path.startswith("/api/"):
            return await call_next(request)
        now = self.clock()
        q = self.hits[self._client(request)]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            retry = max(1, math.ceil(self.window - (now - q[0])))
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"This public demo limits changes to {self.limit} per "
                    f"{int(self.window // 60)} minutes per visitor. Try again in {retry} seconds."
                },
                headers={"Retry-After": str(retry)},
            )
        q.append(now)
        if len(self.hits) > 10_000:  # bound memory: drop idle clients
            for key in [k for k, v in self.hits.items() if not v or now - v[-1] >= self.window]:
                del self.hits[key]
        return await call_next(request)
