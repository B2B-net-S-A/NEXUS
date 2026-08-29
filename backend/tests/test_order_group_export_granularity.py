"""Eksport zamówień i bramka przywracania — czyste funkcje, bez bazy.

Testy są czysto jednostkowe — budują ``OrderGroupRead`` wprost i wołają
``export_rows_for_group``. Bez bazy, bo regresja jest tu CICHA: arkusz się
generuje, liczby są arytmetycznie poprawne, tylko opisują co innego niż
nagłówek obok. Taki błąd wychodzi dopiero przy rozmowie o fakturze.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.client_order_groups import assert_group_is_reopenable
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_EXHAUSTED,
    GROUP_STATUS_SCHEDULED,
)
from app.schemas.client_order_group import OrderGroupRead, OrderLineRead
from app.services.order_excel_export import (
    COST_GROUP_TOTAL_LABEL,
    MD_GROUP_TOTAL_LABEL,
    export_rows_for_group,
)


def _line(name: str, **overrides) -> OrderLineRead:
    payload: dict = {
        "id": abs(hash(name)) % 10_000,
        "contract_id": 1,
        "consultant_name": name,
        "status": "active",
        "is_active": True,
        "rate_cost": Decimal("1000"),
        "rate_revenue": Decimal("1200"),
    }
    payload.update(overrides)
    return OrderLineRead(**payload)


def _group(**overrides) -> OrderGroupRead:
    payload: dict = {
        "id": 1,
        "client_id": 1,
        "order_number": "445",
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 12, 31),
        "created_at": "2026-01-01T00:00:00",
    }
    payload.update(overrides)
    return OrderGroupRead(**payload)


def test_cost_order_amount_appears_once_not_per_consultant():
    """Kwota grupy nie powiela się w wierszach osób.

    Regresja, której to broni: przy trzech konsultantach suma kolumny „Liczba
    MD / Kwota zamówienia" dawała trzykrotność wartości zamówienia, a wiersz
    „zużycie 5 000 z 200 000" czytał się jak budżet tej jednej osoby.
    """

    group = _group(
        is_cost_based=True,
        budget_amount=Decimal("200000"),
        lines=[
            _line("Anna Kowalska", invoiced_total=Decimal("5000")),
            _line("Jan Nowak", invoiced_total=Decimal("7000")),
            _line("Ewa Wiśniewska", invoiced_total=Decimal("0")),
        ],
    )

    rows = export_rows_for_group(group)

    assert len(rows) == 4  # wiersz zbiorczy + trzy osoby
    total_row, *consultants = rows
    assert total_row.consultant_name == COST_GROUP_TOTAL_LABEL
    assert total_row.allocation == Decimal("200000")
    assert total_row.consumption is None
    assert [row.allocation for row in consultants] == [None, None, None]
    assert [row.consumption for row in consultants] == [
        Decimal("5000"),
        Decimal("7000"),
        Decimal("0"),
    ]
    # Obie kolumny sumują się do prawdy — arkusz ma auto-filtr i ludzie go sumują.
    assert sum(row.allocation for row in rows if row.allocation is not None) == Decimal(
        "200000"
    )
    assert sum(
        row.consumption for row in rows if row.consumption is not None
    ) == Decimal("12000")


def test_md_order_keeps_the_budget_per_consultant():
    """Tryb MD zostaje nietknięty: tam budżet NAPRAWDĘ jest per osoba."""

    group = _group(
        is_cost_based=False,
        lines=[
            _line(
                "Anna Kowalska",
                md_total=Decimal("50"),
                md_remaining=Decimal("30"),
            ),
            _line(
                "Jan Nowak",
                md_total=Decimal("20"),
                md_remaining=Decimal("20"),
                md_manual_adjustment=Decimal("5"),
            ),
        ],
    )

    rows = export_rows_for_group(group)

    assert len(rows) == 2  # bez wiersza zbiorczego
    assert [row.consultant_name for row in rows] == ["Anna Kowalska", "Jan Nowak"]
    assert [row.allocation for row in rows] == [Decimal("50"), Decimal("20")]
    assert [row.consumption for row in rows] == [Decimal("20"), Decimal("5")]


def test_shared_md_order_amount_and_usage_appear_once_for_the_group():
    group = _group(
        is_md_budget_based=True,
        md_budget_total=Decimal("80"),
        md_budget_used=Decimal("35"),
        md_budget_remaining=Decimal("45"),
        lines=[_line("Anna Kowalska"), _line("Jan Nowak")],
    )

    rows = export_rows_for_group(group)

    assert len(rows) == 3
    total_row, *consultants = rows
    assert total_row.consultant_name == MD_GROUP_TOTAL_LABEL
    assert total_row.allocation == Decimal("80")
    assert total_row.consumption == Decimal("35")
    assert [row.allocation for row in consultants] == [None, None]
    assert [row.consumption for row in consultants] == [None, None]


def test_cost_order_without_consultants_still_carries_the_amount():
    """Grupa bez obsady to nadal jeden wiersz z kwotą — i bez etykiety zbiorczej."""

    rows = export_rows_for_group(
        _group(is_cost_based=True, budget_amount=Decimal("200000"), lines=[])
    )

    assert len(rows) == 1
    assert rows[0].consultant_name == ""
    assert rows[0].allocation == Decimal("200000")


def test_redacted_budget_does_not_invent_a_number():
    """Rola bez VIEW_FINANCE dostaje pustą kwotę, nie zero.

    ``_group_to_read`` zeruje `budget_amount` do `None`; wiersz zbiorczy ma
    wtedy zostać pusty. Zero czytałoby się jak „zamówienie bez pieniędzy".
    """

    rows = export_rows_for_group(
        _group(
            is_cost_based=True,
            budget_amount=None,
            lines=[_line("Anna Kowalska", invoiced_total=Decimal("5000"))],
        )
    )

    assert rows[0].consultant_name == COST_GROUP_TOTAL_LABEL
    assert rows[0].allocation is None


# ── Przywracanie: bramka musi być WYCZERPUJĄCA ─────────────────────────────


def test_only_a_manually_closed_order_can_be_reopened():
    """Zakończone ręcznie przechodzi — i tylko ono."""

    assert assert_group_is_reopenable(GROUP_STATUS_COMPLETED) is None


@pytest.mark.parametrize(
    "status",
    [GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED, GROUP_STATUS_EXHAUSTED],
)
def test_other_statuses_are_refused_with_409(status: str):
    """Zaplanowane wpadało w gałąź „zakończone" i wracało jako drugie aktywne.

    Regresja, której to broni: bramka znała trzy statusy i traktowała „nic
    z tych dwóch" jak `completed`, więc zamówienie przyszłe dostawało `active`
    przed datą startu, z liniami zostawionymi w `draft` — a materializer,
    który bierze kolejkę wyłącznie z wierszy `scheduled`, nie mógł już tego
    naprawić ani domknąć poprzednika.
    """

    with pytest.raises(HTTPException) as exc:
        assert_group_is_reopenable(status)
    assert exc.value.status_code == 409


def test_an_unknown_future_status_is_refused_instead_of_being_treated_as_closed():
    """Nowy status dorzucony do modelu bez zajrzenia w tę bramkę = 409.

    To jest ta sama pomyłka co wyżej, tylko o jedną iterację później: bramka
    domyślnie przepuszczająca wszystko nieznane zamienia każdy przyszły status
    w cichy skrót do `active`.
    """

    with pytest.raises(HTTPException) as exc:
        assert_group_is_reopenable("on_hold")
    assert exc.value.status_code == 409
