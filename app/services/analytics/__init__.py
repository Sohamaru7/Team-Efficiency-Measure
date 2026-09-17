"""Deterministic performance analytics (Phase 4).

Every computation in this package is plain Python arithmetic over data already stored by
Phase 1-3 (tasks, projects, users). Nothing here calls an LLM or any external service, and
nothing here is non-deterministic: given the same rows and the same `as_of` date, every
function returns exactly the same result every time.

Public, reusable entry points (the six functions requested for Phase 4):

- `calculate_employee_score(db, user_id, ...)` — DB-aware; fetches a user's tasks and their
  projects, then combines the metrics below into one weighted 0-100 score.
- `calculate_team_score(db, ...)` — DB-aware; averages `calculate_employee_score` across a
  set of users (explicit ids, a department, or all active users).
- `calculate_workload(tasks, ...)` — pure; utilization of a person's current open workload.
- `calculate_project_progress(tasks, project_id)` — pure; difficulty-weighted completion
  percentage for one project's tasks.
- `detect_deadline_risk(tasks, ...)` — pure; forward-looking risk classification per task.
- `detect_delays(tasks, ...)` — pure; which tasks are (or were) actually late.

"Pure" functions take an already-fetched list of `Task` ORM instances (or any object with the
same attributes) and never touch the database themselves — that's what makes them independently
unit-testable and reusable outside of a FastAPI request. See `metrics.py` for the full formula
documentation of every metric, and the "Analytics & Efficiency Scoring" section of the project
README for a plain-language summary and the weight table.

Phase 5 adds one more DB-aware entry point on top of the six above:

- `get_manager_dashboard(db, ...)` — composes every dashboard section (summary tiles, employee
  performance, workload distribution, project progress, delayed tasks, upcoming deadlines,
  efficiency trend) from one consistent set of filters, reusing the six functions above plus
  `metrics.average_completion_days` and `dashboard.calculate_efficiency_trend` (both new in
  Phase 5). See `dashboard.py` for the full filter semantics.
"""

from app.services.analytics.dashboard import calculate_efficiency_trend, get_manager_dashboard
from app.services.analytics.metrics import (
    average_completion_days,
    calculate_project_progress,
    calculate_workload,
    detect_deadline_risk,
    detect_delays,
)
from app.services.analytics.scoring import calculate_employee_score, calculate_team_score

__all__ = [
    "calculate_employee_score",
    "calculate_team_score",
    "calculate_workload",
    "calculate_project_progress",
    "detect_deadline_risk",
    "detect_delays",
    "average_completion_days",
    "calculate_efficiency_trend",
    "get_manager_dashboard",
]
