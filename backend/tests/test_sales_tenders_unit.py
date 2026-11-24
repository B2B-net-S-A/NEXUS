"""Przetargi z BZP i TED bez bazy: bramka reguł Kingi, parsowanie rejestrów, kursor BZP, pętla.

→ docs/claude/sprzedaz/przetargi-z-rejestrow.md
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.core.scheduling import DEFAULT_TZ
from app.services.sales.tenders import flow, rules, sources
from app.services.sales.tenders.rules import Notice, TenderRules
from app.tasks import sales_tenders as loop

ZONE = ZoneInfo(DEFAULT_TZ)
NOW = datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 24)


def _notice(**fields: Any) -> Notice:
    base: dict[str, Any] = {
        "source": "bzp",
        "number": "2026/BZP 00000001",
        "title": "Świadczenie usług programistów w modelu body leasing",
        "buyer_name": "Ministerstwo Cyfryzacji",
        "published_at": NOW - timedelta(days=1),
        "order_type": "services",
        "deadline_date": TODAY + timedelta(days=10),
    }
    base.update(fields)
    return Notice(**base)


# ── Dopasowanie fraz ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        ("Zawarcie umowy ramowej na usługi IT", "umowa ramowa"),
        ("Zapewnienie zespołu IT do utrzymania systemu", "zespół IT"),
        ("Usługi programistów Java", "programista"),
        ("Migracji systemów do chmury", "migracja"),
        ("Testów penetracyjnych aplikacji", "testy penetracyjne"),
        ("Wsparcie zgodności z NIS2", "NIS 2"),
        ("Wdrożenie wymogów DORA", "DORA"),
        ("Świadczenie usług IT", "IT"),
    ],
)
def test_phrase_matches_inflected_and_glued_forms(text: str, phrase: str) -> None:
    assert rules.first_match(text, (phrase,)) == phrase


def test_acronym_phrase_matches_only_in_capitals() -> None:
    assert rules.first_match("Usługi IT dla urzędu", ("IT",)) == "IT"
    assert rules.first_match("services it is", ("IT",)) is None
    assert rules.first_match("Usługi ITS", ("IT",)) is None


def test_derived_word_does_not_match_the_stem() -> None:
    """„Wybór dostawcy usługi SOC” to usługa, nie dostawa sprzętu."""

    reject = TenderRules().reject_subject
    assert (
        rules.first_match("Wybór dostawcy usługi Security Operations Center", reject)
        is None
    )
    assert rules.first_match("Dostawy sprzętu komputerowego", reject) == "dostawa"
    assert (
        rules.first_match("Przeprowadzenie szkoleń z cyberbezpieczeństwa", reject)
        == "szkolenie"
    )
    assert (
        rules.first_match("Usługa dostępu do systemu informacji prawnej", reject)
        == "dostęp"
    )


def test_buyer_rules_follow_kinga_instruction() -> None:
    buyers = TenderRules().reject_buyer
    assert rules.first_match("GMINA MIASTO SZCZECIN", buyers) == "gmina"
    assert rules.first_match("Szpitale Zachodniopomorskie SPZOZ", buyers) == "szpital"
    assert (
        rules.first_match("Samodzielny Publiczny ZOZ SP ZOZ w Łodzi", buyers)
        == "SP ZOZ"
    )
    assert rules.first_match("Zakład Wodociągów i Kanalizacji", buyers) == "wodociągi"
    assert rules.first_match("Ministerstwo Finansów", buyers) is None
    assert rules.first_match("Urząd Zamówień Publicznych", buyers) is None


# ── Bramka ──────────────────────────────────────────────────────────────────


def test_notice_outside_it_does_not_enter_the_gate() -> None:
    notice = _notice(title="Remont dachu budynku", cpv_codes=("45261000",))
    assert rules.evaluate(notice, TenderRules(), today=TODAY, now=NOW) is None


def test_it_cpv_code_lets_a_notice_in_without_a_phrase() -> None:
    notice = _notice(title="Utrzymanie systemu finansowego", cpv_codes=("72253200",))
    decision = rules.evaluate(notice, TenderRules(), today=TODAY, now=NOW)
    assert decision is not None and decision.passed
    assert decision.match == "CPV 72253200"


def test_hardware_consultancy_cpv_721_is_not_it_services() -> None:
    notice = _notice(title="Doradztwo sprzętowe", cpv_codes=("72100000",))
    assert rules.evaluate(notice, TenderRules(), today=TODAY, now=NOW) is None


@pytest.mark.parametrize(
    ("fields", "rule", "detail"),
    [
        ({"order_type": "supplies"}, "order_type", "dostawa"),
        ({"order_type": "works"}, "order_type", "roboty budowlane"),
        ({"title": "Zakup licencji dla programistów"}, "subject", "zakup"),
        ({"buyer_name": "Starostwo Powiatowe w Działdowie"}, "buyer", "starostwo"),
        ({"deadline_date": TODAY - timedelta(days=1)}, "expired", None),
    ],
)
def test_gate_rejects_with_the_rule_that_matched(
    fields: dict[str, Any], rule: str, detail: str | None
) -> None:
    decision = rules.evaluate(_notice(**fields), TenderRules(), today=TODAY, now=NOW)
    assert decision is not None and not decision.passed
    assert (decision.rule, decision.detail) == (rule, detail)
    assert decision.match == "fraza „body leasing”" or decision.match.startswith(
        "fraza"
    )


def test_only_services_can_be_switched_off() -> None:
    notice = _notice(order_type="supplies")
    decision = rules.evaluate(
        notice, TenderRules(only_services=False), today=TODAY, now=NOW
    )
    assert decision is not None and decision.passed


def test_exact_deadline_counts_to_the_minute() -> None:
    notice = _notice(deadline_date=TODAY, deadline_at=NOW - timedelta(minutes=1))
    assert rules.is_expired(notice, today=TODAY, now=NOW)
    notice = _notice(deadline_date=TODAY, deadline_at=NOW + timedelta(hours=3))
    assert not rules.is_expired(notice, today=TODAY, now=NOW)
    assert not rules.is_expired(_notice(deadline_date=None), today=TODAY, now=NOW)


def test_rules_from_settings_are_cleaned_and_fall_back_to_defaults() -> None:
    value = {
        "phrases": ["  body   leasing ", "BODY LEASING", "", "x" * 90, 7],
        "only_services": "tak",
        "owner_user_id": True,
    }
    loaded = rules.from_value(value)
    assert loaded.phrases == ("body leasing", "x" * rules.MAX_ITEM_CHARS, "7")
    assert loaded.reject_subject == rules.DEFAULT_REJECT_SUBJECT
    assert loaded.only_services is True
    assert loaded.owner_user_id is None
    assert rules.from_value(None) == TenderRules()
    assert rules.from_value(rules.to_value(loaded)) == loaded


# ── Parsowanie rejestrów ────────────────────────────────────────────────────

BZP_ITEM: dict[str, Any] = {
    "bzpNumber": "2026/BZP 00543285",
    "publicationDate": "2026-11-17T10:21:31.9637498Z",
    "orderObject": "„ Testy bezpieczeństwa   klasy APT”",
    "cpvCode": "72200000-7 (Usługi programowania oprogramowania i doradztwa)",
    "submittingOffersDate": "2026-11-25T09:00:00Z",
    "organizationName": "URZĄD ZAMÓWIEŃ PUBLICZNYCH",
    "organizationCity": "Warszawa",
    "organizationNationalId": "526-16-62-005",
    "orderType": "Services",
    "isTenderAmountBelowEU": True,
    "objectId": "08df4926-e8cc-a6df-7343-eb000163bb96",
}


def test_parse_bzp_keeps_what_the_gate_and_the_opportunity_need() -> None:
    notice = sources.parse_bzp(BZP_ITEM)
    assert notice is not None
    assert notice.number == "2026/BZP 00543285"
    assert notice.title == "„ Testy bezpieczeństwa klasy APT”"
    assert notice.buyer_nip == "5261662005"
    assert notice.cpv_codes == ("72200000",)
    assert notice.order_type == "services"
    assert notice.deadline_at == datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)
    assert notice.deadline_date == date(2026, 11, 25)
    assert notice.published_at.microsecond == 963749
    assert notice.url == (
        "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/"
        "08df4926-e8cc-a6df-7343-eb000163bb96"
    )


def test_parse_bzp_deadline_date_is_the_company_calendar_day() -> None:
    """Termin 23:30 UTC to już następny dzień w Warszawie."""

    item = {**BZP_ITEM, "submittingOffersDate": "2026-11-25T23:30:00Z"}
    notice = sources.parse_bzp(item)
    assert notice is not None and notice.deadline_date == date(2026, 11, 26)


def test_parse_bzp_skips_incomplete_items_and_short_ids() -> None:
    assert sources.parse_bzp({**BZP_ITEM, "bzpNumber": ""}) is None
    assert sources.parse_bzp({**BZP_ITEM, "publicationDate": "wczoraj"}) is None
    regon = sources.parse_bzp({**BZP_ITEM, "organizationNationalId": "012345678"})
    assert regon is not None and regon.buyer_nip is None


TED_ITEM: dict[str, Any] = {
    "publication-number": "804876-2026",
    "notice-title": {
        "pol": "Polska – Usługi w zakresie konserwacji i wsparcia systemów – Świadczenie usług III linii wsparcia",
        "eng": "Poland – Software maintenance – Third line support",
    },
    "buyer-name": {"pol": ["Centrum Informatyki Resortu Finansów"]},
    "deadline-receipt-tender-date-lot": ["2026-12-04+01:00", "2026-11-27+01:00"],
    "classification-cpv": ["72250000", "72250000", "72267000"],
    "publication-date": "2026-11-20+01:00",
    "contract-nature": ["services"],
    "links": {"html": {"POL": "https://ted.europa.eu/pl/notice/-/detail/804876-2026"}},
}


def test_parse_ted_strips_country_and_cpv_prefix_and_takes_earliest_deadline() -> None:
    notice = sources.parse_ted(TED_ITEM)
    assert notice is not None
    assert notice.title == "Świadczenie usług III linii wsparcia"
    assert notice.buyer_name == "Centrum Informatyki Resortu Finansów"
    assert notice.deadline_date == date(2026, 11, 27)
    assert notice.cpv_codes == ("72250000", "72267000")
    assert notice.order_type == "services"
    assert notice.published_at == datetime(2026, 11, 20, 0, 0, tzinfo=ZONE)
    assert notice.url == "https://ted.europa.eu/pl/notice/-/detail/804876-2026"


def test_parse_ted_without_polish_link_builds_one() -> None:
    notice = sources.parse_ted({**TED_ITEM, "links": {}})
    assert notice is not None
    assert notice.url == "https://ted.europa.eu/pl/notice/-/detail/804876-2026"


def test_ted_query_bounds_both_days() -> None:
    query = sources.ted_query(date(2026, 11, 17), date(2026, 11, 24))
    assert "publication-date>=20261117 AND publication-date<=20261124" in query
    assert "buyer-country=POL" in query


# ── Kursor BZP i strony TED na atrapie HTTP ─────────────────────────────────


def _bzp_item(number: int, published: datetime) -> dict[str, Any]:
    return {
        **BZP_ITEM,
        "bzpNumber": f"2026/BZP {number:08d}",
        "publicationDate": published.strftime("%Y-%m-%dT%H:%M:%S.1234567Z"),
    }


@pytest.mark.asyncio
async def test_fetch_bzp_walks_the_cursor_because_paging_is_ignored(
    monkeypatch,
) -> None:
    """API daje wciąż pierwszą stronę; kolejne porcje biorą się z przesuniętej daty."""

    monkeypatch.setattr(sources, "BZP_PAGE_SIZE", 3)
    start = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    published = [start + timedelta(minutes=i) for i in range(7)]
    items = [_bzp_item(i, moment) for i, moment in enumerate(published)]
    seen_from: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["PageSize"] == "3"
        assert request.url.params["PublicationDateTo"] == "2026-11-24"
        since = request.url.params["PublicationDateFrom"]
        seen_from.append(since)
        moment = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
        page = [
            item
            for item, at in zip(items, published)
            if at.replace(microsecond=0) >= moment
        ]
        return httpx.Response(200, json=page[:3])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await sources.fetch_bzp(client, since=start, until=date(2026, 11, 24))
    assert [n.number for n in batch.notices] == [f"2026/BZP {i:08d}" for i in range(7)]
    assert seen_from[0] == "2026-11-23T07:00:00"
    assert seen_from[1] == "2026-11-23T07:02:00"
    assert (
        batch.cursor is not None
        and batch.cursor.replace(microsecond=0) == published[-1]
    )


@pytest.mark.asyncio
async def test_fetch_bzp_error_is_a_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(sources.SourceError, match="bzp"):
            await sources.fetch_bzp(client, since=NOW, until=TODAY)


@pytest.mark.asyncio
async def test_fetch_ted_reads_all_pages() -> None:
    def item(i: int) -> dict[str, Any]:
        return {**TED_ITEM, "publication-number": f"{800000 + i}-2026"}

    pages = {1: [item(i) for i in range(100)], 2: [item(i) for i in range(100, 130)]}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["limit"] == 100
        return httpx.Response(
            200, json={"notices": pages[body["page"]], "totalNoticeCount": 130}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        notices = await sources.fetch_ted(client, since=date(2026, 11, 17), until=TODAY)
    assert len(notices) == 130


# ── Pętla i stan biegu ──────────────────────────────────────────────────────


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=ZONE)


def _state(status: str, started: datetime) -> dict[str, Any]:
    return {"last_run": {"status": status, "started_at": started.isoformat()}}


def test_loop_runs_on_business_days_after_half_past_five() -> None:
    assert not loop.should_run({}, local=_local(24, 5, 29), attempts=0)
    assert loop.should_run({}, local=_local(24, 5, 30), attempts=0)
    assert not loop.should_run({}, local=_local(22, 9, 0), attempts=0)  # niedziela
    assert not loop.should_run({}, local=_local(24, 9, 0), attempts=3)


def test_loop_runs_once_a_day_and_retries_failure_after_an_hour() -> None:
    ok_today = _state("ok", _local(24, 5, 30))
    assert not loop.should_run(ok_today, local=_local(24, 14, 0), attempts=1)
    ok_yesterday = _state("ok", _local(23, 5, 30))
    assert loop.should_run(ok_yesterday, local=_local(24, 5, 45), attempts=0)
    failed = _state("failed", _local(24, 5, 30))
    assert not loop.should_run(failed, local=_local(24, 6, 15), attempts=1)
    assert loop.should_run(failed, local=_local(24, 6, 31), attempts=1)


def test_running_marker_older_than_an_hour_is_an_interrupted_run() -> None:
    running = _state("running", _local(24, 5, 30))
    assert not loop.should_run(running, local=_local(24, 6, 0), attempts=1)
    view = flow.last_run_view(running, now=_local(24, 7, 0))
    assert view is not None and view["status"] == "failed"
    assert loop.should_run(running, local=_local(24, 7, 0), attempts=1)


def test_external_ref_fits_the_column() -> None:
    assert (
        flow.external_ref("bzp", "2026/BZP 00543285") == "tender:bzp:2026/BZP 00543285"
    )
    assert len(flow.external_ref("ted", "9" * 200)) == 80
