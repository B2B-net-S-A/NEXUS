"""Korekta stawki kandydata (PATCH …/expected-rate) nie ma bramki budżetowej.

Historia: M4-P0.4 dołożył tu lustro bramki „Oczekuje" z `/move`, bo recruiter
mógł przesunąć kandydata w budżecie (→ `active`), a potem PATCH-em wpisać
stawkę ponad budżet — omijając akceptację. Decyzja Artura 17.09.2026 zdjęła
bramkę z OBU ścieżek, a 18.09.2026 jej kod został skasowany.

Kontrakt dzisiaj: korekta stawki NIGDY nie ustawia `pending`, sama aktywuje
wiersz historyczny `pending` i zostawia snapshot `budget_max_at_move` dla
audytu. „Ponad budżet" jest odznaką na karcie, nie stanem procesu.

Behawioralne na prawdziwym Postgresie (CI odpala najpierw migracje).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.api.candidates import set_recruitment_expected_rate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.user import User, UserRole
from app.schemas.contract import RateUnit
from app.schemas.pipeline import ClientRateUpdate


async def _seed_verified(db, *, salary_max: int) -> tuple[int, int, User, int]:
    u = uuid.uuid4().hex[:8]
    client = Client(name=f"Rate {u}")
    cand = Candidate(name="Rate", lastname=f"Gate-{u}")
    user = User(
        email=f"rate-{u}@example.com",
        password_hash=hash_password("x"),
        name="R",
        role=UserRole.recruiter,
        is_active=True,
    )
    db.add_all([client, cand, user])
    await db.flush()
    # Rekruter musi NALEŻEĆ do oferty, której stawkę edytuje — bramka zakresu
    # zasobu tego wymaga, a produkcja i tak nie zna innego przypadku.
    job = Job(
        title=f"Rate Job {u}",
        client_id=client.id,
        salary_max=salary_max,
        recruiter_id=user.id,
    )
    db.add(job)
    await db.flush()
    stage = CandidateStage(
        candidate_id=cand.id,
        job_id=job.id,
        stage=PipelineStage.verified,
        moved_at=datetime.now(timezone.utc),
        moved_by=user.id,
        verification_status=VerificationStatus.active,
        budget_max_at_move=salary_max,
    )
    db.add(stage)
    await db.commit()
    return cand.id, job.id, user, stage.id


async def _status(db, stage_id: int) -> VerificationStatus:
    row = await db.get(CandidateStage, stage_id)
    return row.verification_status


async def test_within_budget_rate_edit_stays_active() -> None:
    async with AsyncSessionLocal() as db:
        cid, jid, actor, sid = await _seed_verified(db, salary_max=20000)
        await set_recruitment_expected_rate(
            cid,
            jid,
            ClientRateUpdate(rate_value=Decimal("15000"), rate_unit=RateUnit.monthly),
            current_user=actor,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        assert await _status(db, sid) == VerificationStatus.active


async def test_non_pln_rate_edit_stays_active() -> None:
    """Waluty nie porównujemy z budżetem — ale też niczego nie blokujemy."""
    async with AsyncSessionLocal() as db:
        cid, jid, actor, sid = await _seed_verified(db, salary_max=20000)
        await set_recruitment_expected_rate(
            cid,
            jid,
            ClientRateUpdate(
                rate_value=Decimal("100"),
                rate_unit=RateUnit.monthly,
                rate_currency="EUR",
            ),
            current_user=actor,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        assert await _status(db, sid) == VerificationStatus.active


async def test_over_budget_rate_edit_stays_active() -> None:
    async with AsyncSessionLocal() as db:
        cid, jid, actor, sid = await _seed_verified(db, salary_max=20000)
        await set_recruitment_expected_rate(
            cid,
            jid,
            ClientRateUpdate(rate_value=Decimal("30000"), rate_unit=RateUnit.monthly),
            current_user=actor,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        assert await _status(db, sid) == VerificationStatus.active
        row = await db.get(CandidateStage, sid)
        assert row.budget_max_at_move == 20000


async def test_rate_edit_reactivates_legacy_pending_row() -> None:
    """Wiersz `pending` sprzed zdjęcia bramki staje się aktywny przy korekcie."""
    async with AsyncSessionLocal() as db:
        cid, jid, actor, sid = await _seed_verified(db, salary_max=20000)
        row = await db.get(CandidateStage, sid)
        row.verification_status = VerificationStatus.pending
        await db.commit()
        await set_recruitment_expected_rate(
            cid,
            jid,
            ClientRateUpdate(rate_value=Decimal("30000"), rate_unit=RateUnit.monthly),
            current_user=actor,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateStage, sid)
        assert row.verification_status == VerificationStatus.active
        assert row.approved_at is not None
