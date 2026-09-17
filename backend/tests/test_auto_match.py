"""Autonomiczne dopasowanie CV ↔ rekrutacje (decyzja Artura, 17.09.2026).

Kontrakty:

- decyzja jest czystą funkcją: próg, must-have, kary, sufit — od najlepszego;
- importer JJIT i auto-match używają tej samej reguły (jeden obiekt funkcji);
- pasujący kandydat trafia do pipeline'u (etap „Ogłoszenia”, tag auto-match),
  a właściciel rekrutacji dostaje dzwonek;
- ta sama wersja CV nie trafia drugi raz do tej samej rekrutacji;
- tryb próbny ocenia i zapisuje dziennik, ale niczego nie dodaje;
- CV z maila od nieznanego nadawcy: silna tożsamość łączy, samo imię i nazwisko
  niczego nie zakłada, brak kontaktu w CV niczego nie zakłada.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services import auto_match_service as ams
from app.services.auto_match_service import Scored, decide

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


def _s(job_id, score, *, match=("Python",), gap=(), penalties=()):
    return Scored(
        candidate_id=1,
        job_id=job_id,
        score=score,
        matching_must=tuple(match),
        gap_must=tuple(gap),
        penalties=tuple(penalties),
    )


def test_decide_orders_by_score_and_respects_cap_threshold_and_must():
    decisions = decide(
        [
            _s(1, 91),
            _s(2, 69.9),
            _s(3, 88, match=(), gap=("Kafka",)),
            _s(4, 95, penalties=("konflikt z klientem",)),
            _s(5, 80),
            _s(6, 75),
            _s(7, 72, match=(), gap=()),
        ],
        min_score=70,
        require_must=True,
        cap=2,
    )
    by_job = {d.job_id: d.decision for d in decisions}
    assert by_job == {
        1: "add",
        5: "add",
        6: "capped",
        7: "capped",
        2: "below_threshold",
        3: "must_gap",
        4: "penalized",
    }
    assert [d.job_id for d in decisions][:3] == [4, 1, 3]


def test_client_conflict_warning_blocks_the_autonomous_add():
    """Od #1589 konflikt z klientem tylko ostrzega rekrutera; automat go nie dodaje."""
    row = Scored(
        candidate_id=1,
        job_id=9,
        score=95,
        matching_must=("Python",),
        gap_must=(),
        penalties=(),
        warnings=("active_conflict",),
    )
    [decision] = decide([row], min_score=70, require_must=True, cap=3)
    assert decision.decision == "penalized"
    assert "active_conflict" in decision.reason
    breakdown = SimpleNamespace(
        candidate_id=1, job_id=9, total=95, matching_must=["Python"], gap_must=[],
        penalties=[], warnings=["active_conflict", "something_else"],
    )
    assert ams._scored_from_breakdown(breakdown).warnings == ("active_conflict",)


def test_jjit_and_auto_match_share_one_rule():
    from app.services import auto_match_rules
    from app.services.integrations.jjit import nexus_client

    assert nexus_client.is_good_match is auto_match_rules.is_good_match


# ── integracja z bazą ────────────────────────────────────────────────────────


async def _seed(db, *, job_status="published"):
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    owner = User(
        email=f"auto-match-{marker}@example.com",
        name="Właściciel Rekrutacji",
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value],
        is_active=True,
    )
    client = Client(name=f"auto-match-{marker}")
    db.add_all([owner, client])
    await db.flush()
    job = Job(
        title=f"Python Developer {marker}",
        client_id=client.id,
        status=JobStatus(job_status),
        recruiter_id=owner.id,
    )
    candidate = Candidate(
        name="Anna",
        lastname=f"Auto{marker}",
        cv_parsed_at=datetime.now(timezone.utc),
        cv_extracted_data={
            "_profile_schema": 2,
            "cv_highlights": {"source_hash": f"cv-{marker}"},
        },
    )
    db.add_all([job, candidate])
    await db.flush()
    return owner, job, candidate


