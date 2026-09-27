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


# ---------------------------------------------------------------- R9-N5-1


def _counting_sleep(monkeypatch, module):
    import asyncio

    counter = {"yields": 0}
    real_sleep = asyncio.sleep

    async def counting_sleep(delay, *a, **k):
        if delay == 0:
            counter["yields"] += 1
        await real_sleep(delay, *a, **k)

    monkeypatch.setattr(module.asyncio, "sleep", counting_sleep)
    return counter


@pytest.mark.asyncio
async def test_r9_n5_1_radar_dealbreakers_in_chunks_equal_one_pass_and_yield(
    monkeypatch,
):
    from app.services import talent_radar_search as trs
    from app.services.dealbreaker_filters import DealbreakerInputs, apply_dealbreakers

    cands = [
        _cand(i, expected_rate_hourly=(200 if i % 3 == 0 else 90))
        for i in range(1, 301)
    ]
    inputs = DealbreakerInputs(budget_hourly=100.0)
    whole = apply_dealbreakers(cands, inputs=inputs)

    counter = _counting_sleep(monkeypatch, trs)
    merged = await trs._apply_dealbreakers_yielding(cands, inputs=inputs)
    assert [c.id for c in merged.kept] == [c.id for c in whole.kept]
    assert merged.hidden_meta() == whole.hidden_meta()
    assert merged.exclusion_reasons == whole.exclusion_reasons
    assert counter["yields"] >= 300 // trs.DEALBREAKER_CHUNK


@pytest.mark.asyncio
async def test_r9_n5_1_rank_candidates_for_job_yields_to_the_event_loop(monkeypatch):
    from app.services import scoring_service as ss

    async def ctx(db, job, ids):
        return None

    async def score(c, job, db, *, semantic_similarity, profile, context):
        return SimpleNamespace(total=float(c.id), candidate_id=c.id)

    monkeypatch.setattr(ss, "build_job_scoring_context", ctx)
    monkeypatch.setattr(ss, "score_candidate_job", score)
    counter = _counting_sleep(monkeypatch, ss)
    out = await ss.rank_candidates_for_job(
        SimpleNamespace(id=None), [_cand(i) for i in range(200)], None
    )
    assert [r.candidate_id for r in out][:2] == [199, 198]
    assert counter["yields"] >= 200 // 32


# ---------------------------------------------------------------- R9-N5-8/9


def _module_ast(relpath: str):
    import ast
    from pathlib import Path

    return ast.parse((Path(__file__).resolve().parents[1] / relpath).read_text())


def test_r9_n5_9_radar_limits_are_keyed_per_user():
    import ast

    tree = _module_ast("app/api/talent_radar.py")
    limits = [
        dec
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        for dec in node.decorator_list
        if isinstance(dec, ast.Call)
        and isinstance(dec.func, ast.Attribute)
        and dec.func.attr == "limit"
    ]
    assert len(limits) == 2
    for dec in limits:
        keys = {kw.arg: kw.value for kw in dec.keywords}
        assert isinstance(keys.get("key_func"), ast.Name)
        assert keys["key_func"].id == "user_or_ip_key"


