"""Faktury do klientów (E8) — czyste reguły: dopasowanie faktury, wpłaty, część miesiąca.

Bez bazy. Numery zamówień, faktur i KSeF fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoiceLink,
    ClientSalesInvoicePayment,
)
from app.services.client_invoicing import billing, clients, fa_sales, requirements
from app.services.client_invoicing.billing import (
    COST_NOTE,
    BillingLine,
    BillingRow,
    CostBudget,
    OrderRef,
    period_fraction,
)
from app.services.client_invoicing.ledger import Chain, ChainCheck, check
from app.services.client_invoicing.line_gaps import GAP_REASONS
from app.services.client_invoicing.matching import (
    REASON_LABELS,
    RETRY_REASONS,
    Target,
    auto_match,
    decide,
    numbers_found,
)
from app.services.client_invoicing.views import chain_payload, row_status
from app.services.client_invoicing.payments import (
    OpenInvoice,
    decide_credit,
    mpp_vat,
)
from app.services.client_settlements import rules_catalog
from app.services.hr.bank.parsed import StatementLine

KSEF_A = "9876543210-20261103-A1180C0FFEE1-5C"


def _line(order_id, net, consultant="Jan Przykładowy"):
    return BillingLine(
        order_id=order_id,
        consultant=consultant,
        basis="md",
        quantity=Decimal("1"),
        unit_price=Decimal("1"),
        net=None if net is None else Decimal(net),
        currency="PLN",
    )


def _group(group_id, number, *lines):
    return BillingRow(
        client_id=1,
        kind="md",
        group_id=group_id,
        order_id=None,
        order_number=number,
        currency="PLN",
        lines=tuple(lines),
    )


def _periodic(order_id, number, net, currency="PLN"):
    return BillingRow(
        client_id=1,
        kind="periodic",
        group_id=None,
        order_id=order_id,
        order_number=number,
        currency=currency,
        lines=(_line(order_id, net),),
    )


def _cost(group_id, number, available, members=(31,)):
    return BillingRow(
        client_id=1,
        kind="cost",
        group_id=group_id,
        order_id=None,
        order_number=number,
        currency="PLN",
        lines=(
            BillingLine(
                order_id=None,
                consultant="Marta Kosztowa",
                basis="cost",
                quantity=None,
                unit_price=None,
                net=None,
                currency="PLN",
                note=COST_NOTE,
            ),
        ),
        budget=CostBudget(amount=Decimal("500000.00"), available=Decimal(available)),
        member_ids=frozenset(members),
    )


def _refs(*rows):
    return [OrderRef(1, row.group_id, row.order_id, row.order_number) for row in rows]


# ── Numer zamówienia w treści faktury ─────────────────────────────────────────


def test_order_number_is_found_as_a_whole_word_only():
    refs = [OrderRef(1, 10, None, "445"), OrderRef(1, 11, None, "ZAM/2026/12")]
    assert numbers_found(["Usługi wg zamówienia 4450"], refs) == set()
    assert numbers_found(["zam. 445, październik"], refs) == {"g10"}
    # „ZAM/2026/12” nie siedzi w „ZAM/2026/121”.
    assert numbers_found(["ZAM/2026/121"], refs) == set()
    assert numbers_found(["zam/2026/12 — usługi"], refs) == {"g11"}


def test_digits_only_number_matches_without_leading_zeros_and_sap_prefix():
    refs = [
        OrderRef(1, 10, None, "0012345678"),
        OrderRef(1, 11, None, "SAP 4500000123"),
    ]
    assert numbers_found(["PO 12345678"], refs) == {"g10"}
    assert numbers_found(["Zamówienie 4500000123"], refs) == {"g11"}


def test_short_or_digitless_titles_do_not_bind():
    refs = [OrderRef(1, None, 5, "PO"), OrderRef(1, None, 6, "12")]
    assert numbers_found(["PO 12 do zamówienia"], refs) == set()


def test_title_zamowienie_nr_is_found_by_the_number_alone():
    # Numer zamówienia bez grupy to jego tytuł, a faktura podaje sam numer.
    refs = [
        OrderRef(1, None, 5, "Zamówienie nr 9001/2026"),
        OrderRef(1, 12, None, "ZAMÓWIENIE 9002_2026"),
    ]
    assert numbers_found(["Jan Przykładowy, nr zamówienia: 9001/2026"], refs) == {"o5"}
    assert numbers_found(["zamówienie: 9002_2026_onboarding"], refs) == {"g12"}
    assert numbers_found(["nr zamówienia: 19001/2026"], refs) == set()


@pytest.mark.parametrize(
    "title",
    [
        "Zamówienie Przykładowa Spółka — Jan Przykładowy",
        "Zamówienie nr 9001/2026 — Jan Przykładowy",
        "Zamówienie z dnia 01.07.2026",
        "Zamówienie 5",
    ],
)
def test_descriptive_title_gives_no_bare_number(title):
    # Jak `number_from_title` w rozliczeniach: numerem jest jeden wyraz z cyfrą.
    assert OrderRef(1, None, 5, title).variants() == (title,)


@pytest.mark.parametrize(
    ("ref", "invoice_text"),
    [
        # Numer grupy z dopiskiem po myślniku (audyt 25.11.2026, Wedel).
        (OrderRef(1, 10, None, "4500000777- Wsparcie on-site"), "zamówienie: 4500000777"),
        # Znak kancelaryjny przed numerem — w grupie i w tytule (KIR).
        (OrderRef(1, None, 5, "LDZ.dz.ABC/DAZ/BK/00001/6/2026/ZAM"), "Zamówienie:ABC/DAZ/BK/00001/6/2026/ZAM"),
        (OrderRef(1, None, 6, "L.dz. ABC/DAZ/MD/00002/6/2026/ZAM"), "nr ABC/DAZ/MD/00002/6/2026/ZAM"),
        # Dwa numery sklejone ukośnikiem w jednym polu grupy (Alior).
        (OrderRef(1, 11, None, "OIT/0001/2025/IT/OIT/0002/2026/IT"), "Zamówienie nr OIT/0001/2025/IT"),
        (OrderRef(1, 11, None, "OIT/0001/2025/IT/OIT/0002/2026/IT"), "Zamówienie nr OIT/0002/2026/IT"),
    ],
)
def test_decorated_order_number_is_found_by_the_number_alone(ref, invoice_text):
    assert numbers_found([invoice_text], [ref]) == {ref.key}


@pytest.mark.parametrize(
    "ref",
    [
        # Opis w tytule samodzielnego zamówienia dalej nie daje numeru.
        OrderRef(1, None, 5, "4500000777- Wsparcie on-site"),
        # Krótki początek przed myślnikiem związałby fakturę po dacie.
        OrderRef(1, 10, None, "2026 - opis zamówienia"),
        # Łącznik bez spacji należy do numeru.
        OrderRef(1, 10, None, "1234567-9"),
    ],
)
def test_number_with_dash_stays_whole_outside_group_or_when_short(ref):
    assert ref.variants() == (ref.number,)


# ── Dopasowanie ───────────────────────────────────────────────────────────────


def test_number_binds_even_with_a_different_amount():
    row = _group(10, "ZAM/2026/124", _line(1, "22425.00"))
    decision = decide(
        net=Decimal("22500.00"),
        currency="PLN",
        texts=["ZAM/2026/124"],
        rows=[row],
        refs=_refs(row),
    )
    assert decision.targets == (Target(group_id=10),)
    assert decision.method == "order_number"


def test_order_titled_zamowienie_nr_binds_by_the_number_on_the_invoice():
    # Pomiar 24.11: takie faktury czekały jako numer, którego nie ma w NEXUSIE.
    row = _periodic(5, "Zamówienie nr 9001/2026", "16800.00")
    decision = decide(
        net=Decimal("18400.00"),
        currency="PLN",
        texts=["Konsultant Jan Przykładowy, nr zamówienia: 9001/2026, SSGW 100001-1"],
        rows=[row],
        refs=_refs(row),
    )
    assert decision.targets == (Target(order_id=5),)
    assert decision.method == "order_number"


def test_same_number_with_and_without_the_title_prefix_is_one_number():
    # Wcześniej faktura na dwie osoby wiązała tylko zamówienie z tytułem bez przedrostka.
    bare = _periodic(5, "9001/2026", "16800.00")
    titled = _periodic(6, "Zamówienie nr 9001/2026", "16800.00")

    def invoice(net):
        return decide(
            net=Decimal(net),
            currency="PLN",
            texts=["nr zamówienia: 9001/2026", "nr zamówienia: 9001/2026"],
            rows=[bare, titled],
            refs=_refs(bare, titled),
        )

    assert invoice("33600.00").targets == (Target(order_id=5), Target(order_id=6))
    assert invoice("35000.00").reason == "several_orders"


def test_number_and_one_person_amount_links_to_that_person():
    row = _group(
        10, "445", _line(1, "10000.00"), _line(2, "12000.00", "Ewa Przykładowa")
    )
    decision = decide(
        net=Decimal("12000.00"),
        currency="PLN",
        texts=["zam 445"],
        rows=[row],
        refs=_refs(row),
    )
    assert decision.targets == (Target(order_id=2),)


def _one_number_on_two_groups(first_lines, second_lines):
    """Ten sam numer zamówienia na dwóch grupach klienta (dwa trafione wiersze)."""

    a = _group(10, "445", *first_lines)
    b = _group(11, "445", *second_lines)
    return [a, b]


def test_number_on_two_groups_and_one_person_amount_links_to_that_person():
    rows = _one_number_on_two_groups(
        [_line(1, "10000.00"), _line(2, "12000.00", "Ewa Przykładowa")],
        [_line(3, "7000.00", "Adam Przykładowy")],
    )
    decision = decide(
        net=Decimal("12000.00"),
        currency="PLN",
        texts=["zam 445"],
        rows=rows,
        refs=_refs(*rows),
    )
    assert decision.targets == (Target(order_id=2),)
    assert decision.method == "order_number"


def test_number_on_two_groups_and_two_people_with_that_amount_waits():
    rows = _one_number_on_two_groups(
        [_line(1, "12000.00"), _line(2, "9000.00", "Ewa Przykładowa")],
        [_line(3, "12000.00", "Adam Przykładowy"), _line(4, "5000.00", "Ola Testowa")],
    )
    decision = decide(
        net=Decimal("12000.00"),
        currency="PLN",
        texts=["zam 445"],
        rows=rows,
        refs=_refs(*rows),
    )
    assert not decision.matched
    assert decision.reason == "several_orders"


def test_number_on_two_groups_prefers_a_whole_row_over_a_person():
    rows = _one_number_on_two_groups(
        [_line(1, "12000.00"), _line(2, "9000.00", "Ewa Przykładowa")],
        [_line(3, "7000.00", "Adam Przykładowy"), _line(4, "5000.00", "Ola Testowa")],
    )
    decision = decide(
        net=Decimal("12000.00"),
        currency="PLN",
        texts=["zam 445"],
        rows=rows,
        refs=_refs(*rows),
    )
    assert decision.targets == (Target(group_id=11),)


def test_two_equal_whole_rows_are_not_resolved_by_a_person():
    group = _group(10, "445", _line(1, "12000.00"))
    periodic = _periodic(20, "445", "12000.00")
    decision = decide(
        net=Decimal("12000.00"),
        currency="PLN",
        texts=["zam 445"],
        rows=[group, periodic],
        refs=_refs(group, periodic),
    )
    assert not decision.matched
    assert decision.reason == "several_orders"


def test_number_on_two_rows_ignores_a_person_amount_outside_a_group():
    pool = BillingRow(
        client_id=1,
        kind="md",
        group_id=10,
        order_id=None,
        order_number="445",
        currency="PLN",
        lines=(
            BillingLine(
                order_id=None,
                consultant="2 os.",
                basis="md",
                quantity=Decimal("1"),
                unit_price=Decimal("1"),
                net=Decimal("12000.00"),
                currency="PLN",
            ),
            _line(1, "5000.00"),
        ),
    )
    other = _group(11, "445", _line(3, "7000.00", "Adam Przykładowy"))
    decision = decide(
        net=Decimal("12000.00"),
        currency="PLN",
        texts=["zam 445"],
        rows=[pool, other],
        refs=_refs(pool, other),
    )
    assert not decision.matched
    assert decision.reason == "several_orders"


def test_several_orders_gets_another_attempt():
    assert "several_orders" in RETRY_REASONS


# ── Osoby z pozycji: numer na kilku zamówieniach, a kwota nie wskazuje ─────────


def _own_order(order_id, consultant, number="Zamówienie nr 9001/2026"):
    """Zamówienie okresowe jednej osoby: NEXUS liczy 168 h, klient fakturuje MD."""

    return BillingRow(
        client_id=1,
        kind="periodic",
        group_id=None,
        order_id=order_id,
        order_number=number,
        currency="PLN",
        lines=(
            BillingLine(
                order_id=order_id,
                consultant=consultant,
                basis="hours",
                quantity=Decimal("168"),
                unit_price=Decimal("100"),
                net=Decimal("16800.00"),
                currency="PLN",
            ),
        ),
    )


def _md_item(name, md, price="800", number="9001/2026", **extra):
    return {
        "name": f"Usługi programistyczne – {name}, nr zamówienia: {number}",
        "quantity": md,
        "unit": "MD",
        "unit_price": price,
        "net": str(Decimal(md) * Decimal(price)),
        **extra,
    }


def _invoice_for(rows, *items):
    return decide(
        net=sum((Decimal(item["net"]) for item in items), Decimal("0")),
        currency="PLN",
        texts=[item["name"] for item in items if not item.get("before_correction")],
        rows=rows,
        refs=_refs(*rows),
        items=list(items),
    )


def test_number_on_several_orders_binds_the_people_named_in_the_items():
    # Pomiar 25.11: klient wystawia na numer jedną fakturę z pozycją na osobę,
    # w rzeczywistych MD, więc ani suma, ani żaden wiersz nie jest równy netto.
    rows = [
        _own_order(50, "Jan Przykładowy"),
        _own_order(51, "Ewa Testowa"),
        _own_order(52, "Adam Próbny"),
        _own_order(53, "Ola Wzorcowa", number="9001/2026"),
    ]
    decision = _invoice_for(
        rows,
        _md_item("Ewa Testowa", "23"),
        _md_item("Jan Przykładowy", "19"),
        _md_item("Adam Próbny", "23", price="1000"),
        _md_item("Ola Wzorcowa", "21"),
    )
    assert decision.targets == tuple(Target(order_id=i) for i in (50, 51, 52, 53))
    assert decision.method == "order_number"


@pytest.mark.parametrize("md", ["17", "21"])
def test_number_on_several_orders_and_one_person_binds_that_persons_order(md):
    # Ten sam klient wystawia też osobną fakturę na osobę. Przy 21 MD kwota jest
    # równa obu wierszom (ta sama stawka), przy 17 MD żadnemu.
    rows = [_own_order(50, "Jan Przykładowy"), _own_order(51, "Ewa Testowa")]
    decision = _invoice_for(rows, _md_item("Ewa Testowa", md))
    assert decision.targets == (Target(order_id=51),)
    assert decision.method == "order_number"


def test_two_items_of_one_person_bind_that_persons_order_once():
    # Druga pozycja tej osoby podaje numer, którego NEXUS nie zna: wiąże znany numer.
    rows = [_own_order(50, "Jan Przykładowy"), _own_order(51, "Ewa Testowa")]
    decision = _invoice_for(
        rows,
        _md_item("Ewa Testowa", "7.5", number="9077/2026"),
        _md_item("Ewa Testowa", "7.5"),
    )
    assert decision.targets == (Target(order_id=51),)


def test_people_named_on_group_lines_bind_their_lines():
    rows = _one_number_on_two_groups(
        [_line(1, "10000.00"), _line(2, "12000.00", "Ewa Przykładowa")],
        [_line(3, "7000.00", "Adam Przykładowy")],
    )
    decision = decide(
        net=Decimal("24000.00"),
        currency="PLN",
        texts=["zam 445"],
        rows=rows,
        refs=_refs(*rows),
        items=[
            {"name": "Ewa Przykładowa, zam 445", "unit_price": "800"},
            {"name": "Adam Przykładowy, zam 445", "unit_price": "800"},
        ],
    )
    assert decision.targets == (Target(order_id=2), Target(order_id=3))
    assert decision.method == "order_number"


_TWO_PEOPLE = (("Jan Przykładowy", 50), ("Ewa Testowa", 51))


@pytest.mark.parametrize(
    ("people", "items"),
    [
        # Pozycja bez osoby (koszty, rabat): nie wiadomo, do którego zamówienia należy.
        (
            _TWO_PEOPLE,
            [
                _md_item("Jan Przykładowy", "20"),
                {
                    "name": "Koszty dojazdu, nr zamówienia: 9001/2026",
                    "quantity": "1",
                    "unit_price": "500",
                    "net": "500",
                },
            ],
        ),
        # Osoba spoza zamówień z tym numerem.
        (_TWO_PEOPLE, [_md_item("Adam Próbny", "20")]),
        # Jedna pozycja na dwie osoby.
        (_TWO_PEOPLE, [_md_item("Jan Przykładowy, Ewa Testowa", "20")]),
        # Ta sama osoba na dwóch zamówieniach z tym numerem.
        (
            (("Jan Przykładowy", 50), ("Jan Przykładowy", 51), ("Ewa Testowa", 52)),
            [_md_item("Jan Przykładowy", "20")],
        ),
        # Samo nazwisko nie wskazuje osoby.
        (_TWO_PEOPLE, [_md_item("Przykładowy", "20")]),
        # Pozycja sprzed korekty nie wskazuje osoby.
        (_TWO_PEOPLE, [_md_item("Ewa Testowa", "20", before_correction=True)]),
    ],
)
def test_people_in_items_refuse_when_not_certain(people, items):
    rows = [_own_order(order_id, name) for name, order_id in people]
    rows.append(_own_order(60, "Adam Próbny", number="9002/2026"))
    decision = decide(
        net=sum((Decimal(item["net"]) for item in items), Decimal("0")),
        currency="PLN",
        texts=["nr zamówienia: 9001/2026"],
        rows=rows,
        refs=_refs(*rows),
        items=items,
    )
    assert not decision.matched
    assert decision.reason == "several_orders"


# ── Faktura zbiorcza (cl.collective_invoice): numer wiąże całe zamówienie ──────

COLLECTIVE = (
    "Prace programistyczne za miesiąc wrzesień w ramach zamówienia nr 3/09/2026/XY"
)


def _people_orders(*nets, number="3/09/2026/XY", first_id=20):
    """Zamówienie klienta na kilka osób, a w NEXUSIE osobne zamówienie okresowe każdej."""

    return [
        BillingRow(
            client_id=1,
            kind="periodic",
            group_id=None,
            order_id=first_id + index,
            order_number=number,
            currency="PLN",
            lines=(_line(first_id + index, net, f"Osoba{index} Przykładowa"),),
        )
        for index, net in enumerate(nets)
    ]


def _collective(net, rows, *, collective, item=COLLECTIVE):
    return decide(
        net=Decimal(net),
        currency="PLN",
        texts=[item],
        rows=rows,
        refs=_refs(*rows),
        items=[{"name": item, "quantity": "1", "unit_price": net}],
        collective=collective,
    )


def test_collective_rule_binds_every_order_with_the_number_whatever_the_amount():
    rows = _people_orders(*["16800.00"] * 8)
    # Faktura na 7 osób z 8 też idzie na całe zamówienie: brak osoby wygląda jak
    # urlopy, różnicę widzą Finanse.
    decision = _collective("117600.00", rows, collective=True)
    assert decision.targets == tuple(Target(order_id=row.order_id) for row in rows)
    assert decision.method == "order_number"


def test_collective_rule_reaches_orders_titled_zamowienie_nr():
    rows = _people_orders("18900.00", "33600.00") + _people_orders(
        "17640.00", number="Zamówienie nr 3/09/2026/XY", first_id=30
    )
    decision = _collective("68000.00", rows, collective=True)
    assert {t.order_id for t in decision.targets} == {20, 21, 30}


def test_collective_rule_keeps_other_numbers_apart():
    rows = _people_orders("18900.00", "33600.00") + _people_orders(
        "17640.00", number="4/09/2026/XY", first_id=30
    )
    decision = _collective("52000.00", rows, collective=True)
    assert {t.order_id for t in decision.targets} == {20, 21}


def test_without_the_rule_one_number_on_several_orders_waits():
    # Przegląd 24.11: bez reguły kwota nie odróżni faktury zbiorczej od faktury
    # jednej osoby ani od faktury bez jednej osoby, więc faktura czeka na Finanse.
    eight = _people_orders(*["16800.00"] * 8)
    assert _collective("117600.00", eight, collective=False).reason == "several_orders"
    # Tytuł „Zamówienie nr …” to ten sam numer: faktura bez jednej osoby czeka, a nie
    # wiąże siedmiu zamówień z tytułem bez przedrostka. Suma wszystkich ośmiu co do
    # grosza wiąże wszystkie, jak przy jednakowych tytułach.
    seven_and_typo = _people_orders(*["16800.00"] * 7) + _people_orders(
        "16800.00", number="Zamówienie nr 3/09/2026/XY", first_id=40
    )
    assert (
        _collective("117600.00", seven_and_typo, collective=False).reason
        == "several_orders"
    )
    assert _collective("134400.00", seven_and_typo, collective=False).targets == tuple(
        Target(order_id=row.order_id) for row in seven_and_typo
    )
    one_and_a_bit = _people_orders("16800.00", "1460.87")
    assert (
        _collective("18200.00", one_and_a_bit, collective=False).reason
        == "several_orders"
    )


def test_collective_rule_comes_from_client_rules():
    off = requirements.from_rules(rules_catalog.effective({}), "2026-09")
    on = requirements.from_rules(
        rules_catalog.effective(
            {"cl.collective_invoice": {"level": "block", "params": {}}}
        ),
        "2026-09",
    )
    assert (off.collective_invoice, on.collective_invoice) == (False, True)


def test_two_different_numbers_close_to_the_sum_still_wait():
    a = _periodic(20, "ZAM/1", "100.00")
    b = _periodic(21, "ZAM/2", "50.00")
    decision = decide(
        net=Decimal("140.00"),
        currency="PLN",
        texts=["ZAM/1, ZAM/2"],
        rows=[a, b],
        refs=_refs(a, b),
    )
    assert decision.reason == "several_orders"


def test_number_outside_the_month_is_not_guessed():
    row = _group(10, "ZAM/1", _line(1, "100.00"))
    refs = _refs(row) + [OrderRef(1, 99, None, "ZAM/2025/9")]
    decision = decide(
        net=Decimal("100.00"),
        currency="PLN",
        texts=["ZAM/2025/9"],
        rows=[row],
        refs=refs,
    )
    assert not decision.matched
    assert decision.reason == "order_outside_period"


def test_several_numbers_bind_when_the_sum_matches():
    a = _group(10, "ZAM/1", _line(1, "100.00"))
    b = _periodic(20, "ZAM/2", "50.00")
    decision = decide(
        net=Decimal("150.00"),
        currency="PLN",
        texts=["ZAM/1, ZAM/2"],
        rows=[a, b],
        refs=_refs(a, b),
    )
    assert set(decision.targets) == {Target(group_id=10), Target(order_id=20)}
    unclear = decide(
        net=Decimal("120.00"),
        currency="PLN",
        texts=["ZAM/1, ZAM/2"],
        rows=[a, b],
        refs=_refs(a, b),
    )
    assert unclear.reason == "several_orders"


def test_amount_without_number_must_be_unique():
    a = _periodic(20, "ZAM/2", "31920.00")
    b = _periodic(21, "ZAM/3", "24000.00")
    found = decide(
        net=Decimal("24000.00"), currency="PLN", texts=[], rows=[a, b], refs=[]
    )
    assert found.targets == (Target(order_id=21),) and found.method == "amount"

    twins = [_periodic(20, "ZAM/2", "24000.00"), _periodic(21, "ZAM/3", "24000.00")]
    ambiguous = decide(
        net=Decimal("24000.00"), currency="PLN", texts=[], rows=twins, refs=[]
    )
    assert not ambiguous.matched and ambiguous.reason == "amount_ambiguous"


def _nordea_item(contractor, contact="Anna Klientowa"):
    return (
        f"NIDS: 2026-000001, IT Retail Banking, Nordea Contact: {contact}, "
        f"Contractor {contractor} ID: M000001"
    )


def _person_row(order_id, net, consultant):
    return BillingRow(
        client_id=1,
        kind="periodic",
        group_id=None,
        order_id=order_id,
        order_number=f"ZAM/{order_id}",
        currency="PLN",
        lines=(_line(order_id, net, consultant),),
    )


def _decide_named(net, rows, item):
    return decide(
        net=Decimal(net),
        currency="PLN",
        texts=[item],
        rows=rows,
        refs=[],
        items=[{"name": item, "unit_price": "150.00"}],
    )


def test_amount_does_not_bind_an_invoice_that_names_another_person():
    # Audyt luk 25.11.2026: u Nordei wiele osób ma tę samą stawkę i godziny, więc
    # kwota pasowała do zamówienia innej osoby niż ta z pozycji „Contractor …”.
    rows = [
        _person_row(20, "25200.00", "Jan Przykładowy"),
        _person_row(21, "26880.00", "Ewa Testowa"),
    ]
    decision = _decide_named("25200.00", rows, _nordea_item("Ewa Testowa"))
    assert not decision.matched
    assert decision.reason == "amount_other_person"


def test_amount_binds_when_the_named_person_is_on_the_order():
    rows = [_person_row(20, "25200.00", "Jan Nowak-Kowalski")]
    # Skrócone podwójne nazwisko to ta sama osoba (``same_person``).
    decision = _decide_named("25200.00", rows, _nordea_item("Jan Nowak"))
    assert decision.method == "amount"
    assert decision.targets == (Target(order_id=20),)


def test_named_person_picks_one_of_orders_with_the_same_amount():
    rows = [
        _person_row(20, "25200.00", "Jan Przykładowy"),
        _person_row(21, "25200.00", "Ewa Testowa"),
    ]
    decision = _decide_named("25200.00", rows, _nordea_item("Ewa Testowa"))
    assert decision.method == "amount"
    assert decision.targets == (Target(order_id=21),)


def test_client_contact_is_not_the_person_of_the_invoice():
    rows = [_person_row(20, "25200.00", "Jan Przykładowy")]
    item = _nordea_item("Ewa Testowa", contact="Jan Przykładowy")
    assert _decide_named("25200.00", rows, item).reason == "amount_other_person"


def test_md_person_amount_does_not_bind_another_named_person():
    rows = [_hourly_row((10, "Jan Przykładowy", "150"), (11, "Ewa Testowa", "160"))]
    # Kwota równa pozycji Jana, a faktura jest na Ewę w rzeczywistych godzinach:
    # wiąże osoba z ceną jednostkową, nie kwota.
    decision = decide(
        net=Decimal("25200.00"),
        currency="PLN",
        texts=[_nordea_item("Ewa Testowa")],
        rows=rows,
        refs=[],
        items=[{"name": _nordea_item("Ewa Testowa"), "unit_price": "160.00"}],
    )
    assert decision.method == "person"
    assert decision.targets == (Target(order_id=11),)


def test_other_person_reason_is_retried_and_alerts_the_delivery_lead():
    assert "amount_other_person" in RETRY_REASONS
    assert "amount_other_person" in REASON_LABELS
    assert "amount_other_person" in GAP_REASONS


def test_amount_that_matches_nothing_waits_for_finance():
    rows = [_periodic(20, "ZAM/2", "31920.00")]
    decision = decide(
        net=Decimal("31000.00"), currency="PLN", texts=[], rows=rows, refs=[]
    )
    assert decision.reason == "amount_differs"
    unknown = decide(
        net=Decimal("31000.00"),
        currency="PLN",
        texts=[],
        rows=[_group(10, "ZAM/1", _line(1, None))],
        refs=[],
    )
    assert unknown.reason == "expected_unknown"


def test_cost_order_binds_only_by_number_and_never_waits_for_md_usage():
    cost = _cost(30, "SAP 4500000001", "380000.00")
    bound = decide(
        net=Decimal("12345.67"),
        currency="PLN",
        texts=["Zamówienie SAP 4500000001"],
        rows=[cost],
        refs=_refs(cost),
    )
    assert bound.targets == (Target(group_id=30),)
    # Bez numeru kosztowego nie wiąże kwota, a powód nie mówi o zużyciu MD.
    loose = decide(
        net=Decimal("12345.67"),
        currency="PLN",
        texts=[],
        rows=[cost, _periodic(20, "ZAM/2", "31920.00")],
        refs=[],
    )
    assert not loose.matched and loose.reason == "amount_differs"


def test_currency_must_match_and_empty_month_is_reported():
    rows = [_periodic(20, "ZAM/2", "1000.00", currency="EUR")]
    assert (
        decide(
            net=Decimal("1000.00"), currency="PLN", texts=[], rows=rows, refs=[]
        ).reason
        == "currency_differs"
    )
    assert (
        decide(
            net=Decimal("1000.00"), currency="PLN", texts=[], rows=[], refs=[]
        ).reason
        == "no_orders"
    )


# ── Faktura a budżet zamówienia kosztowego ───────────────────────────────────


def _chain(net, *links, accepted=None):
    head = ClientSalesInvoice(
        id=1,
        net_amount=Decimal(net),
        gross_amount=Decimal(net),
        match_status="matched",
        difference_accepted_amount=None if accepted is None else Decimal(accepted),
    )
    return Chain(
        head=head,
        links=[
            ClientSalesInvoiceLink(
                order_group_id=group_id,
                order_id=order_id,
                period_year=2026,
                period_month=10,
            )
            for group_id, order_id in links
        ],
    )


def _rows(*rows):
    return {row.key: row for row in rows}


def test_cost_invoice_is_compared_with_the_remaining_budget():
    rows = _rows(
        _cost(30, "SAP 1", "380000.00"), _group(10, "ZAM/1", _line(1, "1000.00"))
    )
    within = check(_chain("380000.00", (30, None)), rows)
    assert (within.status, within.basis) == ("ok", "budget")
    over = check(_chain("380000.01", (30, None)), rows)
    assert (over.status, over.difference) == ("difference", Decimal("0.01"))
    # Powiązanie z osobą z zamówienia kosztowego też idzie do budżetu zamówienia.
    assert check(_chain("1000.00", (None, 31)), rows).status == "ok"
    # Faktura na MD i kosztowe razem: najpierw MD wg stawek, reszta z budżetu.
    assert check(_chain("381000.00", (10, None), (30, None)), rows).status == "ok"
    short = check(_chain("500.00", (10, None), (30, None)), rows)
    assert (short.status, short.difference) == ("difference", Decimal("-500.00"))
    accepted = check(_chain("400000.00", (30, None), accepted="20000.00"), rows)
    assert accepted.status == "accepted"
    # Zamówienie MD bez zmian: porównanie kwoty co do grosza.
    md = check(_chain("1000.00", (10, None)), rows)
    assert (md.status, md.basis) == ("ok", "amount")


def test_two_cost_invoices_within_budget_alone_can_exceed_it_together():
    cost = _cost(30, "SAP 1", "100.00")
    rows = _rows(cost)
    first, second = _chain("60.00", (30, None)), _chain("60.00", (30, None))
    attached = [(first, check(first, rows)), (second, check(second, rows))]
    assert [result.status for _chain_, result in attached] == ["ok", "ok"]
    assert row_status(cost, attached, True) == (
        "difference",
        Decimal("120.00"),
        Decimal("20.00"),
    )
    assert row_status(cost, attached[:1], True) == ("ok", Decimal("60.00"), None)


# ── Część miesiąca ───────────────────────────────────────────────────────────


def test_period_fraction_counts_working_days_without_holidays():
    first, last = date(2026, 11, 1), date(2026, 11, 30)
    whole, note = period_fraction(date(2026, 1, 1), None, first, last)
    assert whole == Decimal("1") and note is None
    # Listopad 2026: 20 dni roboczych (11.11 to święto); od 16.11 — 11 dni.
    part, note = period_fraction(date(2026, 11, 16), None, first, last)
    assert part == Decimal(11) / Decimal(20)
    assert note == "częściowy miesiąc: 11 z 20 dni roboczych"


# ── Wpłaty z wyciągu ──────────────────────────────────────────────────────────


def _credit(amount, title, currency="PLN"):
    return StatementLine(
        index=1,
        booked_on=date(2026, 11, 14),
        amount=Decimal(amount),
        direction="credit",
        currency=currency,
        title=title,
        counterparty_name="Bank Testowy S.A.",
        bank_ref="REF1",
    )


def _open(invoice_id, number, to_pay, ksef=None, currency="PLN"):
    return OpenInvoice(
        invoice_id=invoice_id,
        currency=currency,
        to_pay=Decimal(to_pay),
        ksef_numbers=(ksef,) if ksef else (),
        invoice_numbers=(number,),
    )


def test_credit_with_ksef_number_pays_the_invoice_or_part_of_it():
    invoices = [_open(1, "FS 10/118/2026", "30996.00", KSEF_A)]
    full = decide_credit(_credit("30996.00", f"Zapłata {KSEF_A}"), invoices)
    assert (full.invoice_id, full.reason) == (1, "ksef")
    part = decide_credit(_credit("10000.00", f"Zapłata {KSEF_A}"), invoices)
    assert part.invoice_id == 1 and part.amount == Decimal("10000.00")
    too_much = decide_credit(_credit("40000.00", f"Zapłata {KSEF_A}"), invoices)
    assert too_much.invoice_id is None and too_much.reason == "amount_exceeds"


def test_credit_for_a_paid_invoice_is_flagged_not_counted_twice():
    invoices = [_open(1, "FS 10/118/2026", "0.00", KSEF_A)]
    decision = decide_credit(_credit("30996.00", "FS 10/118/2026"), invoices)
    assert decision.invoice_id is None and decision.reason == "already_paid"


def test_invoice_number_in_title_is_matched_as_a_whole_word():
    invoices = [_open(1, "1/10/2026", "100.00"), _open(2, "11/10/2026", "200.00")]
    decision = decide_credit(_credit("200.00", "Faktura 11/10/2026"), invoices)
    assert decision.invoice_id == 2
    spaced = decide_credit(_credit("100.00", "fv 1/10/2026 zapłata"), invoices)
    assert spaced.invoice_id == 1


def test_number_inside_a_longer_number_from_the_title_gives_way():
    # „2/10/2026” krajowej faktury siedzi w „2/10/2026/UE” — wpłata za UE.
    invoices = [_open(1, "2/10/2026", "8265.60"), _open(2, "2/10/2026/UE", "31449.60")]
    decision = decide_credit(
        _credit("31449.60", "REF: 1 /INNE PROW./PLN0,00 2/10/2026/UE 225789781"),
        invoices,
    )
    assert (decision.invoice_id, decision.reason) == (2, "invoice_number")
    domestic = decide_credit(_credit("8265.60", "Zapłata 2/10/2026"), invoices)
    assert domestic.invoice_id == 1


def test_vat_leg_of_our_own_supplier_payment_is_not_a_customer_payment():
    # Santander: płacąc dostawcy w MPP, bank przenosi VAT z naszego rachunku
    # VAT na główny („UZNANIE VAT (SP)”). /IDC/ to NIP sprzedawcy — dostawcy,
    # nie nasz — więc to nie wpłata za naszą fakturę o tym samym numerze
    # (wyciąg 12.11.2026: 13 takich uznań przypiętych do faktur sprzedaży).
    ours = _open(1, "1/11/2026", "48302.10", "1234563218-20261105-0A1B2C3D4E5F-AB")
    leg = _credit("3643.20", "/VAT/3643,20/IDC/1111111111/INV/1/11/2026/TXT/1/11/2026")
    decision = decide_credit(leg, [ours])
    assert (decision.invoice_id, decision.related) == (None, False)
    # Wpłata klienta w MPP ma w /IDC/ nasz NIP — dopasowanie bez zmian.
    paid = decide_credit(
        _credit("39271.63", "/VAT/9030,47/IDC/1234563218/INV/1/11/2026/TXT/1/11/2026"),
        [ours],
    )
    assert (paid.invoice_id, paid.amount) == (1, Decimal("48302.10"))


def test_split_payment_counts_vat_paid_to_the_vat_account():
    assert mpp_vat("/VAT/5157,75/IDC/1111111111/INV/FS 10/124/2026/TXT/X") == Decimal(
        "5157.75"
    )
    invoices = [_open(3, "FS 10/124/2026", "27582.75")]
    decision = decide_credit(
        _credit(
            "22425.00", "/VAT/5157,75/IDC/1111111111/INV/FS 10/124/2026/TXT/ZAPLATA"
        ),
        invoices,
    )
    assert decision.invoice_id == 3
    assert decision.amount == Decimal("27582.75")


def test_credit_without_number_is_only_a_hint_and_unrelated_is_skipped():
    invoices = [_open(4, "FS 11/7/2026", "1230.00")]
    hint = decide_credit(_credit("1230.00", "Zapłata za monitor"), invoices)
    assert hint.invoice_id is None and hint.related and hint.reason == "amount_only"
    assert hint.hint_invoice_id == 4
    other = decide_credit(_credit("500.00", "Zwrot kaucji"), invoices)
    assert not other.related
    foreign = decide_credit(
        _credit("1230.00", "FS 11/7/2026", currency="EUR"), invoices
    )
    assert foreign.reason == "currency_differs"


def _sales_xml(buyer: str) -> bytes:
    path = (
        Path(__file__).parent
        / "data/ksef/sales/9876543210-20261103-A1180C0FFEE1-5C.xml"
    )
    return (
        path.read_text(encoding="utf-8")
        .replace("<NIP>1111111111</NIP>", buyer)
        .encode("utf-8")
    )


@pytest.mark.parametrize(
    ("buyer", "expected"),
    [
        ("<KodUE>FI</KodUE><NrVatUE>12345678</NrVatUE>", "FI12345678"),
        ("<KodUE>fi</KodUE><NrVatUE>FI12345678</NrVatUE>", "FI12345678"),
        ("<KodUE>DE</KodUE><NrVatUE>123 456 789</NrVatUE>", "DE123456789"),
        # Numery z literami: nie wolno ich uciąć ani zgubić prefiksu kraju.
        ("<KodUE>FR</KodUE><NrVatUE>1A123456789</NrVatUE>", "FR1A123456789"),
        ("<KodUE>FR</KodUE><NrVatUE>FR1B987654321</NrVatUE>", "FR1B987654321"),
        ("<KodUE>IE</KodUE><NrVatUE>9S99999L</NrVatUE>", "IE9S99999L"),
        ("<KodUE>AT</KodUE><NrVatUE>U12345678</NrVatUE>", "ATU12345678"),
        ("<KodUE>AT</KodUE><NrVatUE>ATU12345678</NrVatUE>", "ATU12345678"),
        ("<KodUE>ES</KodUE><NrVatUE>X1234567L</NrVatUE>", "ESX1234567L"),
        ("<KodUE>NL</KodUE><NrVatUE>123456789B01</NrVatUE>", "NL123456789B01"),
        ("<KodUE>CY</KodUE><NrVatUE>12345678L</NrVatUE>", "CY12345678L"),
        ("<KodUE>EL</KodUE><NrVatUE>123-456-789</NrVatUE>", "EL123456789"),
        # Kod kraju z faktury decyduje, nawet gdy numer niesie inny prefiks.
        ("<KodUE>DE</KodUE><NrVatUE>FR1A123456789</NrVatUE>", "DEFR1A123456789"),
        ("<KodUE>FI</KodUE><NrVatUE>---</NrVatUE>", None),
        ("<KodKraju>no</KodKraju><NrID>123.456.785</NrID>", "NO123456785"),
        ("<KodKraju>NO</KodKraju><NrID>NO 123 456 785 MVA</NrID>", "NO123456785"),
        ("<KodKraju>CH</KodKraju><NrID>CHE-123.456.789</NrID>", "CHE123456789"),
        ("<KodKraju>GB</KodKraju><NrID>123456789A</NrID>", "GB123456789A"),
        ("<KodKraju>GB</KodKraju><NrID>12345/6789</NrID>", None),
        ("<KodKraju>GB</KodKraju><NrID>1234567890123456789012345678901</NrID>", None),
        ("<KodKraju>G</KodKraju><NrID>123456789</NrID>", None),
        ("<NrID>123456789</NrID>", None),
        ("<KodKraju>NO</KodKraju><NrID>---</NrID>", None),
        ("<NIP>1111111111</NIP>", None),
        ("<BrakID>1</BrakID>", None),
    ],
)
def test_buyer_foreign_id_from_invoice(buyer, expected):
    assert fa_sales.parse_sales_invoice(_sales_xml(buyer)).buyer_foreign_id == expected


def test_registry_resolves_foreign_id_and_rejects_unknown():
    registry = clients.NipRegistry(by_nip={"FI12345678": 7})
    assert registry.resolve("FI12345678") == (7, None)
    assert registry.resolve("FI00000000") == (None, "unknown_buyer")


def _hourly_row(*people):
    return BillingRow(
        client_id=1,
        kind="periodic",
        group_id=5,
        order_id=None,
        order_number="PO-1",
        currency="PLN",
        lines=tuple(
            BillingLine(
                order_id=order_id,
                consultant=name,
                basis="hours",
                quantity=Decimal("168"),
                unit_price=Decimal(price),
                net=Decimal("168") * Decimal(price),
                currency="PLN",
            )
            for order_id, name, price in people
        ),
    )


def _decide_person(
    *people, item_name="ABCD:2026-111111, Jan Przykładowy, usługa", price="150.00"
):
    return decide(
        net=Decimal("24150.00"),
        currency="PLN",
        texts=[item_name],
        rows=[_hourly_row(*people)],
        refs=[],
        items=[{"name": item_name, "unit_price": price}],
    )


def test_person_and_unit_price_bind_when_hours_differ():
    decision = _decide_person(
        (10, "Jan Przykładowy", "150"), (11, "Ewa Testowa", "150")
    )
    assert decision.method == "person"
    assert decision.targets == (Target(order_id=10),)


def test_person_name_order_and_case_do_not_matter():
    decision = _decide_person(
        (10, "Jan Przykładowy", "150"), item_name="USŁUGA, PRZYKŁADOWY JAN"
    )
    assert decision.targets == (Target(order_id=10),)


@pytest.mark.parametrize(
    ("consultant", "item_name"),
    [
        # Faktura po angielsku bez polskich znaków (pomiar 06.11.2026: 5 faktur).
        ("Łukasz Żółtowski", "Consulting services, Lukasz Zoltowski"),
        # I odwrotnie: w NEXUSIE bez znaków, na fakturze ze znakami.
        ("Lukasz Zoltowski", "Usługa, Łukasz Żółtowski"),
    ],
)
def test_person_name_without_polish_letters_still_points_at_the_person(
    consultant, item_name
):
    decision = _decide_person((10, consultant, "150"), item_name=item_name)
    assert decision.method == "person"
    assert decision.targets == (Target(order_id=10),)


@pytest.mark.parametrize(
    ("people", "item_name", "price"),
    [
        # Inna cena: to może być inna umowa albo błąd, decydują Finanse.
        (((10, "Jan Przykładowy", "150"),), "Jan Przykładowy", "151.00"),
        # Sam fragment nazwiska nie wskazuje osoby.
        (((10, "Jan Przykładowy", "150"),), "Jan Przykładowski", "150.00"),
        (((10, "Jan Przykładowy", "150"),), "Przykładowy", "150.00"),
        # Dwie osoby o tym samym nazwisku albo dwa zamówienia jednej osoby.
        (
            ((10, "Jan Przykładowy", "150"), (11, "Jan Przykładowy", "150")),
            "Jan Przykładowy",
            "150.00",
        ),
        # Faktura na dwie osoby naraz.
        (
            ((10, "Jan Przykładowy", "150"), (11, "Ewa Testowa", "150")),
            "Jan Przykładowy, Ewa Testowa",
            "150.00",
        ),
        # Pozycja bez ceny netto (P_9A).
        (((10, "Jan Przykładowy", "150"),), "Jan Przykładowy", None),
        # Pula bez osoby i jednowyrazowa nazwa nie wiążą.
        (((None, "Jan Przykładowy", "150"),), "Jan Przykładowy", "150.00"),
        (((10, "Jan", "150"),), "Jan Kowalski", "150.00"),
    ],
)
def test_person_rule_refuses_when_not_certain(people, item_name, price):
    decision = _decide_person(*people, item_name=item_name, price=price)
    assert decision.matched is False
    assert decision.reason == "amount_differs"


def test_before_correction_item_does_not_point_at_a_person():
    decision = decide(
        net=Decimal("24150.00"),
        currency="PLN",
        texts=["Jan Przykładowy"],
        rows=[_hourly_row((10, "Jan Przykładowy", "150"))],
        refs=[],
        items=[
            {
                "name": "Jan Przykładowy",
                "unit_price": "150.00",
                "before_correction": True,
            }
        ],
    )
    assert decision.matched is False


def test_person_rule_does_not_override_order_number():
    decision = decide(
        net=Decimal("24150.00"),
        currency="PLN",
        texts=["PO-1, Jan Przykładowy"],
        rows=[_hourly_row((10, "Jan Przykładowy", "150"))],
        refs=[OrderRef(client_id=1, group_id=5, order_id=None, number="PO-1")],
        items=[{"name": "PO-1, Jan Przykładowy", "unit_price": "150.00"}],
    )
    assert decision.method == "order_number"


# ── Numer zamówienia, którego NEXUS nie zna ───────────────────────────────────


def _named(net, *order_refs, items=()):
    """Miesiąc klienta z jednym zamówieniem o numerze 87001111 i kwocie 1000."""

    row = _periodic(5, "87001111", "1000.00")
    return decide(
        net=Decimal(net),
        currency="PLN",
        texts=list(order_refs),
        rows=[row],
        refs=_refs(row),
        items=items,
    )


@pytest.mark.parametrize(
    "order_ref",
    [
        "PO number: 0087009999",
        "PO number 87009999, SWE1 contact: Jan Przykładowy jan@example.com",
        "PO 87009999",
        "Purchase order 87009999",
        "Zamówienie nr: ZAM/9/2026/ABC",
        "numer zamówienia: SAP 4500009999",
        "Numer zamówienia: zlecenie X/9/26/AB/9/26CD",
        "Nr zamówienia: 87009999",
        "Protokół odbioru nr 7 dla zamówienia o numerze: ORD99991",
        "87009999",
    ],
)
def test_unknown_order_number_is_not_bound_by_amount(order_ref):
    decision = _named("1000.00", order_ref)
    assert decision.reason == "unknown_order_number"
    assert not decision.matched


def test_unknown_order_number_is_not_bound_by_person():
    row = _periodic(5, "87001111", "1000.00")
    decision = decide(
        net=Decimal("777.00"),
        currency="PLN",
        texts=["PO number: 87009999"],
        rows=[row],
        refs=_refs(row),
        items=[{"name": "Jan Przykładowy", "unit_price": "1"}],
    )
    assert decision.reason == "unknown_order_number"
    assert not decision.matched


def test_unknown_order_number_in_an_item_name_blocks_too():
    row = _periodic(5, "87001111", "1000.00")
    item_name = "Konsultant Jan Przykładowy, Nr zamówienia 1234/2026, SSGW 100001-1"
    decision = decide(
        net=Decimal("1000.00"),
        currency="PLN",
        texts=[item_name],
        rows=[row],
        refs=_refs(row),
        items=[{"name": item_name, "unit_price": "1"}],
    )
    assert decision.reason == "unknown_order_number"
    assert not decision.matched


def test_known_order_number_still_binds():
    decision = _named("777.00", "PO number: 0087001111")
    assert decision.method == "order_number"
    assert decision.targets == (Target(order_id=5),)


def test_known_number_wins_over_a_second_unknown_one():
    decision = _named("777.00", "PO number: 87009999", "PO number: 87001111")
    assert decision.method == "order_number"


@pytest.mark.parametrize(
    "order_ref",
    [
        "Reference: Jan Przykładowy - application code: L12345 project name: L12345",
        "Project name ARD2026 security test",
        "jan.przykladowy2026@example.com",
        "Nr umowy 12/2026 osoba wystawiająca zamówienie: Anna Przykładowa",
        "Zamówienie z dnia 12.10.2026 do umowy ramowej z dnia 3 lipca 2024",
        "Discount, according to the frame agreement - 1,5%",
        "lipiec 2026",
        "2026",
        "PO Box 12345",
        "po 30 dniach od wystawienia",
    ],
)
def test_digits_outside_an_order_number_do_not_block_the_amount(order_ref):
    decision = _named("1000.00", order_ref)
    assert decision.method == "amount"
    assert decision.targets == (Target(order_id=5),)


def test_invoice_without_any_number_binds_by_amount():
    assert _named("1000.00").method == "amount"


def test_unknown_order_number_is_retried_and_explained():
    assert "unknown_order_number" in RETRY_REASONS
    assert "unknown_order_number" in REASON_LABELS
    # Faktura wskazująca osobę bez pozycji dalej alarmuje DL-a.
    assert "unknown_order_number" in GAP_REASONS


@pytest.mark.asyncio
async def test_auto_match_blocks_by_the_number_written_on_the_invoice(monkeypatch):
    row = _periodic(5, "87001111", "1000.00")

    async def family(_db, _client_ids):
        return {1}

    async def billing_rows(_db, **_kwargs):
        return [row]

    async def order_refs(_db, _members):
        return _refs(row)

    monkeypatch.setattr(clients, "family", family)
    monkeypatch.setattr(billing, "billing_rows", billing_rows)
    monkeypatch.setattr(billing, "order_refs", order_refs)
    invoice = ClientSalesInvoice(
        client_id=1,
        invoice_kind="original",
        match_status="unmatched",
        period_year=2026,
        period_month=7,
        net_amount=Decimal("1000.00"),
        currency="PLN",
        order_refs=["PO number: 87009999"],
        items=[],
    )

    decision = await auto_match(AsyncMock(), invoice, registry=object())

    assert decision.reason == "unknown_order_number"
    assert (invoice.match_status, invoice.match_reason) == (
        "unmatched",
        "unknown_order_number",
    )


# ── Zapłata a termin ─────────────────────────────────────────────────────────


def test_unpaid_after_due_date_is_missing_payment_data_not_overdue():
    """19.11.2026: 2 741 faktur „po terminie”, żadna z datą zapłaty (wyciągi z 12.11)."""

    today = date(2026, 11, 19)

    def payload(due, *paid):
        head = ClientSalesInvoice(
            id=1,
            currency="PLN",
            issue_date=date(2026, 9, 3),
            due_date=due,
            net_amount=Decimal("1000.00"),
            gross_amount=Decimal("1230.00"),
            match_status="unmatched",
        )
        chain = Chain(
            head=head,
            payments=[
                ClientSalesInvoicePayment(amount=Decimal(value), booked_on=today)
                for value in paid
            ],
        )
        result = chain_payload(chain, ChainCheck("unmatched", None, None), today)
        return (
            result["payment_status"],
            result["overdue_days"],
            result["payment_unknown"],
        )

    assert payload(date(2026, 10, 2)) == ("unpaid", 0, True)
    assert payload(date(2026, 10, 2), "230.00") == ("partial", 0, True)
    assert payload(date(2026, 10, 2), "1230.00") == ("paid", 0, False)
    assert payload(date(2026, 11, 19)) == ("unpaid", 0, False)
    assert payload(None) == ("unpaid", 0, False)
