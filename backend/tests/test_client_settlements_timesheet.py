"""Time Sheet w godzinach i potwierdzenie usług per projekt (roadmapa E6.2).

Bez bazy. Dane fikcyjne: osoba „Jan Testowy”, projekty ALFA i BETA,
zamówienie ZAM-TEST.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal

import openpyxl

from app.services.client_settlements import (
    client_invoice,
    rcp_bnp,
    rules_catalog,
    service_confirmation,
    timesheet,
)

XLSX = timesheet.XLSX
HEADER = [
    None,
    "Date",
    "Project",
    "Description",
    "Total Hours",
    "Billable",
    "Non-billable",
    "Nr strumienia",
]


def _sheet(
    rows: list[list],
    *,
    project="ALFA",
    consultant="Jan Testowy",
    start=date(2026, 11, 1),
    total=None,
):
    out = [
        [None, "Time Sheet"],
        [],
        [None, "Project Name", project],
        [None, "Consultant(s)", consultant],
        [None, "Date from", start],
        [None, "Date to", date(2026, 11, 30)],
        [],
        HEADER,
        *rows,
        [None, None, None, "Total Hours (This Week)", None, total],
    ]
    return out


def _row(
    day: int,
    hours,
    *,
    project=None,
    desc="Zadanie A",
    billable=None,
    task=None,
    month=11,
):
    return [
        None,
        datetime(2026, month, day),
        project,
        desc,
        hours,
        hours if billable is None else billable,
        None,
        task,
    ]


def _rules(**levels: str) -> dict:
    stored = {
        "proof.month": {"level": "block"},
        "proof.name_match": {"level": "warn"},
        "proof.excel_with_mail": {"level": "off"},
        "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
        "fields.day_limit": {"level": "block", "params": {"hours": "24"}},
        "fields.md_month_limit": {"level": "off"},
    }
    for key, level in levels.items():
        stored[key.replace("__", ".")] = {
            **stored.get(key.replace("__", "."), {}),
            "level": level,
        }
    return rules_catalog.effective(stored)


def _xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ── Odczyt ───────────────────────────────────────────────────────────────────


def test_odczyt_godzin_projektow_i_task_id():
    parsed = timesheet.parse_rows(
        [
            _sheet(
                [
                    _row(3, 8, task="ST-1"),
                    _row(4, 6, desc="Zadanie B", project="BETA"),
                    _row(5, 8, task="ST-1"),
                    [None, None, None, None, None, None, None, None],
                ],
                total=22,
            )
        ]
    )
    assert parsed is not None
    assert parsed.month == "2026-11"
    assert parsed.consultant == "Jan Testowy"
    assert parsed.total_hours == Decimal("22")
    assert parsed.declared_total == Decimal("22")
    assert parsed.hours_by_project() == {"ALFA": Decimal("16"), "BETA": Decimal("6")}
    assert [e.task_id for e in parsed.entries] == ["ST-1", None, "ST-1"]


def test_billable_wygrywa_z_total_hours_a_bez_niego_total_minus_non_billable():
    rows = [
        _row(3, 10, billable=8),
        [None, datetime(2026, 11, 4), None, "Spotkanie", 9, None, 1, None],
    ]
    parsed = timesheet.parse_rows([_sheet(rows)])
    assert [e.hours for e in parsed.entries] == [Decimal("8"), Decimal("8")]


def test_tekst_w_billable_zeruje_wiersz_a_pusta_komorka_bierze_total_hours():
    rows = [
        [None, datetime(2026, 11, 2), None, "Zadanie A", 8, "urlop", None, None],
        [None, datetime(2026, 11, 3), None, "Zadanie A", 8, " ", None, None],
        [None, datetime(2026, 11, 4), None, "Zadanie A", 8, "7,5", "x", None],
    ]
    parsed = timesheet.parse_rows([_sheet(rows)])
    assert [(e.day.day, e.hours) for e in parsed.entries] == [
        (3, Decimal("8")),
        (4, Decimal("7.5")),
    ]


def test_kilka_tabel_tygodniowych_sumuje_sie():
    week1 = _sheet([_row(3, 8)], total=8)
    week2 = [
        HEADER,
        _row(10, 7),
        [None, None, None, "Total Hours (This Week)", None, 7],
    ]
    parsed = timesheet.parse_rows([week1, week2])
    assert parsed.total_hours == Decimal("15")
    assert parsed.declared_total == Decimal("15")


def test_suma_pod_tabela_bez_etykiety_nie_jest_wpisem():
    """Suma „Billable” pod tabelą bez etykiety „Total Hours” (próba rozliczeń
    22.11.2026: 216 h zamiast 108 h — suma szła jako wpis projektu z nagłówka)."""

    rows = [
        _row(3, 8, project="ALFA-K"),
        _row(4, 6, project="ALFA-K"),
        [None, datetime(2026, 11, 7), None, "WEEKEND", 0, 0, None, None],
        [None, None, None, None, None, None, None, None],
        [None, None, None, None, None, 14, None, None],
        [None, "Print Name", None, None, "Print Name"],
        [None, "Date", None, datetime(2026, 11, 30)],
    ]
    sheet = _sheet(rows)[:-1]  # bez wiersza „Total Hours”
    parsed = timesheet.parse_rows([sheet])
    assert parsed.total_hours == Decimal("14")
    assert parsed.declared_total == Decimal("14")
    assert parsed.hours_by_project() == {"ALFA-K": Decimal("14")}


def test_wpis_bez_daty_z_opisem_zostaje():
    rows = [_row(3, 8), [None, None, None, "Szkolenie", 4, 4, None, None]]
    parsed = timesheet.parse_rows([_sheet(rows, total=12)])
    assert parsed.total_hours == Decimal("12")


def test_plik_spoza_szablonu_to_none_a_xlsx_time_sheet_czyta_sie_z_pliku():
    assert timesheet.parse_rows([[["Rozliczenie czasu pracy"], ["SUMA", 1]]]) is None
    content = _xlsx(_sheet([_row(3, 8), _row(4, 8)], total=16))
    parsed = timesheet.parse(content, XLSX)
    assert parsed is not None and parsed.total_hours == Decimal("16")
    # Szablon RCP BNP tego pliku nie rozpoznaje, więc kontrole idą z Time Sheet.
    assert rcp_bnp.parse(content, XLSX) is None
    assert timesheet.parse(content, "application/pdf") is None
    assert timesheet.parse(b"nie xlsx", XLSX) is None


# ── Kontrole ─────────────────────────────────────────────────────────────────


def _evaluate(parsed, rules=None, **kw):
    args = {
        "month": "2026-11",
        "person_name": "Jan Testowy",
        "has_mail": False,
        "rules": rules or _rules(),
        "working_days": 20,
    }
    args.update(kw)
    return timesheet.evaluate(parsed, **args)


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


def test_md_z_godzin_i_bez_uwag():
    parsed = timesheet.parse_rows(
        [_sheet([_row(3, 8), _row(4, 8), _row(5, 4)], total=20)]
    )
    result = _evaluate(parsed)
    assert result.md_regular == Decimal("2.500")
    assert result.md_extra == Decimal("0")
    assert not result.blocking and not result.warn
    assert _titles(result)["Godziny policzone od nowa"] == "ok"


def test_x_w_billable_w_dni_bez_pracy_nie_liczy_total_hours():
    """Szablon VeloBanku: „Total Hours” 8 w każdym dniu kalendarza, a weekendy
    i dni wolne mają „x” w „Billable” i „Non-billable” (próba IX–X 2026: 30 MD
    z wierszy zamiast 20 z sumy pliku i arkusza podpisanego przez klienta)."""

    days_off = {1, 2}
    rows = []
    for day in range(1, 31):
        when = datetime(2026, 9, day)
        if when.weekday() >= 5 or day in days_off:
            rows.append([None, when, "x", "x", 8, "x", "x"])
        else:
            rows.append([None, when, "ST-1", "Zadanie A", 8, 8, "x"])
    sheet = [
        [None, "Time Sheet"],
        [None, "Project Name", None, "ALFA"],
        [None, "Consultant(s)", None, "Jan Testowy"],
        [None, "Date from", None, datetime(2026, 9, 1)],
        [None, "Date to", None, datetime(2026, 9, 30)],
        [],
        [
            None,
            "Date",
            "Nr strumienia/Nr inicjatywy",
            "Description",
            "Total Hours",
            "Billable",
            "Non-billable",
        ],
        *rows,
        [],
        [None, None, None, "Total Hours", None, 160, 0],
        [None, None, None, "Total MD", None, 20],
    ]
    parsed = timesheet.parse(_xlsx(sheet), XLSX)

    assert parsed.total_hours == Decimal("160")
    assert parsed.declared_total == Decimal("160")
    assert len(parsed.entries) == 20
    result = _evaluate(parsed, month="2026-09", working_days=22)
    assert result.md_regular == Decimal("20.000")
    assert not result.blocking
    assert _titles(result)["Godziny policzone od nowa"] == "ok"


def test_inny_miesiac_blokuje_a_suma_total_inna_niz_wiersze_blokuje():
    parsed = timesheet.parse_rows(
        [_sheet([_row(3, 8, month=10)], start=date(2026, 10, 1), total=9)]
    )
    result = _evaluate(parsed)
    titles = _titles(result)
    assert titles["Time Sheet za inny miesiąc"] == "fail"
    assert titles["Suma „Total Hours” inna niż suma wierszy"] == "fail"
    assert result.blocking


def test_limit_md_w_miesiacu_tylko_gdy_regula_wlaczona():
    rows = [_row(d, 12) for d in range(2, 25)]  # 276 h = 34,5 MD
    parsed = timesheet.parse_rows([_sheet(rows)])
    off = _evaluate(parsed)
    assert off.md_regular == Decimal("34.500")
    assert not any("dniach roboczych" in t for t in _titles(off))
    on = _evaluate(parsed, rules=_rules(fields__md_month_limit="warn"))
    assert _titles(on)["34,5 MD przy 20 dniach roboczych"] == "warn"
    assert on.warn and not on.blocking


def test_nazwisko_i_mail_z_akceptacja():
    parsed = timesheet.parse_rows([_sheet([_row(3, 8)], consultant="Anna Inna")])
    rules = _rules(proof__excel_with_mail="warn")
    result = _evaluate(parsed, rules=rules)
    titles = _titles(result)
    assert titles["Inne imię lub nazwisko niż w kontrakcie"] == "warn"
    assert titles["Brak maila z akceptacją godzin"] == "warn"
    with_mail = _titles(_evaluate(parsed, rules=rules, has_mail=True, client_mail=True))
    assert with_mail["Mail z akceptacją godzin jest"] == "ok"


FROM_FILE_NAME = "Imię i nazwisko z nazwy pliku jak w kontrakcie"
NO_FIELD = "Time Sheet bez pola Consultant(s)"


def test_puste_pole_consultant_osoba_z_nazwy_pliku():
    """Szablon VeloBanku z pustym „Consultant(s)” i „Print Name”: osoba stoi tylko
    w nazwie pliku (próba IX–X 2026, jedyna uwaga przy MD zgodnych z arkuszem
    podpisanym przez klienta). Decyzja Artura z 24.11.2026: osoba z nazwy pliku."""

    parsed = timesheet.parse_rows([_sheet([_row(3, 8)], consultant=None)])
    for person, name in (
        ("Jan Testowy", "Jan Testowy - Time Sheet - listopad 2026.xlsx"),
        ("Jan Testowy", "TS_Testowy_Jan_11.2026.xlsx"),
        ("Łucja Testowa", "Lucja_Testowa_TS.xlsx"),
    ):
        result = _evaluate(parsed, person_name=person, file_name=name)
        titles = _titles(result)
        assert titles[FROM_FILE_NAME] == "ok", name
        assert NO_FIELD not in titles, name
        assert not result.warn, name


def test_bez_osoby_z_kontraktu_w_nazwie_pliku_uwaga_zostaje():
    parsed = timesheet.parse_rows([_sheet([_row(3, 8)], consultant=None)])
    for name in (
        "Anna Inna - Time Sheet - listopad 2026.xlsx",  # inna osoba
        "Testowy - Time Sheet - listopad 2026.xlsx",  # samo nazwisko
        "Time Sheet - listopad 2026.xlsx",  # nikt
        None,  # plik bez nazwy
    ):
        result = _evaluate(parsed, file_name=name)
        titles = _titles(result)
        assert titles[NO_FIELD] == "warn", name
        assert FROM_FILE_NAME not in titles, name
        assert result.warn, name


def test_inna_osoba_w_polu_wygrywa_z_nazwa_pliku():
    parsed = timesheet.parse_rows([_sheet([_row(3, 8)], consultant="Anna Inna")])
    result = _evaluate(
        parsed, file_name="Jan Testowy - Time Sheet - listopad 2026.xlsx"
    )
    titles = _titles(result)
    assert titles["Inne imię lub nazwisko niż w kontrakcie"] == "warn"
    assert FROM_FILE_NAME not in titles


async def test_rozliczenie_bierze_nazwe_pliku_z_dokumentu(tmp_path, monkeypatch):
    from app.models.consultant_portal import CpDocument
    from app.services import storage_service
    from app.services.client_settlements import service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True)
    (folder / "ts.xlsx").write_bytes(_xlsx(_sheet([_row(3, 8)], consultant=None)))
    doc = CpDocument(
        id=1,
        kind="report",
        mime=XLSX,
        file_path="consultant_portal/1/ts.xlsx",
        file_name="Jan Testowy - Time Sheet - listopad 2026.xlsx",
    )
    result = await service._proof(
        doc, [doc], month="2026-11", person_name="Jan Testowy", rules=_rules()
    )
    assert _titles(result)[FROM_FILE_NAME] == "ok"
    assert not result.warn


def test_time_sheet_bez_godzin_czeka_na_finanse():
    parsed = timesheet.parse_rows([_sheet([])])
    result = _evaluate(parsed)
    assert result.md_regular is None and result.warn


def test_dzien_ponad_limit():
    parsed = timesheet.parse_rows([_sheet([_row(3, 14), _row(3, 12, desc="Inne")])])
    assert _titles(_evaluate(parsed))["26 h w dniu 03.11"] == "fail"


# ── Kilka plików na różne prace (próba VI–VIII 2026, Polkomtel) ─────────────


def _work_sheet(desc: str, days: list[int], hours: int = 8, **kwargs):
    return timesheet.parse_rows(
        [_sheet([_row(d, hours, desc=desc) for d in days], project=None, **kwargs)]
    )


def test_dwa_pliki_na_rozne_prace_sumuja_sie_z_projektem_z_opisu():
    first = _work_sheet("Utrzymanie systemu A", [2, 3, 4], hours=4)
    second = _work_sheet("Automaty testów B", [2, 3])
    merged, files = timesheet.merge_projects(first, [second])
    assert files == 2
    assert merged.total_hours == Decimal("28")
    assert merged.hours_by_project() == {
        "Utrzymanie systemu A": Decimal("12"),
        "Automaty testów B": Decimal("16"),
    }
    result = _evaluate(merged, files=files)
    assert result.md_regular == Decimal("3.5")
    assert "Time Sheet z 2 plików" in _titles(result)


def test_poprawiona_wersja_tej_samej_pracy_nie_dochodzi():
    """Konsultant dosyła poprawiony Time Sheet: liczy się tylko najnowszy plik."""

    newest = _work_sheet("Utrzymanie systemu A", [2, 3, 4])
    older = _work_sheet("Utrzymanie systemu A", [2, 3])
    merged, files = timesheet.merge_projects(newest, [older])
    assert files == 1 and merged is newest


def test_inny_miesiac_i_inna_osoba_nie_dochodza():
    main = _work_sheet("Utrzymanie systemu A", [2, 3])
    october = _work_sheet("Automaty testów B", [2], start=date(2026, 10, 1))
    stranger = _work_sheet("Automaty testów B", [2], consultant="Anna Inna")
    merged, files = timesheet.merge_projects(main, [october, stranger])
    assert files == 1 and merged is main


def test_projekty_z_naglowka_rozne_sumuja_sie():
    alfa = timesheet.parse_rows([_sheet([_row(2, 8), _row(3, 8)], project="ALFA")])
    beta = timesheet.parse_rows([_sheet([_row(4, 8)], project="BETA")])
    merged, files = timesheet.merge_projects(alfa, [beta])
    assert files == 2
    assert merged.hours_by_project() == {"ALFA": Decimal("16"), "BETA": Decimal("8")}


async def test_rozliczenie_liczy_oba_pliki_miesiaca(tmp_path, monkeypatch):
    from app.models.consultant_portal import CpDocument
    from app.services import storage_service
    from app.services.client_settlements import service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True)
    sheets = {
        "a.xlsx": _sheet(
            [_row(d, 8, desc="Utrzymanie systemu A") for d in (2, 3)], project=None
        ),
        "b.xlsx": _sheet(
            [_row(d, 8, desc="Automaty testów B") for d in (4,)], project=None
        ),
    }
    docs = []
    for number, (name, rows) in enumerate(sheets.items(), start=1):
        (folder / name).write_bytes(_xlsx(rows))
        docs.append(
            CpDocument(
                id=number,
                kind="report",
                mime=XLSX,
                file_path=f"consultant_portal/1/{name}",
                file_name=name,
            )
        )
    result = await service._proof(
        docs[1], docs, month="2026-11", person_name="Jan Testowy", rules=_rules()
    )
    assert result.md_regular == Decimal("3")
    assert "Time Sheet z 2 plików" in _titles(result)


# ── Potwierdzenie usług ──────────────────────────────────────────────────────


def test_regula_dokumentu_per_projekt_od_miesiaca():
    rules = rules_catalog.effective(
        {
            "cl.client_document": {
                "level": "warn",
                "params": {
                    "kind": "Service Delivery Confirmation",
                    "per": "projekt",
                    "from": "2026-11",
                },
            }
        }
    )
    assert (
        service_confirmation.rule_for(rules, "2026-11")["kind"]
        == "Service Delivery Confirmation"
    )
    assert service_confirmation.rule_for(rules, "2026-10") is None
    per_person = rules_catalog.effective(
        {"cl.client_document": {"level": "warn", "params": {"per": "osoba"}}}
    )
    assert service_confirmation.rule_for(per_person, "2026-11") is None
    assert service_confirmation.rule_for(rules_catalog.effective({}), "2026-11") is None


def test_dokument_bez_nazwisk_task_id_ze_strumienia_albo_z_godzin():
    project = service_confirmation.Project(
        "ALFA", hours=Decimal("96"), order_numbers=["ZAM-TEST"]
    )
    project.tasks[("ST-1", "a")] = service_confirmation.Task(
        "ST-1", "Moduł A", Decimal("21")
    )
    project.tasks[("", "b")] = service_confirmation.Task(
        None, "Moduł <B>", Decimal("75")
    )
    html = service_confirmation.render_html(
        kind="Service Delivery Confirmation",
        client_name="Klient ABC",
        project=project,
        month="2026-11",
        stage="ACTUAL",
        per_md=Decimal("8"),
    )
    assert "November 2026" in html and "ZAM-TEST" in html
    assert "<td>ST-1</td>" in html and "<td>75h</td>" in html
    assert "Moduł &lt;B&gt;" in html
    assert "TOTAL MDs: 12" in html
    assert "Jan" not in html and "Testowy" not in html
    assert "name='author'" not in html and 'name="author"' not in html
    assert (
        service_confirmation.file_name("ALFA / 2", "2026-11")
        == "SDC_ALFA_2_2026-11.pdf"
    )


def test_cena_klienta_w_euro_z_linii_zamowienia_a_marza_w_zlotych():
    class Line:
        rate_client_currency = "EUR"
        rate_unit = "daily"
        rate_client = Decimal("250")
        md_rate_revenue = Decimal("1075")

    price = client_invoice.client_price(Line())
    assert (price.rate, price.currency, price.to_pln) == (
        Decimal("250"),
        "EUR",
        Decimal("4.3"),
    )

    class Pln(Line):
        rate_client_currency = "PLN"
        rate_client = Decimal("1100")
        md_rate_revenue = Decimal("1100")

    assert client_invoice.client_price(Pln()).currency == "PLN"
    assert client_invoice.client_price(None).rate is None


def test_blok_kosztow_do_maila_regula_i_format():
    rules = rules_catalog.effective({})
    assert service_confirmation.block_params(rules) is None
    rules["cl.cost_mail_block"] = {"level": "warn", "params": {"vendor": " "}}
    # Pusty dostawca = nazwa spółki z dokumentu.
    assert service_confirmation.block_params(rules) == {
        "vendor": service_confirmation.SUPPLIER
    }
    text = service_confirmation.block_text(
        stage="FORECAST",
        project="ALFA",
        order_numbers=["ZAM-TEST", "ZAM-DRUGIE"],
        month="2026-12",
        vendor="Dostawca",
        md=Decimal("12.000"),
        net=Decimal("3492.50"),
        currency="EUR",
    )
    assert text.splitlines() == [
        "[ESP-MANAGER-START]",
        "Stage: FORECAST",
        "Project: ALFA",
        "PO: ZAM-TEST, ZAM-DRUGIE",
        "Month: 2026-12",
        "Vendor: Dostawca",
        "MD: 12",
        "Cost net EUR: 3492.5",
        "Comment:",
        "[ESP-MANAGER-END]",
    ]
