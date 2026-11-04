"""Runda 7 audytu (N3) — import rejestru umów z Excela, część bez bazy.

Parser, klucze wierszy, dopasowanie klienta i rekrutera. Nazwiska są fikcyjne,
dobrane tak, żeby odtwarzały problem (człon „umow”/„numer” w nazwisku).
"""

from __future__ import annotations

import io
from datetime import date
from types import SimpleNamespace
from typing import Any, Optional

from openpyxl import Workbook

from app.services.b2b_register_import.matching import (
    ClientResolver,
    Match,
    RecruiterResolver,
)
from app.services.b2b_register_import.parser import parse_register
from app.services.b2b_register_import.service import (
    _legacy_number_key,
    _number_key,
    _row_digest,
    _client_identity,
    assign_row_keys,
)
from tests.test_b2b_register_import_parser import (
    HEADERS,
    build_register,
    contract_row,
    no_business_row,
)


# ── N3-3: nazwisko z „umow”/„numer” to nie legenda ──────────────────────────


def test_surname_containing_legend_word_is_a_contract_row():
    payload = build_register(
        [
            contract_row("Umowska-Testowa Ewa", 1800, signing=date(2025, 1, 2)),
            contract_row("Numerowski Adam", 1801, signing=date(2025, 1, 3)),
            contract_row("Kowalik Jan (umowa zlecenie)", "zlecenie", kind="zlecenie"),
        ],
        no_business=[no_business_row("Ewa Umowska-Testowa", date(2025, 1, 6))],
    )
    parsed = parse_register(payload)
    names = [row.name_raw for row in parsed.contracts]
    assert names == [
        "Umowska-Testowa Ewa",
        "Numerowski Adam",
        "Kowalik Jan (umowa zlecenie)",
    ]
    # Legenda pod tabelą nadal odpada.
    assert [s["reason"] for s in parsed.skipped].count("legend") == 4
    assert [nb.name_raw for nb in parsed.no_business] == ["Ewa Umowska-Testowa"]


def test_legend_in_no_business_sheet_leaves_a_trace():
    payload = build_register(
        [contract_row("Testowa Ola", 1802, signing=date(2025, 1, 2))],
        no_business=[
            {"values": ["Umowy zlecenie bez aneksu", None, None, None, None, None]}
        ],
    )
    parsed = parse_register(payload)
    assert parsed.no_business == []
    assert {"row": 2, "reason": "legend", "sheet": "bez_dzialalnosci"} in (
        parsed.skipped
    )


# ── N3-4: numer z dopiskiem to nadal numer ──────────────────────────────────


def test_number_with_year_prefix_or_thousands_space_is_a_number():
    payload = build_register(
        [
            contract_row("Pierwsza Anna", "1517/2026", signing=date(2026, 1, 2)),
            contract_row("Druga Beata", "nr 1518", signing=date(2026, 1, 3)),
            contract_row("Trzecia Celina", "1 519", signing=date(2026, 1, 4)),
            contract_row("Czwarta Dorota", "1 520", signing=date(2026, 1, 5)),
            contract_row("Piąta Ewa", "264A", signing=date(2019, 1, 5)),
        ],
        legend=False,
    )
    numbers = [(r.number_raw, r.number_int) for r in parse_register(payload).contracts]
    assert numbers == [
        ("1517/2026", 1517),
        ("nr 1518", 1518),
        ("1 519", 1519),
        ("1 520", 1520),
        ("264A", None),
    ]


def _row(number_raw: Optional[str], number_int: Optional[int] = None) -> Any:
    return SimpleNamespace(number_raw=number_raw, number_int=number_int)


def test_number_key_ignores_dash_variants_and_keeps_legacy_key():
    assert _number_key(_row("1519-A")) == _number_key(_row("1519 – A")) == "n:1519-a"
    # Klucz sprzed rundy 7 — import odnajduje po nim zapisany wiersz.
    assert _legacy_number_key(_row("1519 – A")) == "n:1519–a"
    assert _legacy_number_key(_row("1517/2026", 1517)) == "n:1517/2026"
    assert _number_key(_row("1517/2026", 1517)) == "n:1517"
    assert _legacy_number_key(_row("1517", 1517)) == "n:1517"


# ── N3-5: arkusz zamówień nie udaje arkusza umów ────────────────────────────


