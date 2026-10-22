"""„Pasuje też do” (14.10.2026, D1–D2) — reguła wyboru i przebieg bez bazy.

Pula z SQL, zawężenie Qdrantem i ocena per rekrutacja są podmienione; testy
z Postgresem (pula, trasa, dodanie z dzwonkiem) są w ``test_also_fits_db.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import also_fits
from app.services.also_fits import (
    ALSO_FITS_LIMIT,
    ALSO_FITS_MIN_SCORE,
    Scored,
    bell_message,
    select_also_fits,
)


def _s(job_id, score, *, measurement="measured", hidden=False, allowed=True):
    return Scored(
        job_id=job_id,
        score=score,
        measurement=measurement,
        hidden=hidden,
        assignment_allowed=allowed,
    )


def test_threshold_and_limit_are_the_owner_decision() -> None:
    assert ALSO_FITS_MIN_SCORE == 70
    assert ALSO_FITS_LIMIT == 3


def test_keeps_only_measured_visible_allowed_at_or_above_threshold() -> None:
    picked = select_also_fits(
        [
            _s(1, 70),
            _s(2, 69),
            _s(3, None, measurement="stale"),
            _s(4, 95, measurement="missing_index"),
            _s(5, 90, hidden=True),
            _s(6, 88, allowed=False),
            _s(7, 81),
        ]
    )
    assert [p.job_id for p in picked] == [7, 1]


def test_sorts_by_score_then_job_id_and_cuts_to_limit() -> None:
    picked = select_also_fits([_s(9, 80), _s(3, 92), _s(5, 80), _s(4, 75), _s(2, 99)])
    assert [p.job_id for p in picked] == [2, 3, 5]


def test_bell_message_names_who_whom_where_and_origin() -> None:
    msg = bell_message(
        actor_name="Marta Nowak",
        candidate_name="Oskar Wzorcowy",
        job_title="Angular Developer",
        origin_title="Programista Frontend",
    )
    assert "Marta Nowak dodał(a) Oskar Wzorcowy" in msg
    assert "„Angular Developer”" in msg
    assert "„Programista Frontend”" in msg
    no_origin = bell_message(
        actor_name="A", candidate_name="B", job_title="C", origin_title=None
    )
    assert "Znaleziony przy" not in no_origin


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Db:
    """Odpowiada na jedno zapytanie (Job + nazwa klienta) dla zawężonej puli."""

    def __init__(self, jobs):
        self.jobs = jobs
        self.queries = 0

    async def execute(self, stmt):
        self.queries += 1
        return _Rows([(job, f"Klient {job.id}") for job in self.jobs])


def _fit(job_id, score, *, hidden=False, allowed=True, measurement="measured"):
    return SimpleNamespace(
        candidate_id=1,
        score=score,
        measurement=measurement,
        decision=SimpleNamespace(assignment_allowed=allowed),
        hidden=hidden,
        breakdown=SimpleNamespace(
            matching_must=["Angular", "RxJS", "TypeScript", "NgRx"],
            gap_must=["Kafka", "Java", "Go"],
        ),
    )


@pytest.fixture
def wiring(monkeypatch):
    from app.services import (
        auto_match_service,
        embedding_service,
        job_working_title,
        my_people_matching,
    )

    state = {"pool": [11, 12, 13, 14], "similarity": None, "fits": {}, "scored": []}

    async def pool(db, **kwargs):
        state["pool_kwargs"] = kwargs
        return list(state["pool"])

    async def similarity(text, *, jobs_collection, ids):
        assert jobs_collection is True
        if isinstance(state["similarity"], Exception):
            raise state["similarity"]
        return state["similarity"] or {jid: 0.5 for jid in ids}

    async def fits_for_job(db, *, job, candidates, profile_user_id):
        state["scored"].append(job.id)
        fit = state["fits"].get(job.id)
        return [fit] if fit is not None else []

    monkeypatch.setattr(also_fits, "open_pool_job_ids", pool)
    monkeypatch.setattr(auto_match_service, "scoped_similarity", similarity)
    monkeypatch.setattr(embedding_service, "_build_candidate_text", lambda c: "cv")
    monkeypatch.setattr(my_people_matching, "fits_for_job", fits_for_job)
    monkeypatch.setattr(job_working_title, "display_title", lambda job: job.title)
    return state


def _jobs(*ids):
    return [
        SimpleNamespace(id=i, title=f"Rekrutacja {i}", client_reference=f"ZOB-{i}")
        for i in ids
    ]


@pytest.mark.asyncio
async def test_returns_top_fits_with_chips_and_client(wiring) -> None:
    wiring["fits"] = {
        11: _fit(11, 72),
        12: _fit(12, 91),
        13: _fit(13, 65),
        14: _fit(14, 80),
    }
    result = await also_fits.also_fits_for_candidate(
        _Db(_jobs(11, 12, 13, 14)),
        candidate=SimpleNamespace(id=1),
        from_job_id=10,
        profile_user_id=5,
    )
    assert result.status == "ok"
    assert [j.job_id for j in result.jobs] == [12, 14, 11]
    first = result.jobs[0]
    assert first.title == "Rekrutacja 12" and first.client_name == "Klient 12"
    # Numer u klienta przed nazwą, jak w nagłówku rekrutacji (16.10.2026).
    assert first.client_reference == "ZOB-12"
    assert first.score == 91
    assert first.matching_must == ("Angular", "RxJS", "TypeScript")
    assert first.gap_must == ("Kafka", "Java")


@pytest.mark.asyncio
async def test_vector_outage_is_unavailable_not_empty(wiring) -> None:
    from app.services.auto_match_service import AutoMatchUnavailable

    wiring["similarity"] = AutoMatchUnavailable("qdrant down")
    result = await also_fits.also_fits_for_candidate(
        _Db([]), candidate=SimpleNamespace(id=1), from_job_id=10, profile_user_id=5
    )
    assert result.status == "unavailable"
    assert result.jobs == ()


@pytest.mark.asyncio
async def test_empty_pool_skips_vector_and_scoring(wiring) -> None:
    wiring["pool"] = []
    db = _Db([])
    result = await also_fits.also_fits_for_candidate(
        db, candidate=SimpleNamespace(id=1), from_job_id=10, profile_user_id=5
    )
    assert result.status == "ok" and result.jobs == ()
    assert db.queries == 0 and wiring["scored"] == []


@pytest.mark.asyncio
async def test_only_the_nearest_jobs_get_the_full_score(wiring) -> None:
    pool = list(range(100, 120))
    wiring["pool"] = pool
    wiring["similarity"] = {jid: jid / 1000 for jid in pool}
    wiring["fits"] = {jid: _fit(jid, 75) for jid in pool}
    await also_fits.also_fits_for_candidate(
        _Db(_jobs(*pool)),
        candidate=SimpleNamespace(id=1),
        from_job_id=10,
        profile_user_id=5,
    )
    assert (
        wiring["scored"] == sorted(pool, reverse=True)[: also_fits.ALSO_FITS_PREFILTER]
    )


@pytest.mark.asyncio
async def test_veto_and_hidden_jobs_never_reach_the_list(wiring) -> None:
    wiring["fits"] = {
        11: _fit(11, 95, allowed=False),
        12: _fit(12, 93, hidden=True),
        13: _fit(13, 90, measurement="stale"),
        14: _fit(14, 71),
    }
    result = await also_fits.also_fits_for_candidate(
        _Db(_jobs(11, 12, 13, 14)),
        candidate=SimpleNamespace(id=1),
        from_job_id=10,
        profile_user_id=5,
    )
    assert [j.job_id for j in result.jobs] == [14]


def test_also_fits_is_a_human_add_source_in_both_vocabularies() -> None:
    from typing import get_args

    from app.api.proposals_bulk import (
        BulkAddSource,
        BulkProposalsRequest,
        _entry_source_for,
    )
    from app.services import candidate_claim
    from app.services.match_telemetry_service import PIPELINE_ADD_SOURCES

    assert "also_fits" in get_args(BulkAddSource)
    assert "also_fits" in PIPELINE_ADD_SOURCES
    body = BulkProposalsRequest(candidate_ids=[1], source="also_fits", origin_job_id=7)
    assert body.origin_job_id == 7
    # Kliknięcie człowieka, nie propozycja systemu.
    assert _entry_source_for("also_fits") == candidate_claim.ENTRY_ADDED_MANUAL


def test_origin_job_id_must_be_positive() -> None:
    from pydantic import ValidationError

    from app.api.proposals_bulk import BulkProposalsRequest

    with pytest.raises(ValidationError):
        BulkProposalsRequest(candidate_ids=[1], source="also_fits", origin_job_id=0)


def test_bell_type_is_registered_for_category_and_section() -> None:
    from app.models.notification import NotificationType
    from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE
    from app.services.notification_categories import CATEGORY_BY_TYPE
    from app.services.section_permissions import ProductSection

    t = NotificationType.also_fits_added
    assert CATEGORY_BY_TYPE[t].value == "candidates"
    assert NOTIFICATION_SECTION_BY_TYPE[t] is ProductSection.pipeline


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _SavepointDb:
    def begin_nested(self):
        return _Nested()


@pytest.mark.asyncio
async def test_returning_consultant_reads_the_employment_marker(monkeypatch) -> None:
    """R2 (22.10.2026): „nasz konsultant · Wraca na rynek DD.MM” w bloku —
    ta sama reguła co znacznik „Pracuje u nas”; awaria = brak informacji."""

    from datetime import date

    from app.services import employment_marker

    markers = {
        7: SimpleNamespace(
            returns_to_market=True, returns_to_market_on=date(2026, 10, 31)
        ),
        8: SimpleNamespace(returns_to_market=False, returns_to_market_on=None),
    }

    async def load(db, ids, *, today):
        return {cid: markers.get(cid) for cid in ids}

    monkeypatch.setattr(employment_marker, "load_employment_markers", load)
    today = date(2026, 10, 22)
    found = await also_fits.returning_consultant(_SavepointDb(), 7, today=today)
    assert found == also_fits.ReturningConsultant(returns_on=date(2026, 10, 31))
    assert await also_fits.returning_consultant(_SavepointDb(), 8, today=today) is None
    assert await also_fits.returning_consultant(_SavepointDb(), 9, today=today) is None

    async def broken(db, ids, *, today):
        raise RuntimeError("boom")

    monkeypatch.setattr(employment_marker, "load_employment_markers", broken)
    assert await also_fits.returning_consultant(_SavepointDb(), 7, today=today) is None
