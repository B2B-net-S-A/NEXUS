"""Odczyt raportu T4T, numery z opisów faktur do klienta i godziny z faktury
kontraktora (plan Nordei N1.1, N1.2, N1.4). Bez bazy; dane fikcyjne.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import openpyxl
import pytest

from app.models.contract import RateUnit
from app.services.client_settlements import t4t, time_reports

HEADER = [
    "Investment ID",
    "Name",
    "UserId",
    "EmploymentType",
    "TimePeriodStart",
    "TimePeriodFinish",
    "DateWorked",
    "Investment Name",
    "Sum of Hours",
    "TimesheetStatus",
    "TimesheetStatus Description",
    "ChargeCode",
    "New Resource Class",
    "ExternalCompanyName",
]


def _line(person: str, hours: float, status: int, day: int = 1) -> list[object]:
    return [
        "2020-000001",
        "Jan Testowy",
        person,
        "CONTRACTOR",
        datetime(2026, 9, 1),
        datetime(2026, 9, 6),
        datetime(2026, 9, day),
        "Projekt testowy",
        hours,
        status,
        "Approved" if status == 2 else "Submitted",
        "Project Work",
        "IT Consultants",
        "Spółka testowa",
    ]


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_arkusz_rozpoznany_po_kolumnach_nie_po_nazwie():
    content = _xlsx(
        {
            "pivot": [["UserId", "Name", "Sum of Hours"], ["M000001", "x", 8]],
            "Dowolna nazwa": [HEADER, _line("m000001", 8, 2), _line("M000002", 7.5, 1)],
        }
    )
    sheets = t4t.read(content)
    assert [s.name for s in sheets] == ["Dowolna nazwa"]
    rows = sheets[0].rows
    assert rows[0].person_no == "M000001"
    assert rows[0].period_start == date(2026, 9, 1)
    assert rows[1].hours == Decimal("7.5")
    assert rows[1].status == 1
    assert sheets[0].month == "2026-09"


def test_naglowek_ponizej_pierwszego_wiersza_i_puste_wiersze():
    content = _xlsx(
        {"Sheet1": [[None], ["Raport"], HEADER, [None] * 3, _line("M1234", 8, 2)]}
    )
    (sheet,) = t4t.read(content)
    assert len(sheet.rows) == 1
    assert sheet.skipped == 0


def test_wiersz_bez_godzin_albo_ze_zlym_statusem_jest_pominiety():
    bad_status = _line("M1234", 8, 2)
    bad_status[9] = 7
    no_hours = _line("M1234", 8, 2)
    no_hours[8] = None
    content = _xlsx({"Sheet1": [HEADER, _line("M1234", 8, 2), bad_status, no_hours]})
    (sheet,) = t4t.read(content)
    assert len(sheet.rows) == 1
    assert sheet.skipped == 2


def test_kilka_arkuszy_raportu_wymaga_wyboru():
    content = _xlsx(
        {
            "Sheet1": [HEADER, _line("M1234", 8, 1)],
            "Sheet1 (2)": [HEADER, _line("M1234", 8, 2)],
        }
    )
    sheets = t4t.read(content)
    with pytest.raises(t4t.T4tError, match="wybierz arkusz"):
        t4t.pick(sheets, None)
    assert t4t.pick(sheets, "Sheet1 (2)").rows[0].status == 2
    with pytest.raises(t4t.T4tError, match="nie ma arkusza"):
        t4t.pick(sheets, "Sheet9")


def test_plik_bez_raportu_i_nie_excel():
    with pytest.raises(t4t.T4tError, match="nie ma arkusza raportu"):
        t4t.read(_xlsx({"Arkusz1": [["Imię i nazwisko", "Numer"]]}))
    with pytest.raises(t4t.T4tError, match="nie jest plik"):
        t4t.read(b"%PDF-1.7 to nie excel")


def test_numery_osoby_i_nids_z_opisu_pozycji_faktury():
    name = "NIDS:2024-000001, IT Developer, Contact: Osoba Testowa, Firma Testowa ID:m012345"
    assert time_reports.person_numbers(name) == {"M012345"}
    assert time_reports.project_numbers(name) == {"2024-000001"}
    assert time_reports.person_numbers("Usługi IT za wrzesień") == set()


def _contract(
    rate: str | None, unit: RateUnit = RateUnit.hourly, currency: str = "PLN"
):
    return SimpleNamespace(
        rate_unit=unit,
        resolved_rate_candidate_currency=currency,
        effective_candidate_rate=lambda on: Decimal(rate) if rate else None,
    )


def _invoice(net: str | None, state: str = "known", currency: str = "PLN"):
    return SimpleNamespace(
        net_amount=Decimal(net) if net else None, nip_state=state, currency=currency
    )


def test_godziny_z_faktury_to_netto_przez_stawke_z_korekta():
    hours = time_reports.invoice_hours(
        _contract("100"), [_invoice("16800.00"), _invoice("800.00")], "2026-09"
    )
    assert hours is not None and hours.hours == Decimal("176.00")
    assert hours.note is None


def test_godziny_przy_stawce_dziennej_i_bez_stawki():
    daily = time_reports.invoice_hours(
        _contract("800", RateUnit.daily), [_invoice("17600.00")], "2026-09"
    )
    assert daily is not None and daily.hours == Decimal("176.00")
    missing = time_reports.invoice_hours(
        _contract(None), [_invoice("100.00")], "2026-09"
    )
    assert missing is not None and missing.hours is None
    assert missing.note == "Kontrakt bez stawki kosztowej."


def test_faktura_z_nipem_do_zatwierdzenia_nie_daje_godzin():
    found = time_reports.invoice_hours(
        _contract("100"), [_invoice("100.00", state="suggested")], "2026-09"
    )
    assert found is not None and found.hours is None
    assert "NIP" in (found.note or "")
    assert time_reports.invoice_hours(_contract("100"), [], "2026-09") is None


def test_inna_waluta_faktury_nie_daje_godzin():
    found = time_reports.invoice_hours(
        _contract("100"), [_invoice("100.00", currency="EUR")], "2026-09"
    )
    assert found is not None and found.hours is None


def test_imie_i_nazwisko_z_drugim_imieniem():
    assert time_reports._same_person(
        {"jan", "maria", "testowy"}, frozenset({"jan", "testowy"})
    )
    assert not time_reports._same_person({"jan", "testowy"}, frozenset({"jan", "inny"}))
    assert not time_reports._same_person({"testowy"}, frozenset({"testowy"}))
