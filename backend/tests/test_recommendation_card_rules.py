"""Karta rekomendacji — czyste reguły (bez bazy). Dane wyłącznie fikcyjne."""

from datetime import datetime, timezone

from app.services import recommendation_card_rules as rules
from app.services.recommendation_card_rules import NoteInput


def _at(day: int) -> datetime:
    return datetime(2026, 9, day, 10, 0, tzinfo=timezone.utc)


_CARD = (
    "Imię i nazwisko: Tomasz Wzorcowy\nStawka: 135 zł/h\nDostępność: 1 miesiąc\n"
    "Tryb pracy: hybrydowo, 2 dni w tygodniu w Łodzi\nLokalizacja: Łódź\n"
    "Narodowość: polska\nCzy pracował u Klienta: nie\nAngielski: C1\n"
    "P1: Opisz doświadczenie z Javą.\nOdpowiedź: Java 21 w banku.\n"
    "Red flags: brak\nNotatka: mocny w Springu\nMotywacja: szuka większego projektu"
)


def test_newer_note_wins_field_by_field_and_remembers_its_source():
    fields, answers = rules.project_notes(
        [
            NoteInput(id=2, content="Stawka: 140 zł/h\nAngielski: B2", at=_at(5)),
            NoteInput(id=1, content=_CARD, at=_at(1)),
        ]
    )

    assert fields["rate"]["value"] == 140.0
    assert fields["rate"]["note_id"] == 2
    assert fields["english"]["level"] == "B2"
    # Pole, którego nowsza notatka nie ma, zostaje ze starszej.
    assert fields["location"]["raw"] == "Łódź"
    assert fields["location"]["note_id"] == 1
    assert answers["note_id"] == 1
    assert answers["items"][0]["answer"] == "Java 21 w banku."


def test_candidate_name_is_not_stored_on_the_card():
    fields, _ = rules.project_notes([NoteInput(id=1, content=_CARD, at=_at(1))])
    assert "name" not in fields


def test_note_that_is_not_a_card_contributes_nothing():
    fields, answers = rules.project_notes(
        [NoteInput(id=1, content="dzwoniłem, oddzwoni jutro", at=_at(1))]
    )
    assert fields == {} and answers == {}


def test_note_without_timezone_sorts_with_aware_ones():
    fields, _ = rules.project_notes(
        [
            NoteInput(id=1, content="Stawka: 120\nDostępność: ASAP", at=_at(1)),
            NoteInput(
                id=2,
                content="Stawka: 130\nDostępność: ASAP",
                at=datetime(2026, 9, 3, 10, 0),
            ),
        ]
    )
    assert fields["rate"]["note_id"] == 2


def test_manual_field_always_wins_over_the_note():
    notes, _ = rules.project_notes([NoteInput(id=1, content=_CARD, at=_at(9))])
    manual = {"rate": rules.manual_value("rate", "150", user_id=7, now=_at(2))}

    current, previous = rules.split_fields(notes, manual)

    assert current["rate"]["value"] == 150.0
    assert current["rate"]["source"] == "manual"
    assert current["rate"]["by"] == 7
    assert current["location"]["source"] == "note"
    assert previous == {}


def test_card_is_complete_only_with_all_ten_fields():
    notes, _ = rules.project_notes([NoteInput(id=1, content=_CARD, at=_at(1))])
    current, _ = rules.split_fields(notes, {})
    assert rules.completeness(current) == {
        "status": "complete",
        "filled": 10,
        "total": 10,
        "missing": [],
    }

    partial, _ = rules.split_fields(
        {key: value for key, value in notes.items() if key != "english"}, {}
    )
    assert rules.completeness(partial)["missing"] == ["english"]
    assert rules.completeness(partial)["status"] == "partial"
    assert rules.completeness({})["status"] == "empty"


