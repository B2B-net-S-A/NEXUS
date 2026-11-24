"""Wymagania klienta na miesiąc faktury: zlecenie B-ZONE i protokół odbioru. Bez bazy.

Dane fikcyjne: numery zleceń w formacie B-ZONE wymyślone (``K/2026/100001/AB/1001/26TEST``),
osoby „Jan Testowy”, „Anna Inna”, umowy „CeZ/99/2026” i „CeZ/98/2026”.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.client_invoicing import period_checks, requirements
from app.services.client_invoicing.period_checks import ProtocolNeed, Span
from app.services.client_settlements import protocol_collective, rules_catalog
from app.services.consultant_portal import identity, mailbox

BZONE = "K/2026/100001/AB/1001/26TEST"
BZONE_NEXT = "K/2026/100002/ŁO/1002/26ALFA"
NOVEMBER = "2026-11"


def _need(period: str = NOVEMBER) -> tuple[date, date]:
    span = period_checks.work_span(period, start=date(2026, 1, 1), end=None)
    assert span is not None
    return span


# ── Numer zlecenia ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        (BZONE, BZONE),
        (BZONE_NEXT, BZONE_NEXT),
        (f"  Zlecenie {BZONE} (IV kw.)", BZONE),
        ("K/2026/100001/", None),  # niepełny numer z odczytu zamówienia
        ("K/2026/100001/AB/1001", None),
        ("ZAM/2026/121", None),
        ("CeZ/99/2026", None),
        (None, None),
    ],
)
def test_bzone_number(text, expected):
    assert period_checks.bzone_number(text) == expected


# ── Pokrycie dni pracy zleceniami ───────────────────────────────────────────


def test_quarterly_order_covers_the_month():
    orders = [(BZONE, Span(date(2026, 10, 1), date(2026, 12, 31)))]
    assert period_checks.uncovered_days(orders, need=_need()) == []


def test_order_ending_before_month_end_leaves_the_rest_uncovered():
    orders = [(BZONE, Span(date(2026, 11, 1), date(2026, 11, 13)))]
    days = period_checks.uncovered_days(orders, need=_need())
    assert days[0] == date(2026, 11, 16)
    assert days[-1] == date(2026, 11, 30)
    assert period_checks.day_ranges(days) == "16.11–30.11.2026"


def test_order_ending_on_last_business_day_covers_the_month():
    # 31.10.2026 to sobota: zlecenie do piątku 30.10 obejmuje październik.
    orders = [(BZONE, Span(date(2026, 10, 1), date(2026, 10, 30)))]
    assert period_checks.uncovered_days(orders, need=_need("2026-10")) == []


def test_two_orders_one_after_another_cover_the_month():
    orders = [
        (BZONE, Span(date(2026, 10, 1), date(2026, 11, 15))),
        (BZONE_NEXT, Span(date(2026, 11, 16), date(2027, 1, 31))),
    ]
    assert period_checks.uncovered_days(orders, need=_need()) == []


def test_no_order_means_every_business_day_is_missing():
    days = period_checks.uncovered_days([], need=_need())
    # Listopad 2026: 21 dni pon–pt minus 11.11 (święto) = 20 dni roboczych.
    assert len(days) == 20
    assert date(2026, 11, 11) not in days
    assert period_checks.day_ranges(days) == "02.11–30.11.2026"


def test_order_without_bzone_number_does_not_count():
    orders = [
        ("ZAM/2026/121", Span(date(2026, 1, 1), None)),
        ("K/2026/100001/", Span(date(2026, 11, 1), date(2026, 11, 30))),
    ]
    assert len(period_checks.uncovered_days(orders, need=_need())) == 20


def test_person_starting_before_the_order():
    # Osoba zaczęła 02.11, bank wystawił zlecenie od 09.11.
    need = period_checks.work_span(NOVEMBER, start=date(2026, 11, 2), end=None)
    orders = [(BZONE, Span(date(2026, 11, 9), date(2026, 12, 31)))]
    days = period_checks.uncovered_days(orders, need=need)
    assert period_checks.day_ranges(days) == "02.11–06.11.2026"


def test_md_line_is_covered_only_while_its_group_order_lasts():
    # Grupa skrócona do 30.11, linia osoby została z końcem 15.12.
    span = period_checks.line_span(
        date(2026, 10, 1), date(2026, 12, 15), date(2026, 10, 1), date(2026, 11, 30)
    )
    assert span == Span(date(2026, 10, 1), date(2026, 11, 30))
    days = period_checks.uncovered_days([(BZONE, span)], need=_need("2026-12"))
    assert days[0] == date(2026, 12, 1)
    # Linia bez własnych dat bierze okres grupy, grupa bez końca — linii.
    assert period_checks.line_span(None, None, date(2026, 1, 1), None) == Span(
        date(2026, 1, 1), None
    )
    assert period_checks.line_span(
        date(2026, 3, 1), date(2026, 6, 30), date(2026, 1, 1), None
    ) == Span(date(2026, 3, 1), date(2026, 6, 30))


def test_work_span_follows_the_contract():
    assert period_checks.work_span(
        NOVEMBER, start=date(2026, 11, 16), end=date(2027, 3, 31)
    ) == (date(2026, 11, 16), date(2026, 11, 30))
    assert period_checks.work_span(
        NOVEMBER,
        start=date(2026, 1, 1),
        end=date(2026, 12, 31),
        terminated=date(2026, 11, 13),
    ) == (date(2026, 11, 1), date(2026, 11, 13))
    assert (
        period_checks.work_span(
            NOVEMBER, start=date(2026, 1, 1), end=date(2026, 10, 31)
        )
        is None
    )
    assert period_checks.work_span(NOVEMBER, start=date(2026, 12, 1), end=None) is None


def test_contract_ending_mid_month_needs_order_only_until_its_end():
    need = period_checks.work_span(
        NOVEMBER, start=date(2026, 1, 1), end=date(2026, 11, 13)
    )
    orders = [(BZONE, Span(date(2026, 11, 1), date(2026, 11, 13)))]
    assert period_checks.uncovered_days(orders, need=need) == []


def test_day_ranges_split_on_covered_days():
    days = [
        date(2026, 11, 2),
        date(2026, 11, 3),
        date(2026, 11, 20),
        date(2026, 11, 23),
    ]
    # 20.11 (pt) i 23.11 (pn) sklejone przez weekend.
    assert period_checks.day_ranges(days) == "02.11–03.11.2026, 20.11–23.11.2026"


def test_bzone_message():
    assert period_checks.bzone_message({}) is None
    message = period_checks.bzone_message(
        {"Jan Testowy": [date(2026, 11, 30)], "pozycja bez osoby": []}
    )
    assert message == (
        "Brak zlecenia B-ZONE na ten okres — poproś KAM o zlecenie: "
        "Jan Testowy (30.11.2026); pozycja bez osoby."
    )


# ── Protokół odbioru od klienta ─────────────────────────────────────────────


def _cez(contract: str, start: str, end: str, people: tuple[str, ...]) -> str:
    rows = "\n".join(
        f"I Analityk {name} ALFA Rozwój 160\n{name} Suma 160" for name in people
    )
    return f"""Protokół odbioru
