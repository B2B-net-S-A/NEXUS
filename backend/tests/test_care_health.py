"""Zdrowie relacji z konsultantem (``care/health.assess``) — brzegi reguł, bez bazy."""

from __future__ import annotations

from datetime import date, timedelta

from app.services.care.health import HealthSignals, assess

TODAY = date(2026, 10, 22)


def _signals(**overrides) -> HealthSignals:
    base = {
        "today": TODAY,
        "start_on": TODAY - timedelta(days=200),
        "last_conversation_on": TODAY - timedelta(days=10),
        "cadence_level": "monthly",
    }
    base.update(overrides)
    return HealthSignals(**base)


def _level(**overrides) -> str:
    result = assess(_signals(**overrides))
    assert result is not None
    return result.level


def test_quiet_contract_is_ok_without_reasons() -> None:
    result = assess(_signals())
    assert result is not None
    assert result.as_dict() == {"level": "ok", "label": "Dobrze", "reasons": []}


def test_ended_contract_has_no_label() -> None:
    assert assess(_signals(live=False, attrition_risk=True)) is None


def test_attrition_risk_is_risk_with_day() -> None:
    result = assess(_signals(attrition_risk=True, attrition_risk_on=date(2026, 10, 1)))
    assert result.level == "risk"
    assert result.label == "Ryzyko"
    assert result.reasons == ("ryzyko odejścia (01.10)",)


def test_wants_change_with_end_at_60_days_is_risk_at_61_watch() -> None:
    at_60 = assess(
        _signals(
            wants_change=True,
            wants_change_on=date(2026, 10, 1),
            end_on=TODAY + timedelta(days=60),
        )
    )
    assert at_60.level == "risk"
    assert at_60.reasons == (
        "chce zmiany projektu (01.10)",
        "zamówienie kończy się za 60 dni",
    )
    at_61 = assess(_signals(wants_change=True, end_on=TODAY + timedelta(days=61)))
    assert at_61.level == "watch"
    assert at_61.reasons == ("chce zmiany projektu",)


def test_manager_feedback_below_three_is_risk_three_is_not() -> None:
    low = assess(_signals(feedback_average=2.9, feedback_on=date(2026, 9, 12)))
    assert low.level == "risk"
    assert low.reasons == ("opinia menedżera 2,9/5 (12.09)",)
    assert _level(feedback_average=3.0) == "ok"


def test_satisfaction_two_is_risk_three_is_watch_four_ok() -> None:
    assert _level(satisfaction=2) == "risk"
    assert _level(satisfaction=3) == "watch"
    assert _level(satisfaction=4) == "ok"


def test_satisfaction_drop_by_two_is_watch_by_one_is_not() -> None:
    drop = assess(_signals(satisfaction=3, previous_satisfaction=5))
    assert drop.level == "watch"
    assert drop.reasons == ("zadowolenie spadło z 5 na 3",)
    assert _level(satisfaction=4, previous_satisfaction=5) == "ok"


def test_overdue_conversation_is_watch_from_first_day() -> None:
    assert _level(overdue_days=0) == "ok"
    result = assess(_signals(overdue_days=1))
    assert result.level == "watch"
    assert result.reasons == ("rozmowa zaległa 1 dzień",)


def test_end_within_45_days_without_decision_is_watch() -> None:
    result = assess(_signals(end_on=TODAY + timedelta(days=45)))
    assert result.level == "watch"
    assert result.reasons == ("zamówienie kończy się za 45 dni, bez decyzji",)
    assert _level(end_on=TODAY + timedelta(days=46)) == "ok"
    assert _level(end_on=TODAY + timedelta(days=10), end_decided=True) == "ok"
    contract_end = assess(
        _signals(end_on=TODAY + timedelta(days=5), end_kind="contract")
    )
    assert contract_end.reasons == ("umowa kończy się za 5 dni, bez decyzji",)
    # Koniec w przeszłości to nie „kończy się” (kontrakt jeszcze nie przestawiony).
    assert _level(end_on=TODAY - timedelta(days=1)) == "ok"


def test_new_contract_without_conversations_is_ok_with_reason() -> None:
    result = assess(
        _signals(start_on=TODAY - timedelta(days=13), last_conversation_on=None)
    )
    assert result.level == "ok"
    assert result.reasons == ("brak rozmów",)


def test_silence_longer_than_two_intervals_is_watch() -> None:
    # Co miesiąc: 60 dni ciszy to jeszcze nie, 61 — tak.
    assert _level(last_conversation_on=TODAY - timedelta(days=60)) == "ok"
    result = assess(_signals(last_conversation_on=TODAY - timedelta(days=61)))
    assert result.level == "watch"
    assert result.reasons == ("brak rozmowy od 61 dni",)
    # Bez rozmów liczy się od startu.
    never = assess(
        _signals(
            start_on=TODAY - timedelta(days=29),
            last_conversation_on=None,
            cadence_level="biweekly",
        )
    )
    assert never.level == "watch"
    assert never.reasons == ("brak rozmowy od 29 dni",)


def test_paused_and_milestones_cadence_skip_the_silence_rule() -> None:
    for level in ("paused", "milestones"):
        assert (
            _level(
                last_conversation_on=TODAY - timedelta(days=400), cadence_level=level
            )
            == "ok"
        )


def test_risk_wins_and_reasons_are_capped_at_three() -> None:
    result = assess(
        _signals(
            attrition_risk=True,
            wants_change=True,
            end_on=TODAY + timedelta(days=20),
            feedback_average=2.0,
            satisfaction=1,
            overdue_days=9,
        )
    )
    assert result.level == "risk"
    assert len(result.reasons) == 3
    assert result.reasons[0] == "ryzyko odejścia"
    assert result.as_dict()["reasons"][2] == "zamówienie kończy się za 20 dni"
