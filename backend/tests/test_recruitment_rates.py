"""Stawki z rekrutacji dla zamówienia i umowy (D7, 08.10.2026) — z bazą.

Źródło (``services/recruitment_rates``): para wprost, kontrakt z rekrutacją
i bez niej, rodzina scalonych klientów; lista kontraktorów z redakcją kwot
i stawki do klienta; podpowiedź dla formularza nowego kontraktora; prefill
Generatora B2B. Baza wspólna i nieczyszczona — asercje tylko na własnych
wierszach (nazwy z UUID).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio


async def _seed() -> dict:
    """Klient z duplikatem scalonym w niego, osoba z dwiema rekrutacjami, kontrakt."""
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    unique = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Stawki z rekrutacji {unique}")
        db.add(client)
        await db.flush()
        duplicate = Client(
            name=f"Stawki z rekrutacji dup {unique}",
            merged_into_client_id=client.id,
            hidden=True,
        )
        candidate = Candidate(
            name="Ola", lastname=f"Stawka{unique}", email=f"rr-{unique}@example.com"
        )
        db.add_all([duplicate, candidate])
        await db.flush()
        old_job = Job(
            title=f"Stara rekrutacja {unique}",
            status=JobStatus.published,
            client_id=duplicate.id,
        )
        job = Job(
            title=f"Java Developer {unique}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add_all([old_job, job])
        await db.flush()
        db.add_all(
            [
                # Starsza rekrutacja u scalonego duplikatu.
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=old_job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=now - timedelta(days=60),
                    client_rate_value=Decimal("150"),
                    client_rate_unit=RateUnit.hourly,
                    client_rate_currency="PLN",
                ),
                # Rekrutacja bieżąca: najpierw stawka kandydata, potem DL
                # wysyła ze stawką do klienta, potem kandydat podnosi stawkę.
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=now - timedelta(days=5),
                    expected_rate_value=Decimal("130"),
                    expected_rate_unit=RateUnit.hourly,
                    expected_rate_currency="PLN",
                ),
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=now - timedelta(days=3),
                    client_rate_value=Decimal("165"),
                    client_rate_unit=RateUnit.hourly,
                    client_rate_currency="PLN",
                ),
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=now - timedelta(days=1),
                    expected_rate_value=Decimal("140"),
                    expected_rate_unit=RateUnit.hourly,
                    expected_rate_currency="PLN",
                ),
            ]
        )
        with_job = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            job_id=job.id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=10),
            rate_candidate=Decimal("140"),
            rate_client=Decimal("165"),
        )
        db.add(with_job)
        await db.commit()
        return {
            "client_id": client.id,
            "duplicate_id": duplicate.id,
            "candidate_id": candidate.id,
            "job_id": job.id,
            "old_job_id": old_job.id,
            "contract_id": with_job.id,
            "job_title": job.title,
        }


async def test_for_pairs_takes_the_newest_value_of_each_rate():
    from app.services import recruitment_rates

    world = await _seed()
    async with AsyncSessionLocal() as db:
        found = await recruitment_rates.for_pairs(
            db, [(world["candidate_id"], world["job_id"])]
        )
    rate = found[(world["candidate_id"], world["job_id"])]
    assert rate.client_rate_value == Decimal("165")
    assert rate.client_rate_unit == "hourly"
    assert rate.candidate_rate_value == Decimal("140")
    assert rate.job_title == world["job_title"]
    assert rate.client_ref().value == Decimal("165")


async def test_for_client_reads_the_merged_family_and_picks_the_newest_pair():
    from app.services import recruitment_rates

    world = await _seed()
    async with AsyncSessionLocal() as db:
        family = await recruitment_rates.client_family_ids(db, world["duplicate_id"])
        assert {world["client_id"], world["duplicate_id"]} <= family
        found = await recruitment_rates.for_client(
            db, world["client_id"], [world["candidate_id"]]
        )
    assert found[world["candidate_id"]].job_id == world["job_id"]


async def test_for_contracts_falls_back_to_the_client_when_the_contract_has_no_job():
    from app.models.contract import Contract, ContractStatus
    from app.services import recruitment_rates

    world = await _seed()
    async with AsyncSessionLocal() as db:
        bare = Contract(
            candidate_id=world["candidate_id"],
            client_id=world["client_id"],
            job_id=None,
            status=ContractStatus.draft,
        )
        db.add(bare)
        await db.flush()
        bare_id = bare.id
        found = await recruitment_rates.for_contracts(
            db,
            [
                recruitment_rates.ContractKey(
                    contract_id=bare_id,
                    candidate_id=world["candidate_id"],
                    job_id=None,
                    client_id=world["client_id"],
                ),
                recruitment_rates.ContractKey(
                    contract_id=world["contract_id"],
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    client_id=world["client_id"],
                ),
            ],
        )
        await db.rollback()
    assert found[bare_id].job_id == world["job_id"]
    assert found[world["contract_id"]].client_rate_value == Decimal("165")


async def test_contractor_listing_carries_rates_and_redacts_them(
    app_client: AsyncClient, app_auth_headers: dict
):
    from tests._permission_grants import grant_permissions
    from tests.test_permissions_orders import _login_as

    world = await _seed()
    url = f"/api/clients/{world['client_id']}/orders"

    admin = await app_client.get(url, headers=app_auth_headers)
    assert admin.status_code == 200, admin.text
    row = next(
        c
        for c in admin.json()["contractors"]
        if c["contract_id"] == world["contract_id"]
    )
    rates = row["recruitment_rates"]
    assert Decimal(rates["client_rate_value"]) == Decimal("165")
    assert Decimal(rates["candidate_rate_value"]) == Decimal("140")
    assert rates["client_rate_redacted"] is False

    # Podgląd bez kwot: stawki z rekrutacji znikają razem z resztą kwot.
    viewer_id, viewer = await _login_as(app_client, UserRole.recruiter)
    await grant_permissions(viewer_id, "delivery_view")
    listing = await app_client.get(url, headers=viewer)
    assert listing.status_code == 200, listing.text
    row = next(
        c
        for c in listing.json()["contractors"]
        if c["contract_id"] == world["contract_id"]
    )
    assert row["recruitment_rates"] is None

    # Kwoty tak, stawka do klienta nie — rekruter jej nie widzi.
    amounts_id, amounts = await _login_as(app_client, UserRole.recruiter)
    await grant_permissions(amounts_id, "delivery_view", "amounts_view")
    listing = await app_client.get(url, headers=amounts)
    assert listing.status_code == 200, listing.text
    row = next(
        c
        for c in listing.json()["contractors"]
        if c["contract_id"] == world["contract_id"]
    )
    assert row["recruitment_rates"]["client_rate_value"] is None
    assert row["recruitment_rates"]["client_rate_redacted"] is True
    assert Decimal(row["recruitment_rates"]["candidate_rate_value"]) == Decimal("140")


async def test_lookup_for_the_new_contractor_form(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed()
    url = f"/api/clients/{world['client_id']}/recruitment-rates"

    by_job = await app_client.get(
        url,
        headers=app_auth_headers,
        params={"candidate_id": world["candidate_id"], "job_id": world["job_id"]},
    )
    assert by_job.status_code == 200, by_job.text
    assert Decimal(by_job.json()["rate"]["client_rate_value"]) == Decimal("165")

    by_client = await app_client.get(
        url, headers=app_auth_headers, params={"candidate_id": world["candidate_id"]}
    )
    assert by_client.status_code == 200, by_client.text
    assert by_client.json()["rate"]["job_id"] == world["job_id"]

    # Rekrutacja innego klienta nie jest punktem odniesienia.
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        other = Client(name=f"Obcy klient {uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.flush()
        foreign = Job(title="Obca", status=JobStatus.published, client_id=other.id)
        db.add(foreign)
        await db.commit()
        foreign_id = foreign.id
    stranger = await app_client.get(
        url,
        headers=app_auth_headers,
        params={"candidate_id": world["candidate_id"], "job_id": foreign_id},
    )
    assert stranger.status_code == 200, stranger.text
    assert stranger.json()["rate"] is None


async def test_generator_prefill_carries_the_recruitment_candidate_rate(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed()
    response = await app_client.get(
        "/api/b2b-generator/prefill",
        headers=app_auth_headers,
        params={"candidate_id": world["candidate_id"], "job_id": world["job_id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recruitment_rate"]["value"] == 140.0
    assert body["recruitment_rate"]["unit"] == "hourly"
    assert body["recruitment_rate"]["job_title"] == world["job_title"]


async def test_generator_prefill_without_a_stage_rate_has_no_recruitment_rate(
    app_client: AsyncClient, app_auth_headers: dict
):
    """„Stawka od” nie jest stawką z rekrutacji — pole zostaje puste."""
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bez stawek {unique}")
        candidate = Candidate(
            name="Iza",
            lastname=f"Bez{unique}",
            email=f"bez-{unique}@example.com",
            expected_rate_hourly=Decimal("120"),
        )
        db.add_all([client, candidate])
        await db.flush()
        job = Job(title="Bez stawek", status=JobStatus.published, client_id=client.id)
        db.add(job)
        await db.flush()
        # Generator wymaga, żeby osoba była w rekrutacji — etap bez żadnej stawki.
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.screening,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        ids = {"candidate_id": candidate.id, "job_id": job.id}
    response = await app_client.get(
        "/api/b2b-generator/prefill", headers=app_auth_headers, params=ids
    )
    assert response.status_code == 200, response.text
    assert response.json()["recruitment_rate"] is None
