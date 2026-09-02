"""Integration tests for generated-contract signature automation.

The generated-contract row is the idempotency anchor.  Confirming a bilateral
signature must atomically:

* create or reuse one B2B ``Contract`` for the candidate/job pair,
* ensure one open ``ClientOrder``,
* append ``CandidateStage.hired`` at most once,
* expose the linkage in candidate/contractor projections, and
* make the legal-history row immutable.

The tests use the in-process FastAPI client and the CI PostgreSQL service.  No
external signer is involved: this endpoint records a manual confirmation, not
QES evidence.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.document_signature import DocumentSignature
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole


CONFIRM_PATH = "/api/b2b-generator/generated/{generated_id}/confirm-fully-signed"


def _unique_number() -> tuple[int, int, str]:
    """Return a race-safe-enough direct-seed number outside normal production years."""
    year = 2099
    seq = int(uuid.uuid4().hex[:7], 16)
    return year, seq, f"{seq}/{year}"


async def _current_admin_id(app_client: AsyncClient) -> int:
    email = app_client.headers.get("X-Test-Admin-Email")
    assert email
    async with AsyncSessionLocal() as db:
        user_id = await db.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    return user_id


async def _headers_for_role(
    app_client: AsyncClient,
    role: UserRole,
) -> dict[str, str]:
    """Create and authenticate one role-specific user."""
    unique = uuid.uuid4().hex[:8]
    email = f"signature-{role.value}-{unique}@example.com"
    password = f"S1gn_{unique}!Pass"
    from app.core.security import hash_password

    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Signature {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
            email_verified=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Test-User-Id": str(user_id),
    }


async def _seed_legacy_generated(*, created_by: int | None = None) -> int:
    """Seed the shape that predates candidate/job/signature columns.

    Omitting every new attribute exercises ORM/DTO backwards compatibility.
    Preservation of a pre-0196 row is covered by the hosted Alembic CI probe.
    """
    year, seq, number = _unique_number()
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            year=year,
            seq=seq,
            contract_number=number,
            partner_name="Legacy Partner",
            client_name="Legacy Client",
            language="pl",
            signing_date=date(2026, 7, 24),
            created_by=created_by,
            render_payload={
                "language": "pl",
                "partner_name": "Legacy Partner",
                "client_name": "Legacy Client",
                "contract_number": number,
            },
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _seed_bound_scenario(
    *, created_by: int, entry_stage: PipelineStage = PipelineStage.onboarding
) -> dict[str, Any]:
    """Seed a candidate in one recruitment plus a linked unsigned DOCX row.

    ``entry_stage`` lets a test start from a terminal stage — a Traffit-imported
    ``rejected`` history is the common real-world shape and leaves the pair with
    no open recruitment process.
    """
    unique = uuid.uuid4().hex[:8]
    year, seq, number = _unique_number()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Signature Client {unique}")
        candidate = Candidate(
            name="Anna",
            lastname=f"Signature-{unique}",
            email=f"signature-candidate-{unique}@example.com",
            phone="+48 600 100 200",
            legal_name=f"Anna Signature {unique}",
            nip=f"77{int(unique[:6], 16):08d}"[:10],
            created_by=created_by,
        )
        db.add_all([client, candidate])
        await db.flush()

        job = Job(
            title=f"Senior Backend Engineer {unique}",
            client_id=client.id,
            status=JobStatus.published,
        )
        db.add(job)
        await db.flush()

        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=entry_stage,
                moved_by=created_by,
            )
        )
        generated = B2BGeneratedContract(
            year=year,
            seq=seq,
            contract_number=number,
            partner_name=f"{candidate.name} {candidate.lastname}",
            client_name=client.name,
            language="pl",
            signing_date=date(2026, 7, 24),
            created_by=created_by,
            candidate_id=candidate.id,
            job_id=job.id,
            client_id=client.id,
            render_payload={
                "candidate_id": candidate.id,
                "job_id": job.id,
                "role_id": None,
                "language": "pl",
                "partner_name": f"{candidate.name} {candidate.lastname}",
                "partner_legal_name": candidate.legal_name,
                "partner_nip": candidate.nip,
                "partner_phone": candidate.phone,
                "partner_email": candidate.email,
                "client_name": client.name,
                "contract_number": number,
                "signing_date": "2026-07-24",
                "start_date": "2026-08-01",
                "project_city": "Warszawa",
                "project_description": "Rozwój systemu bankowego.",
                "partner_correspondence_address": "ul. Testowa 1, Warszawa",
                "rate_candidate": 150.5,
                "currency": "PLN",
                "rate_in_words": "sto pięćdziesiąt złotych pięćdziesiąt groszy",
            },
        )
        db.add(generated)
        await db.commit()
        return {
            "generated_id": generated.id,
            "candidate_id": candidate.id,
            "job_id": job.id,
            "client_id": client.id,
            "client_name": client.name,
            "contract_number": number,
        }


async def _seed_second_generated(scenario: dict[str, Any], *, created_by: int) -> int:
    """Create another unsigned document for the same candidate/job pair."""
    year, seq, number = _unique_number()
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            year=year,
            seq=seq,
            contract_number=number,
            partner_name="Anna Signature",
            client_name=scenario["client_name"],
            language="pl",
            signing_date=date(2026, 7, 24),
            created_by=created_by,
            candidate_id=scenario["candidate_id"],
            job_id=scenario["job_id"],
            client_id=scenario["client_id"],
            render_payload={
                "candidate_id": scenario["candidate_id"],
                "job_id": scenario["job_id"],
                "language": "pl",
                "partner_name": "Anna Signature",
                "client_name": scenario["client_name"],
                "contract_number": number,
                "start_date": "2026-08-01",
            },
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _confirm(
    app_client: AsyncClient,
    headers: dict[str, str],
    generated_id: int,
    payload: dict[str, int] | None = None,
):
    return await app_client.post(
        CONFIRM_PATH.format(generated_id=generated_id),
        json=payload or {},
        headers=headers,
    )


async def _counts_for_pair(candidate_id: int, job_id: int) -> tuple[int, int, int]:
    async with AsyncSessionLocal() as db:
        contract_count = await db.scalar(
            select(func.count(Contract.id)).where(
                Contract.candidate_id == candidate_id,
                Contract.job_id == job_id,
            )
        )
        order_count = await db.scalar(
            select(func.count(ClientOrder.id))
            .join(Contract, Contract.id == ClientOrder.contract_id)
            .where(
                Contract.candidate_id == candidate_id,
                ClientOrder.job_id == job_id,
            )
        )
        hired_count = await db.scalar(
            select(func.count(CandidateStage.id)).where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
                CandidateStage.stage == PipelineStage.hired,
            )
        )
    return int(contract_count or 0), int(order_count or 0), int(hired_count or 0)


async def _seed_existing_contract(
    scenario: dict[str, Any],
    *,
    status: ContractStatus = ContractStatus.draft,
    start_date: date | None = None,
    rate_candidate: Decimal | None = None,
    currency: str = "PLN",
    rate_unit: RateUnit = RateUnit.hourly,
    rate_client: Decimal | None = None,
    with_rate_schedule: bool = False,
) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=scenario["candidate_id"],
            client_id=scenario["client_id"],
            job_id=scenario["job_id"],
            contract_type=ContractType.b2b,
            status=status,
            start_date=start_date or date(2026, 8, 1),
            rate_candidate=rate_candidate or Decimal("150.500"),
            rate_client=rate_client,
            rate_unit=rate_unit,
            currency=currency,
        )
        db.add(contract)
        await db.flush()
        if with_rate_schedule:
            db.add(
                ContractCandidateRate(
                    contract_id=contract.id,
                    rate=contract.rate_candidate,
                    effective_from=contract.start_date,
                    created_by=scenario.get("created_by"),
                )
            )
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _seed_generator_dependencies() -> int:
    """Seed a unique role and ensure a PL HTML template for `/generate`."""
    from app.models.b2b_contract_role import B2BContractRole
    from app.models.contract_template import ContractTemplate

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        role = B2BContractRole(
            category_key="dev",
            category_label_pl="Development",
            category_label_en="Development",
            slug=f"signature-retry-{unique}",
            name_pl=f"Signature Retry {unique}",
            name_en=f"Signature Retry {unique}",
            area_label_pl="Rozwój oprogramowania",
            area_label_en="Software development",
            scope_pl=["Rozwój oprogramowania"],
            scope_en=["Software development"],
            display_order=9999,
            is_active=True,
        )
        db.add(role)
        template_exists = await db.scalar(
            select(ContractTemplate.id).where(
                ContractTemplate.contract_type == "b2b",
                ContractTemplate.language == "pl",
            )
        )
        if template_exists is None:
            db.add(
                ContractTemplate(
                    name=f"Signature Retry PL {unique}",
                    contract_type="b2b",
                    language="pl",
                    content_jinja=(
                        "<h1>Umowa {{ b2b.contract_number or '' }}</h1>"
                        "<p>{{ candidate.full_name }}</p>"
                    ),
                    is_default=False,
                )
            )
        await db.commit()
        await db.refresh(role)
        return role.id


@pytest.mark.asyncio
async def test_legacy_generated_dto_defaults_to_unsigned(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    generated_id = await _seed_legacy_generated(
        created_by=await _current_admin_id(app_client)
    )

    response = await app_client.get(
        "/api/b2b-generator/generated?limit=200", headers=app_auth_headers
    )

    assert response.status_code == 200, response.text
    item = next(row for row in response.json() if row["id"] == generated_id)
    assert item["signature_status"] == "unsigned"
    assert item["signature_source"] is None
    assert item["candidate_id"] is None
    assert item["job_id"] is None
    assert item["client_id"] is None
    assert item["contract_id"] is None
    assert item["signed_at"] is None
    assert item["signed_by_name"] is None
    assert item["can_confirm_signed"] is True
    assert item["blocked_reason"] is None


@pytest.mark.asyncio
async def test_confirm_fully_signed_creates_complete_atomic_handoff(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    admin_id = await _current_admin_id(app_client)
    scenario = await _seed_bound_scenario(created_by=admin_id)

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "created"
    assert isinstance(body["contract_id"], int)
    assert isinstance(body["order_id"], int)
    assert body["candidate_id"] == scenario["candidate_id"]
    assert body["job_id"] == scenario["job_id"]
    assert body["client_id"] == scenario["client_id"]
    assert body["message"]
    assert body["generated_contract"]["signature_status"] == "signed_both"
    assert body["generated_contract"]["signature_source"] == "manual_confirmation"
    assert body["generated_contract"]["contract_id"] == body["contract_id"]
    assert body["generated_contract"]["signed_at"] is not None
    assert body["generated_contract"]["can_confirm_signed"] is False

    async with AsyncSessionLocal() as db:
        contracts = list(
            (
                await db.scalars(
                    select(Contract).where(
                        Contract.candidate_id == scenario["candidate_id"],
                        Contract.job_id == scenario["job_id"],
                    )
                )
            ).all()
        )
        assert len(contracts) == 1
        contract = contracts[0]
        assert contract.id == body["contract_id"]
        assert contract.client_id == scenario["client_id"]
        assert contract.contract_type == ContractType.b2b
        assert contract.status == ContractStatus.draft
        assert contract.start_date == date(2026, 8, 1)
        assert contract.rate_candidate == Decimal("150.500")
        assert contract.rate_unit == RateUnit.hourly

        candidate_row = await db.get(Candidate, scenario["candidate_id"])
        assert candidate_row is not None
        assert candidate_row.status == CandidateStatus.active

        detail = await db.scalar(
            select(B2BContractDetail).where(
                B2BContractDetail.contract_id == contract.id
            )
        )
        assert detail is not None
        assert detail.contract_number == scenario["contract_number"]
        assert detail.signing_date == date(2026, 7, 24)
        assert detail.project_city == "Warszawa"
        assert detail.project_description == "Rozwój systemu bankowego."
        assert detail.correspondence_address == "ul. Testowa 1, Warszawa"
        assert detail.language == "pl"

        order = await db.get(ClientOrder, body["order_id"])
        assert order is not None
        assert order.contract_id == contract.id
        assert order.job_id == scenario["job_id"]
        assert order.client_id == scenario["client_id"]
        assert order.status == ClientOrderStatus.draft

        latest_stage = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == scenario["candidate_id"],
                CandidateStage.job_id == scenario["job_id"],
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        assert latest_stage is not None
        assert latest_stage.stage == PipelineStage.hired
        assert latest_stage.moved_by == admin_id

        generated_audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "b2b_generated_contract",
                Activity.entity_id == scenario["generated_id"],
                Activity.action == "fully_signed_confirmed",
            )
        )
        assert generated_audit is not None
        assert generated_audit.user_id == admin_id

        contract_audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract.id,
                Activity.action == "auto_drafted_from_generated_contract",
            )
        )
        assert contract_audit is not None
        assert contract_audit.user_id == admin_id

        signature_count = await db.scalar(
            select(func.count(DocumentSignature.id)).where(
                DocumentSignature.contract_id == contract.id
            )
        )
        assert signature_count == 0

    candidate = await app_client.get(
        f"/api/candidates/{scenario['candidate_id']}", headers=app_auth_headers
    )
    assert candidate.status_code == 200, candidate.text
    employment = candidate.json()["employment"]
    assert employment["state"] == "employed_at_client"
    assert employment["client_id"] == scenario["client_id"]
    assert employment["client_name"] == scenario["client_name"]
    assert employment["contract_id"] == body["contract_id"]
    assert employment["job_id"] == scenario["job_id"]


@pytest.mark.asyncio
async def test_confirm_signs_when_the_recruitment_history_is_already_closed(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Priority Lock must not turn a closed recruitment into a failed signature.

    Traffit-imported history routinely ends on ``rejected``, so the pair has no
    open process and the hired hook runs with ``require_existing=True``.  At the
    default ``off`` mode that must stay inert.
    """

    admin_id = await _current_admin_id(app_client)
    scenario = await _seed_bound_scenario(
        created_by=admin_id, entry_stage=PipelineStage.rejected
    )

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generated_contract"]["signature_status"] == "signed_both"
    assert isinstance(body["contract_id"], int)

    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None
        assert row.contract_id == body["contract_id"]

        latest_stage = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == scenario["candidate_id"],
                CandidateStage.job_id == scenario["job_id"],
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        assert latest_stage is not None
        assert latest_stage.stage == PipelineStage.hired


