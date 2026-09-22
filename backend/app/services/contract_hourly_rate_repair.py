"""Jednorazowe przeliczenie kontraktów w MD na stawki godzinowe (0309, 14.09.2026).

Ticket „Ujednolicenie stawek w module Kontrakty do formatu godzinowego":
w Kontraktach mieszały się stawki zł/h i zł/MD, więc eksport do Excela
mieszał jednostki. Od tej zmiany kontrakt nigdy nie jest w MD
(``contract_order_sync.contract_unit_for_order``), a ta korekta przelicza
kontrakty, które już w MD są.

Reguły (kryteria akceptacji ticketu):

* przeliczane są WYŁĄCZNIE kontrakty ``rate_unit = daily`` — godzinowe
  i ryczałtowe (``monthly``, decyzja Artura 14.09.2026) zostają nietknięte;
* każda kwota, którą jednostka opisuje: obie stawki, trzy harmonogramy, stawka
  ramowa i widełki — MD ÷ 8, bez zaokrąglenia zniekształcającego kwotę.
  Przed zapisem sprawdzamy odwrotność (godzinowa × 8 == dawna dzienna); kontrakt,
  którego nie da się przeliczyć dokładnie, zostaje w MD z kodem powodu;
* ``billing_hours_per_month`` = standardowy miesiąc roboczy (w 09.2026 było
  to 176 h = 22 MD × 8 h; od 22.09.2026 168 h = 21 MD × 8 h,
  ``app.core.work_time``) i ``orders_in_md`` — czytniki pieniędzy liczą
  miesięcznie MD × 21 i godziny × liczba godzin, więc MRR, marża miesięczna
  i raporty są po korekcie co do grosza takie jak przed nią;
* zamówienia NIE są ruszane: korekta nie woła synchronizacji z zamówieniami,
  a suma kontrolna wszystkich ``client_orders`` przed i po musi być identyczna —
  inaczej wyjątek i rollback całości.

Kolumny muszą mieć już 6 miejsc po przecinku (DDL 0309 w ``entrypoint.sh``,
który przy kontencji zamka potrafi się wycofać). Bez tego przeliczenie
zaokrągliłoby kwoty w bazie — korekta czeka wtedy do następnego startu,
bez markera.

Repo jest publiczne: paragon pod kluczem ``0309_…`` niesie wyłącznie liczniki,
ID i kody powodów; stare i nowe kwoty leżą pod ``repair_details_0309_…``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.work_time import HOURS_PER_MONTH
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.contract import Contract, RateUnit
from app.services.contract_order_sync import _switch_contract_unit
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.order_rate_snapshots import (
    CONTRACT_RATE_SCALE,
    HOURS_PER_DAY,
    convert_order_rate,
)

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0309_contract_hourly_rates"
DETAILS_KEY = "repair_details_0309_contract_hourly_rates"
SOURCE = REPAIR_MARKER

WIDENED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("contracts", "rate_candidate"),
    ("contracts", "rate_client"),
    ("contracts", "margin"),
    ("contracts", "framework_rate"),
    ("contracts", "target_rate_min"),
    ("contracts", "target_rate_max"),
    ("contract_candidate_rates", "rate"),
    ("contract_client_rates", "rate"),
    ("contract_framework_rates", "rate"),
)

_COLUMN_FIELDS = (
    "rate_candidate",
    "rate_client",
    "framework_rate",
    "target_rate_min",
    "target_rate_max",
)
_SCHEDULES = (
    "candidate_rate_schedule",
    "client_rate_schedule",
    "framework_rate_schedule",
)

# Wszystko, co opisuje pieniądze i jednostkę zamówienia, plus ``updated_at``:
# korekta ma nie dotknąć żadnego wiersza, nawet zapisem tej samej wartości.
_ORDER_CHECKSUM_SQL = """
SELECT count(*) AS n, coalesce(md5(string_agg(row_text, '|' ORDER BY id)), '') AS h
FROM (
    SELECT id, concat_ws(';',
        id, contract_id, rate_candidate, rate_client, rate_unit,
        billing_hours_per_month, rate_candidate_currency, rate_client_currency,
        currency, md_rate_cost, md_rate_revenue, md_input_value, md_total,
        md_remaining, md_manual_adjustment, total_value, status, updated_at
    ) AS row_text
    FROM client_orders
) AS rows
"""


async def columns_widened(db: AsyncSession) -> bool:
    """Czy wszystkie kolumny stawek kontraktu mają już NUMERIC(16,6)."""
    rows = (
        await db.execute(
            text(
                "SELECT table_name, column_name, data_type, numeric_precision, "
                "numeric_scale FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name IN ('contracts', 'contract_candidate_rates', "
                "'contract_client_rates', 'contract_framework_rates')"
            )
        )
    ).all()
    found = {
        (row.table_name, row.column_name): (
            row.data_type,
            row.numeric_precision,
            row.numeric_scale,
        )
        for row in rows
    }
    return all(found.get(column) == ("numeric", 16, 6) for column in WIDENED_COLUMNS)


async def orders_checksum(db: AsyncSession) -> tuple[int, str]:
    row = (await db.execute(text(_ORDER_CHECKSUM_SQL))).one()
    return int(row.n), str(row.h)


def _as_decimal(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _to_hourly(value: object) -> Optional[Decimal]:
    return convert_order_rate(
        value, RateUnit.daily, RateUnit.hourly, scale=CONTRACT_RATE_SCALE
    )


def _exact(value: object) -> bool:
    """Godzinowa × 8 musi dać dokładnie dawną stawkę dzienną."""
    old = _as_decimal(value)
    if old is None:
        return True
    hourly = _to_hourly(old)
    return hourly is not None and hourly * HOURS_PER_DAY == old


def _amounts(contract: Contract) -> dict[str, Any]:
    amounts: dict[str, Any] = {
        field: _as_decimal(getattr(contract, field)) for field in _COLUMN_FIELDS
    }
    amounts["margin"] = _as_decimal(contract.margin)
    for schedule in _SCHEDULES:
        amounts[schedule] = [
            {
                "id": step.id,
                "effective_from": step.effective_from.isoformat(),
                "rate": _as_decimal(step.rate),
            }
            for step in getattr(contract, schedule)
        ]
    return amounts


def _all_values(contract: Contract) -> list[object]:
    values: list[object] = [getattr(contract, field) for field in _COLUMN_FIELDS]
    for schedule in _SCHEDULES:
        values.extend(step.rate for step in getattr(contract, schedule))
    return values


def _monthly_equivalents(contract: Contract) -> list[Optional[Decimal]]:
    return [contract.monthly_rate(value) for value in _all_values(contract)]


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


async def run_contract_hourly_rate_repair(
    db: AsyncSession,
    *,
    marker: str = REPAIR_MARKER,
    details_key: str = DETAILS_KEY,
    batch_size: int = 200,
    only_contract_ids: Optional[set[int]] = None,
) -> Optional[dict[str, Any]]:
    """Przelicz kontrakty w MD na zł/h. ``None`` = nic do zrobienia. Wołający commituje.

    Zwraca ``{"pending": "columns_not_widened"}`` bez markera, gdy DDL jeszcze
    nie poszerzył kolumn — następny start spróbuje ponownie.
    ``only_contract_ids`` zawęża przebieg (testy na współdzielonej bazie).

    Po markerze przebieg nadal łapie kontrakty w MD zapisane PÓŹNIEJ (stary
    kontener w trakcie deployu działa jeszcze na starej regule) — dopisuje je
    do paragonu jako ``late_converted_contract_ids``. Kontrakty pominięte
    w pierwszym przebiegu z kodem powodu nie są oglądane ponownie.
    """
    # REPEATABLE READ: suma kontrolna zamówień przed i po widzi tę samą migawkę,
    # więc zapis zamówienia przez stary kontener w trakcie korekty nie wywraca
    # jej fałszywie (zmiany z tej transakcji nadal są widoczne).
    # Tylko na świeżej transakcji (tak woła entrypoint) — Postgres odrzuca
    # zmianę poziomu izolacji po pierwszym zapytaniu.
    if not db.in_transaction():
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    # Stary kontener przy wdrożeniu trzyma blokady kontraktów; przekroczenie
    # = rollback, następny start ponawia (jak w korektach 0306 i 0308).
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    receipt = await db.get(AppSetting, marker)
    if not await columns_widened(db):
        return None if receipt is not None else {"pending": "columns_not_widened"}

    query = select(Contract.id).where(Contract.rate_unit == RateUnit.daily)
    if only_contract_ids is not None:
        query = query.where(Contract.id.in_(sorted(only_contract_ids)))
    if receipt is not None:
        already_skipped = [
            int(item["contract_id"]) for item in receipt.value.get("skipped", [])
        ]
        if already_skipped:
            query = query.where(Contract.id.not_in(already_skipped))
    contract_ids = list((await db.scalars(query.order_by(Contract.id))).all())
    if receipt is not None and not contract_ids:
        return None
    orders_before = await orders_checksum(db)

    converted: list[int] = []
    skipped: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for offset in range(0, len(contract_ids), batch_size):
        batch = contract_ids[offset : offset + batch_size]
        contracts = (
            await db.scalars(
                select(Contract)
                .where(Contract.id.in_(batch))
                .options(*RATE_SCHEDULE_LOADS)
                .order_by(Contract.id)
                .with_for_update(of=Contract)
                .execution_options(populate_existing=True)
            )
        ).all()
        for contract in contracts:
            if RateUnit(contract.rate_unit) != RateUnit.daily:
                skipped.append({"contract_id": contract.id, "reason": "not_daily"})
                continue
            if not all(_exact(value) for value in _all_values(contract)):
                skipped.append(
                    {"contract_id": contract.id, "reason": "inexact_conversion"}
                )
                continue
            before = _amounts(contract)
            monthly_before = _monthly_equivalents(contract)
            hours_before = contract.billing_hours_per_month
            _switch_contract_unit(contract, RateUnit.hourly)
            contract.margin = contract.calculate_margin()
            if (
                contract.billing_hours_per_month != HOURS_PER_MONTH
                or not contract.orders_in_md
                or _monthly_equivalents(contract) != monthly_before
            ):
                raise RuntimeError(
                    f"contract {contract.id}: monthly equivalent changed"
                )
            converted.append(contract.id)
            details.append(
                {
                    "contract_id": contract.id,
                    "billing_hours_before": hours_before,
                    "before": _plain(before),
                    "after": _plain(_amounts(contract)),
                }
            )
            db.add(
                Activity(
                    entity_type="contract",
                    entity_id=contract.id,
                    action="rate_unit_converted_to_hourly",
                    user_id=None,
                    external_source=SOURCE,
                    external_id=f"hourly:{contract.id}",
                    details={
                        "source": SOURCE,
                        "rate_unit": {"from": "daily", "to": "hourly"},
                        "billing_hours_per_month": {
                            "from": hours_before,
                            "to": HOURS_PER_MONTH,
                        },
                        "divisor": 8,
                    },
                )
            )
        await db.flush()

    orders_after = await orders_checksum(db)
    if orders_after != orders_before:
        raise RuntimeError("client_orders changed during contract hourly repair")

    if receipt is not None:
        # Kontrakty dopisane w MD po pierwszym przebiegu — ten sam paragon.
        late = receipt.value.get("late_converted_contract_ids", []) + converted
        receipt.value = {**receipt.value, "late_converted_contract_ids": late}
        stored = await db.get(AppSetting, details_key)
        if stored is not None:
            stored.value = {
                **stored.value,
                "late": stored.value.get("late", []) + details,
            }
        await db.flush()
        logger.info("contract hourly repair: %s late conversions", len(converted))
        return {"late_converted": converted, "skipped": skipped}

    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "daily_contracts_found": len(contract_ids),
        "contracts_converted": len(converted),
        "converted_contract_ids": converted,
        "skipped": skipped,
        "client_orders_checked": orders_before[0],
        "client_orders_unchanged": True,
    }
    db.add(AppSetting(key=marker, value=summary))
    db.add(AppSetting(key=details_key, value={"converted": details}))
    await db.flush()
    logger.info(
        "contract hourly repair: %s/%s converted", len(converted), len(contract_ids)
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    if "pending" in summary:
        return f"waiting ({summary['pending']}), next start retries"
    if "late_converted" in summary:
        return f"late conversions: {len(summary['late_converted'])}"
    reasons = ", ".join(
        f"{item['contract_id']}:{item['reason']}" for item in summary["skipped"]
    )
    return (
        f"converted {summary['contracts_converted']}/"
        f"{summary['daily_contracts_found']} daily contracts; "
        f"{summary['client_orders_checked']} orders unchanged"
        + (f" (skipped {reasons})" if reasons else "")
    )
