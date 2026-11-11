"""Dzwonienie → Skuteczność: agregacja, progi wniosków i trasa z odmową.

Część bez bazy liczy ``summarize`` na fikcyjnych telefonach. Część z bazą idzie
przez prawdziwy zapis wyniku z kolejki, więc pilnuje też znacznika rekordu
w dzienniku (``external_source = 'call_queue'``). Baza testowa jest wspólna:
asercje patrzą na własną kampanię i własnego dzwoniącego.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pytest

from app.core.scheduling import DEFAULT_TZ
from app.services.sales import calling_stats as stats
from app.services.sales.calling import CALL_SOURCE
from app.services.sales.calling_stats import (
    CallRow,
    CampaignInfo,
    DayTotalRow,
    MeetingRow,
)
from tests.test_sales_calling_queue import (
    URL,
    _calls,
    _campaign,
    _company,
    _opportunity,
    _record,
    _save,
)
from tests.test_sales_companies_api import _headers, _user

ZONE = ZoneInfo(DEFAULT_TZ)
# Poniedziałek 09.11.2026; 11.11 to święto (Narodowe Święto Niepodległości).
MONDAY = date(2026, 11, 9)


def _at(day: date, hour: int = 10) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=ZONE)


def _call(
    outcome: str,
    *,
    user: int = 1,
    day: date = MONDAY,
    hour: int = 10,
    record: Optional[int] = None,
    campaign: Optional[int] = None,
    source: Optional[str] = None,
    opportunity: Optional[int] = None,
) -> CallRow:
    return CallRow(
        user_id=user,
        at=_at(day, hour),
        outcome=outcome,
        record_id=record,
        campaign_id=campaign,
        contact_source=source,
        from_opportunity=record is not None and campaign is None,
        opportunity_id=opportunity,
    )


def _summary(calls: list[CallRow], **kwargs):
    params = {
        "meetings": {},
        "campaigns": [],
        "record_states": {},
        "names": {1: "Osoba A", 2: "Osoba B"},
        "start": MONDAY,
        "end": MONDAY + timedelta(days=4),
        "today": MONDAY + timedelta(days=4),
    }
    params.update(kwargs)
    return stats.summarize(calls=calls, **params)


# ── Okres ─────────────────────────────────────────────────────────────────


def test_period_bounds_follow_the_company_calendar() -> None:
    wednesday = MONDAY + timedelta(days=2)
    assert stats.period_bounds("week", wednesday, None) == (MONDAY, wednesday)
    assert stats.period_bounds("4w", wednesday, None) == (
        wednesday - timedelta(days=27),
        wednesday,
    )
    assert stats.period_bounds("all", wednesday, date(2026, 11, 2)) == (
        date(2026, 11, 2),
        wednesday,
    )
    # Bez żadnego telefonu „cała kampania” to sam dzisiejszy dzień.
    assert stats.period_bounds("all", wednesday, None) == (wednesday, wednesday)


def test_workdays_skip_weekend_and_holiday() -> None:
    # 09–15.11.2026: pon, wt, (śr 11.11 święto), czw, pt, (sob, nd).
    assert stats.workdays_between(MONDAY, MONDAY + timedelta(days=6)) == 4
    assert stats.workdays_between(MONDAY, MONDAY - timedelta(days=1)) == 0


# ── Lejek i wyniki ────────────────────────────────────────────────────────


def test_funnel_counts_talks_without_no_answer_and_meetings_of_the_period() -> None:
    calls = [
        _call("no_answer"),
        _call("no_answer"),
        _call("not_now"),
        _call("offer_sent", record=10, campaign=5),
        _call("meeting_booked", opportunity=100),
        _call("meeting_booked", opportunity=101),
    ]
    meetings = {
        100: MeetingRow(100, dated=True, verdict="qualified"),
        101: MeetingRow(101, dated=False, verdict=None),
        # Szansa spoza okresu nie wchodzi do lejka.
        102: MeetingRow(102, dated=True, verdict="qualified"),
    }
    result = _summary(calls, meetings=meetings)
    funnel = result.funnel
    assert (funnel.calls, funnel.talks, funnel.offers, funnel.meetings) == (6, 4, 1, 2)
    assert (funnel.dated, funnel.held, funnel.qualified) == (1, 1, 1)
    assert result.outcomes == {
        "no_answer": 2,
        "not_now": 1,
        "offer_sent": 1,
        "meeting_booked": 2,
    }


def test_no_show_is_not_a_held_meeting() -> None:
    calls = [_call("meeting_booked", opportunity=7)]
    result = _summary(calls, meetings={7: MeetingRow(7, dated=True, verdict="no_show")})
    assert (result.funnel.held, result.funnel.qualified) == (0, 0)


# ── Kampanie i listy ──────────────────────────────────────────────────────


def test_campaign_pace_counts_touched_records_per_workday() -> None:
    # 4 dni robocze (święto w środku), 8 różnych rekordów → 2 dziennie.
    calls = [_call("no_answer", record=i, campaign=5) for i in range(8)]
    calls += [_call("no_answer", record=0, campaign=5)]  # drugi telefon do tego samego
    info = CampaignInfo(id=5, name="Kampania", service="Usługa", on_list=50, left=9)
    result = _summary(
        calls,
        campaigns=[
            info,
            CampaignInfo(id=6, name="Pusta", service=None, on_list=3, left=3),
        ],
        end=MONDAY + timedelta(days=6),
        today=MONDAY + timedelta(days=6),
    )
    first, empty = result.campaigns
    assert (first.id, first.calls, first.talks, first.days_left) == (5, 9, 0, 5)
    # Kampania bez telefonów w okresie: lista jest, tempa nie ma.
    assert (empty.id, empty.calls, empty.days_left) == (6, 0, None)


def test_calls_without_campaign_land_in_one_row_at_the_end() -> None:
    calls = [
        _call("offer_sent", record=1, campaign=5),
        _call("meeting_booked"),  # z karty szansy
        _call("not_now", record=2),  # rekord szansy z etapu „Lead”
    ]
    info = CampaignInfo(id=5, name="Kampania", service=None, on_list=1, left=0)
    result = _summary(calls, campaigns=[info])
    assert [row.name for row in result.campaigns] == ["Kampania", stats.NO_CAMPAIGN]
    assert result.campaigns[-1].calls == 2


def test_sources_count_each_record_once_and_name_the_loose_calls() -> None:
    calls = [
        _call("no_answer", record=1, campaign=5, source="Lista A"),
        _call("meeting_booked", record=1, campaign=5, source="Lista A"),
        _call("do_not_contact", record=2, campaign=5, source="Lista A"),
        _call("no_answer", record=3, campaign=5, source=" "),
        _call("offer_sent", record=4),
        _call("connected"),
    ]
    by_name = {s.source: s for s in _summary(calls).sources}
    lista = by_name["Lista A"]
    assert (
        lista.records,
        lista.reached,
        lista.talks,
        lista.meetings,
        lista.objections,
    ) == (
        2,
        2,
        2,
        1,
        1,
    )
    assert by_name[stats.NO_SOURCE].reached == 0
    assert stats.LEAD_SOURCE in by_name and stats.CARD_SOURCE in by_name


# ── Pory dnia, oferta, osoby ──────────────────────────────────────────────


def test_hour_map_hides_thin_cells_and_skips_weekends_and_evenings() -> None:
    calls = [_call("connected", hour=9) for _ in range(4)] + [
        _call("no_answer", hour=9)
    ]
    calls += [_call("connected", hour=11) for _ in range(4)]
    calls += [_call("connected", day=MONDAY + timedelta(days=5), hour=10)]  # sobota
    calls += [_call("connected", hour=19)]  # po 18
    cells = {(c.weekday, c.hour): c for c in _summary(calls).hours}
    assert len(cells) == 5 * len(stats.HOURS)
    assert cells[(0, 9)].rate == pytest.approx(0.8)
    assert cells[(0, 11)].calls == 4 and cells[(0, 11)].rate is None
    assert sum(c.calls for c in cells.values()) == 9


def test_offer_followup_reads_the_current_state_of_offered_records() -> None:
    calls = [
        _call("offer_sent", record=1, campaign=5),
        _call("offer_sent", record=2, campaign=5),
        _call("offer_sent", record=3, campaign=5),
        _call("no_answer", record=4, campaign=5),
    ]
    states = {1: "offer_sent", 2: "meeting_booked", 3: "not_now", 4: "no_answer"}
    assert _summary(calls, record_states=states).offer_followup == {
        "offer_sent": 1,
        "meeting_booked": 1,
        "not_now": 1,
    }


def test_people_are_ranked_by_meetings_with_their_own_dated_meetings() -> None:
    calls = [
        _call("connected", user=1, day=MONDAY),
        _call("meeting_booked", user=1, day=MONDAY + timedelta(days=1), opportunity=9),
        _call("meeting_booked", user=2, opportunity=7),
        _call("meeting_booked", user=2, opportunity=8),
    ]
    meetings = {
        7: MeetingRow(7, dated=True, verdict=None),
        8: MeetingRow(8, dated=False, verdict=None),
        9: MeetingRow(9, dated=True, verdict="qualified"),
    }
    first, second = _summary(calls, meetings=meetings).people
    assert (first.name, first.meetings, first.dated, first.days) == ("Osoba B", 2, 1, 1)
    assert (second.name, second.days, second.calls, second.qualified) == (
        "Osoba A",
        2,
        2,
        1,
    )


# ── Wnioski ───────────────────────────────────────────────────────────────


def test_without_calls_there_is_one_plain_sentence() -> None:
    [insight] = _summary([]).insights
    assert "nie ma zapisanych telefonów" in insight.text


def test_small_samples_give_no_hour_or_list_comparison() -> None:
    calls = [
        _call("connected", hour=9, source="A", record=i, campaign=1) for i in range(20)
    ]
    calls += [
        _call("no_answer", hour=15, source="B", record=100 + i, campaign=1)
        for i in range(20)
    ]
    texts = " ".join(i.text for i in _summary(calls).insights)
    assert "odbierają" not in texts and "Lista" not in texts


def test_enough_calls_name_the_best_hour_and_the_better_list() -> None:
    calls = [
        _call(
            "meeting_booked" if i % 3 == 0 else "connected",
            hour=9,
            source="A",
            record=i,
            campaign=1,
        )
        for i in range(60)
    ]
    calls += [
        _call(
            "connected" if i % 2 else "no_answer",
            hour=15,
            source="B",
            record=100 + i,
            campaign=1,
        )
        for i in range(70)
    ]
    texts = [i.text for i in _summary(calls).insights]
    assert any("Najczęściej odbierają o 9:00 (100% rozmów)" in t for t in texts)
    assert any(
        t.startswith("Lista „A” daje spotkanie w 33% rozmów, „B” w 0%") for t in texts
    )


def test_undated_meetings_and_waiting_offers_are_flagged() -> None:
    calls = [
        _call("meeting_booked", opportunity=1),
        _call("meeting_booked", opportunity=2),
        _call("offer_sent", record=5, campaign=1),
    ]
    meetings = {1: MeetingRow(1, True, None), 2: MeetingRow(2, False, None)}
    texts = [
        i.text
        for i in _summary(
            calls, meetings=meetings, record_states={5: "offer_sent"}
        ).insights
    ]
    assert texts[0].startswith("1 z 2 umówionych spotkań nie ma terminu")
    assert any(
        t.startswith("Oferty ogólne z tego okresu czekające na oddzwonienie: 1.")
        for t in texts
    )


# ── Trasa ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_effectiveness_needs_sales_edit(app_client) -> None:
    viewer = await _user("sales_view")
    resp = await app_client.get(f"{URL}/effectiveness", headers=_headers(viewer))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_queue_outcome_is_counted_in_campaign_list_and_ranking(
    app_client,
) -> None:
    caller = await _user("sales_view", "sales_edit")
    other = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign("Skuteczność")
    company_id = await _company()
    record_id = await _record(
        caller.id, campaign_id, company_id, contact_source="Lista testowa"
    )
    await _record(
        caller.id, campaign_id, await _company(), contact_source="Lista testowa"
    )

    resp = await _save(app_client, caller, record_id, outcome="no_answer")
    assert resp.status_code == 200, resp.text
    # Drugi telefon do tego samego rekordu: znacznik nie może zderzyć się z pierwszym.
    resp = await _save(app_client, caller, record_id, outcome="offer_sent")
    assert resp.status_code == 200, resp.text
    calls = await _calls(company_id)
    assert [(c.external_source, c.external_id) for c in calls] == [
        (CALL_SOURCE, f"{record_id}:1"),
        (CALL_SOURCE, f"{record_id}:2"),
    ]

    resp = await app_client.get(
        f"{URL}/effectiveness",
        params={"campaign_id": campaign_id},
        headers=_headers(other),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    funnel = body["funnel"]
    assert (funnel["calls"], funnel["talks"], funnel["offers"]) == (2, 1, 1)
    [row] = body["campaigns"]
    assert (row["id"], row["on_list"], row["left"], row["offers"]) == (
        campaign_id,
        2,
        1,
        1,
    )
    assert body["sources"][0]["source"] == "Lista testowa"
    assert body["offer_followup"] == {"offer_sent": 1}
    # Pełna tabela osób: drugi dzwoniący widzi wiersz pierwszego.
    assert [p["user_id"] for p in body["people"]] == [caller.id]
    assert {"id": campaign_id, "name": row["name"]} in body["campaign_options"]

    mine = await app_client.get(
        f"{URL}/effectiveness",
        params={"campaign_id": campaign_id, "mine": "true"},
        headers=_headers(other),
    )
    assert mine.json()["funnel"]["calls"] == 0


@pytest.mark.asyncio
async def test_meeting_from_queue_counts_as_dated_after_logging_a_meeting(
    app_client,
) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign("Spotkania")
    company_id = await _company()
    record_id = await _record(caller.id, campaign_id, company_id)
    opp_id = await _opportunity(caller.id, company_id, stage="qualifying-meeting")
    resp = await _save(
        app_client, caller, record_id, outcome="meeting_booked", opportunity_id=opp_id
    )
    assert resp.status_code == 200, resp.text

    params = {"campaign_id": campaign_id, "mine": "true"}
    body = (
        await app_client.get(
            f"{URL}/effectiveness", params=params, headers=_headers(caller)
        )
    ).json()
    assert (body["funnel"]["meetings"], body["funnel"]["dated"]) == (1, 0)

    from app.core.database import AsyncSessionLocal
    from app.models.sales import SalesActivity

    async with AsyncSessionLocal() as db:
        db.add(
            SalesActivity(
                kind="meeting",
                subject="Spotkanie wstępne",
                company_id=company_id,
                opportunity_id=opp_id,
                created_by_user_id=caller.id,
                occurred_at=datetime.now(ZONE) + timedelta(days=2),
            )
        )
        await db.commit()
    body = (
        await app_client.get(
            f"{URL}/effectiveness", params=params, headers=_headers(caller)
        )
    ).json()
    assert body["funnel"]["dated"] == 1
    assert body["people"][0]["dated"] == 1


def test_second_meeting_result_for_one_opportunity_counts_once() -> None:
    # Rekord szansy zostaje w kolejce po „Umówionym spotkaniu” (dzwoniący ustala
    # termin), więc ten sam wynik może paść dwa razy dla jednej szansy.
    calls = [
        _call("meeting_booked", record=5, opportunity=7),
        _call("meeting_booked", record=5, opportunity=7),
        _call("meeting_booked"),  # z karty szansy, bez id: liczy się jako jedno
    ]
    result = _summary(
        calls, meetings={7: MeetingRow(7, dated=True, verdict="qualified")}
    )
    assert (result.funnel.meetings, result.funnel.dated) == (2, 1)
    assert result.outcomes["meeting_booked"] == 3
    [person] = result.people
    assert (person.meetings, person.dated) == (2, 1)
    lead = next(s for s in result.sources if s.source == stats.LEAD_SOURCE)
    assert lead.meetings == 1
    assert result.insights[0].text.startswith("1 z 2 umówionych spotkań")


def test_bad_number_is_an_attempt_not_a_talk() -> None:
    # „Zły numer / brak danych” to próba bez rozmowy, jak „Nie odebrał” (mapa decyzyjna tak samo).
    result = _summary(
        [_call("bad_contact"), _call("not_interested"), _call("no_answer")]
    )
    assert (result.funnel.calls, result.funnel.talks) == (3, 1)


# ── Historia z Excela (sales_call_day_totals) ──────────────────────────────


def _excel(
    day: date,
    *,
    user: int = 1,
    calls: int = 40,
    talks: int = 19,
    offers: int = 6,
    meetings: int = 1,
) -> DayTotalRow:
    return DayTotalRow(user, day, calls, talks, offers, meetings)


def test_excel_day_counts_only_when_the_journal_has_no_call_that_day() -> None:
    tuesday = MONDAY + timedelta(days=1)
    calls = [_call("no_answer", day=MONDAY), _call("connected", day=MONDAY)]
    result = _summary(
        calls,
        day_totals=[
            # Ten sam dzień i osoba co telefony w dzienniku: dziennik wygrywa.
            _excel(MONDAY, calls=99, talks=50, offers=9, meetings=5),
            _excel(tuesday),
            # Inna osoba tego samego dnia co dziennik osoby 1: jej Excel się liczy.
            _excel(MONDAY, user=2, calls=10, talks=4, offers=1, meetings=0),
        ],
    )
    f = result.funnel
    assert (f.calls, f.talks, f.offers, f.meetings) == (
        2 + 40 + 10,
        1 + 19 + 4,
        6 + 1,
        1,
    )
    assert result.excel == stats.ExcelShare(
        days=2, calls=50, talks=23, offers=7, meetings=1
    )
    # Wyniki, kampanie, listy i godziny zna tylko dziennik.
    assert sum(result.outcomes.values()) == 2
    assert sum(c.calls for c in result.hours) == 2

    by_user = {p.user_id: p for p in result.people}
    assert (by_user[1].days, by_user[1].excel_days, by_user[1].calls) == (2, 1, 42)
    assert (by_user[2].days, by_user[2].excel_days, by_user[2].calls) == (1, 1, 10)
    # Środa to święto (11.11), czwartek i piątek bez liczb zostają na osi jako luka.
    assert [(d.day, d.calls, d.source) for d in result.daily] == [
        (MONDAY, 12, "mixed"),
        (tuesday, 40, "excel"),
        (MONDAY + timedelta(days=3), 0, "none"),
        (MONDAY + timedelta(days=4), 0, "none"),
    ]


def test_excel_meetings_are_not_flagged_as_undated() -> None:
    # Excel nie zna terminów: tylko spotkania z dziennika mogą być „bez terminu”.
    result = _summary(
        [_call("connected")], day_totals=[_excel(MONDAY + timedelta(days=1))]
    )
    assert result.funnel.meetings == 1
    assert not any("terminu" in i.text for i in result.insights)
    [person] = result.people
    assert (person.meetings, person.excel_meetings, person.dated) == (1, 1, 0)


def test_only_excel_in_the_period_is_not_an_empty_screen() -> None:
    result = _summary([], day_totals=[_excel(MONDAY)])
    assert result.funnel.calls == 40
    assert result.daily[0].source == "excel"
    assert not any("nie ma zapisanych" in i.text for i in result.insights)


@pytest.mark.asyncio
async def test_effectiveness_reads_excel_history_without_double_counting(
    app_client,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.sales import SalesCallDayTotal
    from app.services import sales_schema as schema

    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign("Excel i kolejka")
    record_id = await _record(caller.id, campaign_id, await _company())
    resp = await _save(app_client, caller, record_id, outcome="offer_sent")
    assert resp.status_code == 200, resp.text

    first_day = date(2026, 7, 27)
    async with AsyncSessionLocal() as db:
        for day, calls in ((first_day, 40), (business_today(), 99)):
            db.add(
                SalesCallDayTotal(
                    user_id=caller.id,
                    day=day,
                    source=schema.CALL_DAY_TOTALS_EXCEL,
                    calls=calls,
                    talks=19,
                    offers=6,
                    meetings=0,
                )
            )
        await db.commit()

    body = (
        await app_client.get(
            f"{URL}/effectiveness",
            params={"period": "all", "mine": "true"},
            headers=_headers(caller),
        )
    ).json()
    assert date.fromisoformat(body["start"]) <= first_day
    # Dziś jest telefon w dzienniku, więc dzisiejsze 99 z Excela się nie liczy.
    assert body["funnel"]["calls"] == 1 + 40
    assert body["excel"]["days"] == 1
    filled = [(d["day"], d["source"]) for d in body["daily"] if d["source"] != "none"]
    assert filled[0] == (first_day.isoformat(), "excel")
    assert filled[-1] == (business_today().isoformat(), "journal")
    assert len([f for f in filled if f[0] == first_day.isoformat()]) == 1
    [person] = body["people"]
    assert (person["days"], person["excel_days"]) == (2, 1)

    # Excel nie zna kampanii: filtr kampanii pokazuje sam dziennik.
    only_campaign = (
        await app_client.get(
            f"{URL}/effectiveness",
            params={"period": "all", "mine": "true", "campaign_id": campaign_id},
            headers=_headers(caller),
        )
    ).json()
    assert only_campaign["funnel"]["calls"] == 1
    assert only_campaign["excel"]["days"] == 0
