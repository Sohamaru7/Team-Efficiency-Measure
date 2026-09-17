"""File upload size guard (production-readiness pass, item 14 "file upload security"). One
shared constant/helper so every upload endpoint (CSV/XLSX import, .eml ingestion) enforces the
same cap the same way, checked immediately after reading the body and BEFORE any parsing is
attempted — cheap insurance against a client sending an enormous or pathological file that would
otherwise be fully parsed (CSV/XLSX parsing, MIME parsing) before anything else notices it's too
big to be a legitimate task/email import for this app.
"""

from fastapi import HTTPException, status

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB — generous for the CSV/XLSX/.eml files this app expects


def enforce_upload_size(content: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES) -> None:
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is too large (max {max_bytes // (1024 * 1024)} MB).",
        )
