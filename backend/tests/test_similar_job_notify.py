"""Unit tests for `similar_job_notify` (szybkie przepinanie, Faza 1).

Pure-function coverage of the alert decision (`build_alert`) and message
rendering (`build_message`) — no DB. The IO wrapper
(`notify_similar_job_candidates`) is exercised indirectly on prod via the
POST /jobs background task; its building blocks (fetch_historical_candidates,
emit) have their own suites.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.recruitment_pipeline import PipelineStage
from app.services.similar_job_candidates import (
    HistoricalCandidate,
    HistoricalSource,
    SimilarJobRef,
)
from app.services.similar_job_notify import build_alert, build_message


def _source(
    *,
    job_id: int = 100,
    stage: PipelineStage,
    client_id: int | None = None,
    similarity: float = 0.8,
) -> HistoricalSource:
    return HistoricalSource(
        job_id=job_id,
        job_title=f"Job {job_id}",
        stage=stage,
        similarity=similarity,
        months_ago=1.0,
        moved_at=datetime.now(timezone.utc),
        stage_weight=0.5,
        contribution=0.4,
        client_id=client_id,
    )


def _candidate(
    *,
    candidate_id: int,
    tier: str = "A",
    stage: PipelineStage = PipelineStage.cv_sent,
    same_client: bool = False,
    rejected_by_same_client: bool = False,
    client_id: int | None = None,
) -> HistoricalCandidate:
    return HistoricalCandidate(
        candidate_id=candidate_id,
        historical_score=1.0,
        tier=tier,  # type: ignore[arg-type]
        negative_signal=rejected_by_same_client,
        sources=(_source(stage=stage, client_id=client_id),),
        same_client=same_client,
        rejected_by_same_client=rejected_by_same_client,
    )


def _refs_tier_a() -> list[SimilarJobRef]:
    return [
        SimilarJobRef(job_id=100, title="Java Dev — Bank", similarity=0.87, tier="A")
    ]


@pytest.mark.unit
def test_build_alert_fires_for_client_facing_tier_a_candidate() -> None:
    ranked = [_candidate(candidate_id=1, stage=PipelineStage.cv_sent)]
    alert = build_alert(ranked, _refs_tier_a())
    assert alert is not None
    assert alert.candidate_ids == (1,)
    assert alert.top_similar_title == "Java Dev — Bank"
    assert alert.top_similarity == pytest.approx(0.87)


@pytest.mark.unit
def test_build_alert_skips_screening_only_history() -> None:
    """Screening/interview wewnętrzne ≠ "poszedł do klienta" — bez alertu."""
    ranked = [_candidate(candidate_id=1, stage=PipelineStage.screening)]
    assert build_alert(ranked, _refs_tier_a()) is None


@pytest.mark.unit
def test_build_alert_skips_tier_b_candidates() -> None:
    ranked = [_candidate(candidate_id=1, tier="B", stage=PipelineStage.hired)]
    refs = [
        SimilarJobRef(job_id=100, title="Job", similarity=0.60, tier="B"),
    ]
    assert build_alert(ranked, refs) is None


@pytest.mark.unit
def test_build_alert_excludes_rejected_by_same_client() -> None:
    ranked = [
        _candidate(
            candidate_id=1,
            stage=PipelineStage.cv_sent,
            same_client=True,
            rejected_by_same_client=True,
        )
    ]
    assert build_alert(ranked, _refs_tier_a()) is None


@pytest.mark.unit
def test_build_alert_counts_same_client_candidates() -> None:
    ranked = [
        _candidate(candidate_id=1, stage=PipelineStage.cv_sent, same_client=True),
        _candidate(candidate_id=2, stage=PipelineStage.hired),
    ]
    alert = build_alert(ranked, _refs_tier_a())
    assert alert is not None
    assert set(alert.candidate_ids) == {1, 2}
    assert alert.same_client_count == 1


@pytest.mark.unit
def test_build_message_mentions_counts_and_similarity() -> None:
    ranked = [
        _candidate(candidate_id=1, stage=PipelineStage.cv_sent, same_client=True),
        _candidate(candidate_id=2, stage=PipelineStage.hired),
    ]
    alert = build_alert(ranked, _refs_tier_a())
    assert alert is not None
    msg = build_message("Senior Java", alert, available_count=1)
    assert "Senior Java" in msg
    assert "Java Dev — Bank" in msg
    assert "87%" in msg
    assert "2 kandydat" in msg
    assert "1 u tego klienta" in msg
    assert "1 oznaczonych jako dostępni" in msg


# ── Powiadomienie liczy to samo, co zakładka (2026-08-20) ───────────────────
#
# `notify_similar_job_candidates` i `GET /jobs/{id}/candidates-from-similar`
# wołają ten sam `fetch_historical_candidates`, ale od chwili wprowadzenia
# bramki dopuszczalności w endpoincie liczyłyby CO INNEGO: dzwonek mówiłby
# „N kandydatów poszło już do klienta", a zakładka — do której ten dzwonek
# linkuje (`?tab=similar`) — pokazywałaby mniej. To nie jest dług zastany,
# tylko rozjazd produkowany przez tę samą zmianę, więc musi być domknięty razem
# z nią.
#
# Test idzie przez REALNĄ sesję i realny `candidate_conflicts`: patchowany jest
# tylko ranking (wymaga Qdranta) i `emit` (żeby przechwycić treść). Bramka
# biegnie po tej samej ścieżce co na produkcji.


@pytest.mark.integration
@pytest.mark.asyncio
async def test_notification_counts_only_assignable_candidates() -> None:
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.candidate_conflict import CandidateConflict, ConflictType
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.user import User, UserRole
    from app.core.security import hash_password
    from app.services import similar_job_notify as notify

    unique = _uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"NotifyGate-{unique}")
        user = User(
            email=f"notify-gate-{unique}@example.com",
            password_hash=hash_password(f"N0tify_{unique}!PassX"),
            name="Notify Gate",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add_all([cli, user])
        await db.flush()
        job = Job(
            title=f"pytest-notify-gate-{unique}",
            description="pytest sentinel",
            status=JobStatus.draft,
            client_id=cli.id,
            created_by=user.id,
            hiring_manager_contact_id=None,
        )
        cands = [
            Candidate(
                name=f"Notify{i}",
                lastname=f"Kandydat{unique}",
                email=f"notify-{i}-{unique}@example.com",
                # Status `active` — globalną blacklistę serwis odsiewa sam,
                # więc dowodem może być tylko konflikt z klientem oferty.
                status=CandidateStatus.active,
            )
            for i in range(3)
        ]
        db.add_all([job, *cands])
        await db.flush()
        blocked_id = cands[0].id
        db.add(
            CandidateConflict(
                candidate_id=blocked_id,
                client_id=cli.id,
                type=ConflictType.blacklist,
                reason="pytest — blacklista klienta",
                active=True,
            )
        )
        await db.commit()
        job_id, client_id = job.id, cli.id
        cand_ids = [c.id for c in cands]
        user_id = user.id

    ranked = [_candidate(candidate_id=i, stage=PipelineStage.cv_sent) for i in cand_ids]
    refs = _refs_tier_a()
    emit_mock = AsyncMock(return_value=object())

    try:
        async with AsyncSessionLocal() as db:
            with (
                patch.object(
                    notify,
                    "fetch_historical_candidates",
                    new=AsyncMock(return_value=(ranked, refs, "primary")),
                ),
                patch.object(notify, "emit", new=emit_mock),
            ):
                emitted = await notify.notify_similar_job_candidates(db, job_id)

        assert emitted == 1, "powiadomienie w ogóle nie poszło"
        message = emit_mock.await_args.kwargs["message"]
        assert "2 kandydat" in message, (
            "dzwonek obiecuje więcej osób, niż zakładka pokaże — kandydat "
            f"z aktywną blacklistą klienta został policzony ({message})"
        )
        assert "3 kandydat" not in message
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateConflict).where(
                    CandidateConflict.client_id == client_id
                )
            )
            await db.execute(delete(Candidate).where(Candidate.id.in_(cand_ids)))
            await db.execute(delete(Job).where(Job.id == job_id))
            await db.execute(delete(Client).where(Client.id == client_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_notification_is_silent_when_everyone_is_blocked() -> None:
    """Wszyscy zablokowani → zero emisji, nie dzwonek prowadzący do pustki.

    Bez bramki powiadomienie wysyłałoby rekrutera do zakładki, która po drugiej
    stronie pokaże komunikat „są, ale zablokowani dla tego klienta" — czyli
    dzwonek, którego jedyną treścią jest strata czasu.
    """
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.candidate_conflict import CandidateConflict, ConflictType
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.user import User, UserRole
    from app.core.security import hash_password
    from app.services import similar_job_notify as notify

    unique = _uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"NotifySilent-{unique}")
        user = User(
            email=f"notify-silent-{unique}@example.com",
            password_hash=hash_password(f"N0tify_{unique}!PassX"),
            name="Notify Silent",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add_all([cli, user])
        await db.flush()
        job = Job(
            title=f"pytest-notify-silent-{unique}",
            description="pytest sentinel",
            status=JobStatus.draft,
            client_id=cli.id,
            created_by=user.id,
            hiring_manager_contact_id=None,
        )
        cand = Candidate(
            name="NotifySilent",
            lastname=f"Kandydat{unique}",
            email=f"notify-silent-c-{unique}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add(
            CandidateConflict(
                candidate_id=cand.id,
                client_id=cli.id,
                type=ConflictType.nda,
                reason="pytest — NDA",
                active=True,
            )
        )
        await db.commit()
        job_id, client_id, cand_id, user_id = job.id, cli.id, cand.id, user.id

    ranked = [_candidate(candidate_id=cand_id, stage=PipelineStage.cv_sent)]
    emit_mock = AsyncMock(return_value=object())
    try:
        async with AsyncSessionLocal() as db:
            with (
                patch.object(
                    notify,
                    "fetch_historical_candidates",
                    new=AsyncMock(return_value=(ranked, _refs_tier_a(), "primary")),
                ),
                patch.object(notify, "emit", new=emit_mock),
            ):
                emitted = await notify.notify_similar_job_candidates(db, job_id)
        assert emitted == 0
        emit_mock.assert_not_awaited()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateConflict).where(
                    CandidateConflict.client_id == client_id
                )
            )
            await db.execute(delete(Candidate).where(Candidate.id == cand_id))
            await db.execute(delete(Job).where(Job.id == job_id))
            await db.execute(delete(Client).where(Client.id == client_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
