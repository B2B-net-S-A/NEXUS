"""GET /api/admin/candidate-pii-orphans — read-only erasure gap report.

Deletion and anonymisation of a candidate are implemented as ad-hoc
``session.delete()`` + FK cascade, not as a domain command with a plan. The
result is wrong in both directions and this endpoint measures both, without
changing anything:

- **PII survives.** When a candidate row goes away, several stores keep the
  person's data. Some tables ``SET NULL`` the candidate FK but retain the
  payload (e-mail bodies, generated CVs, calendar rows); one integration table
  (``traffit_webhook_events``) never had a candidate FK at all, so the raw
  Traffit candidate JSON persists indefinitely.
- **Evidence is over-deleted.** A candidate hard delete cascades into
  ``contracts`` and from there into ``invoices``, ``document_signatures`` and
  ``client_orders`` — destroying the commercial and legal trail that must be
  retained. This report previews that blast radius as an aggregate so the cost
  is visible *before* any executor is built.

Contract, identical to the other admin inventories:
- **Read-only.** SELECT / COUNT only. No DDL, no DML, no delete, nothing.
- **Zero PII.** Output is counts, severities and descriptions — never a name,
  e-mail, phone or body. No row content is selected.
- Each check has its own timeout; one failing check yields an ``error`` field
  rather than collapsing the report.
- ``query_version`` lets successive runs be compared.

This is the safe first step of the erasure work. It deliberately does NOT
re-enable the disabled DELETE endpoint, does NOT run the merge CLI, and does NOT
touch production data. The real fix — a deferred privacy executor that reaches
object storage / Qdrant / integration payloads and *retains* contracts,
invoices and signatures — is a separate, destructive change that needs its own
review and a verified backup.

Auth: same as ``/api/admin/snapshot`` — ``X-Snapshot-Token`` or admin JWT.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_snapshot import _snapshot_auth
from app.core.database import get_db

router = APIRouter()

QUERY_VERSION = "candidate-pii-orphans-v1"
CHECK_TIMEOUT_SECONDS = 20.0


# Each check: (key, severity, description, sql). SQL must return a single
# integer column named ``n`` and must never select row content.
_CHECKS: tuple[tuple[str, str, str, str], ...] = (
    # ── PII survives an erasure (under-deletion) ─────────────────────────────
    (
        "emails_unlinked_with_body",
        "high",
        "E-mails whose candidate FK is NULL but which still carry a body — "
        "candidate PII (correspondence) retained after the link was cut. Upper "
        "bound: also counts mail that never had a candidate.",
        "SELECT count(*) AS n FROM emails "
        "WHERE candidate_id IS NULL "
        "AND (body_html IS NOT NULL OR body_text IS NOT NULL)",
    ),
    (
        "traffit_webhook_events_total",
        "high",
        "Traffit webhook events — raw candidate JSON in `payload`, with NO "
        "candidate FK at all, so a candidate erasure never reaches them. Every "
        "row is un-erasable candidate PII.",
        "SELECT count(*) AS n FROM traffit_webhook_events",
    ),
    (
        "cv_generated_documents_unlinked",
        "medium",
        "Generated branded CVs with a NULL candidate FK — the rendered document "
        "(candidate name + history) is retained after the link was cut.",
        "SELECT count(*) AS n FROM cv_generated_documents WHERE candidate_id IS NULL",
    ),
    (
        "calendar_events_unlinked",
        "low",
        "Calendar events with a NULL candidate FK — interview context retained "
        "unlinked.",
        "SELECT count(*) AS n FROM calendar_events WHERE candidate_id IS NULL",
    ),
    # ── Legal / financial evidence a hard delete WOULD destroy (over-deletion)─
    # These are aggregate blast-radius previews: how many retention-worthy rows
    # are reachable from candidates via the cascade. They are NOT deletions.
    (
        "blast_contracts_on_candidates",
        "high",
        "Contracts reachable from a live candidate — a candidate hard delete "
        "cascades into every one of these (contracts.candidate_id CASCADE).",
        "SELECT count(*) AS n FROM contracts WHERE candidate_id IS NOT NULL",
    ),
    (
        "blast_invoices_via_candidate_contracts",
        "high",
        "Invoices that a candidate hard delete would destroy via "
        "candidate → contracts → invoices CASCADE. Financial records that must "
        "be retained.",
        "SELECT count(*) AS n FROM invoices i "
        "JOIN contracts c ON c.id = i.contract_id "
        "WHERE c.candidate_id IS NOT NULL",
    ),
    (
        "blast_signatures_via_candidate_contracts",
        "high",
        "Signed-document / e-signature records destroyed via the same "
        "candidate → contracts cascade. Legal evidence that must be retained.",
        "SELECT count(*) AS n FROM document_signatures s "
        "JOIN contracts c ON c.id = s.contract_id "
        "WHERE c.candidate_id IS NOT NULL",
    ),
    (
        "blast_client_orders_via_candidate_contracts",
        "medium",
        "Client purchase orders destroyed via the candidate → contracts cascade.",
        "SELECT count(*) AS n FROM client_orders o "
        "JOIN contracts c ON c.id = o.contract_id "
        "WHERE c.candidate_id IS NOT NULL",
    ),
)


async def _run_check(db: AsyncSession, sql: str) -> int:
    result = await asyncio.wait_for(
        db.execute(text(sql)), timeout=CHECK_TIMEOUT_SECONDS
    )
    return int(result.scalar() or 0)


@router.get("/candidate-pii-orphans")
async def candidate_pii_orphans(
    auth_mode: Annotated[str, Depends(_snapshot_auth)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Measure PII that survives candidate erasure and evidence it over-deletes.

    Read-only. Emits counts and severities only — never row content.
    """
    started = time.monotonic()
    out: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_version": QUERY_VERSION,
        "auth_mode": auth_mode,
    }

    checks: list[dict[str, Any]] = []
    pii_survives = 0
    evidence_at_risk = 0
    for key, severity, description, sql in _CHECKS:
        entry: dict[str, Any] = {
            "key": key,
            "severity": severity,
            "description": description,
        }
        try:
            n = await _run_check(db, sql)
            entry["count"] = n
            if key.startswith("blast_"):
                evidence_at_risk += n
            else:
                pii_survives += n
        except asyncio.TimeoutError:
            entry["error"] = "timeout"
        except Exception as exc:  # noqa: BLE001 — one bad check must not 500 the report
            entry["error"] = type(exc).__name__
        checks.append(entry)

    out["checks"] = checks
    out["summary"] = {
        # Rows still holding candidate PII after an erasure (under-deletion).
        "pii_bearing_rows_surviving": pii_survives,
        # Retention-worthy rows a candidate hard delete would destroy today.
        "evidence_rows_a_hard_delete_would_destroy": evidence_at_risk,
        "checks_run": len(checks),
        "checks_errored": sum(1 for c in checks if "error" in c),
    }
    out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return out
