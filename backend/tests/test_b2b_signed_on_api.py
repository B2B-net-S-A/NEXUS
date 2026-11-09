"""„Oznacz jako podpisaną”: plik obowiązkowy, dzień z podpisu konsultanta (06.11.2026).

Prawdziwy PDF podpisany pyHanko w teście; konsultant to kandydat z umowy
(``partner_name``), firma to konto w NEXUSIE. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract_document import ContractDocument
from app.models.user import User, UserRole
from tests._confirm_signed import confirm_request
from tests._signed_pdf import blank_pdf, signed_by
from tests.test_b2b_signature_automation import (
    CONFIRM_PATH,
    _backdate_generation,
    _counts_for_pair,
    _current_admin_id,
    _headers_for_role,
    _seed_bound_scenario,
)

pytest.importorskip("pyhanko")

_WAW = ZoneInfo("Europe/Warsaw")


async def _partner(generated_id: int) -> str:
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, generated_id)
        assert row is not None and row.partner_name
        return row.partner_name


async def _admin_name(app_client: AsyncClient) -> str:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, await _current_admin_id(app_client))
        assert user is not None and user.name
        return user.name


def _signed_morning(days_ago: int) -> datetime:
    day = business_today() - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, 7, 32, tzinfo=_WAW).astimezone(
        timezone.utc
    )


async def _scenario(app_client: AsyncClient) -> dict:
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    await _backdate_generation(scenario["generated_id"], days=10)
    return scenario


def _upload(pdf: bytes) -> dict:
    return {"files": {"file": ("umowa-podpisana.pdf", pdf, "application/pdf")}}


@pytest.mark.asyncio
async def test_preview_lists_signatures_with_parties_and_saves_nothing(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _scenario(app_client)
    consultant_at = _signed_morning(4)
    pdf = await signed_by(
        (await _partner(scenario["generated_id"]), consultant_at),
        (await _admin_name(app_client), _signed_morning(3)),
    )

    response = await app_client.post(
        f"/api/b2b-generator/generated/{scenario['generated_id']}/signatures",
        headers=app_auth_headers,
        **_upload(pdf),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "pdf"
    assert [s["party"] for s in body["signatures"]] == ["consultant", "company"]
    assert (
        body["consultant_signed_on"]
        == (business_today() - timedelta(days=4)).isoformat()
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None and row.signature_status == "unsigned"


@pytest.mark.asyncio
async def test_confirm_takes_the_day_from_the_consultant_signature(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _scenario(app_client)
    consultant_at = _signed_morning(4)
    pdf = await signed_by(
        (await _partner(scenario["generated_id"]), consultant_at),
        (await _admin_name(app_client), _signed_morning(1)),
    )

    response = await app_client.post(
        CONFIRM_PATH.format(generated_id=scenario["generated_id"]),
        headers=app_auth_headers,
        # Ręczna data z okna nie wygrywa z podpisem w pliku.
        **confirm_request(pdf=pdf, signed_on=business_today()),
    )

    assert response.status_code == 200, response.text
    item = response.json()["generated_contract"]
    expected = (business_today() - timedelta(days=4)).isoformat()
    assert item["signed_on"] == expected
    assert item["signed_on_source"] == "pdf"
    assert item["signed_document_id"] is not None
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None
        assert row.consultant_signed_at == consultant_at
        assert row.signed_on_set_by is None
        document = await db.get(ContractDocument, row.signed_document_id)
        assert document is not None and document.contract_id == row.contract_id


@pytest.mark.asyncio
async def test_pdf_without_the_consultant_signature_cannot_be_confirmed(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _scenario(app_client)
    pdf = await signed_by((await _admin_name(app_client), _signed_morning(2)))

    response = await app_client.post(
        CONFIRM_PATH.format(generated_id=scenario["generated_id"]),
        headers=app_auth_headers,
        **confirm_request(pdf=pdf),
    )

    assert response.status_code == 422, response.text
    assert "nie ma podpisu konsultanta" in response.json()["detail"]
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        0,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None and row.signature_status == "unsigned"


@pytest.mark.asyncio
async def test_handwritten_scan_needs_a_date_and_a_reason(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _scenario(app_client)
    path = CONFIRM_PATH.format(generated_id=scenario["generated_id"])
    day = business_today() - timedelta(days=2)

    no_reason = await app_client.post(
        path,
        headers=app_auth_headers,
        **confirm_request(signed_on=day, reason=None),
    )
    assert no_reason.status_code == 422, no_reason.text
    assert "powód" in no_reason.json()["detail"]

    response = await app_client.post(
        path,
        headers=app_auth_headers,
        **confirm_request(
            signed_on=day, reason="podpis odręczny, skan od reprezentanta"
        ),
    )
    assert response.status_code == 200, response.text
    item = response.json()["generated_contract"]
    assert item["signed_on"] == day.isoformat()
    assert item["signed_on_source"] == "manual"
    assert item["signed_on_reason"] == "podpis odręczny, skan od reprezentanta"
    assert item["signed_on_set_by_name"]


@pytest.mark.asyncio
async def test_confirm_without_a_file_is_refused(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _scenario(app_client)
    response = await app_client.post(
        CONFIRM_PATH.format(generated_id=scenario["generated_id"]),
        headers=app_auth_headers,
        json={"signed_on": business_today().isoformat()},
    )
    assert response.status_code == 422, response.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(B2BGeneratedContract).where(
                B2BGeneratedContract.id == scenario["generated_id"]
            )
        )
        assert row is not None and row.signature_status == "unsigned"


@pytest.mark.asyncio
async def test_preview_needs_the_signature_permission(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _scenario(app_client)
    headers = await _headers_for_role(app_client, UserRole.recruiter)
    response = await app_client.post(
        f"/api/b2b-generator/generated/{scenario['generated_id']}/signatures",
        headers=headers,
        **_upload(blank_pdf()),
    )
    assert response.status_code == 403, response.text
