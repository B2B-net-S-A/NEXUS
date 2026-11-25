"""Kontrola formalna faktury sprzedaży (``client_invoicing.sale_checks``) — bez bazy.

Osoby, kody i numery fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.client_invoicing.sale_checks import (
    Line,
    Owner,
    person_id_problems,
    quantity_problems,
    sale_date_problems,
    without_contract_problems,
    working_days,
)

KNOWN = SimpleNamespace(
    people=(("jan", "przykladowy"), ("ewa", "testowa")),
    person_numbers=frozenset({"A123456"}),
)
OWNERS = {
    "A123456": (Owner(1, "Jan Przykładowy"),),
    "B765432": (Owner(2, "Ewa Testowa"),),
}


def _line(name: str, **kw) -> Line:
    return Line(name=name, **kw)


def test_dni_robocze_pazdziernika_i_listopada_2026() -> None:
    assert working_days(2026, 10) == 22
    # 11.11 i 1.11 (niedziela) — 20 dni roboczych.
    assert working_days(2026, 11) == 20


def test_data_sprzedazy_poza_okresem_uslugi() -> None:
    [problem] = sale_date_problems(date(2026, 6, 14), (2026, 5), [_line("Usługi")])
    assert "14.06.2026" in problem and "maj 2026" in problem
    assert sale_date_problems(date(2026, 5, 31), (2026, 5), [_line("Usługi")]) == []


def test_miesiac_w_nazwie_pozycji_inny_niz_data_sprzedazy() -> None:
    lines = [_line("Usługi IT — maj 2026"), _line("Usługi IT za 05.2026")]
    [problem] = sale_date_problems(date(2026, 6, 14), None, lines)
    assert "pozycja 1" in problem and "maj 2026" in problem
    assert sale_date_problems(date(2026, 5, 31), None, lines) == []
    # Inny rok przy tym samym miesiącu to też błąd.
    assert sale_date_problems(date(2026, 10, 31), None, [_line("październik 2025")])


def test_wiecej_md_albo_godzin_niz_dni_robocze() -> None:
    lines = [
        _line("a", quantity=Decimal("23"), unit="MD"),
        _line("b", quantity=Decimal("22"), unit="MD"),
        _line("c", quantity=Decimal("177"), unit="godz."),
        _line("d", quantity=Decimal("176"), unit="h"),
        _line("e", quantity=Decimal("40"), unit="szt."),
    ]
    problems = quantity_problems(lines, (2026, 10))
    assert len(problems) == 2
    assert (
        problems[0].startswith("Pozycja 1: 23 MD") and "22 dni roboczych" in problems[0]
    )
    assert problems[1].startswith("Pozycja 3: 177 h") and "176 h" in problems[1]


def test_kod_osoby_poprawny_przechodzi() -> None:
    line = _line(
        "NIDS:1, IT, Contact: Anna Kliencka, Contractor Jan Przykładowy ID: A123456"
    )
    assert person_id_problems([line], OWNERS, KNOWN) == []
    no_colon = _line("Contractor: Jan Przykładowy ID A123456")
    assert person_id_problems([no_colon], OWNERS, KNOWN) == []


def test_imie_w_polu_id_zamiast_kodu() -> None:
    line = _line(
        "Contact: Anna Kliencka, Contractor Jan Przykładowy ID: Jan Przykładowy"
    )
    [problem] = person_id_problems([line], OWNERS, KNOWN)
    assert "w polu ID jest „Jan Przykładowy”" in problem


def test_osoba_klienta_jako_contractor() -> None:
    line = _line("Contact: Anna Kliencka, Contractor Anna Kliencka ID: A123456")
    problems = person_id_problems([line], OWNERS, KNOWN)
    assert any("osobę klienta" in problem for problem in problems)


def test_kod_innej_osoby_i_kod_nieznany() -> None:
    other = _line("Contractor Jan Przykładowy ID: B765432")
    [problem] = person_id_problems([other], OWNERS, KNOWN)
    assert "należy w NEXUSIE do Ewa Testowa" in problem
    # Osoba z kontraktem bez numeru w NEXUSIE — brak danych, nie błąd faktury.
    gap = _line("Contractor Jan Przykładowy ID: C111111")
    [problem] = person_id_problems([gap], OWNERS, KNOWN)
    assert "NEXUS nie zna kodu C111111" in problem
    stranger = _line("Contractor Piotr Obcy ID: C111111")
    [problem] = person_id_problems([stranger], OWNERS, KNOWN)
    assert "nie jest w NEXUSIE numerem żadnej osoby" in problem


def test_brak_id_i_pozycja_bez_contractor() -> None:
    [problem] = person_id_problems(
        [_line("Contractor Jan Przykładowy, HOTEL")], OWNERS, KNOWN
    )
    assert "brak „ID" in problem
    assert (
        person_id_problems([_line("Usługi IT, NIDS: 2026-000001")], OWNERS, KNOWN) == []
    )


def test_kod_z_kontraktu_pozycji_wygrywa_z_imieniem() -> None:
    line = _line("Contractor Janek Przykładowy ID: A123456", contract_id=1)
    assert person_id_problems([line], OWNERS, KNOWN) == []
    wrong = _line("Contractor Jan Przykładowy ID: A123456", contract_id=2)
    assert len(person_id_problems([wrong], OWNERS, KNOWN)) == 1


def test_osoba_bez_kontraktu_u_klienta() -> None:
    lines = [
        _line("Usługi — Piotr Obcy", consultant="Piotr Obcy"),
        _line("Contractor Marek Nieznany ID: Z999999"),
        _line("Usługi — Jan Przykładowy", consultant="Jan Przykładowy"),
        _line("Usługi — ktoś", consultant="Piotr Obcy", contract_id=7),
    ]
    problems = without_contract_problems(lines, KNOWN)
    assert problems == [
        "Pozycja 1: Piotr Obcy nie ma kontraktu u tego klienta.",
        "Pozycja 2: Marek Nieznany (ID Z999999) nie ma kontraktu u tego klienta.",
    ]
