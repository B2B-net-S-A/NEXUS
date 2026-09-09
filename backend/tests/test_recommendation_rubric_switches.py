"""`/recommendations`: trzy nowe przełączniki rubryk (0278) + AUTO `exclude_remote_only`.

Dwa kontrakty:

1. STATYCZNY (AST) — trasa deklaruje `exclude_missing_must`,
   `exclude_office_days_exceeded`, `exclude_office_city_mismatch` i
   `exclude_remote_only`, i przekazuje WSZYSTKIE CZTERY do
   `_recommend_candidates_core`. Dopisanie parametru do trasy bez przekazania
   go dalej jest martwym pokrętłem — front wysyła query param, backend go
   ignoruje.
2. WYKONAWCZY (spy przez HTTP) — `_recommend_candidates_core` przekazuje
   `inputs=dealbreaker_inputs_for_job(job)` i cztery przełączniki do
   `apply_dealbreakers`; pominięty `exclude_remote_only` w query stringu
   dociera jako `None` (AUTO), nie jako `False` sprzed 0278.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.candidate import Candidate
from app.models.job import Job

BACKEND = Path(__file__).resolve().parent.parent


def test_route_declares_and_forwards_the_four_switches():
    tree = ast.parse(
        (BACKEND / "app/api/recommendations.py").read_text(encoding="utf-8")
    )
    route = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "recommend_candidates_for_job"
    )
    route_params = {a.arg for a in route.args.args + route.args.kwonlyargs}
    core = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "_recommend_candidates_core"
    )
    core_params = {a.arg for a in core.args.args + core.args.kwonlyargs}

    switches = (
        "exclude_missing_must",
        "exclude_office_days_exceeded",
        "exclude_office_city_mismatch",
        "exclude_remote_only",
    )
    for name in switches:
        assert name in route_params, f"trasa nie deklaruje {name}"
        assert name in core_params, f"core nie deklaruje {name}"

    call = next(
        n
        for n in ast.walk(route)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_recommend_candidates_core"
    )
    forwarded = {kw.arg for kw in call.keywords}
    for name in switches:
        assert name in forwarded, f"trasa nie przekazuje {name} do core"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_core_calls_shared_gate_with_inputs_and_new_switches(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """AUTO: query bez `exclude_remote_only` → `apply_dealbreakers(..., exclude_remote_only=None)`.

    W CI Qdrant/Voyage są niedostępne, więc `retrieve_candidate_pool` zwraca
    pustą pulę i core spada na DB fallback (`SELECT ... ORDER BY id DESC LIMIT`)
    — świeżo zasiany kandydat ma najwyższe `id`, więc wchodzi do puli bez
    mockowania retrievalu.
    """
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RubricSwitches Client {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"RubricSwitches Job {unique}",
            client_id=client.id,
            description="Python backend engineer",
            requirements="python",
        )
        cand = Candidate(
            name="Rubric",
            lastname=f"Switch{unique}",
            email=f"rubric-switch-{unique}@example.com",
        )
        db.add_all([job, cand])
        await db.commit()
        job_id = job.id

    seen: dict = {}
    import app.api.matching as matching

    real_gate = matching._gate_and_dealbreakers

    async def spy(db, **kwargs):
        seen.update(kwargs)
        return await real_gate(db, **kwargs)

    monkeypatch.setattr(matching, "_gate_and_dealbreakers", spy)

    resp = await app_client.get(
        f"/api/jobs/{job_id}/recommendations",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    assert "inputs" in seen, "core musi przekazać wspólne kryteria do bramki"
    assert seen["inputs"].budget_hourly is None
    # Pominięty query param → AUTO (None), NIE `False` sprzed 0278.
    assert seen.get("exclude_remote_only") is None
    assert seen.get("exclude_missing_must") is True
    assert seen.get("exclude_office_days_exceeded") is True
    assert seen.get("exclude_office_city_mismatch") is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_explicit_query_params_override_the_defaults(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RubricSwitches2 Client {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"RubricSwitches2 Job {unique}",
            client_id=client.id,
            description="Python backend engineer",
            requirements="python",
        )
        cand = Candidate(
            name="Rubric",
            lastname=f"Switch2{unique}",
            email=f"rubric-switch2-{unique}@example.com",
        )
        db.add_all([job, cand])
        await db.commit()
        job_id = job.id

    seen: dict = {}
    import app.api.matching as matching

    real_gate = matching._gate_and_dealbreakers

    async def spy(db, **kwargs):
        seen.update(kwargs)
        return await real_gate(db, **kwargs)

    monkeypatch.setattr(matching, "_gate_and_dealbreakers", spy)

    resp = await app_client.get(
        f"/api/jobs/{job_id}/recommendations",
        params={
            "exclude_remote_only": "true",
            "exclude_missing_must": "false",
            "exclude_office_days_exceeded": "false",
            "exclude_office_city_mismatch": "false",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert seen.get("exclude_remote_only") is True
    assert seen.get("exclude_missing_must") is False
    assert seen.get("exclude_office_days_exceeded") is False
    assert seen.get("exclude_office_city_mismatch") is False
