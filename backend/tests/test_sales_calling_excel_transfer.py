"""Przeniesienie Excela dzwoniących (arkusz = osoba, kolor = wynik): parser i trasy.

Skoroszyt budowany w teście, dane fikcyjne. Baza testowa jest wspólna: każdy test ma
własną kampanię, osoby i losowe numery.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesCallDayTotal, SalesCallRecord
from app.services.sales import calling_excel as excel
from tests.test_sales_calling_queue import URL, _campaign
from tests.test_sales_companies_api import _headers, _user

TODAY = date(2026, 11, 18)
HEADER = [
    "Imię",
    "Nazwisko",
    "Stanowisko",
    "Nazwa firmy",
    "Telefon",
    "E-mail",
    "LinkedIn",
    "Komentarz po rozmowie (np. nie odebrał; wysłać ofertę; nie jest zainteresowany)",
    "Czy wysłana oferta (prezentacja)? ",
    "Czy umówione spotkanie?",
    "Ponowny kontakt",
    "Uwagi",
]
RED, RED_2, YELLOW, BLUE, GREEN = (
    "FFFF5E5E",
    "FFFF0000",
    "FFFFFF00",
    "FF00B0F0",
    "FF92D050",
)


def _phone() -> str:
    return f"5{uuid.uuid4().int % 10**8:08d}"


def _workbook(sheets: dict[str, list[tuple[list[Any], Optional[str]]]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill

    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        sheet.append(HEADER)
        for values, color in rows:
            sheet.append(values)
            if color:
                for cell in sheet[sheet.max_row][:12]:
                    cell.fill = PatternFill("solid", fgColor=color)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _person(
    company: str,
    phone: Optional[str],
    comment: Optional[str] = None,
    callback: Any = None,
    remarks: Optional[str] = None,
) -> list[Any]:
    return [
        "Jan",
        "Testowy",
        "CTO",
        company,
        phone,
        None,
        None,
        comment,
        None,
        None,
        callback,
        remarks,
    ]


# ── Wynik wiersza ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rgb", "state"),
    [
        (RED, "not_interested"),
        (RED_2, "not_interested"),
        (YELLOW, "offer_sent"),
        (BLUE, "meeting_booked"),
        ("FF00B050", "interested"),
        (GREEN, "interested"),
        ("FFFFFFFF", None),
        ("FFD9D9D9", None),
        (None, None),
        ("zly", None),
    ],
)
def test_color_state_reads_the_legend_by_hue(
    rgb: Optional[str], state: Optional[str]
) -> None:
    assert excel.color_state(rgb) == state


@pytest.mark.parametrize(
    ("comment", "state"),
    [
        ("nie odbiera", "no_answer"),
        ("Nie odebrał", "no_answer"),
        ("nie jest zainteresowany.", "not_interested"),
        ("nie zaintersowany, jednoosobowa firma", "not_interested"),
        ("brak danych kontaktowych", "bad_contact"),
        ("wysłac oferte", "offer_sent"),
        ("urlop", "call_back"),
        ("dzwonic 12.11", "call_back"),
        ("ciekawa firma", excel.REVIEW),
        ("niezainteresowani", "not_interested"),
        ("Nie są zainteresowani", "not_interested"),
        # Audyt 12.11 (S1): „nie” wewnątrz słowa to nie zaprzeczenie.
        ("Zainteresowany, prosi o spotkanie", excel.REVIEW),
        ("zainteresowany, zadzwonić w poniedziałek", "call_back"),
        ("chętnie, zainteresowana", excel.REVIEW),
        ("zainteresowany ofertą", "offer_sent"),
        ("brak", None),
        (None, None),
    ],
)
def test_comment_state_understands_the_typos(
    comment: Optional[str], state: Optional[str]
) -> None:
    assert excel.comment_state(comment) == state


def test_parse_day_infers_the_year() -> None:
    assert excel.parse_day("27.07 Podsumowanie", TODAY) == date(2026, 7, 27)
    assert excel.parse_day("pn, 16.11.2026 12:30", TODAY) == date(2026, 11, 16)
    assert excel.parse_day(datetime(2026, 11, 3), TODAY) == date(2026, 11, 3)
    # Bez roku: bieżący rok, chyba że data wypada ponad 60 dni po dziś (wtedy poprzedni).
    assert excel.parse_day("zadzwonić 05.01", TODAY) == date(2026, 1, 5)
    assert excel.parse_day("10.12", TODAY) == date(2026, 12, 10)
    assert excel.parse_day("31.12", date(2026, 7, 1)) == date(2025, 12, 31)
    assert excel.parse_day("bez daty", TODAY) is None


def test_suggest_matches_the_sheet_title_to_one_first_name() -> None:
    people = [
        (1, "Bianca Testowa"),
        (2, "Marcel Przykładowy"),
        (3, "Marek Inny"),
        (4, "Marek Drugi"),
    ]
    assert excel.suggest("Bianca", people) == 1
    assert excel.suggest(" marcel ", people) == 2
    assert excel.suggest("Marek", people) is None
    assert excel.suggest("Arkusz1", people) is None


# ── Skoroszyt ─────────────────────────────────────────────────────────────


def test_workbook_rows_states_callbacks_summaries_and_moves() -> None:
    shared = _phone()
    payload = _workbook(
        {
            "Ola": [
                (_person("Czerwona", _phone()), RED),
                (_person("Żółta", _phone()), YELLOW),
                (_person("Niebieska", _phone()), BLUE),
                (_person("Zielona", _phone()), GREEN),
                (_person("Bez koloru", _phone(), "nie odbiera"), None),
                (
                    _person("Oddzwoń", _phone(), "zadzwonić", datetime(2026, 11, 25)),
                    None,
                ),
                (_person("Dawno", _phone(), "zadzwonić", "22.07.2026"), None),
                (
                    _person(
                        "Ciekawa",
                        _phone(),
                        "ciekawa firma",
                        None,
                        "LinkedIn: potwierdzone",
                    ),
                    None,
                ),
                (_person("Przekazana", shared, "nie odbiera"), None),
                (_person("Bez numeru", None, "nie odbiera"), None),
                (
                    [
                        None,
                        None,
                        None,
                        None,
                        None,
                        "27.07 Podsumowanie",
                        "Wykonane telefony: 40",
                        "Rozmowy: 19",
                        "Wysłane Oferty: 6",
                        "Spotkania: 0",
                    ],
                    None,
                ),
                (
                    [
                        datetime(2026, 11, 3),
                        "wykonane telefony:",
                        84,
                        "Rozmowy:",
                        37,
                        "wysłane oferty:",
                        9,
                        "spotkania:",
                        6,
                    ],
                    None,
                ),
                (
                    [
                        datetime(2026, 11, 3),
                        "wykonane telefony:",
                        80,
                        "Rozmowy:",
                        30,
                        "wysłane oferty:",
                        5,
                        "spotkania:",
                        2,
                    ],
                    None,
                ),
                (
                    [
                        "Połowa dnia",
                        None,
                        None,
                        None,
                        None,
                        "Wykonane telefony: 35",
                        "Rozmowy: 15",
                        "Wysłane Oferty: 1",
                        "Spotkania: 1",
                    ],
                    None,
                ),
            ],
            "Jan": [(_person("Przekazana", shared, "nie zaintersowany"), None)],
        }
    )
    ola, jan = excel.parse_workbook("lista.xlsx", payload, TODAY)
    states = {item.row.company: item for item in ola.rows}

    assert states["Czerwona"].state == "not_interested"
    assert states["Czerwona"].callback_on >= TODAY + timedelta(days=182)
    assert states["Żółta"].state == "offer_sent"
    assert states["Niebieska"].state == states["Zielona"].state == "meeting_booked"
    assert states["Niebieska"].callback_on is None
    assert states["Bez koloru"].state == "no_answer"
    assert states["Bez koloru"].callback_on > TODAY
    assert states["Oddzwoń"].callback_on == date(2026, 11, 25)
    # Data z przeszłości: do zrobienia dziś.
    assert states["Dawno"].callback_on == TODAY
    assert states["Ciekawa"].state == "new" and states["Ciekawa"].review
    assert (
        states["Ciekawa"].row.note == "Z Excela: ciekawa firma · LinkedIn: potwierdzone"
    )
    # Ten sam numer u dwóch osób zostaje w późniejszym arkuszu.
    assert "Przekazana" not in states and ola.moved == 1
    assert [item.row.company for item in jan.rows] == ["Przekazana"]
    assert jan.rows[0].state == "not_interested"
    # Wiersz bez numeru zostaje osobą bez telefonu (bramka importu go odrzuci).
    assert states["Bez numeru"].row.phone is None
    # Podsumowania: dwa formaty, ten sam dzień dwa razy = późniejszy, bez daty = pominięty.
    assert ola.days[date(2026, 7, 27)] == excel.DayTotal(
        date(2026, 7, 27), 40, 19, 6, 0
    )
    assert ola.days[date(2026, 11, 3)].calls == 80
    assert ola.duplicate_days == 1 and len(ola.days) == 2


def test_workbook_rejects_csv_and_too_many_sheets() -> None:
    with pytest.raises(excel.ListFileError):
        excel.parse_workbook("lista.csv", b"Firma;Telefon\nA;1", TODAY)
    payload = _workbook(
        {
            f"Arkusz {i}": [(_person("A", _phone()), None)]
            for i in range(excel.MAX_SHEETS + 1)
        }
    )
    with pytest.raises(excel.ListFileError, match="arkuszy"):
        excel.parse_workbook("lista.xlsx", payload, TODAY)


# ── Trasy ─────────────────────────────────────────────────────────────────


async def _post(app_client, user, path: str, payload: bytes, **data: Any):
    return await app_client.post(
        f"{URL}/campaigns/{data.pop('campaign_id')}/{path}",
        files={
            "file": (
                "excel.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data=data,
        headers=_headers(user),
    )


@pytest.mark.asyncio
async def test_preview_and_transfer_put_each_sheet_into_its_persons_queue(
    app_client,
) -> None:
    lead = await _user("sales_view", "sales_edit")
    ola = await _user("sales_view", "sales_edit")
    jan = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign("Excel")
    marker = uuid.uuid4().hex[:8]
    payload = _workbook(
        {
            "Ola": [
                (_person(f"Czerwona {marker}", _phone()), RED),
                (_person(f"Cisza {marker}", _phone(), "nie odbiera"), None),
                (
                    [
                        datetime(2026, 11, 3),
                        "wykonane telefony:",
                        84,
                        "Rozmowy:",
                        37,
                        "wysłane oferty:",
                        9,
                        "spotkania:",
                        6,
                    ],
                    None,
                ),
            ],
            "Jan": [(_person(f"Oferta {marker}", _phone()), YELLOW)],
        }
    )
    assignees = json.dumps({"Ola": ola.id, "Jan": jan.id})

    preview = await _post(
        app_client,
        lead,
        "excel/preview",
        payload,
        campaign_id=campaign_id,
        assignees=assignees,
    )
    assert preview.status_code == 200, preview.text
    sheets = {sheet["title"]: sheet for sheet in preview.json()["sheets"]}
    assert sheets["Ola"]["states"] == {"not_interested": 1, "no_answer": 1}
    assert sheets["Ola"]["days"] == 1 and sheets["Ola"]["totals"]["calls"] == 84
    assert sheets["Jan"]["addable"] == 1
    async with AsyncSessionLocal() as db:
        nothing = await db.scalar(
            select(SalesCallRecord.id).where(SalesCallRecord.campaign_id == campaign_id)
        )
    assert nothing is None  # podgląd niczego nie zapisuje

    resp = await _post(
        app_client,
        lead,
        "excel",
        payload,
        campaign_id=campaign_id,
        assignees=assignees,
        contact_source="Excel dzwoniących",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"added": 3, "days": 1}
    async with AsyncSessionLocal() as db:
        records = list(
            (
                await db.execute(
                    select(SalesCallRecord).where(
                        SalesCallRecord.campaign_id == campaign_id
                    )
                )
            ).scalars()
        )
        totals = list(
            (
                await db.execute(
                    select(SalesCallDayTotal).where(SalesCallDayTotal.user_id == ola.id)
                )
            ).scalars()
        )
    by_company = {record.company_id: record for record in records}
    assert {(r.assigned_user_id, r.state) for r in by_company.values()} == {
        (ola.id, "not_interested"),
        (ola.id, "no_answer"),
        (jan.id, "offer_sent"),
    }
    assert all(
        r.attempts == 1 and r.contact_source == "Excel dzwoniących" for r in records
    )
    assert [(t.day, t.calls, t.meetings) for t in totals] == [
        (date(2026, 11, 3), 84, 6)
    ]

    # Drugi raz ten sam plik: bez dubli, podsumowanie nadpisane, nie powielone.
    again = await _post(
        app_client,
        lead,
        "excel",
        payload,
        campaign_id=campaign_id,
        assignees=assignees,
        contact_source="Excel dzwoniących",
    )
    assert again.json() == {"added": 0, "days": 1}
    async with AsyncSessionLocal() as db:
        count = len(
            list(
                (
                    await db.execute(
                        select(SalesCallDayTotal.id).where(
                            SalesCallDayTotal.user_id == ola.id
                        )
                    )
                ).scalars()
            )
        )
    assert count == 1


@pytest.mark.asyncio
async def test_preview_counts_a_company_taken_by_an_earlier_sheet(app_client) -> None:
    """Audyt 12.11 (S9): podgląd planował arkusze osobno, zapis idzie po kolei.

    Ta sama firma w dwóch arkuszach: drugi arkusz trafia na kolejkę pierwszej osoby
    (``other_caller``), więc podgląd ma to pokazać, zamiast obiecać więcej.
    """

    lead = await _user("sales_view", "sales_edit")
    ola = await _user("sales_view", "sales_edit")
    jan = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign("Excel dwa arkusze")
    shared = f"Wspólna {uuid.uuid4().hex[:8]}"
    other = _person(shared, _phone())
    other[0] = "Ewa"
    payload = _workbook(
        {
            "Ola": [(_person(shared, _phone(), "nie odbiera"), None)],
            "Jan": [(other, YELLOW)],
        }
    )
    assignees = json.dumps({"Ola": ola.id, "Jan": jan.id})

    preview = await _post(
        app_client,
        lead,
        "excel/preview",
        payload,
        campaign_id=campaign_id,
        assignees=assignees,
    )
    assert preview.status_code == 200, preview.text
    sheets = {sheet["title"]: sheet for sheet in preview.json()["sheets"]}
    assert sheets["Ola"]["addable"] == 1
    assert (sheets["Jan"]["addable"], sheets["Jan"]["fates"]) == (
        0,
        {"other_caller": 1},
    )
    async with AsyncSessionLocal() as db:
        nothing = await db.scalar(
            select(SalesCallRecord.id).where(SalesCallRecord.campaign_id == campaign_id)
        )
    assert nothing is None  # bieg na sucho niczego nie zostawia

    resp = await _post(
        app_client,
        lead,
        "excel",
        payload,
        campaign_id=campaign_id,
        assignees=assignees,
        contact_source="Excel dzwoniących",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == sum(s["addable"] for s in sheets.values()) == 1


@pytest.mark.asyncio
async def test_transfer_refusals(app_client) -> None:
    lead = await _user("sales_view", "sales_edit")
    viewer = await _user("sales_view")
    campaign_id = await _campaign("Excel odmowy")
    payload = _workbook({"Ola": [(_person("Firma", _phone()), RED)]})

    missing = await _post(
        app_client,
        lead,
        "excel",
        payload,
        campaign_id=campaign_id,
        contact_source="Excel dzwoniących",
    )
    assert missing.status_code == 422
    assert "Ola" in missing.json()["detail"]

    not_allowed = await _post(
        app_client,
        lead,
        "excel",
        payload,
        campaign_id=campaign_id,
        contact_source="Excel dzwoniących",
        assignees=json.dumps({"Ola": viewer.id}),
    )
    assert not_allowed.status_code == 422

    garbage = await _post(
        app_client,
        lead,
        "excel/preview",
        payload,
        campaign_id=campaign_id,
        assignees="[1]",
    )
    assert garbage.status_code == 422

    csv = await app_client.post(
        f"{URL}/campaigns/{campaign_id}/excel/preview",
        files={"file": ("lista.csv", b"Firma;Telefon\nA;600100200", "text/csv")},
        headers=_headers(lead),
    )
    assert csv.status_code == 422

    forbidden = await _post(
        app_client, viewer, "excel/preview", payload, campaign_id=campaign_id
    )
    assert forbidden.status_code == 403
