"""QC-11 (audyt 08.11.2026): jeden słownik stanów QC."""

from __future__ import annotations

from app.services.qc_state import CONSENT_MANUAL_ITEM, describe


def _pick(state: dict) -> tuple[str, str, str]:
    return state["kind"], state["text"], state["tone"]


def test_checked() -> None:
    assert _pick(describe(status="passed")) == ("checked", "QC: sprawdzone", "ok")


def test_checked_manually_names_the_person() -> None:
    state = describe(
        status="passed", manual_by="Anna K.", manual_requirements=["Kafka"]
    )
    assert _pick(state) == (
        "checked_manually",
        "QC: sprawdzone ręcznie · Anna K.",
        "info",
    )
    assert state["who"] == "Anna K." and state["items"] == ["Kafka"]


def test_verify_roles_counts_requirements() -> None:
    state = describe(
        status="passed",
        manual_items=["Kafka", "AWS", "Terraform"],
        unverified=["Kafka", "AWS", "Terraform"],
    )
    assert _pick(state) == ("verify_roles", "QC: wskaż stanowisko · 3", "wait")
    assert state["n"] == 3
    assert "Kafka, AWS, Terraform" in state["hint"]


def test_consent_alone_says_what_to_look_at() -> None:
    state = describe(status="passed", manual_items=[CONSENT_MANUAL_ITEM])
    assert state["text"] == "QC: obejrzyj zgodę RODO"


def test_other_manual_check_does_not_ask_for_a_role() -> None:
    state = describe(status="passed", manual_items=["CV nie twierdzi niczego spoza"])
    assert state["text"] == "QC: sprawdź ręcznie · 1"


def test_verify_roles_comes_before_candidate_gap() -> None:
    state = describe(
        status="passed",
        manual_items=["AWS"],
        unverified=["AWS"],
        candidate_gaps=["Kafka"],
    )
    assert state["kind"] == "verify_roles"


def test_candidate_gap_names_one_and_counts_many() -> None:
    assert (
        describe(status="passed", candidate_gaps=["Kafka"])["text"]
        == "QC: kandydat nie ma: Kafka"
    )
    assert (
        describe(status="passed", candidate_gaps=["Kafka", "AWS"])["text"]
        == "QC: kandydat nie ma · 2"
    )
    assert (
        describe(status="passed", candidate_gaps=["x" * 40])["text"]
        == "QC: kandydat nie ma · 1"
    )


def test_to_fix_is_never_zero() -> None:
    assert _pick(describe(status="failed", blocking_failed=0)) == (
        "to_fix",
        "QC: 1 do poprawy",
        "urgent",
    )
    state = describe(status="failed", blocking_failed=2, to_fix_items=["Kafka"])
    assert state["text"] == "QC: 2 do poprawy"
    assert state["hint"] == "2 rzeczy zatrzymują wysyłkę: Kafka."


def test_overridden_names_the_person_when_known() -> None:
    assert (
        describe(status="overridden", override_by="Anna K.")["text"]
        == "QC: przepuszczone · Anna K."
    )
    assert describe(status="overridden")["text"] == "QC: przepuszczone"


def test_unchecked() -> None:
    assert _pick(describe(status="unchecked")) == (
        "unchecked",
        "QC: jeszcze nie sprawdzone",
        "neutral",
    )