@pytest.mark.asyncio
async def test_confirm_repeat_is_idempotent(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )

    first = await _confirm(app_client, app_auth_headers, scenario["generated_id"])
    second = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["outcome"] == "created"
    assert second.json()["outcome"] == "already_processed"
    assert second.json()["contract_id"] == first.json()["contract_id"]
    assert second.json()["order_id"] == first.json()["order_id"]
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        1,
        1,
    )


@pytest.mark.asyncio
async def test_concurrent_documents_for_one_recruitment_share_one_contractor(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    admin_id = await _current_admin_id(app_client)
    scenario = await _seed_bound_scenario(created_by=admin_id)
    second_generated_id = await _seed_second_generated(scenario, created_by=admin_id)

    first, second = await asyncio.gather(
        _confirm(app_client, app_auth_headers, scenario["generated_id"]),
        _confirm(app_client, app_auth_headers, second_generated_id),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert {first.json()["outcome"], second.json()["outcome"]} == {
        "created",
        "linked_existing",
    }
    assert first.json()["contract_id"] == second.json()["contract_id"]
    assert first.json()["order_id"] == second.json()["order_id"]
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        1,
        1,
    )


@pytest.mark.asyncio
async def test_concurrent_pipeline_hire_and_signature_create_one_hired_handoff(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )

    confirmed, moved = await asyncio.gather(
        _confirm(app_client, app_auth_headers, scenario["generated_id"]),
        app_client.post(
            "/api/pipeline/move",
            json={
                "candidate_id": scenario["candidate_id"],
                "job_id": scenario["job_id"],
                "stage": "hired",
            },
            headers=app_auth_headers,
        ),
    )

    assert confirmed.status_code == 200, confirmed.text
    assert moved.status_code == 200, moved.text
    assert moved.json()["stage"] == "hired"
    assert confirmed.json()["outcome"] in {"created", "linked_existing"}
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        1,
        1,
    )


