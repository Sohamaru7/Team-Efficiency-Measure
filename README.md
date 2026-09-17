# Team Work Efficiency Management System

A FastAPI + PostgreSQL application for tracking tasks, daily updates, and
deterministic team-performance analytics, with an optional Claude-powered
manager assistant.

## Features

- **Auth & RBAC** — JWT login (bcrypt password hashing), three roles:
  Employee (own data), Manager (own department), Admin (everything).
- **Core CRUD** — users, projects, tasks (with status-change history),
  daily updates.
- **Employee UI** — dashboard, my tasks, task details, add/edit task, daily
  work update, my performance (Bootstrap 5 + vanilla JS).
- **Analytics** — deterministic efficiency scoring (completion rate,
  on-time rate, quality, time efficiency, deadline adherence, project
  progress, workload) with documented formulas and weights, no AI involved.
- **Manager Dashboard** — team efficiency, workload, project progress,
  delayed tasks, upcoming deadlines, efficiency trend (Chart.js).
- **Manager AI Assistant** (optional, needs `ANTHROPIC_API_KEY`) — answers
  plain-English questions via a fixed set of read-only tools that call the
  same analytics functions the dashboard uses; the model never computes a
  metric itself.
- **Agentic actions** — the assistant can detect problems (overload,
  imbalance, at-risk deadlines, delays, performance drops) and take action:
  notifications/reports execute immediately, anything that changes task or
  employee data is queued and requires manager approval.
- **Import/export** — CSV/XLSX task import with column mapping, validation,
  duplicate detection, and a preview-before-commit flow; task list and
  dashboard-report export to CSV/XLSX.
- **Email-based work context** — associate emails with tasks/projects;
  deterministic signal detection (client response delay, pending response,
  approval delay, external blocker) can explain *why* a task was delayed.
  Never used as a productivity metric.
- **Autonomous Daily Manager** — an optional scheduled job that runs once
  per working day, reuses the analytics/detection engine, reports only
  what's new or changed in severity since the last run, and can
  auto-notify or propose (approval-gated) task reassignment.
- **Demo mode** — a one-command, disposable, no-setup way to try the app
  (own SQLite DB, seeded data, one-click login as Admin/Manager/Employee).

## Tech stack

FastAPI · SQLAlchemy + Alembic · PostgreSQL · Pydantic · Bootstrap 5 +
vanilla JS + Chart.js · bcrypt + PyJWT · slowapi (rate limiting) ·
Anthropic API (optional) · pytest

## Project structure

```
app/
  main.py             FastAPI app factory, static mount, router registration
  core/                Settings, security (hashing/JWT), rate limiting,
                        middleware, error handlers, upload limits
  database/            Engine/session, base metadata, admin bootstrap
  models/               SQLAlchemy ORM models
  schemas/              Pydantic request/response schemas
  services/             Business logic
    analytics/            Deterministic efficiency scoring + dashboard
    ai/                    Assistant tools, issue detection, actions, approvals
    import_export/         CSV/XLSX import & export pipeline
    emailing/               Email ingestion, signal detection, delay classification
    daily_manager/          Autonomous daily report pipeline + scheduler
    authz.py, auth_service.py   Role/ownership rules, authentication
  api/routes/            One router per resource
  templates/             Jinja2 pages (Bootstrap 5)
  static/                CSS + per-page JS
migrations/             Alembic migration environment
tests/                  pytest suite (unit + API + a few DB-integration tests)
scripts/run_demo.py     Demo mode launcher
```

## Setup

**Prerequisites:** Python 3.12+, a reachable PostgreSQL server.

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` — at minimum set your PostgreSQL credentials and generate a
`JWT_SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Create the database (once) and run migrations:

```bash
createdb team_efficiency
alembic upgrade head
```

Bootstrap the first admin account by setting `ADMIN_BOOTSTRAP_EMAIL` and
`ADMIN_BOOTSTRAP_PASSWORD` in `.env` before the app's first startup — it
creates exactly one admin the first time it boots against an empty `users`
table. Unset both afterward.

Run it:

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/.

### Optional configuration

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Enables the Manager AI Assistant. Blank = every other feature works; the assistant page/endpoint returns a clear 503. |
| `DAILY_MANAGER_SCHEDULER_ENABLED`, `DAILY_MANAGER_RUN_HOUR` | Off by default. When on, runs the Autonomous Daily Manager Mon–Fri at the given UTC hour. `POST /api/daily-manager/run` always works as a manual trigger regardless. |
| `DEMO_MODE` | Never set manually — see Demo Mode below. |

## Demo mode

No PostgreSQL setup, no account needed:

```bash
python scripts/run_demo.py
```

Seeds a disposable SQLite database with realistic sample data and starts
the app at http://127.0.0.1:8100. Open `/login` and click "Enter Demo" to
sign in as Admin, Manager, or Employee. Role-based access control still
applies in full — only the password step is skipped.

## Running tests

```bash
pytest tests/ -v
```

Runs against an in-memory SQLite database — no PostgreSQL required. Most
requests authenticate as a fixed admin test fixture; authentication and
authorization themselves are covered directly in `test_auth.py`,
`test_authorization_boundaries.py`, and `test_agent_permissions.py`.

## API overview

Full interactive docs at `/docs` once the app is running. Main resource
groups:

| Area | Base path |
|---|---|
| Auth | `/api/auth/*` (login, logout, me, change-password) |
| Users / Projects / Tasks / Daily updates | `/api/users`, `/api/projects`, `/api/tasks`, `/api/daily-updates` |
| Analytics | `/api/analytics/*` (per-employee score, workload, deadline risk, delays; per-project progress; team score) |
| Dashboard | `/api/dashboard` |
| AI Assistant | `/api/ai/ask`, `/api/ai/actions` (+ approve/reject) |
| Import / Export | `/api/import/*`, `/api/export/*` |
| Emails | `/api/emails/*` |
| Autonomous Daily Manager | `/api/daily-manager/*` |
| Health | `/api/health`, `/api/health/db` (public) |

All endpoints except `/api/health*` and demo-login require a bearer token
and enforce role/ownership rules (see `app/services/authz.py`).

## Known limitations

- **No refresh tokens.** Sessions expire after `ACCESS_TOKEN_EXPIRE_MINUTES`
  (default 60) with no silent renewal.
- **Rate limiting is single-process, in-memory** — a multi-worker/multi-
  instance deployment needs a shared backend (slowapi supports Redis via
  `storage_uri`).
- **No CORS/CSRF configuration** — the app is same-origin only (API + UI
  served by one process); add CORS explicitly if a separate frontend origin
  is introduced.
- **Not tested against real PostgreSQL in development** — the test suite
  runs against SQLite, which exercises the same models/relationships but
  not Postgres-specific DDL (native enum types). Run `alembic upgrade head`
  against your own instance and verify before relying on it.
- **`send_notification` has no real delivery channel** — it records an
  auditable action but doesn't email/SMS/in-app-notify anyone.
- **No performance-score history** — `performance_scores` has a read-only
  API but nothing currently populates it; analytics are point-in-time
  snapshots computed live, not period-bucketed history.
- **Detection thresholds are fixed constants** (workload cutoffs, imbalance
  spread, delay lookback, etc.) — not configurable per team/department.
- **No dependency vulnerability scan has been run** (e.g. `pip-audit`).

This system is not fully production-ready — treat the above as a checklist
before a real deployment, not as exhaustive.
