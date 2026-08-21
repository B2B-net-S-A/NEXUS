"""Import Nordea: nagłówki stawek, podgląd nadpisań i data biegu.

Trzy awarie z jednej rodziny — wszystkie CICHE. Plik zapisuje się, raport jest
zielony, a kwota/dzień w bazie opisuje co innego, niż operator widział przed
zapisem.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.nordea_order_import import (
    MATCH_CURRENT,
    MATCH_EXACT,
    MATCH_ONLY_ORDER,
    NordeaImportError,
    NordeaRow,
    _pick_existing_order,
    parse_nordea_csv,
)

_HEADER = (
    "Numer zamówienia;Kontraktor;Line manager;Start date;End date;"
    "Stawka  przychodowa;Stawka z umowy ramowej"
)


def _csv(header: str, *rows: str) -> bytes:
    return ("﻿" + "\n".join([header, *rows])).encode("utf-8")


# ── Nagłówki: żadnego zgadywania po pozycji dla kolumn z kwotami ────────────


def test_double_space_in_the_rate_header_still_matches():
    """Historyczne pliki mają dwie spacje — i to nie wymaga fallbacku.

    `_header_key` zdejmuje wszystko poza [a-z0-9], więc dopasowanie semantyczne
    łapie oba warianty. Ten test jest podkładką pod test poniżej: dowodzi, że
    zaostrzenie walidacji nie odcina realnych plików Finansów.
    """

    parsed = parse_nordea_csv(
        _csv(_HEADER, "279411;Paweł Włodarczyk;M;25.02.2026;23.08.2026;185;178")
    )
    assert parsed[0].revenue_rate == Decimal("185")
    assert parsed[0].framework_rate == Decimal("178.00")


def test_renamed_rate_header_is_refused_instead_of_silently_shifting_columns():
    """Zmieniony nagłówek stawki = błąd z nazwą kolumny, nie cicha podmiana.

    Regresja, której to broni: przy zmienionym nagłówku i dołożonej kolumnie
    `setdefault` przypinał „stawkę przychodową" do indeksu 5, czyli tutaj do
    stawki RAMOWEJ. Plik parsował się bez słowa, a raport dry-run pokazywał
    tylko `orders_updated: N` — bez ani jednej kwoty, więc nie było jak tego
    zauważyć przed zapisem.
    """

    header = (
        "Numer zamówienia;Kontraktor;Line manager;Start date;End date;"
        "Centrum kosztów;Stawka przychodowa netto;Stawka z umowy ramowej"
    )
    with pytest.raises(NordeaImportError) as exc:
        parse_nordea_csv(
            _csv(header, "279411;Paweł Włodarczyk;M;25.02.2026;23.08.2026;CC1;185;178")
        )
    message = str(exc.value)
    assert "Stawka przychodowa" in message
    # Komunikat musi wskazywać, CO przyszło — inaczej operator nie wie, co poprawić.
    assert "Stawka przychodowa netto" in message


def test_single_column_file_is_a_readable_error_not_an_index_crash():
    """Plik z jedną kolumną: 422 z komunikatem, nie IndexError (czyli 500)."""

    with pytest.raises(NordeaImportError, match="nagłówków"):
        parse_nordea_csv("Numer zamówienia\n279411\n".encode("utf-8"))


# ── Dopasowanie: która heurystyka i według jakiego „dziś" ───────────────────


class _FakeOrder:
    def __init__(self, id: int, title: str, start: date, end: date):
        self.id = id
        self.title = title
        self.start_date = start
        self.end_date = end
        self.order_group_id = None
        self.status = "active"


class _FakeContract:
    def __init__(self, orders: list[_FakeOrder]):
        self.client_orders = orders


def _row(number: str, start: date, end: date) -> NordeaRow:
    return NordeaRow(
        row_number=2,
        order_number=number,
        contractor_name="Jan Kowalski",
        start_date=start,
        end_date=end,
        revenue_rate=Decimal("185"),
        framework_rate=Decimal("178.00"),
    )


def test_current_order_heuristic_follows_the_supplied_day_not_the_container_clock():
    """„Zamówienie obejmujące dziś" zależy od przekazanej daty.

    Wcześniej brała się z `date.today()`, czyli z zegara kontenera w UTC —
    a daty w pliku Nordea są handlowe, w kalendarzu polskim. Test przesuwa
    „dziś" o pół roku i sprawdza, że wynik się przełącza: dowodzi, że funkcja
    nie zagląda już do zegara.
    """

    first_half = _FakeOrder(1, "111", date(2026, 1, 1), date(2026, 6, 30))
    second_half = _FakeOrder(2, "222", date(2026, 7, 1), date(2026, 12, 31))
    contract = _FakeContract([first_half, second_half])
    row = _row("279411", date(2026, 3, 15), date(2026, 9, 15))

    picked, kind = _pick_existing_order(
        contract, row, first_for_contractor=True, today=date(2026, 3, 1)
    )
    assert (picked.id, kind) == (1, MATCH_CURRENT)

    picked, kind = _pick_existing_order(
        contract, row, first_for_contractor=True, today=date(2026, 8, 1)
    )
    assert (picked.id, kind) == (2, MATCH_CURRENT)


def test_exact_number_match_is_reported_as_exact():
    contract = _FakeContract(
        [_FakeOrder(1, "279411", date(2026, 1, 1), date(2026, 6, 30))]
    )
    picked, kind = _pick_existing_order(
        contract,
        _row("279411", date(2026, 2, 1), date(2026, 8, 1)),
        first_for_contractor=True,
        today=date(2026, 3, 1),
    )
    assert (picked.id, kind) == (1, MATCH_EXACT)


def test_sole_order_match_is_flagged_as_a_guess():
    """Jedyne zamówienie kontraktora dostaje etykietę heurystyki, nie „exact".

    To jest dokładnie ten przypadek, w którym żywe zamówienie „222" dostaje
    numer, okres i stawkę z historycznego wiersza pliku.
    """

    contract = _FakeContract([_FakeOrder(7, "222", date(2026, 1, 1), date(2026, 12, 31))])
    picked, kind = _pick_existing_order(
        contract,
        _row("279411", date(2026, 2, 25), date(2026, 8, 23)),
        first_for_contractor=True,
        today=date(2026, 3, 1),
    )
    assert (picked.id, kind) == (7, MATCH_ONLY_ORDER)


def test_later_rows_never_fall_back_to_guessing():
    """Tylko pierwszy wiersz osoby wolno dopasować heurystyką."""

    contract = _FakeContract([_FakeOrder(7, "222", date(2026, 1, 1), date(2026, 12, 31))])
    picked, kind = _pick_existing_order(
        contract,
        _row("279411", date(2026, 2, 25), date(2026, 8, 23)),
        first_for_contractor=False,
        today=date(2026, 3, 1),
    )
    assert (picked, kind) == (None, None)


# ── Podgląd: raport pokazuje, KTÓRE zamówienie i czym zostanie nadpisane ────


async def _seed_nordea() -> tuple[int, int, int, str]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus
    import uuid

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Nordea Bank ABP {suffix}")
        candidate = Candidate(
            name="Ewa",
            lastname=f"Podgladowska {suffix}",
            email=f"nordea-preview-{suffix}@example.com",
        )
        db.add_all([client, candidate])
        await db.commit()
        await db.refresh(client)
        await db.refresh(candidate)
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=date.today() - timedelta(days=365),
            rate_candidate=Decimal("123.456"),
            rate_client=Decimal("150.000"),
            framework_rate=Decimal("110.00"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="222",
            status=ClientOrderStatus.active,
            start_date=date.today() - timedelta(days=100),
            end_date=date.today() + timedelta(days=200),
            rate_client=Decimal("149.000"),
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return (
            client.id,
            contract.id,
            order.id,
            f"{candidate.name} {candidate.lastname}",
        )


def _import_csv(name: str, number: str, start: date, end: date) -> bytes:
    return "\n".join(
        [
            _HEADER,
            ";".join(
                [
                    number,
                    name,
                    "Manager",
                    start.strftime("%d.%m.%Y"),
                    end.strftime("%d.%m.%Y"),
                    "185",
                    "178",
                ]
            ),
        ]
    ).encode("utf-8")


async def test_dry_run_names_the_overwritten_order_and_both_values(
    app_client, app_auth_headers: dict[str, str]
):
    """Podgląd pokazuje id zamówienia, użytą heurystykę i wartości przed → po.

    Regresja, której to broni: raport zwracał wyłącznie liczniki
    (`orders_updated: 1`), więc nadpisanie żywego zamówienia „222" numerem,
    okresem i stawką z historycznego wiersza pliku było z podglądu
    NIEODRÓŻNIALNE od aktualizacji tego samego zamówienia.
    """

    client_id, _, order_id, name = await _seed_nordea()
    content = _import_csv(
        name, "279411", date(2026, 2, 25), date.today() + timedelta(days=30)
    )

    preview = await app_client.post(
        f"/api/admin/clients/{client_id}/nordea-orders/import",
        params={"dry_run": "true"},
        headers=app_auth_headers,
        files={"file": ("Nordea.csv", content, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()

    assert body["orders_updated"] == 1
    assert body["fuzzy_matched"] == 1, "dopasowanie zeszło poniżej dokładnego numeru"
    assert len(body["order_changes"]) == 1
    change = body["order_changes"][0]
    assert change["order_id"] == order_id
    assert change["exact_number_match"] is False
    assert change["match"] == MATCH_ONLY_ORDER
    assert change["before"]["order_number"] == "222"
    assert change["after"]["order_number"] == "279411"
    assert Decimal(change["before"]["revenue_rate"]) == Decimal("149")
    assert Decimal(change["after"]["revenue_rate"]) == Decimal("185")


async def test_completed_status_follows_the_business_calendar_not_utc_midnight(
    app_client, app_auth_headers: dict[str, str], monkeypatch
):
    """Status zamówienia rozstrzyga „dziś" firmy, nie zegar kontenera.

    Podmieniamy `business_today` na dzień PO końcu okresu z pliku: gdyby kod
    dalej wołał `date.today()`, zamówienie zostałoby `active`. Objaw
    produkcyjny jest wąski (import odpala człowiek), ale cichy — między 00:00
    a 02:00 czasu warszawskiego UTC pokazuje jeszcze poprzednią dobę.
    """

    from app.services import nordea_order_import as service

    client_id, _, order_id, name = await _seed_nordea()
    end = date.today() + timedelta(days=5)
    monkeypatch.setattr(service, "business_today", lambda: end + timedelta(days=1))

    applied = await app_client.post(
        f"/api/admin/clients/{client_id}/nordea-orders/import",
        params={"dry_run": "false"},
        headers=app_auth_headers,
        files={
            "file": (
                "Nordea.csv",
                _import_csv(name, "279411", date.today() - timedelta(days=10), end),
                "text/csv",
            )
        },
    )
    assert applied.status_code == 200, applied.text

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        assert str(getattr(order.status, "value", order.status)) == "completed"
