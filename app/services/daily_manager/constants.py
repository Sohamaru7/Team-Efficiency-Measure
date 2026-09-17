"""Tunable constants for the Autonomous Daily Manager, centralized for the same reason as
`app.services.analytics.constants` / `app.services.import_export.constants` /
`app.services.emailing.constants`.
"""

# A finding's severity ("low"/"medium"/"high") is only ever reported as a "significant change"
# when it's new, or its rank here increases/decreases relative to the last *reported* severity
# — an issue sitting at the same severity every day is deliberately silent (see
# app.services.daily_manager.change_tracking).
SEVERITY_ORDER: dict[str, int] = {"low": 1, "medium": 2, "high": 3}

# Per-issue-type severity thresholds. Each is a short, named, documented rule — same philosophy
# as Phase 7's detection thresholds (app.services.ai.detection) — so "why did this get flagged
# high vs. medium" is always answerable by reading one constant, never a model's judgment call.
OVERLOAD_HIGH_PCT = 150.0
OVERLOAD_MEDIUM_PCT = 120.0

UNDERUTILIZED_HIGH_MAX_PCT = 10.0
UNDERUTILIZED_MEDIUM_MAX_PCT = 20.0

IMBALANCE_HIGH_SPREAD = 80.0
IMBALANCE_MEDIUM_SPREAD = 65.0

DELAY_HIGH_DAYS = 14
DELAY_MEDIUM_DAYS = 7

PERFORMANCE_DROP_HIGH_PCT = 30.0
PERFORMANCE_DROP_MEDIUM_PCT = 20.0

RECURRING_HIGH_COUNT = 5
RECURRING_MEDIUM_COUNT = 3

QUALITY_HIGH_MAX_SCORE = 40.0
QUALITY_MEDIUM_MAX_SCORE = 50.0

PROJECT_RISK_HIGH_DAYS = 3
PROJECT_RISK_MEDIUM_DAYS = 7

# The only two action tools the daily manager is ever allowed to call itself (see
# action_policy.py) — both already exist in app.services.ai.actions from Phase 7, and neither
# can penalize, discipline, evaluate, reassign without approval, or delete anything:
# - "send_notification" auto-executes (a logged message, no task/project/user row changes).
# - "assign_task" is APPROVAL-REQUIRED in actions.py — it only ever queues a PENDING
#   AgentAction; a human must still click Approve before any reassignment actually happens.
# This constant exists so the restriction is enforced in one visible place and is directly
# assertable by a test, not just a comment.
ALLOWED_AUTO_ACTION_TOOLS: frozenset[str] = frozenset({"send_notification", "assign_task"})

# Explicitly never touched by the daily manager, regardless of what a future contributor might
# be tempted to wire up — kept here as a readable, testable statement of intent, not because
# any code path currently reaches these categories. See README "Human approval boundary".
RESTRICTED_ACTION_CATEGORIES: frozenset[str] = frozenset(
    {"performance_penalty", "disciplinary_decision", "employee_evaluation_change", "data_deletion"}
)
