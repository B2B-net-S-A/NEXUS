"""Smoke tests for /api/competence-categories endpoints.

Assumes migration 0033_cc_entities has been applied (5 seed rows present) and
0371_request_allocation switched the team to four categories (``data_ai``
stays in the table, inactive).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def test_list_competence_categories_returns_seed(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get("/api/competence-categories", headers=app_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    slugs = {cc["slug"] for cc in data}
    # Cztery kategorie zespołu (0371); wycofana "data_ai" nie jest aktywna.
    expected = {
        "infrastructure_operations",
        "software_development",
        "security_quality",
        "management_delivery",
    }
    assert expected.issubset(slugs)
    assert "data_ai" not in slugs

    # Each CC should have required shape
    for cc in data:
        assert "id" in cc
        assert "name_pl" in cc
        assert "keywords" in cc
        assert isinstance(cc["keywords"], list)


async def test_active_catalog_has_the_four_team_categories(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/competence-categories",
        params={"active_only": "true"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    by_slug = {cc["slug"]: cc["name_pl"] for cc in resp.json()}
    # Inne testy na wspólnej bazie mogą dopisać własne kategorie — sprawdzamy
    # nasze cztery, nie cały katalog.
    assert "data_ai" not in by_slug
    assert {
        slug: by_slug.get(slug)
        for slug in (
            "infrastructure_operations",
            "software_development",
            "security_quality",
            "management_delivery",
        )
    } == {
        "infrastructure_operations": "Infra & Operations & Security / Data & AI",
        "software_development": "Development",
        "security_quality": "QA",
        "management_delivery": "Management & Delivery (PM & BA)",
    }


async def test_cc_list_sorted_by_display_order(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get("/api/competence-categories", headers=app_auth_headers)
    data = resp.json()
    orders = [cc["display_order"] for cc in data]
    assert orders == sorted(orders)


async def test_cc_recruiters_404_on_missing(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/competence-categories/99999/recruiters", headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_cc_recruiters_returns_empty_or_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    # get first CC id
    list_resp = await app_client.get(
        "/api/competence-categories", headers=app_auth_headers
    )
    cc_id = list_resp.json()[0]["id"]

    resp = await app_client.get(
        f"/api/competence-categories/{cc_id}/recruiters",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_cc_recruiters_lists_active_accounts_only(
    app_client: AsyncClient, app_auth_headers: dict
):
    """02.10.2026: lista zasila blok „Kategoria” w panelu rekrutacji — pokazuje
    ludzi, którzy mogą wziąć request. Wyłączone konto z przypisaną kategorią
    (na produkcji zostały takie duplikaty) do nich nie należy."""
    from sqlalchemy import delete, update

    from app.core.database import AsyncSessionLocal
    from app.models.competence_category import UserCompetenceCategory
    from app.models.user import User, UserRole
    from tests._jarvis_helpers import make_user

    list_resp = await app_client.get(
        "/api/competence-categories", headers=app_auth_headers
    )
    cc_id = list_resp.json()[0]["id"]
    active_id, _ = await make_user(UserRole.recruiter)
    inactive_id, _ = await make_user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                UserCompetenceCategory(
                    user_id=user_id,
                    competence_category_id=cc_id,
                    is_primary=False,
                    priority=2,
                )
                for user_id in (active_id, inactive_id)
            ]
        )
        await db.execute(
            update(User).where(User.id == inactive_id).values(is_active=False)
        )
        await db.commit()
    try:
        for query in ({}, {"priority": 2}):
            resp = await app_client.get(
                f"/api/competence-categories/{cc_id}/recruiters",
                params=query,
                headers=app_auth_headers,
            )
            assert resp.status_code == 200, resp.text
            listed = {row["user_id"] for row in resp.json()}
            assert active_id in listed, query
            assert inactive_id not in listed, query
    finally:
        # Baza testowa jest wspólna: osoba z kategorią wchodzi do puli automatu
        # przydziału, który inne pliki uruchamiają na całej bazie.
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(UserCompetenceCategory).where(
                    UserCompetenceCategory.user_id.in_([active_id, inactive_id])
                )
            )
            await db.commit()


async def test_assign_cc_to_missing_candidate_is_404_not_500(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Runda 9 (R9-N8-13): brak kandydata = 404, nie naruszenie FK (500)."""
    list_resp = await app_client.get(
        "/api/competence-categories", headers=app_auth_headers
    )
    cc_id = list_resp.json()[0]["id"]
    resp = await app_client.post(
        "/api/candidates/999999999/competence-categories",
        json={"competence_category_id": cc_id, "is_primary": True},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404, resp.text


async def test_manual_primary_syncs_legacy_slug_and_unassign_clears_it(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Runda 10 (R10-N8-6): ręczna główna kategoria przestawia też slug.

    Slug `competence_category` czytają karta dla klienta, prep-kit, tekst
    embeddingu i wyszukiwarka — sam FK zostawiał tam starą kategorię AI.
    """
    import uuid

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    by_slug = {
        cc["slug"]: cc["id"]
        for cc in (
            await app_client.get("/api/competence-categories", headers=app_auth_headers)
        ).json()
    }
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Kat",
            lastname=f"Slug-{uuid.uuid4().hex[:6]}",
            email=f"ccslug-{uuid.uuid4().hex[:8]}@example.com",
            competence_category="software_development",
            competence_category_id=by_slug["software_development"],
        )
        db.add(cand)
        await db.commit()
        cand_id = cand.id

    qa_id = by_slug["security_quality"]
    resp = await app_client.post(
        f"/api/candidates/{cand_id}/competence-categories",
        json={"competence_category_id": qa_id, "is_primary": True},
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        assert row.competence_category_id == qa_id
        assert row.competence_category == "security_quality"

    resp = await app_client.delete(
        f"/api/candidates/{cand_id}/competence-categories/{qa_id}",
        headers=app_auth_headers,
    )
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        assert row.competence_category_id is None
        assert row.competence_category is None
