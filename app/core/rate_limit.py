"""Shared rate limiter (production-readiness pass, item 13). One `Limiter` instance for the
whole app — registered on `app.state` in `main.py` (global default limit + the
`RateLimitExceeded` -> 429 handler) and imported directly wherever a route needs a *stricter*
limit than the default (currently just `POST /api/auth/login`, for brute-force protection).

In-memory storage (slowapi's default) — correct and effective for a single-process deployment
(what this app runs as), but each worker process would track its own counters if run behind a
multi-process server (gunicorn -w N, multiple containers, ...). See README Known Limitations —
a real multi-instance deployment needs a shared backend (e.g. Redis, which slowapi/`limits`
supports by changing `storage_uri` here) for the limit to hold across processes.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# 120 requests/minute per client IP is a generous default meant to stop scripted abuse, not to
# throttle normal interactive use of this app.
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
