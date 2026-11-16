"""Umowy ramowe z duplikatów klientów na rekord docelowy (decyzja Artura 16.11.2026).

Manifest portfela klientów (``client_excel``) założył umowy ramowe na
rekordach ``portfolio:*``, które potem scalono w klienta z Traffita.
Scalenie (``POST /api/clients/{id}/merge-into/{target}``) nie przenosiło
umów, więc leżały na ukrytym wierszu: karta klienta docelowego, wyszukiwanie
umów (Jarvis), katalog raportów, „Moi klienci” i wybór umowy w zamówieniach
czytają je po ``client_id`` celu i ich nie widziały. Dwa duplikaty bez
flagi scalenia (Santander → ERSTE, NBP) mają ten sam problem.

Korekta przepina ``client_id`` umów z listy; aneksy i fragmenty treści idą
za umową kluczem obcym, a punkty w Qdrancie niosą tylko id umowy (id punktu
= id fragmentu), więc wektory zostają. Wiersz importu i zakres portfela
zostają na duplikacie (``scalenie-cardif-pelne-przeniesienie-danych.md``),
a inwariant manifestu w ``/api/health/deep`` uznaje przeniesioną umowę
(``reassigned_manifest_contracts``).

Druga umowa Aliora (ten sam PDF wgrany ręcznie na klienta docelowego,
bez aneksów i odwołań) zostaje usunięta, bo po przeniesieniu byłaby
duplikatem z podwójnymi fragmentami. Plik i wektory sprząta wołający
po commicie.

Inny stan niż z decyzji = pominięcie z kodem powodu. Paragon pod
``REPAIR_MARKER`` niesie wyłącznie ID i kody.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, NamedTuple, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_directory import ClientImportRow, ClientPortfolioScope
from app.models.client_executive_contract import ClientExecutiveContract
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.client_order import ClientOrder
from app.models.document_signature import DocumentSignature

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0721_framework_contract_owner_repair"
SOURCE = REPAIR_MARKER
PORTFOLIO_SOURCE_SYSTEM = "client_excel"


class Move(NamedTuple):
    framework_contract_id: int
    from_client_id: int
    to_client_id: int
    source_key: str


class DuplicateDrop(NamedTuple):
    """Umowa-duplikat na kliencie docelowym; ``kept_id`` ma ten sam plik."""

    framework_contract_id: int
    client_id: int
    kept_id: int


# Kopia produkcji z 15.11.2026: umowa ramowa z manifestu na duplikacie →
# klient, na którym pracuje zespół.
TICKET_MOVES: tuple[Move, ...] = (
    Move(30, 38342, 116, "active:credit-agricole"),
    Move(10, 38337, 13, "active:ergo"),
    Move(16, 38338, 106, "active:nationale"),
    Move(6, 38334, 58, "active:bnp-cib"),
    Move(2, 38333, 39, "active:alior"),
    Move(9, 38336, 103, "active:santander"),
    Move(33, 38345, 141, "inactive:narodowy-bank-polski"),
)

TICKET_DROPS: tuple[DuplicateDrop, ...] = (DuplicateDrop(41, 39, 2),)


def reassigned_manifest_contracts(
    moves: tuple[Move, ...] = TICKET_MOVES,
) -> tuple[tuple[int, int, int], ...]:
    """(umowa, klient z wiersza importu, klient po korekcie) dla inwariantu manifestu."""

    return tuple(
        (m.framework_contract_id, m.from_client_id, m.to_client_id) for m in moves
    )


def _target_is_open(client: Optional[Client]) -> bool:
    return (
        client is not None
        and client.merged_into_client_id is None
        and client.archived_at is None
        and client.deleted_at is None
    )


async def _move_one(db: AsyncSession, move: Move) -> dict[str, Any]:
    result: dict[str, Any] = {"fc_id": move.framework_contract_id, "skipped": None}
    fc = await db.scalar(
        select(ClientFrameworkContract)
        .where(ClientFrameworkContract.id == move.framework_contract_id)
        .with_for_update()
    )
    if (
        fc is None
        or fc.source_system != PORTFOLIO_SOURCE_SYSTEM
        or fc.source_key != move.source_key
    ):
        result["skipped"] = "identity_mismatch"
        return result
    if fc.client_id == move.to_client_id:
        result["skipped"] = "already_moved"
        return result
    if fc.client_id != move.from_client_id:
        result["skipped"] = "other_client"
        return result
    target = await db.get(Client, move.to_client_id)
    if not _target_is_open(target):
        result["skipped"] = "target_not_open"
        return result
    if fc.project_part is not None:
        # Część umowy (CeZ) jest unikalna per klient — nie przepinamy na ślepo.
        result["skipped"] = "project_part"
        return result

    fc.client_id = move.to_client_id
    for entity_id, role in ((move.from_client_id, "from"), (move.to_client_id, "to")):
        db.add(
            Activity(
                entity_type="client",
                entity_id=entity_id,
                action="framework_contract_reassigned",
                user_id=None,
                external_source=SOURCE,
                external_id=f"move:{fc.id}:{role}",
                details={
                    "fc_id": fc.id,
                    "from_client_id": move.from_client_id,
                    "to_client_id": move.to_client_id,
                    "source": SOURCE,
                },
            )
        )
    await db.flush()
    return result


async def _references(db: AsyncSession, fc_id: int) -> int:
    """Wszystko, co wskazuje na umowę i zniknęłoby albo straciło powiązanie."""

    from app.models.client_report import ClientReportDefinition

    checks = (
        select(func.count(ClientOrder.id)).where(
            ClientOrder.framework_contract_id == fc_id
        ),
        select(func.count(ClientExecutiveContract.id)).where(
            ClientExecutiveContract.framework_contract_id == fc_id
        ),
        select(func.count(ClientContractAmendment.id)).where(
            ClientContractAmendment.framework_contract_id == fc_id
        ),
        select(func.count(ClientPortfolioScope.id)).where(
            ClientPortfolioScope.framework_contract_id == fc_id
        ),
        select(func.count(ClientImportRow.id)).where(
            ClientImportRow.framework_contract_id == fc_id
        ),
        select(func.count(ClientReportDefinition.id)).where(
            ClientReportDefinition.source_contract_id == fc_id
        ),
        select(func.count(DocumentSignature.id)).where(
            DocumentSignature.client_framework_contract_id == fc_id
        ),
        select(func.count(ClientFrameworkContract.id)).where(
            ClientFrameworkContract.parent_contract_id == fc_id
        ),
    )
    total = 0
    for statement in checks:
        total += int(await db.scalar(statement) or 0)
    return total


async def _drop_one(db: AsyncSession, drop: DuplicateDrop) -> dict[str, Any]:
    result: dict[str, Any] = {
        "fc_id": drop.framework_contract_id,
        "skipped": None,
        "file_path": None,
    }
    fc = await db.scalar(
        select(ClientFrameworkContract)
        .where(ClientFrameworkContract.id == drop.framework_contract_id)
        .with_for_update()
    )
    kept = await db.get(ClientFrameworkContract, drop.kept_id)
    if fc is None:
        result["skipped"] = "already_dropped"
        return result
    if (
        fc.client_id != drop.client_id
        or fc.source_system == PORTFOLIO_SOURCE_SYSTEM
        or kept is None
    ):
        result["skipped"] = "identity_mismatch"
        return result
    if kept.client_id != drop.client_id:
        # Bez przeniesionej umowy usunięcie zostawiłoby klienta bez umowy.
        result["skipped"] = "kept_not_on_client"
        return result
    if (
        not fc.file_path
        or fc.size_bytes != kept.size_bytes
        or fc.filename != kept.filename
        or fc.effective_date != kept.effective_date
        or fc.expiry_date != kept.expiry_date
    ):
        result["skipped"] = "not_the_same_document"
        return result
    if await _references(db, fc.id):
        result["skipped"] = "referenced"
        return result

    result["file_path"] = fc.file_path
    db.add(
        Activity(
            entity_type="client",
            entity_id=drop.client_id,
            action="framework_contract_deleted",
            user_id=None,
            external_source=SOURCE,
            external_id=f"drop:{fc.id}",
            details={
                "fc_id": fc.id,
                "hard_delete": True,
                "duplicate_of_fc_id": kept.id,
                "source": SOURCE,
            },
        )
    )
    await db.delete(fc)
    await db.flush()
    return result


async def run_framework_contract_owner_repair(
    db: AsyncSession,
    *,
    moves: tuple[Move, ...] = TICKET_MOVES,
    drops: tuple[DuplicateDrop, ...] = TICKET_DROPS,
    marker: str = REPAIR_MARKER,
) -> Optional[dict[str, Any]]:
    """Przenieś umowy z listy i usuń duplikat. ``None`` = już było. Wołający commituje.

    Ścieżki plików usuniętych umów są w ``summary['dropped_file_paths']`` —
    plik i punkty w Qdrancie kasuje wołający PO commicie.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    if await db.get(AppSetting, marker) is not None:
        return None

    moved = [await _move_one(db, move) for move in moves]
    dropped = [await _drop_one(db, drop) for drop in drops]
    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested_moves": len(moves),
        "moved_fc_ids": [r["fc_id"] for r in moved if r["skipped"] is None],
        "moves": [
            {
                "fc_id": m.framework_contract_id,
                "from": m.from_client_id,
                "to": m.to_client_id,
            }
            for m, r in zip(moves, moved)
            if r["skipped"] is None
        ],
        "dropped_fc_ids": [r["fc_id"] for r in dropped if r["skipped"] is None],
        "skipped": [
            {"fc_id": r["fc_id"], "reason": r["skipped"]}
            for r in (*moved, *dropped)
            if r["skipped"] is not None
        ],
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    summary = {
        **summary,
        "dropped_file_paths": [
            r["file_path"] for r in dropped if r["skipped"] is None and r["file_path"]
        ],
    }
    logger.info(
        "framework contract owner repair: moved %s/%s, dropped %s",
        len(summary["moved_fc_ids"]),
        len(moves),
        len(summary["dropped_fc_ids"]),
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    skipped = ", ".join(
        f"{item['fc_id']}:{item['reason']}" for item in summary["skipped"]
    )
    return f"moved {summary['moved_fc_ids']}; dropped {summary['dropped_fc_ids']}" + (
        f"; skipped {skipped}" if skipped else ""
    )
