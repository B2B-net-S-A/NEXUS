"""„Po terminie” tylko z dowodem z wyciągów (bez bazy).

Reguła: ostatnia sekcja ``docs/claude/zamowienia/faktury-do-klientow-z-ksef.md``
(19.11.2026), kod ``app/services/client_invoicing/payment_proof.py``. Numery
rachunków w testach są fikcyjne (suma kontrolna liczona w teście).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.services.client_invoicing import issue_settings
from app.services.client_invoicing.ledger import Chain, ChainCheck
from app.services.client_invoicing.payment_proof import (
    KnownStatement,
    PendingCredit,
    Proof,
    is_compensation,
    compensation_patterns,
    reasons_summary,
)
from app.services.client_invoicing.views import chain_payload
from app.services.hr.bank.accounts import iban_check_digits
from app.services.ledger.bank_continuity import Span

TODAY = date(2026, 11, 19)
CLIENT = 41
OTHER = 42


def _nrb(tail: str) -> str:
    bban = "10901056" + tail.rjust(16, "0")
    return iban_check_digits(bban) + bban


PLN = _nrb("1111")
EUR_DEFAULT = _nrb("2222")
EUR_CLIENT = _nrb("3333")
UPLOADED = datetime(2026, 11, 18, 17, 0, tzinfo=timezone.utc)
#: Faktura trafia do NEXUSA w dniu wystawienia (pętla KSeF).
INVOICE_IN = datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc)


def _issue(overrides: dict[int, str] | None = None) -> dict:
    return issue_settings.normalize(
        {
            "accounts": {
                "PLN": {"number": f"PL{PLN}"},
                "EUR": {"number": f"PL {EUR_DEFAULT}"},
            },
            "clients": {
                str(client): {"accounts": {"EUR": {"number": number}}}
                for client, number in (overrides or {}).items()
            },
        }
    )


def _statement(
    account: str,
    start: date,
    end: date,
    opening: int,
    closing: int,
    *,
    statement_id: int,
    created_at: datetime = UPLOADED,
    credits_matched: bool = True,
) -> KnownStatement:
    return KnownStatement(
        id=statement_id,
        account=account,
        span=Span(opening, start, closing, end),
        created_at=created_at,
        credits_matched=credits_matched,
    )


def _months(account: str, *months: int, **kwargs) -> list[KnownStatement]:
    """Wyciągi miesięczne 2026 r. z łańcuchem sald (saldo rośnie o 100 zł)."""

    out = []
    for index, month in enumerate(months):
        start = date(2026, month, 1)
        end = (
            date(2026, month + 1, 1) if month < 12 else date(2027, 1, 1)
        ) - timedelta(days=1)
        out.append(
            _statement(
                account,
                start,
                end,
                10_000 * index,
                10_000 * (index + 1),
                statement_id=month,
                **kwargs,
            )
        )
    return out


def _proof(
    statements, *, issue=None, accounts=None, pending=(), unassigned=None
) -> Proof:
    by_account: dict[str, list[KnownStatement]] = {}
    for item in statements:
        by_account.setdefault(item.account, []).append(item)
    return Proof(
        issue=issue or _issue(),
        ledger_accounts=accounts
        if accounts is not None
        else {PLN: "PLN", EUR_CLIENT: "EUR"},
        statements={key: tuple(value) for key, value in by_account.items()},
        pending=tuple(pending),
        unassigned=unassigned or {},
    )


def _chain(
    *,
    issued=date(2026, 5, 4),
    due=date(2026, 5, 18),
    currency="PLN",
    client_id=CLIENT,
    number="12/5/2026",
    created_at=INVOICE_IN,
    paid=(),
) -> Chain:
    head = ClientSalesInvoice(
        id=1,
        ksef_number="5250000000-20260504-AAAAAA-BBBBBB-CC",
        invoice_number=number,
        currency=currency,
        client_id=client_id,
        issue_date=issued,
        due_date=due,
        net_amount=Decimal("1000.00"),
        gross_amount=Decimal("1230.00"),
        match_status="unmatched",
        created_at=created_at,
    )
    return Chain(
        head=head,
        payments=[
            ClientSalesInvoicePayment(amount=Decimal(value), booked_on=issued)
            for value in paid
        ],
    )


def _verdict(proof: Proof, chain: Chain):
    verdict = proof.verdict(chain, TODAY)
    return verdict.overdue_days, verdict.reason


# ── Dowód jest ───────────────────────────────────────────────────────────────


def test_unpaid_invoice_with_continuous_statements_is_overdue_until_their_last_day():
    proof = _proof(_months(PLN, 4, 5, 6))
    verdict = proof.verdict(_chain(), TODAY)

    # Dni do ostatniego dnia ciągłości (30.06), nie do dziś: potem NEXUS nie wie.
    assert (verdict.overdue_days, verdict.unknown) == (
        (date(2026, 6, 30) - date(2026, 5, 18)).days,
        False,
    )
    assert (verdict.account, verdict.until) == ("1111", date(2026, 6, 30))


def test_paid_or_not_yet_due_invoice_has_no_verdict():
    proof = _proof(_months(PLN, 4, 5, 6))

    assert _verdict(proof, _chain(paid=("1230.00",))) == (0, None)
    assert _verdict(proof, _chain(due=TODAY)) == (0, None)
    assert _verdict(proof, _chain(due=None)) == (0, None)


def test_partial_payment_leaves_the_rest_overdue():
    proof = _proof(_months(PLN, 4, 5, 6))

    assert _verdict(proof, _chain(paid=("230.00",)))[0] > 0


# ── Rachunek odbioru ─────────────────────────────────────────────────────────


def test_client_account_override_decides_which_statements_count():
    """Klient z rachunkiem EUR przy sobie płaci na niego, nie na domyślny EUR."""

    issue = _issue({CLIENT: EUR_CLIENT})
    eur = dict(currency="EUR")

    client_statements = _proof(
        _months(EUR_CLIENT, 4, 5, 6), issue=issue, accounts={EUR_CLIENT: "EUR"}
    )
    assert _verdict(client_statements, _chain(**eur))[0] > 0
    # Inny klient płaci na domyślny EUR, którego nie ma w Księdze.
    assert _verdict(client_statements, _chain(client_id=OTHER, **eur)) == (
        0,
        "account_outside_ledger",
    )

    default_only = _proof(
        _months(EUR_DEFAULT, 4, 5, 6),
        issue=issue,
        accounts={EUR_DEFAULT: "EUR", EUR_CLIENT: "EUR"},
    )
    assert _verdict(default_only, _chain(**eur)) == (0, "statements")
    assert _verdict(default_only, _chain(client_id=OTHER, **eur))[0] > 0


def test_account_missing_in_settings_or_in_another_currency_is_not_proof():
    no_eur = issue_settings.normalize({"accounts": {"PLN": {"number": PLN}}})
    proof = _proof(_months(PLN, 4, 5, 6), issue=no_eur)

    assert _verdict(proof, _chain(currency="EUR")) == (0, "no_account")
    wrong_currency = _proof(_months(PLN, 4, 5, 6), accounts={PLN: "EUR"})
    assert _verdict(wrong_currency, _chain()) == (0, "account_outside_ledger")


# ── Łańcuch sald ─────────────────────────────────────────────────────────────


def test_gap_in_the_balance_chain_is_missing_data_until_the_gap():
    """Brak wyciągu za maj: kwiecień i czerwiec nie łączą się saldem."""

    april, _, june = _months(PLN, 4, 5, 6)
    proof = _proof([april, june])
    verdict = proof.verdict(_chain(), TODAY)

    assert (verdict.unknown, verdict.reason, verdict.until) == (
        True,
        "statements",
        date(2026, 4, 30),
    )
    # Czerwcowa faktura ma ciągłość od czerwca — ale wyciąg musi otwierać się przed nią.
    june_invoice = _chain(issued=date(2026, 6, 3), due=date(2026, 6, 17))
    assert (
        _verdict(proof, june_invoice)[0] == (date(2026, 6, 30) - date(2026, 6, 17)).days
    )


def test_statement_without_e8_check_does_not_prove_anything():
    april, may, june = _months(PLN, 4, 5, 6)
    unchecked = KnownStatement(may.id, may.account, may.span, may.created_at, False)
    proof = _proof([april, unchecked, june])

    assert _verdict(proof, _chain()) == (0, "statements")


# ── Faktura dodana po wyciągu ────────────────────────────────────────────────


def test_statement_uploaded_before_the_invoice_was_in_nexus_does_not_count():
    """E8 dopasowuje uznania tylko do faktur, które już są w NEXUSIE."""

    early = _months(PLN, 4, 5, 6, created_at=datetime(2026, 7, 2, tzinfo=timezone.utc))
    late_invoice = _chain(created_at=datetime(2026, 7, 5, tzinfo=timezone.utc))

    assert _verdict(_proof(early), late_invoice) == (0, "statements")
    assert _verdict(_proof(early), _chain())[0] > 0


def test_correction_added_after_the_statement_counts_like_the_invoice():
    early = _months(PLN, 4, 5, 6, created_at=datetime(2026, 7, 2, tzinfo=timezone.utc))
    chain = _chain()
    chain.corrections.append(
        ClientSalesInvoice(
            id=2,
            invoice_number="KOR/1/7/2026",
            currency="PLN",
            issue_date=date(2026, 7, 3),
            net_amount=Decimal("-100.00"),
            gross_amount=Decimal("-123.00"),
            created_at=datetime(2026, 7, 6, tzinfo=timezone.utc),
        )
    )

    assert _verdict(_proof(early), chain) == (0, "statements")


# ── Kompensata ───────────────────────────────────────────────────────────────


def test_benefit_invoice_is_settled_by_compensation_not_overdue():
    proof = _proof(_months(PLN, 4, 5, 6))

    assert _verdict(proof, _chain(number="303/5/2026/Benefit")) == (0, "compensation")
    assert _verdict(proof, _chain(number="303/5/2026/benefit ")) == (0, "compensation")
    assert _verdict(proof, _chain(number="303/5/2026/UE"))[0] > 0


def test_compensation_follows_the_series_pattern_from_settings():
    issue = issue_settings.normalize({"series": {"BEN": "BEN/{n}/{mm}/{yyyy}"}})
    patterns = compensation_patterns(issue)

    assert is_compensation("BEN/7/05/2026", patterns)
    # Faktury z eBI24 sprzed zmiany wzoru mają domyślny.
    assert is_compensation("7/5/2026/Benefit", patterns)
    assert not is_compensation("7/5/2026", patterns)


# ── Termin a ostatni dzień ciągłości ─────────────────────────────────────────


def test_due_date_on_the_last_covered_day_is_not_overdue_yet():
    """Wpłata w dniu terminu jest w terminie, a po nim wyciągów nie ma."""

    proof = _proof(_months(PLN, 4, 5))

    assert _verdict(proof, _chain(due=date(2026, 5, 31))) == (0, "statements")
    assert _verdict(proof, _chain(due=date(2026, 5, 30))) == (1, None)


def test_invoice_issued_on_the_first_covered_day_needs_the_previous_statement():
    """Data SWIFT: wyciąg z otwarciem 01.05 może nie obejmować operacji z 01.05."""

    proof = _proof(_months(PLN, 5, 6))

    assert _verdict(proof, _chain(issued=date(2026, 5, 1))) == (0, "statements")
    assert _verdict(proof, _chain(issued=date(2026, 5, 2)))[0] > 0


# ── Wpłata do sprawdzenia ────────────────────────────────────────────────────


def _pending(title: str, amount: str, currency="PLN", booked_on=date(2026, 5, 20)):
    return PendingCredit(title, Decimal(amount), currency, booked_on)


def test_credit_waiting_for_finance_may_be_the_payment():
    statements = _months(PLN, 4, 5, 6)

    by_number = _proof(statements, pending=[_pending("zapłata FV 12/5/2026", "999.00")])
    assert _verdict(by_number, _chain()) == (0, "credit_pending")
    by_amount = _proof(statements, pending=[_pending("usługi maj", "1230.00")])
    assert _verdict(by_amount, _chain()) == (0, "credit_pending")
    # Ta sama kwota sprzed wystawienia albo w innej walucie to nie ta wpłata.
    older = _proof(
        statements, pending=[_pending("usługi", "1230.00", booked_on=date(2026, 4, 2))]
    )
    assert _verdict(older, _chain())[0] > 0
    other = _proof(statements, pending=[_pending("usługi", "1230.00", currency="EUR")])
    assert _verdict(other, _chain())[0] > 0


def test_credit_e8_left_without_a_trace_may_be_the_payment():
    """Przegląd 19.11.2026: dwie faktury po 1 230,00 zł, wpłata 1 230,00 zł bez
    numeru — E8 jej nie zapisuje (kwota pasuje do kilku faktur), ale Księga ma ją
    jako operację bez konta. Taka wpłata w oknie faktury blokuje „po terminie”."""

    statements = _months(PLN, 4, 5, 6)
    loose = _proof(statements, unassigned={("PLN", 123_000): (date(2026, 5, 20),)})
    assert _verdict(loose, _chain()) == (0, "credit_pending")
    # Inna kwota, inna waluta albo dzień poza oknem (przed wystawieniem, po
    # ostatnim dniu ciągłości) nie blokują.
    for key, day in (
        (("PLN", 123_001), date(2026, 5, 20)),
        (("EUR", 123_000), date(2026, 5, 20)),
        (("PLN", 123_000), date(2026, 5, 3)),
        (("PLN", 123_000), date(2026, 7, 1)),
    ):
        assert _verdict(_proof(statements, unassigned={key: (day,)}), _chain())[0] > 0


# ── Payload i podsumowanie ───────────────────────────────────────────────────


def test_payload_carries_the_verdict_and_falls_back_to_missing_data():
    chain = _chain()
    check = ChainCheck("unmatched", None, None)
    proof = _proof(_months(PLN, 4, 5, 6))

    proven = chain_payload(chain, check, TODAY, verdict=proof.verdict(chain, TODAY))
    assert (proven["overdue_days"], proven["payment_unknown"]) == (43, False)
    assert (proven["payment_account"], proven["statements_until"]) == (
        "1111",
        "2026-06-30",
    )
    unproven = chain_payload(chain, check, TODAY)
    assert (unproven["overdue_days"], unproven["payment_unknown"]) == (0, True)


def test_reasons_summary_counts_unknown_invoices_per_reason_and_account():
    proof = _proof(_months(PLN, 4))
    verdicts = [
        proof.verdict(_chain(), TODAY),
        proof.verdict(_chain(number="1/5/2026/Benefit"), TODAY),
        proof.verdict(_chain(issued=date(2026, 5, 6)), TODAY),
    ]

    assert [
        (r["reason"], r["account"], r["count"]) for r in reasons_summary(verdicts)
    ] == [
        ("statements", "1111", 2),
        ("compensation", None, 1),
    ]
