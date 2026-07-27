"""Tests for the editable draft endpoints (migracja 0058).

Coverage:
  GET  /api/contracts/{id}/draft       — lazy render with default template
  GET  /api/contracts/{id}/draft       — return existing content (no re-render)
  GET  /api/contracts/{id}/draft       — empty content if no default exists
  PATCH /api/contracts/{id}/draft      — save edited content_html
  PATCH /api/contracts/{id}/draft      — switch template (re-render)
  PATCH /api/contracts/{id}/draft      — 422 when neither field provided
  POST /api/contracts/{id}/draft/finalize — draft → ready_for_signature + document
  POST /api/contracts/{id}/draft/finalize — 409 when required fields missing

Each test seeds its own candidate + client + template + draft contract so
runs stay isolated regardless of pre-seeded test data.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    ContractWorkMode,
)
from app.models.contract_template import ContractTemplate


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _seed_candidate(**overrides) -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Draft",
            lastname=f"Test{unique}",
            email=f"draft-{unique}@example.com",
            legal_name=f"JDG Draft {unique}",
            nip=f"PL{unique}",
            **overrides,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_client(**overrides) -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(
            name=f"Klient Draft {unique}",
            legal_name=f"Klient Draft Sp. z o.o. {unique}",
            nip=f"7770{unique}",
            **overrides,
        )
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        return cli.id


async def _seed_template(
    contract_type: str = "b2b",
    is_default: bool = True,
    body: str | None = None,
) -> int:
    """Seed a ContractTemplate. When `is_default=True`, demote all other
    templates of the same `contract_type` first so the test can rely on a
    single deterministic default regardless of pre-seeded data left by other
    test files (which is essential because the `app_client` fixture shares
    one Postgres instance across the whole suite)."""
    from sqlalchemy import update

    unique = uuid.uuid4().hex[:6]
    content = body or (
        "<h1>Umowa B2B</h1>"
        "<p>Wykonawca: {{ candidate.full_name }} (NIP {{ candidate.nip }})</p>"
        "<p>Zamawiający: {{ client.name }} (NIP {{ client.nip }})</p>"
        "<p>Stawka: {{ contract.rate_candidate }} {{ contract.currency }}</p>"
    )
    async with AsyncSessionLocal() as db:
        if is_default:
            await db.execute(
                update(ContractTemplate)
                .where(ContractTemplate.contract_type == contract_type)
                .values(is_default=False)
            )
        tpl = ContractTemplate(
            name=f"Test Tpl {unique}",
            contract_type=contract_type,
            content_jinja=content,
            is_default=is_default,
        )
        db.add(tpl)
        await db.commit()
        await db.refresh(tpl)
        return tpl.id


async def _seed_draft_contract(
    candidate_id: int,
    client_id: int,
    *,
    contract_type: ContractType = ContractType.b2b,
    rate_candidate: int | None = None,
    rate_client: int | None = None,
    end_date: date | None = None,
    work_mode: ContractWorkMode | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            start_date=date.today(),
            end_date=end_date,
            rate_candidate=rate_candidate,
            rate_client=rate_client,
            contract_type=contract_type,
            status=ContractStatus.draft,
            work_mode=work_mode,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


# ── GET /draft ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_draft_lazy_renders_default_template(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand_id = await _seed_candidate()
    cli_id = await _seed_client()
    tpl_id = await _seed_template()
    contract_id = await _seed_draft_contract(cand_id, cli_id)

    resp = await app_client.get(
        f"/api/contracts/{contract_id}/draft", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["contract_id"] == contract_id
    assert body["template_id"] == tpl_id
    assert body["rendered_from_default"] is True
    assert body["content_html"] is not None
    # Merge fields populated from the seeded JDG data
    assert "Umowa B2B" in body["content_html"]
    # available_templates contains our template
    assert any(t["id"] == tpl_id for t in body["available_templates"])


@pytest.mark.asyncio
async def test_get_draft_returns_existing_content(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand_id = await _seed_candidate()
    cli_id = await _seed_client()
    await _seed_template()
    contract_id = await _seed_draft_contract(cand_id, cli_id)

    # First fetch lazy-renders.
    first = await app_client.get(
        f"/api/contracts/{contract_id}/draft", headers=app_auth_headers
    )
    assert first.status_code == 200
    rendered_at = first.json()["updated_at"]
    assert rendered_at is not None

    # Manual edit via PATCH.
    edited_html = "<p>Manualna edycja recruitera</p>"
    patch = await app_client.patch(
        f"/api/contracts/{contract_id}/draft",
        json={"content_html": edited_html},
        headers=app_auth_headers,
    )
    assert patch.status_code == 200, patch.text

    # Second GET MUST return the manual edit, not re-render.
    second = await app_client.get(
        f"/api/contracts/{contract_id}/draft", headers=app_auth_headers
    )
    assert second.status_code == 200
    assert second.json()["content_html"] == edited_html
    assert second.json()["rendered_from_default"] is False


@pytest.mark.asyncio
async def test_get_draft_no_default_template_returns_empty(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Use `uzlecenie` contract_type so we don't collide with b2b/uop
    defaults seeded by other test files. Then check that a non-default
    template alone does NOT trigger a render."""
    from sqlalchemy import update

    from app.models.contract_template import ContractTemplate

    cand_id = await _seed_candidate()
    cli_id = await _seed_client()

    # Defensive: even for `uzlecenie`, demote any pre-existing default templates
    # so this test is hermetic regardless of seed history.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ContractTemplate)
            .where(ContractTemplate.contract_type == "uzlecenie")
            .values(is_default=False)
        )
        await db.commit()

    await _seed_template(contract_type="uzlecenie", is_default=False)
    contract_id = await _seed_draft_contract(
        cand_id, cli_id, contract_type=ContractType.uzlecenie
    )

    resp = await app_client.get(
        f"/api/contracts/{contract_id}/draft", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content_html"] is None
    assert body["template_id"] is None
    assert body["rendered_from_default"] is False
    # FE has at least one uzlecenie template available to choose from
    assert any(
        t["contract_type"] == "uzlecenie" for t in body["available_templates"]
    )


# ── PATCH /draft ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_draft_saves_content(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand_id = await _seed_candidate()
    cli_id = await _seed_client()
    await _seed_template()
    contract_id = await _seed_draft_contract(cand_id, cli_id)

    new_html = "<h1>Nowa wersja</h1><p>edycja {}</p>".format(uuid.uuid4().hex[:6])
    resp = await app_client.patch(
        f"/api/contracts/{contract_id}/draft",
        json={"content_html": new_html},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content_html"] == new_html
    assert body["updated_at"] is not None
    assert body["updated_by"] is not None


@pytest.mark.asyncio
async def test_patch_draft_changes_template_rerenders(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand_id = await _seed_candidate()
    cli_id = await _seed_client()
    default_tpl = await _seed_template()
    other_tpl = await _seed_template(
        is_default=False,
        body="<h2>WARIANT B</h2><p>{{ candidate.full_name }}</p>",
    )
    contract_id = await _seed_draft_contract(cand_id, cli_id)

    # Lazy render with default first.
    first = await app_client.get(
        f"/api/contracts/{contract_id}/draft", headers=app_auth_headers
    )
    assert first.status_code == 200
    assert first.json()["template_id"] == default_tpl

    # Switch template.
    swap = await app_client.patch(
        f"/api/contracts/{contract_id}/draft",
        json={"template_id": other_tpl},
        headers=app_auth_headers,
    )
    assert swap.status_code == 200, swap.text
    body = swap.json()
    assert body["template_id"] == other_tpl
    assert "WARIANT B" in body["content_html"]


@pytest.mark.asyncio
async def test_patch_draft_rejects_empty_payload(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand_id = await _seed_candidate()
    cli_id = await _seed_client()
    contract_id = await _seed_draft_contract(cand_id, cli_id)

    resp = await app_client.patch(
        f"/api/contracts/{contract_id}/draft",
        json={},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


# ── POST /draft/finalize ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_draft_moves_to_ready_for_signature(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand_id = await _seed_candidate()
    cli_id = await _seed_client()
    await _seed_template()
    contract_id = await _seed_draft_contract(
        cand_id,
        cli_id,
        rate_candidate=15000,
        rate_client=20000,
        end_date=date.today() + timedelta(days=120),
        work_mode=ContractWorkMode.remote,
    )

    # Initialize draft body so finalize doesn't 422 on empty content.
    init = await app_client.get(
        f"/api/contracts/{contract_id}/draft", headers=app_auth_headers
    )
    assert init.status_code == 200
    assert init.json()["content_html"] is not None

    finalize = await app_client.post(
        f"/api/contracts/{contract_id}/draft/finalize",
        headers=app_auth_headers,
    )
    assert finalize.status_code == 200, finalize.text
    body = finalize.json()
    # Finalizing an unsigned draft parks it at `ready_for_signature`, never
    # `active` (P1-CONTRACT-01) — reaching `active` requires signed evidence.
    assert body["status"] == "ready_for_signature"
    assert body["document_id"] is not None
    assert body["document_filename"].endswith(".html")

    # Document landed on the contract documents endpoint.
    docs = await app_client.get(
        f"/api/contracts/{contract_id}/documents", headers=app_auth_headers
    )
    assert docs.status_code == 200
    assert any(d["id"] == body["document_id"] for d in docs.json())


@pytest.mark.asyncio
async def test_finalize_draft_validates_required_fields(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand_id = await _seed_candidate()
    cli_id = await _seed_client()
    await _seed_template()
    # Intentionally skip rate_client / work_mode — should trigger 409.
    contract_id = await _seed_draft_contract(cand_id, cli_id)

    # Initialize draft body so we hit field validation, not the empty-body guard.
    init = await app_client.get(
        f"/api/contracts/{contract_id}/draft", headers=app_auth_headers
    )
    assert init.status_code == 200

    resp = await app_client.post(
        f"/api/contracts/{contract_id}/draft/finalize",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "missing" in detail
    assert "rate_client" in detail["missing"]