def test_r9_n5_8_radar_search_checks_client_assignable_before_ranking():
    import ast

    tree = _module_ast("app/api/talent_radar.py")
    [fn] = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "talent_radar_search"
    ]
    calls = [
        n.func.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert "assert_client_assignable" in calls
    assert calls.index("assert_client_assignable") < calls.index("runner")


@pytest.mark.asyncio
async def test_r9_n5_8_full_scan_radar_refuses_deleted_client(monkeypatch):
    from fastapi import HTTPException

    from app.api import candidate_search as cs
    from app.api.talent_radar import TalentRadarSearchRequest
    from app.services import client_access

    async def refuse(db, client_id):
        raise HTTPException(422, {"code": "client_deleted", "message": "x"})

    class _Db:
        async def get(self, model, pk):
            return SimpleNamespace(id=pk)

    monkeypatch.setattr(cs, "_search_access", lambda user: None)
    monkeypatch.setattr(client_access, "assert_client_assignable", refuse)
    payload = cs.StartSearchRequest(
        radar=TalentRadarSearchRequest(client_id=5, text="Java developer")
    )
    with pytest.raises(HTTPException) as exc:
        await cs.start_search(payload, SimpleNamespace(id=1), _Db())
    assert exc.value.status_code == 422


# ---------------------------------------------------------------- R9-V3-2


def test_r9_v3_2_jarvis_calendar_dates_are_whole_warsaw_days():
    from datetime import datetime, timedelta

    from app.services.jarvis.tools import TOOLS_BY_NAME

    spec = TOOLS_BY_NAME["list_calendar_events"].build(
        {"from_date": "2026-09-30", "to_date": "2026-09-30"}
    )
    start = datetime.fromisoformat(spec.params["from_date"])
    end = datetime.fromisoformat(spec.params["to_date"])
    assert start.utcoffset() is not None and end.utcoffset() is not None
    # 30.09 w Warszawie (CEST, UTC+2): 29.09 22:00 UTC → 30.09 21:59:59.999999 UTC.
    assert start.isoformat() == "2026-09-29T22:00:00+00:00"
    assert end - start == timedelta(days=1, microseconds=-1)
    assert spec.params["upcoming"] is False

    # Pełna chwila ISO przechodzi bez zmian; bez dat — nadchodzące.
    spec = TOOLS_BY_NAME["list_calendar_events"].build(
        {"to_date": "2026-09-30T12:00:00+02:00"}
    )
    assert spec.params["to_date"] == "2026-09-30T12:00:00+02:00"
    assert TOOLS_BY_NAME["list_calendar_events"].build({}).params["upcoming"] is True


# ---------------------------------------------------------------- R9-N5-4


def test_r9_n5_4_jarvis_radar_asks_for_the_canonical_score():
    from app.services.jarvis.tools import TOOLS_BY_NAME

    spec = TOOLS_BY_NAME["talent_radar_search"].build(
        {"client_id": 5, "text": "Java developer", "limit": 5}
    )
    assert spec.path == "/api/talent-radar/search"
    assert spec.params == {"canonical": "true"}
    assert spec.json["client_id"] == 5


@pytest.mark.asyncio
async def test_r9_n5_4_canonical_radar_uses_search_policy_and_canonical_fit(
    monkeypatch,
):
    from app.api import matching
    from app.services import canonical_fit, scoring_service
    from app.services import talent_radar_search as trs
    from app.services.scoring_service import DEFAULT_PROFILE

    cands = [_cand(1), _cand(2), _cand(3)]
    seen = {}

    async def pool(db, text, *, top_k, raise_on_error, use_rerank):
        seen["pool_text"] = text
        return [{"candidate_id": c.id, "score": 0.9} for c in cands]

    async def load(db, ids):
        return [c for c in cands if c.id in ids]

    async def gate(db, *, job, ordered, now, inputs):
        seen["inputs"] = inputs
        kept = [c for c in ordered if c.id != 3]
        return kept, {1: {"reason_code": "client_nda"}}, {"over_budget": 1}, 0, inputs

    async def fits(db, context, kept):
        seen["context"] = context
        return [
            canonical_fit.CanonicalFit(
                SimpleNamespace(candidate_id=2, total=88.0), "measured"
            ),
            canonical_fit.CanonicalFit(
                SimpleNamespace(candidate_id=1, total=70.0), "unavailable"
            ),
        ]

    async def profile(db, **k):
        return DEFAULT_PROFILE

    class _Db:
        async def scalar(self, stmt):
            return 5

    monkeypatch.setattr(trs, "retrieve_candidate_pool", pool)
    monkeypatch.setattr(trs, "_load_candidates", load)
    monkeypatch.setattr(matching, "_gate_and_dealbreakers", gate)
    monkeypatch.setattr(canonical_fit, "score_candidates", fits)
    monkeypatch.setattr(scoring_service, "resolve_active_profile", profile)

    result = await trs.canonical_search(
        _Db(),
        trs.RadarQuery(client_id=5, text="Java developer, Spring", top_k=10),
        user_id=7,
    )
    # Niezmierzony wynik odpada — nigdy nie jest zerem na liście.
    assert [f.breakdown.candidate_id for f in result.breakdowns] == [2]
    assert result.pool_size == 3 and result.eligible_size == 2
    assert result.degraded is False
    assert result.hidden == {"over_budget": 1}
    assert seen["context"].query_text == seen["pool_text"]
    assert set(result.candidates_by_id) == {2}
    assert result.eligibility_by_id == {}