def test_values_from_before_the_current_attempt_are_only_hints():
    notes, answers = rules.project_notes([NoteInput(id=1, content=_CARD, at=_at(1))])
    manual = {
        "nationality": rules.manual_value(
            "nationality", "polska", user_id=7, now=_at(20)
        )
    }

    current, previous = rules.split_fields(notes, manual, attempt_started=_at(10))

    assert set(current) == {"nationality"}
    assert previous["rate"]["value"] == 135.0
    assert rules.completeness(current)["filled"] == 1
    assert rules.current_answers(answers, attempt_started=_at(10)) is None
    assert rules.current_answers(answers)["items"][0]["number"] == 1


def test_empty_values_do_not_count_as_filled():
    current, _ = rules.split_fields({"rate": {"raw": "  "}}, {"english": "C1"})
    assert current == {}


def test_legacy_text_keeps_the_department_template_order():
    notes, answers = rules.project_notes([NoteInput(id=1, content=_CARD, at=_at(1))])
    current, _ = rules.split_fields(notes, {})

    text = rules.legacy_text(
        current,
        answers["items"],
        candidate_name="Tomasz Wzorcowy",
        project="ZOB-0001",
    )

    assert text.split("\n") == [
        "Imię i nazwisko: Tomasz Wzorcowy",
        "Stawka: 135 zł/h",
        "Dostępność: 1 miesiąc",
        "Tryb pracy: hybrydowo, 2 dni w tygodniu w Łodzi",
        "Lokalizacja: Łódź",
        "Narodowość: polska",
        "Czy pracował u Klienta: nie",
        "Angielski: C1",
        "Nazwa projektu: ZOB-0001",
        "Nazwa pliku CV:",
        "P1: Opisz doświadczenie z Javą.",
        "Odpowiedź: Java 21 w banku.",
        "Red flags: brak",
        "Notatka: mocny w Springu",
        "Motywacja: szuka większego projektu",
    ]


def test_every_editable_field_has_a_label_and_a_limit():
    for key in rules.EDITABLE_FIELDS:
        assert rules.LABELS[key]
        assert rules.max_length(key) in (rules.LINE_MAX, rules.TEXT_MAX)
    assert set(rules.REQUIRED_FIELDS) <= set(rules.EDITABLE_FIELDS)


def test_questions_take_the_sheet_answer_then_the_note_answer():
    questions = {"q1": "Java 17+ i Spring Boot?", "q2": "Kolejki?", "q3": "Chmura?"}
    sheet = [
        {"question_id": "q1", "response": "Java 21, Spring Boot 3."},
        {"question_id": "q2", "response": "pominięte", "skipped": True},
    ]
    note = [
        {"number": 1, "question": "", "answer": "z notatki 1"},
        {"number": 2, "question": "", "answer": "Kafka do zdarzeń."},
    ]

    merged = rules.merge_questions(questions, sheet, note)

    assert merged == [
        {
            "number": 1,
            "question": "Java 17+ i Spring Boot?",
            "answer": "Java 21, Spring Boot 3.",
            "source": "sheet",
        },
        {
            "number": 2,
            "question": "Kolejki?",
            "answer": "Kafka do zdarzeń.",
            "source": "note",
        },
        {"number": 3, "question": "Chmura?", "answer": "", "source": None},
    ]


def test_job_without_champion_questions_shows_the_questions_from_the_note():
    note = [{"number": 1, "question": "Opisz projekt.", "answer": "Bank, 3 lata."}]
    assert rules.merge_questions({}, [], note) == [
        {
            "number": 1,
            "question": "Opisz projekt.",
            "answer": "Bank, 3 lata.",
            "source": "note",
        }
    ]
    assert rules.merge_questions({}, [], []) == []


def test_note_items_without_a_usable_number_fall_back_to_their_position():
    note = [
        {"number": "x", "question": "", "answer": "pierwsza"},
        {"number": None, "question": "", "answer": "druga"},
    ]
    merged = rules.merge_questions({"q1": "A?", "q2": "B?"}, [], note)
    assert [item["answer"] for item in merged] == ["pierwsza", "druga"]
