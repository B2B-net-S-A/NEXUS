"""Wygasłe zgody jednorazowe bez dokumentu — przywrócenie (23.10.2026).

Do 22.10.2026 `settlement.expire_stale` zamykał po 30 dniach bez faktury
i paragonu także zgodę na wydatek „raz” (rozliczenie ``expired``, dzwonek
„Zgoda wygasła”). Od audytu 22.10 (F21) taka zgoda nie wygasa: delegacja czy
szkolenie rozliczają się rachunkiem po wydarzeniu. Decyzja Artura z 23.10.2026:
zgody, które zdążyły wygasnąć według starej reguły, wracają do stanu sprzed
wygaśnięcia. Kod reguły zmienia F21; ten skrypt naprawia dane.

Najpierw liczby (tylko odczyt): ``backend/scripts/hr_one_off_expired_report.sql``.

Uruchomienie na produkcji — po wdrożeniu F21 i po zgodzie Artura, na serwerze
(nazwa kontenera zmienia się po każdym wdrożeniu)::

    B=$(docker ps --format '{{.Names}}' | grep '^backend-ocgkw' | head -1)
    docker exec -i -w /app "$B" python -m app.cli.hr_one_off_expiry_restore
    docker exec -i -w /app "$B" python -m app.cli.hr_one_off_expiry_restore \\
        --apply --expected <restorable z próby>

Zasady:

* wybór: zgoda zatwierdzona (``status = 'approved'``), wydatek (nie premia),
  ``recurrence = 'once'``, rozliczenie ``expired``. Stan ``expired`` ustawia
  wyłącznie `expire_stale`, a ten zapisuje w ``hr_audit_events`` zdarzenie
  ``approval_expired`` — z niego jest miesiąc wygaśnięcia (czas firmy).
  Zgoda ``expired`` bez takiego zdarzenia (ktoś zmienił stan ręcznie)
  zostaje bez zmian i trafia do raportu;
* stan sprzed wygaśnięcia to ``open`` („czeka na fakturę”): `on_approved`
  daje zgodzie „raz” ``open``, a `expire_stale` brał tylko zgody bez
  dołączonego dokumentu. Zgoda, która ma dziś dołączony dokument (``pinned``
  albo ``settled``), zostaje bez zmian i trafia do raportu — to już nie jest
  „bez dokumentu”;
* ``expires_on`` = NULL jak w F21 (zgoda „raz” nie ma terminu). Osobnej daty
  wygaśnięcia model nie ma — jest tylko zdarzenie w historii, które zostaje;
* każda przywrócona zgoda dostaje w historii (``hr_audit_events``) zdarzenie
  ``approval_expiry_reverted`` (z jakiego stanu, na jaki, skasowany termin).
  Autor nie dostaje dzwonka — zgoda po prostu znowu czeka na fakturę;
* ``--apply`` wymaga ``--expected`` równego ``restorable`` z próby na sucho.
  Bieg idzie w jednej transakcji pod blokadą doradczą: inny stan bazy niż
  w próbie przerywa go przed pierwszym zapisem. Paragon
  ``app_settings['hr_one_off_expiry_restore_2026_10']`` niesie same liczby
  i id; drugie ``--apply`` przy paragonie jest odrzucane. Raport bez nazwisk,
  tytułów, celów i kwot (logi Actions są publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import String, cast, exists, func, select, text, update

logger = logging.getLogger(__name__)

RECEIPT_KEY = "hr_one_off_expiry_restore_2026_10"
#: Stan rozliczenia zgody „raz” bez dokumentu — ten sam co po zatwierdzeniu.
RESTORED_STATUS = "open"
#: Zdarzenie, które `settlement.expire_stale` zapisuje przy wygaśnięciu.
EXPIRED_ACTION = "approval_expired"
RESTORED_ACTION = "approval_expiry_reverted"


class StateChanged(Exception):
    """Od planu do zapisu zmienił się stan zgód — bieg przerwany."""


@dataclass(frozen=True)
class Item:
    request_id: int
    # Miesiąc ostatniego `approval_expired` (czas firmy, „RRRR-MM”).
    expired_month: Optional[str]
    has_expiry_event: bool
    has_document: bool

    @property
    def restorable(self) -> bool:
        return self.has_expiry_event and not self.has_document


def _selection():
    from app.models.hr_approval import ApprovalRequest

    return (
        ApprovalRequest.status == "approved",
        ApprovalRequest.kind != "bonus",
        ApprovalRequest.recurrence == "once",
        ApprovalRequest.settlement_status == "expired",
    )


async def plan(db, *, request_ids: Optional[list[int]] = None) -> list[Item]:
    """Wygasłe zgody „raz”. ``request_ids`` zawęża bieg (testy na wspólnej bazie)."""
    from app.core.scheduling import business_date
    from app.models.hr_approval import ApprovalDocument, ApprovalRequest
    from app.models.hr_ops import HrAuditEvent
    from app.services.hr_approval_settlement_schema import ATTACHED_STATUSES

    expired_at = (
        select(func.max(HrAuditEvent.created_at))
        .where(
            HrAuditEvent.entity_type == "approval_request",
            HrAuditEvent.entity_id == cast(ApprovalRequest.id, String),
            HrAuditEvent.action == EXPIRED_ACTION,
        )
        .correlate(ApprovalRequest)
        .scalar_subquery()
    )
    has_doc = (
        exists()
        .where(
            ApprovalDocument.approval_request_id == ApprovalRequest.id,
            ApprovalDocument.status.in_(ATTACHED_STATUSES),
        )
        .correlate(ApprovalRequest)
    )
    query = select(ApprovalRequest.id, expired_at, has_doc).where(*_selection())
    if request_ids is not None:
        query = query.where(ApprovalRequest.id.in_(request_ids))
    return [
        Item(
            request_id=request_id,
            expired_month=(
                business_date(at).strftime("%Y-%m") if at is not None else None
            ),
            has_expiry_event=at is not None,
            has_document=bool(doc),
        )
        for request_id, at, doc in (
            await db.execute(query.order_by(ApprovalRequest.id))
        ).all()
    ]


def summarize(items: list[Item]) -> dict[str, Any]:
    ready = [item for item in items if item.restorable]
    return {
        "found": len(items),
        "restorable": len(ready),
        "restorable_by_expiry_month": dict(
            sorted(Counter(item.expired_month for item in ready).items())
        ),
        # Same identyfikatory — bez nazwisk, tytułów i kwot (logi są publiczne).
        "request_ids": sorted(item.request_id for item in ready),
        "skipped_with_document": sorted(
            item.request_id
            for item in items
            if item.has_expiry_event and item.has_document
        ),
        "skipped_without_expiry_event": sorted(
            item.request_id for item in items if not item.has_expiry_event
        ),
    }


async def restore(db, items: list[Item]) -> list[int]:
    """Przywraca zgody z planu w bieżącej transakcji; bez commitu."""
    from app.models.hr_approval import ApprovalRequest
    from app.services.hr import audit

    ids = sorted(item.request_id for item in items if item.restorable)
    if not ids:
        return []
    rows = (
        await db.execute(
            select(
                ApprovalRequest.id,
                ApprovalRequest.requester_user_id,
                ApprovalRequest.expires_on,
            )
            .where(ApprovalRequest.id.in_(ids), *_selection())
            .order_by(ApprovalRequest.id)
            .with_for_update()
        )
    ).all()
    if [row.id for row in rows] != ids:
        raise StateChanged
    await db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id.in_(ids))
        .values(
            settlement_status=RESTORED_STATUS, expires_on=None, updated_at=func.now()
        )
        .execution_options(synchronize_session=False)
    )
    for request_id, requester_id, expires_on in rows:
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=requester_id,
            entity_type="approval_request",
            entity_id=request_id,
            action=RESTORED_ACTION,
            details={
                "from": "expired",
                "to": RESTORED_STATUS,
                "expires_on_cleared": (
                    expires_on.isoformat() if expires_on is not None else None
                ),
                "reason": "zgoda jednorazowa bez dokumentu nie wygasa (F21)",
            },
        )
    await db.flush()
    return ids


async def _receipt_exists(db) -> bool:
    return bool(
        await db.scalar(
            text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": RECEIPT_KEY}
        )
    )


async def _write_receipt(db, payload: dict[str, Any]) -> None:
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, CAST(:v AS jsonb), NOW())
            """
        ),
        {"k": RECEIPT_KEY, "v": json.dumps(payload)},
    )


