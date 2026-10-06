"""Dopasowania z portali (JJIT/RocketJobs) → „Do przejrzenia” (30.09.2026).

* ``POST /api/jobs/{id}/proposals/bulk`` od tokenu integracji Z ``auto_match``
  zakłada propozycję ``job_board`` zamiast karty na Tablicy; integracja BEZ
  wyniku (np. zgłoszenia z pracuj.pl) i człowiek dodają jak dotąd;
* wbudowany runner JJIT liczy ``proposed`` jako udane dopasowanie;
* jednorazowe przeniesienie starych, nietkniętych kart
  (``services/job_board_cards_to_proposals.py``): próba nic nie zapisuje,
  każdy warunek wyklucza parę, zapis jest idempotentny; od 05.10.2026 także
  karty z pustym ``entry_meta`` i notatką automatu (scraper 30.09–05.10) —
  plakietka z notatki, notatka zostaje.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text

from app.api import proposals_bulk
from app.services import job_board_cards_to_proposals as conversion
from app.services.job_proposals import sanitize_evidence
from app.services.process_entry_meta import auto_match_entry_meta

_META = auto_match_entry_meta(
    score=71.6, source="jjit", must_hit=["Java", "Spring"], must_total=3
)


# ── bez bazy ─────────────────────────────────────────────────────────────────


def test_evidence_keeps_only_numbers_and_requirement_names():
    evidence = proposals_bulk.job_board_evidence(_META)
    clean = sanitize_evidence({**evidence, "cv_quote": "cały akapit z CV"})
    assert clean == {
        "auto_match": {
            "score": 72,
            "source": "jjit",
            "must_hit": ["Java", "Spring"],
            "must_total": 3,
        },
        "matched_must": ["Java", "Spring"],
    }
    assert sanitize_evidence({"auto_match": {"score": True, "x": "y"}}) is None
    assert proposals_bulk.job_board_evidence(None) is None


def test_response_stays_backward_compatible():
    body = proposals_bulk.BulkProposalsResponse(
        added=[], skipped=[], total_added=0, total_skipped=0
    ).model_dump()
    assert body["proposed"] == [] and body["total_proposed"] == 0


class _FakeJobDb:
    def __init__(self) -> None:
        self.commit = AsyncMock()

    async def scalar(self, _stmt):
        return SimpleNamespace(id=5)


def _body(**extra) -> proposals_bulk.BulkProposalsRequest:
    return proposals_bulk.BulkProposalsRequest(candidate_ids=[3, 4], **extra)


@pytest.fixture
def routed(monkeypatch):
    calls: dict[str, list] = {"propose": [], "add": []}

    async def fake_membership(*_a, **_k):
        return None

    async def fake_propose(db, *, job, candidate_ids, entry_meta):
        calls["propose"].append((candidate_ids, entry_meta))
        return proposals_bulk.ProposeResult(
            proposed=[3],
            skipped=[
                proposals_bulk.BulkSkippedRow(candidate_id=4, reason="blacklisted")
            ],
            warnings=[],
        )

    async def fake_add(db, **kwargs):
        calls["add"].append(kwargs)
        return proposals_bulk.IntakeResult(
            added=[], skipped=[], warnings=[], stage_ids={}
        )

    monkeypatch.setattr(proposals_bulk, "ensure_job_membership", fake_membership)
    monkeypatch.setattr(proposals_bulk, "propose_candidates_for_job", fake_propose)
    monkeypatch.setattr(proposals_bulk, "add_candidates_to_job", fake_add)
    return calls


_INTEGRATION = SimpleNamespace(state=SimpleNamespace(oauth_client_id="jjit"))
_HUMAN = SimpleNamespace(state=SimpleNamespace())
_AUTO = {"score": 71.6, "source": "jjit", "must_hit": ["Java"], "must_total": 3}


@pytest.mark.asyncio
async def test_integration_auto_match_becomes_a_proposal(routed):
    resp = await proposals_bulk.bulk_add_proposals(
        request=_INTEGRATION,
        job_id=5,
        body=_body(auto_match=_AUTO, initial_stage_legacy="posting"),
        current_user=SimpleNamespace(id=9),
        db=_FakeJobDb(),
    )
    assert routed["add"] == []
    assert routed["propose"][0][1]["score"] == 72
    assert resp.added == [] and resp.total_added == 0
    assert resp.proposed == [3] and resp.total_proposed == 1
    assert resp.total_skipped == 1


@pytest.mark.asyncio
async def test_integration_without_score_still_adds_a_card(routed):
    await proposals_bulk.bulk_add_proposals(
        request=_INTEGRATION,
        job_id=5,
        body=_body(initial_stage_legacy="posting"),
        current_user=SimpleNamespace(id=9),
        db=_FakeJobDb(),
    )
    assert routed["propose"] == []
    assert routed["add"][0]["entry_source"] == "auto_match"
    # 07.10.2026: karta z integracji nie zamyka propozycji („dodana” = człowiek).
    assert routed["add"][0]["mark_proposals"] is False


@pytest.mark.asyncio
async def test_human_request_ignores_auto_match_and_adds(routed):
    await proposals_bulk.bulk_add_proposals(
        request=_HUMAN,
        job_id=5,
        body=_body(auto_match=_AUTO, source="manual_search"),
        current_user=SimpleNamespace(id=9),
        db=_FakeJobDb(),
    )
    assert routed["propose"] == []
    assert routed["add"][0]["entry_source"] == "added_manual"
    assert routed["add"][0]["mark_proposals"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"added": [], "proposed": [7], "skipped": []}, (True, "")),
        ({"added": [7], "skipped": []}, (True, "")),
        (
            {
                "added": [],
                "proposed": [],
                "skipped": [{"candidate_id": 7, "reason": "already_in_job"}],
            },
            (False, "already_in_job"),
        ),
    ],
)
async def test_jjit_runner_counts_proposed_as_matched(payload, expected):
    from app.services.integrations.jjit.nexus_client import NexusLoopbackClient

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    client = NexusLoopbackClient.__new__(NexusLoopbackClient)

    async def fake_request(method, path, **kwargs):
        return _Resp()

    client._request = fake_request  # type: ignore[method-assign]
    assert await client.add_to_job(3, 7, {"score": 70}) == expected


def test_fk_disqualifiers_skip_self_pointer_and_snapshot_row():
    fks = [
        {
            "tbl": "recruitment_processes",
            "qualified": "public.recruitment_processes",
            "col": "legacy_current_candidate_stage_id",
            "target": "candidate_stages",
        },
        {
            "tbl": "candidate_stage_cvs",
            "qualified": "public.candidate_stage_cvs",
            "col": "candidate_stage_id",
            "target": "candidate_stages",
        },
        {
            "tbl": "cv_qc_runs",
            "qualified": "public.cv_qc_runs",
            "col": "stage_id",
            "target": "candidate_stages",
        },
        {
            "tbl": "recruitment_priority_audit_events",
            "qualified": "public.recruitment_priority_audit_events",
            "col": "process_id",
            "target": "recruitment_processes",
        },
        {
            "tbl": "cv_share_tokens",
            "qualified": "public.cv_share_tokens",
            "col": "stage_cv_id",
            "target": "candidate_stage_cvs",
        },
    ]
    got = dict(conversion.fk_disqualifiers(fks))
    assert set(got) == {
        "fk:cv_qc_runs.stage_id",
        "fk:recruitment_priority_audit_events.process_id",
        "fk:cv_share_tokens.stage_cv_id",
    }
    assert "b.stage_id" in got["fk:cv_qc_runs.stage_id"]
    assert "b.process_id" in got["fk:recruitment_priority_audit_events.process_id"]
    assert "candidate_stage_cvs scv" in got["fk:cv_share_tokens.stage_cv_id"]


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        return None


class _RecordingDb:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.commit = AsyncMock()

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.statements.append(sql)
        if "pg_constraint" in sql:
            return _Result([])
        if "count(*) AS base" in sql:
            n = len(conversion._STATIC_DISQUALIFIERS)
            return _Result([{"base": 4, **{f"c{i}": 1 for i in range(n)}}])
        return _Result(
            [
                {
                    "process_id": 11,
                    "candidate_id": 21,
                    "job_id": 31,
                    "entry_meta": _META,
                    "stage_id": 41,
                }
            ]
        )


@pytest.mark.asyncio
async def test_dry_run_writes_only_its_report():
    db = _RecordingDb()
    report = await conversion.plan(db)
    assert report["qualifying_pairs"] == 1 and report["base_pairs"] == 4
    assert report["qualifying_from_automatch_notes"] == 0
    assert report["per_job"] == [{"job_id": 31, "pairs": 1}]
    assert report["samples"] == [
        {"candidate_id": 21, "job_id": 31, "process_id": 11, "stage_id": 41}
    ]
    assert set(report["blocked_by"]) == {r for r, _ in conversion._STATIC_DISQUALIFIERS}
    writes = [
        s
        for s in db.statements
        if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert writes == []

    await conversion.finish_run(db, report, started=datetime.now(timezone.utc))
    writes = [s for s in db.statements if "INSERT INTO app_settings" in s]
    assert len(writes) == 1


def test_qualifying_sql_carries_every_rule():
    sql = conversion.qualifying_sql(
        list(conversion._STATIC_DISQUALIFIERS), one_pair=True
    )
    for needle in (
        "entry_source = 'auto_match'",
        "rp.status = 'open'",
        "IS DISTINCT FROM 'nexus'",
        "IS DISTINCT FROM 'traffit'",
        "c3.stage = 'posting'",
        "FROM notes nt",
        "FROM application_screenings aps",
        "FROM screening_notes sn",
        "branded_status = 'none'",
        "base.process_id = :process_id",
        "oauth_clients oc",
        "COALESCE(nt.kind = 'automatch', false)",
        "strpos(an.content, 'Auto-match score:')",
        "b.automatch_note_ids",
    ):
        assert needle in sql


_PRACUJ_NOTE = (
    "Źródło: Pracuj.pl — oferta: Programista Python\n"
    "Auto-match score: 71/100 (Jan Testowy)\n"
    "Must-have trafione: Python, Django"
)


def test_entry_meta_from_scraper_note():
    assert conversion.entry_meta_from_note(_PRACUJ_NOTE) == auto_match_entry_meta(
        score=71, source="pracuj", must_hit=["Python", "Django"], must_total=None
    )
    jjit = conversion.entry_meta_from_note(
        "<p>Źródło: RocketJobs/JJIT — oferta: X</p>"
        "<p>Auto-match score: 63,5/100 (A B)</p><p>Must-have trafione: —</p>"
    )
    assert jjit["source"] == "jjit" and jjit["score"] == 64
    assert jjit["must_hit"] == [] and jjit["must_total"] is None
    assert conversion.entry_meta_from_note("Auto-match score: ?/100") is None
    assert conversion.entry_meta_from_note(None) is None


def test_process_badge_wins_over_note():
    assert (
        conversion.effective_entry_meta(
            {"entry_meta": _META, "automatch_note": _PRACUJ_NOTE}
        )
        == _META
    )
    from_note = conversion.effective_entry_meta(
        {"entry_meta": {}, "automatch_note": _PRACUJ_NOTE}
    )
    assert from_note["source"] == "pracuj"
    assert conversion.effective_entry_meta({"entry_meta": None}) is None


# ── z bazą (CI) ──────────────────────────────────────────────────────────────


async def _seed_admin() -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"jb-admin-{unique}@example.com",
            password_hash=hash_password(f"T3st_{unique}!"),
            name=f"JB Admin {unique}",
            role=UserRole.admin,
            roles=[UserRole.admin.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _seed_job(**job_fields) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"JBClient-{unique}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"JB Rola {unique}",
            status=job_fields.pop("status", JobStatus.published),
            client_id=cli.id,
            **job_fields,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Candidate(name=f"JB{unique}", lastname="Portal", email=f"{unique}@jb.pl")
        db.add(c)
        await db.commit()
        return c.id


async def _seed_card(
    job_id: int, candidate_id: int, actor_id: int, entry_meta: object = _META
) -> int:
    """Karta jak od starej integracji: „Ogłoszenia”, auto_match, z wynikiem."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.recruitment_process import RecruitmentProcess

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        result = await proposals_bulk.add_candidates_to_job(
            db,
            job=job,
            candidate_ids=[candidate_id],
            actor_user_id=actor_id,
            initial_stage_legacy="posting",
            entry_source="auto_match",
            claim=False,
            entry_meta=entry_meta,
        )
        assert result.added == [candidate_id]
        await db.commit()
        return await db.scalar(
            select(RecruitmentProcess.id).where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
        )