def _breakdown(candidate_id, job_id, total=86.0):
    return SimpleNamespace(
        candidate_id=candidate_id,
        job_id=job_id,
        total=total,
        matching_must=["Python"],
        gap_must=[],
        penalties=[],
    )


def _stub_ranking(monkeypatch, *, job_hits, candidate_hits, total=86.0):
    from app.services import (
        dealbreaker_filters,
        embedding_service,
        pipeline_eligibility,
        scoring_service,
    )

    seen_ids: dict[str, list[list[int]]] = {"jobs": [], "candidates": []}

    async def scoped(query_text, *, jobs_collection, ids):
        seen_ids["jobs" if jobs_collection else "candidates"].append(list(ids))
        hits = job_hits if jobs_collection else candidate_hits
        return {k: v for k, v in hits.items() if k in ids}

    monkeypatch.setattr(ams, "scoped_similarity", scoped)
    monkeypatch.setattr(embedding_service, "_build_candidate_text", lambda c: "cv")
    monkeypatch.setattr(embedding_service, "_build_job_text", lambda j: "job")

    async def eligible(db, *, job, candidates, now):
        return list(candidates)

    monkeypatch.setattr(pipeline_eligibility, "filter_eligible_candidates", eligible)
    monkeypatch.setattr(
        dealbreaker_filters,
        "apply_dealbreakers",
        lambda cands, **kw: SimpleNamespace(kept=list(cands), exclusion_reasons={}),
    )

    async def rank_jobs(candidate, jobs, db, *, similarity_map=None, contexts=None):
        return [_breakdown(candidate.id, j.id, total) for j in jobs]

    async def rank_candidates(job, candidates, db, *, similarity_map=None):
        return [_breakdown(c.id, job.id, total) for c in candidates]

    async def contexts(db, jobs, ids):
        return {}

    monkeypatch.setattr(scoring_service, "rank_jobs_for_candidate", rank_jobs)
    monkeypatch.setattr(scoring_service, "rank_candidates_for_job", rank_candidates)
    monkeypatch.setattr(scoring_service, "build_jobs_scoring_contexts", contexts)
    return seen_ids


async def _cleanup(ids):
    """Sprzątanie best-effort: dodanie do pipeline'u zakłada powiązane wiersze
    (notatki, proces, migawki CV), a baza testowa jest wspólna dla przebiegu."""
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    statements = [
        ("DELETE FROM notifications WHERE user_id = :owner", {"owner": ids["owner"]}),
        ("DELETE FROM candidate_auto_match_log WHERE job_id = :job", {"job": ids["job"]}),
        (
            "DELETE FROM candidate_match_outbox WHERE job_id = :job OR candidate_id = :cand",
            {"job": ids["job"], "cand": ids["candidate"]},
        ),
        ("DELETE FROM notes WHERE job_id = :job", {"job": ids["job"]}),
        ("DELETE FROM candidate_stages WHERE job_id = :job", {"job": ids["job"]}),
        ("DELETE FROM jobs WHERE id = :job", {"job": ids["job"]}),
        ("DELETE FROM candidates WHERE id = :cand", {"cand": ids["candidate"]}),
        ("DELETE FROM clients WHERE id = :client", {"client": ids["client"]}),
        ("DELETE FROM users WHERE id = :owner", {"owner": ids["owner"]}),
    ]
    async with AsyncSessionLocal() as db:
        for sql, params in statements:
            try:
                async with db.begin_nested():
                    await db.execute(text(sql), params)
            except Exception:  # noqa: BLE001 — pozostałe powiązania zostają w bazie testowej
                pass
        await db.commit()


