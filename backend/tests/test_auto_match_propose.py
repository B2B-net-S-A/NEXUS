"""Auto-match w trybie ``propose`` (21.09.2026): nowe CV → skrzynka „Propozycje".

Kontrakty:

- ``AUTO_MATCH_MODE`` wygrywa; bez niego alias ``AUTO_MATCH_DRY_RUN``
  (true → dry_run, false → add); bez obu → ``propose``; literówka → ``dry_run``;
- w trybie ``propose`` dobry wynik daje decyzję ``proposed`` i wiersz
  ``job_proposals`` (źródło ``new_cv``, wersja CV) — a w pipeline'ie NIE pojawia
  się nikt i nikt nie dostaje dzwonka „system dodał kandydata";
- ``proposed`` blokuje ponowną ocenę tej samej wersji CV jak inne decyzje;
- ostrzeżenia blokujące (konflikt z klientem) nadal dają ``penalized``;
- JEDEN dzienny digest na (rekrutacja, odbiorca), kolejne propozycje tego dnia
  podbijają licznik w tym samym wpisie.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import auto_match_service as ams
from app.services.auto_match_outbox import auto_match_mode
from tests.test_auto_match import _cleanup, _seed, _stub_ranking, needs_db


@pytest.mark.parametrize(
    "mode,alias,expected",
    [
        (None, None, "propose"),
        (None, True, "dry_run"),
        (None, False, "add"),
        ("add", True, "add"),
        ("propose", False, "propose"),
        (" DRY_RUN ", False, "dry_run"),
        ("ad", False, "dry_run"),
        ("", True, "dry_run"),
    ],
)
def test_mode_resolution(monkeypatch, mode, alias, expected):
    monkeypatch.setattr(settings, "AUTO_MATCH_MODE", mode)
    monkeypatch.setattr(settings, "AUTO_MATCH_DRY_RUN", alias)
    assert auto_match_mode() == expected


def test_digest_wording():
    assert ams._digest_text(1) == "1 nowa propozycja z nowych CV"
    assert ams._digest_text(3) == "3 nowe propozycje z nowych CV"
    assert ams._digest_text(5) == "5 nowych propozycji z nowych CV"
    assert ams._digest_text(12) == "12 nowych propozycji z nowych CV"
    assert ams._digest_text(22) == "22 nowe propozycje z nowych CV"


def test_digest_type_is_visible_to_its_recipients():
    from app.models.notification import NotificationType
    from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE

    assert NotificationType.auto_match_proposals in NOTIFICATION_SECTION_BY_TYPE


async def _candidate_event(ids, revision="rev-1"):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_auto_match import CandidateMatchOutbox

    async with AsyncSessionLocal() as db:
        event = CandidateMatchOutbox(
            candidate_id=ids["candidate"],
            trigger="cv_upload",
            profile_revision=revision,
            status="processing",
        )
        db.add(event)
        await db.commit()
        result = await ams.run_candidate_event(db, event)
        event.status = "done"
        await db.commit()
        return result


async def _world(monkeypatch, *, mode="propose"):
    from app.core.database import AsyncSessionLocal

    monkeypatch.setattr(settings, "AUTO_MATCH_MODE", mode)
    async with AsyncSessionLocal() as db:
        owner, job, candidate = await _seed(db)
        await db.commit()
        return {
            "owner": owner.id,
            "job": job.id,
            "candidate": candidate.id,
            "client": job.client_id,
        }


async def _purge_proposals(ids):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM job_proposals WHERE job_id = :j"), {"j": ids["job"]}
        )
        await db.execute(
            text(
                "DELETE FROM activities WHERE entity_type = 'job_automation' "
                "AND entity_id = :j"
            ),
            {"j": ids["job"]},
        )
        await db.commit()


@needs_db
async def test_propose_mode_writes_a_proposal_and_nothing_to_the_pipeline(monkeypatch):
    from sqlalchemy import func, select, text

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.job_proposal import JobProposal
    from app.models.notification import Notification, NotificationType
    from app.models.recruitment_pipeline import CandidateStage

    ids = await _world(monkeypatch)
    try:
        _stub_ranking(monkeypatch, job_hits={ids["job"]: 0.91}, candidate_hits={})
        first = await _candidate_event(ids)
        assert first["decisions"] == {"proposed": 1}
        # Ta sama wersja CV drugi raz: dziennik decyzji zatrzymuje ponowną ocenę.
        second = await _candidate_event(ids)
        assert second["decisions"] == {}

        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(CandidateStage)
                    .where(CandidateStage.job_id == ids["job"])
                )
                == 0
            )
            candidate = await db.get(Candidate, ids["candidate"])
            assert "auto-match" not in (candidate.tags or [])
            [proposal] = (
                await db.scalars(
                    select(JobProposal).where(JobProposal.job_id == ids["job"])
                )
            ).all()
            assert (proposal.source, proposal.status) == ("new_cv", "proposed")
            assert proposal.candidate_id == ids["candidate"]
            assert proposal.cv_revision == "rev-1"
            assert proposal.evidence == {"matched_must": ["Python"]}
            assert float(proposal.score) == 86.0
            log = (
                await db.execute(
                    text(
                        "SELECT decision, stage_id FROM candidate_auto_match_log "
                        "WHERE job_id = :j"
                    ),
                    {"j": ids["job"]},
                )
            ).all()
            assert [(r.decision, r.stage_id) for r in log] == [("proposed", None)]
            notes = (
                await db.scalars(
                    select(Notification).where(Notification.user_id == ids["owner"])
                )
            ).all()
            assert [n.notification_type for n in notes] == [
                NotificationType.auto_match_proposals
            ]
            assert notes[0].link == f"/jobs/{ids['job']}?tab=similar"
            assert notes[0].title.startswith("1 nowa propozycja z nowych CV")
            [event] = (
                await db.scalars(
                    select(Activity).where(
                        Activity.entity_type == "job_automation",
                        Activity.entity_id == ids["job"],
                    )
                )
            ).all()
            assert event.action == "auto_match_proposed"
            assert event.details["count"] == 1
    finally:
        await _purge_proposals(ids)
        await _cleanup(ids)


@needs_db
async def test_second_proposal_of_the_day_updates_the_same_digest(monkeypatch):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.models.notification import Notification

    ids = await _world(monkeypatch)
    extra_id = None
    try:
        _stub_ranking(monkeypatch, job_hits={ids["job"]: 0.91}, candidate_hits={})
        await _candidate_event(ids)
        async with AsyncSessionLocal() as db:
            note = await db.scalar(
                select(Notification).where(Notification.user_id == ids["owner"])
            )
            note.is_read = True
            extra = Candidate(name="Druga", lastname="Propozycja")
            db.add(extra)
            await db.commit()
            extra_id = extra.id
            event = CandidateMatchOutbox(
                candidate_id=extra_id,
                trigger="cv_upload",
                profile_revision="rev-x",
                status="processing",
            )
            db.add(event)
            await db.commit()
            await ams.run_candidate_event(db, event)
            event.status = "done"
            await db.commit()
        async with AsyncSessionLocal() as db:
            notes = (
                await db.scalars(
                    select(Notification).where(Notification.user_id == ids["owner"])
                )
            ).all()
            assert len(notes) == 1
            assert notes[0].title.startswith("2 nowe propozycje z nowych CV")
            # Podbity licznik wraca jako nieprzeczytany.
            assert notes[0].is_read is False
    finally:
        await _purge_proposals(ids)
        if extra_id is not None:
            from sqlalchemy import text

            async with AsyncSessionLocal() as db:
                await db.execute(
                    text(
                        "DELETE FROM candidate_auto_match_log WHERE candidate_id = :c"
                    ),
                    {"c": extra_id},
                )
                await db.execute(
                    text("DELETE FROM candidate_match_outbox WHERE candidate_id = :c"),
                    {"c": extra_id},
                )
                await db.execute(
                    text("DELETE FROM candidates WHERE id = :c"), {"c": extra_id}
                )
                await db.commit()
        await _cleanup(ids)


@needs_db
async def test_blocking_warning_is_never_proposed(monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.job_proposal import JobProposal
    from app.services import scoring_service

    ids = await _world(monkeypatch)
    try:
        _stub_ranking(monkeypatch, job_hits={ids["job"]: 0.91}, candidate_hits={})

        async def rank_jobs(candidate, jobs, db, *, similarity_map=None, contexts=None):
            return [
                SimpleNamespace(
                    candidate_id=candidate.id,
                    job_id=j.id,
                    total=95.0,
                    matching_must=["Python"],
                    gap_must=[],
                    penalties=[],
                    warnings=["active_conflict"],
                )
                for j in jobs
            ]

        monkeypatch.setattr(scoring_service, "rank_jobs_for_candidate", rank_jobs)
        result = await _candidate_event(ids)
        assert result["decisions"] == {"penalized": 1}
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(JobProposal)
                    .where(JobProposal.job_id == ids["job"])
                )
                == 0
            )
    finally:
        await _cleanup(ids)


@needs_db
async def test_job_event_proposes_fresh_cvs_until_the_job_changes(monkeypatch):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.models.job_proposal import JobProposal
    from app.models.recruitment_pipeline import CandidateStage

    ids = await _world(monkeypatch)
    try:
        _stub_ranking(monkeypatch, job_hits={}, candidate_hits={ids["candidate"]: 0.8})

        async def _job_event():
            async with AsyncSessionLocal() as db:
                event = CandidateMatchOutbox(
                    job_id=ids["job"], trigger="job_publish", status="processing"
                )
                db.add(event)
                await db.commit()
                result = await ams.run_job_event(db, event)
                event.status = "done"
                await db.commit()
                return result

        assert (await _job_event())["decisions"] == {"proposed": 1}
        # Bez zmiany rekrutacji ta sama para nie jest oceniana ponownie.
        assert (await _job_event())["decisions"] == {}
        async with AsyncSessionLocal() as db:
            rows = (
                await db.scalars(
                    select(JobProposal).where(JobProposal.job_id == ids["job"])
                )
            ).all()
            assert [(r.source, r.status) for r in rows] == [("new_cv", "proposed")]
            assert (
                await db.scalar(
                    select(CandidateStage.id).where(CandidateStage.job_id == ids["job"])
                )
            ) is None
    finally:
        await _purge_proposals(ids)
        await _cleanup(ids)


def test_job_event_is_recorded_even_when_auto_match_is_off(monkeypatch):
    """Zdarzenie rekrutacji zasila też nocny przegląd bazy."""
    from app.services import auto_match_outbox as outbox

    monkeypatch.setattr(settings, "AUTO_MATCH_ENABLED", False)
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_ENABLED", True)
    assert outbox.job_events_enabled() is True
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_ENABLED", False)
    # Oba wyłączniki OFF = stan sprzed automatów: nic nie jest zapisywane.
    assert outbox.job_events_enabled() is False


@needs_db
async def test_job_change_without_new_people_does_not_ring_the_bell(monkeypatch):
    """Runda 6 audytu (A6-2): każda zmiana rekrutacji ocenia wszystkich od
    nowa, a dzwonek liczył PRZETWORZONE pary — „1 nowa propozycja” przy
    każdej edycji, choć w skrzynce nikt nowy się nie pojawił."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select, update

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.models.job import Job
    from app.models.notification import Notification

    ids = await _world(monkeypatch)
    try:
        _stub_ranking(
            monkeypatch,
            job_hits={ids["job"]: 0.91},
            candidate_hits={ids["candidate"]: 0.91},
        )
        first = await _candidate_event(ids)
        assert first["decisions"] == {"proposed": 1}
        async with AsyncSessionLocal() as db:
            await db.execute(
                Notification.__table__.delete().where(
                    Notification.user_id == ids["owner"]
                )
            )
            # Zmiana rekrutacji PO decyzji — dziennik jej nie blokuje.
            await db.execute(
                update(Job)
                .where(Job.id == ids["job"])
                .values(updated_at=datetime.now(timezone.utc) + timedelta(seconds=1))
            )
            await db.commit()
            event = CandidateMatchOutbox(
                job_id=ids["job"], trigger="job_publish", status="processing"
            )
            db.add(event)
            await db.commit()
            again = await ams.run_job_event(db, event)
        assert again["decisions"] == {"proposed": 1}
        assert again["notified"] == 0
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.user_id == ids["owner"])
                )
                == 0
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Activity)
                    .where(
                        Activity.entity_type == "job_automation",
                        Activity.entity_id == ids["job"],
                        Activity.action == "auto_match_proposed",
                    )
                )
                == 1
            )
    finally:
        await _purge_proposals(ids)
        await _cleanup(ids)