async def _qualifies(process_id: int) -> bool:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        rules = await conversion.load_disqualifiers(db)
        row = (
            await db.execute(
                text(conversion.qualifying_sql(rules, one_pair=True)),
                {"process_id": process_id},
            )
        ).first()
        return row is not None


async def _seed_integration_user() -> int:
    """Użytkownik serwisowy klienta OAuth (jak scraper pracuj.pl + JJIT)."""
    from app.core.database import AsyncSessionLocal
    from app.models.oauth_client import OAuthClient
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"jb-scraper-{unique}@example.com",
            password_hash="!no-login!",
            name=f"JB Scraper {unique}",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
        )
        db.add(user)
        await db.flush()
        db.add(
            OAuthClient(
                name=f"JB scraper {unique}",
                client_id=f"jb-scraper-{unique}",
                secret_hash="!test-no-secret!",
                scopes=["candidate:write"],
                enabled=True,
                acting_user_id=user.id,
            )
        )
        await db.commit()
        return user.id


async def _add_note(
    cand_id: int, job_id: int, author_id: int, content: str, kind: str
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note, NoteType

    async with AsyncSessionLocal() as db:
        note = Note(
            content=content,
            note_type=NoteType.general,
            candidate_id=cand_id,
            job_id=job_id,
            author_id=author_id,
            kind=kind,
            external_source="system",
        )
        db.add(note)
        await db.commit()
        return note.id


async def _scraper_world(
    note: str = _PRACUJ_NOTE,
) -> tuple[int, int, int, int, int, int]:
    """Karta bez plakietki (puste ``entry_meta``) + notatka automatu scrapera."""
    actor = await _seed_admin()
    scraper = await _seed_integration_user()
    job_id = await _seed_job()
    cand_id = await _seed_candidate()
    process_id = await _seed_card(job_id, cand_id, scraper, entry_meta=None)
    note_id = await _add_note(cand_id, job_id, scraper, note, "automatch")
    return actor, scraper, job_id, cand_id, process_id, note_id


async def _blocked_reasons(process_id: int) -> set[str]:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        rules = await conversion.load_disqualifiers(db)
        columns = ", ".join(f"({pred}) AS c{i}" for i, (_, pred) in enumerate(rules))
        row = (
            (
                await db.execute(
                    text(
                        f"SELECT {columns} FROM ({conversion._BASE_SQL}) b "
                        "WHERE b.process_id = :p"
                    ),
                    {"p": process_id},
                )
            )
            .mappings()
            .one()
        )
        return {reason for i, (reason, _) in enumerate(rules) if row[f"c{i}"]}


async def _world(**job_fields) -> tuple[int, int, int, int]:
    actor = await _seed_admin()
    job_id = await _seed_job(**job_fields)
    cand_id = await _seed_candidate()
    process_id = await _seed_card(job_id, cand_id, actor)
    return actor, job_id, cand_id, process_id


@pytest.mark.asyncio
async def test_untouched_card_qualifies_and_moves_once(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_stage_removal import CandidateStageRemoval
    from app.models.job_proposal import JobProposal
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
    from app.models.user import User

    actor_id, job_id, cand_id, process_id = await _world()
    assert await _qualifies(process_id)

    async with AsyncSessionLocal() as db:
        actor = await db.get(User, actor_id)
        report = await conversion.apply(db, actor=actor, only_process_ids={process_id})
    assert report["counts"]["moved"] == 1, report

    async with AsyncSessionLocal() as db:
        stages = (
            await db.scalars(
                select(CandidateStage).where(
                    CandidateStage.candidate_id == cand_id,
                    CandidateStage.job_id == job_id,
                )
            )
        ).all()
        assert stages == []
        process = await db.get(RecruitmentProcess, process_id)
        assert process.status == ProcessStatus.voided
        proposal = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id,
                JobProposal.candidate_id == cand_id,
                JobProposal.source == "job_board",
            )
        )
        assert proposal is not None and proposal.status == "proposed"
        assert float(proposal.score) == 72.0
        assert proposal.evidence["auto_match"]["source"] == "jjit"
        removal = await db.scalar(
            select(CandidateStageRemoval).where(
                CandidateStageRemoval.candidate_id == cand_id,
                CandidateStageRemoval.job_id == job_id,
            )
        )
        assert removal.reason == conversion.REMOVAL_REASON
        actor = await db.get(User, actor_id)
        again = await conversion.apply(db, actor=actor, only_process_ids={process_id})
    assert again["targets"] == 0 and again["counts"]["moved"] == 0