@needs_db
async def test_new_cv_lands_in_pipeline_once_and_notifies_the_owner(monkeypatch):
    from sqlalchemy import select, text

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.models.notification import Notification, NotificationType
    from app.models.recruitment_pipeline import CandidateStage

    monkeypatch.setattr(settings, "AUTO_MATCH_DRY_RUN", False)
    async with AsyncSessionLocal() as db:
        owner, job, candidate = await _seed(db)
        await db.commit()
        ids = {"owner": owner.id, "job": job.id, "candidate": candidate.id, "client": job.client_id}
    try:
        seen = _stub_ranking(monkeypatch, job_hits={ids["job"]: 0.91}, candidate_hits={})
        for _ in range(2):
            async with AsyncSessionLocal() as db:
                event = CandidateMatchOutbox(
                    candidate_id=ids["candidate"],
                    trigger="cv_upload",
                    profile_revision="rev-1",
                    status="processing",
                )
                db.add(event)
                await db.commit()
                await ams.run_candidate_event(db, event)
                # Tak jak worker: zakończone zdarzenie zwalnia częściowy UNIQUE
                # kolejki, więc ta sama wersja CV może przyjść drugi raz — a dedup
                # ma ją zatrzymać na dzienniku decyzji.
                event.status = "done"
                await db.commit()

        async with AsyncSessionLocal() as db:
            stages = (
                await db.scalars(
                    select(CandidateStage).where(
                        CandidateStage.job_id == ids["job"],
                        CandidateStage.candidate_id == ids["candidate"],
                    )
                )
            ).all()
            assert len(stages) == 1
            log = (
                await db.execute(
                    text("SELECT decision, stage_id FROM candidate_auto_match_log WHERE job_id = :j"),
                    {"j": ids["job"]},
                )
            ).all()
            assert [(r.decision, r.stage_id) for r in log] == [("added", stages[0].id)]
            candidate = await db.get(Candidate, ids["candidate"])
            assert "auto-match" in (candidate.tags or [])
            notes = (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == ids["owner"],
                        Notification.notification_type == NotificationType.auto_match,
                    )
                )
            ).all()
            assert len(notes) == 1
            assert f"?job={ids['job']}" in (notes[0].link or "")
            # Pula = wyłącznie opublikowane rekrutacje bez tego kandydata.
            assert ids["job"] in seen["jobs"][0]
            # Drugie zdarzenie: kandydat jest już w procesie, więc tej rekrutacji
            # nie ma nawet w puli wyszukiwania.
            assert ids["job"] not in seen["jobs"][1]
            from app.models.user import User
            from app.services.notification_access import user_can_receive_notification

            owner = await db.get(User, ids["owner"])
            assert user_can_receive_notification(
                owner,
                notes[0].notification_type,
                related_entity_type=notes[0].related_entity_type,
                link=notes[0].link,
            )
    finally:
        await _cleanup(ids)


@needs_db
async def test_dry_run_logs_the_decision_without_adding(monkeypatch):
    from sqlalchemy import func, select, text

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.models.recruitment_pipeline import CandidateStage

    monkeypatch.setattr(settings, "AUTO_MATCH_DRY_RUN", True)
    async with AsyncSessionLocal() as db:
        owner, job, candidate = await _seed(db)
        await db.commit()
        ids = {"owner": owner.id, "job": job.id, "candidate": candidate.id, "client": job.client_id}
    try:
        _stub_ranking(monkeypatch, job_hits={}, candidate_hits={ids["candidate"]: 0.8})
        async with AsyncSessionLocal() as db:
            event = CandidateMatchOutbox(job_id=ids["job"], trigger="job_publish", status="processing")
            db.add(event)
            await db.commit()
            result = await ams.run_job_event(db, event)
        assert result["decisions"] == {"dry_run": 1}
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count()).select_from(CandidateStage).where(CandidateStage.job_id == ids["job"])
                )
                == 0
            )
            decision = await db.scalar(
                text("SELECT decision FROM candidate_auto_match_log WHERE job_id = :j"), {"j": ids["job"]}
            )
            assert decision == "dry_run"
    finally:
        await _cleanup(ids)


