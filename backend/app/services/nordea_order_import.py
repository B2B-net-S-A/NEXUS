"""Validated, idempotent import of Nordea order and framework-rate data."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

MAX_NORDEA_IMPORT_BYTES = 2 * 1024 * 1024
LIVE_CONTRACT_STATUSES = {
    "active",
    "ending",
    "ready_for_signature",
    "draft",
}


class NordeaImportError(ValueError):
    """A user-correctable file or scope validation error."""


@dataclass(frozen=True)
class NordeaRow:
    row_number: int
    order_number: str
    contractor_name: str
    start_date: date
    end_date: date
    revenue_rate: Decimal
    framework_rate: Decimal


def _header_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]", "", ascii_value.casefold())


def _normalize_name_part(value: Any) -> str:
    translated = str(value or "").strip().translate(str.maketrans({"ł": "l", "Ł": "L"}))
    decomposed = unicodedata.normalize("NFKD", translated)
    ascii_value = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]", "", ascii_value.casefold())


def _name_key(value: str) -> str:
    parts = [_normalize_name_part(part) for part in re.findall(r"[^\s,;]+", value)]
    return "|".join(sorted(part for part in parts if part))


def _candidate_name(contract: Any) -> str:
    candidate = contract.candidate
    if candidate is None:
        return ""
    return f"{candidate.name} {candidate.lastname}".strip()


def _parse_date(value: str, *, row: int, field: str) -> date:
    raw = value.strip()
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            pass
    raise NordeaImportError(f"Wiersz {row}: nieprawidłowa {field}: {raw!r}")


def _parse_decimal(value: str, *, row: int, field: str) -> Decimal:
    raw = value.replace("\u00a0", "").replace(" ", "").replace(",", ".").strip()
    try:
        parsed = Decimal(raw)
    except InvalidOperation as exc:
        raise NordeaImportError(
            f"Wiersz {row}: nieprawidłowa {field}: {value!r}"
        ) from exc
    if not parsed.is_finite():
        raise NordeaImportError(f"Wiersz {row}: {field} musi być skończoną liczbą")
    if parsed < 0:
        raise NordeaImportError(f"Wiersz {row}: {field} nie może być ujemna")
    return parsed


def parse_nordea_csv(payload: bytes) -> list[NordeaRow]:
    if not payload:
        raise NordeaImportError("Plik CSV jest pusty")
    if len(payload) > MAX_NORDEA_IMPORT_BYTES:
        raise NordeaImportError("Plik CSV przekracza limit 2 MB")
    text: Optional[str] = None
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            text = payload.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise NordeaImportError("Plik musi być zapisany jako UTF-8 lub Windows-1250")

    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        header = next(reader)
    except StopIteration as exc:
        raise NordeaImportError("Plik CSV jest pusty") from exc
    keys = [_header_key(cell) for cell in header]
    expected = {
        "ord": "numerzamowienia",
        "name": "kontraktor",
        "start": "startdate",
        "end": "enddate",
        "revenue": "stawkaprzychodowa",
        "framework": "stawkazumowyramowej",
    }
    # Historical files contain one or two spaces in the revenue header. Match
    # semantically, then fall back to the documented column position.
    indexes: dict[str, int] = {}
    for label, key in expected.items():
        if key in keys:
            indexes[label] = keys.index(key)
    positional = {
        "ord": 0,
        "name": 1,
        "start": 3,
        "end": 4,
        "revenue": 5,
        "framework": 6,
    }
    for label, index in positional.items():
        indexes.setdefault(label, index)
    if len(header) < 7 or keys[0] != "numerzamowienia" or keys[1] != "kontraktor":
        raise NordeaImportError(
            "Nie rozpoznano nagłówków pliku Nordea (wymagane kolumny A–G)"
        )

    rows: list[NordeaRow] = []
    for row_number, values in enumerate(reader, start=2):
        if not any(value.strip() for value in values):
            continue
        if len(values) < 7:
            raise NordeaImportError(f"Wiersz {row_number}: brakuje kolumn A–G")
        order_number = values[indexes["ord"]].strip()
        contractor_name = " ".join(values[indexes["name"]].split())
        if not order_number or not contractor_name:
            raise NordeaImportError(
                f"Wiersz {row_number}: numer zamówienia i kontraktor są wymagane"
            )
        start = _parse_date(
            values[indexes["start"]], row=row_number, field="data rozpoczęcia"
        )
        end = _parse_date(
            values[indexes["end"]], row=row_number, field="data zakończenia"
        )
        if end < start:
            raise NordeaImportError(
                f"Wiersz {row_number}: data zakończenia jest wcześniejsza od rozpoczęcia"
            )
        rows.append(
            NordeaRow(
                row_number=row_number,
                order_number=order_number,
                contractor_name=contractor_name,
                start_date=start,
                end_date=end,
                revenue_rate=_parse_decimal(
                    values[indexes["revenue"]],
                    row=row_number,
                    field="stawka przychodowa",
                ),
                framework_rate=_parse_decimal(
                    values[indexes["framework"]], row=row_number, field="stawka ramowa"
                ).quantize(Decimal("0.01")),
            )
        )
    if not rows:
        raise NordeaImportError("Plik nie zawiera żadnych rekordów")
    return rows


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _choose_contract(contracts: list[Any], rows: list[NordeaRow]) -> Optional[Any]:
    candidate_ids = {contract.candidate_id for contract in contracts}
    if len(candidate_ids) != 1:
        return None
    order_numbers = {row.order_number for row in rows}
    with_exact = [
        contract
        for contract in contracts
        if any(order.title.strip() in order_numbers for order in contract.client_orders)
    ]
    pool = (
        with_exact
        or [c for c in contracts if _status_value(c.status) in LIVE_CONTRACT_STATUSES]
        or contracts
    )
    return max(
        pool, key=lambda contract: (contract.start_date or date.min, contract.id)
    )


def _pick_existing_order(
    contract: Any, row: NordeaRow, *, first_for_contractor: bool
) -> Optional[Any]:
    orders = [
        order
        for order in contract.client_orders
        if order.order_group_id is None and _status_value(order.status) != "cancelled"
    ]
    exact = [order for order in orders if order.title.strip() == row.order_number]
    if exact:
        same_period = [
            order
            for order in exact
            if order.start_date == row.start_date and order.end_date == row.end_date
        ]
        return max(same_period or exact, key=lambda order: order.id)
    if not first_for_contractor:
        return None
    same_period = [
        order
        for order in orders
        if order.start_date == row.start_date or order.end_date == row.end_date
    ]
    if len(same_period) == 1:
        return same_period[0]
    if len(orders) == 1:
        return orders[0]
    current = [
        order
        for order in orders
        if (order.start_date is None or order.start_date <= date.today())
        and (order.end_date is None or order.end_date >= date.today())
    ]
    return current[0] if len(current) == 1 else None


def _order_state(order: Any) -> tuple[Any, ...]:
    return (
        order.title,
        order.start_date,
        order.end_date,
        order.rate_client,
        order.status,
    )


async def import_nordea_orders(
    db: AsyncSession,
    *,
    client: Any,
    rows: list[NordeaRow],
    filename: str,
    user_id: int,
    dry_run: bool,
    sha256: str,
) -> dict[str, Any]:
    # Lazy model imports keep the CSV parser usable as a pure unit without
    # bootstrapping application settings or a database engine.
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract
    from app.models.contract_framework_rate import ContractFrameworkRate

    client_label = client.display_name or client.legal_name or client.name
    if "nordea" not in _normalize_name_part(client_label):
        raise NordeaImportError(
            "Import jest dostępny wyłącznie dla klienta Nordea Bank ABP"
        )

    contracts = list(
        (
            await db.execute(
                select(Contract)
                .options(
                    selectinload(Contract.candidate),
                    selectinload(Contract.client_orders),
                    selectinload(Contract.framework_rate_schedule),
                )
                .where(
                    Contract.client_id == client.id, Contract.candidate_id.is_not(None)
                )
            )
        ).scalars()
    )
    by_name: dict[str, list[Any]] = defaultdict(list)
    nexus_names: dict[str, str] = {}
    for contract in contracts:
        name = _candidate_name(contract)
        key = _name_key(name)
        if key:
            by_name[key].append(contract)
            nexus_names.setdefault(key, name)

    rows_by_name: dict[str, list[NordeaRow]] = defaultdict(list)
    for row in rows:
        rows_by_name[_name_key(row.contractor_name)].append(row)
    for person_rows in rows_by_name.values():
        person_rows.sort(
            key=lambda item: (item.start_date, item.order_number, item.row_number)
        )

    unmatched: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    overlaps: list[dict[str, Any]] = []
    matched_keys: set[str] = set()
    counters: Counter[str] = Counter()

    for key, person_rows in sorted(
        rows_by_name.items(), key=lambda item: item[1][0].contractor_name
    ):
        candidates = by_name.get(key, [])
        if not candidates:
            unmatched.append(
                {
                    "contractor": person_rows[0].contractor_name,
                    "rows": [row.row_number for row in person_rows],
                    "reason": "Nie znaleziono kontraktora przypisanego do Nordea w Nexusie",
                }
            )
            continue
        contract = _choose_contract(candidates, person_rows)
        if contract is None:
            ambiguous.append(
                {
                    "contractor": person_rows[0].contractor_name,
                    "rows": [row.row_number for row in person_rows],
                    "contract_ids": sorted(contract.id for contract in candidates),
                    "reason": "Nazwa wskazuje więcej niż jedną osobę w Nexusie",
                }
            )
            continue
        matched_keys.add(key)

        for previous, following in zip(person_rows, person_rows[1:]):
            if following.start_date <= previous.end_date:
                overlaps.append(
                    {
                        "contractor": following.contractor_name,
                        "earlier_order": previous.order_number,
                        "later_order": following.order_number,
                        "message": "Okresy zamówień nakładają się; zachowano daty z pliku",
                    }
                )

        for index, row in enumerate(person_rows):
            order = _pick_existing_order(contract, row, first_for_contractor=index == 0)
            created = order is None
            if created:
                order = ClientOrder(
                    client_id=client.id,
                    contract_id=contract.id,
                    title=row.order_number,
                    status=(
                        ClientOrderStatus.completed
                        if row.end_date < date.today()
                        else ClientOrderStatus.active
                    ),
                    start_date=row.start_date,
                    end_date=row.end_date,
                    rate_client=row.revenue_rate,
                    created_by_user_id=user_id,
                    notes=f"Import Nordea z pliku {filename}",
                )
                db.add(order)
                contract.client_orders.append(order)
                counters["orders_created"] += 1
            else:
                before = _order_state(order)
                # Intentionally do not mutate Contract.rate_candidate or
                # ClientOrder.md_rate_cost: the ticket explicitly preserves cost.
                order.title = row.order_number
                order.start_date = row.start_date
                order.end_date = row.end_date
                order.rate_client = row.revenue_rate
                order.status = (
                    ClientOrderStatus.completed
                    if row.end_date < date.today()
                    else ClientOrderStatus.active
                )
                counters[
                    "orders_unchanged"
                    if before == _order_state(order)
                    else "orders_updated"
                ] += 1

            schedule = list(contract.framework_rate_schedule)
            same_day = [
                step for step in schedule if step.effective_from == row.start_date
            ]
            if same_day:
                step = same_day[-1]
                before_step = (step.rate, step.effective_to)
                step.rate = row.framework_rate
                step.effective_to = row.end_date
                step.note = f"Import Nordea z pliku {filename}"
                counters[
                    "framework_unchanged"
                    if before_step == (step.rate, step.effective_to)
                    else "framework_updated"
                ] += 1
            else:
                step = ContractFrameworkRate(
                    contract_id=contract.id,
                    rate=row.framework_rate,
                    effective_from=row.start_date,
                    effective_to=row.end_date,
                    note=f"Import Nordea z pliku {filename}",
                    created_by=user_id,
                )
                db.add(step)
                contract.framework_rate_schedule.append(step)
                counters["framework_created"] += 1

        contract.framework_rate = contract.effective_framework_rate(date.today())

    nexus_only = [
        {
            "contractor": nexus_names[key],
            "contract_ids": sorted(c.id for c in by_name[key]),
        }
        for key in sorted(set(nexus_names) - set(rows_by_name))
    ]
    shared = Counter(row.order_number for row in rows)
    return {
        "dry_run": dry_run,
        "applied": not dry_run,
        "filename": filename,
        "sha256": sha256,
        "rows_total": len(rows),
        "contractors_in_file": len(rows_by_name),
        "matched_contractors": len(matched_keys),
        "orders_created": counters["orders_created"],
        "orders_updated": counters["orders_updated"],
        "orders_unchanged": counters["orders_unchanged"],
        "framework_created": counters["framework_created"],
        "framework_updated": counters["framework_updated"],
        "framework_unchanged": counters["framework_unchanged"],
        "cost_rates_changed": 0,
        "unmatched_file": unmatched,
        "ambiguous_file": ambiguous,
        "nexus_only": nexus_only,
        "overlap_warnings": overlaps,
        "shared_order_numbers": [
            {"order_number": number, "contractors": count}
            for number, count in sorted(shared.items())
            if count > 1
        ],
    }


def payload_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
