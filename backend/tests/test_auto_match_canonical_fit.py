"""Auto-match liczy wynik pary tak jak „Dop.” (21.10.2026).

Do tej daty `run_candidate_event` i `run_job_event` wołały stary scoring
(`rank_jobs_for_candidate` / `rank_candidates_for_job`) z wagami wbudowanymi,
więc próg `AUTO_MATCH_MIN_SCORE` mierzył inną skalę niż procent na ekranach
i nocny przegląd, a profil wag z `/settings/scoring` nie miał na niego wpływu.

Kontrakty:

- wynik, który dostaje `decide()`, to kanoniczny fit z profilem BEZ
  użytkownika (globalny albo klienta rekrutacji) — w obu kierunkach;
- czarna lista, konflikt i wykluczenie klienta dalej blokują (`penalized`),
  choć kanoniczny fit ich nie niesie;
- para bez pomiaru nie dostaje decyzji: zdarzenie CV wraca do kolejki,
  w zdarzeniu rekrutacji ta osoba jest pomijana.

Bez bazy: sesja i wszystko poza ścieżką wyniku jest podstawione.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import auto_match_service as ams

LEGACY_TOTAL = 62.0
CANONICAL_FIT = 74.0
CLIENT_ID = 31
JOB_ID = 501
CANDIDATE_ID = 7001


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDb:
    """Odpowiada na `get` i kolejne `scalars` w kolejności wywołań."""

    def __init__(self, *, by_key, scalars):
        self._by_key = by_key
        self._scalars = list(scalars)

    async def get(self, model, key):
        return self._by_key.get((model.__name__, key))

    async def scalars(self, _stmt):
        return _Rows(self._scalars.pop(0))

    async def commit(self):
        return None


def _job():
    from app.models.job import JobStatus

    return SimpleNamespace(
        id=JOB_ID,
        client_id=CLIENT_ID,
        status=JobStatus.published,
        work_state="searching",
        updated_at=None,
        created_at=None,
        recruiter_id=None,
        tac_id=None,
        title="Rekrutacja testowa",
    )


def _candidate():
    return SimpleNamespace(
        id=CANDIDATE_ID,
        name="Kandydat",
        lastname="Testowy",
        cv_extracted_data={"cv_highlights": {"source_hash": "rev-1"}},
        cv_parsed_at=None,
    )


def _breakdown(candidate_id, job_id, total, *, penalties=(), warnings=()):
    return SimpleNamespace(
        candidate_id=candidate_id,
        job_id=job_id,
        total=total,
        matching_must=["Python"],
        gap_must=[],
        penalties=list(penalties),
        warnings=list(warnings),
    )


@pytest.fixture
def world(monkeypatch):
    """Podstawia wszystko poza wynikiem pary; zwraca zapis wywołań."""
    from app.services import (
        canonical_fit,
        dealbreaker_filters,
        embedding_service,
        full_search_measurement,
        pipeline_eligibility,
        requirement_contract,
        request_matching_context,
        scoring_service,
    )

    seen = {
        "profiles": [],
        "logged": [],
        "proposed": [],
        "measurement": "measured",
        "penalties": (),
        "warnings": (),
        "warmed": [],
    }
    monkeypatch.setattr(settings, "AUTO_MATCH_MODE", "propose")
    monkeypatch.setattr(settings, "AUTO_MATCH_MIN_SCORE", 70.0)
    monkeypatch.setattr(settings, "AUTO_MATCH_REQUIRE_MUST", True)

    async def scoped(query_text, *, jobs_collection, ids):
        return {i: 0.8 for i in ids}

    async def eligible(db, *, job, candidates, now):
        return list(candidates)

    async def nothing(*args, **kwargs):
        return None

    async def none_logged(db, pairs, revisions, *, since=None):
        return set()

    async def write_log(db, *, decisions, **kwargs):
        seen["logged"] += list(decisions)

    async def publish(db, *, decisions, **kwargs):
        seen["proposed"] += [d for d in decisions if d.decision == "proposed"]
        return {}

    async def notify(db, **kwargs):
        return 0

    monkeypatch.setattr(ams, "scoped_similarity", scoped)
    monkeypatch.setattr(ams, "attach_gate_evidence", nothing)
    monkeypatch.setattr(ams, "_logged_pairs", none_logged)
    monkeypatch.setattr(ams, "_write_log", write_log)
    monkeypatch.setattr(ams, "_publish_proposals", publish)
    monkeypatch.setattr(ams, "_notify", notify)
    monkeypatch.setattr(
        embedding_service, "_build_candidate_text", lambda c, **kw: "cv"
    )
    monkeypatch.setattr(embedding_service, "_build_job_text", lambda j, **kw: "job")
    monkeypatch.setattr(pipeline_eligibility, "filter_eligible_candidates", eligible)
    monkeypatch.setattr(
        requirement_contract,
        "search_dealbreaker_inputs",
        lambda job, **kw: SimpleNamespace(gate_evidence_labels=[], gate_options=None),
    )
    monkeypatch.setattr(
        dealbreaker_filters,
        "apply_dealbreakers",
        lambda cands, **kw: SimpleNamespace(kept=list(cands), exclusion_reasons={}),
    )

    # Stary scoring: inna skala dla tej samej pary.
    async def rank_jobs(candidate, jobs, db, *, similarity_map=None, contexts=None):
        return [_breakdown(candidate.id, j.id, LEGACY_TOTAL) for j in jobs]

    async def rank_candidates(job, candidates, db, *, similarity_map=None):
        return [_breakdown(c.id, job.id, LEGACY_TOTAL) for c in candidates]

    async def contexts(db, jobs, ids):
        return {}

    monkeypatch.setattr(scoring_service, "rank_jobs_for_candidate", rank_jobs)
    monkeypatch.setattr(scoring_service, "rank_candidates_for_job", rank_candidates)
    monkeypatch.setattr(scoring_service, "build_jobs_scoring_contexts", contexts)

    # Kanoniczny fit: profil bez użytkownika i wynik „Dop.”.
    profile = object()

    async def resolve(db, *, user_id, client_id):
        seen["profiles"].append({"user_id": user_id, "client_id": client_id})
        return profile

    def build_context(job, given):
        assert given is profile
        return SimpleNamespace(job_id=job.id, query_text=f"request {job.id}")

    async def warm(texts):
        seen["warmed"].append(list(texts))

    async def score(db, context, candidates):
        measured = seen["measurement"] == "measured"
        return [
            SimpleNamespace(
                breakdown=_breakdown(c.id, context.job_id, CANONICAL_FIT),
                measurement=seen["measurement"],
                fit_score=CANONICAL_FIT if measured else None,
            )
            for c in candidates
        ]

    async def scoring_context(db, job, ids):
        return None

    async def penalties(candidate, job, db, context=None):
        return list(seen["penalties"]), list(seen["warnings"])

    monkeypatch.setattr(scoring_service, "resolve_active_profile", resolve)
    monkeypatch.setattr(
        request_matching_context, "build_request_context", build_context
    )
    monkeypatch.setattr(canonical_fit, "score_candidates", score)
    monkeypatch.setattr(full_search_measurement, "warm_request_vectors", warm)
    monkeypatch.setattr(scoring_service, "build_job_scoring_context", scoring_context)
    monkeypatch.setattr(scoring_service, "_check_penalties_and_warnings", penalties)
    return seen


def _candidate_db():
    from app.models.candidate import Candidate

    return _FakeDb(
        by_key={(Candidate.__name__, CANDIDATE_ID): _candidate()},
        scalars=[[JOB_ID], [_job()]],
    )


def _job_db():
    from app.models.job import Job

    return _FakeDb(
        by_key={(Job.__name__, JOB_ID): _job()},
        scalars=[[CANDIDATE_ID], [_candidate()]],
    )


def _event(**kw):
    fields = {"candidate_id": None, "job_id": None, "profile_revision": None, **kw}
    return SimpleNamespace(trigger="cv_upload", **fields)


async def test_new_cv_is_scored_with_the_canonical_fit_and_the_client_profile(world):
    await ams.run_candidate_event(_candidate_db(), _event(candidate_id=CANDIDATE_ID))

    assert [(d.score, d.decision) for d in world["logged"]] == [
        (CANONICAL_FIT, "proposed")
    ]
    assert world["profiles"] == [{"user_id": None, "client_id": CLIENT_ID}]


async def test_job_event_is_scored_with_the_canonical_fit_and_the_client_profile(
    world,
):
    await ams.run_job_event(_job_db(), _event(job_id=JOB_ID))

    assert [(d.score, d.decision) for d in world["logged"]] == [
        (CANONICAL_FIT, "proposed")
    ]
    assert world["profiles"] == [{"user_id": None, "client_id": CLIENT_ID}]


@pytest.mark.parametrize(
    "penalties,warnings",
    [(("blacklist",), ()), ((), ("active_conflict", "something_else"))],
)
async def test_blacklist_and_client_conflict_still_block(world, penalties, warnings):
    world["penalties"], world["warnings"] = penalties, warnings

    await ams.run_job_event(_job_db(), _event(job_id=JOB_ID))

    [decision] = world["logged"]
    assert decision.decision == "penalized"
    assert decision.reason == "; ".join(penalties + warnings[:1])
    assert world["proposed"] == []


async def test_new_cv_without_a_current_vector_gets_no_decision(world):
    """Wektor może dogonić CV dopiero po kilku minutach (reconciler co 300 s):
    para bez decyzji, zdarzenie nie umiera — ocenia ją nocny przegląd bazy."""
    world["measurement"] = "stale"

    result = await ams.run_candidate_event(
        _candidate_db(), _event(candidate_id=CANDIDATE_ID)
    )

    assert world["logged"] == []
    assert result["unmeasured"] == {"stale": 1}


async def test_new_cv_with_the_engine_down_goes_back_to_the_queue(world):
    world["measurement"] = "unavailable"

    with pytest.raises(ams.AutoMatchUnavailable):
        await ams.run_candidate_event(
            _candidate_db(), _event(candidate_id=CANDIDATE_ID)
        )
    assert world["logged"] == []


async def test_job_event_skips_unmeasured_people_without_a_decision(world):
    world["measurement"] = "missing_index"

    result = await ams.run_job_event(_job_db(), _event(job_id=JOB_ID))

    assert world["logged"] == []
    assert result["unmeasured"] == {"missing_index": 1}


async def test_job_event_with_the_engine_down_goes_back_to_the_queue(world):
    world["measurement"] = "unavailable"

    with pytest.raises(ams.AutoMatchUnavailable):
        await ams.run_job_event(_job_db(), _event(job_id=JOB_ID))
    assert world["logged"] == []


async def test_new_cv_warms_request_vectors_in_portions_that_fit_the_cache(
    world, monkeypatch
):
    """Zdarzenie CV ocenia średnio 74 rekrutacje (do 300): wektory zapytań
    idą paczkami, w porcjach mniejszych niż pamięć podręczna."""
    from app.models.candidate import Candidate
    from app.services import full_search_measurement

    jobs = [SimpleNamespace(**{**vars(_job()), "id": JOB_ID + i}) for i in range(70)]
    db = _FakeDb(
        by_key={(Candidate.__name__, CANDIDATE_ID): _candidate()},
        scalars=[[j.id for j in jobs], jobs],
    )
    monkeypatch.setattr(ams, "_WARM_CHUNK", 64)

    await ams.run_candidate_event(db, _event(candidate_id=CANDIDATE_ID))

    assert [len(texts) for texts in world["warmed"]] == [64, 6]
    assert ams._WARM_CHUNK * 2 <= full_search_measurement._QUERY_CACHE_LIMIT
    assert len(world["logged"]) == 70


async def test_warmed_vector_is_the_one_request_vector_would_compute(monkeypatch):
    from app.services import full_search_measurement as fsm

    calls = []

    async def embed(texts, *, input_type):
        calls.append(len(texts))
        return [[float(len(t)), 1.0, 2.0] for t in texts]

    monkeypatch.setattr(fsm.embeddings, "_voyage_embed_batch", embed)
    monkeypatch.setattr(fsm.embeddings, "_voyage_model", lambda: "test-model")
    monkeypatch.setattr(fsm, "_query_cache", type(fsm._query_cache)())
    texts = [f"request {i}" for i in range(40)]
    long_text = "x" * (fsm._CHUNK + 1)

    expected = await fsm.request_vector(texts[0])
    expected_long = await fsm.request_vector(long_text)
    fsm._query_cache.clear()
    calls.clear()
    await fsm.warm_request_vectors(texts + texts[:5] + [long_text, ""])

    # 40 krótkich + 2 kawałki długiego (27.10.2026: długi w tej samej paczce).
    assert calls == [32, 10]
    assert await fsm.request_vector(texts[0]) == expected
    assert await fsm.request_vector(long_text) == expected_long
    assert calls == [32, 10]


async def test_warm_leaves_a_text_with_a_failed_chunk_for_request_vector(
    monkeypatch,
):
    from app.services import full_search_measurement as fsm

    async def embed(texts, *, input_type):
        return [[] if t == "y" else [1.0, 2.0] for t in texts]

    monkeypatch.setattr(fsm.embeddings, "_voyage_embed_batch", embed)
    monkeypatch.setattr(fsm.embeddings, "_voyage_model", lambda: "test-model")
    monkeypatch.setattr(fsm, "_query_cache", type(fsm._query_cache)())
    broken = "x" * fsm._CHUNK + "y"

    await fsm.warm_request_vectors(["ok", broken])

    assert fsm._cached(fsm._cache_key("ok")) is not None
    assert fsm._cached(fsm._cache_key(broken)) is None


async def test_job_event_with_one_failed_batch_goes_back_to_the_queue(
    world, monkeypatch
):
    """Awaria jednej paczki pomiaru (256 osób) nie może zostawić reszty bez
    decyzji do następnej zmiany rekrutacji."""
    from app.models.job import Job
    from app.services import canonical_fit

    people = [
        SimpleNamespace(**{**vars(_candidate()), "id": CANDIDATE_ID + i})
        for i in range(2)
    ]

    async def half(db, context, candidates):
        return [
            SimpleNamespace(
                breakdown=_breakdown(c.id, context.job_id, CANONICAL_FIT),
                measurement="measured" if i == 0 else "unavailable",
                fit_score=CANONICAL_FIT if i == 0 else None,
            )
            for i, c in enumerate(candidates)
        ]

    monkeypatch.setattr(canonical_fit, "score_candidates", half)
    db = _FakeDb(
        by_key={(Job.__name__, JOB_ID): _job()},
        scalars=[[p.id for p in people], people],
    )

    with pytest.raises(ams.AutoMatchUnavailable):
        await ams.run_job_event(db, _event(job_id=JOB_ID))
    assert world["logged"] == []
