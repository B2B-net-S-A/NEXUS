"""Runda 4 audytu (25.09.2026) — obszar rekrutacji.

Cpro (kto ustawia osobę, martwe konto), przydział requestów (nieaktywne
konta, zdjęcie rekrutera automatu), tytuł dla rekrutera po zapisach
Championa spoza edytora, QC CV (role bez daty końca), follow-upy (skrót dla
admina/HoR, poczta głosowa), ocena prepu (archiwum pytań), portale (zmiana
treści w trakcie wysyłki, niepewna publikacja) i generate-upload (klient
przed płatnym podglądem Championa).

Testy bez bazy idą lokalnie; oznaczone ``db`` w nazwie wymagają PostgreSQL
(CI).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.models.user import User, UserRole
from app.services import cpro_sender
from app.services.cpro_sender import CproSenderState
from app.services.request_allocation_plan import (
    RELEASE_REASONS,
    LiveAssignment,
    PersonInfo,
    PlanInput,
    RequestInfo,
    plan_assignments,
)

NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)


# ── R4-1: kto ustawia osobę od Cpro ─────────────────────────────────────────


def _user(*roles: UserRole, user_id: int = 7) -> User:
    return User(
        id=user_id, role=roles[0], roles=[r.value for r in roles], is_active=True
    )


@pytest.mark.asyncio
async def test_admin_can_set_the_cpro_sender_without_a_portfolio() -> None:
    assert await cpro_sender.can_set_sender(AsyncMock(), _user(UserRole.admin))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles",
    [
        (UserRole.recruiter,),
        (UserRole.sourcer,),
        (UserRole.head_of_recruitment,),
        (UserRole.talent_community_manager,),
    ],
)
async def test_team_roles_cannot_set_the_cpro_sender(roles) -> None:
    assert not await cpro_sender.can_set_sender(AsyncMock(), _user(*roles))


@pytest.mark.asyncio
async def test_only_a_delivery_lead_of_nordea_can_set_the_sender(monkeypatch) -> None:
    from app.services import access_scope

    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "901")
    portfolio: dict[int, frozenset[int]] = {1: frozenset({901, 5}), 2: frozenset({5})}

    async def assigned(user, db):
        return portfolio[user.id]

    monkeypatch.setattr(
        access_scope, "resolve_delivery_lead_assigned_client_ids", assigned
    )
    nordea_dl = _user(UserRole.delivery_lead, user_id=1)
    other_dl = _user(UserRole.delivery_lead, user_id=2)
    assert await cpro_sender.can_set_sender(AsyncMock(), nordea_dl)
    assert not await cpro_sender.can_set_sender(AsyncMock(), other_dl)


@pytest.mark.asyncio
async def test_put_sender_refuses_other_roles_with_polish_403(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.api import board_tasks as api

    async def cannot(db, user):
        return False

    monkeypatch.setattr(cpro_sender, "can_set_sender", cannot)
    set_sender = AsyncMock()
    monkeypatch.setattr(cpro_sender, "set_sender", set_sender)
    with pytest.raises(HTTPException) as refused:
        await api.set_cpro_sender(
            api.CproSenderUpdate(user_id=7),
            _user(UserRole.recruiter),
            db=AsyncMock(),
        )
    assert refused.value.status_code == 403
    assert refused.value.detail == cpro_sender.SET_SENDER_FORBIDDEN
    assert "Delivery Lead" in refused.value.detail
    set_sender.assert_not_awaited()


# ── R4-18: martwe konto nie jest osobą od Cpro ─────────────────────────────


def _patch_state(monkeypatch, state: CproSenderState, active: set[int]) -> None:
    async def load(db, *, for_update=False):
        return state

    async def active_ids(db, ids):
        return {i for i in ids if i in active}

    monkeypatch.setattr(cpro_sender, "load_state", load)
    monkeypatch.setattr(cpro_sender, "active_user_ids", active_ids)


@pytest.mark.asyncio
async def test_inactive_firm_sender_reads_as_nobody(monkeypatch) -> None:
    _patch_state(monkeypatch, CproSenderState(user_id=7), active=set())
    state = await cpro_sender.effective_sender(AsyncMock(), NOW)
    assert state.user_id is None


@pytest.mark.asyncio
async def test_inactive_person_returning_after_substitution_reads_as_nobody(
    monkeypatch,
) -> None:
    # Zastępstwo minęło wczoraj, wraca osoba 4 — jej konto jest już nieaktywne.
    expired = CproSenderState(user_id=7, until=date(2026, 9, 24), fallback_user_id=4)
    _patch_state(monkeypatch, expired, active={7})
    assert (await cpro_sender.effective_sender(AsyncMock(), NOW)).user_id is None
    _patch_state(monkeypatch, expired, active={4})
    assert (await cpro_sender.effective_sender(AsyncMock(), NOW)).user_id == 4


@pytest.mark.asyncio
async def test_inactive_fallback_is_not_announced(monkeypatch) -> None:
    current = CproSenderState(user_id=7, until=date(2026, 10, 3), fallback_user_id=4)
    _patch_state(monkeypatch, current, active={7})
    state = await cpro_sender.effective_sender(AsyncMock(), NOW)
    assert state.user_id == 7 and state.fallback_user_id is None


def test_without_a_live_sender_admin_and_hor_see_the_queue() -> None:
    from app.services import board_tasks as svc

    task = svc.BoardTask(
        kind=svc.KIND_CPRO_TO_SEND,
        stage_id=1,
        candidate_id=2,
        candidate_name="Anna",
        job_id=3,
        job_title="Java",
        client_id=None,
        client_name=None,
        since=NOW,
        process_state_version=0,
        target_stage_def_id=None,
    )
    snapshot = svc.BoardTaskSnapshot(tasks=[task], firm_sender_id=None)
    for role in (UserRole.admin, UserRole.head_of_recruitment):
        mine = svc.tasks_for_user(snapshot, _user(role), portfolio=frozenset())
        assert mine[svc.KIND_CPRO_TO_SEND] == [task]


def test_fallback_senders_of_the_job_must_be_active_accounts() -> None:
    from app.services import board_tasks as svc

    sql = str(svc._LATEST_SQL)  # noqa: SLF001
    assert "CASE WHEN ta.is_active THEN l.task_assignee_id END" in sql
    assert "CASE WHEN js.is_active THEN j.cpro_sender_id END" in sql


def test_substitution_for_the_permanent_sender_keeps_them_afterwards() -> None:
    state = cpro_sender.next_state(
        CproSenderState(user_id=4),
        user_id=4,
        until=date(2026, 9, 30),
        actor_id=1,
        today=date(2026, 9, 25),
        now=NOW,
    )
    assert state.fallback_user_id == 4
    after = cpro_sender.effective(state, date(2026, 10, 1))
    assert after.user_id == 4


# ── R4-2: nieaktywne konto zwalnia przypisania ─────────────────────────────


def _request(job_id: int = 10) -> RequestInfo:
    return RequestInfo(
        job_id=job_id,
        categories=frozenset({2}),
        primary_category=2,
        sent=0,
        deadline=None,
        base_matches=None,
    )


def _recruiter(user_id: int) -> PersonInfo:
    return PersonInfo(
        user_id=user_id,
        can_recruit=True,
        can_source=False,
        first=frozenset({2}),
        second=frozenset(),
    )


@pytest.mark.parametrize(
    "source,in_process",
    [("manual", False), ("manual", True), ("auto", True), ("owner", False)],
)
def test_inactive_account_releases_every_assignment(source, in_process) -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[_request()],
            people=[_recruiter(2)],
            live=[
                LiveAssignment(
                    job_id=10,
                    user_id=1,
                    role="recruiter",
                    source=source,
                    state="active",
                    in_process=in_process,
                )
            ],
            mode="auto",
            inactive_ids=frozenset({1}),
        )
    )
    released = [c for c in changes if c.kind == "release"]
    assert [(c.user_id, c.reason) for c in released] == [(1, "inactive")]
    # Request nie jest już „pokryty” martwym kontem — dostaje żywą osobę.
    assert [(c.job_id, c.user_id) for c in changes if c.kind == "assign"] == [(10, 2)]
    assert RELEASE_REASONS["inactive"]


def test_active_manual_assignment_stays_without_the_inactive_flag() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[_request()],
            people=[_recruiter(2)],
            live=[
                LiveAssignment(
                    job_id=10,
                    user_id=1,
                    role="recruiter",
                    source="manual",
                    state="active",
                )
            ],
            mode="auto",
        )
    )
    assert changes == []


def test_nobody_working_filter_counts_only_active_accounts() -> None:
    from app.api.jobs import jobs_nobody_working_clause

    sql = str(jobs_nobody_working_clause())
    assert "users.is_active" in sql


def test_inactive_release_clears_the_owner_set_by_the_automat() -> None:
    from app.services.request_allocation import AUTO_RELEASE_REASONS

    assert "inactive" in AUTO_RELEASE_REASONS


# ── R4-4: ręczne zdjęcie rekrutera automatu zdejmuje prowadzącego ───────────


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row,clears",
    [
        (SimpleNamespace(source="auto", role="recruiter", state="active"), True),
        (SimpleNamespace(source="auto", role="recruiter", state="proposed"), False),
        (SimpleNamespace(source="auto", role="sourcer", state="active"), False),
        (SimpleNamespace(source="manual", role="recruiter", state="active"), False),
        (SimpleNamespace(source="owner", role="recruiter", state="active"), False),
    ],
)
async def test_manual_remove_clears_only_the_automat_owner(
    monkeypatch, row, clears
) -> None:
    from app.services import request_allocation

    db = AsyncMock()
    db.execute.side_effect = [_Rows([row]), None]
    cleared = AsyncMock()
    monkeypatch.setattr(request_allocation, "_clear_auto_owner", cleared)
    assert await request_allocation.manual_remove(db, job_id=10, user_id=1)
    assert cleared.await_count == (1 if clears else 0)


@pytest.mark.asyncio
async def test_manual_remove_without_live_row_changes_nothing(monkeypatch) -> None:
    from app.services import request_allocation

    db = AsyncMock()
    db.execute.side_effect = [_Rows([])]
    cleared = AsyncMock()
    monkeypatch.setattr(request_allocation, "_clear_auto_owner", cleared)
    assert not await request_allocation.manual_remove(db, job_id=10, user_id=1)
    assert db.execute.await_count == 1
    cleared.assert_not_awaited()


# ── R4-19: QC CV — rola bez daty końca dalej niż na 1. pozycji ──────────────


def test_qc_years_treat_blank_end_after_the_first_role_as_unknown() -> None:
    from app.services import cv_qc as qc

    # Profil z opisu audytu: najnowsza rola trwa, starsza nie ma daty końca.
    history = [
        {"company": "Bank", "start": "2023-01", "end": None},
        {"company": "Software house", "start": "2012-03", "end": ""},
    ]
    assert qc.experience_years(history, today=date(2026, 9, 25)) is None


def test_qc_years_first_role_without_end_is_ongoing() -> None:
    from app.services import cv_qc as qc

    history = [
        {"company": "Bank", "start": "2021-01", "end": ""},
        {"company": "Software house", "start": "2016-01", "end": "2020-12"},
    ]
    years = qc.experience_years(history, today=date(2026, 1, 15))
    assert years is not None and int(years) == 10


def test_qc_years_unreadable_end_is_unknown() -> None:
    from app.services import cv_qc as qc

    history = [{"company": "Bank", "start": "2021-01", "end": "wkrótce"}]
    assert qc.experience_years(history, today=date(2026, 1, 15)) is None


def test_qc_years_dates_string_without_end_after_first_role_is_unknown() -> None:
    from app.services import cv_qc as qc

    history = [
        {"company": "Bank", "dates": "2021-01 – obecnie"},
        {"company": "Software house", "dates": "2012-03"},
    ]
    assert qc.experience_years(history, today=date(2026, 1, 15)) is None


# ── R4-20 + niskie: follow-upy ──────────────────────────────────────────────


def _followup(caller_id, due_on: date):
    return SimpleNamespace(caller_id=caller_id, due_on=due_on)


def test_followups_without_caller_reach_admin_and_hor_digest() -> None:
    from app.services import candidate_followups as svc

    today = date(2026, 9, 25)
    counts = svc.digest_counts(
        {
            1: _followup(None, today - timedelta(days=1)),
            2: _followup(None, today),
            3: _followup(5, today),
            4: _followup(None, today + timedelta(days=2)),
        },
        today=today,
        oversight_ids=[10, 11],
    )
    assert (counts[10].due, counts[10].overdue) == (2, 1)
    assert (counts[11].due, counts[11].overdue) == (2, 1)
    assert counts[5].due == 1
    # Bez listy nadzoru (stare wywołanie) — jak dotąd tylko dzwoniący.
    assert set(svc.digest_counts({3: _followup(5, today)}, today=today)) == {5}


def test_voicemail_is_not_contact_with_the_candidate() -> None:
    from app.models.call import CallStatus
    from app.services import candidate_followups as svc

    assert CallStatus.voicemail in svc._FAILED_CALLS  # noqa: SLF001


# ── R4-7: pytania z archiwum nie są punktami oceny prepu ────────────────────


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_prep_review_skips_archive_pins_added_without_a_human(
    monkeypatch,
) -> None:
    from app.models.interview_question import InterviewQuestionSource
    from app.services import dz_review, prep_review

    monkeypatch.setattr(dz_review, "job_requirements", lambda job: ([], []))

    def question(qid, source):
        return SimpleNamespace(id=qid, text=f"Pytanie {qid}?", source=source)

    links = [
        # Import archiwum — bez człowieka: pomijane.
        SimpleNamespace(
            question=question(1, InterviewQuestionSource.legacy_import),
            added_by_user_id=None,
        ),
        # To samo archiwum, ale przypięte ręcznie — liczy się.
        SimpleNamespace(
            question=question(2, InterviewQuestionSource.legacy_import),
            added_by_user_id=9,
        ),
        # Zwykłe przypięte pytanie — liczy się.
        SimpleNamespace(
            question=question(3, InterviewQuestionSource.client_debrief),
            added_by_user_id=None,
        ),
    ]
    db = AsyncMock()
    db.execute.return_value = _Scalars(links)
    db.scalars.return_value = _Scalars([])
    job = SimpleNamespace(id=1, client_id=None)
    items = await prep_review.build_items(db, job)
    assert [i.key for i in items] == ["q:2", "q:3"]


# ── R4-5 / R4-6: portale ────────────────────────────────────────────────────


def _posting(status=PostingStatus.published, pending=None, attempts=0) -> JobPosting:
    return JobPosting(
        job_id=1,
        portal=Portal.rocketjobs,
        status=status,
        attempts=attempts,
        pending_action=pending,
        options={"city": "Warszawa"},
    )


def _ok():
    from app.services.job_portals import service

    return service._Outcome(  # noqa: SLF001
        "ok", result=SimpleNamespace(external_id="E1", url=None, extra={})
    )


def test_publish_success_with_options_changed_in_flight_keeps_an_update() -> None:
    from app.services.job_portals import service

    posting = _posting(PostingStatus.publishing, pending=service.ACTION_PUBLISH)
    service._apply(  # noqa: SLF001
        posting, service.ACTION_PUBLISH, _ok(), changed=True, stale_content=True
    )
    assert posting.status == PostingStatus.published
    assert posting.pending_action == service.ACTION_UPDATE
    assert posting.next_attempt_at is None and posting.attempts == 0


def test_update_success_with_new_approval_in_flight_keeps_an_update() -> None:
    from app.services.job_portals import service

    posting = _posting(pending=service.ACTION_UPDATE)
    # Zatwierdzenie opisu nie zmienia `pending_action` (już było `update`).
    service._apply(  # noqa: SLF001
        posting, service.ACTION_UPDATE, _ok(), changed=False, stale_content=True
    )
    assert posting.pending_action == service.ACTION_UPDATE


def test_update_success_without_changes_clears_the_order() -> None:
    from app.services.job_portals import service

    posting = _posting(pending=service.ACTION_UPDATE)
    service._apply(  # noqa: SLF001
        posting, service.ACTION_UPDATE, _ok(), changed=False, stale_content=False
    )
    assert posting.pending_action is None


def test_close_queued_in_flight_wins_over_stale_content() -> None:
    from app.services.job_portals import service

    posting = _posting(PostingStatus.publishing, pending=service.ACTION_CLOSE)
    service._apply(  # noqa: SLF001
        posting, service.ACTION_PUBLISH, _ok(), changed=True, stale_content=True
    )
    assert posting.pending_action == service.ACTION_CLOSE


def test_failed_update_with_new_content_is_tried_again() -> None:
    from app.services.job_portals import service

    posting = _posting(pending=service.ACTION_UPDATE)
    refused = service._Outcome("give_up", "Portal odrzucił treść.")  # noqa: SLF001
    service._apply(  # noqa: SLF001
        posting, service.ACTION_UPDATE, refused, changed=False, stale_content=True
    )
    assert posting.pending_action == service.ACTION_UPDATE
    assert posting.attempts == 0


def test_certain_refusal_after_an_earlier_attempt_queues_cleanup() -> None:
    from app.services.job_portals import service

    # Próba 1 skończyła się timeoutem (ponowienie), próba 2 — pewną odmową.
    posting = _posting(
        PostingStatus.publishing, pending=service.ACTION_PUBLISH, attempts=1
    )
    refused = service._Outcome("give_up", "Opis wrócił do szkicu.")  # noqa: SLF001
    service._apply(  # noqa: SLF001
        posting, service.ACTION_PUBLISH, refused, changed=False
    )
    assert posting.status == PostingStatus.failed
    assert posting.pending_action == service.ACTION_CLOSE


def test_certain_refusal_on_the_first_attempt_does_not_queue_cleanup() -> None:
    from app.services.job_portals import service

    posting = _posting(
        PostingStatus.publishing, pending=service.ACTION_PUBLISH, attempts=0
    )
    refused = service._Outcome("give_up", "Opis wrócił do szkicu.")  # noqa: SLF001
    service._apply(  # noqa: SLF001
        posting, service.ACTION_PUBLISH, refused, changed=False
    )
    assert posting.status == PostingStatus.failed
    assert posting.pending_action is None


@pytest.mark.asyncio
async def test_content_update_counts_rows_with_update_already_in_flight() -> None:
    from app.services.job_portals import service

    queued = _posting(pending=service.ACTION_UPDATE)
    queued.next_attempt_at = NOW + timedelta(minutes=10)  # dzierżawa workera
    idle = _posting(pending=None)
    db = AsyncMock()
    db.scalars.return_value = _Scalars([queued, idle])
    assert await service.queue_content_update(db, 1) == 2
    # Dzierżawa w toku nietknięta — drugi tick nie weźmie tego samego wiersza.
    assert queued.next_attempt_at == NOW + timedelta(minutes=10)
    assert idle.pending_action == service.ACTION_UPDATE


# ── R4-28: klient przed płatnym podglądem Championa ────────────────────────


@pytest.mark.asyncio
async def test_upload_without_client_refuses_before_the_paid_champion_preview(
    monkeypatch,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.api import champion_intake as champion_api
    from tests.test_audit_r3_recruitment import _docx_bytes, _upload_app

    app, _db, charge, pending = _upload_app(monkeypatch)
    preview = AsyncMock(side_effect=AssertionError("podgląd AI nie może ruszyć"))
    monkeypatch.setattr(champion_api, "read_preview", preview)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/cv-generator/generate-upload",
            data={"content_mode": "tailored"},
            files={
                "cv_file": ("CV.docx", _docx_bytes()),
                "champion_file": ("Champion.docx", _docx_bytes("MUST: Python")),
            },
        )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Wybierz klienta, dla którego powstaje CV."
    preview.assert_not_awaited()
    charge.assert_not_awaited()
    pending.assert_not_awaited()


# ── R4-3: tytuł dla rekrutera po zapisach Championa spoza edytora ───────────


class _JobResult:
    def __init__(self, job):
        self._job = job

    def scalar_one_or_none(self):
        return self._job


@pytest.mark.asyncio
async def test_ingest_refreshes_the_working_title(monkeypatch) -> None:
    from app.services import (
        champion_profile_ingest,
        index_outbox_service,
        job_working_title,
        match_score_cache,
    )

    job = SimpleNamespace(
        id=5,
        champion_profile=None,
        must_skills=[],
        nice_skills=[],
        working_title_auto=True,
    )
    db = AsyncMock()
    db.execute.return_value = _JobResult(job)
    refreshed = AsyncMock(return_value=True)
    monkeypatch.setattr(job_working_title, "refresh_working_title", refreshed)
    monkeypatch.setattr(index_outbox_service, "record_bulk_reindex", AsyncMock())
    monkeypatch.setattr(match_score_cache, "mark_stale_for_job", AsyncMock())
    from app.services import requirement_contract

    def apply(job_, field, value):
        setattr(job_, field, value)

    monkeypatch.setattr(requirement_contract, "apply_requirement_source_update", apply)
    monkeypatch.setattr(
        champion_profile_ingest, "fill_job_columns_from_champion", lambda *a: []
    )
    outcome = await champion_profile_ingest.ingest_parsed_profile(
        db,
        external_rid=123,
        file_id=9,
        parsed={"stack": {"must": [{"name": "Kotlin"}]}},
        commit=False,
    )
    assert outcome["must_written"] is True
    refreshed.assert_awaited_once_with(db, job)


@pytest.mark.asyncio
async def test_db_apply_suggestion_refreshes_the_working_title(
    app_client, app_auth_headers
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.champion_suggestion import (
        ChampionProfileSuggestion,
        SuggestionSource,
        SuggestionStatus,
    )
    from app.models.job import Job
    from app.services.champion_draft_service import apply_suggestion

    me = await app_client.get("/api/auth/me", headers=app_auth_headers)
    assert me.status_code == 200, me.text
    created = await app_client.post(
        "/api/jobs",
        json={
            "title": f"Programista R4 {uuid.uuid4().hex[:6]}",
            "must_skills": ["Java"],
        },
        headers=app_auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    job_id = created.json()["id"]
    async with AsyncSessionLocal() as db:
        suggestion = ChampionProfileSuggestion(
            job_id=job_id,
            source_type=SuggestionSource.jd_paste,
            payload={"basics": {"value": {"role_name": "Kotlin Developer"}}},
            status=SuggestionStatus.pending,
        )
        db.add(suggestion)
        await db.commit()
        suggestion_id = suggestion.id
    async with AsyncSessionLocal() as db:
        await apply_suggestion(
            db,
            suggestion_id=suggestion_id,
            accepted_sections=["basics"],
            user_id=me.json()["id"],
        )
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.working_title.startswith("Kotlin Developer")


# ── R4-2 / R4-4 na bazie ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_db_inactive_account_is_not_work_and_manual_remove_clears_auto_owner(
    app_client,
) -> None:
    from sqlalchemy import select

    from app.api.jobs import jobs_nobody_working_clause
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.job_work_assignment import JobWorkAssignment
    from app.services.request_allocation import _live, manual_remove
    from tests.test_request_board_api import _seed_job, _seed_recruiter

    job_id = await _seed_job(work_state="searching")
    dead = await _seed_recruiter()
    auto_rec = await _seed_recruiter()
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=dead,
                role="recruiter",
                source="manual",
                state="active",
                assigned_at=datetime.now(timezone.utc),
            )
        )
        (await db.get(User, dead)).is_active = False
        await db.commit()
    async with AsyncSessionLocal() as db:
        nobody = await db.scalar(
            select(Job.id).where(Job.id == job_id, jobs_nobody_working_clause())
        )
        assert nobody == job_id
        _rows, _out, inactive = await _live(db)
        assert dead in inactive

    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=auto_rec,
                role="recruiter",
                source="auto",
                state="active",
                assigned_at=datetime.now(timezone.utc),
            )
        )
        (await db.get(Job, job_id)).recruiter_id = auto_rec
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await manual_remove(db, job_id=job_id, user_id=auto_rec)
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).recruiter_id is None
