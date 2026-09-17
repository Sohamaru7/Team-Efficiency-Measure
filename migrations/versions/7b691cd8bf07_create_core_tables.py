"""create core tables

Revision ID: 7b691cd8bf07
Revises:
Create Date: 2026-08-14 17:46:40.359941

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7b691cd8bf07'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum types are created explicitly (once) and referenced from multiple
# columns/tables with create_type=False, so op.create_table doesn't try to
# re-issue CREATE TYPE for a type that already exists.
user_role_enum = postgresql.ENUM("admin", "manager", "employee", name="user_role", create_type=False)
project_status_enum = postgresql.ENUM(
    "planning", "active", "on_hold", "completed", "cancelled", name="project_status", create_type=False
)
task_priority_enum = postgresql.ENUM("low", "medium", "high", "urgent", name="task_priority", create_type=False)
task_status_enum = postgresql.ENUM(
    "not_started", "in_progress", "blocked", "completed", "cancelled", name="task_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    user_role_enum.create(bind, checkfirst=True)
    project_status_enum.create(bind, checkfirst=True)
    task_priority_enum.create(bind, checkfirst=True)
    task_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", user_role_enum, nullable=False, server_default="employee"),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_department"), "users", ["department"], unique=False)

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("status", project_status_enum, nullable=False, server_default="planning"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "deadline IS NULL OR start_date IS NULL OR deadline >= start_date",
            name=op.f("ck_project_deadline_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"], ["users.id"], name=op.f("fk_projects_manager_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(op.f("ix_projects_name"), "projects", ["name"], unique=False)
    op.create_index(op.f("ix_projects_manager_id"), "projects", ["manager_id"], unique=False)
    op.create_index(op.f("ix_projects_status"), "projects", ["status"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("assigned_to", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", task_priority_enum, nullable=False, server_default="medium"),
        sa.Column("estimated_hours", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("actual_hours", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("completed_date", sa.Date(), nullable=True),
        sa.Column("status", task_status_enum, nullable=False, server_default="not_started"),
        sa.Column("quality_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("delay_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("estimated_hours IS NULL OR estimated_hours >= 0", name=op.f("ck_task_estimated_hours_nonneg")),
        sa.CheckConstraint("actual_hours IS NULL OR actual_hours >= 0", name=op.f("ck_task_actual_hours_nonneg")),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name=op.f("ck_task_quality_score_range"),
        ),
        sa.CheckConstraint(
            "deadline IS NULL OR start_date IS NULL OR deadline >= start_date",
            name=op.f("ck_task_deadline_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_tasks_project_id_projects"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"], ["users.id"], name=op.f("fk_tasks_assigned_to_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_index(op.f("ix_tasks_assigned_to"), "tasks", ["assigned_to"], unique=False)
    op.create_index(op.f("ix_tasks_priority"), "tasks", ["priority"], unique=False)
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)

    op.create_table(
        "task_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("old_status", task_status_enum, nullable=True),
        sa.Column("new_status", task_status_enum, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_task_history_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"], ["users.id"], name=op.f("fk_task_history_changed_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_history")),
    )
    op.create_index(op.f("ix_task_history_task_id"), "task_history", ["task_id"], unique=False)
    op.create_index(op.f("ix_task_history_changed_by"), "task_history", ["changed_by"], unique=False)
    op.create_index(op.f("ix_task_history_timestamp"), "task_history", ["timestamp"], unique=False)

    op.create_table(
        "daily_updates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("tasks_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_pending", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blockers", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("tasks_completed >= 0", name=op.f("ck_daily_update_tasks_completed_nonneg")),
        sa.CheckConstraint("tasks_pending >= 0", name=op.f("ck_daily_update_tasks_pending_nonneg")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_daily_updates_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_updates")),
        sa.UniqueConstraint("user_id", "date", name=op.f("uq_daily_update_user_date")),
    )
    op.create_index(op.f("ix_daily_updates_user_id"), "daily_updates", ["user_id"], unique=False)
    op.create_index(op.f("ix_daily_updates_date"), "daily_updates", ["date"], unique=False)

    op.create_table(
        "performance_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=20), nullable=False),
        sa.Column("completion_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("timeliness_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("quality_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("time_efficiency_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("workload_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("overall_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "completion_score IS NULL OR completion_score BETWEEN 0 AND 100", name=op.f("ck_perf_completion_range")
        ),
        sa.CheckConstraint(
            "timeliness_score IS NULL OR timeliness_score BETWEEN 0 AND 100", name=op.f("ck_perf_timeliness_range")
        ),
        sa.CheckConstraint(
            "quality_score IS NULL OR quality_score BETWEEN 0 AND 100", name=op.f("ck_perf_quality_range")
        ),
        sa.CheckConstraint(
            "time_efficiency_score IS NULL OR time_efficiency_score BETWEEN 0 AND 100",
            name=op.f("ck_perf_time_efficiency_range"),
        ),
        sa.CheckConstraint(
            "workload_score IS NULL OR workload_score BETWEEN 0 AND 100", name=op.f("ck_perf_workload_range")
        ),
        sa.CheckConstraint(
            "overall_score IS NULL OR overall_score BETWEEN 0 AND 100", name=op.f("ck_perf_overall_range")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_performance_scores_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_scores")),
        sa.UniqueConstraint("user_id", "period", name=op.f("uq_performance_score_user_period")),
    )
    op.create_index(op.f("ix_performance_scores_user_id"), "performance_scores", ["user_id"], unique=False)
    op.create_index(op.f("ix_performance_scores_period"), "performance_scores", ["period"], unique=False)

    op.create_table(
        "agent_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_type", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_actions")),
    )
    op.create_index(op.f("ix_agent_actions_agent_type"), "agent_actions", ["agent_type"], unique=False)
    op.create_index(op.f("ix_agent_actions_timestamp"), "agent_actions", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_table("agent_actions")
    op.drop_table("performance_scores")
    op.drop_table("daily_updates")
    op.drop_table("task_history")
    op.drop_table("tasks")
    op.drop_table("projects")
    op.drop_table("users")

    bind = op.get_bind()
    task_status_enum.drop(bind, checkfirst=True)
    task_priority_enum.drop(bind, checkfirst=True)
    project_status_enum.drop(bind, checkfirst=True)
    user_role_enum.drop(bind, checkfirst=True)
