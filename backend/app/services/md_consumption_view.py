"""Okno „Zużycie MD" osoby — saldo po miesiącu, numer z importu, korekty.

Ticket 7 (25.09.2026): okno zużycia nie pokazywało salda po każdym miesiącu
ani numeru zamówienia z importu, a ręczne korekty żyły wyłącznie w historii
zamówienia. Ten moduł składa je przy odczycie z trzech źródeł — wpisów
``client_order_md_consumptions``, wierszy importu przypisanych do linii i
wpisów dziennika „zejście MD" — jako czyste funkcje, bez sesji.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.services import finance_order_matching

ZERO = Decimal("0")
_DIGITS = re.compile(r"\d+")


@dataclass(frozen=True)
class ConsumptionIn:
    period_month: str
    md_reported: Decimal
    source: str


@dataclass(frozen=True)
class ImportRefIn:
    import_id: int
    row_number: int
    order_number_hint: Optional[str]
    md_reported: Decimal


@dataclass(frozen=True)
class CorrectionEventIn:
    created_at: datetime
    author_name: Optional[str]
    payload: dict[str, Any]


@dataclass
class ImportRefOut:
    import_id: int
    row_number: int
    order_number_hint: Optional[str]
    md_reported: Decimal
    foreign: bool


@dataclass
class CorrectionOut:
    created_at: datetime
    period_month: Optional[str]
    author_name: Optional[str]
    from_md: Optional[Decimal]
    from_source: str
    to_md: Optional[Decimal]
    removed: bool


@dataclass
class MonthOut:
    period_month: str
    source_kind: str
    balance_after: Optional[Decimal]
    import_rows: list[ImportRefOut] = field(default_factory=list)
    corrections: list[CorrectionOut] = field(default_factory=list)


@dataclass
class ConsumptionView:
    months: dict[str, MonthOut]
    removed: list[CorrectionOut]
    foreign: list[tuple[str, ImportRefOut]]
    used: Decimal


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def order_digits(value: Optional[str]) -> str:
    """Cyfry numeru bez zer wiodących („SAP 0087020188" → „87020188")."""
    return "".join(_DIGITS.findall(value or "")).lstrip("0")


def same_order_number(hint: Optional[str], order_number: str) -> bool:
    """Czy numer z „Uwag" to DOKŁADNIE ten numer zamówienia (po cyfrach).

    Równość, nie zawieranie się: „2026" z „09/2026" zawiera się w
    „OIT/0189/2026/ITVM", a „445" w „4450012345" — to inne zamówienia.
    Numer bez cyfr nie pasuje do niczego.
    """
    hint_digits = order_digits(hint)
    return bool(hint_digits) and hint_digits == order_digits(order_number)


def binds_as_order_number(
    hint: Optional[str],
    *,
    client_id: Optional[int],
    order_numbers: Optional[finance_order_matching.OrderNumberIndex],
) -> bool:
    """Czy numer z „Uwag" reguła wiązania uznaje za numer zamówienia klienta.

    Ta sama reguła co import MD (``_authoritative_md_hints``): u Polkomtela
    każdy ciąg cyfr jest numerem SAP, u pozostałych klientów wiąże wyłącznie
    numer ZNANY jako numer zamówienia tego klienta, a u klienta z numerami
    z samych cyfr także dostatecznie długi ciąg
    (``finance_order_matching.explicit_order_hints``). „Uwagi” niosą też inne
    liczby („delegacja 445”, „08/2026”) — import je ignoruje, więc okno
    zużycia nie może ich nazywać „innym numerem zamówienia” (audyt 25.09.2026,
    runda 4).
    """
    if not order_digits(hint) or client_id is None:
        return False
    if client_id == finance_order_matching.POLKOMTEL_CLIENT_ID:
        return True
    return bool(
        finance_order_matching.explicit_order_hints(
            [str(hint)], order_numbers, {client_id}
        )
    )


def is_foreign_number(
    hint: Optional[str],
    order_number: str,
    *,
    client_id: Optional[int],
    order_numbers: Optional[finance_order_matching.OrderNumberIndex],
) -> bool:
    """Czy numer z „Uwag" wskazuje INNE zamówienie niż ``order_number``.

    Brak numeru w arkuszu (albo numer zamówienia bez cyfr) nie jest obcym
    numerem — nie ma czego porównać. Liczba, której reguła wiązania nie uznaje
    za numer zamówienia tego klienta (``binds_as_order_number``), też nie.
    """
    if not order_digits(hint) or not order_digits(order_number):
        return False
    if same_order_number(hint, order_number):
        return False
    return binds_as_order_number(hint, client_id=client_id, order_numbers=order_numbers)


def build_consumption_view(
    consumptions: list[ConsumptionIn],
    *,
    remaining: Optional[Decimal],
    import_refs: dict[str, list[ImportRefIn]],
    corrections: list[CorrectionEventIn],
    order_number: str,
    client_id: Optional[int],
    order_numbers: Optional[finance_order_matching.OrderNumberIndex],
) -> ConsumptionView:
    ordered = sorted(consumptions, key=lambda c: c.period_month)
    used = sum((Decimal(str(c.md_reported)) for c in ordered), ZERO)

    # Saldo po miesiącu liczone WSTECZ od dzisiejszej pozostałości: ostatni
    # miesiąc zgadza się z paskiem karty także wtedy, gdy budżet zmieniały
    # zamiany, przejęcia albo ręczna korekta.
    balances: dict[str, Optional[Decimal]] = {}
    later = ZERO
    for item in reversed(ordered):
        balances[item.period_month] = (
            None if remaining is None else Decimal(str(remaining)) + later
        )
        later += Decimal(str(item.md_reported))

    by_month: dict[str, list[CorrectionOut]] = {}
    removed: list[CorrectionOut] = []
    seen_manual: set[str] = set()
    for event in sorted(corrections, key=lambda e: e.created_at):
        payload = event.payload or {}
        month = payload.get("period_month")
        if not isinstance(month, str):
            continue
        is_removed = "removed_md" in payload
        from_md = _decimal(
            payload.get("removed_md") if is_removed else payload.get("previous")
        )
        if from_md is None or from_md == ZERO:
            from_source = "none"
        elif month in seen_manual:
            from_source = "manual"
        elif import_refs.get(month):
            from_source = "import"
        else:
            from_source = "manual"
        correction = CorrectionOut(
            created_at=event.created_at,
            period_month=month,
            author_name=event.author_name,
            from_md=from_md if from_source != "none" else None,
            from_source=from_source,
            to_md=None if is_removed else _decimal(payload.get("md_reported")),
            removed=is_removed,
        )
        if is_removed:
            seen_manual.discard(month)
        else:
            seen_manual.add(month)
        by_month.setdefault(month, []).append(correction)

    present = {c.period_month for c in ordered}
    for month, items in by_month.items():
        if month not in present:
            removed.extend(items)

    months: dict[str, MonthOut] = {}
    foreign: list[tuple[str, ImportRefOut]] = []
    for item in ordered:
        refs = [
            ImportRefOut(
                import_id=ref.import_id,
                row_number=ref.row_number,
                order_number_hint=ref.order_number_hint,
                md_reported=ref.md_reported,
                foreign=is_foreign_number(
                    ref.order_number_hint,
                    order_number,
                    client_id=client_id,
                    order_numbers=order_numbers,
                ),
            )
            for ref in import_refs.get(item.period_month, [])
        ]
        for ref in refs:
            if ref.foreign:
                foreign.append((item.period_month, ref))
        month_corrections = by_month.get(item.period_month, [])
        if item.source == "import":
            kind = "import"
        elif refs or any(c.from_source == "import" for c in month_corrections):
            kind = "manual_correction"
        else:
            kind = "manual"
        months[item.period_month] = MonthOut(
            period_month=item.period_month,
            source_kind=kind,
            balance_after=balances.get(item.period_month),
            import_rows=refs,
            corrections=month_corrections,
        )
    return ConsumptionView(months=months, removed=removed, foreign=foreign, used=used)
