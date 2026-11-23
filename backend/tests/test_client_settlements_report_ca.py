"""Raport zbiorczy Credit Agricole „Raport rozliczenia outsourcingu” → MD per osoba.

Bez bazy. Dane fikcyjne: osoby „Testowy Jan” i „Inna Anna”, projekty i stawki
wymyślone. Układ arkusza jak w raporcie klienta (IX 2026): wiersz na osobę i PID,
„TE” to MD, wiersz „ABS” ma godziny w „Czas 0%” i 0 TE, pod spodem „Podsumowanie”.
"""

from __future__ import annotations

import io
from decimal import Decimal

import openpyxl

from app.models.consultant_portal import CpDocument
from app.services.client_settlements import report_ca, rules_catalog, service

MONTH = "2026-09"
HEADER = [
    "Pracownik Nazwisko Imie",
    "Nr Ewid",
    "PID",
    "Nazwa Utworu",
    "Czas 0%",
    "Czas 100%",
    "Czas 150%",
    "Czas 200%",
    "TE",
    "Stawka Netto",
    "Kwota Netto",
    "Kwota Brutto",
]


def _row(name, pid, *, absent=0, hours=0, te=0, rate=800, overtime=0):
    return [name, "O-1", pid, "", absent, hours, overtime, 0, te, rate, te * rate, 0]


def ca_report(month_cell: str = "2026.09", rows=None) -> bytes:
    rows = rows or [
        _row("Testowy Jan", "ABS", absent=40),
        _row("Testowy Jan", "P1-01", hours=56, te=7),
        _row("Testowy Jan", "P2-01", hours=80, te=10),
        _row("Inna Anna", "BAU", hours=176, te=22, rate=700),
    ]
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Raport_rozliczenia_szyfrowanie"
    sheet.append(["Raport rozliczenia outsourcingu"])
    sheet.append([""])
    sheet.append(["Raport za miesiąc:", month_cell])
    sheet.append(["Dostawca usług", "Dostawca Testowy S.A."])
    sheet.append(["email", "dl@example.com"])
    sheet.append([""])
    sheet.append(HEADER)
    for row in rows:
        sheet.append(row)
    sheet.append([])
    sheet.append(["Podsumowanie"])
    sheet.append(["Nazwisko Imię", "", "", "", *HEADER[4:]])
    sheet.append(["Testowy Jan", "", "", "", 40, 136, 0, 0, 17, 800, 13600, 0])
    sheet.append(["Inna Anna", "", "", "", 0, 176, 0, 0, 22, 700, 15400, 0])
    sheet.append(["Total", "", "", "", "", "", "", "", "", "", 29000, 0])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _rules() -> dict:
    return rules_catalog.effective(
        {
            "proof.month": {"level": "block"},
            "proof.name_match": {"level": "warn"},
            "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
            "fields.md_month_limit": {"level": "off"},
        }
    )


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


def _evaluate(report, person: str, month: str = MONTH):
    return report_ca.evaluate(
        report,
        month=month,
        person_name=person,
        rules=_rules(),
        working_days=22,
    )


def test_raport_ca_md_z_te_per_osoba_sumuje_projekty():
    report = report_ca.parse(ca_report(), report_ca.XLSX)

    assert report is not None
    assert report.month == MONTH
    assert [person.name for person in report.people] == ["Testowy Jan", "Inna Anna"]
    jan = _evaluate(report, "Jan Testowy")
    assert jan.md_regular == Decimal("17.000")
    assert jan.md_extra == Decimal("0")
    # Godziny „Czas 0%” (nieobecność) nie są MD, ale stoją na karcie.
    assert "Nieobecność w raporcie: 40 h" in _titles(jan)
    assert _evaluate(report, "Anna Inna").md_regular == Decimal("22.000")


def test_osoba_spoza_raportu_nie_dostaje_md():
    report = report_ca.parse(ca_report(), report_ca.XLSX)

    assert _evaluate(report, "Piotr Obcy") is None


def test_raport_za_inny_miesiac_to_kontrola_bez_md():
    report = report_ca.parse(ca_report("2026.08"), report_ca.XLSX)

    result = _evaluate(report, "Jan Testowy")

    assert result.md_regular is None
    assert _titles(result)["Raport rozliczenia CA za inny miesiąc"] == "fail"


def test_nadgodziny_w_raporcie_stoja_na_karcie():
    rows = [_row("Testowy Jan", "P1", hours=168, te=21, overtime=8)]
    report = report_ca.parse(ca_report(rows=rows), report_ca.XLSX)

    result = _evaluate(report, "Jan Testowy")

    assert result.md_regular == Decimal("21.000")
    assert _titles(result)["Nadgodziny w raporcie: 8 h"] == "warn"


def test_inny_arkusz_to_nie_raport_ca():
    book = openpyxl.Workbook()
    book.active.append(["Time Sheet"])
    book.active.append(["Data", "Godziny"])
    out = io.BytesIO()
    book.save(out)

    assert report_ca.parse(out.getvalue(), report_ca.XLSX) is None
    assert report_ca.parse(b"%PDF-1.4 nie arkusz", "application/pdf") is None
    assert report_ca.parse(b"PK\x03\x04 uszkodzony", report_ca.XLSX) is None


async def test_proof_bierze_md_z_raportu_ca(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True)
    (folder / "raport.xlsx").write_bytes(ca_report())
    doc = CpDocument(
        id=7,
        kind="report",
        mime=report_ca.XLSX,
        file_path="consultant_portal/1/raport.xlsx",
    )

    result = await service._proof(
        doc, [doc], month=MONTH, person_name="Jan Testowy", rules=_rules()
    )

    assert result.md_regular == Decimal("17.000")
