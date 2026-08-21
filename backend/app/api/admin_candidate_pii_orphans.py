"""GET /api/admin/candidate-pii-orphans — read-only erasure gap report.

Deletion and anonymisation of a candidate are implemented as ad-hoc
``session.delete()`` + FK cascade, not as a domain command with a plan. The
result is wrong in both directions and this endpoint measures both, without
changing anything:

- **PII survives.** When a candidate row goes away, several stores keep the
  person's data. Some tables ``SET NULL`` the candidate FK but retain the
  payload (e-mail bodies, generated CVs, calendar rows, the Traffit
  contact-intake ledger); one integration table (``traffit_webhook_events``)
  never had a candidate FK at all, so the raw Traffit candidate JSON persists
  indefinitely.
- **Evidence is detached, not destroyed** (since migration 0225, 2026-08-12).
  ``contracts.candidate_id`` is ``ON DELETE SET NULL`` and the delete endpoint
  stamps every contract with a pseudonymous ``candidate_subject_ref`` first, so
  contracts — and with them ``invoices``, ``document_signatures`` and
  ``client_orders`` — survive an erasure, unlinked. The ``blast_*`` counts below
  therefore measure REACH ("how many retention-worthy rows lose their link to a
  person"), NOT destruction. Until 2026-08-12 the same counts really did mean
  destruction, which is why the wording changed; a run predating
  ``query_version`` v3 must be read with the old meaning.

Contract, identical to the other admin inventories:
- **Read-only.** SELECT / COUNT only. No DDL, no DML, no delete, nothing.
- **Zero PII.** Output is counts, severities and descriptions — never a name,
  e-mail, phone or body. No row content is selected.
- Each check has its own timeout; one failing check yields an ``error`` field
  rather than collapsing the report.
- ``query_version`` lets successive runs be compared.

This report stays read-only: it does NOT delete, does NOT run the merge CLI and
does NOT touch production data. ``DELETE /api/candidates/{id}`` is live again
(2026-08-12) and now reaches object storage and the Qdrant index itself, so what
this report still measures is the residue nobody erases: unlinked payloads whose
tables have no candidate FK to follow.

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

QUERY_VERSION = "candidate-pii-orphans-v3"
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
        "row is un-erasable candidate PII. NOTE: no endpoint writes to this "
        "table today, so a 0 here means 'the inbox was never wired up', not "
        "'the erasure gap is closed' — the check stays as a tripwire for the "
        "day it is.",
        "SELECT count(*) AS n FROM traffit_webhook_events",
    ),
    (
        "candidate_contact_traffit_ledger_orphaned_pii",
        "high",
        "Traffit contact-intake ledger rows whose candidate FK was SET NULL by "
        "an erasure but which still carry the durable Traffit person id and/or "
        "the verbatim remote event body. The poller scrubs `processed` rows on "
        "each tick; `exception` rows are deliberately left intact because the "
        "retry loop replays `raw_payload`, so they need a manual resolution "
        "before they can be erased.",
        "SELECT count(*) AS n FROM candidate_contact_traffit_ledger "
        "WHERE candidate_id IS NULL "
        "AND (candidate_external_id IS NOT NULL "
        "OR raw_payload <> '{}'::jsonb)",
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
    # ── Legal / financial evidence a hard delete DETACHES ────────────────────
    # Aggregate reach previews: how many retention-worthy rows lose their link
    # to a person when that person is erased. They are NOT deletions, and since
    # migration 0225 they are not destructions either.
    (
        "blast_contracts_on_candidates",
        "high",
        "Contracts reachable from a live candidate. A hard delete does NOT "
        "destroy these — since migration 0225 contracts.candidate_id is ON "
        "DELETE SET NULL and each row is stamped with a pseudonymous "
        "candidate_subject_ref first, so the contract survives, unlinked.",
        "SELECT count(*) AS n FROM contracts WHERE candidate_id IS NOT NULL",
    ),
    (
        "blast_invoices_via_candidate_contracts",
        "high",
        "Invoices hanging off a live candidate's contracts. They have no "
        "candidate FK of their own, so they survive an erasure untouched — the "
        "contract above keeps them reconcilable via candidate_subject_ref.",
        "SELECT count(*) AS n FROM invoices i "
        "JOIN contracts c ON c.id = i.contract_id "
        "WHERE c.candidate_id IS NOT NULL",
    ),
    (
        "blast_signatures_via_candidate_contracts",
        "high",
        "Signed-document / e-signature records hanging off a live candidate's "
        "contracts. Retained across an erasure for the same reason as invoices.",
        "SELECT count(*) AS n FROM document_signatures s "
        "JOIN contracts c ON c.id = s.contract_id "
        "WHERE c.candidate_id IS NOT NULL",
    ),
    (
        "blast_client_orders_via_candidate_contracts",
        "medium",
        "Client purchase orders hanging off a live candidate's contracts. "
        "Retained across an erasure, reachable through the pseudonymised contract.",
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
        # Retention-worthy rows a hard delete UNLINKS from the person (they
        # survive, pseudonymised through the contract). Nazwa mówiąca prawdę.
        "evidence_rows_detached_by_a_hard_delete": evidence_at_risk,
        # DEPRECATED alias tej samej liczby pod dawną, już nieprawdziwą nazwą
        # („…would_destroy"). Zostaje wyłącznie dlatego, że pinuje ją
        # `tests/test_candidate_pii_orphans.py`; do usunięcia razem z tamtą
        # asercją. NIE opieraj na niej nowych konsumentów.
        "evidence_rows_a_hard_delete_would_destroy": evidence_at_risk,
        "checks_run": len(checks),
        "checks_errored": sum(1 for c in checks if "error" in c),
    }
    out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return out
