"""Rejestr faktów z rozmów: mapowanie, „nie ma”, nowe CV, flaga (08.11.2026)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import conversation_facts as facts
from app.services import scoring_service, skill_normalize
from app.services.conversation_facts import FactRow, build_projection
from app.services.cv_enrichment import CvWritePolicy, _apply_cv_enrichment
from app.services.dealbreaker_filters import missing_must_skills
from app.services.must_text_evidence import text_met_labels

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def taxonomy(monkeypatch):
    aliases = {
        "pl/sql": "pl/sql",
        "plsql": "pl/sql",
        "kafka": "kafka",
        "apache kafka": "kafka",
        "rabbitmq": "rabbitmq",
        "java": "java",
        "go": "go",
        "bankowość": "bankowość",
    }
    monkeypatch.setattr(skill_normalize, "ALIAS_TO_CANONICAL", aliases)
    monkeypatch.setattr(scoring_service, "ALIAS_MAP", aliases)
    monkeypatch.setattr(
        skill_normalize,
        "TECH_CANONICALS",
        {"pl/sql", "kafka", "rabbitmq", "java", "go"},
    )
    monkeypatch.setattr(scoring_service, "_CHAMPION_ALIAS_PATTERN", None)
    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", True)
    yield
    scoring_service._CHAMPION_ALIAS_PATTERN = None


def _row(
    value, terms, status="confirmed", source="sheet", job_id=7, at=NOW, kind="skill"
):
    return FactRow(
        kind=kind,
        value=value,
        value_key=facts.value_key(value),
        terms=tuple(terms),
        status=status,
        source=source,
        job_id=job_id,
        noted_at=at,
    )


def _candidate(rows=(), **kw):
    projection = build_projection(list(rows))
    data = {facts.PROJECTION_KEY: projection, **kw.pop("data", {})}
    base = dict(
        id=1,
        skills=[],
        verified_tech=None,
        tags=None,
        cv_extracted_data=data,
        raw_cv_text=None,
        experience=None,
        skills_manually_curated=False,
    )
    return SimpleNamespace(**{**base, **kw})


# ── Mapowanie ────────────────────────────────────────────────────────────────


def test_full_name_and_alias_map_to_the_dictionary():
    assert facts.map_requirement("Apache Kafka", "confirmed") == ["kafka"]
    assert facts.map_requirement("Java 8+", "absent") == ["java"]


def test_sentence_with_technology_counts_as_that_technology_when_confirmed():
    assert facts.map_requirement("Optymalizacja zapytań PL/SQL", "confirmed") == [
        "pl/sql"
    ]


def test_absent_sentence_stays_in_this_recruitment():
    """„Nie ma” przy zdaniu nie mówi, czego z niego brakuje."""
    assert facts.map_requirement("Optymalizacja zapytań PL/SQL", "absent") == []


def test_sentence_without_dictionary_term_is_job_only():
    assert facts.map_requirement("Prowadzenie warsztatów z klientem", "confirmed") == []


def test_alternatives_do_not_confirm_every_option():
    assert facts.map_requirement("Kafka lub RabbitMQ", "confirmed") == []
    assert facts.map_requirement("Kafka/RabbitMQ", "confirmed") == []
    assert facts.map_requirement("Brokery np. Kafka, RabbitMQ", "confirmed") == []


def test_common_word_alias_is_not_a_technology():
    assert facts.map_requirement("Chęć aby go wdrożyć", "confirmed") == []


# ── Projekcja ────────────────────────────────────────────────────────────────


def test_sheet_click_beats_a_newer_model_reading():
    rows = [
        _row("Kafka", ["kafka"], status="absent", at=NOW - timedelta(days=30)),
        _row("Kafka", ["kafka"], source="note_ai", job_id=None, at=NOW),
    ]
    projection = build_projection(rows)
    assert projection["absent"] == ["kafka"]
    assert projection["confirmed"] == []
    assert projection["skills"] == []


def test_newest_sheet_click_wins():
    rows = [
        _row("Kafka", ["kafka"], status="absent", job_id=1, at=NOW - timedelta(days=1)),
        _row("Kafka", ["kafka"], job_id=2, at=NOW),
    ]
    assert build_projection(rows)["confirmed"] == ["kafka"]


def test_model_reading_without_dictionary_term_stays_a_fact_about_the_person():
    projection = build_projection([_row("Vertica", [], source="note_ai", job_id=None)])
    assert projection["skills"] == ["Vertica"]
    assert projection["texts"] == ["Vertica"]


def test_sheet_sentence_goes_only_to_its_recruitment():
    sentence = "Prowadzenie warsztatów"
    projection = build_projection([_row(sentence, [])])
    assert projection["skills"] == []
    assert projection["texts"] == []
    assert projection["jobs"]["7"]["confirmed"] == [facts.value_key(sentence)]


def test_only_skill_kind_reaches_the_skill_list():
    rows = [_row("Bankowość", ["bankowość"], kind="domain")]
    assert build_projection(rows)["skills"] == []


# ── Bramka i warstwa skills ──────────────────────────────────────────────────


def test_confirmed_fact_passes_the_gate_without_cv_trace():
    candidate = _candidate([_row("Kafka", ["kafka"])])
    assert missing_must_skills(candidate, ["Kafka"]) == []


def test_absent_fact_beats_the_cv():
    candidate = _candidate(
        [_row("Kafka", ["kafka"], status="absent")],
        raw_cv_text="Kafka Streams w banku",
        skills=[{"name": "Kafka"}],
    )
    assert missing_must_skills(candidate, ["Kafka"]) == ["Kafka"]
    assert "kafka" not in scoring_service.candidate_skill_names(candidate)


def test_one_absent_option_leaves_the_other():
    candidate = _candidate(
        [_row("Kafka", ["kafka"], status="absent")],
        raw_cv_text="RabbitMQ na produkcji i Kafka w CV",
    )
    assert missing_must_skills(candidate, ["Kafka lub RabbitMQ"]) == []
    only_kafka = _candidate(
        [_row("Kafka", ["kafka"], status="absent")], raw_cv_text="Kafka w CV"
    )
    assert missing_must_skills(only_kafka, ["Kafka lub RabbitMQ"]) == [
        "Kafka lub RabbitMQ"
    ]


def test_sentence_counts_only_in_its_own_recruitment():
    sentence = "Prowadzenie warsztatów"
    candidate = _candidate([_row(sentence, [], job_id=7)])
    assert text_met_labels(candidate, [sentence], job_id=7) == frozenset({sentence})
    assert text_met_labels(candidate, [sentence], job_id=8) == frozenset()
    assert text_met_labels(candidate, [sentence]) == frozenset()


def test_curated_list_is_not_widened_but_absent_still_narrows():
    candidate = _candidate(
        [_row("Kafka", ["kafka"]), _row("Java", ["java"], status="absent")],
        skills=[{"name": "Java"}],
        skills_manually_curated=True,
    )
    assert scoring_service.candidate_known_skill_names(candidate) == set()


def test_flag_off_ignores_the_projection(monkeypatch):
    candidate = _candidate(
        [_row("Kafka", ["kafka"], status="absent")],
        raw_cv_text="Kafka Streams",
        skills=[{"name": "Kafka"}],
    )
    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", False)
    assert missing_must_skills(candidate, ["Kafka"]) == []
    assert "kafka" in scoring_service.candidate_skill_names(candidate)
    assert facts.revision(candidate) is None


# ── Lista umiejętności ───────────────────────────────────────────────────────


def test_merge_adds_only_missing_names_and_keeps_case():
    skills, written, added = facts.merge_skill_names(
        [{"name": "kafka", "level": "senior"}], ["Kafka", "PL/SQL"], []
    )
    assert skills == [
        {"name": "kafka", "level": "senior"},
        {"name": "PL/SQL", "level": None},
    ]
    assert written == ["PL/SQL"]
    assert added == 1


def test_retracted_fact_removes_only_what_the_register_wrote():
    skills, written, added = facts.merge_skill_names(
        [{"name": "PL/SQL", "level": None}, {"name": "Java", "level": None}],
        [],
        ["PL/SQL"],
    )
    assert skills == [{"name": "Java", "level": None}]
    assert written == []
    assert added == 0


def test_new_cv_does_not_wipe_conversation_skills():
    projection = {**build_projection([_row("Kafka", ["kafka"])]), "written": ["Kafka"]}
    candidate = SimpleNamespace(
        name="A",
        lastname="B",
        email="a@b.pl",
        phone="1",
        city="X",
        linkedin="x",
        skills=[{"name": "Kafka", "level": None}, {"name": "Java", "level": None}],
        education=None,
        years_it_experience=None,
        ai_summary=None,
        experience=[],
        cv_parsed_at=None,
        skills_manually_curated=False,
        country="PL",
        location="X",
        cv_extracted_data={facts.PROJECTION_KEY: projection},
    )
    _apply_cv_enrichment(
        candidate,
        {"skills": [{"name": "Python", "level": None}]},
        policy=CvWritePolicy.REFRESH,
    )
    assert [s["name"] for s in candidate.skills] == ["Python", "Kafka"]
    assert candidate.cv_extracted_data[facts.PROJECTION_KEY]["written"] == ["Kafka"]


def test_new_cv_with_the_same_skill_takes_ownership_away_from_the_register():
    projection = {**build_projection([_row("Kafka", ["kafka"])]), "written": ["Kafka"]}
    candidate = SimpleNamespace(
        skills=[],
        cv_extracted_data={facts.PROJECTION_KEY: projection},
    )
    candidate.skills = [{"name": "kafka", "level": None}]
    next_extracted = dict(candidate.cv_extracted_data)
    facts.reapply_after_cv(candidate, next_extracted)
    assert next_extracted[facts.PROJECTION_KEY]["written"] == []


def test_flag_off_new_cv_replaces_the_list(monkeypatch):
    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", False)
    projection = {**build_projection([_row("Kafka", ["kafka"])]), "written": ["Kafka"]}
    candidate = SimpleNamespace(skills=[{"name": "Python", "level": None}])
    next_extracted = {facts.PROJECTION_KEY: projection}
    facts.reapply_after_cv(candidate, next_extracted)
    assert candidate.skills == [{"name": "Python", "level": None}]


# ── Wejście z arkusza ────────────────────────────────────────────────────────


def test_sheet_checks_take_only_decided_rows():
    checks = facts.sheet_checks(
        [
            {
                "kind": "skills",
                "name": "  Kafka ",
                "status": "confirmed",
                "note": "2 lata",
            },
            {"kind": "domains", "name": "Bankowość", "status": "not_confirmed"},
            {"kind": "skills", "name": "Java", "status": "unknown"},
            {"kind": "nowy", "name": "X", "status": "confirmed"},
            "zepsuty",
        ]
    )
    assert checks == [
        facts.SheetCheck("skill", "Kafka", "confirmed", "2 lata"),
        facts.SheetCheck("domain", "Bankowość", "absent"),
    ]


# ── Dobór kart ───────────────────────────────────────────────────────────────

LABELS = [("nordea", 1, "Nordea")]


def test_veto_from_notes_blocks_that_client_only():
    insights = {"client_vetoes": [{"client": "Nordea Bank Abp", "reason": "Nie chce"}]}
    assert facts.vetoes_client(insights, LABELS)
    assert not facts.vetoes_client(insights, [("pko", 2, "PKO")])


def test_no_history_with_client_is_not_a_veto():
    insights = {
        "client_vetoes": [
            {"client": "Nordea", "reason": "Nie pracował wcześniej w Nordei."}
        ]
    }
    assert not facts.vetoes_client(insights, LABELS)


def test_not_looking_uses_the_date_in_text():
    today = NOW.date()
    assert facts.not_looking_now({"not_looking_until": "2026-12"}, today)
    assert not facts.not_looking_now({"not_looking_until": "2026-05-05"}, today)


def test_not_looking_without_date_lasts_half_a_year_from_reading():
    today = NOW.date()
    fresh = {
        "not_looking_until": "za pół roku",
        "_v2_extracted_at": "2026-09-01T00:00:00+00:00",
    }
    old = {**fresh, "_v2_extracted_at": "2025-09-01T00:00:00+00:00"}
    assert facts.not_looking_now(fresh, today)
    assert not facts.not_looking_now(old, today)
    assert not facts.not_looking_now({"not_looking_until": None}, today)


async def test_blocked_for_job_does_nothing_with_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", False)
    assert await facts.blocked_for_job(None, 1, [1, 2]) == set()


# ── Kolejka ──────────────────────────────────────────────────────────────────


def test_note_event_reads_notes_first_and_sheet_event_does_not(monkeypatch):
    from app.services.auto_match_outbox import conversation_reading_needed

    monkeypatch.setattr(settings, "NOTES_INSIGHTS_SYNC_ENABLED", True)
    note = SimpleNamespace(trigger="conversation", profile_revision="note:5")
    sheet = SimpleNamespace(trigger="conversation", profile_revision="abc+f1")
    cv = SimpleNamespace(trigger="cv_upload", profile_revision="note:5")
    assert conversation_reading_needed(note)
    assert not conversation_reading_needed(sheet)
    assert not conversation_reading_needed(cv)


def test_revision_includes_facts_only_with_flag(monkeypatch):
    from app.services.auto_match_outbox import candidate_revision

    data = {
        "cv_highlights": {"source_hash": "h" * 64},
        facts.PROJECTION_KEY: {"rev": "abc123def456"},
    }
    candidate = SimpleNamespace(cv_extracted_data=data, cv_parsed_at=None)
    assert candidate_revision(candidate) == "h" * 49 + "+abc123def456"
    assert len(candidate_revision(candidate)) <= 64
    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", False)
    assert candidate_revision(candidate) == "h" * 64


# ── Silniki wyszukiwania ─────────────────────────────────────────────────────


def _sql(clause) -> str:
    from sqlalchemy.dialects import postgresql

    return str(clause.compile(dialect=postgresql.dialect()))


def test_v2_search_reads_the_register_and_v1_does_not():
    from app.services.candidate_search_predicates import Semantics, skill_match

    v2 = _sql(skill_match("Kafka", Semantics(version=2, engine="list")))
    assert "_conversation_facts" in v2 or "cv_extracted_data" in v2
    assert "?|" in v2
    v1 = _sql(skill_match("Kafka", None))
    assert "cv_extracted_data" not in v1


def test_search_ignores_the_register_with_flag_off(monkeypatch):
    from app.services.candidate_search_predicates import Semantics, skill_match

    monkeypatch.setattr(settings, "CONVERSATION_FACTS_ENABLED", False)
    assert "cv_extracted_data" not in _sql(
        skill_match("Kafka", Semantics(version=2, engine="list"))
    )
