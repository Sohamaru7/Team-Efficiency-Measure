import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"


class ProjectStatus(str, enum.Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AgentActionStatus(str, enum.Enum):
    """Lifecycle of one AgentAction row (Phase 7).

    PENDING        - a write-action was proposed and is awaiting manager approval; nothing has
                      been executed yet.
    AUTO_APPROVED  - a low-risk action (notification, report) executed immediately, no approval
                      needed. Also used for read-only tool calls (Phase 6 behavior, unchanged).
    APPROVED       - a manager approved a pending action and it executed successfully.
    REJECTED       - a manager rejected a pending action; nothing was executed.
    FAILED         - a manager approved a pending action but execution failed (e.g. the
                      referenced task/employee no longer exists, or backend validation rejected
                      the change) — the failure is recorded, nothing partial was applied.
    """

    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class EmailDirection(str, enum.Enum):
    """Which way an email flowed relative to this organization (existing `User.email` domains
    are treated as "internal" — see app.services.emailing.ingestion). Computed once at
    ingestion time from address domains only — metadata, never message content.

    OUTBOUND - sent by an internal user (From address domain is a known internal domain).
    INBOUND  - received from outside (From address domain is not a known internal domain).
    """

    INBOUND = "inbound"
    OUTBOUND = "outbound"
