"""Email-based work context (Phase 9): associate emails with tasks/projects, detect
deterministic signals from them (client response delays, pending responses, approval delays,
external blockers, plain communication), and use those signals to *optionally* enrich delay
explanations — never to replace the existing Phase 4 delay/efficiency formulas, and never as a
productivity measure.

- `ingestion.py` — the only module that knows about email formats (structured data or raw
  `.eml` bytes). Extension point for a future live mailbox connector — see its docstring.
- `queries.py` — plain read access to `emails`.
- `permissions.py` — privacy control: who may see one email's content.
- `signals.py` — pure, evidence-based signal detection over a task's linked emails.
- `delay_classification.py` — combines the untouched `metrics.detect_delays` result with
  `signals.py` evidence into an optional, explicit "why" — see its docstring for the guarantee.
"""

from app.services.emailing.ingestion import EmailIngestData, ingest_email, parse_eml

__all__ = ["ingest_email", "parse_eml", "EmailIngestData"]
