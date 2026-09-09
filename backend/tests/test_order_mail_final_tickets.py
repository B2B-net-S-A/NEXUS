"""Regression examples from the final September tickets; no live data or LLM."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest

from app.services.order_mail_gate import evaluate
from app.services.order_mail_planner import ExistingOrder, plan_document
from app.services.order_mail_resolver import RosterContract, RosterPerson, resolve_rows
from app.services.order_pdf_parser import (
    OrderExtraction,
    ConsultantOrderRow,
    apply_pfron_order_policy,
)
from app.services.order_policies.nordea import non_order_reason, apply_rate_rules
from tests.test_order_mail_gate_and_planner import _gate_input

PFRON = """ZLECENIE NA USŁUGI OUTSOURCING SPECJALISTÓW IT
Imię i nazwisko: Konrad Kozłowski – Administrator Itunes
Stawka za jedną Roboczogodzinę (zgodna z Ofertą Wykonawcy): 172,20 zł brutto
Data rozpoczęcia wykonywania Prac przez Specjalistę: 01.09.2026 r.
Okres realizacji Prac przez Specjalistę: do 160 RBH miesięcznie (z możliwością zmiany)
Termin wykonania Prac 30.11.2026r. z możliwością przedłużenia do 31.12.2028
"""
CERTIFICATE = """Certificate Of Completion
Envelope Id: abc Status: Completed
Subject: 286499 - IT Operations
Record Tracking
Holder: Nordea
Signer Events Signature Timestamp
"""
ORDER = """Call Off Agreement
Call Off Agreement number: 286380
Initial Term
Start date End date
2026-10-08 2027-01-31
Maciej Sobczyk Data Analyst Poland - 1 728 Hours 130,00 PLN
"""


def test_pfron_22_source_fields_override_old_model_and_are_idempotent():
    old = OrderExtraction(
        title="22",
        start_date="2026-01-01",
        end_date="2028-12-31",
        rate_client=Decimal("172.20"),
        md_total=Decimal("160"),
        source="claude",
        consultant_rows=[
            ConsultantOrderRow(
                consultant_name="Konrad Kozłowski – Administrator Itunes"
            )
        ],
        uncertain=True,
        uncertain_reasons=[
            "Stawka podana jako brutto, nie netto - niejednoznaczne przeliczenie"
        ],
    )
    for _ in range(2):
        result = apply_pfron_order_policy(
            old, PFRON, filename="Zlecenie nr 22 Konrad Kozłowski pk-sig.pdf"
        )
        assert result.title == "Zlecenie nr 22"
        assert (result.start_date, result.end_date) == ("2026-09-01", "2026-11-30")
        assert result.rate_client == Decimal("140.00")
        assert result.rate_client_gross == Decimal("172.20")
        assert result.md_total is None
        assert not result.uncertain, result.uncertain_reasons
        row = result.consultant_rows[0]
        assert row.consultant_name == "Konrad Kozłowski"
        assert row.start_date == "2026-09-01" and row.end_date == "2026-11-30"
        assert row.rate_client == Decimal("140.00") and not row.uncertain


def test_pfron_independent_concern_remains():
    old = OrderExtraction(
        uncertain=True, uncertain_reasons=["Sprzeczne numery NIP zamawiającego"]
    )
    result = apply_pfron_order_policy(old, PFRON, filename="Zlecenie nr 22.pdf")
    assert result.uncertain and result.uncertain_reasons == [
        "Sprzeczne numery NIP zamawiającego"
    ]


@pytest.mark.parametrize(
    "text", [CERTIFICATE, "", "A signature audit trail without procurement details"]
)
def test_nordea_non_orders_are_classified_by_content(text):
    assert non_order_reason(text)


@pytest.mark.parametrize("text", [ORDER, ORDER + CERTIFICATE, CERTIFICATE + ORDER])
def test_certificate_does_not_drop_the_order_from_a_combined_document(text):
    assert non_order_reason(text) is None


def test_286380_optional_quantity_remark_is_not_a_review_reason():
    result = OrderExtraction(
        uncertain=True,
        uncertain_reasons=[
            "można by je wyliczyć z kwoty i stawki, ale to niedozwolone",
            "Sprzeczne daty okresu zamówienia",
        ],
    )
    apply_rate_rules(result)
    assert result.uncertain_reasons == ["Sprzeczne daty okresu zamówienia"]


def plan(statuses, orders, name="Bartłomiej Okraszewski"):
    row = ConsultantOrderRow(
        consultant_name=name,
        rate_client=Decimal("163"),
        rate_unit="hour",
        start_date="2026-09-16",
        end_date="2027-02-28",
        uncertain=False,
    )
    ex = OrderExtraction(
        title="286506",
        consultant_rows=[row],
        source="claude",
        uncertain=False,
        confidence={"title": 1.0},
    )
    roster = (
        [
            RosterPerson(
                10,
                "Bartłomiej",
                "Okraszewski",
                tuple(
                    RosterContract(cid, status, date(2026, 1, 1), date(2026, 8, 15))
                    for cid, status in statuses
                ),
            )
        ]
        if statuses
        else []
    )
    resolved = resolve_rows([row], roster)
    prop = plan_document(
        client_id=1,
        extraction=ex,
        resolved=resolved,
        existing_orders_by_contract=orders,
        is_group_client=False,
        today=date(2026, 9, 9),
    )
    verdict = evaluate(
        _gate_input(
            extraction=ex,
            resolved=tuple(resolved),
            proposal=prop,
            deterministic_rows=(row,),
            current_rates={},
        )
    )
    return prop, verdict


def test_286506_fills_named_recruitment_draft_with_start_date():
    prop, verdict = plan(
        [(652, "draft")],
        {
            652: [
                ExistingOrder(
                    611,
                    "draft",
                    "Bartłomiej Okraszewski — Nordea: PL - MDM",
                    date(2026, 9, 16),
                    None,
                )
            ]
        },
    )
    assert prop.rows[0].action == "fill_draft" and prop.rows[0].target_order_id == 611
    assert verdict.is_auto, verdict.reasons


def test_new_person_is_normal_initial_draft():
    prop, verdict = plan([], {})
    assert prop.rows[0].action == "new_draft" and verdict.is_auto


def test_ending_contract_wins_over_draft():
    prop, verdict = plan(
        [(652, "draft"), (653, "ending")],
        {
            652: [
                ExistingOrder(
                    611, "draft", "Draft next period", date(2026, 9, 16), None
                )
            ],
            653: [
                ExistingOrder(
                    612, "active", "old order", date(2026, 1, 1), date(2026, 9, 15)
                )
            ],
        },
    )
    assert prop.rows[0].contract_id == 653 and prop.rows[0].action == "future"
    assert verdict.is_auto


def test_completed_order_reused_even_with_same_number_and_actual_gap():
    prop, verdict = plan(
        [(652, "ended")],
        {
            652: [
                ExistingOrder(
                    611, "completed", "286506", date(2026, 1, 1), date(2026, 8, 15)
                )
            ]
        },
    )
    assert prop.rows[0].action == "reactivate" and prop.rows[0].target_order_id == 611
    assert prop.rows[0].reasons == [
        "Powrót po 32 dniach od zakończenia poprzedniego zamówienia"
    ]
    assert verdict.is_auto


def test_real_overlap_remains_a_specific_problem():
    prop, verdict = plan(
        [(652, "active")],
        {
            652: [
                ExistingOrder(
                    611, "active", "older", date(2026, 1, 1), date(2026, 12, 31)
                )
            ]
        },
    )
    assert prop.rows[0].action == "overlap" and not verdict.is_auto
    assert any("611" in r for r in verdict.reasons)


@pytest.mark.asyncio
async def test_nordea_certificate_skipped_before_parser_and_non_nordea_unchanged(
    monkeypatch,
):
    from app.services import order_mail_ingest as svc
    from app.services.order_document_text import OrderDocumentText
    from app.services.order_policies.registry import policy_by_key

    monkeypatch.setattr(
        svc,
        "extract_order_text",
        lambda *a: OrderDocumentText(
            text=CERTIFICATE,
            page_count=1,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0,
        ),
    )
    monkeypatch.setattr(
        svc,
        "identify_client",
        lambda *a, **kw: SimpleNamespace(
            method="registry_id", reason="NIP", client_key="nordea"
        ),
    )
    monkeypatch.setattr(
        svc, "resolve_order_client_id", AsyncMock(return_value=(1, "nordea"))
    )
    monkeypatch.setattr(svc, "active_policies", lambda cid: [policy_by_key("nordea")])
    parser = AsyncMock(return_value=OrderExtraction())
    monkeypatch.setattr(svc, "parse_order_document", parser)
    monkeypatch.setattr(svc, "_plan_and_gate", AsyncMock())
    row = SimpleNamespace(
        attachment_name="arbitrary.pdf",
        sender_email="orders@nordea.com",
        gate_verdict=None,
    )
    await svc.process_pdf_bytes(AsyncMock(), row, b"synthetic", registry=None)
    assert row.outcome == "dismissed" and row.extraction is None
    parser.assert_not_awaited()
    monkeypatch.setattr(svc, "active_policies", lambda cid: [])
    await svc.process_pdf_bytes(AsyncMock(), row, b"synthetic", registry=None)
    parser.assert_awaited_once()


@pytest.mark.asyncio
async def test_286408_auto_verdict_calls_writer_even_when_old_shadow_flag_false(
    monkeypatch,
):
    from app.services import order_mail_ingest as svc, order_mail_apply as writer
    from app.services.order_document_text import OrderDocumentText

    monkeypatch.setattr(svc.settings, "ORDER_MAIL_AUTOAPPLY_ENABLED", False)
    monkeypatch.setattr(
        svc,
        "extract_order_text",
        lambda *a: OrderDocumentText(
            text=ORDER,
            page_count=1,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0,
        ),
    )
    monkeypatch.setattr(
        svc,
        "identify_client",
        lambda *a, **kw: SimpleNamespace(
            method="registry_id", reason="NIP", client_key="test"
        ),
    )
    monkeypatch.setattr(
        svc, "resolve_order_client_id", AsyncMock(return_value=(1, "test"))
    )
    monkeypatch.setattr(svc, "active_policies", lambda cid: [])
    monkeypatch.setattr(
        svc, "parse_order_document", AsyncMock(return_value=OrderExtraction())
    )

    async def gate(db, row, *args):
        row.gate_verdict = "auto"

    monkeypatch.setattr(svc, "_plan_and_gate", gate)
    apply = AsyncMock(return_value=writer.ApplyResult())
    monkeypatch.setattr(writer, "apply_document", apply)
    row = SimpleNamespace(
        attachment_name="286408.pdf", sender_email="orders@example.com"
    )
    db = AsyncMock()
    db.add = lambda row: None
    await svc.process_pdf_bytes(db, row, b"synthetic", registry=None)
    assert row.outcome == "auto_applied"
    apply.assert_awaited_once()
    db.flush.assert_awaited_once()