@needs_db
async def test_stale_event_is_skipped_by_the_worker(monkeypatch):
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.tasks import candidate_auto_match

    async with AsyncSessionLocal() as db:
        owner, job, candidate = await _seed(db)
        event = CandidateMatchOutbox(candidate_id=candidate.id, trigger="cv_upload", profile_revision="old", status="processing")
        db.add(event)
        await db.commit()
        ids = {"owner": owner.id, "job": job.id, "candidate": candidate.id, "client": job.client_id}
        event_id = event.id
        await db.execute(
            update(CandidateMatchOutbox)
            .where(CandidateMatchOutbox.id == event_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=5))
        )
        await db.commit()
    try:
        assert await candidate_auto_match._process(event_id) == "skipped"
    finally:
        await _cleanup(ids)


# ── M365: CV od nadawcy spoza bazy ───────────────────────────────────────────


def _m365_inputs(tmp_path):
    (tmp_path / "cv.pdf").write_bytes(b"cv")
    attachment = SimpleNamespace(
        id=7,
        is_cv_candidate=True,
        storage_path="cv.pdf",
        filename="cv.pdf",
        parse_error=None,
        cv_parse_attempted_at=None,
        parsed_candidate_id=None,
    )
    email = SimpleNamespace(
        id=9,
        candidate_id=None,
        is_private_filtered=False,
        user_id=3,
        match_method=None,
        match_confidence=None,
        matched_at=None,
    )
    return attachment, email


def _patch_m365(monkeypatch, tmp_path, parsed, duplicates):
    from app.services import dedup_service
    from app.services.m365 import attachment_handler

    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachment_handler.settings, "M365_AUTO_PARSE_CV", True)
    monkeypatch.setattr(attachment_handler.settings, "M365_AUTO_CREATE_CANDIDATE_FROM_CV", True)
    monkeypatch.setattr(
        attachment_handler, "_extract_and_parse", AsyncMock(return_value=("tekst", parsed))
    )
    monkeypatch.setattr(dedup_service, "find_candidate_duplicates", AsyncMock(return_value=duplicates))
    parse = AsyncMock()
    monkeypatch.setattr(attachment_handler, "try_parse_cv", parse)
    return attachment_handler, parse


@pytest.mark.asyncio
async def test_unknown_sender_cv_with_strong_identity_links_existing(monkeypatch, tmp_path):
    from app.models.m365 import EmailMatchMethod

    handler, parse = _patch_m365(
        monkeypatch,
        tmp_path,
        {"first_name": "Jan", "last_name": "Nowak", "email": "jan@example.com"},
        [{"candidate_id": 42, "match_score": 1.0, "match_reasons": ["email_exact"]}],
    )
    attachment, email = _m365_inputs(tmp_path)
    assert await handler.try_create_candidate_from_cv(AsyncMock(), attachment, email) == 42
    assert email.candidate_id == 42
    assert email.match_method is EmailMatchMethod.cv_identity
    parse.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_sender_cv_matching_only_by_name_creates_nothing(monkeypatch, tmp_path):
    handler, parse = _patch_m365(
        monkeypatch,
        tmp_path,
        {"first_name": "Jan", "last_name": "Kowalski", "phone": "600100200"},
        [{"candidate_id": 5, "match_score": 0.9, "match_reasons": ["name_exact"]}],
    )
    attachment, email = _m365_inputs(tmp_path)
    db = AsyncMock()
    assert await handler.try_create_candidate_from_cv(db, attachment, email) is None
    assert attachment.parse_error == "possible_duplicate_name"
    assert email.candidate_id is None
    db.add.assert_not_called()
    parse.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_sender_cv_without_contact_creates_nothing(monkeypatch, tmp_path):
    handler, _ = _patch_m365(monkeypatch, tmp_path, {"first_name": "Jan", "last_name": "Bez"}, [])
    attachment, email = _m365_inputs(tmp_path)
    assert await handler.try_create_candidate_from_cv(AsyncMock(), attachment, email) is None
    assert attachment.parse_error == "identity_insufficient"


