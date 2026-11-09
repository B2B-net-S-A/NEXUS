"""QC-11 (audyt 08.11.2026): jeden słownik stanów QC."""

from __future__ import annotations

from typing import Iterable

from app.api.cv_qc import QcResponse
from app.services.cv_qc import qc_state_of_checks
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


# Ten sam stan z bieżącego wyniku QC (`run_qc`): panel osoby i okno QC mówiły
# „bez blokad”, kiedy karta mówiła „wskaż stanowisko” (09.11.2026).


def _critical(*roles: dict, info: Iterable[dict] = ()) -> dict:
    return {
        "key": "critical_skills",
        "label": "Umiejętności krytyczne opisane",
        "status": "pass",
        "severity": "blocking",
        "items": [],
        "roles": list(roles),
        "info": list(info),
    }


def _blocker(requirement: str) -> dict:
    return {
        "key": "must_in_roles",
        "label": "Wymagania opisane",
        "status": "fail",
        "severity": "blocking",
        "items": [{"requirement": requirement}],
    }


def test_checks_passed_is_checked() -> None:
    state = qc_state_of_checks([_critical()], has_override=False)
    assert state["kind"] == "checked"


def test_checks_unverified_role_is_not_checked() -> None:
    state = qc_state_of_checks(
        [
            _critical(
                {"requirement": "Kafka", "state": "unverified"},
                {"requirement": "Kafka", "state": "unverified"},
                {"requirement": "AWS", "state": "unverified"},
            )
        ],
        has_override=False,
    )
    assert state["kind"] == "verify_roles"
    assert state["text"] == "QC: wskaż stanowisko · 2"


def test_checks_candidate_gap_names_the_requirement() -> None:
    state = qc_state_of_checks(
        [_critical(info=[{"requirement": "Kafka", "candidate_gap": True}])],
        has_override=False,
    )
    assert state["text"] == "QC: kandydat nie ma: Kafka"


def test_checks_manual_role_names_the_person() -> None:
    state = qc_state_of_checks(
        [
            _critical(
                {
                    "requirement": "Kafka",
                    "state": "described",
                    "manual": {"by": "Anna K."},
                }
            )
        ],
        has_override=False,
    )
    assert state["text"] == "QC: sprawdzone ręcznie · Anna K."


def test_checks_consent_from_file_is_named() -> None:
    state = qc_state_of_checks(
        [
            {
                "key": "client_rules",
                "label": "Reguły klienta",
                "status": "manual",
                "severity": "blocking",
                "items": [],
            }
        ],
        has_override=False,
    )
    assert state["text"] == "QC: obejrzyj zgodę RODO"


def test_checks_failed_counts_things_to_fix() -> None:
    state = qc_state_of_checks([_blocker("Kafka")], has_override=False)
    assert state["kind"] == "to_fix" and state["items"] == ["Kafka"]


def test_checks_failed_with_override_is_overridden() -> None:
    state = qc_state_of_checks([_blocker("Kafka")], has_override=True)
    assert state["kind"] == "overridden"


def test_checks_override_does_not_hide_a_clean_pass() -> None:
    state = qc_state_of_checks([_critical()], has_override=True)
    assert state["kind"] == "checked"


def test_checks_override_on_unverified_roles_is_overridden() -> None:
    state = qc_state_of_checks(
        [_critical({"requirement": "Kafka", "state": "unverified"})],
        has_override=True,
    )
    assert state["kind"] == "overridden"


def test_checks_dismissed_blocker_is_overridden() -> None:
    check = {**_critical(), "dismissed_items": [{"requirement": "Kafka"}]}
    assert qc_state_of_checks([check], has_override=False)["kind"] == "overridden"


def test_checks_older_cv_keeps_the_file_name() -> None:
    state = qc_state_of_checks(
        [
            {
                "key": "cv_present",
                "label": "CV sprzed tej rekrutacji",
                "status": "manual",
                "severity": "blocking",
                "items": [
                    {"document": {"filename": "cv.docx", "at": "2026-10-01T10:00:00"}}
                ],
            }
        ],
        has_override=False,
    )
    assert state["kind"] == "older_cv"
    assert "cv.docx" in state["hint"]


def test_qc_response_carries_the_state() -> None:
    assert "qc_state" in QcResponse.model_fields
