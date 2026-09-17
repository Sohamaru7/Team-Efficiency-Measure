"""Tunable constants for the import/export package, centralized for the same reason as
`app.services.analytics.constants` — so the numbers documented in the README stay in sync with
the code that enforces them.
"""

# A pragmatic upper bound on data rows accepted in a single uploaded file (excluding the header
# row). Prevents a mistakenly-huge upload from tying up a request; not a real chunked-upload
# scheme. See Known Limitations.
MAX_IMPORT_ROWS = 5000

# ImportHistory.errors is a single Text column, not a separate table — cap its JSON payload so
# an import with thousands of rejected rows can't produce an unbounded database write. Errors
# beyond this cap are truncated, not silently dropped (the count is still accurate; only the
# detail listing is capped).
MAX_ERROR_LOG_CHARS = 20_000
