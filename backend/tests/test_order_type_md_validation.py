"""Walidacja dopasowana do typu zamówienia: „brak MD" tylko tam, gdzie MD jest potrzebne.

Ticket 09.2026 (Polkomtel): zamówienie KOSZTOWE zgłaszało „brak informacji
o liczbie MD", bo model czyta PDF bez wiedzy o typie zamówienia. Zamówienie MD
podaje liczbę MD w jednym z dwóch wariantów — przy każdej osobie albo raz na
całe zamówienie — i żaden z nich nie jest brakiem. Czyste funkcje; lata 2031+.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.order_mail_gate import VERDICT_AUTO, GateInput, evaluate
from app.services.order_mail_planner import plan_document
from app.services.order_mail_resolver import MATCH_EXACT, ResolvedConsultant
from app.services.order_pdf_parser import (
    MD_SCOPE_ORDER,
    MD_SCOPE_PER_CONSULTANT,
    ConsultantOrderRow,
    OrderExtraction,
    drop_md_absence_reasons,
    is_md_absence_reason,
    md_scope,
)

TODAY = date(2031, 3, 3)


@pytest.mark.parametrize(
    "reason",
    [
        "Brak informacji o liczbie MD",
        "Nie znaleziono liczby MD (osobodni) w dokumencie",
        "Dokument nie podaje liczby MD dla konsultantów",
        "md_total missing — the document states no man-days",
        "Liczba roboczodni nie została podana",
    ],
)
def test_md_absence_reasons_are_recognised(reason):
    assert is_md_absence_reason(reason) is True


@pytest.mark.parametrize(
    "reason",
    [
        "Nie znaleziono jednoznacznej daty końca",
        "Nieczytelna liczba MD albo cena jednostkowa",
        "Brak stawki i liczby MD dla konsultanta",
        "Liczba MD w opisie (60) różni się od ilości z tabeli (64)",
        "Stawka brutto — sprawdź przeliczenie; brak MD",
        "U tego klienta liczby MD z PDF-a nie używamy — wpisz ją ręcznie",
        "Nie znaleziono numeru zamówienia",
        "Nie znaleziono MD ani konsultanta w wierszu 2",
        "Brak konsultanta i liczby MD w pozycji 3",
        "Zdublowana pozycja — brak MD",
    ],
)
def test_other_concerns_are_never_treated_as_md_absence(reason):
    assert is_md_absence_reason(reason) is False


def test_drop_removes_only_md_absence_and_clears_empty_uncertainty():
    ex = OrderExtraction(
        uncertain=True,
        uncertain_reasons=["Brak informacji o liczbie MD"],
        consultant_rows=[
            ConsultantOrderRow(
                consultant_name="Ewa Nowak",
                rate_client=Decimal("840"),
                uncertain=True,
                uncertain_reason="Brak liczby MD przy tej osobie",
            ),
            ConsultantOrderRow(
                consultant_name="Adam Przykładowy",
                rate_client=None,
                uncertain=True,
                uncertain_reason="Brak informacji o liczbie MD",
            ),
        ],
    )
    drop_md_absence_reasons(ex)
    assert ex.uncertain is False and ex.uncertain_reasons == []
    assert ex.consultant_rows[0].uncertain is False
    assert ex.consultant_rows[0].uncertain_reason is None
    # Bez stawki wiersz zostaje niepewny — brak MD nie był jego jedynym brakiem.
    assert ex.consultant_rows[1].uncertain is True


def test_drop_keeps_other_reasons_and_uncertainty():
    ex = OrderExtraction(
        uncertain=True,
        uncertain_reasons=["Brak informacji o liczbie MD", "Nie znaleziono daty"],
    )
    drop_md_absence_reasons(ex)
    assert ex.uncertain is True
    assert ex.uncertain_reasons == ["Nie znaleziono daty"]


def test_md_scope_recognises_both_variants():
    rows = [
        ConsultantOrderRow(consultant_name="A B", md_total=Decimal("20")),
        ConsultantOrderRow(consultant_name="C D"),
    ]
    assert md_scope(OrderExtraction(consultant_rows=rows)) == MD_SCOPE_PER_CONSULTANT
    two = [
        ConsultantOrderRow(consultant_name="A B"),
        ConsultantOrderRow(consultant_name="C D"),
    ]
    assert (
        md_scope(OrderExtraction(consultant_rows=two, md_total=Decimal("38")))
        == MD_SCOPE_ORDER
    )
    # Jedna osoba z liczbą MD dokumentu — to jej limit, nie pula.
    assert (
        md_scope(OrderExtraction(consultant_rows=two[:1], md_total=Decimal("38")))
        == MD_SCOPE_PER_CONSULTANT
    )
    assert md_scope(OrderExtraction(consultant_rows=two)) is None


# ── Bramka poczty: typ zamówienia rozstrzyga ────────────────────────────────


def _gate(order_type: str, *, row_md=None, doc_md=None, reasons=None):
    rows = [
        ConsultantOrderRow(
            consultant_name="Jan Kowalski",
            rate_client=Decimal("900.00"),
            rate_unit="day",
            md_total=row_md,
            uncertain=False,
        )
    ]
    ex = OrderExtraction(
        title="SAP 4500987654",
        start_date="2031-04-01",
        end_date="2031-06-30",
        md_total=doc_md,
        consultant_rows=rows,
        source="claude",
        uncertain=bool(reasons),
        uncertain_reasons=list(reasons or []),
    )
    ex.confidence["title"] = 1.0
    resolved = (
        ResolvedConsultant(
            row_index=0,
            row_name="Jan Kowalski",
            match_kind=MATCH_EXACT,
            candidate_id=100,
            contract_id=10,
            contract_status="active",
            candidate_ids=(100,),
            live_contract_ids=(10,),
            reason="Dopasowanie dokładne",
        ),
    )
    proposal = plan_document(
        client_id=1,
        extraction=ex,
        resolved=list(resolved),
        existing_orders_by_contract={},
        is_group_client=True,
        today=TODAY,
        order_type=order_type,
    )
    return GateInput(
        identification_method="registry_id",
        policies_applied=("Polkomtel",),
        extraction=ex,
        document_truncated=False,
        ocr_capped=False,
        resolved=resolved,
        proposal=proposal,
        deterministic_rows=tuple(rows),
        current_rates={10: (Decimal("900"), "day")},
        autoapply_enabled=True,
    )


def test_cost_order_is_not_blocked_by_missing_md():
    verdict = evaluate(_gate("cost", reasons=["Brak informacji o liczbie MD"]))
    assert verdict.verdict == VERDICT_AUTO, verdict.reasons


def test_md_for_the_whole_order_is_not_reported_as_missing():
    verdict = evaluate(
        _gate("md", doc_md=Decimal("38"), reasons=["Brak liczby MD przy konsultantach"])
    )
    assert verdict.verdict == VERDICT_AUTO, verdict.reasons


def test_md_pool_for_several_people_is_not_split_automatically():
    inp = _gate("md", doc_md=Decimal("38"))
    inp.extraction.consultant_rows.append(
        ConsultantOrderRow(
            consultant_name="Anna Nowak",
            rate_client=Decimal("900.00"),
            rate_unit="day",
            uncertain=False,
        )
    )
    verdict = evaluate(inp)
    assert not verdict.is_auto
    assert any("jedną liczbę MD na całe zamówienie" in r for r in verdict.reasons)
    assert not any("bez liczby MD" in r for r in verdict.reasons)


def test_md_order_accepts_md_per_consultant():
    verdict = evaluate(_gate("md", row_md=Decimal("20")))
    assert verdict.verdict == VERDICT_AUTO, verdict.reasons


def test_md_order_without_md_in_either_variant_goes_to_review():
    verdict = evaluate(_gate("md", reasons=["Brak informacji o liczbie MD"]))
    assert not verdict.is_auto
    assert any("zamówienie MD bez liczby MD" in reason for reason in verdict.reasons), (
        verdict.reasons
    )


def test_other_reasons_still_block_a_cost_order():
    verdict = evaluate(
        _gate("cost", reasons=["Brak informacji o liczbie MD", "Nie znaleziono daty"])
    )
    assert not verdict.is_auto
    assert "Odczyt niepewny: Nie znaleziono daty" in verdict.reasons
    assert not any("liczbie MD" in reason for reason in verdict.reasons)