@pytest.mark.asyncio
async def test_two_concurrent_pipeline_hires_are_idempotent(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    payload = {
        "candidate_id": scenario["candidate_id"],
        "job_id": scenario["job_id"],
        "stage": "hired",
    }

    first, second = await asyncio.gather(
        app_client.post(
            "/api/pipeline/move",
            json=payload,
            headers=app_auth_headers,
        ),
        app_client.post(
            "/api/pipeline/move",
            json=payload,
            headers=app_auth_headers,
        ),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["stage"] == "hired"
    assert second.json()["stage"] == "hired"
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        1,
        1,
    )


@pytest.mark.asyncio
async def test_confirm_links_existing_ready_contract_and_lists_contractor(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    async with AsyncSessionLocal() as db:
        existing = Contract(
            candidate_id=scenario["candidate_id"],
            client_id=scenario["client_id"],
            job_id=scenario["job_id"],
            contract_type=ContractType.b2b,
            status=ContractStatus.ready_for_signature,
            start_date=date(2026, 8, 1),
            rate_candidate=Decimal("150.500"),
            rate_unit=RateUnit.hourly,
        )
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
        existing_id = existing.id

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "linked_existing"
    assert body["contract_id"] == existing_id
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        1,
        1,
    )

    contractors = await app_client.get(
        "/api/contractors?status=draft&page_size=200",
        headers=app_auth_headers,
    )
    assert contractors.status_code == 200, contractors.text
    item = next(
        row for row in contractors.json()["items"] if row["contract_id"] == existing_id
    )
    assert item["candidate"]["id"] == scenario["candidate_id"]
    assert item["status"] == "ready_for_signature"

    async with AsyncSessionLocal() as db:
        linked_audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == existing_id,
                Activity.action == "linked_to_generated_contract",
            )
        )
        assert linked_audit is not None


