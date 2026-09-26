"""Nordea PDF: netto/h, bez Quantity i summary. Wyłącznie dane syntetyczne."""

import re
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
from tests.conftest import db_without_client_merges

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
@pytest.mark.parametrize("autoapply", [True, False])
async def test_mail_pipeline_excludes_summary_and_builds_auto_proposal(
    monkeypatch, autoapply
):
    from app.services import order_mail_apply as writer
    from app.services.order_mail_apply import ApplyResult

    apply = AsyncMock(return_value=ApplyResult())
    monkeypatch.setattr(writer, "apply_document", apply)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "77")
    # Wyłącznik automatu jest czytany od 10.09.2026: przy False pewny plan
    # zostaje w kolejce, a writer nie jest wołany.
    monkeypatch.setattr(ingest.settings, "ORDER_MAIL_AUTOAPPLY_ENABLED", autoapply)
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
        assert Decimal(proposal.rows[0].rate_client) == Decimal("175")
        assert proposal.rows[0].rate_unit == "hour"
        assert proposal.rows[0].md_total is None
        assert proposal.order_number == "277157"

    monkeypatch.setattr(ingest, "_plan_and_gate", planner)
    row = SimpleNamespace(attachment_name="order.pdf", sender_email="a@nordea.com")
    await ingest.process_pdf_bytes(
        AsyncMock(), row, b"%PDF-dummy", registry=ClientRegistry({})
    )
    assert parser.call_args.kwargs == {"all_rows": True}
    sent = parser.call_args.args[0]
    assert "Summary" not in sent and "Quantity" not in sent and "999,00" not in sent
    if autoapply:
        apply.assert_awaited_once()
        assert row.gate_verdict == "auto"
        assert row.gate_reasons == []
    else:
        apply.assert_not_awaited()
        assert row.outcome == "needs_review"
        assert row.gate_verdict == "review"
        assert row.gate_reasons == [ingest.AUTOAPPLY_DISABLED_REASON]


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
    await ingest.refresh_review_plan(db_without_client_merges(), row)
    await ingest.refresh_review_plan(db_without_client_merges(), row)
    assert Decimal(row.extraction["rate_client"]) == Decimal("175")
    assert row.extraction["rate_client_gross"] is None
    assert row.extraction["md_total"] is None
    assert [r["consultant_name"] for r in row.extraction["consultant_rows"]] == [
        "Jan Testowy"
    ]
    for field in ("title", "start_date", "end_date"):
        assert row.extraction[field] == saved[field]
    parser.assert_not_called()


# The screenshots supply a second real layout; identities are regression data
# supplied by the user, not looked up from unrelated production records.
JAKUB = (
    ORDER.replace("277157", "286471")
    .replace("Jan Testowy", "Jakub Górecki")
    .replace("2031-04-01", "2026-09-09")
    .replace("2031-11-30", "2026-11-26")
    .replace("175,00", "160,00")
)


@pytest.mark.parametrize("total", ["300 000,00", "999 999,99", "NIE CZYTELNE"])
def test_nordea_five_field_projection_never_sends_totals_to_model(total):
    original = JAKUB + "\nContact persons\nNot Consultant\nStart date: 2099-01-01\n"
    projected = prepare_parser_text(original.replace("300 000,00", total), POLICIES)
    assert projected == prepare_parser_text(original, POLICIES)
    assert not re.search(r"^\s*total", projected, re.I | re.M)
    assert "300 000,00" not in projected
    assert "2099" not in projected
    assert "Not Consultant" not in projected
    assert "286471" in projected and "160,00 PLN/hour netto" in projected
    assert "2026-09-09" in projected and "2026-11-26" in projected


@pytest.mark.parametrize(
    "reason",
    [
        "Nieczytelne Total_value: brak kwoty",
        "Total, excl. VAT nie jest przypisane jako total_value pola dokumentu",
        "Subtotal nie pasuje do okresu zamówienia",
        "Total_value nie odpowiada iloczynowi stawki i ilości",
    ],
)
def test_nordea_totals_are_discarded_even_when_extracted_or_uncertain(reason):
    ex = model_extraction(reason)
    ex.total_value = Decimal("999999")
    ex.confidence["total_value"] = 0.99
    ex, _ = apply_policies(ex, PolicyContext(document_text=ORDER), POLICIES)
    assert ex.total_value is None
    assert "total_value" not in ex.confidence
    assert not ex.uncertain
    assert not ex.consultant_rows[0].uncertain
    assert ex.uncertain_reasons == []
    ex.uncertain_reasons = [reason + "; Nieczytelna stawka konsultanta"]
    ex.uncertain = True
    nordea.apply_rate_rules(ex)
    assert ex.uncertain_reasons == ["Nieczytelna stawka konsultanta"]


