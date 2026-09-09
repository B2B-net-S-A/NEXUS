"""Explicit, fingerprinted one-off cleanup for the September 9 tickets.

Never called from startup, polling or a client status change. The durable
receipt survives deployment and separates deleted clients from blocked ones.
Every foreign key is inventoried from the live database, including CASCADE
and SET NULL; nothing is silently cascaded. Non-FK references are also blockers.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, text, delete, func

from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.services.client_identity import visible_client_predicates
from app.models.order_mail import OrderMailDocument
from app.services.client_portfolio_import import (
    _direct_client_fk_specs,
    _validate_identifier,
)
from app.services.order_mail_ingest import refresh_review_plan
from app.services.order_policies.registry import is_client_in_policy
from app.services.order_policies.nordea import non_order_reason
from app.services.order_mail_apply import apply_document
from app.services import storage_service
from app.services.order_document_text import extract_order_text
from fastapi.concurrency import run_in_threadpool

RECEIPT_KEY = "order_mail_cleanup_20260909_v1"
HISTORY_TABLES = {
    "jobs": "Aktywne i zamknięte projekty / statystyki współpracy",
    "contracts": "Umowy i przypisani konsultanci — wszystkie statusy",
    "client_orders": "Zamówienia — wszystkie statusy",
    "client_order_groups": "Grupy zamówień — wszystkie statusy",
    "client_one_pagers": "Materiały sprzedażowe",
    "client_knowledge": "Notatki i wiedza w profilu klienta",
}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


async def client_inventory(db):
    clients = (
        await db.scalars(
            select(Client)
            .where(
                *visible_client_predicates(),
                select(ClientPortfolioScope.id)
                .where(
                    ClientPortfolioScope.client_id == Client.id,
                    ClientPortfolioScope.archived_at.is_(None),
                    func.coalesce(
                        ClientPortfolioScope.category_override,
                        ClientPortfolioScope.category,
                    )
                    == PortfolioCategory.inactive,
                )
                .exists(),
            )
            .order_by(Client.id)
        )
    ).all()
    target_ids = [c.id for c in clients]
    if not target_ids:
        return {"delete_candidates": [], "blocked": [], "preserved": []}
    specs = await _direct_client_fk_specs(db)
    if not specs:
        raise ValueError("Brak katalogu zależności PostgreSQL — czyszczenie wstrzymane")
    refs = defaultdict(list)
    for spec in specs:
        table, column = spec["table"], spec["column"]
        for cid, count in (
            await db.execute(
                text(
                    f'SELECT r."{column}", count(*) FROM "{table}" r JOIN clients c '
                    f'ON c.id=r."{column}" WHERE c.id = ANY(:target_ids) GROUP BY r."{column}"'
                ),
                {"target_ids": target_ids},
            )
        ).all():
            refs[cid].append(
                {
                    "table": table,
                    "column": column,
                    "count": count,
                    "description": HISTORY_TABLES.get(
                        table,
                        "Przypisanie do zakładki Klienci i historia importu"
                        if table == "client_portfolio_scopes"
                        else f"Powiązane dane: {table}.{column}",
                    ),
                }
            )
    # Inspect every polymorphic reference pair in the catalog, not only the
    # familiar activities/notifications models. Unknown references fail closed.
    columns = (
        await db.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema=current_schema()"
            )
        )
    ).all()
    by_table = defaultdict(set)
    for table, column in columns:
        by_table[table].add(column)
    for table, cols in sorted(by_table.items()):
        table = _validate_identifier(table)
        pairs = sorted((col, col[:-3] + "_type") for col in cols if col.endswith("_id"))
        for idcol, typecol in pairs:
            if typecol not in cols:
                continue
            idcol, typecol = _validate_identifier(idcol), _validate_identifier(typecol)
            for cid, count in (
                await db.execute(
                    text(
                        f'SELECT c.id, count(*) FROM "{table}" r JOIN clients c '
                        f'ON r."{idcol}"::text=c.id::text WHERE c.id = ANY(:target_ids) '
                        f"AND r.\"{typecol}\"::text IN ('client','clients') GROUP BY c.id"
                    ),
                    {"target_ids": target_ids},
                )
            ).all():
                refs[cid].append(
                    {
                        "table": table,
                        "column": idcol,
                        "count": count,
                        "description": f"Powiązanie bez klucza obcego: {table}.{idcol}",
                    }
                )
    # Candidate preferences are the known non-FK JSON client-id collection.
    for cid, count in (
        await db.execute(
            text("""
        SELECT c.id, count(*) FROM clients c JOIN candidates p ON
        p.preferences @> jsonb_build_object('excluded_clients', jsonb_build_array(c.id))
        OR p.preferences @> jsonb_build_object('excluded_clients', jsonb_build_array(c.id::text))
        WHERE c.id = ANY(:target_ids) GROUP BY c.id
    """),
            {"target_ids": target_ids},
        )
    ).all():
        refs[cid].append(
            {
                "table": "candidates",
                "column": "preferences",
                "count": count,
                "description": "Preferencje kandydatów — wykluczony klient",
            }
        )
    result = {"delete_candidates": [], "blocked": [], "preserved": []}
    for client in clients:
        related = refs[client.id]
        history = [r for r in related if r["table"] in HISTORY_TABLES]
        if (client.notes or "").strip():
            history.append(
                {
                    "table": "clients",
                    "column": "notes",
                    "count": 1,
                    "description": "Notatki w profilu klienta",
                }
            )
        if client.nda_signed:
            history.append(
                {
                    "table": "clients",
                    "column": "nda_signed",
                    "count": 1,
                    "description": "Potwierdzone podpisanie NDA",
                }
            )
        record = {
            "id": client.id,
            "name": client.display_name or client.name,
            "dependencies": related,
            "history": history,
            "snapshot": fingerprint(
                {c.name: getattr(client, c.name) for c in Client.__table__.columns}
            ),
        }
        category = (
            "preserved" if history else "blocked" if related else "delete_candidates"
        )
        result[category].append(record)
    return result


def _snapshot(doc):
    return {
        "id": doc.id,
        "client_id": doc.client_id,
        "client_key": doc.client_key,
        "attachment": doc.attachment_name,
        "sha256": doc.attachment_sha256,
        "outcome": doc.outcome,
        "extraction": copy.deepcopy(doc.extraction),
        "proposal": copy.deepcopy(doc.proposal),
        "reasons": copy.deepcopy(doc.gate_reasons),
        "verdict": doc.gate_verdict,
        "applied_order_id": doc.applied_order_id,
    }


async def queue_inventory(db):
    ids = list(
        (
            await db.scalars(
                select(OrderMailDocument.id)
                .where(OrderMailDocument.outcome == "needs_review")
                .order_by(OrderMailDocument.id)
            )
        ).all()
    )
    plans = []
    for doc_id in ids:
        doc = await db.get(OrderMailDocument, doc_id)
        before = _snapshot(doc)
        if doc.applied_order_id or (doc.proposal or {}).get("apply_result"):
            plans.append(
                {
                    "before": before,
                    "action": "preserve",
                    "reason": "Dokument już częściowo zapisany",
                }
            )
            continue
        # Roll back even the ORM modifications from re-planning: dry run never
        # persists changes, not even while building a report for another client.
        async with db.begin_nested() as tx:
            try:
                path = storage_service.get_order_mail_attachment_path(doc.storage_path)
                source = await run_in_threadpool(
                    extract_order_text, str(path), doc.attachment_name
                )
                ignored = (
                    non_order_reason(source.text)
                    if is_client_in_policy("nordea", doc.client_id)
                    else None
                )
                if ignored:
                    plans.append(
                        {
                            "before": before,
                            "action": "dismiss_non_order",
                            "reason": ignored,
                        }
                    )
                else:
                    await refresh_review_plan(db, doc)
                    after = _snapshot(doc)
                    pfron = is_client_in_policy("pfron", doc.client_id)
                    action = (
                        "apply"
                        if doc.gate_verdict == "auto"
                        else "preserve"
                        if pfron
                        else "refresh"
                    )
                    plans.append({"before": before, "after": after, "action": action})
            except Exception as exc:
                plans.append(
                    {"before": before, "action": "preserve", "reason": str(exc)[:500]}
                )
            finally:
                await tx.rollback()
    return plans


async def build_cleanup_plan(db):
    clients = await client_inventory(db)
    queue = await queue_inventory(db)
    counts = defaultdict(Counter)
    for item in queue:
        before = item["before"]
        label = before["client_key"] or str(before["client_id"])
        for reason in before["reasons"] or []:
            counts[label][reason] += 1
    plan = {
        "clients": clients,
        "queue": queue,
        "review_reasons_by_client": {k: dict(v) for k, v in counts.items()},
    }
    return {**plan, "fingerprint": fingerprint(plan)}


async def apply_cleanup_plan(db, expected_fingerprint):
    await db.execute(text("SELECT pg_advisory_xact_lock(20260909, 1)"))
    receipt = await db.get(AppSetting, RECEIPT_KEY)
    if receipt:
        return receipt.value
    # Hold all inventoried tables against concurrent changes until commit.
    # Short, explicit maintenance only; polling never takes this table lock.
    specs = await _direct_client_fk_specs(db)
    tables = sorted(
        {
            "clients",
            "activities",
            "notifications",
            "candidates",
            "order_mail_documents",
            *(s["table"] for s in specs),
        }
    )
    await db.execute(text("SET LOCAL lock_timeout = '5s'"))
    await db.execute(
        text(
            "LOCK TABLE "
            + ", ".join(f'"{_validate_identifier(t)}"' for t in tables)
            + " IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    plan = await build_cleanup_plan(db)
    if plan["fingerprint"] != expected_fingerprint:
        raise ValueError(
            "Dane zmieniły się od audytu. Wykonaj nowy audyt; nic nie usunięto."
        )
    results = []
    for item in plan["queue"]:
        doc = await db.get(OrderMailDocument, item["before"]["id"])
        action = item["action"]
        if action == "dismiss_non_order":
            doc.outcome = "dismissed"
            doc.extraction = None
            doc.proposal = None
            doc.gate_verdict = None
            doc.gate_reasons = [item["reason"]]
            doc.document_meta = {"ignored_non_order": True, "reason": item["reason"]}
        elif action in ("refresh", "apply"):
            await refresh_review_plan(db, doc)
            if action == "apply":
                applied = await apply_document(db, doc, actor_user_id=None)
                if not applied.ok:
                    raise ValueError(
                        f"Zapis dokumentu {item['before']['id']} nie powiódł się: {applied.error}"
                    )
                doc.outcome = "auto_applied"
                doc.error = None
        results.append(
            {
                "document_id": item["before"]["id"],
                "action": action,
                "after": _snapshot(doc),
            }
        )
    deleted = plan["clients"]["delete_candidates"]
    for record in deleted:
        # Raw DELETE cannot trigger an ORM cascade. The catalog precheck rejects
        # even SET NULL dependencies; table locks close the check/delete race.
        await db.execute(delete(Client).where(Client.id == record["id"]))
    receipt_value = {
        "fingerprint": expected_fingerprint,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "deleted_clients": deleted,
        "blocked_clients": plan["clients"]["blocked"],
        "preserved_clients": plan["clients"]["preserved"],
        "queue_results": results,
        "review_reasons_by_client": plan["review_reasons_by_client"],
    }
    db.add(AppSetting(key=RECEIPT_KEY, value=receipt_value))
    await db.flush()
    return receipt_value
