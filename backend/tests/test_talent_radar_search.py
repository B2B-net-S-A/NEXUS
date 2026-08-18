"""Talent Radar — ad-hoc role in, ranked candidates out.

The composition is thin; what these tests guard are the constraints that make it
safe, because each of them is a defect this codebase has already shipped once.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import talent_radar_search as tr
from app.services.talent_radar_search import (
    RadarQuery,
    RadarResult,
    TalentRadarError,
    build_ephemeral_job,
)

BACKEND = Path(__file__).resolve().parents[1]


def test_ephemeral_job_sets_every_attribute_the_scoring_path_reads():
    """Derived from the source, not hand-listed — a hand list rots silently.

    `build_ephemeral_job` returns a SimpleNamespace, so it has exactly what we
    put on it and nothing more. A missing attribute is an `AttributeError` in
    the middle of a live search, not a startup failure.

    The first version of this test enumerated the attributes by hand. That is
    the weaker guard: the day scoring starts reading `job.something_new`, a hand
    list still passes and only production finds out. So the expected set is
    walked out of the modules the radar actually calls. Extra attributes on the
    namespace are fine; missing ones are not.
    """

    import ast

    backend = Path(__file__).resolve().parents[1]
    required: set[str] = set()
    for module in (
        "app/services/scoring_service.py",
        "app/services/embedding_service.py",
        "app/services/pipeline_eligibility.py",
        # Dopisane po awarii na prodzie (2026-08-13): `pipeline_eligibility`
        # DELEGUJE weto do `hiring_manager_verdicts.load_manager_rejections`,
        # które czyta `job.hiring_manager_contact_id`. Skan po trzech modułach
        # tego nie widział, więc test przechodził, a każde realne wyszukanie
        # kończyło się 500. Sama lista modułów jest ostatnią ręczną rzeczą w tym
        # teście — dlatego niżej stoi drugi guard, który jedzie PRAWDZIWĄ ścieżką
        # i nie ma czego przeoczyć.
        "app/services/hiring_manager_verdicts.py",
    ):
        tree = ast.parse((backend / module).read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = {a.arg for a in [*fn.args.args, *fn.args.kwonlyargs]}
            if "job" not in params:
                continue
            required |= {
                node.attr
                for node in ast.walk(fn)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "job"
            }

    assert required, "derivation found nothing — the walk is broken, not the code"

    job = build_ephemeral_job(RadarQuery(client_id=7, text="Senior Python"))
    missing = sorted(attr for attr in required if not hasattr(job, attr))
    assert not missing, (
        f"scoring reads job.{{{','.join(missing)}}} — set it in build_ephemeral_job"
    )


def test_ephemeral_job_has_no_id_so_it_cannot_touch_pipeline_history():
    """`id=None` is load-bearing, not a placeholder.

    `build_job_scoring_context` filters `CandidateStage.job_id == job.id`; a real
    id would pull another job's screening answers into an unrelated search.
    """
    job = build_ephemeral_job(RadarQuery(client_id=7, text="x"))
    assert job.id is None


def test_client_is_carried_onto_the_job_or_conflicts_cannot_be_checked():
    job = build_ephemeral_job(RadarQuery(client_id=42, text="x"))
    assert job.client_id == 42, (
        "the eligibility filter reads client_id — losing it here would silently "
        "skip NDA, competitor and veto checks"
    )


@pytest.mark.asyncio
async def test_empty_query_is_refused_before_any_paid_call():
    class _DB:
        async def scalar(self, *_a, **_k):  # pragma: no cover - must not be reached
            raise AssertionError("no DB work before the input is validated")

    with pytest.raises(TalentRadarError):
        await tr.search(_DB(), RadarQuery(client_id=1))


@pytest.mark.asyncio
async def test_unknown_client_is_refused_rather_than_searched_unfiltered():
    """The whole point of the mandatory client.

    Answering without one would produce a list whose NDA / competitor / veto
    checks silently passed — the `/ai-matches` defect, rebuilt on a new surface.
    """

    class _DB:
        async def scalar(self, *_a, **_k):
            return None  # no such client

    with pytest.raises(TalentRadarError) as exc:
        await tr.search(_DB(), RadarQuery(client_id=999, text="Senior Python"))

    assert "klienta" in str(exc.value).lower()


def test_degraded_retrieval_is_reported_not_rendered_as_no_matches():
    result = RadarResult(
        breakdowns=[], pool_size=0, eligible_size=0, degraded=True, reason="x"
    )
    meta = result.as_meta()
    assert meta["degraded"] is True, (
        "an empty list from a broken provider must be distinguishable from "
        "'we have nobody like that'"
    )


def _calls_in(module_rel: str, func_name: str) -> set[str]:
    tree = ast.parse((BACKEND / module_rel).read_text(encoding="utf-8"))
    target = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == func_name
    )
    return {
        n.func.id
        for n in ast.walk(target)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def test_search_enforces_eligibility():
    assert "filter_eligible_candidates" in _calls_in(
        "app/services/talent_radar_search.py", "search"
    ), "Talent Radar would surface candidates the recruiter cannot assign"


def test_search_does_not_write_the_score_cache():
    """The cache key is (candidate, job, profile) and this job has no id.

    Using `bulk_get_or_compute` here would either collide across unrelated
    ad-hoc searches or write rows keyed on a null job.
    """
    calls = _calls_in("app/services/talent_radar_search.py", "search")
    assert "rank_candidates_for_job" in calls
    assert "bulk_get_or_compute" not in calls


def test_module_makes_no_llm_call():
    """One Voyage query embedding, nothing else — so the module is free to use.

    Implicit must-skills come from `_score_skills`' existing JD/Champion
    fallback, which is why no parse step is needed.
    """
    src = (BACKEND / "app/services/talent_radar_search.py").read_text(encoding="utf-8")
    for forbidden in ("parse_cv", "call_claude", "ai_feature"):
        assert forbidden not in src, (
            f"{forbidden} would add per-search spend and a quota gate to a "
            "module that currently needs neither"
        )


def test_endpoint_module_has_no_future_annotations_import():
    """PEP 563 turns the body model into a ForwardRef and FastAPI then resolves
    it as a *Query* parameter, which fails while building the OpenAPI schema.

    `cv_match_preview` carries the same warning in its own docstring; this module
    was written by copying that pattern and adding the import anyway, so the
    guard lives here as well as in prose.
    """
    # Parsed, not grepped: the module docstring *mentions* the import in order
    # to warn about it, so a substring check fails on its own warning.
    tree = ast.parse((BACKEND / "app/api/talent_radar.py").read_text(encoding="utf-8"))
    future_imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for alias in node.names
    }
    assert "annotations" not in future_imports, (
        "PEP 563 breaks FastAPI body resolution on this endpoint"
    )


def test_result_rows_carry_the_person_not_just_an_id():
    """A ranked list of integers is not a list a recruiter can read.

    `ScoreBreakdown` holds `candidate_id` and scoring layers — nothing about
    who that is. Shipping it unchanged would force the browser to resolve every
    id one by one, an N+1 over the network across data this endpoint already
    holds in memory.
    """

    candidate = SimpleNamespace(
        id=7,
        name="Anna",
        lastname="Kowalska",
        location="Kraków, PL",
        competence_category="software_development",
        years_it_experience=8,
        availability_status=None,
        champion=True,
        avatar_url=None,
    )

    shaped = tr.shape_radar_candidate(candidate)

    assert shaped["id"] == 7
    assert shaped["name"] == "Anna" and shaped["lastname"] == "Kowalska"
    assert shaped["champion"] is True
    assert "email" not in shaped, (
        "a triage list decides whom to open, not whom to write to — contact "
        "details belong on the profile behind the click, not in every response"
    )
    assert "expected_rate_hourly" not in shaped and "phone" not in shaped


def test_salary_layer_is_blanked_because_a_radar_query_has_no_budget():
    """`/recommendations` redacts this layer; the radar has nothing to redact.

    `build_ephemeral_job` sets `salary_min`/`salary_max` to None, so
    `_score_salary` short-circuits and the layer is structurally unscored.
    Returning its raw zero would read as "bad fit on money" rather than "not
    applicable" — and would leave the contract one refactor away from becoming
    the budget oracle the sibling endpoint guards against.
    """

    from app.api.talent_radar import _shape_result

    breakdown = SimpleNamespace(
        candidate_id=7,
        as_dict=lambda: {
            "candidate_id": 7,
            "total": 61.0,
            "salary": {
                "points": 0.0,
                "max": 15,
                "reason": "brak widełek",
                "status": "scored",
            },
        },
    )

    shaped = _shape_result(breakdown, None)

    assert shaped["salary"] == {
        "points": None,
        "max": None,
        "reason": None,
        "status": "not_applicable",
    }
    assert shaped["candidate"] is None, "a vanished row must not crash the response"


async def test_search_survives_the_real_eligibility_path(monkeypatch):
    """Guard, który nie ma czego przeoczyć: pełne `search()` po PRAWDZIWEJ ścieżce.

    Test wyżej (skan AST) wylicza atrybuty z RĘCZNEJ listy modułów i właśnie na
    tym się przewrócił: `pipeline_eligibility` deleguje weto do
    `hiring_manager_verdicts`, którego na liście nie było, więc brak
    `job.hiring_manager_contact_id` przeszedł przez CI i wywalał każde realne
    wyszukanie na prodzie (500). Ten test nie enumeruje niczego — podstawia
    tylko retrieval (jedyną zależność zewnętrzną: Voyage + Qdrant) i puszcza
    resztę łańcucha na żywo, więc KAŻDY brakujący atrybut wychodzi tu, a nie u
    użytkownika.

    Pusta pula jest osobnym, łagodnym przypadkiem (`degraded=True`) i wychodzi
    z `search()` ZANIM dotknie eligibility — dlatego awaria nie pokazywała się
    na ścieżce „retrieval leży", tylko na tej, która miała działać.
    """
    import uuid as _uuid

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.services import talent_radar_search as mod

    async with AsyncSessionLocal() as db:
        client = Client(name=f"RadarE2E-{_uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        cand = Candidate(
            name="Radar",
            lastname=f"E2E-{_uuid.uuid4().hex[:6]}",
            email=f"radar-{_uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)

        async def _fake_pool(
            _db, _text, *, top_k, raise_on_error=False, query_variants=None
        ):
            return [{"candidate_id": cand.id, "score": 0.71}]

        monkeypatch.setattr(mod, "retrieve_candidate_pool", _fake_pool)

        try:
            result = await mod.search(
                db,
                mod.RadarQuery(
                    client_id=client.id,
                    text="Senior DevOps Engineer, Kubernetes, Terraform, AWS",
                    top_k=5,
                ),
            )
        finally:
            # `search()` niczego nie zapisuje, więc sprzątanie jest bezpieczne —
            # a bez niego każdy przebieg zostawiałby wiersze w bazie i psuł testy,
            # które liczą rekordy (paginacja list, inwentarze).
            await db.delete(cand)
            await db.delete(client)
            await db.commit()

    assert result.degraded is False
    assert result.pool_size == 1, "kandydat z puli musi dojść do rankingu"