def test_orders_sheet_is_not_taken_for_the_register():
    workbook = Workbook()
    orders = workbook.active
    orders.title = "Zamówienia"
    orders.append(["Nazwisko", "Numer zamówienia", "Klient"])
    orders.append(["Zamówieniowy Jan", "4500012345", "BIK"])
    register = workbook.create_sheet("Umowy B2B 2026")
    register.append(HEADERS)
    register.append(
        contract_row("Rejestrowa Ala", 1700, signing=date(2026, 2, 2))["values"]
    )
    buffer = io.BytesIO()
    workbook.save(buffer)
    contracts = parse_register(buffer.getvalue()).contracts
    assert [(c.name_raw, c.number_int) for c in contracts] == [("Rejestrowa Ala", 1700)]


# ── N3-9: liczba seryjna Excela w kolumnie daty ─────────────────────────────


def test_excel_serial_number_in_date_column_is_a_date():
    payload = build_register(
        [
            contract_row("Seryjna Iga", 1703, signing=46054, start=46068),
            contract_row("Słowna Iza", 1704, signing="1 lutego 2026"),
        ],
        legend=False,
    )
    iga, iza = parse_register(payload).contracts
    assert iga.signing_date == date(2026, 2, 1)
    assert iga.start_date == date(2026, 2, 15)
    assert "signing_date_unparsed" in iza.flags


# ── N3-6: pusta komórka klienta to nie umowa wewnętrzna ─────────────────────


def test_empty_client_cell_is_unknown_not_internal():
    resolver = ClientResolver({}, {}, {})
    assert resolver.resolve(None).kind == "unmatched"
    assert resolver.resolve("   ").kind == "unmatched"
    assert resolver.resolve("B2B.NET").kind == "internal"


# ── N3-8: rekruter nie jest zgadywany ───────────────────────────────────────


def test_recruiter_is_not_guessed_among_several_accounts():
    resolver = RecruiterResolver(
        [
            (1, ["katarzyna", "odeszla"], False, "Katarzyna Odeszła"),
            (2, ["katarzyna", "obecna"], True, "Katarzyna Obecna"),
        ]
    )
    assert resolver.resolve("Kasia") == Match("ambiguous", count=2)
    assert resolver.resolve("Kasia Obecna").id == 2


# ── N3-2: klucz wiersza bez numeru nie zależy od kolejności i pisowni ───────


def test_row_digest_ignores_legal_form_and_numberless_text():
    tokens = frozenset({"ewa", "testowa"})
    unmatched = Match("unmatched")
    base = _row_digest(
        tokens, _client_identity("Klient Testowy", unmatched), "mandate", "bez numeru"
    )
    assert base == _row_digest(
        tokens, _client_identity("Klient Testowy SA", unmatched), "mandate", "zlecenie"
    )
    assert base == _row_digest(
        tokens,
        _client_identity("Klient Testowy Sp. z o.o.", unmatched),
        "mandate",
        None,
    )
    assert base != _row_digest(
        tokens, _client_identity("Inny Klient", unmatched), "mandate", None
    )


def _plan(signing: Optional[date], start: Optional[date] = None) -> dict[str, Any]:
    return {
        "key": None,
        "digest": "d",
        "row": SimpleNamespace(signing_date=signing, start_date=start),
    }


def _stored(
    row_id: int, key: str, signing: Optional[date], start: Optional[date] = None
) -> Any:
    return SimpleNamespace(
        id=row_id, source_key=key, signing_date=signing, start_date=start
    )


def test_sorted_sheet_keeps_each_contract_with_its_record():
    """Dwie umowy zlecenia tej samej osoby u tego samego klienta — arkusz
    posortowany odwrotnie niż przy pierwszym imporcie."""
    older = _stored(10, "h:d", date(2023, 1, 5))
    newer = _stored(11, "h:d:1", date(2025, 3, 1))
    plans = [_plan(date(2025, 3, 1)), _plan(date(2023, 1, 5))]
    assign_row_keys(plans, [("d", older), ("d", newer)], taken_keys=set())
    assert [p["key"] for p in plans] == ["h:d:1", "h:d"]


def test_date_filled_in_later_still_pairs_and_new_contract_gets_a_free_key():
    stored = _stored(10, "h:oldformat", None)
    plans = [_plan(date(2026, 2, 1)), _plan(date(2026, 5, 1))]
    assign_row_keys(plans, [("d", stored)], taken_keys={"h:d"})
    assert plans[0]["key"] == "h:oldformat"
    assert plans[1]["key"] == "h:d:1"