@pytest.mark.asyncio
async def test_confirm_reuses_pipeline_placeholder_and_replaces_only_its_defaults(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    admin_id = await _current_admin_id(app_client)
    scenario = await _seed_bound_scenario(created_by=admin_id)
    async with AsyncSessionLocal() as db:
        placeholder = Contract(
            candidate_id=scenario["candidate_id"],
            client_id=scenario["client_id"],
            job_id=scenario["job_id"],
            contract_type=ContractType.b2b,
            status=ContractStatus.draft,
            start_date=date(2026, 7, 24),
            rate_candidate=None,
            rate_client=None,
            rate_unit=RateUnit.monthly,
            currency="PLN",
        )
        db.add(placeholder)
        await db.flush()
        db.add(
            Activity(
                entity_type="contract",
                entity_id=placeholder.id,
                action="auto_drafted_from_pipeline",
                user_id=admin_id,
                details={
                    "candidate_id": scenario["candidate_id"],
                    "job_id": scenario["job_id"],
                },
            )
        )
        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert generated is not None
        generated.render_payload = {
            **(generated.render_payload or {}),
            "currency": "EUR",
        }
        await db.commit()
        await db.refresh(placeholder)
        placeholder_id = placeholder.id

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "linked_existing"
    assert response.json()["contract_id"] == placeholder_id
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        1,
        1,
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, placeholder_id)
        assert contract is not None
        assert contract.start_date == date(2026, 8, 1)
        assert contract.rate_candidate == Decimal("150.500")
        assert contract.rate_unit == RateUnit.hourly
        # The signed B2B document defines the candidate/cost currency only.
        # Legacy ``currency`` remains the client/revenue alias.
        assert contract.currency == "PLN"
        assert contract.rate_candidate_currency == "EUR"


@pytest.mark.asyncio
async def test_confirm_never_overwrites_incomplete_manual_draft_terms(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    async with AsyncSessionLocal() as db:
        manual_draft = Contract(
            candidate_id=scenario["candidate_id"],
            client_id=scenario["client_id"],
            job_id=scenario["job_id"],
            contract_type=ContractType.b2b,
            status=ContractStatus.draft,
            start_date=date(2026, 9, 1),
            rate_candidate=None,
            rate_client=None,
            rate_unit=RateUnit.monthly,
            currency="EUR",
        )
        db.add(manual_draft)
        await db.commit()
        await db.refresh(manual_draft)
        manual_draft_id = manual_draft.id

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 409, response.text
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, manual_draft_id)
        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert contract is not None
        assert contract.start_date == date(2026, 9, 1)
        assert contract.rate_candidate is None
        assert contract.rate_unit == RateUnit.monthly
        assert contract.currency == "EUR"
        assert generated is not None
        assert generated.signature_status == "unsigned"
        assert generated.contract_id is None


@pytest.mark.asyncio
async def test_confirm_rejects_multiple_live_contractors_without_partial_changes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    await _seed_existing_contract(scenario, status=ContractStatus.draft)
    await _seed_existing_contract(scenario, status=ContractStatus.ready_for_signature)

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 409, response.text
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        2,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        candidate = await db.get(Candidate, scenario["candidate_id"])
        assert generated is not None
        assert generated.signature_status == "unsigned"
        assert generated.contract_id is None
        assert candidate is not None
        assert candidate.status == CandidateStatus.active


@pytest.mark.asyncio
async def test_confirm_rejects_material_contract_conflict_without_partial_changes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    existing_id = await _seed_existing_contract(
        scenario,
        start_date=date(2026, 9, 1),
        rate_candidate=Decimal("175.000"),
        currency="EUR",
    )

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 409, response.text
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, existing_id)
        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert contract is not None
        assert contract.start_date == date(2026, 9, 1)
        assert contract.rate_candidate == Decimal("175.000")
        assert contract.currency == "EUR"
        assert generated is not None
        assert generated.signature_status == "unsigned"
        assert generated.contract_id is None


