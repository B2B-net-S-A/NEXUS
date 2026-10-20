"""Rozliczenie zgód (0486) — reguły bez bazy: porównanie z progiem 10%,
odnowienie subskrypcji, odczyt dokumentu przez AI, metadane KSeF. Dane fikcyjne (repo jest publiczne)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.hr_approval import ApprovalDocument, ApprovalRequest
from app.services import hr_approval_settlement_schema as schema
from app.services.hr.approvals import cost_invoices, reader, settlement

# NIP z poprawną sumą kontrolną (fikcyjny).
NIP = "1234563218"


def _request(amount: str = "1000", **kw) -> ApprovalRequest:
    values = dict(
        kind="training",
        status="approved",
        amount=Decimal(amount),
        currency="PLN",
        amount_basis="gross",
        recurrence="once",
    )
    values.update(kw)
    return ApprovalRequest(**values)


def _doc(gross: str | None, **kw) -> ApprovalDocument:
    values = dict(
        status="pinned",
        currency="PLN",
        gross_amount=Decimal(gross) if gross is not None else None,
    )
    values.update(kw)
    return ApprovalDocument(**values)


# ── porównanie z kwotą zgody ───────────────────────────────────────────────


def test_invoice_up_to_ten_percent_over_fits() -> None:
    request = _request("1000")
    result = settlement.compare(request, [_doc("1100")])
    assert result.status == "fits"
    assert result.limit == Decimal("1100.00")


def test_invoice_more_than_ten_percent_over_needs_a_topup() -> None:
    request = _request("1000")
    result = settlement.compare(request, [_doc("1180")])
    assert result.status == "over"
    assert result.excess == Decimal("180")
    assert result.percent == 18


def test_once_sums_all_documents_of_the_request() -> None:
    request = _request("1000", kind="trip")
    docs = [_doc("600"), _doc("450")]
    assert settlement.compare(request, docs).status == "fits"
    docs.append(_doc("100"))
    assert settlement.compare(request, docs).status == "over"


def test_approved_topup_raises_the_limit() -> None:
    request = _request("1000")
    doc = _doc("1180", topup_status="approved", topup_amount=Decimal("180"))
    assert settlement.compare(request, [doc]).status == "fits"


def test_decided_amount_wins_over_requested_amount() -> None:
    request = _request("1000", decided_amount=Decimal("800"))
    assert settlement.compare(request, [_doc("1000")]).status == "over"


def test_net_basis_compares_net_amounts() -> None:
    request = _request("1000", amount_basis="net")
    doc = _doc("1353", net_amount=Decimal("1100"), vat_amount=Decimal("253"))
    assert settlement.compare(request, [doc]).status == "fits"


def test_other_currency_or_missing_amount_is_unknown() -> None:
    request = _request("1000")
    assert (
        settlement.compare(request, [_doc("900", currency="EUR")]).status == "unknown"
    )
    assert settlement.compare(request, [_doc(None)]).status == "unknown"
    assert settlement.compare(request, []).status == "unknown"


def test_recurring_compares_each_invoice_alone() -> None:
    request = _request("240", kind="subscription", recurrence="monthly")
    first, second = _doc("240"), _doc("290")
    docs = [first, second]
    assert settlement.compare(request, docs, doc=first).status == "fits"
    over = settlement.compare(request, docs, doc=second)
    assert over.status == "over" and over.percent == 21


def test_unmatched_documents_do_not_count_for_the_request() -> None:
    request = _request("1000")
    docs = [_doc("900"), _doc("5000", status="unmatched")]
    assert settlement.compare(request, docs).status == "fits"


# ── odnowienie subskrypcji rocznej ─────────────────────────────────────────


def test_first_renewal_is_next_anniversary_after_today() -> None:
    today = date(2026, 10, 20)
    assert settlement.first_renewal(date(2026, 11, 1), today) == date(2027, 11, 1)
    assert settlement.first_renewal(date(2025, 3, 1), today) == date(2027, 3, 1)
    assert settlement.first_renewal(None, today) == date(2027, 10, 20)


def test_first_renewal_from_29_february() -> None:
    assert settlement.first_renewal(date(2024, 2, 29), date(2024, 3, 1)) == date(
        2025, 2, 28
    )


# ── odczyt dokumentu przez AI ──────────────────────────────────────────────


def test_reader_parses_amounts_seller_and_nip() -> None:
    reply = (
        'Oto dane: {"doc_type": "invoice", "seller_name": "Sklep  Testowy", '
        f'"seller_nip": "PL{NIP}", "invoice_number": "FV 7/10/2026", '
        '"issue_date": "2026-10-15", "currency": "pln", "net_amount": "935,77", '
        '"vat_amount": 215.23, "gross_amount": "1 151,00"}'
    )
    result = reader.parse_reply(reply)
    assert result.status == "read"
    assert result.fields["seller_nip"] == NIP
    assert result.fields["seller_name"] == "Sklep Testowy"
    assert result.fields["gross_amount"] == "1151.00"
    assert result.fields["net_amount"] == "935.77"
    assert result.fields["currency"] == "PLN"
    assert result.fields["issue_date"] == "2026-10-15"


def test_reader_drops_bad_nip_and_bad_date() -> None:
    result = reader.parse_reply(
        '{"seller_nip": "1234567890", "issue_date": "15.10.2026", "gross_amount": 10}'
    )
    assert result.status == "read"
    assert result.fields["seller_nip"] is None
    assert result.fields["issue_date"] is None


def test_reader_without_gross_or_json_fails() -> None:
    assert reader.parse_reply('{"seller_name": "X"}').status == "failed"
    assert reader.parse_reply("nie umiem").status == "failed"
    assert reader.parse_reply('{"gross_amount": -5}').status == "failed"


@pytest.mark.asyncio
async def test_reader_model_failure_is_failed_not_an_error(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("model padł")

    monkeypatch.setattr(reader, "_call_model", boom)
    result = await reader.read_document(b"%PDF-1.4", "application/pdf")
    assert result.status == "failed"


# ── faktury kosztowe z metadanych KSeF ─────────────────────────────────────


def test_cost_invoice_fields_from_metadata() -> None:
    fields = cost_invoices.fields_from_metadata(
        {
            "invoiceNumber": "FV 12/2026",
            "issueDate": "2026-10-17",
            "seller": {"nip": NIP, "name": "Dostawca Testowy sp. z o.o."},
            "netAmount": 2000.0,
            "vatAmount": 460.0,
            "grossAmount": 2460.0,
            "currency": "PLN",
            "invoiceType": "Vat",
        }
    )
    assert fields["seller_nip"] == NIP
    assert fields["gross_amount"] == Decimal("2460.00")
    assert fields["issue_date"] == date(2026, 10, 17)
    assert fields["ksef_invoice_type"] == "Vat"


def test_cost_invoice_without_amount_or_nip_is_skipped() -> None:
    assert cost_invoices.fields_from_metadata({"seller": {"nip": NIP}}) is None
    assert cost_invoices.fields_from_metadata({"seller": {}, "grossAmount": 10}) is None


# ── schemat i skrót ────────────────────────────────────────────────────────


def test_schema_ddl_carries_every_named_check() -> None:
    table = schema.DOCUMENTS_TABLE
    for name in (
        "ck_approval_documents_origin",
        "ck_approval_documents_attached",
        "ck_approval_documents_topup",
        "ck_approval_documents_settled",
    ):
        assert name in table
    assert "{10}" in schema.FIXED_SELLERS_TABLE
    assert all("IF NOT EXISTS" in stmt for stmt in schema.COLUMN_DDL)
