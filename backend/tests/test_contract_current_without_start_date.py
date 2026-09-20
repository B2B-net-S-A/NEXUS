"""Kontrakt bez daty startu JEST bieżący — brak wiedzy to nie „przyszłość”.

Audyt 18.09.2026, klient 15: kafel deklarował komplet (``active_mrr = 11 968``,
``active_contracts = 2``, ``unpriced = 0``), a trzy AKTYWNE kontrakty z żywymi
liniami zamówień (474, 475, 476) siedziały w „Planowanych”, bo nikt nie wpisał
im daty rozpoczęcia. Poza MRR zostało 13 920 PLN/mc — **54% realnej marży
klienta** — i nic na ekranie o tym nie mówiło.

Reguła jest wspólna dla profilu klienta, zakładki Analityka, rankingu Rady
i katalogu klientów (`is_current_contract`), więc test pilnuje jej w JEDNYM
miejscu i osobno sprawdza, że SQL katalogu jest jej lustrem.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from types import SimpleNamespace

from app.services.contractor_identity import current_contracts, is_current_contract

TODAY = date(2026, 9, 18)


def _contract(start: date | None) -> SimpleNamespace:
    return SimpleNamespace(start_date=start)


def test_contract_without_a_start_date_counts_as_current():
    assert is_current_contract(_contract(None), TODAY) is True


def test_a_future_start_is_still_planned():
    # „Planowany” to twierdzenie o PRZYSZŁOŚCI — wymaga daty, która nie nadeszła.
    assert is_current_contract(_contract(TODAY + timedelta(days=7)), TODAY) is False


def test_a_started_contract_is_unchanged():
    assert is_current_contract(_contract(TODAY), TODAY) is True
    assert is_current_contract(_contract(TODAY - timedelta(days=30)), TODAY) is True


def test_the_order_date_can_still_mark_a_dateless_contract_as_planned():
    # Umowa bez własnej daty, ale z zamówieniem startującym za tydzień, jest
    # planowana NAPRAWDĘ — i wołający, który tę datę zna, może ją podstawić.
    assert (
        is_current_contract(
            _contract(None), TODAY, fallback_start=TODAY + timedelta(days=7)
        )
        is False
    )
    assert (
        is_current_contract(
            _contract(None), TODAY, fallback_start=TODAY - timedelta(days=7)
        )
        is True
    )


def test_filter_keeps_input_order_and_the_dateless_contract():
    rows = [
        _contract(TODAY - timedelta(days=1)),
        _contract(None),
        _contract(TODAY + timedelta(days=1)),
    ]
    assert current_contracts(rows, TODAY) == [rows[0], rows[1]]


def test_client_directory_sql_mirrors_the_python_rule():
    """Licznik katalogu liczy TYCH SAMYCH ludzi co profil klienta.

    Katalog nie wczytuje kontraktów do Pythona (agreguje w SQL), więc reguła
    istnieje tam drugi raz — i to jest jedyne miejsce, w którym może się
    rozjechać. Przed poprawką miał twarde `start_date IS NOT NULL`.
    """
    source = open("app/api/client_directory.py", encoding="utf-8").read()
    assert "Contract.start_date.is_not(None)" not in source
    assert re.search(
        r"or_\(\s*Contract\.start_date\.is_\(None\),\s*Contract\.start_date <= as_of",
        source,
    ), "katalog klientów przestał dopuszczać kontrakt bez daty startu"
