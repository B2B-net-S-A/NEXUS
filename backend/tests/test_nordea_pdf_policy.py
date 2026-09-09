"""Nordea PDF: netto/h, bez Quantity i summary. Wyłącznie dane syntetyczne."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import order_mail_ingest as ingest
from app.services.order_client_identity import ClientIdentification, ClientRegistry
from app.services.order_document_text import OrderDocumentText
from app.services.order_mail_gate import GateInput, evaluate
from app.services.order_mail_planner import plan_document
from app.services.order_mail_resolver import RosterContract, RosterPerson, resolve_rows
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction
from app.services.order_policies import (
    PolicyContext,
    active_policies,
    apply_policies,
    apply_rate_kind,
    policy_by_key,
    prepare_document_text,
    prepare_parser_text,
)
from app.services.order_policies import nordea

ORDER = """Call Off Agreement
Nordea Bank Abp
Frame Agreement number: CW2117535
Call Off Agreement number: 277157
Initial Term
Start date End date
2031-04-01 2031-11-30
Person(s) at the Supplier who Competence Category Location Quantity (max Unit Rate Subtotal
it is intended to perform the (according to Nordea 160h/month)
service definitions)
Jan Testowy IT Operations - Senior Poland - 1 728 Hours 175,00 PLN 300 000,00 PLN
Total, excl. VAT 300 000,00 PLN
"""
SUMMARY = """Summary
Call Off Agreement number: 999999
Start date End date
2032-01-01 2032-12-31
Jan Testowy IT Operations - Senior Poland - 999 Days 999,00 PLN 998 001,00 PLN
Anna Podsumowanie IT Operations - Senior Poland - 999 Days 999,00 PLN 998 001,00 PLN
"""
POLICIES = [policy_by_key("nordea")]


def model_extraction(reason="Nie ustalono, czy stawka jest brutto czy netto"):
    return OrderExtraction(
        title="277157",
        start_date="2031-04-01",
        end_date="2031-11-30",
        rate_client=Decimal("175"),
        rate_unit="day",
        md_total=Decimal("216"),
        consultant_rows=[
            ConsultantOrderRow(
                consultant_name="Jan Testowy",
                rate_client=Decimal("175"),
                rate_unit="day",
                md_total=Decimal("216"),
                uncertain=bool(reason),
                uncertain_reason=reason or None,
            )
        ],
        uncertain=bool(reason),
        uncertain_reasons=[reason] if reason else [],
        source="claude",
    )


@pytest.mark.parametrize("unit", ["Hours", "Days", "Months", "MD", "h"])
@pytest.mark.parametrize("quantity", ["1 728", "0", "999 999", "—"])
def test_quantity_unit_and_subtotal_do_not_affect_the_hourly_net_rate(unit, quantity):
    text = ORDER.replace("1 728 Hours", f"{quantity} {unit}")
    row = nordea.extract_rows(text)[0]
    assert row.rate_client == Decimal("175.00")
    assert row.rate_unit == "hour"
    assert row.md_total is None
    assert row.rate_client_gross is None
    assert not row.uncertain


def test_blank_quantity_does_not_block_reading_the_rate():
    text = ORDER.replace("Poland - 1 728 Hours", "Warsaw Hours")
    row = nordea.extract_rows(text)[0]
    assert row.rate_client == Decimal("175.00")
    assert row.rate_unit == "hour"
    assert row.md_total is None
    assert not row.uncertain


@pytest.mark.parametrize(
    "reason",
    [
        "Nie ustalono, czy stawka jest brutto czy netto",
        "Niepewny odczyt: liczba MD",
        "Ilość × stawka ≠ Subtotal — sprawdź wiersz",
        "Quantity (max 160h/month) nie jest jednoznaczne",
        "Stawka może być w innej jednostce niż miesięczna — sprawdź przeliczenie",
        "Nie podano jednoznacznie, czy stawka i wartość całkowita są netto czy brutto (tabela mówi 'excl. VAT', ale nagłówek kolumny 'Unit Rate' nie ma wprost oznaczenia netto/brutto).",
        "Quantity (920) opisana jako 'Hours', co potraktowano jako liczbę godzin, a nie jednoznaczne MD — pole md_total może nie odpowiadać dokładnie definicji roboczodni.",
    ],
)
def test_only_nordea_bypasses_vat_detection_and_clears_its_resolved_reasons(
    monkeypatch, reason
):
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "77")
    detector = Mock(side_effect=AssertionError("Nordea must not detect VAT"))
    monkeypatch.setattr(
        "app.services.order_pdf_parser.detect_rate_gross_marking", detector
    )
    ex = model_extraction(reason)
    ex.confidence["md_total"] = 0.2
    apply_rate_kind(ex, "Stawka 175,00 PLN brutto", active_policies(77))
    apply_rate_kind(ex, "Stawka 175,00 PLN brutto", active_policies(77))
    for item in [ex, *ex.consultant_rows]:
        assert item.rate_client == Decimal("175")
        assert item.rate_unit == "hour"
        assert item.md_total is None
        assert item.rate_client_gross is None
        assert not item.uncertain
    assert "md_total" not in ex.confidence
    assert ex.uncertain_reasons == []
    detector.assert_not_called()


@pytest.mark.parametrize("client_id", [None, 78])
def test_fixed_rule_does_not_leak_to_other_clients(monkeypatch, client_id):
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "77")
    ex = model_extraction("")
    apply_rate_kind(ex, "Stawka 175,00 PLN brutto", active_policies(client_id))
    assert ex.rate_client == Decimal("142.28")
    assert ex.rate_client_gross == Decimal("175")
    assert ex.rate_unit == "day"
    assert ex.md_total == Decimal("216")
    assert (
        prepare_document_text(ORDER + SUMMARY, active_policies(client_id))
        == ORDER + SUMMARY
    )


@pytest.mark.parametrize(
    "reason",
    [
        "Nieczytelna stawka netto",
        "Sprzeczne kwoty netto",
        "Nie ustalono, czy stawka jest brutto czy netto; Nieczytelna data końca",
        "Nie ustalono, czy stawka jest brutto czy netto, a okres jest sprzeczny",
        "Nieczytelny numer VAT klienta",
        "Nie znaleziono stawki",
    ],
)
def test_unrelated_uncertainty_is_still_reviewed(reason):
    ex = model_extraction(reason)
    ex, _ = apply_policies(ex, PolicyContext(document_text=ORDER), POLICIES)
    assert ex.uncertain
    assert ex.consultant_rows[0].uncertain
    assert ex.uncertain_reasons


@pytest.mark.parametrize("separator", ["\n", "\f", "\r\n"])
@pytest.mark.parametrize(
    "heading", ["Summary", "Order Summary", "Certificate of Completion"]
)
def test_summary_is_excluded_before_all_consumers(separator, heading):
    text = ORDER + separator + SUMMARY.replace("Summary", heading, 1)
    filtered = prepare_document_text(text, POLICIES)
    assert filtered == ORDER.rstrip()
    assert nordea.order_text_only(filtered) == filtered
    assert [r.consultant_name for r in nordea.extract_rows(text)] == ["Jan Testowy"]
    model_text = prepare_parser_text(filtered, POLICIES)
    assert "1 728" not in model_text
    assert "Quantity" not in model_text
    assert "160h/month" not in model_text
    assert "175,00 PLN/hour netto" in model_text
    assert "999,00" not in model_text
    assert "Anna Podsumowanie" not in model_text


def test_leading_summary_is_skipped_and_ordinary_summary_word_is_preserved():
    assert nordea.order_text_only(SUMMARY + "\f" + ORDER) == ORDER
    text = ORDER + "Service description: produce a summary every month.\n"
    assert nordea.order_text_only(text) == text
    assert nordea.order_text_only(SUMMARY) == ""


@pytest.mark.parametrize(
    "target,matched", [("Jan Testowy", True), ("Anna Obca", False)]
)
def test_targeted_extract_still_requires_the_requested_person(target, matched):
    ex = model_extraction()
    ex, _ = apply_policies(
        ex, PolicyContext(document_text=ORDER, target_consultant=target), POLICIES
    )
    assert ex.consultant_rate_matched is matched
    assert ex.rate_client == (Decimal("175") if matched else None)
    assert ex.uncertain is (not matched)


def gate_for(ex, doc):
    roster = [
        RosterPerson(1, "Jan", "Testowy", (RosterContract(10, "active", None, None),))
    ]
    resolved = resolve_rows(ex.consultant_rows, roster)
    proposal = plan_document(
        client_id=77,
        extraction=ex,
        resolved=resolved,
        existing_orders_by_contract={},
        is_group_client=False,
        today=date(2031, 3, 1),
    )
    verdict = evaluate(
        GateInput(
            identification_method="registry_id",
            policies_applied=("Nordea",),
            extraction=ex,
            document_truncated=False,
            ocr_capped=False,
            resolved=tuple(resolved),
            proposal=proposal,
            deterministic_rows=tuple(nordea.extract_rows(doc.text)),
            current_rates={10: (Decimal("175"), "hour")},
            autoapply_enabled=False,
        )
    )
    return verdict, proposal


@pytest.mark.asyncio
async def test_mail_pipeline_excludes_summary_and_builds_auto_proposal(monkeypatch):
    from app.services import order_mail_apply as writer
    from app.services.order_mail_apply import ApplyResult

    apply = AsyncMock(return_value=ApplyResult())
    monkeypatch.setattr(writer, "apply_document", apply)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "77")
    monkeypatch.setattr(ingest.settings, "ORDER_MAIL_AUTOAPPLY_ENABLED", False)
    doc = OrderDocumentText(ORDER + SUMMARY, 4, False, False, None, 0.0)
    monkeypatch.setattr(ingest, "extract_order_text", lambda *args: doc)
    monkeypatch.setattr(
        ingest,
        "identify_client",
        lambda *a, **k: ClientIdentification(client_key="77", method="registry_id"),
    )
    parser = AsyncMock(return_value=model_extraction())
    monkeypatch.setattr(ingest, "parse_order_document", parser)

    async def planner(db, row, ex, document, policies, client_id, method):
        verdict, proposal = gate_for(ex, document)
        row.gate_verdict = verdict.verdict
        row.gate_reasons = verdict.reasons
        assert verdict.is_auto, verdict.reasons
        assert len(proposal.rows) == 1
        assert proposal.rows[0].rate_client == "175"
        assert proposal.rows[0].rate_unit == "hour"
        assert proposal.rows[0].md_total is None
        assert proposal.order_number == "277157"

    monkeypatch.setattr(ingest, "_plan_and_gate", planner)
    row = SimpleNamespace(attachment_name="order.pdf", sender_email="a@nordea.com")
    await ingest.process_pdf_bytes(
        AsyncMock(), row, b"%PDF-dummy", registry=ClientRegistry({})
    )
    apply.assert_awaited_once()
    sent = parser.call_args.args[0]
    assert "Summary" not in sent and "Quantity" not in sent and "999,00" not in sent
    assert row.gate_verdict == "auto"
    assert row.gate_reasons == []


def test_remaining_error_still_blocks_auto_proposal():
    ex, _ = apply_policies(
        model_extraction("Nieczytelna data końca"),
        PolicyContext(document_text=ORDER),
        POLICIES,
    )
    verdict, _ = gate_for(ex, SimpleNamespace(text=ORDER))
    assert not verdict.is_auto
    assert any("Nieczytelna data końca" in reason for reason in verdict.reasons)


def test_unexplained_model_uncertainty_is_not_erased():
    ex = model_extraction("")
    ex.uncertain = True
    ex, _ = apply_policies(ex, PolicyContext(document_text=ORDER), POLICIES)
    verdict, _ = gate_for(ex, SimpleNamespace(text=ORDER))
    assert not verdict.is_auto


@pytest.mark.asyncio
async def test_refresh_uses_order_rows_and_restores_raw_net_amount(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "77")
    old = model_extraction()
    old.rate_client = Decimal("142.28")
    old.rate_client_gross = Decimal("175")
    old.consultant_rows += deepcopy(old.consultant_rows)
    old.consultant_rows[1].consultant_name = "Anna Podsumowanie"
    saved = ingest.extraction_to_json(old)
    row = SimpleNamespace(
        client_id=77,
        extraction=saved,
        storage_path="order.pdf",
        attachment_name="order.pdf",
        identification_method="registry_id",
        error="old",
    )
    doc = OrderDocumentText(ORDER + SUMMARY, 4, False, False, None, 0.0)
    monkeypatch.setattr(ingest, "extract_order_text", lambda *a: doc)
    monkeypatch.setattr(
        ingest.storage_service, "get_order_mail_attachment_path", lambda p: tmp_path / p
    )
    parser = AsyncMock(side_effect=AssertionError("Refresh must not call the model"))
    monkeypatch.setattr(ingest, "parse_order_document", parser)
    planner = AsyncMock()
    monkeypatch.setattr(ingest, "_plan_and_gate", planner)
    await ingest.refresh_review_plan(AsyncMock(), row)
    await ingest.refresh_review_plan(AsyncMock(), row)
    assert Decimal(row.extraction["rate_client"]) == Decimal("175")
    assert row.extraction["rate_client_gross"] is None
    assert row.extraction["md_total"] is None
    assert [r["consultant_name"] for r in row.extraction["consultant_rows"]] == [
        "Jan Testowy"
    ]
    for field in ("title", "start_date", "end_date"):
        assert row.extraction[field] == saved[field]
    parser.assert_not_called()
