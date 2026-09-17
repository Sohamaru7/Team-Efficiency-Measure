"""Tunable constants for the emailing package, centralized for the same reason as
`app.services.analytics.constants` and `app.services.import_export.constants`.
"""

# Subject/body keywords that flag an email as approval-related. Subject is always checked
# first; body is only consulted if the subject alone doesn't match — "use content only when
# necessary" (Phase 9 brief).
APPROVAL_KEYWORDS: tuple[str, ...] = ("approve", "approval", "sign off", "sign-off", "authorize", "authorization")

# Keywords that flag an external email as mentioning a blocker.
BLOCKER_KEYWORDS: tuple[str, ...] = (
    "blocked", "blocker", "cannot proceed", "can't proceed", "on hold", "waiting on", "delay", "delayed",
)

# Task.delay_reason keywords that hint the delay is externally caused (used only to set
# confidence on an already-evidenced classification, never to classify on their own).
EXTERNAL_HINT_KEYWORDS: tuple[str, ...] = (
    "client", "customer", "vendor", "external", "third party", "third-party", "partner",
)

# Body text is capped at ingestion to bound storage/response size for a single email.
MAX_BODY_CHARS = 20_000