async def main(
    argv: Optional[list[str]] = None,
    *,
    request_ids: Optional[list[int]] = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--expected",
        type=int,
        help="liczba zgód do przywrócenia z próby na sucho (wymagana z --apply)",
    )
    args = parser.parse_args(argv)
    if args.apply and args.expected is None:
        print("--apply wymaga --expected z próby na sucho.", file=sys.stderr)
        return 2

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        if args.apply:
            # Dwa równoległe biegi nie przejdą obok siebie przez paragon.
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": RECEIPT_KEY},
            )
        receipt_exists = await _receipt_exists(db)
        items = await plan(db, request_ids=request_ids)
        report = summarize(items)
        print(json.dumps({"plan": report, "receipt": receipt_exists}))
        if not args.apply:
            print(
                "Na sucho — nic nie zmieniono. Dodaj --apply --expected "
                f"{report['restorable']}."
            )
            return 0
        if receipt_exists:
            print(f"Paragon {RECEIPT_KEY} już jest — przerywam.", file=sys.stderr)
            return 2
        if args.expected != report["restorable"]:
            print(
                f"Stan bazy różni się od próby: {report['restorable']} zgód, "
                f"oczekiwano {args.expected} — przerywam.",
                file=sys.stderr,
            )
            return 2
        try:
            restored = await restore(db, items)
        except StateChanged:
            await db.rollback()
            print("Zgody zmieniły się w trakcie biegu — przerywam.", file=sys.stderr)
            return 2
        receipt = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "restored": len(restored),
            "request_ids": restored,
            "restored_by_expiry_month": report["restorable_by_expiry_month"],
            "skipped_with_document": report["skipped_with_document"],
            "skipped_without_expiry_event": report["skipped_without_expiry_event"],
        }
        await _write_receipt(db, receipt)
        await db.commit()
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
