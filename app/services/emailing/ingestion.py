"""Turns an email — either a structured request or a raw `.eml` file — into an `Email` row.

Two entry points, one shared insertion path:
- `ingest_email(db, data)` — structured data (the primary integration point: a future live
  connector, or a script, posts already-parsed fields here).
- `parse_eml(content)` — parses raw RFC 5322 bytes (Python's `email` stdlib, no third-party
  dependency, no network/credentials needed) into the same shape `ingest_email` accepts. This
  is the intended extension point for a future live mailbox connector (IMAP/Gmail/Outlook API):
  such a connector would fetch raw messages and hand them to `parse_eml`, or fetch already-
  structured data and call `ingest_email` directly — either way, nothing else in this package
  changes.

`direction`/`is_external` are computed here, once, from address domains only (metadata) — never
from message content. Internal domains are derived from the real `User.email` addresses already
in the database, so no separate configuration is needed or invented.
"""

from __future__ import annotations

import email as email_stdlib
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.utils import getaddresses, parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import Email
from app.models.enums import EmailDirection
from app.models.user import User
from app.services.emailing.constants import MAX_BODY_CHARS


class InvalidEmailError(ValueError):
    """A .eml file is missing information (From/Date) needed to ingest it."""


@dataclass
class ParsedEmail:
    subject: str | None
    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    sent_at: datetime
    body_text: str | None
    message_id: str | None
    in_reply_to: str | None


@dataclass
class EmailIngestData:
    """Plain-data shape `ingest_email` accepts — matches `app.schemas.email.EmailIngestRequest`
    but kept as an independent dataclass so this module has no dependency on the API schema
    layer (usable from a script or a future connector without importing FastAPI/Pydantic).
    """

    from_address: str
    to_addresses: list[str]
    sent_at: datetime
    task_id: int | None = None
    project_id: int | None = None
    subject: str | None = None
    cc_addresses: list[str] | None = None
    body_text: str | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    linked_by: int | None = None


def parse_eml(content: bytes) -> ParsedEmail:
    msg = email_stdlib.message_from_bytes(content, policy=policy.default)

    from_header = msg.get("From")
    if not from_header:
        raise InvalidEmailError("Email is missing a From header.")
    from_pairs = getaddresses([from_header])
    if not from_pairs or not from_pairs[0][1]:
        raise InvalidEmailError("Could not parse a From address.")
    from_address = from_pairs[0][1]

    date_header = msg.get("Date")
    if not date_header:
        raise InvalidEmailError("Email is missing a Date header.")
    try:
        sent_at = parsedate_to_datetime(date_header)
    except (TypeError, ValueError) as exc:
        raise InvalidEmailError(f"Could not parse Date header: {date_header!r}") from exc
    if sent_at is None:
        raise InvalidEmailError(f"Could not parse Date header: {date_header!r}")

    to_addresses = [addr for _, addr in getaddresses(msg.get_all("To", []) or []) if addr]
    cc_addresses = [addr for _, addr in getaddresses(msg.get_all("Cc", []) or []) if addr]

    body_text = None
    try:
        body_part = msg.get_body(preferencelist=("plain",))
        if body_part is not None:
            body_text = body_part.get_content()
    except Exception:  # noqa: BLE001 — a malformed MIME body should not abort ingestion
        body_text = None
    if body_text is not None:
        body_text = body_text[:MAX_BODY_CHARS]

    return ParsedEmail(
        subject=msg.get("Subject"),
        from_address=from_address,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        sent_at=sent_at,
        body_text=body_text,
        message_id=msg.get("Message-Id"),
        in_reply_to=msg.get("In-Reply-To"),
    )


def _internal_domains(db: Session) -> set[str]:
    addresses = db.scalars(select(User.email)).all()
    return {_domain(a) for a in addresses}


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].strip().lower()


def compute_direction_and_external(
    from_address: str, to_addresses: list[str], cc_addresses: list[str] | None, internal_domains: set[str]
) -> tuple[EmailDirection, bool]:
    from_internal = _domain(from_address) in internal_domains
    direction = EmailDirection.OUTBOUND if from_internal else EmailDirection.INBOUND
    recipient_domains = {_domain(a) for a in (to_addresses + (cc_addresses or []))}
    is_external = (not from_internal) or any(d not in internal_domains for d in recipient_domains)
    return direction, is_external


def ingest_email(db: Session, data: EmailIngestData) -> Email:
    internal_domains = _internal_domains(db)
    direction, is_external = compute_direction_and_external(
        data.from_address, data.to_addresses, data.cc_addresses, internal_domains
    )

    body_text = data.body_text[:MAX_BODY_CHARS] if data.body_text else data.body_text

    record = Email(
        task_id=data.task_id,
        project_id=data.project_id,
        message_id=data.message_id,
        in_reply_to=data.in_reply_to,
        subject=data.subject,
        from_address=data.from_address,
        to_addresses=", ".join(data.to_addresses),
        cc_addresses=", ".join(data.cc_addresses) if data.cc_addresses else None,
        direction=direction,
        is_external=is_external,
        sent_at=data.sent_at,
        body_text=body_text,
        linked_by=data.linked_by,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
