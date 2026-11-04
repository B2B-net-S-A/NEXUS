"""Bramka poczty zamówień: stawka z zamówienia kontra stawka do klienta z rekrutacji (D7).

Różnica = „do sprawdzenia” (kolejka z kodem), nigdy blokada zapisu ręcznego.
Czyste funkcje — bez bazy; fixture'y bramki z ``test_order_mail_gate_and_planner``.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.order_mail_gate import (
    CODE_RATE_RECRUITMENT_MISMATCH,
    VERDICT_REVIEW,
    evaluate,
)
from app.services.order_mail_recheck_reasons import (
    AWAITING_CONTRACT_CODES,
    CATEGORY_OTHER,
    classify_hold,
)
from app.services.order_mail_resolver import MATCH_NONE
from app.services.recruitment_rate_check import RateRef
from tests.test_order_mail_gate_and_planner import (
    _extraction,
    _gate_input,
    _plan,
    _resolved,
    _row,
)

# Wiersz bazowy z fixture'u: 900 zł/MD → 112,50 zł/h, kontrakt 10.
_EQUAL = RateRef(value=Decimal("112.50"), unit="hourly", label="Java Developer")
_OTHER = RateRef(value=Decimal("120"), unit="hourly", label="Java Developer")


def test_equal_recruitment_rate_keeps_the_document_automatic():
    verdict = evaluate(_gate_input(recruitment_rates={10: _EQUAL}))
    assert verdict.is_auto, verdict.reasons


def test_different_recruitment_rate_goes_to_review_with_its_code():
    verdict = evaluate(_gate_input(recruitment_rates={10: _OTHER}))
    assert verdict.verdict == VERDICT_REVIEW
    assert verdict.codes == [CODE_RATE_RECRUITMENT_MISMATCH]
    (reason,) = verdict.reasons
    assert "„Jan Kowalski”" in reason
    assert "„Java Developer”" in reason
    assert "900 zł/MD" in reason and "120 zł/h" in reason
    # Słowo „stawka” jest warunkiem maskowania kwot w kolejce.
    assert "stawka" in reason


def test_no_recruitment_data_changes_nothing():
    assert evaluate(_gate_input()).is_auto
    assert evaluate(_gate_input(recruitment_rates={99: _OTHER})).is_auto


@pytest.mark.parametrize(
    "ref",
    [
        RateRef(value=Decimal("24000"), unit="monthly"),  # miesiąc z MD
        RateRef(value=Decimal("40"), unit="hourly", currency="EUR"),
        RateRef(value=None, unit="hourly"),
    ],
    ids=["miesiac", "waluta", "brak-stawki"],
)
def test_not_comparable_recruitment_rate_is_skipped(ref):
    assert evaluate(_gate_input(recruitment_rates={10: ref})).is_auto


def test_order_row_without_rate_is_not_compared():
    ex = _extraction([_row("Jan Kowalski")])
    prop = _plan(ex, (_resolved(0, "Jan Kowalski"),))
    prop.rows[0].rate_client = None
    verdict = evaluate(
        _gate_input(extraction=ex, proposal=prop, recruitment_rates={10: _OTHER})
    )
    assert CODE_RATE_RECRUITMENT_MISMATCH not in verdict.codes


def test_cost_order_is_not_compared():
    ex = _extraction([_row("Jan Kowalski")])
    prop = _plan(ex, (_resolved(0, "Jan Kowalski"),))
    prop.rows[0].order_type = "cost"
    verdict = evaluate(
        _gate_input(extraction=ex, proposal=prop, recruitment_rates={10: _OTHER})
    )
    assert CODE_RATE_RECRUITMENT_MISMATCH not in verdict.codes


def test_unmatched_person_is_not_compared():
    ex = _extraction([_row("Jan Kowalski")])
    resolved = (_resolved(0, "Jan Kowalski", kind=MATCH_NONE),)
    prop = _plan(ex, (_resolved(0, "Jan Kowalski"),))
    verdict = evaluate(
        _gate_input(
            extraction=ex,
            proposal=prop,
            resolved=resolved,
            recruitment_rates={10: _OTHER},
        )
    )
    assert CODE_RATE_RECRUITMENT_MISMATCH not in verdict.codes


def test_mismatch_is_not_a_quiet_wait_for_a_contract():
    """Po trzech próbach Delivery Lead dostaje kartę — to nie „czeka na podpis”."""
    assert CODE_RATE_RECRUITMENT_MISMATCH not in AWAITING_CONTRACT_CODES
    assert classify_hold([CODE_RATE_RECRUITMENT_MISMATCH]) == CATEGORY_OTHER


@pytest.mark.asyncio
async def test_queue_masks_the_amounts_for_a_role_without_finance(monkeypatch):
    from app.api import order_mail_queue as queue
    from app.models.user import User, UserRole

    monkeypatch.setattr(queue, "_attachment_exists", lambda doc: True)
    (reason,) = evaluate(_gate_input(recruitment_rates={10: _OTHER})).reasons
    doc = SimpleNamespace(
        id=1,
        received_at=None,
        created_at=None,
        sender_email="a@b.example",
        subject="Zamówienie",
        attachment_name="z.pdf",
        outcome="needs_review",
        client_id=5,
        identification_method="registry_id",
        identification_reason="NIP",
        client_policy=None,
        gate_verdict="review",
        gate_reasons=[reason],
        document_meta={},
        extraction=None,
        proposal=None,
        applied_order_id=None,
        applied_at=None,
        reviewed_at=None,
        error=None,
        storage_path=None,
    )
    db = AsyncMock()
    db.scalar = AsyncMock(return_value="Bank")
    lead = User(
        id=7,
        email="dl-outside@example.com",
        role=UserRole.delivery_lead,
        roles=["delivery_lead", "talent_community_manager"],
    )
    outside = await queue._serialize(
        db, doc, lead, boundary=queue._FinanceBoundary(frozenset({99}))
    )
    (masked,) = outside["gate_reasons"]
    assert "900" not in masked and "120" not in masked
    assert "Java Developer" in masked

    assigned = await queue._serialize(
        db, doc, lead, boundary=queue._FinanceBoundary(frozenset({5}))
    )
    assert assigned["gate_reasons"] == [reason]
