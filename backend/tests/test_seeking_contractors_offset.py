"""„Szukają projektu" musi dać się przejrzeć w całości (UAT B06).

Do 09.2026 handler brał z uporządkowanej puli wycinek ``[:page_size]`` i nie
przyjmował żadnego przesunięcia. Licznik mówił „50 z 2890", a do pozostałych
2840 osób nie prowadziła żadna droga poza zgadywaniem filtrów.

Testy idą przez PRAWDZIWY endpoint na bazie testowej (syntetyczni kandydaci),
bo defekt siedział w handlerze, nie w regule sortowania — ta była już objęta
``test_seeking_contractors_truncation.py``.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus

BACKEND = pathlib.Path(__file__).resolve().parents[1]
_SOURCE = BACKEND / "app/api/recommendations.py"


def _patch_pipeline(monkeypatch) -> None:
    from app.services import embedding_service

    async def _fake_embed(_text):
        return [0.1] * 1024

    async def _fake_search(_q, top_k=20, **kwargs):
        return []

    monkeypatch.setattr(embedding_service, "generate_embedding", _fake_embed)
    monkeypatch.setattr(embedding_service, "search_jobs_semantic", _fake_search)
    monkeypatch.setattr("app.api.recommendations.search_jobs_semantic", _fake_search)


async def _seed_looking(n: int) -> list[int]:
    ids: list[int] = []
    async with AsyncSessionLocal() as db:
        for _ in range(n):
            cand = Candidate(
                name=f"Offset-{uuid.uuid4().hex[:8]}",
                lastname="Tester",
                availability_status=AvailabilityStatus.actively_looking,
                status=CandidateStatus.active,
                skills=[{"name": "Python"}],
                years_it_experience=5,
            )
            db.add(cand)
            await db.flush()
            ids.append(cand.id)
        await db.commit()
    return ids


async def _cleanup(ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_offset_walks_the_whole_pool_without_gaps_or_repeats(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Kolejne okna (`offset`) pokrywają całą pulę: bez dziur i bez powtórek.

    Baza testowa bywa współdzielona, więc test nie zakłada, że w puli są TYLKO
    nasi kandydaci — sprawdza własności przejścia po stronach, a nie konkretne
    liczby.
    """
    ours = await _seed_looking(3)
    try:
        _patch_pipeline(monkeypatch)
        seen: list[int] = []
        offset = 0
        total = None
        for _ in range(500):  # bezpiecznik przed pętlą bez końca
            resp = await app_client.get(
                "/api/recommendations/seeking-contractors",
                params={"horizon_days": 1, "page_size": 2, "offset": offset},
                headers=app_auth_headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["offset"] == offset
            if total is None:
                total = body["total"]
            else:
                assert body["total"] == total, "`total` opisuje pulę, nie stronę"
            ids = [it["candidate"]["id"] for it in body["items"]]
            assert len(ids) == body["returned"] <= 2
            seen.extend(ids)
            if not body["truncated"]:
                break
            assert body["returned"] > 0, "przycięta strona bez wierszy = pętla"
            offset += body["returned"]
        else:
            raise AssertionError("strony nie kończą się — `truncated` nigdy nie gaśnie")

        assert len(seen) == len(set(seen)), "ten sam konsultant na dwóch stronach"
        assert set(ours).issubset(set(seen)), "kandydat spoza pierwszej strony przepadł"
        assert len(seen) == total, "suma stron musi zgadzać się z licznikiem"
    finally:
        await _cleanup(ours)


@pytest.mark.asyncio
async def test_last_page_is_not_reported_as_truncated(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """`truncated` liczy się od KOŃCA okna — ostatnia strona nie udaje przyciętej."""
    ours = await _seed_looking(2)
    try:
        _patch_pipeline(monkeypatch)
        # `page_size` ma sufit 200 (`le=200`) — powyżej endpoint odpowiada 422.
        first_resp = await app_client.get(
            "/api/recommendations/seeking-contractors",
            params={"horizon_days": 1, "page_size": 200},
            headers=app_auth_headers,
        )
        assert first_resp.status_code == 200, first_resp.text
        total = first_resp.json()["total"]
        assert total >= 2
        # Okno zaczynające się dokładnie na ostatnim wierszu.
        last_resp = await app_client.get(
            "/api/recommendations/seeking-contractors",
            params={"horizon_days": 1, "page_size": 200, "offset": total - 1},
            headers=app_auth_headers,
        )
        assert last_resp.status_code == 200, last_resp.text
        last = last_resp.json()
        assert last["returned"] == 1
        assert last["truncated"] is False
        # Okno ZA końcem puli: pusto, ale `total` nadal mówi prawdę.
        beyond = (
            await app_client.get(
                "/api/recommendations/seeking-contractors",
                params={"horizon_days": 1, "page_size": 10, "offset": total + 5},
                headers=app_auth_headers,
            )
        ).json()
        assert beyond["items"] == []
        assert beyond["truncated"] is False
        assert beyond["total"] == total
    finally:
        await _cleanup(ours)


def test_handler_no_longer_hardcodes_the_first_window() -> None:
    """Kontrakt na źródle: wycinek `[:page_size]` bez przesunięcia nie wraca."""
    src = _SOURCE.read_text()
    handler = ""
    for node in ast.walk(ast.parse(src)):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "seeking_contractors"
        ):
            handler = ast.get_source_segment(src, node) or ""
    assert handler, "seeking_contractors nie istnieje — zaktualizuj test"
    code = "\n".join(
        line for line in handler.splitlines() if not line.strip().startswith("#")
    )
    assert ")[:page_size]" not in code, "wrócił wycinek od zera — offset ignorowany"
    assert "offset : offset + page_size" in code
