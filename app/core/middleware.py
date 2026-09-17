"""Security response headers (production-readiness pass, item 5 "API security"). Applied to
every response via a plain ASGI-style middleware — cheap, framework-native, no new dependency.
"""

from fastapi import FastAPI, Request


def register_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-XSS-Protection"] = "0"  # deprecated/unreliable header; explicitly disabled rather than left ambiguous
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path.startswith("/api/"):
            # JSON API responses can carry per-user data (task lists, scores, ...) — never let
            # a shared/browser cache store them.
            response.headers["Cache-Control"] = "no-store"
        return response
