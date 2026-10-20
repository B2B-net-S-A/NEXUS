"""Tests for Phase 9 B1 — contract templates + render."""

from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.contract_template import ContractTemplate


async def test_list_templates_ok(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get("/api/contract-templates", headers=app_auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_template_round_trip_and_render(
    app_client: AsyncClient, app_auth_headers: dict
):
    # Need an existing contract to render against.
    contracts = (
        (await app_client.get("/api/contracts?page_size=1", headers=app_auth_headers))
        .json()
        .get("items", [])
    )
    if not contracts:
        return
    cid = contracts[0]["id"]

    payload = {
        "name": "Test B2B Template",
        "contract_type": "b2b",
        "content_jinja": (
            "<h1>Umowa {{ contract.id }}</h1>"
            "<p>Wykonawca: {{ candidate.full_name }}</p>"
            "<p>Klient: {{ client.name }}</p>"
        ),
        "is_default": False,
    }
    created = await app_client.post(
        "/api/contract-templates", json=payload, headers=app_auth_headers
    )
    assert created.status_code == 201, created.text
    tpl = created.json()

    # Render
    rendered = await app_client.get(
        f"/api/contract-templates/{tpl['id']}/render",
        params={"contract_id": cid},
        headers=app_auth_headers,
    )
    assert rendered.status_code == 200
    assert "<h1>Umowa" in rendered.text

    # Clean up
    deleted = await app_client.delete(
        f"/api/contract-templates/{tpl['id']}", headers=app_auth_headers
    )
    assert deleted.status_code == 204


async def test_template_invalid_jinja_rejected(
    app_client: AsyncClient, app_auth_headers: dict
):
    payload = {
        "name": "Bad syntax",
        "contract_type": "b2b",
        "content_jinja": "{% if %}",  # syntax error
    }
    resp = await app_client.post(
        "/api/contract-templates", json=payload, headers=app_auth_headers
    )
    assert resp.status_code == 422


async def test_template_render_404(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-templates/999999/render?contract_id=1",
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


async def test_new_default_template_clears_previous_default_of_same_type_and_language(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Jeden domyślny wzór na typ (20.10.2026).

    Do 20.10 zaznaczenie „Domyślny” na drugim wzorze zostawiało dwa domyślne —
    na produkcji domyślny był wzór z testu smoke obok „Umowa B2B (PL)”.
    """
    kind = "test_default_one"
    body = {"contract_type": kind, "content_jinja": "<p>{{ contract.id }}</p>"}
    first = await app_client.post(
        "/api/contract-templates",
        json={**body, "name": "Pierwszy", "is_default": True},
        headers=app_auth_headers,
    )
    assert first.status_code == 201, first.text
    second = await app_client.post(
        "/api/contract-templates",
        json={**body, "name": "Drugi", "is_default": False},
        headers=app_auth_headers,
    )
    assert second.status_code == 201, second.text
    ids = [first.json()["id"], second.json()["id"]]
    try:
        promoted = await app_client.patch(
            f"/api/contract-templates/{ids[1]}",
            json={"is_default": True},
            headers=app_auth_headers,
        )
        assert promoted.status_code == 200, promoted.text

        listed = (
            await app_client.get(
                "/api/contract-templates",
                params={"contract_type": kind},
                headers=app_auth_headers,
            )
        ).json()
        defaults = {t["name"]: t["is_default"] for t in listed}
        assert defaults == {"Pierwszy": False, "Drugi": True}

        # Nowy wzór tworzony od razu jako domyślny też przejmuje znacznik.
        third = await app_client.post(
            "/api/contract-templates",
            json={**body, "name": "Trzeci", "is_default": True},
            headers=app_auth_headers,
        )
        assert third.status_code == 201, third.text
        ids.append(third.json()["id"])
        listed = (
            await app_client.get(
                "/api/contract-templates",
                params={"contract_type": kind},
                headers=app_auth_headers,
            )
        ).json()
        assert [t["name"] for t in listed if t["is_default"]] == ["Trzeci"]
    finally:
        for template_id in ids:
            await app_client.delete(
                f"/api/contract-templates/{template_id}", headers=app_auth_headers
            )


async def test_default_is_one_per_type_even_across_languages(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Szkic umowy przy kontrakcie bierze PIERWSZY domyślny wzór typu, bez
    języka (`contracts._list_templates_for_contract_type` + `next(...)`), więc
    dwa domyślne (PL i EN) = szkic po cichu z wersji EN (sprawdzone na
    produkcji 20.10.2026 po wdrożeniu #2430). Generator B2B wybiera wzór po
    języku i `is_default` nie czyta — klucz „typ i język” był błędny.
    """
    kind = "test_default_lang"
    body = {"contract_type": kind, "content_jinja": "<p>{{ contract.id }}</p>"}
    ids = []
    try:
        for name in ("Wzór PL", "Wzór EN"):
            created = await app_client.post(
                "/api/contract-templates",
                json={**body, "name": name, "is_default": False},
                headers=app_auth_headers,
            )
            assert created.status_code == 201, created.text
            ids.append(created.json()["id"])
        async with AsyncSessionLocal() as db:
            for template_id, lang in zip(ids, ("pl", "en")):
                await db.execute(
                    update(ContractTemplate)
                    .where(ContractTemplate.id == template_id)
                    .values(language=lang)
                )
            await db.commit()

        for template_id in ids:
            promoted = await app_client.patch(
                f"/api/contract-templates/{template_id}",
                json={"is_default": True},
                headers=app_auth_headers,
            )
            assert promoted.status_code == 200, promoted.text

        listed = (
            await app_client.get(
                "/api/contract-templates",
                params={"contract_type": kind},
                headers=app_auth_headers,
            )
        ).json()
        assert [t["name"] for t in listed if t["is_default"]] == ["Wzór EN"]
    finally:
        for template_id in ids:
            await app_client.delete(
                f"/api/contract-templates/{template_id}", headers=app_auth_headers
            )

