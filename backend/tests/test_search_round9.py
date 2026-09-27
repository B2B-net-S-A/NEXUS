"""Runda 9 audytu (SEARCH): wyszukiwanie, Talent Radar, „Moi ludzie", alerty.

Każdy test pilnuje jednego znaleziska — nazwa testu niesie jego ID.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _cand(cid: int, **kw):
    base = dict(
        id=cid,
        expected_rate_hourly=None,
        expected_rate_currency="PLN",
        b2b_willingness=None,
        accepts_below_min_rate=None,
        accepts_more_office_days=None,
        work_time_preference=None,
        remote_preference=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _decision(severity: str, visibility: str):
    from app.services.candidate_job_eligibility import Severity, Visibility

    return SimpleNamespace(
        severity=Severity(severity), visibility=Visibility(visibility)
    )


# ---------------------------------------------------------------- R9-N5-2


def test_r9_n5_2_my_people_hides_over_budget_but_keeps_hm_veto(monkeypatch):
    from app.services import requirement_contract
    from app.services.dealbreaker_filters import DealbreakerInputs
    from app.services.my_people_matching import dealbreaker_exclusions

    monkeypatch.setattr(
        requirement_contract,
        "search_dealbreaker_inputs",
        lambda job: DealbreakerInputs(budget_hourly=100.0),
    )
    cheap = _cand(1, expected_rate_hourly=90)
    pricey = _cand(2, expected_rate_hourly=200)
    vetoed_pricey = _cand(3, expected_rate_hourly=250)
    employment_only = _cand(4, b2b_willingness="employment_only")
    decisions = {
        1: _decision("none", "visible"),
        2: _decision("none", "visible"),
        3: _decision("hard", "warn"),
        4: _decision("hard", "warn"),
    }
    hidden = dealbreaker_exclusions(
        SimpleNamespace(id=1),
        [cheap, pricey, vetoed_pricey, employment_only],
        decisions,
    )
    assert hidden == {2: "over_budget", 4: "employment_only"}


@pytest.mark.asyncio
async def test_r9_n5_2_score_people_marks_dealbreaker_rows_hidden(monkeypatch):
    from app.services import (
        canonical_fit,
        embedding_service,
        pipeline_eligibility,
        request_matching_context,
        requirement_contract,
        requirement_verification,
        scoring_service,
    )
    from app.services import my_people_matching as mpm
    from app.services.dealbreaker_filters import DealbreakerInputs

    cands = [_cand(1, expected_rate_hourly=90), _cand(2, expected_rate_hourly=300)]

    async def sim(text, *, jobs_collection, ids):
        return {1: 0.9, 2: 0.8}

    async def fits(db, context, candidates):
        return [
            SimpleNamespace(
                breakdown=SimpleNamespace(candidate_id=c.id),
                fit_score=0.8,
                measurement="measured",
            )
            for c in candidates
        ]

    async def decisions(db, *, job, candidate_ids, now):
        return {cid: _decision("none", "visible") for cid in candidate_ids}

    async def noop(*a, **k):
        return None

    async def profile(db, **k):
        return None

    class _Db:
        async def scalars(self, stmt):
            return SimpleNamespace(all=lambda: cands)

    monkeypatch.setattr(mpm, "scoped_similarity", sim)
    monkeypatch.setattr(mpm, "eligibility_annotation", lambda d: None)
    monkeypatch.setattr(embedding_service, "_build_job_text", lambda job: "x")
    monkeypatch.setattr(canonical_fit, "score_candidates", fits)
    monkeypatch.setattr(canonical_fit, "display_score", lambda v: 80)
    monkeypatch.setattr(pipeline_eligibility, "evaluate_candidates_for_job", decisions)
    monkeypatch.setattr(
        request_matching_context, "build_request_context", lambda j, p: None
    )
    monkeypatch.setattr(scoring_service, "resolve_active_profile", profile)
    monkeypatch.setattr(requirement_verification, "load_verified_requirements", noop)
    monkeypatch.setattr(
        requirement_contract,
        "search_dealbreaker_inputs",
        lambda job: DealbreakerInputs(budget_hourly=100.0),
    )
    out = await mpm.score_people_for_job(
        _Db(),
        job=SimpleNamespace(id=7, client_id=1),
        candidate_ids=[1, 2],
        profile_user_id=None,
        pool_limit=10,
    )
    hidden = {p.candidate_id: p.hidden for p in out}
    assert hidden == {1: False, 2: True}
