"""„Zatrzymaj do podpisu przedwstępnej” — czysta reguła blokady (0762, 23.11.2026).

Bez bazy: ``stop_from`` dostaje ustawienie rekrutacji, prośby pary i kolumny.
Reguła: docs/claude/rekrutacja-tablica/stop-do-podpisu-przedwstepnej.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.pre_contract import PreContractRequest
from app.services.pre_contract_stop import rule_of_raw, stop_from

NOW = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
RULE = {
    "needed_before": "cv_sent",
    "stop": True,
    "set_by": 11,
    "set_at": "2026-11-23T10:00",
}


def _req(**kw) -> PreContractRequest:
    base = dict(
        id=1,
        candidate_id=10,
        job_id=20,
        needed_before="cv_sent",
        needed_by=None,
        candidate_signed_at=None,
        company_signed_at=None,
        closed_at=None,
        close_reason=None,
        blocks_move=None,
        blocks_set_by=None,
        blocks_set_at=None,
    )
    base.update(kw)
    return PreContractRequest(**base)


def _signed(**kw) -> PreContractRequest:
    return _req(
        candidate_signed_at=NOW - timedelta(days=2),
        company_signed_at=NOW - timedelta(days=1),
        **kw,
    )


# ── Bez ustawienia rekrutacji: jak dziś, chyba że stop przy osobie ──────────


def test_request_without_stop_only_warns() -> None:
    assert stop_from(rule=None, requests=[_req()], target_column="cv_sent") is None


def test_person_stop_blocks_from_the_needed_column_on() -> None:
    req = _req(blocks_move=True, blocks_set_by=14)
    assert stop_from(rule=None, requests=[req], target_column="cv_qc") is None
    stop = stop_from(rule=None, requests=[req], target_column="cv_sent")
    assert stop is not None and stop.origin == "person" and stop.set_by == 14
    assert stop_from(rule=None, requests=[req], target_column="client_interview")


def test_person_stop_with_date_has_no_column_and_does_not_block() -> None:
    req = _req(needed_before="date", blocks_move=True)
    assert stop_from(rule=None, requests=[req], target_column="hired") is None


def test_signed_contract_releases_the_card() -> None:
    req = _signed(blocks_move=True)
    assert stop_from(rule=RULE, requests=[req], target_column="cv_sent") is None


def test_moves_off_the_board_are_never_blocked() -> None:
    req = _req(blocks_move=True)
    assert stop_from(rule=RULE, requests=[req], target_column="rejected") is None


# ── Ustawienie rekrutacji ────────────────────────────────────────────────────


def test_rule_blocks_open_request_that_inherits_it() -> None:
    stop = stop_from(rule=RULE, requests=[_req()], target_column="cv_sent")
    assert stop is not None and stop.origin == "job" and stop.set_by == 11


def test_rule_without_stop_only_warns() -> None:
    rule = {**RULE, "stop": False}
    assert stop_from(rule=rule, requests=[_req()], target_column="cv_sent") is None


def test_exception_at_the_person_wins_over_the_rule() -> None:
    req = _req(blocks_move=False)
    assert stop_from(rule=RULE, requests=[req], target_column="cv_sent") is None


def test_earlier_of_rule_and_request_stage_wins() -> None:
    # Przegląd 23.11: późniejszy etap na prośbie nie przesuwa blokady w prawo.
    later = _req(needed_before="b2b_contract")
    assert stop_from(rule=RULE, requests=[later], target_column="cv_sent")
    rule_interview = {**RULE, "needed_before": "client_interview"}
    earlier = _req(needed_before="cv_sent")
    stop = stop_from(rule=rule_interview, requests=[earlier], target_column="cv_sent")
    assert stop is not None and stop.column == "cv_sent"


def test_date_on_a_request_does_not_lift_the_rule() -> None:
    req = _req(needed_before="date")
    stop = stop_from(rule=RULE, requests=[req], target_column="cv_sent")
    assert stop is not None and stop.needed_before == "cv_sent"


def test_moving_left_or_within_the_column_is_never_blocked() -> None:
    req = _req(blocks_move=True)
    for target in ("cv_sent", "client_interview"):
        assert (
            stop_from(
                rule=RULE,
                requests=[req],
                target_column=target,
                current_column="client_interview",
            )
            is None
        )
    assert stop_from(
        rule=RULE,
        requests=[req],
        target_column="contract",
        current_column="client_interview",
    )


def test_rule_blocks_a_person_without_any_request_before_the_stage() -> None:
    stop = stop_from(
        rule=RULE, requests=[], target_column="cv_sent", current_column="cv_qc"
    )
    assert stop is not None and stop.request_id is None


def test_rule_does_not_stop_a_person_already_past_the_stage() -> None:
    assert (
        stop_from(
            rule=RULE,
            requests=[],
            target_column="contract",
            current_column="client_interview",
        )
        is None
    )


def test_cancelled_request_is_not_a_loophole_under_the_rule() -> None:
    closed = _req(closed_at=NOW, close_reason="cancelled")
    assert stop_from(rule=RULE, requests=[closed], target_column="cv_sent")


def test_closed_request_with_exception_keeps_the_exception() -> None:
    closed = _req(closed_at=NOW, close_reason="cancelled", blocks_move=False)
    assert stop_from(rule=RULE, requests=[closed], target_column="cv_sent") is None


def test_closed_request_without_stop_releases_the_card() -> None:
    closed = _req(closed_at=NOW, close_reason="withdrawn")
    assert stop_from(rule=None, requests=[closed], target_column="cv_sent") is None


def test_cancelling_a_person_stop_is_not_a_loophole() -> None:
    closed = _req(closed_at=NOW, close_reason="cancelled", blocks_move=True)
    stop = stop_from(rule=None, requests=[closed], target_column="cv_sent")
    assert stop is not None and stop.origin == "person"


def test_signed_earlier_request_releases_even_with_a_new_open_one() -> None:
    reqs = [
        _req(id=2, blocks_move=True),
        _signed(id=1, closed_at=NOW, close_reason="fulfilled"),
    ]
    assert stop_from(rule=RULE, requests=reqs, target_column="cv_sent") is None


def test_bad_rule_shape_counts_as_no_rule() -> None:
    assert rule_of_raw({"needed_before": "date", "stop": True}) is None
    assert rule_of_raw("cv_sent") is None
    assert rule_of_raw(None) is None
    assert rule_of_raw(RULE)["stop"] is True
