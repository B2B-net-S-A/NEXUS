"""Przedłużenie z maila: stawka odniesienia i nakładające się okresy (27.10.2026).

Zgłoszenie z 27.10.2026: przedłużenie z podwyżką czekało w kolejce, bo bramka
porównywała je ze stawką z rekrutacji sprzed dwóch lat — sprzed startu
kontraktu — zamiast z obecnym zamówieniem. Drugi powód, „Okres nachodzi na
otwarte zamówienie”, był nie do zapisania: „Zastosuj” odmawiał wiersza
``overlap``.

Decyzja Artura 27.10.2026: odniesieniem jest ostatnia uzgodniona stawka —
przy pierwszym zamówieniu kontraktu stawka z rekrutacji, przy każdym kolejnym
stawka poprzedniego zamówienia. Nakładanie się okresów rozstrzyga człowiek
jednym wyborem w panelu: skrócić poprzednie albo zacząć nowe po nim.
Czyste funkcje; fixture'y z ``test_order_mail_gate_and_planner``. Lata 2031+.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.order_mail_gate import (
    CODE_RATE_RECRUITMENT_MISMATCH,
    CODE_RATE_RENEWAL_CHANGED,
    VERDICT_REVIEW,
    evaluate,
)
from app.services.order_mail_planner import (
    ACTION_FUTURE,
    ACTION_OVERLAP,
    ACTION_REACTIVATE,
    OVERLAP_START_AFTER,
    OVERLAP_TRIM_PREVIOUS,
    ExistingOrder,
)
from app.services.order_mail_recheck_reasons import (
    AWAITING_CONTRACT_CODES,
    CATEGORY_OTHER,
    classify_hold,
)
from app.services.recruitment_rate_check import RateRef
from tests.test_order_mail_gate_and_planner import (
    _extraction,
    _gate_input,
    _plan,
    _resolved,
    _row,
)

#: Rekrutacja sprzed lat — przy przedłużeniu nie jest już odniesieniem.
_OLD_RECRUITMENT = RateRef(value=Decimal("100"), unit="hourly", label="Analityk")


def _current(
    order_id=70,
    *,
    start=date(2031, 1, 1),
    end=date(2031, 3, 31),
    rate="120",
    status="active",
):
    return ExistingOrder(
        id=order_id,
        status=status,
        title="9/2030",
        start_date=start,
        end_date=end,
        rate_client=Decimal(rate),
        rate_unit="hourly",
    )


def _renewal(rate="138", start="2031-04-01", end="2031-06-30", existing=None):
    ex = _extraction(
        [_row("Jan Kowalski", rate=rate, unit="hour", start=start, end=end)]
    )
    prop = _plan(
        ex,
        (_resolved(0, "Jan Kowalski"),),
        existing={10: existing if existing is not None else [_current()]},
    )
    return ex, prop


# ── Planer: poprzednie zamówienie jako odniesienie ──────────────────────────


def test_renewal_row_carries_the_previous_order_and_its_rate():
    _, prop = _renewal()
    (row,) = prop.rows
    assert row.action == ACTION_FUTURE
    assert row.previous_order_id == 70
    assert row.previous_order_title == "9/2030"
    assert Decimal(row.previous_rate_client) == Decimal("120")
    assert row.previous_rate_unit == "hour"


def test_first_order_of_a_contract_has_no_previous_rate():
    _, prop = _renewal(existing=[])
    assert prop.rows[0].previous_order_id is None
    assert prop.rows[0].previous_rate_client is None


def test_return_after_a_break_compares_with_the_completed_order():
    _, prop = _renewal(existing=[_current(status="completed", end=date(2031, 2, 28))])
    (row,) = prop.rows
    assert row.action == ACTION_REACTIVATE
    assert row.previous_order_id == 70


def test_drafts_and_cancelled_orders_are_not_an_agreed_rate():
    _, prop = _renewal(
        existing=[
            _current(
                order_id=300,
                status="draft",
                start=date(2031, 4, 1),
                end=date(2031, 6, 30),
                rate="999",
            ),
            _current(order_id=301, status="cancelled", rate="1"),
        ]
    )
    assert prop.rows[0].previous_rate_client is None


# ── Bramka: przedłużenie porównujemy z poprzednim zamówieniem ───────────────


def test_renewal_at_the_same_rate_is_automatic_despite_an_old_recruitment():
    ex, prop = _renewal(rate="120")
    verdict = evaluate(
        _gate_input(
            extraction=ex,
            proposal=prop,
            deterministic_rows=tuple(ex.consultant_rows),
            current_rates={10: (Decimal("120"), "hour")},
            recruitment_rates={10: _OLD_RECRUITMENT},
        )
    )
    assert verdict.is_auto, verdict.reasons


def test_renewal_with_a_new_rate_asks_to_confirm_it_against_the_previous_order():
    ex, prop = _renewal(rate="138")
    verdict = evaluate(
        _gate_input(
            extraction=ex,
            proposal=prop,
            deterministic_rows=tuple(ex.consultant_rows),
            current_rates={10: (Decimal("120"), "hour")},
            recruitment_rates={10: _OLD_RECRUITMENT},
        )
    )
    assert verdict.verdict == VERDICT_REVIEW
    assert verdict.codes == [CODE_RATE_RENEWAL_CHANGED]
    (reason,) = verdict.reasons
    assert "„Jan Kowalski”" in reason
    assert "120 zł/h → 138 zł/h" in reason
    assert "+15%" in reason
    assert "#70" in reason
    # Rekrutacja sprzed lat nie pojawia się w powodzie przedłużenia.
    assert "rekrutac" not in reason
    # Słowo „stawka” jest warunkiem maskowania kwot w kolejce.
    assert "stawka" in reason


def test_rate_cut_on_renewal_shows_the_minus_sign():
    ex, prop = _renewal(rate="108")
    verdict = evaluate(
        _gate_input(
            extraction=ex,
            proposal=prop,
            deterministic_rows=tuple(ex.consultant_rows),
            current_rates={10: (Decimal("120"), "hour")},
        )
    )
    (reason,) = verdict.reasons
    assert "120 zł/h → 108 zł/h (−10%)" in reason


def test_first_order_is_still_compared_with_the_recruitment():
    """Kontrola z D7 zostaje: DL wysłał za 200, zamówienie przyszło na 180."""
    ex, prop = _renewal(rate="138", existing=[])
    verdict = evaluate(
        _gate_input(
            extraction=ex,
            proposal=prop,
            deterministic_rows=tuple(ex.consultant_rows),
            current_rates={},
            recruitment_rates={10: _OLD_RECRUITMENT},
        )
    )
    assert verdict.codes == [CODE_RATE_RECRUITMENT_MISMATCH]


def test_renewal_change_is_not_a_quiet_wait_for_a_contract():
    assert CODE_RATE_RENEWAL_CHANGED not in AWAITING_CONTRACT_CODES
    assert classify_hold([CODE_RATE_RENEWAL_CHANGED]) == CATEGORY_OTHER


# ── Planer: nakładające się okresy dostają dwie możliwości ──────────────────


def test_overlapping_renewal_offers_trimming_or_starting_after():
    """Nowe od 01.03, obecne do 31.03 — marzec w obu zamówieniach."""
    _, prop = _renewal(
        start="2031-03-01",
        end="2031-08-31",
        existing=[_current(end=date(2031, 3, 31))],
    )
    (row,) = prop.rows
    assert row.action == ACTION_OVERLAP
    assert row.target_order_id == 70
    assert row.overlap_options == [OVERLAP_TRIM_PREVIOUS, OVERLAP_START_AFTER]
    assert row.overlap_trim_end == "2031-02-28"
    assert row.overlap_start_after == "2031-04-01"
    assert row.previous_end_date == "2031-03-31"
    assert row.previous_start_date == "2031-01-01"
    (reason,) = row.reasons
    assert "01.03.2031" in reason and "#70" in reason and "31.03.2031" in reason


def test_overlap_ending_with_the_previous_order_cannot_start_after_it():
    _, prop = _renewal(
        start="2031-03-01",
        end="2031-03-31",
        existing=[_current(end=date(2031, 3, 31))],
    )
    assert prop.rows[0].overlap_options == [OVERLAP_TRIM_PREVIOUS]


def test_document_inside_the_previous_period_gets_no_options():
    """Krótszy okres wewnątrz obecnego to nie przedłużenie — decyduje okno zamówienia."""
    _, prop = _renewal(
        start="2031-02-01",
        end="2031-02-28",
        existing=[_current(end=date(2031, 3, 31))],
    )
    (row,) = prop.rows
    assert row.action == ACTION_OVERLAP
    assert row.overlap_options == []


def test_open_ended_previous_order_gets_no_options():
    _, prop = _renewal(
        start="2031-03-01",
        end="2031-08-31",
        existing=[_current(end=None)],
    )
    assert prop.rows[0].overlap_options == []


def test_document_starting_with_the_previous_order_gets_no_options():
    _, prop = _renewal(
        start="2031-01-01",
        end="2031-08-31",
        existing=[_current(end=date(2031, 3, 31))],
    )
    assert prop.rows[0].overlap_options == []