def test_nordea_initial_term_is_the_only_date_source():
    assert nordea.initial_term("Start date End date\n2099-01-01 2099-12-31") == (
        None,
        None,
    )
    assert nordea.initial_term(
        "Initial Term\nStart date: 2026-09-09\nEnd date: 2026-11-26\nMiscellaneous\nStart date End date\n2099-01-01 2099-12-31"
    ) == ("2026-09-09", "2026-11-26")


@pytest.mark.asyncio
async def test_nordea_create_fill_extend_use_the_same_all_rows_parser_as_mail(
    monkeypatch,
):
    from app.api import client_orders
    from app.services.order_policies import parse_plan
    from app.services.order_pdf_parser import parse_order_document
    from app.services import order_pdf_parser as parser_module

    text = JAKUB.replace(
        "Total, excl.",
        "Anna Druga IT Developer Poland - 100 Hours 234,00 PLN 23 400,00 PLN\nTotal, excl.",
    )
    rows = nordea.extract_rows(text)
    assert [(r.consultant_name, r.rate_client) for r in rows] == [
        ("Jakub Górecki", Decimal("160")),
        ("Anna Druga", Decimal("234")),
    ]
    model = AsyncMock(
        return_value=OrderExtraction(
            title="286471", consultant_rows=rows, source="claude", uncertain=False
        )
    )
    monkeypatch.setattr(parser_module, "_extract_all_rows_with_claude", model)
    monkeypatch.setattr(
        parser_module,
        "_extract_with_claude",
        AsyncMock(
            side_effect=AssertionError("Nordea must always read all consultants")
        ),
    )
    projected = prepare_parser_text(text, POLICIES)
    mail = await parse_order_document(projected, all_rows=True)
    mail, _ = apply_policies(
        deepcopy(mail), PolicyContext(document_text=text), POLICIES
    )
    for target in (None, "Jakub Górecki", "Anna Druga"):
        parsed = await client_orders._extract_with_plan(
            projected,
            plan=parse_plan(POLICIES),
            target_consultant=target,
            target_given_names=None,
        )
        parsed, _ = apply_policies(
            deepcopy(parsed),
            PolicyContext(document_text=text, target_consultant=target),
            POLICIES,
        )
        assert parsed.consultant_rows == mail.consultant_rows
        assert (
            parsed.title,
            parsed.start_date,
            parsed.end_date,
            parsed.total_value,
        ) == ("286471", "2026-09-09", "2026-11-26", None)
        assert (
            parsed.rate_client
            == {
                "Jakub Górecki": Decimal("160"),
                "Anna Druga": Decimal("234"),
                None: None,
            }[target]
        )
    assert model.await_count == 4
    assert all(call.args == (projected,) for call in model.call_args_list)


def test_model_row_name_disagreement_keeps_real_concern_after_table_override():
    ex = model_extraction("Nieczytelna stawka konsultanta")
    ex.consultant_rows[0].consultant_name = "J. Testowy"
    ex, _ = apply_policies(ex, PolicyContext(document_text=ORDER), POLICIES)
    assert ex.consultant_rows[0].consultant_name == "Jan Testowy"
    assert ex.uncertain
    assert "Nieczytelna stawka konsultanta" in ex.uncertain_reasons


def test_nordea_missing_table_is_reviewed_and_polish_total_warning_is_ignored():
    ex = model_extraction("Nieczytelna wartość całkowita zamówienia")
    ex, _ = apply_policies(
        ex, PolicyContext(document_text=ORDER.split("Person(s)")[0]), POLICIES
    )
    assert ex.consultant_rows == []
    assert ex.rate_client is None
    assert ex.uncertain_reasons == [
        "Nie znaleziono osób i stawek w tabeli Consultant(s)"
    ]


def test_only_consultant_table_supplies_people_even_when_other_sections_look_like_rows():
    decoy = "Anna Kontaktowa IT Developer Poland - 100 Hours 999,00 PLN\n"
    text = decoy + ORDER + "\nContact persons\n" + decoy
    assert [r.consultant_name for r in nordea.extract_rows(text)] == ["Jan Testowy"]
    assert "Anna Kontaktowa" not in nordea.parser_text(text)
    assert nordea.extract_rows(decoy) == []


# ── Audyt 24.09.2026, M11: stan „legacy” tylko dla odczytu po starej regule ──


_LEGACY_REASON = "odczyt zapisany przed zmianą reguły Nordei"


async def _refresh_saved(monkeypatch, tmp_path, *, client_policy, meta):
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "77")
    saved = model_extraction("")
    saved.rate_unit = "hour"
    saved.md_total = None
    saved.consultant_rows[0].rate_unit = "hour"
    saved.consultant_rows[0].md_total = None
    assert saved.model_rows is None
    row = SimpleNamespace(
        client_id=77,
        extraction=ingest.extraction_to_json(saved),
        storage_path="order.pdf",
        attachment_name="order.pdf",
        identification_method="registry_id",
        client_policy=client_policy,
        document_meta=meta,
        error=None,
    )
    doc = OrderDocumentText(ORDER, 4, False, False, None, 0.0)
    monkeypatch.setattr(ingest, "extract_order_text", lambda *a: doc)
    monkeypatch.setattr(
        ingest.storage_service, "get_order_mail_attachment_path", lambda p: tmp_path / p
    )
    monkeypatch.setattr(
        ingest,
        "parse_order_document",
        AsyncMock(side_effect=AssertionError("Refresh must not call the model")),
    )
    monkeypatch.setattr(ingest, "_plan_and_gate", AsyncMock())
    await ingest.refresh_review_plan(db_without_client_merges(), row)
    return row.extraction


