"""Maps arbitrary spreadsheet column headers onto the fixed set of canonical fields this system
understands, so an uploaded file doesn't have to use this app's exact internal names. Matching
is automatic (alias table below) rather than an interactive drag-and-drop wizard — out of scope
for this phase — but the resolved mapping is always returned in the preview/commit response so
a manager can see exactly which of their columns was used for what before anything is inserted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical field -> the set of header spellings (already normalized, see _normalize) accepted
# for it. Add a new alias here to support another spreadsheet convention — nothing else in the
# pipeline needs to change.
COLUMN_ALIASES: dict[str, set[str]] = {
    "employee": {"employee", "employee name", "assigned to", "assignee", "assigned employee", "name"},
    "task": {"task", "task title", "title", "task name"},
    "project": {"project", "project name"},
    "priority": {"priority"},
    "estimated_hours": {"estimated hours", "est hours", "estimate", "estimated"},
    "actual_hours": {"actual hours", "hours spent", "actual"},
    "start_date": {"start date", "started", "start"},
    "deadline": {"deadline", "due date", "end date", "due"},
    "status": {"status", "task status"},
    "quality": {"quality", "quality score"},
    "delay_reason": {"delay reason", "reason for delay", "reason"},
}

REQUIRED_FIELDS = {"task", "project"}

CANONICAL_FIELDS = list(COLUMN_ALIASES)


@dataclass
class ColumnMapping:
    # canonical field -> the actual header text found in the file, or None if unmapped.
    mapping: dict[str, str | None] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)


def _normalize(header: str) -> str:
    normalized = re.sub(r"[_\-]+", " ", header.strip().lower())
    return re.sub(r"\s+", " ", normalized).strip()


def map_columns(headers: list[str]) -> ColumnMapping:
    normalized_headers = {_normalize(h): h for h in headers}

    mapping: dict[str, str | None] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        actual_header = None
        for alias in aliases:
            if alias in normalized_headers:
                actual_header = normalized_headers[alias]
                break
        mapping[canonical] = actual_header

    missing_required = [f for f in REQUIRED_FIELDS if mapping[f] is None]
    return ColumnMapping(mapping=mapping, missing_required=missing_required)
