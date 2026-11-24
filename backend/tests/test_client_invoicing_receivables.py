"""Monity i należności po terminie (bez bazy): VAT w PLN, eskalacja, stan na dzień, treść.

Reguła: ``docs/claude/zamowienia/monity-i-naleznosci-po-terminie.md``. Kod:
``client_invoicing/receivables.py``, ``payment_reminders.py``, ``overdue_export.py``.
Numery rachunków są fikcyjne (suma kontrolna liczona w teście), kontrahentów brak.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.models.contact import Contact
from app.services.client_invoicing import issue_settings, receivables
from app.services.client_invoicing.ledger import Chain
from app.services.client_invoicing.overdue_export import state_text, table
from app.services.client_invoicing.payment_proof import (
    KnownStatement,
    PendingCredit,
    Proof,
    Verdict,
)
from app.services.client_invoicing.payment_reminders import (
    DraftInvoice,
    Recipient,
    compose,
    finance_contact,
    language_for,
    level_for,
    merge_recipients,
    totals,
)
from app.services.client_invoicing.views import Late
from app.services.hr.bank.accounts import iban_check_digits
from app.services.ledger.bank_continuity import Span

TODAY = date(2026, 11, 23)
CLIENT = 41
UPLOADED = datetime(2026, 11, 20, 17, 0, tzinfo=timezone.utc)
INVOICE_IN = datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc)
RATE = receivables.Rate(Decimal("4.2500"), date(2026, 4, 30), "nbp")


def _nrb(tail: str) -> str:
    bban = "10901056" + tail.rjust(16, "0")
    return iban_check_digits(bban) + bban


PLN = _nrb("1111")
EUR = _nrb("2222")


def _issue() -> dict:
    return issue_settings.normalize(
        {"accounts": {"PLN": {"number": PLN}, "EUR": {"number": EUR}}}
    )


def _months(account: str, *months: int) -> list[KnownStatement]:
    out = []
    for index, month in enumerate(months):
        start = date(2026, month, 1)
        end = date(2026, month + 1, 1) - timedelta(days=1)
        out.append(
            KnownStatement(
                id=month + (100 if account == EUR else 0),
                account=account,
                span=Span(10_000 * index, start, 10_000 * (index + 1), end),
                created_at=UPLOADED,
                credits_matched=True,
            )
        )
    return out


def _proof(statements, *, pending=(), unassigned=None) -> Proof:
    by_account: dict[str, list[KnownStatement]] = {}
    for item in statements:
        by_account.setdefault(item.account, []).append(item)
    return Proof(
        issue=_issue(),
        ledger_accounts={PLN: "PLN", EUR: "EUR"},
        statements={key: tuple(value) for key, value in by_account.items()},
        pending=tuple(pending),
        unassigned=unassigned or {},
    )


def _invoice(
    invoice_id: int = 1,
    *,
    net: str = "1000.00",
    gross: str = "1230.00",
    currency: str = "EUR",
    issued: date = date(2026, 5, 4),
    due: date | None = date(2026, 5, 18),
    number: str = "12/5/2026",
    corrects: int | None = None,
    country: str | None = None,
) -> ClientSalesInvoice:
    return ClientSalesInvoice(
        id=invoice_id,
        ksef_number=f"5250000000-20260504-AAAAAA-BBBBB{invoice_id}-CC",
        invoice_number=number,
        invoice_kind="correction" if corrects else "original",
        corrects_invoice_id=corrects,
        currency=currency,
        client_id=CLIENT,
        issue_date=issued,
        due_date=due,
        net_amount=Decimal(net),
        gross_amount=Decimal(gross),
        match_status="unmatched",
        created_at=INVOICE_IN,
        buyer_country=country,
    )


def _chain(*, paid=(), corrections=(), **kwargs) -> Chain:
    head = _invoice(**kwargs)
    return Chain(
        head=head,
        corrections=list(corrections),
        payments=[
            ClientSalesInvoicePayment(
                amount=Decimal(value), currency=head.currency, booked_on=day
            )
            for value, day in paid
        ],
    )


NET_PAID = (("1000.00", date(2026, 5, 15)),)


# ── VAT w PLN nieopłacony ────────────────────────────────────────────────────


def test_eur_invoice_with_net_paid_leaves_only_vat():
    assert receivables.vat_gap(_chain(paid=NET_PAID)) == Decimal("230.00")


def test_partial_payment_below_net_is_an_ordinary_partial_payment():
    """Wpłata mniejsza niż netto: reszta to i netto, i VAT — zwykła częściowa zapłata."""

    chain = _chain(paid=(("600.00", date(2026, 5, 15)),))

    assert receivables.vat_gap(chain) is None
    assert chain.to_pay == Decimal("630.00")


def test_net_plus_part_of_vat_leaves_the_rest_of_vat():
    assert receivables.vat_gap(
        _chain(paid=(("1100.00", date(2026, 5, 15)),))
    ) == Decimal("130.00")


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "currency": "PLN",
            "paid": NET_PAID,
        },  # VAT w PLN faktury w PLN to zwykła reszta
        {"paid": (("1230.00", date(2026, 5, 15)),)},  # zapłacona w całości
        {"paid": ()},  # nic nie wpłynęło
        {"gross": "1000.00", "paid": NET_PAID},  # bez VAT (np. odwrotne obciążenie)
    ],
)
def test_no_vat_gap(kwargs):
    assert receivables.vat_gap(_chain(**kwargs)) is None


def test_correction_changes_net_and_vat_of_the_chain():
    """Korekta −200 netto / −246 brutto: netto 800 zapłacone, został VAT 184."""

    correction = _invoice(
        2, net="-200.00", gross="-246.00", corrects=1, issued=date(2026, 5, 10)
    )
    chain = _chain(paid=(("800.00", date(2026, 5, 15)),), corrections=[correction])

    assert receivables.vat_gap(chain) == Decimal("184.00")


def test_correction_to_zero_leaves_nothing_to_pay():
    correction = _invoice(2, net="-1000.00", gross="-1230.00", corrects=1)

    assert receivables.vat_gap(_chain(corrections=[correction])) is None


def test_vat_in_pln_uses_the_invoice_rate():
    assert receivables.to_pln(Decimal("230.00"), RATE) == Decimal("977.50")
    assert receivables.to_pln(Decimal("230.00"), None) is None


def test_rate_day_is_the_business_day_before_sale():
    chain = _chain()
    chain.head.sale_date = date(2026, 5, 4)  # poniedziałek

    assert receivables.rate_day(chain) == date(2026, 4, 30)  # 1–3.05 wolne


# ── Dowód: VAT idzie z wyciągów rachunku PLN ─────────────────────────────────


def test_vat_gap_is_overdue_only_with_pln_statements():
    chain = _chain(paid=NET_PAID)
    eur_only = _proof(_months(EUR, 4, 5, 6))
    both = _proof(_months(EUR, 4, 5, 6) + _months(PLN, 4, 5, 6))

    # Ciągłe wyciągi EUR nie mówią nic o przelewie VAT w PLN.
    pln_unknown = eur_only.verdict(
        chain, TODAY, currency="PLN", amount=Decimal("977.50")
    )
    assert (pln_unknown.unknown, pln_unknown.reason) == (True, "statements")
    proven = both.verdict(chain, TODAY, currency="PLN", amount=Decimal("977.50"))
    assert proven.overdue_days == (date(2026, 6, 30) - date(2026, 5, 18)).days
    assert proven.account == "1111"


def test_pln_credit_with_the_invoice_number_may_be_the_vat():
    chain = _chain(paid=NET_PAID)
    credit = PendingCredit(
        title="VAT do FV 12/5/2026",
        amount=Decimal("977.00"),
        currency="PLN",
        booked_on=date(2026, 5, 20),
    )
    proof = _proof(_months(PLN, 4, 5, 6), pending=[credit])

    verdict = proof.verdict(chain, TODAY, currency="PLN", amount=Decimal("977.50"))
    assert verdict.reason == "credit_pending"


def test_pln_credit_equal_to_vat_in_pln_may_be_the_vat():
    chain = _chain(paid=NET_PAID)
    credit = PendingCredit(
        title="przelew", amount=Decimal("977.50"), currency="PLN", booked_on=None
    )
    proof = _proof(_months(PLN, 4, 5, 6), pending=[credit])

    assert (
        proof.verdict(chain, TODAY, currency="PLN", amount=Decimal("977.50")).reason
        == "credit_pending"
    )
    # Bez kursu nie porównujemy kwoty: sama kwota w PLN nie wystarcza.
    assert proof.verdict(chain, TODAY, currency="PLN", amount=None).overdue_days > 0


def test_eur_credit_equal_to_vat_does_not_block_the_pln_verdict():
    chain = _chain(paid=NET_PAID)
    credit = PendingCredit(
        title="przelew", amount=Decimal("230.00"), currency="EUR", booked_on=None
    )
    proof = _proof(_months(PLN, 4, 5, 6), pending=[credit])

    assert (
        proof.verdict(
            chain, TODAY, currency="PLN", amount=Decimal("977.50")
        ).overdue_days
        > 0
    )


def test_unassigned_ledger_line_in_pln_may_be_the_vat():
    chain = _chain(paid=NET_PAID)
    proof = _proof(
        _months(PLN, 4, 5, 6), unassigned={("PLN", 97750): (date(2026, 5, 25),)}
    )

    assert (
        proof.verdict(chain, TODAY, currency="PLN", amount=Decimal("977.50")).reason
        == "credit_pending"
    )


def test_compensation_series_never_gets_a_vat_monit():
    chain = _chain(paid=NET_PAID, number="303/5/2026/Benefit")
    proof = _proof(_months(PLN, 4, 5, 6))

    verdict = proof.verdict(chain, TODAY, currency="PLN", amount=Decimal("977.50"))
    assert (verdict.unknown, verdict.reason) == (True, "compensation")


def test_default_verdict_is_unchanged_for_ordinary_invoices():
    chain = _chain(currency="PLN")
    proof = _proof(_months(PLN, 4, 5, 6))

    assert (
        proof.verdict(chain, TODAY).overdue_days
        == proof.verdict(chain, TODAY, currency=None).overdue_days
    )


# ── Eskalacja 7 / 14 / 30 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("days", "level"),
    [
        (0, None),
        (6, None),
        (7, "first"),
        (13, "first"),
        (14, "second"),
        (29, "second"),
        (30, "final"),
        (400, "final"),
    ],
)
def test_escalation_thresholds(days, level):
    assert receivables.escalation(days) == level


def _draft(days: int, **kwargs) -> DraftInvoice:
    values = dict(
        invoice_id=1,
        number="12/5/2026",
        ksef_number="5250000000-20260504-AAAAAA-BBBBBB-CC",
        issue_date=date(2026, 5, 4),
        due_date=date(2026, 5, 18),
        currency="PLN",
        to_pay=Decimal("1230.00"),
        overdue_days=days,
        statements_until=date(2026, 6, 30),
    )
    values.update(kwargs)
    return DraftInvoice(**values)


def test_level_is_the_highest_among_invoices():
    assert level_for([_draft(8), _draft(31, invoice_id=2)]) == "final"
    assert level_for([_draft(3)]) is None
    assert level_for([]) is None


# ── Stan na dzień ────────────────────────────────────────────────────────────


def test_as_of_drops_later_payments_and_corrections():
    correction = _invoice(
        2, net="-200.00", gross="-246.00", corrects=1, issued=date(2026, 7, 2)
    )
    chain = _chain(
        currency="PLN",
        paid=(("500.00", date(2026, 6, 10)), ("484.00", date(2026, 7, 5))),
        corrections=[correction],
    )

    june = receivables.as_of(chain, date(2026, 6, 30))
    assert june is not None
    assert (june.gross, june.paid, june.to_pay) == (
        Decimal("1230.00"),
        Decimal("500.00"),
        Decimal("730.00"),
    )
    assert receivables.as_of(chain, date(2026, 7, 31)).to_pay == Decimal("0.00")
    assert receivables.as_of(chain, date(2026, 5, 1)) is None
    # Oryginał zostaje nietknięty.
    assert len(chain.payments) == 2 and len(chain.corrections) == 1


# ── Treść monitu ─────────────────────────────────────────────────────────────


def test_first_reminder_lists_invoices_totals_and_accounts():
    subject, text = compose(
        [
            _draft(9),
            _draft(8, invoice_id=2, number="13/5/2026", to_pay=Decimal("100.00")),
        ],
        level="first",
        language="pl",
        accounts={"PLN": PLN},
        signature=["Osoba z Finansów", "Spółka"],
    )

    assert subject == "Przypomnienie o płatności — 2 faktury po terminie"
    assert "12/5/2026" in text and "13/5/2026" in text
    assert "do zapłaty 1 230,00 PLN — 9 dni po terminie" in text
    assert "Razem do zapłaty: 1 330,00 PLN" in text
    assert f"PLN: {PLN}" in text
    assert "Stan wpłat na 30.06.2026." in text
    assert "odsetek" not in text
    assert text.rstrip().endswith("Spółka")


def test_final_reminder_mentions_statutory_interest():
    subject, text = compose(
        [_draft(45)], level="final", language="pl", accounts={}, signature=[]
    )

    assert subject.startswith("Ostateczne wezwanie do zapłaty — 1 faktura")
    assert "odsetek ustawowych za opóźnienie w transakcjach handlowych" in text


def test_vat_line_asks_for_pln_on_the_pln_account():
    vat = _draft(
        20,
        currency="EUR",
        to_pay=Decimal("230.00"),
        vat=Decimal("230.00"),
        vat_pln=Decimal("977.50"),
    )
    _, text = compose(
        [vat],
        level="second",
        language="pl",
        accounts={"PLN": PLN, "EUR": EUR},
        signature=[],
    )

    assert "netto zapłacone, do zapłaty VAT 977,50 PLN — 20 dni po terminie" in text
    assert "Razem do zapłaty: 977,50 PLN" in text
    # Rachunek EUR nie jest potrzebny: VAT płaci się w PLN.
    assert f"PLN: {PLN}" in text and EUR not in text
    assert totals([vat]) == {"PLN": Decimal("977.50")}


def test_vat_without_rate_has_no_pln_total():
    vat = _draft(20, currency="EUR", to_pay=Decimal("230.00"), vat=Decimal("230.00"))
    _, text = compose([vat], level="second", language="pl", accounts={}, signature=[])

    assert "VAT 230,00 EUR przeliczony na PLN po kursie z faktury" in text
    assert "Razem do zapłaty" not in text


def test_english_reminder_for_foreign_buyers():
    subject, text = compose(
        [_draft(15, currency="EUR", to_pay=Decimal("1234.50"))],
        level="second",
        language="en",
        accounts={"EUR": EUR},
        signature=[],
    )

    assert subject == "Second payment reminder — 1 overdue invoice"
    assert "outstanding 1,234.50 EUR — 15 days overdue" in text
    assert f"EUR: {EUR}" in text


def _late(country: str | None) -> Late:
    return Late(_chain(country=country), Verdict(overdue_days=10))


def test_language_is_english_only_when_every_buyer_is_abroad():
    assert language_for([_late("DE"), _late("FI")]) == "en"
    assert language_for([_late("DE"), _late("PL")]) == "pl"
    assert language_for([_late("DE"), _late(None)]) == "pl"
    assert language_for([]) == "pl"


# ── Adresaci ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("department", "position", "expected"),
    [
        ("Finanse", None, True),
        (None, "Główna księgowa", True),
        ("Accounts Payable", None, True),
        (None, "Specjalista ds. rozliczeń", True),
        ("IT", "Kierownik projektu", False),
        (None, None, False),
    ],
)
def test_finance_contact(department, position, expected):
    contact = Contact(name="x", department=department, position=position)

    assert finance_contact(contact) is expected


def test_recipients_keep_the_first_source_for_a_repeated_address():
    merged = merge_recipients(
        [
            [Recipient("ap@example.com", "AP", "contact")],
            [
                Recipient("ap@example.com", None, "send_to"),
                Recipient("pm@example.com", None, "acceptance"),
            ],
        ]
    )

    assert [(r.email, r.source) for r in merged] == [
        ("ap@example.com", "contact"),
        ("pm@example.com", "acceptance"),
    ]


# ── Lista na zamknięcie miesiąca ─────────────────────────────────────────────


def test_month_close_lists_proven_first_and_unknown_without_days():
    proven = Late(
        _chain(currency="PLN"),
        Verdict(overdue_days=40, account="1111", until=date(2026, 6, 30)),
    )
    vat = Late(
        _chain(paid=NET_PAID),
        Verdict(overdue_days=12, account="1111", until=date(2026, 6, 30)),
        vat=Decimal("230.00"),
        vat_pln=Decimal("977.50"),
        rate=RATE,
    )
    unknown = Late(
        _chain(currency="PLN", number="=HYPERLINK(1)"),
        Verdict(unknown=True, reason="statements", account="1111"),
    )
    sent = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)

    rows = table(
        [unknown, vat, proven],
        names={CLIENT: "Klient"},
        numbers={CLIENT: "1234563218"},
        last={CLIENT: (sent, "first")},
    )

    assert [row[11] for row in rows] == ["40", "12", ""]
    assert [row[12] for row in rows] == [
        "Ostateczne wezwanie do zapłaty",
        "Przypomnienie o płatności",
        "",
    ]
    assert rows[1][10] == "977.50"
    assert rows[1][13].startswith("VAT w PLN nieopłacony (netto zapłacone)")
    assert rows[2][13].startswith("brak danych o zapłacie: brak ciągłych wyciągów")
    assert rows[0][14] == "02.11.2026"


def test_state_text_for_partial_payment():
    late = Late(
        _chain(currency="PLN", paid=(("230.00", date(2026, 5, 15)),)),
        Verdict(overdue_days=5, until=date(2026, 6, 30)),
    )

    assert state_text(late) == "po terminie, zapłacono część; wpłaty do 30.06.2026"