@needs_db
async def test_unknown_sender_cv_creates_a_candidate(monkeypatch, tmp_path):
    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate

    marker = uuid.uuid4().hex[:8]
    handler, parse = _patch_m365(
        monkeypatch,
        tmp_path,
        {"first_name": "Ewa", "last_name": f"Mail{marker}", "email": f"ewa.{marker}@example.com"},
        [],
    )
    attachment, email = _m365_inputs(tmp_path)
    email.user_id = None

    async def parsed_ok(db, att, em, **kwargs):
        att.parsed_candidate_id = em.candidate_id

    parse.side_effect = parsed_ok
    from app.services import index_outbox_service

    index = AsyncMock(return_value=True)
    monkeypatch.setattr(index_outbox_service, "schedule_or_embed_candidate", index)
    async with AsyncSessionLocal() as db:
        try:
            candidate_id = await handler.try_create_candidate_from_cv(db, attachment, email)
            await db.flush()
            candidate = await db.get(Candidate, candidate_id)
            assert candidate.source == "email"
            assert candidate.email == f"ewa.{marker}@example.com"
            assert email.candidate_id == candidate_id
            action = await db.scalar(
                select(Activity.action).where(
                    Activity.entity_type == "candidate", Activity.entity_id == candidate_id
                )
            )
            assert action == "created_from_email"
            parse.assert_awaited_once()
            # Odczyt przeszedł wspólną ścieżką — bez drugiego wektora.
            index.assert_not_awaited()

            # Odczyt się nie udał: kandydat i tak trafia do indeksu.
            parse.side_effect = None
            other, other_email = _m365_inputs(tmp_path)
            other_email.user_id = None
            from app.services import dedup_service

            monkeypatch.setattr(
                handler,
                "_extract_and_parse",
                AsyncMock(
                    return_value=(
                        "tekst",
                        {
                            "first_name": "Ola",
                            "last_name": f"Mail{marker}",
                            "email": f"ola.{marker}@example.com",
                        },
                    )
                ),
            )
            monkeypatch.setattr(dedup_service, "find_candidate_duplicates", AsyncMock(return_value=[]))
            second_id = await handler.try_create_candidate_from_cv(db, other, other_email)
            index.assert_awaited_once_with(second_id, db)
        finally:
            await db.rollback()
            await db.execute(delete(Candidate).where(Candidate.lastname == f"Mail{marker}"))
            await db.commit()


@needs_db
async def test_dry_run_approvals_are_added_after_going_live(monkeypatch):
    """Dziennik trybu próbnego nie może zablokować dodania po przełączeniu."""
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_auto_match import CandidateMatchOutbox

    async with AsyncSessionLocal() as db:
        owner, job, candidate = await _seed(db)
        await db.commit()
        ids = {"owner": owner.id, "job": job.id, "candidate": candidate.id, "client": job.client_id}
    try:
        _stub_ranking(monkeypatch, job_hits={}, candidate_hits={ids["candidate"]: 0.8})
        for dry in (True, False):
            monkeypatch.setattr(settings, "AUTO_MATCH_DRY_RUN", dry)
            async with AsyncSessionLocal() as db:
                event = CandidateMatchOutbox(job_id=ids["job"], trigger="job_publish", status="processing")
                db.add(event)
                await db.commit()
                await ams.run_job_event(db, event)
                event.status = "done"
                await db.commit()
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text("SELECT decision, stage_id FROM candidate_auto_match_log WHERE job_id = :j"),
                    {"j": ids["job"]},
                )
            ).all()
        assert [r.decision for r in rows] == ["added"]
        assert rows[0].stage_id is not None
    finally:
        await _cleanup(ids)


@needs_db
async def test_job_requirement_change_re_evaluates_earlier_rejections(monkeypatch):
    from sqlalchemy import text, update

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.models.job import Job

    monkeypatch.setattr(settings, "AUTO_MATCH_DRY_RUN", True)
    async with AsyncSessionLocal() as db:
        owner, job, candidate = await _seed(db)
        await db.commit()
        ids = {"owner": owner.id, "job": job.id, "candidate": candidate.id, "client": job.client_id}
    try:
        for total in (40.0, 90.0):
            _stub_ranking(monkeypatch, job_hits={}, candidate_hits={ids["candidate"]: 0.8}, total=total)
            async with AsyncSessionLocal() as db:
                if total == 90.0:
                    await db.execute(
                        update(Job)
                        .where(Job.id == ids["job"])
                        .values(updated_at=datetime.now(timezone.utc) + timedelta(seconds=5))
                    )
                event = CandidateMatchOutbox(job_id=ids["job"], trigger="job_publish", status="processing")
                db.add(event)
                await db.commit()
                await ams.run_job_event(db, event)
                event.status = "done"
                await db.commit()
        async with AsyncSessionLocal() as db:
            decision = await db.scalar(
                text("SELECT decision FROM candidate_auto_match_log WHERE job_id = :j"),
                {"j": ids["job"]},
            )
        assert decision == "dry_run"
    finally:
        await _cleanup(ids)