Nr Umowy Wykonawczej {contract}
Zestawienie czasu pracy i wykonanych zadań
w okresie od {start} do {end}
(Data i podpis osoby uprawnionej) (Data i podpis osoby uprawnionej)
Zestawienie
{rows}
Suma końcowa {160 * len(people)}
Podsumowanie projektu/ów
"""


OCTOBER_99 = protocol_collective.parse_text(
    _cez("CeZ/99/2026", "01.10.2026", "31.10.2026", ("Jan Testowy", "Anna Inna"))
)


def test_protocol_carries_contract_number_from_its_text():
    assert OCTOBER_99 is not None
    assert OCTOBER_99.month == "2026-10"
    assert OCTOBER_99.contract == "CEZ/99/2026"
    split = protocol_collective.parse_text(
        _cez("\nCeZ / 98 / 2026", "01.10.2026", "31.10.2026", ("Jan Testowy",))
    )
    assert split is not None and split.contract == "CEZ/98/2026"


@pytest.mark.parametrize(
    "number, key",
    [
        ("CeZ/99/2026", "CEZ/99/2026"),
        ("CeZ_99_2026", "CEZ/99/2026"),
        ("cez / 099 / 2026", "CEZ/99/2026"),
        ("ZAM/2026/121", None),
        (None, None),
    ],
)
def test_contract_key(number, key):
    assert protocol_collective.contract_key(number) == key


def test_protocol_of_the_month_and_contract_counts():
    need = ProtocolNeed(
        contract_id=1, person="Jan Testowy", contract_number="CeZ/99/2026"
    )
    assert period_checks.protocol_matches(
        OCTOBER_99, need, period="2026-10", doc_month="2026-10"
    )


def test_protocol_of_another_contract_does_not_count():
    # W wątku umowy CeZ/98 przyszedł protokół CeZ/99 (ta sama osoba, ten sam miesiąc).
    need = ProtocolNeed(
        contract_id=1, person="Jan Testowy", contract_number="CeZ/98/2026"
    )
    assert not period_checks.protocol_matches(
        OCTOBER_99, need, period="2026-10", doc_month="2026-10"
    )


def test_protocol_month_comes_from_its_text_not_the_mail():
    # Temat i okres dokumentu mówią „listopad”, treść PDF — październik.
    need = ProtocolNeed(
        contract_id=1, person="Jan Testowy", contract_number="CeZ/99/2026"
    )
    assert not period_checks.protocol_matches(
        OCTOBER_99, need, period="2026-11", doc_month="2026-11"
    )


def test_protocol_without_the_person_does_not_count():
    need = ProtocolNeed(
        contract_id=1, person="Piotr Trzeci", contract_number="CeZ/99/2026"
    )
    assert not period_checks.protocol_matches(
        OCTOBER_99, need, period="2026-10", doc_month="2026-10"
    )
    assert not period_checks.protocol_matches(
        None, need, period="2026-10", doc_month="2026-10"
    )


def test_unknown_contract_of_the_person_accepts_any_contract():
    need = ProtocolNeed(
        contract_id=1, person="Anna Inna", contract_number="ZAM/2026/121"
    )
    assert period_checks.protocol_matches(
        OCTOBER_99, need, period="2026-10", doc_month="2026-10"
    )


def test_protocol_message():
    assert period_checks.protocol_message([]) is None
    assert period_checks.protocol_message(
        ["Jan Testowy", "Anna Inna", "Jan Testowy"]
    ) == (
        "Brak protokołu odbioru od klienta za ten miesiąc — faktura może wymagać "
        "korekty: Anna Inna, Jan Testowy."
    )


# ── Reguły klienta ──────────────────────────────────────────────────────────


def test_rules_are_off_by_default_and_switch_on_per_client():
    assert requirements.from_rules(rules_catalog.effective(None), NOVEMBER) == (
        requirements.Requirements()
    )
    for key in ("cl.bzone_order", "cl.client_protocol"):
        rule = rules_catalog.RULES[key]
        assert rule.level == "off" and rule.switch
    found = requirements.from_rules(
        rules_catalog.effective(
            {
                "cl.bzone_order": {"level": "block", "params": {}},
                "cl.client_protocol": {"level": "block", "params": {}},
            }
        ),
        NOVEMBER,
    )
    assert found.bzone_order and found.client_protocol
    labels = [item["label"] for item in requirements.summary(found, [])]
    assert labels == ["Zlecenie B-ZONE", "Protokół odbioru"]


# ── Nadawca protokołu z wątku (czytnik rozliczeń) ───────────────────────────


class _Mailbox:
    def __init__(self, raw: bytes | None) -> None:
        self.raw = raw
        self.asked = 0

    async def mime(self, message_id: str) -> bytes | None:
        self.asked += 1
        return self.raw


@pytest.fixture
def client_domain(monkeypatch):
    async def fake(db, address):
        return (
            frozenset({7})
            if address.endswith("@klient-testowy.example")
            else frozenset()
        )

    monkeypatch.setattr(identity, "client_ids_for_sender", fake)


def _reply(to: list[str], cc: list[str] = ()) -> dict:
    return {
        "id": "m1",
        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
    }


async def test_reply_to_client_with_cc_takes_client_recipient(client_domain):
    box = _Mailbox(None)
    found = await mailbox._thread_client_address(
        None,
        box,
        _reply(["Ktos.Klienta@klient-testowy.example"], ["rozliczenia@firma.example"]),
        client_id=7,
    )
    assert found == "ktos.klienta@klient-testowy.example"
    assert box.asked == 0  # adresat wystarcza, bez pobierania MIME


async def test_forward_takes_quoted_client_sender(client_domain):
    raw = (
        b"From: pm@firma.example\r\nTo: rozliczenia@firma.example\r\n"
        b"Subject: FW: Protokol\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Przekazuje.\r\n\r\nOd: Anna Klient <anna@klient-testowy.example>\r\n"
        b"Temat: Protokol odbioru\r\n"
    )
    found = await mailbox._thread_client_address(
        None, _Mailbox(raw), _reply(["rozliczenia@firma.example"]), client_id=7
    )
    assert found == "anna@klient-testowy.example"


async def test_internal_mail_without_client_in_thread_gives_nothing(client_domain):
    raw = (
        b"From: pm@firma.example\r\nTo: rozliczenia@firma.example\r\n"
        b"Subject: Protokol\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nW zalaczeniu.\r\n"
    )
    found = await mailbox._thread_client_address(
        None, _Mailbox(raw), _reply(["rozliczenia@firma.example"]), client_id=7
    )
    assert found is None
    # Adres klienta, ale innego klienta niż osoby z protokołu, też się nie liczy.
    assert (
        await mailbox._thread_client_address(
            None, _Mailbox(None), _reply(["x@klient-testowy.example"]), client_id=8
        )
        is None
    )
