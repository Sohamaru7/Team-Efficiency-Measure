"""Tunable constants for the analytics package. Centralized here so the weight table and
thresholds documented in the README stay in sync with the code that implements them.
"""

# Weight (hours) assumed for a task that has no `estimated_hours` recorded, when a task's
# "difficulty" is used to weight aggregate metrics (see metrics.task_weight). Keeping this at
# 1.0 means an un-estimated task still counts, but does not dominate a weighted average the
# way an arbitrarily large default would.
DEFAULT_TASK_WEIGHT = 1.0

# Default expected working hours for one scoring period (used by calculate_workload when the
# caller doesn't supply a period-specific capacity). 40.0 = one standard 5-day work week.
DEFAULT_CAPACITY_HOURS = 40.0

# Weights for the individual efficiency score (calculate_employee_score). Must sum to 1.0 —
# enforced below so a typo here fails fast at import time instead of silently skewing scores.
INDIVIDUAL_SCORE_WEIGHTS: dict[str, float] = {
    "completion": 0.25,
    "on_time": 0.20,
    "quality": 0.15,
    "time_efficiency": 0.15,
    "deadline_adherence": 0.10,
    "project_progress": 0.10,
    "workload": 0.05,
}

_weight_total = sum(INDIVIDUAL_SCORE_WEIGHTS.values())
if abs(_weight_total - 1.0) > 1e-9:
    raise AssertionError(f"INDIVIDUAL_SCORE_WEIGHTS must sum to 1.0, got {_weight_total}")

# Deadline-risk thresholds, in whole days remaining until a task's deadline.
DEADLINE_RISK_HIGH_DAYS = 2
DEADLINE_RISK_MEDIUM_DAYS = 5

# A pragmatic upper bound on rows fetched per query for analytics purposes. Phase 2's
# task_service.list_tasks/user_service.list_users are paginated for CRUD use; analytics needs
# "all of them" for a correct aggregate, so scoring.py and dashboard.py ask for one large page
# instead of adding a new unbounded-fetch method to the CRUD services.
MAX_ANALYTICS_ROWS = 10_000

# Default trailing window (in days, inclusive of today) for the efficiency trend chart when the
# caller doesn't supply an explicit date_from/date_to.
DEFAULT_TREND_WINDOW_DAYS = 14
