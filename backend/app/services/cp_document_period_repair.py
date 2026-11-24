"""Jednorazowa poprawka okresu dokumentu rozliczeń z nazwą pliku w NFD.

Nazwy plików z Maca przychodzą rozłożone (NFD: litera i osobny akcent). Przed
#3866 ``consultant_portal/mailbox.find_period`` nie łapał w takiej nazwie miesiąca
słownie, więc okres brał się z tematu wątku. Czytnik poczty na produkcji (od
19.11.2026) zapisał tak jeden dokument: Time Sheet ERSTE za październik, który
przyszedł w wątku „wrzesień”, dostał wrzesień 2026. Odczyt produkcji z 24.11.2026:
to jedyny plik z akcentem rozłożonym w ``cp_documents``. Rozliczenie IX liczyło się
z pliku za X, a rozliczenia X nie było.

Decyzja Artura z 24.11.2026: naprawa danych w PR-ze. Dokument jest przypięty do
ID, kontraktu, rodzaju, początku skrótu pliku i okresu sprzed naprawy. Nowy okres
musi wynikać z nazwy pliku po NFC, a dokumentu nikt jeszcze nie przyjął ani nie
odrzucił. Rozliczenie starego miesiąca przyjęte albo „Do poprawy” to decyzja
człowieka: wtedy dokument zostaje, jak jest. Każdy inny stan to pominięcie z kodem
powodu. Po zmianie okresu MD, które stary miesiąc odczytał z tego pliku, wracają do
pustych i stary miesiąc liczy się od nowa, a nowy tak, jak czytnik po nowym pliku
(``service.refresh_for_document``). Paragon pod ``REPAIR_MARKER`` niesie wyłącznie
ID, okresy i statusy: bez nazw plików, nazwisk i kwot.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import datetime, timezone
from typing import Any, NamedTuple, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.client_settlement import ClientSettlement
from app.models.consultant_portal import CpDocument
from app.services.client_settlements import service as settlements
from app.services.consultant_portal.mailbox import find_period

logger = logging.getLogger(__name__)

REPAIR_MARKER = "cp_document_nfd_period_repair_2026_11_24"

# Decyzja Finansów o rozliczeniu miesiąca: naprawa jej nie zmienia.
DECIDED_STATUSES = frozenset({"accepted", "needs_fix"})


class Target(NamedTuple):
    document_id: int
    contract_id: int
    kind: str
    sha256_prefix: str
    old_period: tuple[int, int]
    new_period: tuple[int, int]


# Stan produkcji z 24.11.2026 (odczyt tylko do odczytu, zgoda Artura).
ERSTE_TIME_SHEET_X = Target(11, 619, "report", "bbf003bfea50", (2026, 9), (2026, 10))
TARGETS: tuple[Target, ...] = (ERSTE_TIME_SHEET_X,)


def month_key(period: tuple[int, int]) -> str:
    return f"{period[0]}-{period[1]:02d}"


def period_from_nfd_name(file_name: Optional[str]) -> Optional[tuple[int, int]]:
    """Okres z nazwy pliku tylko wtedy, gdy nazwa jest rozłożona (nie w NFC)."""

    name = file_name or ""
    composed = unicodedata.normalize("NFC", name)
    if composed == name:
        return None
    return find_period(composed)


async def _month_settlements(
    db: AsyncSession, contract_id: int, month: str
) -> list[ClientSettlement]:
    return list(
        (
            await db.scalars(
                select(ClientSettlement)
                .where(
                    ClientSettlement.contract_id == contract_id,
                    ClientSettlement.period_month == month,
                )
                .order_by(ClientSettlement.kind)
                .with_for_update()
            )
        ).all()
    )


def _settlement_row(
    s: ClientSettlement, before: Optional[str], *, md_cleared: bool = False
) -> dict[str, Any]:
    return {
        "id": s.id,
        "kind": s.kind,
        "status_before": before,
        "status_after": s.status,
        "report_document_id": s.report_document_id,
        "md_cleared": md_cleared,
    }


async def _locked_document(
    db: AsyncSession, target: Target
) -> tuple[Optional[CpDocument], Optional[str]]:
    document = await db.scalar(
        select(CpDocument).where(CpDocument.id == target.document_id).with_for_update()
    )
    if document is None:
        return None, "document_missing"
    if (
        document.contract_id != target.contract_id
        or document.kind != target.kind
        or not document.sha256.startswith(target.sha256_prefix)
    ):
        return None, "identity_mismatch"
    period = (document.period_year, document.period_month)
    if period == target.new_period:
        return None, "already_fixed"
    if period != target.old_period:
        return None, "period_changed"
    if document.status != "received":
        # Przyjęty albo odrzucony (np. „Do poprawy”) zostaje przy decyzji człowieka.
        return None, "document_decided"
    if period_from_nfd_name(document.file_name) != target.new_period:
        return None, "name_period_mismatch"
    twin = await db.scalar(
        select(CpDocument.id).where(
            CpDocument.id != document.id,
            CpDocument.contract_id == document.contract_id,
            CpDocument.kind == document.kind,
            CpDocument.sha256 == document.sha256,
            CpDocument.period_year == target.new_period[0],
            CpDocument.period_month == target.new_period[1],
        )
    )
    if twin is not None:
        return None, "duplicate_in_new_period"
    return document, None


async def _fix_document(
    db: AsyncSession, target: Target, *, now: datetime
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "document_id": target.document_id,
        "contract_id": target.contract_id,
        "old_period": month_key(target.old_period),
        "new_period": month_key(target.new_period),
        "skipped": None,
        "old_month": [],
        "new_month": [],
    }
    document, skipped = await _locked_document(db, target)
    if document is None:
        result["skipped"] = skipped
        return result
    old_month = await _month_settlements(
        db, target.contract_id, month_key(target.old_period)
    )
    if any(s.status in DECIDED_STATUSES for s in old_month):
        result["skipped"] = "old_month_decided"
        return result
    document.period_year, document.period_month = target.new_period
    document.updated_at = now
    await db.flush()
    for s in old_month:
        before = s.status
        # MD odczytane z tego pliku należą do nowego miesiąca; wpis Finansów zostaje.
        cleared = s.report_document_id == document.id and s.md_source == "rcp"
        if cleared:
            s.md_regular = s.md_extra = s.md_source = None
        await settlements.recompute_and_store(db, s)
        result["old_month"].append(_settlement_row(s, before, md_cleared=cleared))
    await settlements.refresh_for_document(db, document)
    await db.flush()
    for s in await _month_settlements(
        db, target.contract_id, month_key(target.new_period)
    ):
        result["new_month"].append(_settlement_row(s, None))
    return result


async def run_cp_document_period_repair(
    db: AsyncSession,
    *,
    targets: tuple[Target, ...] = TARGETS,
    marker: str = REPAIR_MARKER,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Popraw okres dokumentów i przelicz rozliczenia; ``None`` = już wykonane.
    Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    moment = now or datetime.now(timezone.utc)
    results = [await _fix_document(db, target, now=moment) for target in targets]
    summary = {
        "executed_at": moment.isoformat(),
        "requested": len(results),
        "fixed": sum(1 for r in results if r["skipped"] is None),
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info(
        "cp document period repair: %s/%s", summary["fixed"], summary["requested"]
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    parts = [f"fixed {summary['fixed']}/{summary['requested']}"]
    for r in summary["results"]:
        if r["skipped"] is not None:
            parts.append(f"document {r['document_id']}: skipped {r['skipped']}")
            continue
        old = ", ".join(
            f"#{s['id']} {s['status_before']}->{s['status_after']}"
            for s in r["old_month"]
        )
        new = ", ".join(f"#{s['id']} {s['status_after']}" for s in r["new_month"])
        parts.append(
            f"document {r['document_id']}: {r['old_period']}->{r['new_period']}"
            f"; {r['old_period']} [{old or 'none'}]; {r['new_period']} [{new or 'none'}]"
        )
    return "; ".join(parts)
