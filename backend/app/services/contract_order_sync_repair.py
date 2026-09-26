"""Jednorazowo przy wdrożeniu synchronizacji kontrakt ↔ zamówienia (09.2026).

Dwie rzeczy, w tej kolejności — i kolejność jest cała istotą tego modułu:

1. **Migawka raportu zgodności** (ticket, punkt 9): dla każdego bieżącego
   zamówienia — osoba, stawki w zamówieniu i w kontrakcie z jednostkami, okres
   w zamówieniu i w kontrakcie. Zapisywana PRZED jakąkolwiek synchronizacją,
   bo raport ma pokazać niezgodności SPRZED wdrożenia, a codzienny przebieg
   kosztowy i korekta szkiców zatarłyby je w ciągu doby.
2. **Korekta szkiców** (punkt 8): każdy kontrakt w statusie ``draft``
   przechodzi na ``active``. Jeśli osoba ma uzupełnione zamówienie, kontrakt
   dostaje okres zamówienia i stawkę przychodową (w jednostce zamówienia,
   z przeliczeniem stawki kosztowej 1 MD = 8 h); jeśli nie ma — sam status,
   reszta dojdzie przy uzupełnieniu zamówienia.

Blok jest jednorazowy (marker w ``app_settings`` + advisory lock) i odpalany
z ``entrypoint.sh``. Paragon (``app_settings[REPAIR_MARKER]``) niesie
wyłącznie liczniki i ID. Migawka raportu i stan KAŻDEGO poprawionego kontraktu
sprzed korekty (nazwiska, klienci, stawki) leżą pod ``DETAILS_KEY`` — z nich
da się odtworzyć, co zmieniono, i z nich powstaje plik Excel
(``GET /api/contracts/order-sync-report``). Runda 7 (R7-X2-1): do 26.09.2026
całość szła pod kluczem paragonu, a workflow „migration-receipts” drukuje
paragony w publicznym logu Actions.
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.export_safety import safe_cell
from app.core.scheduling import business_today
from app.core.work_time import HOURS_PER_MONTH
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.client_identity import client_display_name
from app.services.contract_lifecycle import (
    DRAFT_REPAIR_ACTIVATION,
    activate_without_revenue_gate,
    end_expired_draft,
)
from app.services.contract_order_sync import (
    REPAIR_DETAILS_KEY,
    REPAIR_MARKER,
    convert_rate_between,
    cost_reference_day,
    resync_contract,
)
from app.services.contract_rates import RATE_SCHEDULE_LOADS

logger = logging.getLogger(__name__)

_TOLERANCE = Decimal("0.01")
_UNIT_LABEL = {
    RateUnit.hourly.value: "h",
    RateUnit.daily.value: "MD",
    RateUnit.monthly.value: "mc",
}
_STATUS_LABEL = {
    "draft": "Szkic",
    "ready_for_signature": "Do podpisu",
    "active": "Aktywny",
    "ending": "Kończący się",
    "ended": "Zakończony",
    "void": "Anulowany",
}
_ORDER_STATUS_LABEL = {
    "draft": "Szkic",
    "active": "Aktywne",
    "paused": "Wstrzymane",
    "completed": "Zakończone",
    "cancelled": "Anulowane",
}
MATCH = "zgodne"
MISMATCH = "NIEZGODNE"
NO_DATA = "brak danych"
NOT_IN_CONTRACT = "brak w kontrakcie"


# ── Wiersze raportu ──────────────────────────────────────────────────────────


def _num(value: object) -> Optional[str]:
    if value is None:
        return None
    return str(value if isinstance(value, Decimal) else Decimal(str(value)))


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def _compare(left: Optional[Decimal], right: Optional[Decimal]) -> str:
    if left is None or right is None:
        return NO_DATA
    return MATCH if abs(left - right) <= _TOLERANCE else MISMATCH


def _order_side(order: ClientOrder) -> dict[str, Any]:
    """Stawki zamówienia w jego własnej jednostce i walucie."""
    if order.order_group_id is not None:
        revenue = order.rate_client
        revenue_currency = order.rate_client_currency or order.currency or "PLN"
        if revenue is None and order.md_rate_revenue is not None:
            revenue, revenue_currency = order.md_rate_revenue, "PLN"
        cost = order.rate_candidate
        cost_currency = order.rate_candidate_currency or "PLN"
        if cost is None and order.md_rate_cost is not None:
            cost, cost_currency = order.md_rate_cost, "PLN"
        unit = RateUnit.daily
    else:
        revenue = order.rate_client
        revenue_currency = order.rate_client_currency or order.currency or "PLN"
        cost = order.rate_candidate
        cost_currency = order.rate_candidate_currency or "PLN"
        unit = RateUnit(order.rate_unit)
    return {
        "unit": unit,
        "cost": None if cost is None else Decimal(str(cost)),
        "cost_currency": str(cost_currency).upper(),
        "revenue": None if revenue is None else Decimal(str(revenue)),
        "revenue_currency": str(revenue_currency).upper(),
    }


def reconciliation_row(
    order: ClientOrder,
    contract: Contract,
    *,
    candidate_name: str,
    client_name: str,
    is_latest: bool,
    today: date,
) -> dict[str, Any]:
    """Jeden wiersz zestawienia: zamówienie obok swojego kontraktu.

    Kontrakt jest wyceniany z harmonogramów (nie z kolumn-cache) i przeliczany
    na jednostkę zamówienia — porównanie 120 zł/h z 960 zł/MD to zgodność,
    nie różnica. Waluty różne = „brak danych": porównanie bez kursu kłamie.
    """
    side = _order_side(order)
    unit: RateUnit = side["unit"]
    contract_unit = RateUnit(contract.rate_unit)
    contract_hours = contract.billing_hours_per_month or HOURS_PER_MONTH
    order_hours = order.billing_hours_per_month or HOURS_PER_MONTH
    cost_day = cost_reference_day(order, today)
    revenue_day = order.start_date or cost_day

    contract_cost = contract.effective_candidate_rate(cost_day)
    contract_revenue = contract.effective_client_rate(revenue_day)
    cost_in_order_unit = convert_rate_between(
        contract_cost,
        contract_unit,
        unit,
        from_hours=contract_hours,
        to_hours=order_hours,
    )
    revenue_in_order_unit = convert_rate_between(
        contract_revenue,
        contract_unit,
        unit,
        from_hours=contract_hours,
        to_hours=order_hours,
    )
    cost_status = (
        _compare(side["cost"], cost_in_order_unit)
        if side["cost_currency"] == contract.resolved_rate_candidate_currency
        else NO_DATA
    )
    revenue_status = (
        _compare(side["revenue"], revenue_in_order_unit)
        if side["revenue_currency"] == contract.resolved_rate_client_currency
        else NO_DATA
    )
    # Okres porównujemy tylko dla NAJNOWSZEGO zamówienia — kontrakt niesie
    # jeden okres zamówienia, więc starsze zamówienia różnią się z definicji.
    # Przed wdrożeniem kontrakt znał co najwyżej koniec zamówienia
    # (``client_order_end_date``); brak pola to brak synchronizacji, a nie
    # sprzeczne dane — stąd osobny stan.
    if not is_latest:
        period_status = "—"
    elif order.start_date is None and order.end_date is None:
        period_status = NO_DATA
    elif (
        contract.client_order_start_date is None
        and contract.client_order_end_date is None
    ):
        period_status = NOT_IN_CONTRACT
    elif contract.client_order_start_date is None:
        period_status = (
            MATCH if contract.client_order_end_date == order.end_date else MISMATCH
        )
    else:
        period_status = (
            MATCH
            if (contract.client_order_start_date, contract.client_order_end_date)
            == (order.start_date, order.end_date)
            else MISMATCH
        )
    return {
        "contract_id": contract.id,
        "contract_status": contract.status.value,
        "candidate_name": candidate_name,
        "client_name": client_name,
        "order_id": order.id,
        "order_number": order.title,
        "order_kind": (
            "linia zamówienia grupowego"
            if order.order_group_id is not None
            else "zamówienie okresowe"
        ),
        "order_status": ClientOrderStatus(order.status).value,
        "is_latest_order": is_latest,
        "order_cost": _num(side["cost"]),
        "order_cost_unit": unit.value,
        "order_cost_currency": side["cost_currency"],
        "contract_cost": _num(contract_cost),
        "contract_cost_unit": contract_unit.value,
        "contract_cost_currency": contract.resolved_rate_candidate_currency,
        "contract_cost_in_order_unit": _num(cost_in_order_unit),
        "cost_status": cost_status,
        "order_revenue": _num(side["revenue"]),
        "order_revenue_unit": unit.value,
        "order_revenue_currency": side["revenue_currency"],
        "contract_revenue": _num(contract_revenue),
        "contract_revenue_unit": contract_unit.value,
        "contract_revenue_currency": contract.resolved_rate_client_currency,
        "contract_revenue_in_order_unit": _num(revenue_in_order_unit),
        "revenue_status": revenue_status,
        "order_start": _iso(order.start_date),
        "order_end": _iso(order.end_date),
        "contract_order_start": _iso(contract.client_order_start_date),
        "contract_order_end": _iso(contract.client_order_end_date),
        "contract_start": _iso(contract.start_date),
        "contract_end": _iso(contract.end_date),
        "period_status": period_status,
    }


async def build_reconciliation_rows(
    db: AsyncSession, *, today: Optional[date] = None
) -> list[dict[str, Any]]:
    """Zestawienie dla OBECNYCH rekordów: każde nieanulowane zamówienie."""
    today = today or business_today()
    pairs = (
        await db.execute(
            select(ClientOrder, Contract.id)
            .join(Contract, Contract.id == ClientOrder.contract_id)
            .where(
                ClientOrder.status != ClientOrderStatus.cancelled,
                ClientOrder.client_id == Contract.client_id,
                Contract.status != ContractStatus.void,
            )
            .order_by(Contract.id, ClientOrder.start_date.nullsfirst(), ClientOrder.id)
        )
    ).all()
    if not pairs:
        return []
    contract_ids = sorted({contract_id for _, contract_id in pairs})
    contracts: dict[int, Contract] = {}
    for offset in range(0, len(contract_ids), 500):
        batch = contract_ids[offset : offset + 500]
        for contract in (
            await db.scalars(
                select(Contract)
                .where(Contract.id.in_(batch))
                .options(*RATE_SCHEDULE_LOADS)
            )
        ).all():
            contracts[contract.id] = contract
    candidate_names = {
        row.id: f"{row.name or ''} {row.lastname or ''}".strip()
        for row in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_(
                        {c.candidate_id for c in contracts.values() if c.candidate_id}
                    )
                )
            )
        ).all()
    }
    client_names = {
        client.id: client_display_name(client)
        for client in (
            await db.scalars(
                select(Client).where(
                    Client.id.in_({c.client_id for c in contracts.values()})
                )
            )
        ).all()
    }
    orders_by_contract: dict[int, list[ClientOrder]] = {}
    for order, contract_id in pairs:
        orders_by_contract.setdefault(contract_id, []).append(order)

    rows: list[dict[str, Any]] = []
    for contract_id in contract_ids:
        contract = contracts[contract_id]
        orders = orders_by_contract[contract_id]
        dated = [o for o in orders if o.start_date is not None]
        latest_id = max(dated, key=lambda o: (o.start_date, o.id)).id if dated else None
        for order in orders:
            rows.append(
                reconciliation_row(
                    order,
                    contract,
                    candidate_name=candidate_names.get(contract.candidate_id, "")
                    or "(osoba usunięta)",
                    client_name=client_names.get(contract.client_id, ""),
                    is_latest=order.id == latest_id,
                    today=today,
                )
            )
    return rows


# ── Korekta szkiców ──────────────────────────────────────────────────────────


def _contract_state(contract: Contract) -> dict[str, Any]:
    return {
        "status": contract.status.value,
        "rate_unit": RateUnit(contract.rate_unit).value,
        "rate_candidate": _num(contract.rate_candidate),
        "rate_client": _num(contract.rate_client),
        "rate_client_currency": contract.resolved_rate_client_currency,
        "client_order_start_date": _iso(contract.client_order_start_date),
        "client_order_end_date": _iso(contract.client_order_end_date),
        "start_date": _iso(contract.start_date),
        "end_date": _iso(contract.end_date),
    }


# Co korekta zrobiła z konkretnym szkicem — w paragonie i w arkuszu Excela.
ACTION_ACTIVATED = "activated"
ACTION_REVIVED = "activated_end_date_cleared"
ACTION_ENDED = "ended_expired"
ACTION_DUPLICATE = "left_draft_duplicate"
ACTION_LABEL = {
    ACTION_ACTIVATED: "Aktywny",
    ACTION_REVIVED: "Aktywny — usunięto minioną datę końca (trwa zamówienie)",
    ACTION_ENDED: "Zakończony — data końca minęła, brak trwającego zamówienia",
    ACTION_DUPLICATE: "Zostawiony jako szkic — osoba ma już aktywny kontrakt u klienta",
}


async def _live_sibling_ids(db: AsyncSession, contract: Contract) -> list[int]:
    """Żywe kontrakty TEJ SAMEJ osoby u TEGO SAMEGO klienta (poza tym szkicem)."""
    if contract.candidate_id is None:
        return []
    return list(
        (
            await db.scalars(
                select(Contract.id)
                .where(
                    Contract.candidate_id == contract.candidate_id,
                    Contract.client_id == contract.client_id,
                    Contract.id != contract.id,
                    Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
                )
                .order_by(Contract.id)
            )
        ).all()
    )


async def _has_live_order(db: AsyncSession, contract: Contract, today: date) -> bool:
    """Czy osoba ma dziś trwające (aktywne) zamówienie na tym kontrakcie."""
    found = await db.scalar(
        select(ClientOrder.id)
        .where(
            ClientOrder.contract_id == contract.id,
            ClientOrder.client_id == contract.client_id,
            ClientOrder.status == ClientOrderStatus.active,
            ClientOrder.start_date <= today,
            or_(ClientOrder.end_date.is_(None), ClientOrder.end_date >= today),
        )
        .limit(1)
    )
    return found is not None


async def _repair_one_draft(
    db: AsyncSession, contract: Contract, *, today: date
) -> dict[str, Any]:
    """Jeden szkic: synchronizacja z zamówieniami + decyzja o statusie.

    Trzy przypadki, w których „szkic → aktywny" wprost byłoby szkodą:

    * **duplikat** — osoba ma już żywy kontrakt u tego klienta; drugi aktywny
      podwoiłby jej przychód w MRR. Zostaje szkicem i trafia do raportu
      do ręcznej decyzji (scalenie albo anulowanie należy do człowieka);
    * **minęła data końca, zamówienie trwa** — data jest pozostałością po
      kopiowaniu okresu zamówienia na kontrakt (naprawione w 09.2026).
      Aktywny szkic z minioną datą zakończyłby nocny cron, a razem z nim
      domknąłby trwające zamówienia i otworzył sprawy offboardingu MD. Ta sama
      reguła co przy wskrzeszaniu (``sync_contract_to_live_order``): kontrakt
      staje się bezterminowy;
    * **minęła data końca, zamówienia brak** — współpraca się skończyła albo
      nie zaczęła; kontrakt przechodzi wprost na „Zakończony" (bez
      offboardingu — nie ma czego domykać).

    Każdy przypadek w savepoincie: błąd jednego kontraktu nie blokuje reszty.
    """
    before = _contract_state(contract)
    item: dict[str, Any] = {
        "contract_id": contract.id,
        "before": before,
        "action": None,
        "activated": False,
        "source_order_id": None,
        "order_costs_synced": [],
        "live_sibling_ids": [],
        "missing_start_date": contract.start_date is None,
        "sync_error": None,
    }
    try:
        async with db.begin_nested():
            siblings = await _live_sibling_ids(db, contract)
            if siblings:
                item["action"] = ACTION_DUPLICATE
                item["live_sibling_ids"] = siblings
            else:
                expired = contract.end_date is not None and contract.end_date < today
                revive = expired and await _has_live_order(db, contract, today)
                if revive:
                    contract.end_date = None
                if expired and not revive:
                    await end_expired_draft(
                        db,
                        contract,
                        actor_id=None,
                        source=DRAFT_REPAIR_ACTIVATION,
                    )
                    item["action"] = ACTION_ENDED
                else:
                    outcome = await resync_contract(
                        db,
                        contract,
                        actor_id=None,
                        today=today,
                        # Status przestawiamy niżej niezależnie od kompletności —
                        # ticket: żaden kontrakt nie zostaje szkicem.
                        auto_activate=False,
                    )
                    if outcome is not None:
                        item["source_order_id"] = outcome.source_order_id
                        item["order_costs_synced"] = outcome.order_cost_ids
                    item["activated"] = await activate_without_revenue_gate(
                        db,
                        contract,
                        actor_id=None,
                        source=DRAFT_REPAIR_ACTIVATION,
                        extra={
                            "order_id": item["source_order_id"],
                            "end_date_cleared": before["end_date"] if revive else None,
                        },
                    )
                    item["action"] = ACTION_REVIVED if revive else ACTION_ACTIVATED
                await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.exception("contract-order sync repair: contract %s", contract.id)
        item["sync_error"] = repr(exc)[:500]
        item["action"] = None
        item["activated"] = False
        await db.refresh(contract)
    item["after"] = _contract_state(contract)
    return item


async def run_contract_order_sync_repair(
    db: AsyncSession,
    *,
    today: Optional[date] = None,
    only_contract_ids: Optional[set[int]] = None,
) -> Optional[dict[str, Any]]:
    """Migawka raportu, potem korekta szkiców. ``None`` = już wykonane.

    Wołający commituje. Advisory lock jest transakcyjny, więc dwa równoległe
    starty (rolling deploy) wykonają blok raz: drugi czeka i widzi marker.
    ``only_contract_ids`` zawęża KOREKTĘ (nie migawkę) — wyłącznie dla testów,
    które nie mogą aktywować cudzych szkiców we wspólnej bazie.
    """
    today = today or business_today()
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": REPAIR_MARKER}
    )
    if await db.get(AppSetting, REPAIR_MARKER) is not None:
        return None

    snapshot = await build_reconciliation_rows(db, today=today)

    draft_ids = list(
        (
            await db.scalars(
                select(Contract.id)
                .where(
                    Contract.status == ContractStatus.draft,
                    *(
                        (Contract.id.in_(only_contract_ids),)
                        if only_contract_ids is not None
                        else ()
                    ),
                )
                .order_by(Contract.id)
            )
        ).all()
    )
    repaired: list[dict[str, Any]] = []
    for contract_id in draft_ids:
        contract = await db.get(Contract, contract_id)
        if contract is None:
            continue
        repaired.append(await _repair_one_draft(db, contract, today=today))

    summary = {
        "business_day": today.isoformat(),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "report_rows": len(snapshot),
        "drafts_found": len(draft_ids),
        "drafts_activated": sum(1 for item in repaired if item["activated"]),
        "drafts_with_order": sum(1 for item in repaired if item["source_order_id"]),
        "drafts_ended": sum(1 for item in repaired if item["action"] == ACTION_ENDED),
        "drafts_left_as_duplicates": sum(
            1 for item in repaired if item["action"] == ACTION_DUPLICATE
        ),
        "sync_errors": sum(1 for item in repaired if item["sync_error"]),
    }
    db.add(
        AppSetting(
            key=REPAIR_MARKER,
            value={
                **summary,
                "repaired_contract_ids": [item["contract_id"] for item in repaired],
            },
        )
    )
    details = {"snapshot": snapshot, "repaired": repaired}
    existing = await db.get(AppSetting, REPAIR_DETAILS_KEY)
    if existing is None:
        db.add(AppSetting(key=REPAIR_DETAILS_KEY, value=details))
    else:
        existing.value = details
    await db.flush()
    logger.info("contract-order sync repair: %s", summary)
    return summary


async def load_repair_details(
    db: AsyncSession,
) -> Optional[tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]]:
    """Paragon, migawka i poprawione kontrakty; ``None`` = korekta się nie wykonała.

    Paragon zapisany przed 26.09.2026 niesie migawkę w sobie (zostaje w bazie,
    nikt go nie przepisuje) — wtedy czytamy ją stamtąd.
    """
    receipt = await db.get(AppSetting, REPAIR_MARKER)
    if receipt is None:
        return None
    summary = dict(receipt.value or {})
    details_row = await db.get(AppSetting, REPAIR_DETAILS_KEY)
    details = dict(details_row.value or {}) if details_row is not None else summary
    return (
        summary,
        list(details.get("snapshot") or []),
        list(details.get("repaired") or []),
    )


# ── Excel ────────────────────────────────────────────────────────────────────

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_MISMATCH_FILL = PatternFill("solid", fgColor="F8D7DA")
_MATCH_FILL = PatternFill("solid", fgColor="D1E7DD")

_REPORT_COLUMNS: list[tuple[str, str, int]] = [
    ("Osoba", "candidate_name", 26),
    ("Klient", "client_name", 26),
    ("Kontrakt ID", "contract_id", 11),
    ("Status kontraktu", "contract_status", 15),
    ("Nr zamówienia", "order_number", 26),
    ("Rodzaj zamówienia", "order_kind", 22),
    ("Status zamówienia", "order_status", 15),
    ("Najnowsze zamówienie", "is_latest_order", 12),
    ("Stawka kosztowa — zamówienie", "order_cost", 16),
    ("Jedn. (zam.)", "order_cost_unit", 9),
    ("Stawka kosztowa — kontrakt", "contract_cost", 16),
    ("Jedn. (kontr.)", "contract_cost_unit", 9),
    ("Koszt z kontraktu w jedn. zamówienia", "contract_cost_in_order_unit", 18),
    ("Zgodność kosztu", "cost_status", 14),
    ("Stawka przychodowa — zamówienie", "order_revenue", 16),
    ("Jedn. (zam.) ", "order_revenue_unit", 9),
    ("Stawka przychodowa — kontrakt", "contract_revenue", 16),
    ("Jedn. (kontr.) ", "contract_revenue_unit", 9),
    ("Przychód z kontraktu w jedn. zamówienia", "contract_revenue_in_order_unit", 18),
    ("Zgodność przychodu", "revenue_status", 14),
    ("Okres w zamówieniu", "order_period", 24),
    ("Okres zamówienia w kontrakcie", "contract_order_period", 24),
    ("Okres umowy (kontrakt)", "contract_period", 24),
    ("Zgodność okresu", "period_status", 14),
]
_MONEY_KEYS = {
    "order_cost",
    "contract_cost",
    "contract_cost_in_order_unit",
    "order_revenue",
    "contract_revenue",
    "contract_revenue_in_order_unit",
}
_STATUS_KEYS = {"cost_status", "revenue_status", "period_status"}


def _period(start: Optional[str], end: Optional[str]) -> str:
    def fmt(value: Optional[str]) -> Optional[str]:
        return date.fromisoformat(value).strftime("%d.%m.%Y") if value else None

    if not start and not end:
        return "—"
    return f"{fmt(start) or '—'} → {fmt(end) or 'bezterminowo'}"


def _cell_value(row: dict[str, Any], key: str) -> object:
    if key == "order_period":
        return _period(row.get("order_start"), row.get("order_end"))
    if key == "contract_order_period":
        return _period(row.get("contract_order_start"), row.get("contract_order_end"))
    if key == "contract_period":
        return _period(row.get("contract_start"), row.get("contract_end"))
    value = row.get(key)
    if key in _MONEY_KEYS:
        return None if value is None else float(Decimal(value))
    if key.endswith("_unit"):
        return _UNIT_LABEL.get(value, value)
    if key == "contract_status":
        return _STATUS_LABEL.get(value, value)
    if key == "order_status":
        return _ORDER_STATUS_LABEL.get(value, value)
    if key == "is_latest_order":
        return "tak" if value else ""
    if isinstance(value, str):
        return safe_cell(value)
    return value


def _write_table(sheet, columns, rows, *, status_keys=frozenset()) -> None:
    sheet.append([title for title, _, _ in columns])
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in rows:
        sheet.append([_cell_value(row, key) for _, key, _ in columns])
    for index, (_, key, width) in enumerate(columns, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
        if key in _MONEY_KEYS:
            for (cell,) in sheet.iter_rows(min_row=2, min_col=index, max_col=index):
                cell.number_format = "#,##0.00#"
        if key in status_keys:
            for (cell,) in sheet.iter_rows(min_row=2, min_col=index, max_col=index):
                if cell.value == MISMATCH:
                    cell.fill = _MISMATCH_FILL
                    cell.font = Font(bold=True)
                elif cell.value == MATCH:
                    cell.fill = _MATCH_FILL
    sheet.row_dimensions[1].height = 42
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = sheet.dimensions


_REPAIR_COLUMNS: list[tuple[str, str, int]] = [
    ("Kontrakt ID", "contract_id", 11),
    ("Osoba", "candidate_name", 26),
    ("Klient", "client_name", 26),
    ("Status przed", "before_status", 13),
    ("Status po", "after_status", 13),
    ("Jednostka przed", "before_unit", 11),
    ("Jednostka po", "after_unit", 11),
    ("Stawka kosztowa przed", "before_cost", 14),
    ("Stawka kosztowa po", "after_cost", 14),
    ("Stawka przychodowa przed", "before_revenue", 14),
    ("Stawka przychodowa po", "after_revenue", 14),
    ("Okres zamówienia po", "after_order_period", 24),
    ("Zamówienie źródłowe", "source_order_id", 12),
    ("Decyzja korekty", "action", 44),
    ("Uwagi — do ręcznego sprawdzenia", "remarks", 48),
]


def _repair_rows(
    repaired: list[dict[str, Any]], names: dict[int, tuple[str, str]]
) -> list[dict[str, Any]]:
    out = []
    for item in repaired:
        before, after = item.get("before", {}), item.get("after", {})
        candidate, client = names.get(item["contract_id"], ("", ""))
        out.append(
            {
                "contract_id": item["contract_id"],
                "candidate_name": candidate,
                "client_name": client,
                "before_status": _STATUS_LABEL.get(before.get("status"), ""),
                "after_status": _STATUS_LABEL.get(after.get("status"), ""),
                "before_unit": _UNIT_LABEL.get(before.get("rate_unit"), ""),
                "after_unit": _UNIT_LABEL.get(after.get("rate_unit"), ""),
                "before_cost": before.get("rate_candidate"),
                "after_cost": after.get("rate_candidate"),
                "before_revenue": before.get("rate_client"),
                "after_revenue": after.get("rate_client"),
                "after_order_period": _period(
                    after.get("client_order_start_date"),
                    after.get("client_order_end_date"),
                ),
                "source_order_id": item.get("source_order_id"),
                "action": ACTION_LABEL.get(item.get("action"), "Bez zmiany statusu"),
                "remarks": _repair_remarks(item),
            }
        )
    return out


def _repair_remarks(item: dict[str, Any]) -> str:
    remarks = []
    if item.get("live_sibling_ids"):
        remarks.append(
            "aktywny kontrakt tej osoby u klienta: "
            + ", ".join(f"#{cid}" for cid in item["live_sibling_ids"])
        )
    if item.get("missing_start_date"):
        remarks.append("brak daty startu umowy")
    if item.get("sync_error"):
        remarks.append("błąd synchronizacji — status bez zmian")
    return "; ".join(remarks)


def _repair_cell(row: dict[str, Any], key: str) -> object:
    value = row.get(key)
    if key in {"before_cost", "after_cost", "before_revenue", "after_revenue"}:
        return None if value is None else float(Decimal(value))
    if isinstance(value, str):
        return safe_cell(value)
    return value


def build_reconciliation_workbook(
    *,
    snapshot: list[dict[str, Any]],
    repaired: list[dict[str, Any]],
    repair_names: dict[int, tuple[str, str]],
    live: list[dict[str, Any]],
    summary: dict[str, Any],
) -> bytes:
    """Plik Excel: stan sprzed wdrożenia, poprawione szkice, stan bieżący."""
    workbook = Workbook()
    info = workbook.active
    info.title = "Podsumowanie"
    mismatches = {
        key: sum(1 for row in snapshot if row.get(key) == MISMATCH)
        for key in _STATUS_KEYS
    }
    info.append(["Zestawienie zgodności zamówienie ↔ kontrakt (jednorazowe)"])
    info["A1"].font = Font(bold=True, size=13)
    for label, value in (
        ("Migawka z dnia", summary.get("business_day")),
        ("Wierszy (zamówień) w migawce", len(snapshot)),
        ("Niezgodna stawka kosztowa", mismatches["cost_status"]),
        ("Niezgodna stawka przychodowa", mismatches["revenue_status"]),
        ("Niezgodny okres (najnowsze zamówienie)", mismatches["period_status"]),
        (
            "Okres zamówienia nieobecny w kontrakcie",
            sum(1 for row in snapshot if row.get("period_status") == NOT_IN_CONTRACT),
        ),
        ("Szkiców przestawionych na Aktywny", summary.get("drafts_activated")),
        ("…w tym uzupełnionych z zamówienia", summary.get("drafts_with_order")),
        ("Szkiców zakończonych (minęła data końca)", summary.get("drafts_ended")),
        (
            "Szkiców zostawionych — duplikat aktywnego kontraktu",
            summary.get("drafts_left_as_duplicates"),
        ),
        ("Błędy synchronizacji (status bez zmian)", summary.get("sync_errors")),
    ):
        info.append([label, value])
    info.append([])
    info.append(
        [
            "Porównanie przelicza stawkę kontraktu na jednostkę zamówienia "
            "(1 MD = 8 h). Kontrakt jest wyceniany z harmonogramu stawek na dzień "
            "okresu zamówienia. Różne waluty = „brak danych”."
        ]
    )
    info.column_dimensions["A"].width = 44
    info.column_dimensions["B"].width = 18

    before = workbook.create_sheet("Przed wdrożeniem")
    _write_table(before, _REPORT_COLUMNS, snapshot, status_keys=_STATUS_KEYS)

    fixed = workbook.create_sheet("Poprawione szkice")
    fixed.append([title for title, _, _ in _REPAIR_COLUMNS])
    for cell in fixed[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in _repair_rows(repaired, repair_names):
        fixed.append([_repair_cell(row, key) for _, key, _ in _REPAIR_COLUMNS])
    for index, (_, _, width) in enumerate(_REPAIR_COLUMNS, start=1):
        fixed.column_dimensions[get_column_letter(index)].width = width
    fixed.freeze_panes = "B2"
    fixed.auto_filter.ref = fixed.dimensions

    now = workbook.create_sheet("Stan bieżący")
    _write_table(now, _REPORT_COLUMNS, live, status_keys=_STATUS_KEYS)

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


async def repair_contract_names(
    db: AsyncSession, contract_ids: list[int]
) -> dict[int, tuple[str, str]]:
    """Nazwisko i klient dla poprawionych kontraktów (do arkusza korekty)."""
    if not contract_ids:
        return {}
    rows = (
        await db.execute(
            select(Contract.id, Candidate.name, Candidate.lastname, Client)
            .join(Client, Client.id == Contract.client_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.id.in_(contract_ids))
        )
    ).all()
    return {
        contract_id: (
            f"{name or ''} {lastname or ''}".strip() or "(osoba usunięta)",
            client_display_name(client),
        )
        for contract_id, name, lastname, client in rows
    }