@pytest.mark.asyncio
async def test_note_on_the_job_disqualifies(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note, NoteType

    actor_id, job_id, cand_id, process_id = await _world()
    async with AsyncSessionLocal() as db:
        db.add(
            Note(
                content="dzwoniłam",
                note_type=NoteType.general,
                candidate_id=cand_id,
                job_id=job_id,
                author_id=actor_id,
            )
        )
        await db.commit()
    assert not await _qualifies(process_id)


@pytest.mark.asyncio
async def test_traffit_job_disqualifies(app_client):
    _, _, _, process_id = await _world(
        external_source="traffit", external_id=f"t-{uuid.uuid4().hex[:8]}"
    )
    assert not await _qualifies(process_id)


@pytest.mark.asyncio
async def test_unpublished_job_disqualifies(app_client):
    from app.core.database import AsyncSessionLocal

    _, job_id, _, process_id = await _world()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE jobs SET status = 'closed' WHERE id = :id"), {"id": job_id}
        )
        await db.commit()
    assert not await _qualifies(process_id)


@pytest.mark.asyncio
async def test_second_stage_row_disqualifies(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    _, job_id, cand_id, process_id = await _world()
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=cand_id,
                job_id=job_id,
                stage=PipelineStage.new,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    assert not await _qualifies(process_id)


@pytest.mark.asyncio
async def test_screening_answers_disqualify(app_client):
    from app.core.database import AsyncSessionLocal

    _, job_id, cand_id, process_id = await _world()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE candidate_stages SET screening_answers = "
                "CAST(:a AS jsonb) WHERE candidate_id = :c AND job_id = :j"
            ),
            {"a": '{"answers": [{"q": 1}]}', "c": cand_id, "j": job_id},
        )
        await db.commit()
    assert not await _qualifies(process_id)