@pytest.mark.asyncio
async def test_late_recognised_document_is_not_treated_as_a_pre_rule_reading(
    monkeypatch, tmp_path
):
    """Klienta rozpoznano dopiero przy ponownej weryfikacji: wiersze są PROSTO
    od modelu (reguła Nordei nigdy na nich nie działała). Trwały powód „odczyt
    sprzed zmiany reguły" blokował automat na zawsze."""
    refreshed = await _refresh_saved(
        monkeypatch,
        tmp_path,
        client_policy=None,
        meta={"policies_pending": True},
    )
    assert not any(_LEGACY_REASON in r for r in refreshed["uncertain_reasons"])
    # Odczyt modelu zachowany — kolejne „Przelicz plan" porównuje tabelę z nim.
    assert [r["consultant_name"] for r in refreshed["model_rows"]] == ["Jan Testowy"]


@pytest.mark.asyncio
async def test_reading_saved_by_the_old_nordea_rule_still_needs_a_human(
    monkeypatch, tmp_path
):
    """Zapis po starej regule: ``consultant_rows`` to już tabela — nie dowód."""
    refreshed = await _refresh_saved(
        monkeypatch,
        tmp_path,
        client_policy=policy_by_key("nordea").display_name,
        meta={},
    )
    assert any(_LEGACY_REASON in r for r in refreshed["uncertain_reasons"])


# ── Runda 6 audytu: tabela Consultant(s) nie może potwierdzać samej siebie ──

BROKEN_ROW = ORDER.replace(
    "Total, excl.",
    "Anna Druga IT Developer Poland - 100 Hours 234,00 PLN 23 400,00 PLN\n"
    "Piotr Trzeci IT Operations - Senior Poland - 1 728\n"
    "Hours 200,00 PLN 345 600,00 PLN\n"
    "Total, excl.",
)


def test_row_broken_by_pdfplumber_is_seen_by_the_model_and_blocks_auto():
    # pdfplumber łamie wiersz: ilość na końcu linii, jednostka i stawka w
    # następnej. Regex tabeli czyta 2 z 3 osób — model musi dostać surowy
    # fragment tabeli, a kontrola kompletności zatrzymać automat.
    assert [r.consultant_name for r in nordea.extract_rows(BROKEN_ROW)] == [
        "Jan Testowy",
        "Anna Druga",
    ]
    projected = prepare_parser_text(BROKEN_ROW, POLICIES)
    assert "Piotr Trzeci" in projected
    assert "Hours 200,00 PLN" in projected
    # Nawet gdy model przepisał tylko wyciąg (2 osoby), kontrola liczy stawki.
    ex = model_extraction("")
    ex.consultant_rows.append(
        ConsultantOrderRow(consultant_name="Anna Druga", rate_client=Decimal("234"))
    )
    ex, _ = apply_policies(ex, PolicyContext(document_text=BROKEN_ROW), POLICIES)
    assert ex.uncertain
    assert any("3 pozycje" in r and "2 wiersze" in r for r in ex.uncertain_reasons)


def test_model_reading_the_third_person_from_raw_table_is_reported():
    ex = model_extraction("")
    ex.consultant_rows += [
        ConsultantOrderRow(consultant_name="Anna Druga", rate_client=Decimal("234")),
        ConsultantOrderRow(consultant_name="Piotr Trzeci", rate_client=Decimal("200")),
    ]
    ex, _ = apply_policies(ex, PolicyContext(document_text=BROKEN_ROW), POLICIES)
    assert ex.uncertain
    assert any("Piotr Trzeci" in r for r in ex.uncertain_reasons)


def test_three_word_name_before_competence_column_is_uncertain():
    text = ORDER.replace("Jan Testowy IT", "Jan Kowalski Nowak IT")
    rows = nordea.extract_rows(text)
    assert len(rows) == 1
    assert rows[0].uncertain
    assert "Nowak" in rows[0].uncertain_reason
    ex = model_extraction("")
    ex.consultant_rows[0].consultant_name = "Jan Kowalski"
    ex, _ = apply_policies(ex, PolicyContext(document_text=text), POLICIES)
    assert ex.uncertain
    assert ex.consultant_rows[0].uncertain
    assert any("Nowak" in r for r in ex.uncertain_reasons)


def test_raw_table_fragment_hides_totals_and_row_subtotals():
    projected = nordea.parser_text(BROKEN_ROW)
    assert "345 600,00" not in projected
    assert "300 000,00" not in projected
    assert "Total, excl" not in projected
