"""`/ai-matches` na wspólnym silniku — kontrakt liczby, nie tylko kolejności.

Zakładka rekrutacji renderuje DWIE listy opisane tym samym słowem
„dopasowanie": „Ranking" (`/recommendations`, kompozyt 0–100 ważony profilem)
i „Shortlistę" (`/ai-matches`, surowy kosinus Qdranta z puli 100). Te same dane
potrafiły dać dwie różne kolejności, bez żadnego sygnału, że to dwie różne
miary.

Flaga `AI_MATCHES_SHARED_ENGINE` (domyślnie OFF) przełącza drugą listę na ten
sam silnik. Te testy zamrażają obie strony flagi, bo najgroźniejszy stan to nie
„flaga nie działa", tylko „flaga działa, a kontrakt odpowiedzi cicho się
zmienił": `match_score` czyta `MatchScoreBar` (×100), parametr `min_score`
(ge=0, le=1) i zamrożony `JobShortlist.score_snapshot`.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job


@pytest_asyncio.fixture
async def shared_engine_fixture():
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"SharedEngine Client {unique}")
        db.add(client)
        await db.flush()

        job = Job(
            title=f"SharedEngine Job {unique}",
            client_id=client.id,
            description="Python backend engineer",
            requirements="python, fastapi",
            hiring_manager_contact_id=None,
        )
        cand = Candidate(
            name="Wspolny",
            lastname=f"Silnik{unique}",
            email=f"shared-{unique}@example.com",
            status=CandidateStatus.active,
            skills=[{"name": "python"}, {"name": "fastapi"}],
        )
        db.add_all([job, cand])
        await db.commit()
        ids = (job.id, cand.id, client.id)

    yield ids

    job_id, cand_id, client_id = ids
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id == cand_id))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


def _semantic_hits(monkeypatch, cand_id: int, *, score: float = 0.9, unknown=False):
    """Podmień pulę na jedno trafienie o znanym kosinusie.

    Patchujemy `embedding_service.search_candidates_semantic` — fasada woła je
    przez ATRYBUT modułu, więc podmiana obejmuje też ścieżkę przez
    `retrieve_candidate_pool` (przy flagach retrievalu OFF to dokładnie to
    samo wywołanie).
    """

    row = {"candidate_id": cand_id, "score": score}
    if unknown:
        row = {"candidate_id": cand_id, "score": 0.0, "semantic_unknown": True}

    async def _hits(*_a, **_kw):
        return [row]

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _hits
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_flag_off_response_is_legacy_shape(
    app_client: AsyncClient, app_auth_headers: dict, shared_engine_fixture, monkeypatch
):
    """Bez flagi: `search_type == "semantic"`, wiersz bez kompozytu."""
    job_id, cand_id, _ = shared_engine_fixture
    monkeypatch.setattr(settings, "AI_MATCHES_SHARED_ENGINE", False)
    _semantic_hits(monkeypatch, cand_id)

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["search_type"] == "semantic"
    row = next(m for m in body["matches"] if m["candidate"]["id"] == cand_id)
    assert "total_score" not in row, "stara ścieżka nie liczy kompozytu"
    assert row["match_score"] == pytest.approx(0.9)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_flag_on_scores_rows_with_the_composite(
    app_client: AsyncClient, app_auth_headers: dict, shared_engine_fixture, monkeypatch
):
    """Z flagą: kompozyt 0–100, a `match_score` to DOKŁADNIE `total/100`.

    Ta równość jest całym kontraktem wstecznym: `MatchScoreBar` mnoży przez 100
    i gdyby te dwie liczby się rozjechały, pasek pokazywałby procent, którego
    nie da się odtworzyć z `total_score` obok niego.
    """
    job_id, cand_id, _ = shared_engine_fixture
    monkeypatch.setattr(settings, "AI_MATCHES_SHARED_ENGINE", True)
    _semantic_hits(monkeypatch, cand_id)

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["search_type"].startswith("semantic"), (
        "front uznaje odpowiedź za zdegradowaną, gdy `search_type` nie zaczyna "
        "się od 'semantic' — patrz jobs/[id]/page.tsx"
    )
    assert body["search_type"] == "semantic+composite"
    assert body["meta"]["mode"] == "semantic+composite"
    row = next(m for m in body["matches"] if m["candidate"]["id"] == cand_id)
    assert "total_score" in row and "breakdown" in row
    assert 0.0 <= row["match_score"] <= 1.0
    assert row["match_score"] == pytest.approx(row["total_score"] / 100.0, abs=0.005)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_min_score_keeps_its_zero_to_one_meaning_under_flag(
    app_client: AsyncClient, app_auth_headers: dict, shared_engine_fixture, monkeypatch
):
    """Jawny `min_score` nadal jest w skali 0–1 i nadal odsiewa."""
    job_id, cand_id, _ = shared_engine_fixture
    monkeypatch.setattr(settings, "AI_MATCHES_SHARED_ENGINE", True)
    _semantic_hits(monkeypatch, cand_id)

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 1.0, "limit": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["min_score"] == pytest.approx(1.0)
    assert body["matches"] == [], "próg 1.0 = kompozyt 100/100, nikt go nie osiąga"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_default_threshold_follows_the_sibling_list_under_flag(
    app_client: AsyncClient, app_auth_headers: dict, shared_engine_fixture, monkeypatch
):
    """Domyślna podłoga to `RECOMMENDATION_MIN_SCORE/100`, nie 0.5.

    Bez tego domyślne `AI_MATCH_MIN_SCORE=0.5` odsiałoby każdy kompozyt poniżej
    50/100 — czyli WIĘKSZOŚĆ realnych dopasowań, bo kompozyt hybrydowy ma niski
    zakres bezwzględny (stąd `RECOMMENDATION_MIN_SCORE=40`).
    """
    job_id, cand_id, _ = shared_engine_fixture
    monkeypatch.setattr(settings, "AI_MATCHES_SHARED_ENGINE", True)
    _semantic_hits(monkeypatch, cand_id)

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"limit": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["min_score"] == pytest.approx(
        settings.RECOMMENDATION_MIN_SCORE / 100.0, abs=0.001
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unmeasured_cosine_is_degraded_but_still_scored_under_flag(
    app_client: AsyncClient, app_auth_headers: dict, shared_engine_fixture, monkeypatch
):
    """Brak POMIARU kosinusu ≠ zmierzone zero.

    Stara ścieżka takie wiersze odrzuca (porównuje kosinus wprost z progiem,
    więc 0.0 udawałoby zmierzony brak dopasowania). Wspólny silnik je ZOSTAWIA,
    bo `bulk_get_or_compute` zna stan „brak pomiaru" — ale odpowiedź musi to
    powiedzieć, inaczej awaria dosypki wygląda jak zdrowy, słaby ranking.
    """
    job_id, cand_id, _ = shared_engine_fixture
    monkeypatch.setattr(settings, "AI_MATCHES_SHARED_ENGINE", True)
    _semantic_hits(monkeypatch, cand_id, unknown=True)

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"]["degraded"] is True
    assert body["meta"]["reason"] == "semantic_unavailable"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provider_outage_still_falls_back_under_flag(
    app_client: AsyncClient, app_auth_headers: dict, shared_engine_fixture, monkeypatch
):
    """Flaga nie może odebrać ścieżki ratunkowej — awaria nadal schodzi na tagi."""
    job_id, _cand_id, _ = shared_engine_fixture
    monkeypatch.setattr(settings, "AI_MATCHES_SHARED_ENGINE", True)
    monkeypatch.setattr(settings, "AI_MATCH_POOL_SIZE", 100_000)
    monkeypatch.setattr(settings, "MATCH_POOL_SIZE", 100_000)

    from app.services.embedding_service import SemanticSearchUnavailable

    async def _outage(*_a, **_kw):
        raise SemanticSearchUnavailable("qdrant down")

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _outage
    )

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["search_type"] == "tag_fallback"
    assert body["meta"]["degraded"] is True
    assert body["meta"]["reason"] == "semantic_unavailable"


def test_shared_engine_branch_stays_outside_any_swallowing_try():
    """Bramka dopuszczalności nie może wrócić pod `try` wraz z nową gałęzią.

    `_gate_and_dealbreakers` została WYCIĄGNIĘTA spod `try` w sierpniu 2026,
    bo wyjątek z samej bramki spychał request na gałąź tag-fallback, która
    bramki nie miała — bramka bezpieczeństwa, której własna awaria omijała
    bramkę bezpieczeństwa. Wspólny silnik dokłada gałąź obok niej i ten test
    pilnuje, że nie wciągnął jej z powrotem.
    """
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "app/api/matching.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    handler = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_ai_matches"
    )
    guarded: set[str] = set()
    for node in ast.walk(handler):
        if not isinstance(node, ast.Try):
            continue
        swallows = any(
            not any(isinstance(s, ast.Raise) for s in h.body) for h in node.handlers
        )
        if not swallows:
            continue
        for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                guarded.add(inner.func.id)
    assert "_gate_and_dealbreakers" not in guarded, (
        "bramka dopuszczalności wróciła pod połykający `try` — jej awaria "
        "znów spycha request na ścieżkę bez bramki"
    )
    assert "_shared_engine_matches" not in guarded, (
        "wspólny silnik pod połykającym `try` — awaria scoringu cicho "
        "degradowałaby do rankingu po tagach zamiast dać 500"
    )
