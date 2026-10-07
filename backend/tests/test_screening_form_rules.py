"""Jeden formularz screeningu (0424) — czyste reguły, bez bazy.

Reguła edycji, migawka stanu pary, porównanie wersji, lista zmian „przed →
po”, plan przywrócenia wersji i walidacja zapisu. Dane wyłącznie fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.job import JobStatus
from app.models.recruitment_process import ProcessStatus
from app.services import recommendation_card_assist as assist
from app.services import screening_form as form
from app.services import screening_form_rules as rules

QUESTIONS = {
    "q1": "Jakie ma doświadczenie z Kafką?",
    "q2": "Dlaczego chce zmienić projekt?",
    "q3": "Ile dni może być w biurze?",
}
ORDER = list(QUESTIONS)


def _sheet(*answers: dict, **extra) -> dict:
    return {"answers": list(answers), "overall_fit": "uncertain", **extra}


def _answer(question_id: str, response: str = "", **extra) -> dict:
    return {"question_id": question_id, "response": response, **extra}


# ── Reguła edycji ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("job_status", "has_stage", "process_status", "column", "reason"),
    [
        (JobStatus.published, True, ProcessStatus.open, "screening", None),
        (JobStatus.draft, True, ProcessStatus.open, "new", None),
        # D8: edycja na każdym etapie, dopóki proces trwa.
        (JobStatus.published, True, ProcessStatus.open, "cv_sent", None),
        (JobStatus.closed, True, ProcessStatus.open, "screening", rules.JOB_CLOSED),
        (
            JobStatus.published,
            True,
            ProcessStatus.closed,
            "closed",
            rules.PROCESS_CLOSED,
        ),
        (JobStatus.published, False, ProcessStatus.voided, None, rules.PROCESS_VOIDED),
        (JobStatus.published, True, ProcessStatus.voided, "new", rules.PROCESS_VOIDED),
        (JobStatus.published, False, None, None, rules.NO_STAGE),
        # „Onboarding” nie zamyka procesu, ale osoba jest już zatrudniona.
        (JobStatus.published, True, ProcessStatus.open, "hired", rules.PROCESS_CLOSED),
        # Para bez procesu: rozstrzyga kolumna najnowszego wiersza etapu.
        (JobStatus.published, True, None, "closed", rules.PROCESS_CLOSED),
        (JobStatus.published, True, None, "verified", None),
    ],
)
def test_read_only_reason(job_status, has_stage, process_status, column, reason):
    assert (
        rules.read_only_reason(
            job_status=job_status,
            has_stage=has_stage,
            process_status=process_status,
            column=column,
        )
        == reason
    )


def test_every_reason_has_a_polish_message():
    for reason in (
        rules.JOB_CLOSED,
        rules.PROCESS_CLOSED,
        rules.PROCESS_VOIDED,
        rules.NO_STAGE,
    ):
        assert rules.READ_ONLY_MESSAGES[reason].endswith(".")


# ── Treść arkusza ────────────────────────────────────────────────────────────


def test_empty_answers_are_not_content():
    assert rules.sheet_has_content(None) is False
    assert rules.sheet_has_content(_sheet(_answer("q1"), _answer("q2", "   "))) is False
    # Sama ocena i stara notatka z arkusza to nie rozmowa.
    assert rules.sheet_has_content(_sheet(overall_fit="fit", notes="stara")) is False


@pytest.mark.parametrize(
    "answer",
    [
        _answer("q1", "Kafka od 3 lat"),
        _answer("q1", skipped=True),
        _answer("q1", deal_breaker_hit=True),
    ],
)
def test_answers_with_content(answer):
    assert rules.sheet_has_content(_sheet(answer)) is True


def test_experience_check_counts_as_content():
    sheet = _sheet(
        experience_checks=[
            {"kind": "domains", "name": "Bankowość", "status": "confirmed"}
        ]
    )
    assert rules.sheet_has_content(sheet) is True
    unknown = _sheet(experience_checks=[{"name": "Bankowość", "status": "unknown"}])
    assert rules.sheet_has_content(unknown) is False


# ── Migawka ──────────────────────────────────────────────────────────────────


def test_sheet_snapshot_is_normalized_and_idempotent():
    raw = _sheet(
        _answer(
            "q1",
            "  Kafka od 3 lat ",
            origin="phrased",
            keywords="kafka 3",
            question_text=QUESTIONS["q1"],
        ),
        _answer("q2"),
        notes="  stara notatka ",
        answered_at="2026-10-07T10:00:00+00:00",
        answered_by=7,
    )
    snap = rules.sheet_snapshot(raw)
    assert snap["answers"][0]["response"] == "Kafka od 3 lat"
    assert snap["answers"][0]["question_text"] == QUESTIONS["q1"]
    assert snap["notes"] == "stara notatka"
    assert "answered_at" not in snap and "answered_by" not in snap
    assert rules.sheet_snapshot(snap) == snap
    assert rules.sheet_snapshot(_sheet(_answer("q1"))) is None


def test_card_snapshot_skips_rate_and_unknown_origins():
    snap = rules.card_snapshot(
        {
            "rate": {"raw": "150 zł/h", "source": "manual"},
            "availability": {"raw": "od zaraz", "source": "note", "origin": "x"},
            "recommendation": {
                "raw": "Mocny w Kafce.",
                "source": "manual",
                "origin": "phrased",
                "keywords": "kafka mocny",
            },
            "english": {"raw": "  ", "source": "manual"},
        }
    )
    assert set(snap) == {"availability", "recommendation"}
    assert "origin" not in snap["availability"]
    assert snap["recommendation"]["keywords"] == "kafka mocny"


def test_rate_snapshot_amount_is_comparable_text():
    assert rules.rate_snapshot(
        {"amount": Decimal("150.00"), "unit": "hourly", "currency": "pln"}
    ) == {"amount": "150", "unit": "hourly", "currency": "PLN"}
    assert (
        rules.rate_snapshot({"amount": "150.5", "unit": "daily"})["amount"] == "150.5"
    )
    assert rules.rate_snapshot(None) is None
    assert rules.rate_snapshot({"amount": None}) is None


# ── Porównanie ───────────────────────────────────────────────────────────────


def _snapshot(sheet=None, card=None, rate=None) -> dict:
    return rules.build_snapshot(sheet=sheet, card_fields=card or {}, rate=rate)


def test_origin_and_empty_answers_are_not_a_change():
    a = _snapshot(_sheet(_answer("q1", "Kafka", origin="manual"), _answer("q2")))
    b = _snapshot(_sheet(_answer("q1", "Kafka", origin="note_import", keywords="k")))
    assert rules.snapshots_equal(a, b)
    assert rules.diff_snapshots(a, b, questions=ORDER) == []


def test_card_source_alone_is_not_a_change():
    a = _snapshot(card={"english": {"raw": "B2", "source": "note"}})
    b = _snapshot(card={"english": {"raw": "B2", "source": "manual"}})
    assert rules.snapshots_equal(a, b)


def test_diff_lists_changes_in_form_order_with_polish_labels():
    before = _snapshot(
        _sheet(_answer("q1", "Kafka 2 lata"), notes="stara notatka"),
        card={"availability": {"raw": "miesiąc", "source": "note"}},
        rate={"amount": Decimal("110"), "unit": "hourly", "currency": "PLN"},
    )
    after = _snapshot(
        _sheet(
            _answer("q1", "Kafka 3 lata"),
            _answer("q3", skipped=True),
            overall_fit="fit",
        ),
        card={
            "availability": {"raw": "od zaraz", "source": "manual"},
            "recommendation": {"raw": "Mocny w Kafce.", "source": "manual"},
        },
        rate={"amount": Decimal("125"), "unit": "hourly", "currency": "PLN"},
    )
    changes = rules.diff_snapshots(before, after, questions=ORDER)
    assert [(c.section, c.key, c.label) for c in changes] == [
        ("answers", "q1", "Pytanie 1"),
        ("answers", "q3", "Pytanie 3"),
        ("terms", "availability", "Dostępność"),
        ("assessment", "overall_fit", "Ocena rekrutera"),
        ("assessment", "recommendation", "Dlaczego ten kandydat"),
        ("assessment", "notes", "Notatka z arkusza"),
        ("rate", "rate", "Stawka kandydata"),
    ]
    by_key = {c.key: c for c in changes}
    assert (by_key["q3"].before, by_key["q3"].after) == (None, "pominięte")
    assert (by_key["overall_fit"].before, by_key["overall_fit"].after) == (
        "Nie wiadomo",
        "Pasuje",
    )
    assert (by_key["rate"].before, by_key["rate"].after) == ("110 zł/h", "125 zł/h")
    assert by_key["notes"].after is None
    assert by_key["q1"].as_dict() == {
        "section": "answers",
        "key": "q1",
        "label": "Pytanie 1",
        "before": "Kafka 2 lata",
        "after": "Kafka 3 lata",
    }


def test_first_sheet_with_default_fit_does_not_list_the_fit():
    changes = rules.diff_snapshots(
        None, _snapshot(_sheet(_answer("q2", "Chce dłuższy projekt"))), questions=ORDER
    )
    assert [c.key for c in changes] == ["q2"]
    assert changes[0].label == "Pytanie 2"


def test_deal_breaker_and_experience_are_described():
    after = _snapshot(
        _sheet(
            _answer("q1", "Nie zna Kafki", deal_breaker_hit=True),
            experience_checks=[
                {
                    "kind": "domains",
                    "name": "Bankowość",
                    "status": "not_confirmed",
                    "note": "tylko e-commerce",
                }
            ],
        )
    )
    changes = rules.diff_snapshots(None, after, questions=ORDER)
    assert changes[0].after == "Nie zna Kafki (odpada)"
    assert changes[1].key == "experience:domains:Bankowość"
    assert changes[1].after == "nie potwierdził — tylko e-commerce"
    # Dziennik zdarzeń nie dostaje nazwy wymagania z Championa.
    assert rules.activity_fields(changes) == ["experience", "q1"]


def test_question_label_outside_the_profile():
    assert rules.question_label("q7", ORDER) == "Pytanie 7"
    assert rules.question_label("custom", ORDER) == "Pytanie custom"


def test_card_field_differs_from_the_effective_value():
    fields = {
        "english": {"raw": "B2", "source": "note"},
        "location": {"raw": "Łódź", "source": "manual"},
    }
    # Pole z notatki nie staje się ręczne od zapisu bez zmiany.
    assert rules.card_field_differs(fields, "english", " B2 ") is False
    assert rules.card_field_differs(fields, "english", "C1") is True
    assert rules.card_field_differs(fields, "english", None) is False
    assert rules.card_field_differs(fields, "location", "") is True
    assert rules.card_field_differs(fields, "motivation", None) is False
    assert rules.card_field_differs(fields, "motivation", "Dłuższy projekt") is True


def test_untouched_field_does_not_revert_an_external_change():
    # Formularz otwarty przed zmianą DL-a: odesłał wartość z ostatniej wersji.
    assert rules.stale_against_external("110", "125", "110") is True
    # Rekruter zmienił pole świadomie — jego wartość wygrywa.
    assert rules.stale_against_external("110", "125", "130") is False
    # Nic się nie zmieniło obok formularza.
    assert rules.stale_against_external("110", "110", "110") is False


# ── Przywracanie ─────────────────────────────────────────────────────────────


def test_restore_plan_keeps_answers_to_changed_questions():
    version = _snapshot(
        _sheet(
            _answer("q1", "Kafka 2 lata", question_text=QUESTIONS["q1"]),
            _answer("q2", "Stara odpowiedź", question_text="Inne pytanie?"),
            _answer("q9", "Pytanie usunięte", question_text="Usunięte?"),
        ),
        card={
            "availability": {"raw": "miesiąc", "source": "manual"},
            "recommendation": {
                "raw": "Zdanie.",
                "source": "manual",
                "origin": "phrased",
                "keywords": "hasła",
            },
        },
        rate={"amount": Decimal("110"), "unit": "hourly", "currency": "PLN"},
    )
    current = _sheet(
        _answer("q1", "Kafka 3 lata"),
        _answer("q2", "Nowa odpowiedź"),
        _answer("q3", "2 dni"),
    )
    plan = rules.restore_plan(version, current_sheet=current, questions=QUESTIONS)
    by_id = {item["question_id"]: item for item in plan.sheet["answers"]}
    assert by_id["q1"]["response"] == "Kafka 2 lata"
    # Treść pytania 2 się zmieniła — zostaje bieżąca odpowiedź.
    assert by_id["q2"]["response"] == "Nowa odpowiedź"
    # Pytania 9 nie ma w profilu; pytania 3 wersja nie znała.
    assert "q9" not in by_id
    assert by_id["q3"]["response"] == "2 dni"
    assert [item["question_id"] for item in plan.sheet["answers"]] == ["q1", "q2", "q3"]
    assert plan.skipped_answers == ("Pytanie 2", "Pytanie 9")
    assert plan.card["availability"] == "miesiąc"
    assert plan.card["english"] is None
    assert plan.card_origins == {
        "recommendation": {"origin": "phrased", "keywords": "hasła"}
    }
    assert plan.rate == {"amount": "110", "unit": "hourly", "currency": "PLN"}


def test_restore_plan_without_sheet_leaves_the_sheet():
    plan = rules.restore_plan(_snapshot(), current_sheet=None, questions=QUESTIONS)
    assert plan.sheet is None and plan.rate is None
    assert set(plan.card) == set(rules.FORM_CARD_FIELDS)


# ── Walidacja zapisu ─────────────────────────────────────────────────────────


def _input(**overrides) -> form.SaveInput:
    return form.SaveInput.model_validate({"expected_version": 0, **overrides})


@pytest.mark.parametrize(
    "payload",
    [
        {"sheet": {"answers": [{"question_id": "q9", "response": "x"}]}},
        {"card": {"fields": {"rate": "150 zł/h"}}},
        {"card": {"fields": {"pesel": "x"}}},
        {"card": {"fields": {"english": "x" * 301}}},
        {
            "card": {
                "fields": {"english": "B2"},
                "origins": {"english": {"origin": "phrased", "keywords": "b2"}},
            }
        },
        {
            "card": {
                "fields": {"english": "B2"},
                "origins": {"english": {"origin": "note_ai"}},
            }
        },
        {"card": {"fields": {}, "origins": {"english": {"origin": "note_rule"}}}},
        {"rate": {"amount": "0", "unit": "hourly"}},
        {"rate": {"amount": "-10", "unit": "hourly"}},
        {"rate": {"amount": "150", "unit": "hourly", "currency": "zł"}},
        {"rate": {"amount": "2000000", "unit": "hourly"}},
        {"note_import": {"text": "   "}},
    ],
)
def test_invalid_save_is_refused_with_a_code(payload):
    with pytest.raises(HTTPException) as caught:
        form.validate_save(_input(**payload), QUESTIONS)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "SCREENING_FORM_INVALID"
    assert caught.value.detail["message"]


def test_valid_save_passes(monkeypatch):
    monkeypatch.setattr(settings, "RECOMMENDATION_CARD_ASSIST_ENABLED", True)
    form.validate_save(
        _input(
            sheet={"answers": [{"question_id": "q1", "response": "Kafka"}]},
            card={
                "fields": {"recommendation": "Mocny.", "english": None},
                "origins": {
                    "recommendation": {"origin": "note_ai"},
                },
            },
            rate={"amount": "150", "unit": "hourly", "currency": "pln"},
            note_import={"text": "Rozmowa: kafka 3 lata, stawka 150."},
        ),
        QUESTIONS,
    )


def test_note_import_needs_the_switch_and_some_text(monkeypatch):
    """Lustro dawnego `…/note/apply`: wyłączony odczyt notatki nie zostawia
    notatek z jego pochodzeniem; włączony — odmawia pustej notatki."""
    note = {"note_import": {"text": "Rozmowa: kafka 3 lata."}}
    monkeypatch.setattr(settings, "RECOMMENDATION_CARD_ASSIST_ENABLED", False)
    with pytest.raises(HTTPException) as off:
        form.validate_save(_input(**note), QUESTIONS)
    assert "wyłączone" in off.value.detail["message"]

    monkeypatch.setattr(settings, "RECOMMENDATION_CARD_ASSIST_ENABLED", True)
    form.validate_save(_input(**note), QUESTIONS)
    with pytest.raises(HTTPException) as empty:
        form.validate_save(_input(note_import={"text": "<p> </p>"}), QUESTIONS)
    assert "pusta" in empty.value.detail["message"]


def test_target_sheet_keeps_legacy_notes_unless_moved():
    sheet = form.SheetInput.model_validate(
        {
            "answers": [
                {"question_id": "q1", "response": " Kafka ", "keywords": "x"},
                {"question_id": "q1", "response": "duplikat"},
                {
                    "question_id": "q2",
                    "response": "Zdanie.",
                    "origin": "phrased",
                    "keywords": " hasła ",
                },
            ],
            "overall_fit": "fit",
        }
    )
    built = form._target_sheet(sheet, {"notes": "Stara notatka"})
    assert [a.question_id for a in built.answers] == ["q1", "q2"]
    assert built.answers[0].response == "Kafka"
    # Hasła zostają tylko przy zdaniu z haseł i odpowiedzi z notatki.
    assert built.answers[0].keywords is None
    assert built.answers[1].keywords == "hasła"
    assert built.notes == "Stara notatka"
    moved = form._target_sheet(
        sheet.model_copy(update={"clear_legacy_notes": True}),
        {"notes": "Stara notatka"},
    )
    assert moved.notes == ""


# ── Stawka strukturalna w propozycji z notatki ──────────────────────────────


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("165 zł/h netto B2B", 165.0),
        ("160/115", 115.0),
        ("14 000 zł", None),
        ("130–150 zł/h", None),
        ("40 EUR/h", None),
        ("1200 zł za MD", None),
    ],
)
def test_structured_rate_only_without_guessing(text, amount):
    out = assist.structured_rate(text)
    if amount is None:
        assert out is None
    else:
        assert out == {"amount": amount, "unit": "hourly", "currency": "PLN"}


def test_proposal_carries_the_structured_rate():
    proposal = assist.build_proposal(
        note="stawka 165 netto b2b",
        rule_fields={"rate": {"raw": "165 zł/h"}},
        rule_answers=[],
        model_fields={"english": {"value": "B2", "quote": "eng B2"}},
        model_answers={},
        current_fields={},
        questions={},
        current_answers={},
    )
    by_key = {item["key"]: item for item in proposal["fields"]}
    assert by_key["rate"]["rate"] == {
        "amount": 165.0,
        "unit": "hourly",
        "currency": "PLN",
    }
    assert "rate" not in by_key["english"]