@pytest.mark.asyncio
async def test_started_company_cv_disqualifies(app_client):
    from app.core.database import AsyncSessionLocal

    _, job_id, cand_id, process_id = await _world()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                UPDATE candidate_stage_cvs SET branded_status = 'draft',
                       branded_draft_html = '<p>x</p>'
                WHERE candidate_id = :c AND job_id = :j
                """
            ),
            {"c": cand_id, "j": job_id},
        )
        await db.commit()
    assert not await _qualifies(process_id)


@pytest.mark.asyncio
async def test_application_screening_disqualifies(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.application_screening import ApplicationScreening

    _, job_id, cand_id, process_id = await _world()
    async with AsyncSessionLocal() as db:
        db.add(ApplicationScreening(candidate_id=cand_id, job_id=job_id))
        await db.commit()
    assert not await _qualifies(process_id)


@pytest.mark.asyncio
async def test_card_without_integration_score_is_left_alone(app_client):
    from app.core.database import AsyncSessionLocal

    _, _, _, process_id = await _world()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE recruitment_processes SET entry_meta = NULL WHERE id = :p"),
            {"p": process_id},
        )
        await db.commit()
    assert not await _qualifies(process_id)


@pytest.mark.asyncio
async def test_scraper_card_without_badge_moves_with_score_from_note(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.job_proposal import JobProposal
    from app.models.note import Note
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
    from app.models.user import User

    actor_id, _, job_id, cand_id, process_id, note_id = await _scraper_world()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE recruitment_processes SET entry_meta = CAST('{}' AS jsonb) "
                "WHERE id = :p"
            ),
            {"p": process_id},
        )
        await db.commit()
    assert await _qualifies(process_id)

    async with AsyncSessionLocal() as db:
        actor = await db.get(User, actor_id)
        report = await conversion.apply(db, actor=actor, only_process_ids={process_id})
    assert report["counts"]["moved"] == 1, report

    async with AsyncSessionLocal() as db:
        process = await db.get(RecruitmentProcess, process_id)
        assert process.status == ProcessStatus.voided
        proposal = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id,
                JobProposal.candidate_id == cand_id,
                JobProposal.source == "job_board",
            )
        )
        assert proposal is not None and proposal.status == "proposed"
        assert float(proposal.score) == 71.0
        assert proposal.evidence["auto_match"]["source"] == "pracuj"
        assert proposal.evidence["matched_must"] == ["Python", "Django"]
        # Nic nie znika: notatka automatu zostaje, jej id jest w danych odwrócenia.
        assert await db.get(Note, note_id) is not None
        details = await db.scalar(
            text("SELECT value FROM app_settings WHERE key = :k"),
            {"k": conversion.DETAILS_KEY},
        )
        moved = [e for e in details["moved"] if e["process_id"] == process_id]
        assert moved and moved[0]["automatch_note_ids"] == [note_id]
        assert moved[0]["original_entry_meta"] == {}


@pytest.mark.asyncio
async def test_scraper_card_with_application_form_note_stays(app_client):
    _, scraper, job_id, cand_id, process_id, _ = await _scraper_world()
    await _add_note(
        cand_id, job_id, scraper, "Formularz aplikacyjny pracuj.pl", "application_form"
    )
    assert not await _qualifies(process_id)
    assert "notes" in await _blocked_reasons(process_id)


@pytest.mark.asyncio
async def test_application_card_without_automatch_note_is_not_in_base(app_client):
    scraper = await _seed_integration_user()
    job_id = await _seed_job()
    cand_id = await _seed_candidate()
    process_id = await _seed_card(job_id, cand_id, scraper, entry_meta=None)
    await _add_note(
        cand_id, job_id, scraper, "Formularz aplikacyjny pracuj.pl", "application_form"
    )
    assert not await _qualifies(process_id)


@pytest.mark.asyncio
async def test_scraper_card_with_human_note_stays(app_client):
    actor, _, job_id, cand_id, process_id, _ = await _scraper_world()
    await _add_note(cand_id, job_id, actor, "dzwoniłam, oddzwoni", "human")
    assert not await _qualifies(process_id)
    assert "notes" in await _blocked_reasons(process_id)


@pytest.mark.asyncio
async def test_scraper_note_without_score_is_skipped_with_reason(app_client):
    _, _, _, _, process_id, _ = await _scraper_world(
        note="Źródło: Pracuj.pl — oferta: X\nAuto-match score: brak (Jan Testowy)"
    )
    assert not await _qualifies(process_id)
    reasons = await _blocked_reasons(process_id)
    assert "automatch_note_unreadable" in reasons
    assert "notes" not in reasons


@pytest.mark.asyncio
async def test_propose_path_writes_a_job_board_proposal_and_no_card(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.job_proposal import JobProposal
    from app.models.recruitment_pipeline import CandidateStage

    job_id = await _seed_job()
    cand_id = await _seed_candidate()
    missing = cand_id + 10_000_000
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        result = await proposals_bulk.propose_candidates_for_job(
            db, job=job, candidate_ids=[cand_id, missing], entry_meta=_META
        )
        await db.commit()
    assert result.proposed == [cand_id]
    assert [s.reason for s in result.skipped] == ["candidate_not_found"]

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage.id).where(
                CandidateStage.candidate_id == cand_id,
                CandidateStage.job_id == job_id,
            )
        )
        assert stage is None
        proposal = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id, JobProposal.candidate_id == cand_id
            )
        )
        assert proposal.source == "job_board"
        assert proposal.status == "proposed"
        assert proposal.cv_revision
