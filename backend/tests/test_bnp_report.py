"""Raport miesięczny BNP: reguły kolumn, odczyt widełek i plik Excel."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openpyxl import load_workbook

from app.models.contract import RateUnit
from app.models.job import Seniority
from app.models.recruitment_pipeline import PipelineStage as S
from app.services.bnp_report.calculations import (
    RateBand,
    ReportJob,
    StageEvent,
    build_row,
    extract_request_number,
    hourly_rate,
    propose_band,
    propose_seniority,
    role_from_title,
    sla_date,
)
from app.services.bnp_report.rate_annex import parse_rate_annex
from app.services.bnp_report.workbook import (
    FULL_HEADERS,
    FULL_SHEET,
    OPTION_HEADERS,
    OPTION_SHEET,
    build_workbook,
)

BANDS = [
    RateBand(1, "IT Analyst", 50, 100),
    RateBand(2, "Software Developer - Java", 60, 120),
    RateBand(3, "Software Developer - Net", 70, 130),
    RateBand(4, "Software Developer - Full stack", 80, 140),
    RateBand(5, "Test Automation Engineer", 40, 90),
    RateBand(6, "Tester", 30, 70),
    RateBand(7, "Technical Architect", 90, 150),
]


def moment(day: int, month: int = 10) -> datetime:
    return datetime(2026, month, day, 10, tzinfo=timezone.utc)


def event(candidate: int, stage: S, day: int, **fields) -> StageEvent:
    fields.setdefault("ended_by", None)
    return StageEvent(candidate_id=candidate, stage=stage, moved_at=moment(day), **fields)


def job(**overrides) -> ReportJob:
    values = {
        "id": 1,
        "title": "IT Analyst",
        "working_title": None,
        "description": None,
        "client_reference": "RITM1",
        "seniority": Seniority.mid,
        "client_rate_card_id": 1,
        "opened_on": date(2026, 10, 8),
        "closed_on": None,
        "budget_hourly": 60.0,
    }
    return ReportJob(**{**values, **overrides})


def rated(candidate: int, day: int, client: str = "90", expected: str = "55") -> StageEvent:
    return event(
        candidate,
        S.cv_sent,
        day,
        client_rate_value=Decimal(client),
        client_rate_unit=RateUnit.hourly,
        client_rate_currency="PLN",
        expected_rate_value=Decimal(expected),
        expected_rate_unit=RateUnit.hourly,
        expected_rate_currency="PLN",
    )


def test_sla_liczy_dziesiec_dni_roboczych_bez_dnia_startu():
    assert sla_date(date(2026, 10, 8)) == date(2026, 10, 22)


def test_sla_omija_swieto_i_weekend():
    # 01.11 to niedziela, 11.11 święto: oba poza liczeniem.
    assert sla_date(date(2026, 11, 2)) == date(2026, 11, 17)


def test_cv_po_terminie_sla_nie_liczy_sie_do_sla():
    row = build_row(job(), [rated(1, 9), rated(2, 23)], BANDS)
    assert (row.cv, row.cv_sla) == (2, 1)
    assert row.ritm_sla == 0


def test_stawki_arkusza_sa_za_md_i_obejmuja_wszystkich_wyslanych():
    row = build_row(job(), [rated(1, 9, client="80"), rated(2, 9, client="95")], BANDS)
    assert (row.offer_min_md, row.offer_max_md) == (640, 760)
    assert row.recommended_average_md == 700
    assert (row.band_min_md, row.band_max_md, row.band_average_md) == (400, 800, 600)


def test_rozbieznosc_i_roznica_jak_w_pliku_delivery_leada():
    row = build_row(job(), [rated(1, 9, client="80"), rated(2, 9, client="95")], BANDS)
    assert row.percent_from_band_average == pytest.approx((700 - 600) / 600)
    assert row.offer_min_minus_top == 640 - 800
    assert row.percent_difference == pytest.approx(-160 / 800)


def test_zgodna_stawka_porownuje_kandydata_z_budzetem_gorna_granica():
    row = build_row(
        job(budget_hourly=60.0),
        [rated(1, 9, expected="60"), rated(2, 9, expected="61"), rated(3, 9, expected="20")],
        BANDS,
    )
    assert row.cv_in_budget == 2
    assert row.ritm_sla_and_budget == 1


def test_bez_budzetu_zgodna_stawka_jest_pusta():
    row = build_row(job(budget_hourly=None), [rated(1, 9)], BANDS)
    assert row.cv_in_budget is None
    assert row.ritm_sla_and_budget is None


def test_klient_wybral_kogos_innego_nie_jest_odrzuceniem():
    row = build_row(
        job(),
        [
            rated(1, 9),
            event(1, S.rejected, 20, ended_by="client", rejection_reason="client_chose_other"),
        ],
        BANDS,
    )
    assert row.rejected_cv == 0


def test_odrzucenie_przed_spotkaniem_i_po_spotkaniu_sie_nie_mieszaja():
    row = build_row(
        job(),
        [
            rated(1, 9),
            event(1, S.rejected, 12, ended_by="client", rejection_reason="Brak doświadczenia"),
            rated(2, 9),
            event(2, S.client_interview, 12),
            event(2, S.rejected, 15, ended_by="client", rejection_reason="Brak doświadczenia"),
        ],
        BANDS,
    )
    assert (row.rejected_cv, row.meetings, row.rejected_after_meeting) == (1, 1, 1)


def test_odrzucenie_osoby_bez_wyslanego_cv_nie_liczy_sie():
    row = build_row(
        job(),
        [event(9, S.screening, 9), event(9, S.rejected, 10, ended_by="client")],
        BANDS,
    )
    assert (row.cv, row.rejected_cv) == (0, 0)


def test_odrzucenie_przez_rekrutera_nie_jest_odrzuceniem_klienta():
    row = build_row(
        job(),
        [rated(1, 9), event(1, S.rejected, 12, ended_by="recruiter")],
        BANDS,
    )
    assert row.rejected_cv == 0


def test_oferta_to_akceptacja_albo_dalej_nie_tylko_umowa():
    row = build_row(
        job(),
        [rated(1, 9), event(1, S.acceptance, 20), rated(2, 9), event(2, S.hired, 22)],
        BANDS,
    )
    assert row.offers == 2


def test_ten_sam_kandydat_wyslany_dwa_razy_to_jedno_cv():
    row = build_row(job(), [rated(1, 9), rated(1, 12)], BANDS)
    assert row.cv == 1


def test_etap_u_klienta_bez_cv_wyslane_tez_znaczy_wysylke():
    row = build_row(job(), [event(1, S.client_interview, 12)], BANDS)
    assert (row.cv, row.meetings) == (1, 1)


def test_stawka_za_dzien_przeliczona_a_miesieczna_i_obca_waluta_pominiete():
    assert hourly_rate(Decimal("800"), RateUnit.daily, "PLN") == 100
    assert hourly_rate(Decimal("100"), RateUnit.monthly, "PLN") is None
    assert hourly_rate(Decimal("100"), RateUnit.hourly, "EUR") is None


@pytest.mark.parametrize(
    ("reference", "title", "working", "expected"),
    [
        ("RITM123", "Tester", None, ("RITM123", "field")),
        (None, "Senior Dev RITM456", None, ("RITM456", "title")),
        (None, "Dev", "RITM789 Dev", ("RITM789", "title")),
        (None, "Dev (RFP_90)", None, ("RFP 90", "rfp")),
        ("   ", "Dev", None, (None, "none")),
    ],
)
def test_numer_zapytania(reference, title, working, expected):
    assert extract_request_number(reference, title, working) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Software Developer RITM0864052", "Senior Software Developer"),
        ("Software Developer_RITM0866775", "Software Developer"),
        ("IT Analyst – RITM0869306", "IT Analyst"),
        ("Test Automation Engineer (RFP 92)", "Test Automation Engineer"),
    ],
)
def test_rola_to_tytul_bez_numeru(title, expected):
    assert role_from_title(title) == expected


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"seniority": Seniority.lead, "title": "Senior Dev"}, (Seniority.lead, "field")),
        ({"title": "Senior Dev"}, (Seniority.senior, "title")),
        ({"working_title": "Analyst · 5+ lat"}, (Seniority.senior, "years")),
        ({"working_title": "Analyst · 4+ lata"}, (Seniority.senior, "years")),
        ({"working_title": "Analyst · 3+ lata"}, (Seniority.mid, "years")),
        ({"working_title": "Analyst · 1 rok", "description": "Junior"}, (Seniority.junior, "description")),
        ({"title": "Analyst"}, (None, "none")),
    ],
)
def test_propozycja_poziomu(kwargs, expected):
    args = {"seniority": None, "title": None, "working_title": None, "description": None}
    assert propose_seniority(**{**args, **kwargs}) == expected


@pytest.mark.parametrize(
    ("title", "working", "role"),
    [
        ("IT Analyst RITM1", None, "IT Analyst"),
        ("Senior .NET Developer", None, "Software Developer - Net"),
        ("Software Developer_RITM1", "Software Developer · Java, Oracle", "Software Developer - Java"),
        ("Senior Software Developer", "Senior Software Developer · Android, Kotlin", "Software Developer - Full stack"),
        ("Tester", "Tester automatyzujący · Java", "Test Automation Engineer"),
        ("Tester manualny", None, "Tester"),
        ("Technical Architect", None, "Technical Architect"),
        ("Software Developer", None, None),
        ("Kierownik budowy", None, None),
    ],
)
def test_propozycja_roli_z_umowy(title, working, role):
    band = propose_band(title, working, BANDS)
    assert (band.role if band else None) == role


def test_zapisana_rola_wygrywa_z_propozycja():
    row = build_row(job(title="Tester", client_rate_card_id=7), [], BANDS)
    assert (row.contract_role, row.contract_role_source) == ("Technical Architect", "field")


def test_brak_roli_wymaga_uwagi():
    row = build_row(job(title="Software Developer", client_rate_card_id=None), [], BANDS)
    assert row.contract_role_source == "none"
    assert row.needs_attention


def test_numer_rfp_wymaga_uwagi_a_numer_z_tytulu_nie():
    assert build_row(job(client_reference=None, title="IT Analyst RFP 9"), [], BANDS).needs_attention
    assert not build_row(job(client_reference=None, title="IT Analyst RITM9"), [], BANDS).needs_attention


ANNEX = """
regulamin Strona 47 z 49 Załącznik nr 7 – Stawki. minimalna maksymalna średnia stawka
Nazwa pozycji specjalistycznej IT stawka netto stawka netto Rozliczenie za MD netto PLN
PLN PLN Administrator (VMWARE.,OPENSHIFT , 11 22 godz 133 Storage , Network) Agile Coach 33 44
godz 308 Software Developer - Net 55 66 godz 484 IT support specialist- 1st line 12 34 godz 184
Test Coordinator 77 88 godz 660 Strona 48 z 49 Autenti ID: abc Załącznik nr 8 – Graficzne
"""


def test_odczyt_tabeli_z_zalacznika():
    rows = {row.role: (row.minimum, row.maximum) for row in parse_rate_annex(ANNEX, [])}
    assert rows == {
        "Administrator (VMWARE, OPENSHIFT, Storage, Network)": (11, 22),
        "Agile Coach": (33, 44),
        "Software Developer - Net": (55, 66),
        "IT support specialist- 1st line": (12, 34),
        "Test Coordinator": (77, 88),
    }


def test_aneks_dopisuje_role_przeliczona_z_md_na_godziny():
    amendment = (
        "Stawki netto PLN Nazwa roli Junior Medium Senior min max min max min max "
        "Kompetencje UX 160 240 240 320 320 400 § 2"
    )
    rows = parse_rate_annex(ANNEX, [amendment])
    assert rows[-1].role == "Kompetencje UX"
    assert (rows[-1].minimum, rows[-1].maximum) == (20, 50)


def test_umowa_bez_tabeli_nie_daje_wierszy():
    assert parse_rate_annex("Zwykła treść umowy bez stawek.", []) == []


def _sample_rows():
    return [
        build_row(job(), [rated(1, 9, client="80"), rated(2, 9, client="95")], BANDS),
        build_row(job(id=2, title="Software Developer", client_rate_card_id=None, client_reference=None, seniority=None), [], BANDS),
    ]


def test_arkusze_maja_naglowki_szablonu():
    workbook = load_workbook(BytesIO(build_workbook(_sample_rows())))
    assert workbook.sheetnames == [OPTION_SHEET, FULL_SHEET]
    assert [c.value for c in workbook[OPTION_SHEET][1]] == list(OPTION_HEADERS)
    assert [c.value for c in workbook[FULL_SHEET][1]] == list(FULL_HEADERS)


def test_kolumny_wyliczane_sa_formulami_z_szablonu():
    sheet = load_workbook(BytesIO(build_workbook(_sample_rows())))[FULL_SHEET]
    assert sheet["U2"].value == 400
    assert sheet["X2"].value == 640
    assert sheet["L2"].value == "=IF(I2>=2,1,0)"
    assert sheet["W2"].value == '=IF(OR(U2="",V2=""),"",AVERAGE(U2:V2))'
    assert sheet["Z2"].value == '=IF(OR(X2="",Y2=""),"",AVERAGE(X2:Y2))'
    assert sheet["AA2"].value == '=IF(OR(Z2="",W2=""),"",(Z2-W2)/W2)'
    assert sheet["AB2"].value == '=IF(OR(V2="",X2=""),"",X2-V2)'
    assert sheet["AC2"].value == '=IF(AB2="","",AB2/V2)'


def test_tekst_od_znaku_rownosci_nie_staje_sie_formula():
    rows = [build_row(job(client_reference="=HYPERLINK(\"http://x\")"), [], BANDS)]
    cell = load_workbook(BytesIO(build_workbook(rows)))[OPTION_SHEET]["D2"]
    assert cell.data_type == "s"


def test_znak_sterujacy_w_numerze_nie_wywraca_eksportu():
    rows = [build_row(job(client_reference="RITM\x01123"), [], BANDS)]
    sheet = load_workbook(BytesIO(build_workbook(rows)))[OPTION_SHEET]
    assert sheet["D2"].value == "RITM123"


def test_brak_danych_zaznaczony_kolorem():
    sheet = load_workbook(BytesIO(build_workbook(_sample_rows())))[OPTION_SHEET]
    assert sheet["D3"].value is None
    assert sheet["D3"].fill.fgColor.rgb.endswith("FFF2CC")
    assert sheet["A2"].value.date() == date(2026, 10, 8)
    assert sheet["A2"].number_format == "DD.MM.YYYY"
    assert date(2026, 10, 8) + timedelta(days=14) == sheet["C2"].value.date()


@pytest.mark.asyncio
async def test_zmiana_seniority_odswieza_dopasowania_jak_edycja_rekrutacji():
    from app.api import bnp_report
    from app.models.job import JobStatus

    published = SimpleNamespace(id=5, status=JobStatus.published)
    tasks = MagicMock()
    db = AsyncMock()
    with (
        patch.object(bnp_report, "_maybe_embed_job", AsyncMock()) as embed,
        patch.object(bnp_report, "mark_stale_for_job", AsyncMock()) as stale,
        patch.object(bnp_report, "mark_latest_snapshot_stale", AsyncMock()) as snapshot,
        patch.object(bnp_report.settings, "MARKETPLACE_ENABLED", False),
    ):
        await bnp_report.refresh_matching_after_seniority(published, db, tasks)
    embed.assert_awaited_once_with(5, db)
    stale.assert_awaited_once_with(db, 5)
    snapshot.assert_awaited_once_with(5, db)
    tasks.add_task.assert_called_once_with(bnp_report.enqueue_job_safe, 5)
