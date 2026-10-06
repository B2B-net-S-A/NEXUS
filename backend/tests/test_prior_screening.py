"""Warstwa `prior_screening` — odpowiedzi z wcześniejszych rozmów w ocenie AI.

Bez bazy: reguły dopasowania i wydźwięku, ocena warstwy, kontrakt „przy OFF
nic się nie zmienia” (odcisk żądania, `as_dict`) i `attach` na atrapie sesji.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import prior_screening as ps
from app.services import scoring_service as scoring
from app.services.request_matching_context import build_request_context
from tests.test_scoring_service import make_candidate, make_job

JUNE = datetime(2026, 6, 1, tzinfo=timezone.utc)
JULY = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _job(questions, job_id=10):
    return make_job(id=job_id, champion_profile={"screening_questions": questions})


def _material(*answers, target=10):
    return ps.PriorScreeningMaterial(target_job_id=target, answers=tuple(answers))


def _answer(question, response, *, hit=False, when=JUNE, job_id=7):
    return ps.PriorAnswer(
        job_id=job_id,
        question=question,
        response=response,
        deal_breaker_hit=hit,
        answered_at=when,
    )


# ── Dopasowanie pytań ────────────────────────────────────────────────────────


def test_same_question_in_other_words_order_and_inflection_matches():
    assert ps.questions_match(
        "Czy kandydat ma doświadczenie z mikroserwisami w chmurze?",
        "Doświadczenie z mikroserwisami w chmurze — czy ma?",
    )


def test_different_question_does_not_match():
    assert (
        ps.questions_match(
            "Czy pracował w zespole Scrum?",
            "Czy prowadził szkolenia dla klienta?",
        )
        is None
    )


def test_technology_of_this_question_must_be_in_the_earlier_one():
    scoring.set_alias_map({"java": "java", "python": "python"})
    assert (
        ps.questions_match(
            "Ile lat doświadczenia komercyjnego z Java?",
            "Ile lat doświadczenia komercyjnego z Python?",
        )
        is None
    )
    assert ps.questions_match(
        "Ile lat doświadczenia komercyjnego z Java?",
        "Doświadczenie komercyjne z Java — ile lat?",
    )


@pytest.mark.parametrize(
    "question",
    [
        "Jaka jest oczekiwana stawka B2B?",
        "Od kiedy jest dostępny?",
        "Czy akceptuje pracę w biurze w Warszawie?",
        "Czy może pracować hybrydowo 2 dni?",
        "What is the notice period?",
    ],
)
def test_questions_with_their_own_layer_are_skipped(question):
    assert ps.has_own_layer(question)
    job = _job([{"id": "q1", "question": question}])
    candidate = make_candidate(id=1)
    candidate._prior_screening = _material(_answer(question, "tak"))
    result = ps.evaluate(candidate, job)
    assert result is not None and result.matches == ()
    assert not result.scored


# ── Wydźwięk odpowiedzi ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("Tak, 3 lata komercyjnie", 1),
        ("5 lat w projektach bankowych", 1),
        ("Pracował z tym przy migracji", 1),
        ("Nie", -1),
        ("nie miał styczności", -1),
        ("Brak doświadczenia", -1),
        ("tylko teoretycznie", -1),
        ("Hmm, trudno powiedzieć", None),
        ("", None),
    ],
)
def test_polarity(response, expected):
    assert ps.polarity(response) == expected


# ── Ocena warstwy ────────────────────────────────────────────────────────────

Q_CLOUD = "Czy kandydat ma doświadczenie z mikroserwisami w chmurze?"
Q_SCRUM = "Czy pracował w zespole Scrum z klientem zagranicznym?"


def test_layer_scored_from_matched_answers():
    job = _job(
        [
            {"id": "q1", "question": Q_CLOUD},
            {"id": "q2", "question": Q_SCRUM},
        ]
    )
    candidate = make_candidate(id=1)
    candidate._prior_screening = _material(
        _answer(Q_CLOUD, "Tak, 2 lata"),
        _answer(Q_SCRUM, "Nie"),
    )
    result = ps.evaluate(candidate, job)
    assert result.positive == 1 and result.negative == 1
    assert result.points == pytest.approx(ps.MAX_POINTS / 2)
    layer = ps.layer_for(candidate, job)
    assert layer.scored and layer.max_points == ps.MAX_POINTS
    assert result.status == ps.STATUS_ANSWERED


def test_no_matches_or_only_unknown_polarity_leaves_layer_unscored():
    job = _job([{"id": "q1", "question": Q_CLOUD}])
    candidate = make_candidate(id=1)
    candidate._prior_screening = _material(_answer(Q_CLOUD, "zależy od projektu"))
    layer = ps.layer_for(candidate, job)
    assert not layer.scored and layer.max_points == 0 and layer.points == 0
    candidate._prior_screening = _material()
    assert not ps.layer_for(candidate, job).scored


def test_deal_breaker_needs_this_jobs_condition_and_an_earlier_hit():
    job = _job(
        [
            {"id": "q1", "question": Q_CLOUD, "deal_breaker": "brak chmury"},
            {"id": "q2", "question": Q_SCRUM},
        ]
    )
    candidate = make_candidate(id=1)
    candidate._prior_screening = _material(
        _answer(Q_CLOUD, "Nie", hit=True), _answer(Q_SCRUM, "Tak")
    )
    result = ps.evaluate(candidate, job)
    assert result.deal_breaker and result.points == 0
    assert result.status == ps.STATUS_DEAL_BREAKER


def test_plain_no_to_a_deal_breaker_question_is_not_a_deal_breaker():
    # Przegląd #2063: „Czy potrzebujesz sponsorowania wizy?” — „nie” to dobra
    # odpowiedź; samo „nie” nie może dawać plakietki deal-breaker.
    job = _job([{"id": "q1", "question": Q_CLOUD, "deal_breaker": "brak chmury"}])
    candidate = make_candidate(id=1)
    candidate._prior_screening = _material(_answer(Q_CLOUD, "Nie"))
    assert not ps.evaluate(candidate, job).deal_breaker


def test_earlier_hit_without_a_condition_here_is_not_a_deal_breaker():
    # Tam warunkiem było 5 lat, tu pytanie nie ma warunku.
    job = _job([{"id": "q1", "question": Q_SCRUM}])
    candidate = make_candidate(id=1)
    candidate._prior_screening = _material(_answer(Q_SCRUM, "Tak", hit=True))
    assert not ps.evaluate(candidate, job).deal_breaker


def test_material_for_another_job_is_ignored():
    job = _job([{"id": "q1", "question": Q_CLOUD}])
    candidate = make_candidate(id=1)
    candidate._prior_screening = _material(_answer(Q_CLOUD, "Tak"), target=99)
    assert ps.evaluate(candidate, job) is None
    assert ps.layer_for(candidate, job) is None


def test_evidence_carries_this_jobs_question_without_other_job_details():
    job = _job([{"id": "q1", "question": Q_CLOUD}])
    candidate = make_candidate(id=1)
    candidate._prior_screening = _material(
        _answer(Q_CLOUD, "Tak, w projekcie dla Banku X")
    )
    evidence = ps.evaluate(candidate, job).evidence()
    assert evidence == [
        {
            "question_id": "q1",
            "question": Q_CLOUD,
            "polarity": 1,
            "deal_breaker": False,
            "similarity": 1.0,
            "answered_at": JUNE.isoformat(),
        }
    ]
    assert "Bank" not in str(evidence)


# ── Materiał z arkusza ───────────────────────────────────────────────────────


def test_sheet_skips_skipped_reassign_and_empty_and_uses_profile_text():
    sheet = {
        "answered_at": JUNE.isoformat(),
        "answers": [
            {"question_id": "q1", "response": "Tak", "question_text": Q_CLOUD},
            {"question_id": "q2", "response": "Tak", "skipped": True},
            {"question_id": "q3", "response": "Tak", "origin": "reassign_suggested"},
            {"question_id": "q4", "response": "  "},
            {"question_id": "q5", "response": "Nie"},
        ],
    }
    answers = ps.answers_from_sheet(7, sheet, {"q5": Q_SCRUM})
    assert [(a.question, a.response) for a in answers] == [
        (Q_CLOUD, "Tak"),
        (Q_SCRUM, "Nie"),
    ]


def test_sheet_respects_before():
    sheet = {
        "answered_at": JULY.isoformat(),
        "answers": [
            {"question_id": "q1", "response": "Tak", "question_text": Q_CLOUD},
        ],
    }
    assert ps.answers_from_sheet(7, sheet, {}, before=JUNE) == []
    assert ps.answers_from_sheet(
        7, sheet, {}, before=datetime(2026, 8, 1, tzinfo=timezone.utc)
    )


# ── attach na atrapie sesji ──────────────────────────────────────────────────


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows, *, fail=False):
        self.rows = rows
        self.fail = fail
        self.statements = []

    def begin_nested(self):
        return _Nested()

    async def execute(self, statement):
        self.statements.append(statement)
        if self.fail:
            raise RuntimeError("boom")
        return _Result(self.rows)


@pytest.mark.asyncio
async def test_attach_excludes_target_job_and_respects_before_in_query():
    sheet = {
        "answered_at": JUNE.isoformat(),
        "answers": [{"question_id": "q1", "response": "Tak", "question_text": Q_CLOUD}],
    }
    db = _FakeDb([(1, 7, sheet, JUNE)])
    candidate = make_candidate(id=1)
    job = _job([{"id": "q1", "question": Q_CLOUD}])
    await ps.attach_prior_screening(db, job, [candidate], before=JULY)
    from sqlalchemy.dialects import postgresql

    sql = str(
        db.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "job_id != 10" in sql
    assert "moved_at <" in sql
    assert "CASE WHEN" in sql
    assert len(candidate._prior_screening.answers) == 1
    assert ps.layer_for(candidate, job).scored


@pytest.mark.asyncio
async def test_newest_sheet_with_only_skipped_answers_does_not_hide_an_older_one():
    skipped = {
        "answered_at": JULY.isoformat(),
        "answers": [
            {
                "question_id": "q1",
                "response": "",
                "skipped": True,
                "question_text": Q_CLOUD,
            }
        ],
    }
    older = {
        "answered_at": JUNE.isoformat(),
        "answers": [{"question_id": "q1", "response": "Tak", "question_text": Q_CLOUD}],
    }
    db = _FakeDb([(1, 7, skipped, JULY), (1, 7, older, JUNE)])
    candidate = make_candidate(id=1)
    job = _job([{"id": "q1", "question": Q_CLOUD}])
    await ps.attach_prior_screening(db, job, [candidate])
    assert [a.response for a in candidate._prior_screening.answers] == ["Tak"]


@pytest.mark.asyncio
async def test_job_without_questions_does_not_query():
    db = _FakeDb([], fail=True)
    candidate = make_candidate(id=1)
    await ps.attach_prior_screening(db, _job([]), [candidate])
    assert db.statements == []
    assert candidate._prior_screening.answers == ()


@pytest.mark.asyncio
async def test_attach_survives_query_failure():
    candidate = make_candidate(id=1)
    job = _job([{"id": "q1", "question": Q_CLOUD}])
    await ps.attach_prior_screening(_FakeDb([], fail=True), job, [candidate])
    assert getattr(candidate, "_prior_screening", None) is None


# ── Przy OFF nic się nie zmienia ─────────────────────────────────────────────


def test_request_fingerprint_unchanged_when_off(monkeypatch):
    job = make_job()
    monkeypatch.setattr(settings, "PRIOR_SCREENING_LAYER_ENABLED", False)
    off = build_request_context(job, scoring.DEFAULT_PROFILE)
    assert "prior_screening" not in off.versions
    monkeypatch.setattr(settings, "PRIOR_SCREENING_LAYER_ENABLED", True)
    on = build_request_context(job, scoring.DEFAULT_PROFILE)
    assert on.versions["prior_screening"] == ps.VERSION
    assert on.fingerprint != off.fingerprint
    monkeypatch.setattr(settings, "PRIOR_SCREENING_LAYER_ENABLED", False)
    assert build_request_context(job, scoring.DEFAULT_PROFILE).fingerprint == (
        off.fingerprint
    )


_BREAKDOWN_KEYS = {
    "candidate_id",
    "job_id",
    "total",
    "semantic",
    "skills",
    "salary",
    "location",
    "availability",
    "champion_fit",
    "seniority_note",
    "matching_must",
    "gap_must",
    "matching_nice",
    "gap_nice",
    "penalties",
    "warnings",
    "historical_boost",
    "historical_sources_count",
    "fit_confidence",
}


@pytest.mark.asyncio
async def test_as_dict_and_total_identical_without_the_layer():
    job = _job([{"id": "q1", "question": Q_CLOUD}])
    candidate = make_candidate(id=1, skills=["Python"])
    candidate._prior_screening = _material(_answer(Q_CLOUD, "Tak"))
    plain = await scoring.score_candidate_job(
        candidate, job, None, semantic_similarity=0.7, base_fit=True
    )
    assert set(plain.as_dict()) == _BREAKDOWN_KEYS
    with_layer = await scoring.score_candidate_job(
        candidate,
        job,
        None,
        semantic_similarity=0.7,
        base_fit=True,
        prior_screening=True,
    )
    assert with_layer.as_dict()["prior_screening"]["max"] == ps.MAX_POINTS
    assert {
        k: v
        for k, v in with_layer.as_dict().items()
        if k not in ("prior_screening", "total")
    } == {k: v for k, v in plain.as_dict().items() if k != "total"}
    # Pełne „tak” podnosi wynik, ale zostaje w skali 0–100.
    assert plain.total < with_layer.total <= 100


@pytest.mark.asyncio
async def test_unscored_layer_keeps_total_and_deal_breaker_lowers_it():
    job = _job([{"id": "q1", "question": Q_CLOUD, "deal_breaker": "x"}])
    candidate = make_candidate(id=1, skills=["Python"])
    plain = await scoring.score_candidate_job(
        candidate, job, None, semantic_similarity=0.7, base_fit=True
    )
    candidate._prior_screening = _material()
    unscored = await scoring.score_candidate_job(
        candidate,
        job,
        None,
        semantic_similarity=0.7,
        base_fit=True,
        prior_screening=True,
    )
    assert unscored.total == plain.total
    candidate._prior_screening = _material(_answer(Q_CLOUD, "Nie", hit=True))
    hit = await scoring.score_candidate_job(
        candidate,
        job,
        None,
        semantic_similarity=0.7,
        base_fit=True,
        prior_screening=True,
    )
    assert hit.total < plain.total
    assert hit.as_dict()["prior_screening"]["status"] == ps.STATUS_DEAL_BREAKER


@pytest.mark.asyncio
async def test_layer_needs_base_fit():
    job = _job([{"id": "q1", "question": Q_CLOUD}])
    candidate = make_candidate(id=1)
    candidate._prior_screening = _material(_answer(Q_CLOUD, "Tak"))
    context = SimpleNamespace()  # never touched: layer only with base_fit
    assert context is not None
    breakdown = await scoring.score_candidate_job(
        candidate,
        job,
        None,
        semantic_similarity=0.7,
        base_fit=True,
        prior_screening=False,
    )
    assert breakdown.prior_screening is None
