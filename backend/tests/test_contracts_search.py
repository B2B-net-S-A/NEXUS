"""Free-text search (`?q=`) tests for /api/contracts.

Regression: the list endpoint silently ignored the `q` param the frontend
sends, so the "Szukaj po kandydacie, kliencie, pozycji…" box never filtered.
These tests pin the search across candidate name/lastname, client name and job
title — including case-insensitive + Polish-diacritic matching ("grądzki" must
find "Grądzki").
"""

from __future__ import annotations

import unicodedata
import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient


async def _seed_searchable_contract(
    *, lastname: str, client_name: str, job_title: str
) -> tuple[int, int, int, int]:
    """Seed candidate + client + job + contract with the given searchable text.

    Returns (contract_id, candidate_id, client_id, job_id).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Krzysztof",
            lastname=lastname,
            email=f"csearch-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=client_name)
        db.add_all([cand, client])
        await db.flush()

        job = Job(title=job_title, client_id=client.id)
        db.add(job)
        await db.flush()

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            job_id=job.id,
            status=ContractStatus.active,
            contract_type=ContractType.b2b,
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() + timedelta(days=60),
            rate_client=10000,
            rate_candidate=8000,
            margin=2000,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id, cand.id, client.id, job.id


async def _cleanup(rows: list[tuple[int, int, int, int]]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract
    from app.models.job import Job
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for contract_id, cand_id, client_id, job_id in rows:
            await db.execute(delete(Contract).where(Contract.id == contract_id))
            await db.execute(delete(Job).where(Job.id == job_id))
            await db.execute(delete(Candidate).where(Candidate.id == cand_id))
            await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


@pytest.mark.asyncio
async def test_search_by_surname_is_case_and_diacritic_insensitive(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The reported bug: typing 'grądzki' must surface candidate 'Grądzki'."""
    token = uuid.uuid4().hex[:6]
    surname = f"Grądzki{token}"  # stored capitalised, with Polish 'ą'
    row = await _seed_searchable_contract(
        lastname=surname,
        client_name=f"Nordea-{token}",
        job_title=f"Senior Engineer {token}",
    )
    try:
        # Lowercase query with the diacritic preserved — ILIKE folds the case.
        r = await app_client.get(
            f"/api/contracts?q=grądzki{token}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        ids = {item["id"] for item in body["items"]}
        assert row[0] in ids
        assert body["total"] == 1

        # NFD form of the same query (decomposed 'ą' = 'a' + combining ogonek)
        # must also match the NFC-stored name — the server normalises to NFC.
        nfd_query = unicodedata.normalize("NFD", f"grądzki{token}")
        assert nfd_query != f"grądzki{token}"  # sanity: forms really differ
        r_nfd = await app_client.get(
            "/api/contracts",
            params={"q": nfd_query, "page_size": 100},
            headers=app_auth_headers,
        )
        assert r_nfd.status_code == 200, r_nfd.text
        assert row[0] in {item["id"] for item in r_nfd.json()["items"]}
    finally:
        await _cleanup([row])


@pytest.mark.asyncio
async def test_search_matches_full_name_client_and_job_title(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = uuid.uuid4().hex[:6]
    row = await _seed_searchable_contract(
        lastname=f"Kowalski{token}",
        client_name=f"AcmeBank{token}",
        job_title=f"Python Developer {token}",
    )
    try:
        # Full name "Krzysztof Kowalski<token>" via the concat clause.
        r_name = await app_client.get(
            f"/api/contracts?q=Krzysztof+Kowalski{token}&page_size=100",
            headers=app_auth_headers,
        )
        assert r_name.status_code == 200, r_name.text
        assert row[0] in {i["id"] for i in r_name.json()["items"]}

        # Client name substring.
        r_client = await app_client.get(
            f"/api/contracts?q=acmebank{token}&page_size=100",
            headers=app_auth_headers,
        )
        assert r_client.status_code == 200, r_client.text
        assert row[0] in {i["id"] for i in r_client.json()["items"]}

        # Job title substring.
        r_job = await app_client.get(
            f"/api/contracts?q=python+developer+{token}&page_size=100",
            headers=app_auth_headers,
        )
        assert r_job.status_code == 200, r_job.text
        assert row[0] in {i["id"] for i in r_job.json()["items"]}
    finally:
        await _cleanup([row])


@pytest.mark.asyncio
async def test_search_excludes_non_matching_and_blank_is_noop(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = uuid.uuid4().hex[:6]
    row = await _seed_searchable_contract(
        lastname=f"Nowak{token}",
        client_name=f"ClientX{token}",
        job_title=f"Analyst {token}",
    )
    try:
        # A query that matches nothing must exclude the seeded contract.
        r_none = await app_client.get(
            f"/api/contracts?q=zzz-no-such-token-{token}&page_size=100",
            headers=app_auth_headers,
        )
        assert r_none.status_code == 200, r_none.text
        assert r_none.json()["total"] == 0

        # Blank/whitespace `q` is a no-op (does not filter everything out).
        # Asserted on `total`, not on page 1's ids: the seeded row is only
        # *visible* in an unfiltered listing while the table holds fewer than
        # `page_size` contracts, so the old membership check turned red as soon
        # as siblings populated it. Comparing blank-q against no-q states the
        # actual invariant — the two are the same query — at any table size.
        r_blank = await app_client.get(
            "/api/contracts?q=%20%20&page_size=100",
            headers=app_auth_headers,
        )
        assert r_blank.status_code == 200, r_blank.text
        r_noq = await app_client.get(
            "/api/contracts?page_size=100",
            headers=app_auth_headers,
        )
        assert r_noq.status_code == 200, r_noq.text
        assert r_blank.json()["total"] == r_noq.json()["total"]
        assert r_blank.json()["total"] >= 1  # our seeded row is in there
    finally:
        await _cleanup([row])
