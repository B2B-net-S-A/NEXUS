"""Trzy wzory z powtórki IX–X (23.11.2026), które zostawały bez MD.

Bez bazy. Dane fikcyjne: „Jan Testowy”, przełożona „Anna Inna”, projekt ALFA,
numery zleceń wymyślone.

1. Eksport SAP Fieldglass („timeSheet.worker.list”): tygodnie sob.–pt. z godzinami
   ST; tydzień na przełomie miesięcy dzielimy po dniach roboczych tylko, gdy jest
   pełny (8 h × dni robocze tygodnia).
2. Ewidencja czasu pracy Orlenu w PDF: wiersz na dzień z datą i liczbą godzin.
3. Polski Time Sheet z rokiem z zeszłorocznego szablonu: dni z godzinami pasują
   do kalendarza rozliczanego roku, a nie roku w pliku.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from decimal import Decimal

import openpyxl

from app.models.consultant_portal import CpDocument
from app.services.client_settlements import (
    ewidencja_orlen,
    rules_catalog,
    service,
    timesheet,
    timesheet_fieldglass,
)
from app.services.person_workdays import business_days

MONTH = "2026-10"
PERSON = "Jan Testowy"
PDF = "application/pdf"


def _rules(month_level: str = "block") -> dict:
    return rules_catalog.effective(
        {
            "proof.month": {"level": month_level},
            "proof.name_match": {"level": "warn"},
            "proof.excel_with_mail": {"level": "off"},
            "proof.accept_has_hours": {"level": "off"},
            "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
            "fields.day_limit": {"level": "block", "params": {"hours": "24"}},
            "fields.md_month_limit": {"level": "off"},
        }
    )


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


def _xlsx(rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _document(
    tmp_path, doc_id: int, name: str, mime: str, content: bytes
) -> CpDocument:
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(content)
    return CpDocument(
        id=doc_id, kind="report", mime=mime, file_path=f"consultant_portal/1/{name}"
    )


# ── 1. SAP Fieldglass ─────────────────────────────────────────────────────────

FG_HEADER = (
    "Status,ID,Revision,Main Document ID,Main Document Title,Supervisor of Worker,"
    "Start Date,End,ST,OT,DT,Others,NB,"
)


def _fg_line(
    status: str, ts_id: str, start: str, end: str, st: str, rev: str = "0"
) -> str:
    return (
        f"{status},{ts_id},{rev},JP0001,ALFA Engineer_PL,Anna Inna(12345),"
        f"{start},{end},{st},0.00,0.00,0.00,0.00,"
    )


def _fg_october(first_week: str = "40.00") -> list[str]:
    return [
        _fg_line("Pending Approval", "TS6", "10/31/2026", "11/06/2026", "40.00"),
        _fg_line("Pending Approval", "TS5", "10/24/2026", "10/30/2026", "40.00"),
        _fg_line("Pending Approval", "TS4", "10/17/2026", "10/23/2026", "40.00"),
        _fg_line("Pending Approval", "TS3", "10/10/2026", "10/16/2026", "40.00"),
        _fg_line("Pending Approval", "TS2", "10/03/2026", "10/09/2026", "40.00"),
        _fg_line("Approved", "TS1", "09/26/2026", "10/02/2026", first_week),
    ]


def _fg_xlsx(lines: list[str], *, split: bool = False) -> bytes:
    rows = [[None], [FG_HEADER], *[[line] for line in lines]]
    if split:
        rows = [[None], FG_HEADER.split(","), *[line.split(",") for line in lines]]
    return _xlsx(rows)


def _fg_result(content: bytes, month: str = MONTH):
    parsed = timesheet_fieldglass.parse(content, timesheet_fieldglass.XLSX)
    assert parsed is not None
    return parsed, timesheet_fieldglass.evaluate(
        parsed,
        month=month,
        person_name=PERSON,
        rules=_rules(),
        working_days=len(business_days(date(2026, 10, 1), date(2026, 10, 31))),
    )


def test_fieldglass_tygodnie_z_przelomu_dzielone_po_dniach_roboczych():
    # 26.09–02.10: 40 h, z czego czw. 1.10 i pt. 2.10 w październiku = 16 h;
    # cztery pełne tygodnie = 160 h; 31.10–06.11 bez dni roboczych w X.
    parsed, result = _fg_result(_fg_xlsx(_fg_october()))

    assert len(parsed.weeks) == 6
    assert result.md_regular == Decimal("22.000")
    assert result.md_extra == Decimal("0")
    sums = {c["title"]: c["detail"] for g in result.groups for c in g["checks"]}
    assert sums["MD z tygodni Fieldglass"] == "176 h / 8 = 22 MD."


def test_fieldglass_kolumny_rozdzielone_jak_zwykly_arkusz():
    _, result = _fg_result(_fg_xlsx(_fg_october(), split=True))

    assert result.md_regular == Decimal("22.000")


def test_fieldglass_niepelny_tydzien_na_przelomie_bez_md():
    # 32 h w tygodniu 26.09–02.10: nie wiadomo, ile z nich przypada na październik.
    _, result = _fg_result(_fg_xlsx(_fg_october(first_week="32.00")))

    assert result.md_regular is None
    assert any(t.startswith("Tydzień 26.09–02.10") for t in _titles(result))


def test_fieldglass_oczekujace_tygodnie_to_informacja():
    _, result = _fg_result(_fg_xlsx(_fg_october()))

    assert _titles(result)["Zatwierdzone w Fieldglass: 1 z 5 tygodni"] == "none"


def test_fieldglass_bez_nazwiska_konsultanta_to_uwaga_reguly():
    _, result = _fg_result(_fg_xlsx(_fg_october()))

    assert _titles(result)["Eksport Fieldglass bez imienia i nazwiska"] == "warn"


def test_fieldglass_nowsza_rewizja_zastepuje_starsza():
    lines = _fg_october() + [
        _fg_line("Approved", "TS3", "10/10/2026", "10/16/2026", "32.00", rev="1")
    ]
    _, result = _fg_result(_fg_xlsx(lines))

    assert result.md_regular == Decimal("21.000")


def test_fieldglass_odrzucony_tydzien_bez_md():
    lines = _fg_october()
    lines[1] = _fg_line("Rejected", "TS5", "10/24/2026", "10/30/2026", "40.00")
    _, result = _fg_result(_fg_xlsx(lines))

    assert result.md_regular is None


def test_fieldglass_brak_tygodnia_w_miesiacu_to_kontrola():
    lines = [line for line in _fg_october() if ",TS3," not in line]
    _, result = _fg_result(_fg_xlsx(lines))

    assert result.md_regular == Decimal("17.000")
    assert any(t.startswith("Dni robocze bez tygodnia") for t in _titles(result))


def test_fieldglass_nadgodziny_to_uwaga():
    lines = _fg_october()
    lines[2] = lines[2].replace("40.00,0.00", "40.00,4.00", 1)
    _, result = _fg_result(_fg_xlsx(lines))

    assert result.md_regular == Decimal("22.000")
    assert any(t.startswith("Nadgodziny w Fieldglass") for t in _titles(result))


def test_inny_arkusz_to_nie_fieldglass():
    content = _xlsx([["Status", "Cena"], ["Approved", 100]])
    assert timesheet_fieldglass.parse(content, timesheet_fieldglass.XLSX) is None


async def test_fieldglass_przez_dispatch_rozliczen(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    doc = _document(
        tmp_path,
        1,
        "timeSheet.worker.list.xlsx",
        timesheet.XLSX,
        _fg_xlsx(_fg_october()),
    )

    result = await service._proof(
        doc, [doc], month=MONTH, person_name=PERSON, rules=_rules()
    )

    assert result.md_regular == Decimal("22.000")


# ── 2. Ewidencja czasu pracy Orlenu (PDF) ─────────────────────────────────────

_WEEKDAYS = (
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
    "sobota",
    "niedziela",
)
ORLEN_HEAD = """UWAGA: wypełniamy samodzielnie
Procent dnia
Nr zadania Przelicznik -
Forma Data MPK stawki 1 DZIEŃ
Przełożony NAZWISKO I IMIĘ Kategoria Podkategoria (nadgodziny Komentarz
umowy [RRRR-MM-DD] (OPEX) TYLKO BL i ROBOCZY (1"""


def _orlen_text(
    month: int = 10, hours: str = "8,0", category: str = "Projekt ALFA - Testy"
) -> str:
    lines = [ORLEN_HEAD]
    day = date(2026, month, 1)
    while day.month == month:
        label = f"{day.isoformat()}, {_WEEKDAYS[day.weekday()]}"
        if day.weekday() < 5:
            lines.append(
                f"BL Inna Anna Testowy Jan {label} {category} 100,00% MPK 11111 {hours}"
            )
        else:
            lines.append(label)
        day += timedelta(days=1)
    lines.append("Suma końcowa 176")
    return "\n".join(lines)


def _orlen_result(text: str, month: str = MONTH):
    parsed = ewidencja_orlen.parse_text(text)
    assert parsed is not None
    from app.services.client_settlements import declared

    return parsed, declared.evaluate(
        parsed, month=month, person_name=PERSON, rules=_rules(), working_days=22
    )


def test_orlen_ewidencja_md_z_godzin_dziennych():
    parsed, result = _orlen_result(_orlen_text())

    assert parsed.hours == Decimal("176")
    assert parsed.month == MONTH
    assert result.md_regular == Decimal("22.000")
    assert _titles(result)["Imię i nazwisko jak w kontrakcie"] == "ok"


def test_orlen_ewidencja_inna_suma_koncowa_bez_md():
    text = _orlen_text().replace("Suma końcowa 176", "Suma końcowa 168")
    parsed, result = _orlen_result(text)

    assert parsed.hours is None
    assert result.md_regular is None


def test_orlen_ewidencja_urlop_w_wierszu_bez_md():
    text = _orlen_text().replace(
        "2026-10-05, poniedziałek Projekt ALFA - Testy",
        "2026-10-05, poniedziałek Urlop",
    )
    parsed, result = _orlen_result(text)

    assert parsed.hours is None
    assert result.md_regular is None


def test_orlen_ewidencja_za_inny_miesiac_to_kontrola_bez_md():
    _, result = _orlen_result(_orlen_text(month=9), month=MONTH)

    assert result.md_regular is None


def test_orlen_ewidencja_dwie_osoby_to_none():
    text = _orlen_text().replace(
        "BL Inna Anna Testowy Jan 2026-10-06", "BL Inna Anna Nowak Ewa 2026-10-06"
    )
    assert ewidencja_orlen.parse_text(text) is None


def test_inny_pdf_to_nie_ewidencja_orlenu():
    assert ewidencja_orlen.parse_text("Faktura VAT 1/10/2026\nRazem 100,00") is None


async def test_orlen_ewidencja_przez_dispatch_rozliczen(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(ewidencja_orlen, "pdf_text", lambda _content: _orlen_text())
    doc = _document(tmp_path, 1, "ewidencja.pdf", PDF, b"%PDF-1.4 fikcyjny")

    result = await service._proof(
        doc, [doc], month=MONTH, person_name=PERSON, rules=_rules()
    )

    assert result.md_regular == Decimal("22.000")


# ── 3. Polski Time Sheet z rokiem z szablonu ──────────────────────────────────


def _template_sheet(file_year: int, worked: list[int]) -> list[list]:
    rows: list[list] = [
        [None, "Time Sheet"],
        [None, "Imię Nazwisko", PERSON],
        [None, "Data", "Opis zadań", "Liczba godzin", "Uwagi"],
    ]
    for day in range(1, 32):
        rows.append(
            [None, datetime(file_year, 10, day), None, 8 if day in worked else None]
        )
    rows.append([None, "Łączna liczba godzin", None, 8 * len(worked)])
    return rows


def _october_2026_workdays() -> list[int]:
    return [d.day for d in business_days(date(2026, 10, 1), date(2026, 10, 31))]


def _ts_result(rows: list[list], month: str = MONTH):
    parsed = timesheet.parse_rows([rows])
    return timesheet.evaluate(
        parsed,
        month=month,
        person_name=PERSON,
        has_mail=False,
        rules=_rules(),
        working_days=22,
    )


def test_rok_2025_w_szablonie_z_dniami_pracy_2026_daje_md():
    # Dni z godzinami to dni robocze X 2026; w X 2025 część z nich to soboty i niedziele.
    result = _ts_result(_template_sheet(2025, _october_2026_workdays()))

    assert result.md_regular == Decimal("22.000")
    assert _titles(result)["Rok w szablonie: 2025"] == "none"


def test_rok_2025_z_dniami_pracy_2025_zostaje_bez_md():
    worked_2025 = [d.day for d in business_days(date(2025, 10, 1), date(2025, 10, 31))]
    result = _ts_result(_template_sheet(2025, worked_2025))

    assert result.md_regular is None
    assert _titles(result)["Time Sheet za inny miesiąc"] == "fail"


def test_rok_w_szablonie_z_weekendem_2026_zostaje_bez_md():
    # Sobota 3.10.2026 z godzinami: nie pasuje do żadnego roku jako dzień roboczy.
    result = _ts_result(_template_sheet(2025, _october_2026_workdays() + [3]))

    assert result.md_regular is None


def test_poczta_zapisuje_eksport_fieldglass_jako_raport():
    from app.services.consultant_portal.mailbox import kind_of_file

    content = _fg_xlsx(_fg_october())
    assert kind_of_file("Faktura 10/2026", "2026-10.xlsx", content) == "report"


def test_fieldglass_komorka_wielowierszowa_z_przecinkiem_nie_wywraca_odczytu():
    cells = timesheet_fieldglass._cells(("Uwagi: dzień 1,\npoprawione",))
    assert cells == ["Uwagi: dzień 1,\npoprawione"]
