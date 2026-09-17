"""Global error handling (production-readiness pass, item 11 / "sensitive data protection").

Without this, an unhandled exception anywhere in the app (a bug, a DB hiccup treated as
unexpected, ...) risks the client seeing whatever `str(exc)` happens to say — which can include
fragments of a SQL query, a file path, or other internal detail. Every unhandled exception is
now converted to one generic, constant JSON body; the real exception (with traceback) is still
logged server-side via `logger.exception`, so nothing about debuggability is lost, only what
reaches the client over the network.

`HTTPException`s raised deliberately throughout the app (404s, 403s, 409s, ...) are untouched —
they already carry an intentional, safe `detail` message and continue to pass through FastAPI's
own handling exactly as before this phase.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_GENERIC_MESSAGE = "An internal error occurred. Please try again or contact support."


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, StarletteHTTPException):
            # Let FastAPI's own HTTPException handling proceed unchanged (it never reaches
            # here in practice since Starlette handles it first, but this keeps intent
            # explicit and is a harmless no-op safety net).
            raise exc
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": _GENERIC_MESSAGE})
