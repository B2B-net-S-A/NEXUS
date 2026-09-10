"""`GET /api/admin/index-coverage` mierzy też rozmiar pełnego przeglądu bazy.

Każdy przegląd dopisuje wiersz na każdego kandydata, więc to jest pomiar,
po którym widać, czy retencja trzyma tabelę wyników w ryzach. Musi być tani
(bez skanu tabeli wyników) i nie może udawać zera tam, gdzie nie wie.
"""

import uuid

import pytest

from app.api import admin_index_coverage as coverage
from app.core.database import AsyncSessionLocal


@pytest.mark.asyncio
async def test_candidate_search_block_reports_size_estimate_and_runs_by_state(
    monkeypatch,
):
    from app.models.candidate_search_run import CandidateSearchRun
    from app.models.client import Client
    from app.models.user import User, UserRole

    async def no_qdrant(_collection):
        return None

    monkeypatch.setattr(coverage, "_collection_points", no_qdrant)
    async with AsyncSessionLocal() as db:
        try:
            unique = uuid.uuid4().hex
            user = User(
                name="Coverage",
                email=f"coverage-{unique}@example.com",
                password_hash="unused",
                role=UserRole.admin,
                is_active=True,
            )
            client = Client(name=f"Coverage client {unique}")
            db.add_all([user, client])
            await db.flush()
            db.add(
                CandidateSearchRun(
                    id=str(uuid.uuid4()),
                    created_by=user.id,
                    client_id=client.id,
                    state="failed",
                    request_fingerprint="f" * 64,
                    request_context={},
                    version_trace={},
                    population_size=0,
                    metrics={},
                )
            )
            await db.flush()
            body = await coverage.index_coverage(auth_mode="jwt", db=db)
        finally:
            await db.rollback()

    block = body["candidate_search"]
    assert set(block) == {
        "results_total_bytes",
        "results_total_pretty",
        "results_estimated_rows",
        "runs_by_state",
    }
    assert isinstance(block["results_total_bytes"], int)
    assert block["results_total_bytes"] >= 0 and block["results_total_pretty"]
    # An estimate never measured (-1) is unknown, never a fake zero.
    assert (
        block["results_estimated_rows"] is None or block["results_estimated_rows"] >= 0
    )
    assert block["runs_by_state"].get("failed", 0) >= 1