@needs_db
async def test_claim_never_collides_and_dead_letters_exhausted_events(monkeypatch):
    from sqlalchemy import select, text

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.tasks import candidate_auto_match

    async with AsyncSessionLocal() as db:
        owner, job, candidate = await _seed(db)
        await db.commit()
        ids = {"owner": owner.id, "job": job.id, "candidate": candidate.id, "client": job.client_id}
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        failed = CandidateMatchOutbox(
            job_id=ids["job"], trigger="job_publish", status="failed", attempts=1, heartbeat_at=old
        )
        db.add(failed)
        await db.commit()
        # Drugie zgłoszenie tej samej rekrutacji przy otwartym `failed` jest zwijane.
        from app.services.auto_match_outbox import enqueue_job

        monkeypatch.setattr(settings, "AUTO_MATCH_ENABLED", True)
        await enqueue_job(db, job_id=ids["job"], trigger="job_publish")
        await db.commit()
        open_rows = await db.scalar(
            text("SELECT count(*) FROM candidate_match_outbox WHERE job_id = :j"), {"j": ids["job"]}
        )
        assert open_rows == 1
        stuck = CandidateMatchOutbox(
            candidate_id=ids["candidate"],
            trigger="cv_upload",
            profile_revision="stuck",
            status="processing",
            attempts=settings.AUTO_MATCH_MAX_ATTEMPTS,
            heartbeat_at=old,
        )
        db.add(stuck)
        await db.commit()
        stuck_id, failed_id = stuck.id, failed.id
    try:
        async with AsyncSessionLocal() as db:
            claimed = await candidate_auto_match._claim(db)
        assert failed_id in claimed
        async with AsyncSessionLocal() as db:
            status = await db.scalar(
                select(CandidateMatchOutbox.status).where(CandidateMatchOutbox.id == stuck_id)
            )
        assert status == "dead"
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
async def test_unknown_sender_cv_with_conflicting_strong_matches_creates_nothing(monkeypatch, tmp_path):
    handler, parse = _patch_m365(
        monkeypatch,
        tmp_path,
        {"first_name": "Jan", "last_name": "Nowak", "email": "jan@example.com", "phone": "600100200"},
        [
            {"candidate_id": 1, "match_score": 1.0, "match_reasons": ["phone_exact"]},
            {"candidate_id": 2, "match_score": 1.0, "match_reasons": ["email_exact"]},
        ],
    )
    attachment, email = _m365_inputs(tmp_path)
    assert await handler.try_create_candidate_from_cv(AsyncMock(), attachment, email) is None
    assert attachment.parse_error == "conflicting_identity"
    assert email.candidate_id is None
    assert attachment.cv_parse_attempted_at is None
    parse.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_sender_cv_with_only_company_contact_creates_nothing(monkeypatch, tmp_path):
    handler, _ = _patch_m365(
        monkeypatch,
        tmp_path,
        {"first_name": "Jan", "last_name": "Nowak", "email": "rekruter@b2bnetwork.pl"},
        [],
    )
    monkeypatch.setattr(handler.settings, "SSO_ALLOWED_DOMAINS", "b2bnetwork.pl")
    attachment, email = _m365_inputs(tmp_path)
    assert await handler.try_create_candidate_from_cv(AsyncMock(), attachment, email) is None
    assert attachment.parse_error == "identity_insufficient"

