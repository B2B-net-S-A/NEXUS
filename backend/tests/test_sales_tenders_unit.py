"""Przetargi z BZP i TED bez bazy: bramka reguł Kingi, parsowanie rejestrów, zmiany
ogłoszeń BZP, kursor BZP, pętla.

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
    "objectId": "notice-object-1",
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
        "notice-object-1"
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


def test_parse_ted_takes_the_main_nature_and_the_procedure() -> None:
    """808107-2026: dostawa z usługą dodatkową — „tylko usługi” ma ją odsiać."""

    item = {
        **TED_ITEM,
        "procedure-identifier": "procedure-ted-1",
        "contract-nature-main-proc": "supplies",
        "contract-nature": ["supplies", "services", "supplies", "services"],
    }
    notice = sources.parse_ted(item)
    assert notice is not None
    assert notice.order_type == "supplies"
    assert notice.procedure_id == "procedure-ted-1"
    decision = rules.evaluate(notice, TenderRules(), today=TODAY, now=NOW)
    assert decision is not None and decision.rule == "order_type"
    without_main = sources.parse_ted({**item, "contract-nature-main-proc": None})
    assert without_main is not None and without_main.order_type == "supplies"


def test_parse_bzp_keeps_the_procedure_id() -> None:
    notice = sources.parse_bzp({**BZP_ITEM, "tenderId": "ocds-148610-6d17e6f7"})
    assert notice is not None and notice.procedure_id == "ocds-148610-6d17e6f7"


def test_parse_ted_without_polish_link_builds_one() -> None:
    notice = sources.parse_ted({**TED_ITEM, "links": {}})
    assert notice is not None
    assert notice.url == "https://ted.europa.eu/pl/notice/-/detail/804876-2026"


def test_bzp_changes_window_starts_where_stale_deadlines_can_be() -> None:
    cursor = NOW - timedelta(hours=20)
    oldest = NOW - timedelta(days=2)
    assert (
        sources.bzp_changes_since(cursor, oldest_row=oldest, now=NOW, initial_days=7)
        == cursor
    )
    assert (
        sources.bzp_changes_since(None, oldest_row=oldest, now=NOW, initial_days=7)
        == oldest
    )
    month_ago = NOW - timedelta(days=30)
    assert sources.bzp_changes_since(
        None, oldest_row=month_ago, now=NOW, initial_days=7
    ) == NOW - timedelta(days=7)
    # Pusta baza: ogłoszenia z tego biegu mają już termin po zmianach.
    assert (
        sources.bzp_changes_since(None, oldest_row=None, now=NOW, initial_days=7) == NOW
    )


def test_ted_query_bounds_both_days() -> None:
    query = sources.ted_query(date(2026, 11, 17), date(2026, 11, 24))
    assert "publication-date>=20261117 AND publication-date<=20261124" in query
    assert "buyer-country=POL" in query


# ── Zmiany ogłoszeń BZP (NoticeUpdateNotice) ────────────────────────────────


def _change_html(*blocks: tuple[str, str, str]) -> str:
    """Układ ogłoszenia o zmianie z BZP (wycięty, bez danych zamawiającego):
    każdy blok to (opis zmienianego pola, „Przed zmianą”, „Po zmianie”)."""

    parts = [
        '<html><head><meta charset="UTF-8"><style>body { font-family: "Calibri"; }'
        "</style></head><body><main>"
        '<h2 class="bg-light p-3 mt-4">SEKCJA III ZMIANA OGŁOSZENIA</h2>'
        '<h3 class="mb-0">3.1.) Nazwa zmienianego ogłoszenia: </h3>Ogłoszenie o zamówieniu'
        '<h3 class="mb-0">3.2.) Numer zmienianego ogłoszenia w BZP: '
        '<span class="normal">2026/BZP 00000001</span></h3>'
    ]
    for label, before, after in blocks:
        parts.append(
            '<h3 class="mb-0">3.4.1.) Opis zmiany, w tym tekst, który należy dodać '
            f"lub zmienić: </h3>                    {label}                <p>"
            f"                    Przed zmianą: <br/>                        {before}"
            "                </p>                <p>                    Po zmianie: <br/>"
            f"                        {after}                </p>"
        )
    parts.append("</main></body></html>")
    return "".join(parts)


OFFERS = "8.1.  Termin składania ofert"
OPENING = ("8.3.  Termin otwarcia ofert", "2026-11-23 19:30", "2026-11-26 19:30")
BINDING = ("8.4.  Termin związania ofertą", "2026-12-22", "2026-12-25")


def test_changed_deadline_reads_the_offers_block_in_warsaw_time() -> None:
    body = _change_html(
        ("6.7.  Zamawiający przewiduje unieważnienie postępowania", "TAK", "NIE"),
        (OFFERS, "2026-11-23 19:00", "2026-11-26 19:00"),
        OPENING,
        BINDING,
    )
    assert sources.changed_deadline(body) == (
        date(2026, 11, 26),
        datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    ("after", "day", "moment"),
    [
        # Po północy w Warszawie, a jeszcze poprzedni dzień w UTC.
        (
            "2026-11-27 00:30",
            date(2026, 11, 27),
            datetime(2026, 11, 26, 23, 30, tzinfo=timezone.utc),
        ),
        # Czas letni: +2 h.
        (
            "2026-06-10 10:00",
            date(2026, 6, 10),
            datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        ),
        ("2026-11-26", date(2026, 11, 26), None),
    ],
)
def test_changed_deadline_day_is_the_company_calendar_day(
    after: str, day: date, moment: datetime | None
) -> None:
    body = _change_html((OFFERS, "2026-11-23 10:00", after))
    assert sources.changed_deadline(body) == (day, moment)


def test_change_without_a_new_offers_deadline_gives_nothing() -> None:
    """Otwarcie i związanie ofertą, warunki z „terminem składania ofert” w treści
    i termin wniosków w konkursie nie są terminem składania ofert."""

    assert sources.changed_deadline(_change_html(OPENING, BINDING)) is None
    conditions = (
        "7.1.  Informacje dotyczące wadium",
        "Wadium należy wnieść przed upływem terminu składania ofert.",
        "Wadium należy wnieść do upływu terminu składania ofert, 2026-11-30 10:00.",
    )
    assert sources.changed_deadline(_change_html(conditions)) is None
    contest = (
        "4.1.  Termin składania wniosków o dopuszczenie do udziału w konkursie",
        "2026-11-23 10:00",
        "2026-11-30 10:00",
    )
    assert sources.changed_deadline(_change_html(contest)) is None
    assert sources.changed_deadline(None) is None
    assert (
        sources.changed_deadline(_change_html((OFFERS, "", "do uzgodnienia"))) is None
    )


def test_empty_new_deadline_does_not_borrow_the_next_block() -> None:
    """Puste „Po zmianie” terminu składania nie bierze daty otwarcia ofert tuż niżej."""

    body = (
        "<p>8.1. Termin składania ofert</p><p>Przed zmianą: 2026-11-23 19:00</p>"
        "<p>Po zmianie:</p><p>8.3. Termin otwarcia ofert</p>"
        "<p>Przed zmianą: 2026-11-23 19:30</p><p>Po zmianie: 2026-11-26 19:30</p>"
    )
    assert sources.changed_deadline(body) is None


def test_change_with_only_a_day_compares_the_day() -> None:
    at = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)
    row = flow.notice_row(
        _notice(deadline_at=at, deadline_date=date(2026, 11, 26)),
        rules.Decision(True, "fraza „body leasing”"),
    )

    def change(day: date, moment: datetime | None) -> sources.BzpChange:
        return sources.BzpChange("2026/BZP 00000003", "p", NOW, day, moment, None)

    assert not flow._moves_deadline(row, change(date(2026, 11, 26), None))
    assert flow._moves_deadline(row, change(date(2026, 11, 27), None))
    assert not flow._moves_deadline(row, change(date(2026, 11, 26), at))
    later = at + timedelta(hours=2)
    assert flow._moves_deadline(row, change(date(2026, 11, 26), later))


BZP_CHANGE_ITEM: dict[str, Any] = {
    "noticeType": "NoticeUpdateNotice",
    "bzpNumber": "2026/BZP 00000002",
    "noticeNumber": "2026/BZP 00000002/01",
    "publicationDate": "2026-11-23T04:24:27.1905182Z",
    "submittingOffersDate": None,
    "cpvCode": "",
    "orderType": None,
    "tenderId": "ocds-148610-procedure-1",
    "objectId": "change-object-1",
    "htmlBody": _change_html((OFFERS, "2026-11-23 19:00", "2026-11-26 19:00")),
}


def test_parse_bzp_change_keeps_its_number_procedure_and_link() -> None:
    change = sources.parse_bzp_change(BZP_CHANGE_ITEM)
    assert change == sources.BzpChange(
        number="2026/BZP 00000002",
        procedure_id="ocds-148610-procedure-1",
        published_at=datetime(2026, 11, 23, 4, 24, 27, 190518, tzinfo=timezone.utc),
        deadline_date=date(2026, 11, 26),
        deadline_at=datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc),
        url=(
            "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/"
            "change-object-1"
        ),
    )


def test_parse_bzp_change_skips_changes_it_cannot_follow() -> None:
    assert sources.parse_bzp_change({**BZP_CHANGE_ITEM, "tenderId": ""}) is None
    assert sources.parse_bzp_change({**BZP_CHANGE_ITEM, "bzpNumber": None}) is None
    assert sources.parse_bzp_change({**BZP_CHANGE_ITEM, "publicationDate": "x"}) is None
    no_deadline = {**BZP_CHANGE_ITEM, "htmlBody": _change_html(OPENING)}
    assert sources.parse_bzp_change(no_deadline) is None


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
        assert request.url.params["NoticeType"] == "ContractNotice"
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
async def test_fetch_bzp_changes_walks_past_pages_of_changes_without_a_deadline(
    monkeypatch,
) -> None:
    """Pierwsza pełna porcja to same zmiany bez terminu; kursor i tak idzie dalej."""

    monkeypatch.setattr(sources, "BZP_PAGE_SIZE", 3)
    start = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    published = [start + timedelta(minutes=i) for i in range(5)]
    items = [
        {
            **BZP_CHANGE_ITEM,
            "bzpNumber": f"2026/BZP {i:08d}",
            "tenderId": f"ocds-148610-{i}",
            "publicationDate": moment.strftime("%Y-%m-%dT%H:%M:%S.1234567Z"),
            "htmlBody": _change_html(OPENING)
            if i < 3
            else _change_html((OFFERS, "2026-11-23 19:00", f"2026-11-2{i} 12:00")),
        }
        for i, moment in enumerate(published)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["NoticeType"] == "NoticeUpdateNotice"
        moment = datetime.fromisoformat(
            request.url.params["PublicationDateFrom"]
        ).replace(tzinfo=timezone.utc)
        page = [
            item
            for item, at in zip(items, published)
            if at.replace(microsecond=0) >= moment
        ]
        return httpx.Response(200, json=page[:3])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await sources.fetch_bzp_changes(
            client, since=start, until=date(2026, 11, 24)
        )
    assert [change.procedure_id for change in batch.changes] == [
        "ocds-148610-3",
        "ocds-148610-4",
    ]
    assert [change.deadline_date for change in batch.changes] == [
        date(2026, 11, 23),
        date(2026, 11, 24),
    ]
    assert batch.requests == 3
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


def test_row_notice_gives_the_gate_its_cpv_codes_back() -> None:
    """Bramka po zmianie terminu ma przepuścić ogłoszenie, które weszło samym CPV."""

    row = flow.notice_row(
        _notice(
            title="Utrzymanie systemu ewidencji",
            cpv_codes=("72267000",),
            cpv_label="72267000-4 (Usługi w zakresie konserwacji oprogramowania)",
        ),
        rules.Decision(False, "CPV 72267000", "expired"),
    )
    notice = flow.row_notice(row)
    assert notice.cpv_codes == ("72267000",)
    decision = rules.evaluate(notice, TenderRules(), today=TODAY, now=NOW)
    assert decision is not None and decision.passed


def test_change_note_deadline_has_the_hour_when_bzp_gave_one() -> None:
    at = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)
    assert flow._deadline_text(date(2026, 11, 26), at) == "26.11.2026, 19:00"
    assert flow._deadline_text(date(2026, 11, 26)) == "26.11.2026"
    assert flow._deadline_text(None) == "brak"


def test_external_ref_fits_the_column() -> None:
    assert (
        flow.external_ref("bzp", "2026/BZP 00543285") == "tender:bzp:2026/BZP 00543285"
    )
    assert len(flow.external_ref("ted", "9" * 200)) == 80