@pytest.mark.asyncio
async def test_conflict_409_names_every_difference_and_offers_keeping_terms(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """The prod shape (2026-09): Delivery entered the contractor by hand AFTER
    the document was generated — daily unit, MD-derived amount (68 PLN/h ×
    8 = 544 PLN/day) and one schedule row. Three labels, one hint."""
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    existing_id = await _seed_existing_contract(
        scenario,
        status=ContractStatus.active,
        rate_candidate=Decimal("1204.000"),
        rate_client=Decimal("1760.000"),
        rate_unit=RateUnit.daily,
        with_rate_schedule=True,
    )

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["contract_ids"] == [existing_id]
    assert detail["conflicts"] == [
        "stawka kandydata",
        "jednostka stawki",
        "harmonogram stawek",
    ]
    assert detail["can_keep_existing_terms"] is True
    assert "zachowując dotychczasowe warunki" in detail["message"]


@pytest.mark.asyncio
async def test_keep_existing_terms_links_without_touching_the_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Acknowledged conflicts link the signed document and run the order/hired
    automation, but the contract keeps EVERY populated term — including the
    non-hourly unit, which also governs the client rate and therefore margin."""
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    existing_id = await _seed_existing_contract(
        scenario,
        status=ContractStatus.active,
        rate_candidate=Decimal("1204.000"),
        rate_client=Decimal("1760.000"),
        rate_unit=RateUnit.daily,
        with_rate_schedule=True,
    )

    response = await _confirm(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        {"keep_existing_contract_terms": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "linked_existing"
    assert body["contract_id"] == existing_id
    assert body["acknowledged_conflicts"] == [
        "stawka kandydata",
        "jednostka stawki",
        "harmonogram stawek",
    ]
    assert "bez zmian" in body["message"]
    assert "jednostka stawki" in body["message"]
    assert body["generated_contract"]["signature_status"] == "signed_both"
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        1,
        1,
    )

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, existing_id)
        assert contract is not None
        assert contract.status == ContractStatus.active
        assert contract.rate_candidate == Decimal("1204.000")
        assert contract.rate_client == Decimal("1760.000")
        assert contract.rate_unit == RateUnit.daily
        assert contract.start_date == date(2026, 8, 1)
        schedule = (
            await db.execute(
                select(ContractCandidateRate).where(
                    ContractCandidateRate.contract_id == existing_id
                )
            )
        ).scalars().all()
        assert [row.rate for row in schedule] == [Decimal("1204.000")]

        # Absent values are still completed from the document: the B2B detail
        # did not exist, so it is created with the signed document's number.
        detail = await db.scalar(
            select(B2BContractDetail).where(
                B2BContractDetail.contract_id == existing_id
            )
        )
        assert detail is not None
        assert detail.project_city == "Warszawa"
        assert detail.contract_number == scenario["contract_number"]

        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert generated is not None
        assert generated.contract_id == existing_id
        assert generated.signature_source == "manual_confirmation"

        order = await db.scalar(
            select(ClientOrder).where(ClientOrder.contract_id == existing_id)
        )
        assert order is not None
        # The auto-drafted order inherits the contract as it IS, not the
        # document's hourly reading.
        assert order.rate_unit == RateUnit.daily

        audit = (
            await db.execute(
                select(Activity).where(
                    Activity.entity_type == "b2b_generated_contract",
                    Activity.entity_id == scenario["generated_id"],
                    Activity.action == "fully_signed_confirmed",
                )
            )
        ).scalars().all()
        assert len(audit) == 1
        assert audit[0].details["acknowledged_conflicts"] == [
            "stawka kandydata",
            "jednostka stawki",
            "harmonogram stawek",
        ]
        link_audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == existing_id,
                Activity.action == "linked_to_generated_contract",
            )
        )
        assert link_audit is not None
        assert link_audit.details["existing_terms_kept"] is True


@pytest.mark.asyncio
async def test_keep_existing_terms_completes_empty_fields_but_never_reinterprets(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Empty fields are still filled from the document (start date), but a
    populated daily unit stays, and the document's HOURLY rate is not written
    next to it — that number would be read in the wrong unit."""
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=scenario["candidate_id"],
            client_id=scenario["client_id"],
            job_id=scenario["job_id"],
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=None,
            rate_candidate=None,
            rate_client=Decimal("1760.000"),
            rate_unit=RateUnit.daily,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        existing_id = contract.id

    response = await _confirm(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        {"keep_existing_contract_terms": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["acknowledged_conflicts"] == ["jednostka stawki"]
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, existing_id)
        assert contract is not None
        assert contract.start_date == date(2026, 8, 1)
        assert contract.rate_unit == RateUnit.daily
        assert contract.rate_candidate is None
        assert contract.rate_client == Decimal("1760.000")
        schedule_rows = await db.scalar(
            select(func.count(ContractCandidateRate.id)).where(
                ContractCandidateRate.contract_id == existing_id
            )
        )
        assert schedule_rows == 0
        order = await db.scalar(
            select(ClientOrder).where(ClientOrder.contract_id == existing_id)
        )
        assert order is not None
        assert order.start_date == date(2026, 8, 1)


@pytest.mark.asyncio
async def test_keep_existing_terms_stamps_the_signed_number_but_keeps_detail_terms(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """A detail left by an earlier document keeps its populated terms (city is
    a listed conflict) but takes the number of the document actually signed —
    the number is identity, not a term, and is never listed as a conflict."""
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    existing_id = await _seed_existing_contract(
        scenario,
        status=ContractStatus.ready_for_signature,
        start_date=date(2026, 8, 1),
        rate_candidate=Decimal("150.500"),
    )
    async with AsyncSessionLocal() as db:
        db.add(
            B2BContractDetail(
                contract_id=existing_id,
                contract_number="OLD/2099",
                project_city="Kraków",
                language="pl",
            )
        )
        await db.commit()

    response = await _confirm(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        {"keep_existing_contract_terms": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["acknowledged_conflicts"] == ["miasto realizacji"]
    async with AsyncSessionLocal() as db:
        detail = await db.scalar(
            select(B2BContractDetail).where(
                B2BContractDetail.contract_id == existing_id
            )
        )
        assert detail is not None
        assert detail.contract_number == scenario["contract_number"]
        assert detail.project_city == "Kraków"
        # Empty detail fields are still completed from the document.
        assert detail.signing_date == date(2026, 7, 24)
        assert detail.project_description == "Rozwój systemu bankowego."


@pytest.mark.asyncio
async def test_keep_existing_terms_message_survives_the_cost_client_suffix(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    """At a cost client (no auto order) the message must still say the terms
    were kept — the order suffix is appended, not substituted."""
    import app.services.b2b_contract_automation as automation

    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    await _seed_existing_contract(
        scenario,
        status=ContractStatus.active,
        rate_candidate=Decimal("1204.000"),
        rate_client=Decimal("1760.000"),
        rate_unit=RateUnit.daily,
        with_rate_schedule=True,
    )
    monkeypatch.setattr(
        automation,
        "skips_standard_order_automation",
        lambda client_id: client_id == scenario["client_id"],
    )

    response = await _confirm(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        {"keep_existing_contract_terms": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_id"] is None
    assert body["acknowledged_conflicts"] == [
        "stawka kandydata",
        "jednostka stawki",
        "harmonogram stawek",
    ]
    assert "dotychczasowe warunki zostały bez zmian" in body["message"]
    assert "Zamówienia nie utworzono automatycznie" in body["message"]


@pytest.mark.asyncio
async def test_keep_existing_terms_is_a_no_op_without_conflicts(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Without differences the flag changes nothing: absent terms are filled
    from the document exactly as on the default path."""
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    existing_id = await _seed_existing_contract(
        scenario,
        status=ContractStatus.ready_for_signature,
        start_date=date(2026, 8, 1),
        rate_candidate=Decimal("150.500"),
    )

    response = await _confirm(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        {"keep_existing_contract_terms": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["acknowledged_conflicts"] == []
    async with AsyncSessionLocal() as db:
        detail = await db.scalar(
            select(B2BContractDetail).where(
                B2BContractDetail.contract_id == existing_id
            )
        )
        assert detail is not None
        assert detail.contract_number == scenario["contract_number"]
        assert detail.signing_date == date(2026, 7, 24)
        link_audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == existing_id,
                Activity.action == "linked_to_generated_contract",
            )
        )
        assert link_audit is not None
        assert link_audit.details["existing_terms_kept"] is False


@pytest.mark.asyncio
async def test_keep_existing_terms_never_bypasses_identity_guards(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Two live contractors is not a term conflict — the flag must not turn
    that 409 into a silent link to either of them."""
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    await _seed_existing_contract(scenario, status=ContractStatus.draft)
    await _seed_existing_contract(scenario, status=ContractStatus.ready_for_signature)

    response = await _confirm(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        {"keep_existing_contract_terms": True},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "can_keep_existing_terms" not in detail
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        2,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert generated is not None
        assert generated.signature_status == "unsigned"
        assert generated.contract_id is None


@pytest.mark.asyncio
async def test_confirm_rejects_material_b2b_detail_conflict_without_changes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    existing_id = await _seed_existing_contract(scenario)
    async with AsyncSessionLocal() as db:
        db.add(
            B2BContractDetail(
                contract_id=existing_id,
                signing_date=date(2026, 7, 24),
                project_city="Kraków",
                project_description="Rozwój systemu bankowego.",
                correspondence_address="ul. Testowa 1, Warszawa",
                rate_in_words="sto pięćdziesiąt złotych pięćdziesiąt groszy",
                language="pl",
            )
        )
        await db.commit()

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 409, response.text
    assert "miasto realizacji" in response.json()["detail"]["message"]
    assert response.json()["detail"]["contract_ids"] == [existing_id]
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        detail = await db.scalar(
            select(B2BContractDetail).where(
                B2BContractDetail.contract_id == existing_id
            )
        )
        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert detail is not None
        assert detail.project_city == "Kraków"
        assert generated is not None
        assert generated.signature_status == "unsigned"
        assert generated.contract_id is None


@pytest.mark.asyncio
async def test_confirm_rejects_multiple_open_orders_without_partial_changes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    admin_id = await _current_admin_id(app_client)
    scenario = await _seed_bound_scenario(created_by=admin_id)
    existing_id = await _seed_existing_contract(scenario)
    async with AsyncSessionLocal() as db:
        orders = [
            ClientOrder(
                client_id=scenario["client_id"],
                contract_id=existing_id,
                job_id=scenario["job_id"],
                title=f"Existing order {index}",
                status=ClientOrderStatus.draft,
                created_by_user_id=admin_id,
            )
            for index in (1, 2)
        ]
        db.add_all(orders)
        await db.commit()
        order_ids = [order.id for order in orders]

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["contract_ids"] == [existing_id]
    assert set(response.json()["detail"]["order_ids"]) == set(order_ids)
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        2,
        0,
    )
    async with AsyncSessionLocal() as db:
        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert generated is not None
        assert generated.signature_status == "unsigned"
        assert generated.contract_id is None


@pytest.mark.asyncio
async def test_confirm_requires_complete_legacy_binding(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    generated_id = await _seed_legacy_generated(
        created_by=await _current_admin_id(app_client)
    )

    missing_pair = await _confirm(
        app_client, app_auth_headers, generated_id, payload={}
    )
    one_sided = await _confirm(
        app_client,
        app_auth_headers,
        generated_id,
        payload={"candidate_id": 1},
    )

    assert missing_pair.status_code == 422, missing_pair.text
    assert one_sided.status_code == 422, one_sided.text
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, generated_id)
        assert row is not None
        assert row.signature_status == "unsigned"
        assert row.contract_id is None


@pytest.mark.asyncio
async def test_confirm_persists_one_time_legacy_binding(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    admin_id = await _current_admin_id(app_client)
    scenario = await _seed_bound_scenario(created_by=admin_id)
    legacy_id = await _seed_legacy_generated(created_by=admin_id)

    response = await _confirm(
        app_client,
        app_auth_headers,
        legacy_id,
        payload={
            "candidate_id": scenario["candidate_id"],
            "job_id": scenario["job_id"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "created"
    assert body["candidate_id"] == scenario["candidate_id"]
    assert body["job_id"] == scenario["job_id"]
    assert body["client_id"] == scenario["client_id"]
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, legacy_id)
        assert row is not None
        assert row.candidate_id == scenario["candidate_id"]
        assert row.job_id == scenario["job_id"]
        assert row.client_id == scenario["client_id"]
        assert row.contract_id == body["contract_id"]
        assert row.signature_status == "signed_both"


@pytest.mark.asyncio
async def test_confirm_rejects_candidate_job_without_recruitment_and_rolls_back(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        unrelated = Candidate(
            name="Unrelated",
            lastname=f"Candidate-{unique}",
            email=f"unrelated-signature-{unique}@example.com",
        )
        db.add(unrelated)
        await db.flush()
        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert generated is not None
        generated.candidate_id = unrelated.id
        unrelated_id = unrelated.id
        await db.commit()

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 409, response.text
    assert await _counts_for_pair(unrelated_id, scenario["job_id"]) == (0, 0, 0)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None
        assert row.signature_status == "unsigned"
        assert row.contract_id is None


@pytest.mark.asyncio
async def test_confirm_rbac_allows_admin_and_fails_closed_without_client_scope(
    app_client: AsyncClient,
):
    generated_id = await _seed_legacy_generated()

    admin_headers = await _headers_for_role(app_client, UserRole.admin)
    admin_response = await _confirm(app_client, admin_headers, generated_id)
    # 422 proves authentication/authorization passed and business validation ran.
    assert admin_response.status_code == 422, admin_response.text

    for role in (
        UserRole.delivery_lead,
        UserRole.tac,
        UserRole.head_of_recruitment,
        UserRole.recruiter,
        UserRole.sourcer,
        UserRole.user,
    ):
        headers = await _headers_for_role(app_client, role)
        response = await _confirm(app_client, headers, generated_id)
        assert response.status_code == 403, (
            f"{role.value} unexpectedly confirmed a legal status: {response.text}"
        )


@pytest.mark.asyncio
async def test_delivery_lead_scope_allows_confirmation_but_tac_stays_outside_delivery(
    app_client: AsyncClient,
):
    admin_id = await _current_admin_id(app_client)

    for role, assignment_field in (
        (UserRole.delivery_lead, "delivery_lead_id"),
        (UserRole.tac, "tac_id"),
    ):
        scenario = await _seed_bound_scenario(created_by=admin_id)
        headers = await _headers_for_role(app_client, role)
        user_id = int(headers["X-Test-User-Id"])

        denied = await _confirm(app_client, headers, scenario["generated_id"])
        assert denied.status_code == 403, (
            f"out-of-scope {role.value} got {denied.status_code}: {denied.text}"
        )
        assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
            0,
            0,
            0,
        )

        async with AsyncSessionLocal() as db:
            job = await db.get(Job, scenario["job_id"])
            generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
            assert job is not None
            assert generated is not None
            assert generated.signature_status == "unsigned"
            setattr(job, assignment_field, user_id)
            await db.commit()

        job_only = await _confirm(app_client, headers, scenario["generated_id"])
        assert job_only.status_code == 403, (
            f"{role.value} without explicit client assignment got "
            f"{job_only.status_code}: {job_only.text}"
        )

        async with AsyncSessionLocal() as db:
            if role is UserRole.delivery_lead:
                db.add(
                    DeliveryLeadClientAssignment(
                        delivery_lead_user_id=user_id,
                        client_id=scenario["client_id"],
                    )
                )
            else:
                db.add(
                    ClientTacAssignment(
                        tac_user_id=user_id,
                        client_id=scenario["client_id"],
                    )
                )
            await db.commit()

        allowed = await _confirm(app_client, headers, scenario["generated_id"])
        if role is UserRole.tac:
            assert allowed.status_code == 403, (
                "TAC must remain outside Delivery even with legacy job/client "
                f"assignments: {allowed.text}"
            )
            assert await _counts_for_pair(
                scenario["candidate_id"], scenario["job_id"]
            ) == (0, 0, 0)
            continue

        assert allowed.status_code == 200, (
            f"assigned {role.value} got {allowed.status_code}: {allowed.text}"
        )
        assert allowed.json()["outcome"] == "created"
        assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
            1,
            1,
            1,
        )


@pytest.mark.asyncio
async def test_exception_after_flush_rolls_back_entire_confirmation(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    import app.services.b2b_contract_automation as automation

    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )

    async def fail_after_contract_and_order(*args, **kwargs):
        raise RuntimeError("forced failure after flush")

    monkeypatch.setattr(
        automation, "_ensure_hired_stage", fail_after_contract_and_order
    )

    try:
        response = await _confirm(
            app_client, app_auth_headers, scenario["generated_id"]
        )
    except RuntimeError as exc:
        assert str(exc) == "forced failure after flush"
    else:
        assert response.status_code == 500, response.text

    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        0,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        generated = await db.get(B2BGeneratedContract, scenario["generated_id"])
        candidate = await db.get(Candidate, scenario["candidate_id"])
        assert generated is not None
        assert generated.signature_status == "unsigned"
        assert generated.signature_source is None
        assert generated.contract_id is None
        assert generated.signed_at is None
        assert candidate is not None
        assert candidate.status == CandidateStatus.active


@pytest.mark.asyncio
async def test_generate_retry_with_contract_id_does_not_create_another_contractor(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    role_id = await _seed_generator_dependencies()
    payload = {
        "candidate_id": scenario["candidate_id"],
        "job_id": scenario["job_id"],
        "role_id": role_id,
        "language": "pl",
        "contract_number": scenario["contract_number"],
        "signing_date": "2026-07-24",
        "start_date": "2026-08-01",
        "project_city": "Warszawa",
        "project_description": "Rozwój systemu bankowego.",
        "correspondence_address": "ul. Testowa 1, Warszawa",
        "rate_candidate": 150.5,
        "currency": "PLN",
    }

    first = await app_client.post(
        "/api/b2b-generator/generate",
        json=payload,
        headers=app_auth_headers,
    )
    assert first.status_code == 200, first.text
    contract_id = first.json()["contract_id"]

    second = await app_client.post(
        "/api/b2b-generator/generate",
        json={**payload, "contract_id": contract_id},
        headers=app_auth_headers,
    )

    assert second.status_code == 200, second.text
    assert first.json()["contract_id"] == contract_id
    assert second.json()["contract_id"] == contract_id
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        signature_count = await db.scalar(
            select(func.count(DocumentSignature.id)).where(
                DocumentSignature.contract_id == contract_id
            )
        )
        assert signature_count == 0


@pytest.mark.asyncio
async def test_generate_cannot_mutate_contract_linked_to_signed_generated_row(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    confirmed = await _confirm(app_client, app_auth_headers, scenario["generated_id"])
    assert confirmed.status_code == 200, confirmed.text
    contract_id = confirmed.json()["contract_id"]
    role_id = await _seed_generator_dependencies()

    response = await app_client.post(
        "/api/b2b-generator/generate",
        json={
            "contract_id": contract_id,
            "role_id": role_id,
            "language": "pl",
            "contract_number": "9999/2099",
            "signing_date": "2026-07-25",
            "start_date": "2026-09-01",
            "rate_candidate": 999,
            "currency": "EUR",
        },
        headers=app_auth_headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["contract_ids"] == [contract_id]
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        detail = await db.scalar(
            select(B2BContractDetail).where(
                B2BContractDetail.contract_id == contract_id
            )
        )
        assert contract is not None
        assert detail is not None
        assert contract.start_date == date(2026, 8, 1)
        assert contract.rate_candidate == Decimal("150.500")
        assert contract.currency == "PLN"
        assert detail.contract_number == scenario["contract_number"]
        assert detail.signing_date == date(2026, 7, 24)


@pytest.mark.asyncio
async def test_generate_without_id_reuses_and_updates_only_the_existing_draft(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    import app.api.b2b_contract_generator as generator_api

    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    existing_id = await _seed_existing_contract(
        scenario,
        start_date=date(2026, 9, 1),
        rate_candidate=Decimal("175.000"),
        currency="EUR",
    )
    role_id = await _seed_generator_dependencies()

    def render_with_loaded_detail(_template, contract):
        assert contract.b2b_detail is not None
        assert contract.b2b_detail.contract_number == scenario["contract_number"]
        assert contract.b2b_detail.b2b_role_id == role_id
        return "<p>loaded B2B detail</p>"

    monkeypatch.setattr(generator_api, "_render_draft_body", render_with_loaded_detail)

    response = await app_client.post(
        "/api/b2b-generator/generate",
        json={
            "candidate_id": scenario["candidate_id"],
            "job_id": scenario["job_id"],
            "role_id": role_id,
            "language": "pl",
            "contract_number": scenario["contract_number"],
            "signing_date": "2026-07-24",
            "start_date": "2026-08-01",
            "rate_candidate": 150.5,
            "currency": "PLN",
        },
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["contract_id"] == existing_id
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, existing_id)
        assert contract is not None
        assert contract.status == ContractStatus.draft
        assert contract.start_date == date(2026, 8, 1)
        assert contract.rate_candidate == Decimal("150.500")
        assert contract.currency == "EUR"
        assert contract.rate_candidate_currency == "PLN"
        assert contract.draft_content_html == "<p>loaded B2B detail</p>"


@pytest.mark.asyncio
async def test_generate_without_id_never_mutates_or_duplicates_a_finalized_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    existing_id = await _seed_existing_contract(
        scenario,
        status=ContractStatus.ready_for_signature,
    )
    role_id = await _seed_generator_dependencies()

    response = await app_client.post(
        "/api/b2b-generator/generate",
        json={
            "candidate_id": scenario["candidate_id"],
            "job_id": scenario["job_id"],
            "role_id": role_id,
            "language": "pl",
            "contract_number": scenario["contract_number"],
            "signing_date": "2026-07-24",
            "start_date": "2026-09-01",
            "rate_candidate": 175,
            "currency": "EUR",
        },
        headers=app_auth_headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["contract_ids"] == [existing_id]
    assert await _counts_for_pair(scenario["candidate_id"], scenario["job_id"]) == (
        1,
        0,
        0,
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, existing_id)
        assert contract is not None
        assert contract.status == ContractStatus.ready_for_signature
        assert contract.start_date == date(2026, 8, 1)
        assert contract.rate_candidate == Decimal("150.500")
        assert contract.currency == "PLN"


@pytest.mark.asyncio
async def test_signed_generated_row_cannot_be_edited_or_deleted(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    confirmed = await _confirm(app_client, app_auth_headers, scenario["generated_id"])
    assert confirmed.status_code == 200, confirmed.text

    patched = await app_client.patch(
        f"/api/b2b-generator/generated/{scenario['generated_id']}",
        json={"client_name": "Changed after signature"},
        headers=app_auth_headers,
    )
    deleted = await app_client.delete(
        f"/api/b2b-generator/generated/{scenario['generated_id']}",
        headers=app_auth_headers,
    )
    contract_deleted = await app_client.delete(
        f"/api/contracts/{confirmed.json()['contract_id']}",
        headers=app_auth_headers,
    )

    assert patched.status_code == 409, patched.text
    assert deleted.status_code == 409, deleted.text
    assert contract_deleted.status_code == 409, contract_deleted.text
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        assert row is not None
        assert row.signature_status == "signed_both"
        assert row.client_name == scenario["client_name"]


# ── Status handlowy: promocja in_progress → active (migracja 0224) ────────────


async def _set_generated_status(generated_id: int, **values: Any) -> None:
    """Ustaw status handlowy wprost w bazie.

    Helper `_seed_bound_scenario` zostawia default kolumny (`active`), a testy
    niżej potrzebują wiersza w stanie, do którego prowadzi dopiero `/render`.
    """
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, generated_id)
        assert row is not None
        for key, value in values.items():
            setattr(row, key, value)
        await db.commit()


async def test_confirming_signature_promotes_in_progress_to_active(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Potwierdzenie podpisu jest JEDYNYM przejściem `in_progress` → `active`.

    Bez tego testu warunek promocji mógłby zniknąć albo się odwrócić przy
    zielonym CI: pozostałe testy tego pliku seedują wiersze przez ORM z defaultem
    `active`, więc żaden nie przechodzi przez ten stan.
    """
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    await _set_generated_status(scenario["generated_id"], contract_status="in_progress")

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])
    assert response.status_code == 200, response.text

    generated = response.json()["generated_contract"]
    assert generated["contract_status"] == "active", (
        "podpis obustronny musi wypromować umowę z in_progress na active"
    )
    assert generated["signature_status"] == "signed_both"


async def test_confirming_signature_does_not_reopen_a_closed_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Promocja jest WARUNKOWA i to jest jej sens.

    Umowę wolno zamknąć powodem `resignation_before_signing` PRZED podpisem.
    Bezwarunkowe `contract_status = "active"` zostawiłoby wtedy wypełnione pola
    `closure_*` przy statusie `active`, co łamie
    `ck_b2b_generated_contracts_closure_coherence` → IntegrityError w środku
    atomowej automatyzacji zatrudnienia. Test na samo przejście
    `in_progress → active` przeszedłby również dla wersji bezwarunkowej.
    """
    scenario = await _seed_bound_scenario(
        created_by=await _current_admin_id(app_client)
    )
    await _set_generated_status(
        scenario["generated_id"],
        contract_status="closed",
        closure_reason="resignation_before_signing",
        closure_date=date(2026, 8, 15),
    )

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])
    assert response.status_code == 200, response.text

    generated = response.json()["generated_contract"]
    assert generated["contract_status"] == "closed", (
        "zamknięta umowa nie może zostać cicho otwarta przez potwierdzenie podpisu"
    )
    assert generated["closure_reason"] == "resignation_before_signing"
    # Sam podpis został odnotowany — blokujemy tylko zmianę statusu handlowego.
    assert generated["signature_status"] == "signed_both"
