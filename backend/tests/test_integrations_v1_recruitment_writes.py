"""API v1 — zapis rekrutacji: dodanie osoby i ruch karty (15.10.2026).

Dwie części:

* bez bazy — polityka ruchu konta serwisowego
  (``services/recruitment_move_policy.py``): co klucz przesuwa, czego nie
  (403 ``requires_screen_decision``), że widz reguł ekranu nie ma żadnych
  praw, a polityka osoby woła bramki ekranu bez zmian;
* na bazie — trasy ``/recruitments/{id}/candidates`` i ``/moves``: osoba ze
  zgłoszeniem trafia na Tablicę, reszta do propozycji, ruch bez osoby
  (``moved_by`` puste, bez ``UserActivity``), bramki Tablicy w kopercie v1,
  odrzucenie bez maila, powtórka paragonu, scope.

Dane są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select

from app.api import pipeline as pipeline_api
from app.models.recruitment_pipeline import PipelineStage
from app.schemas.pipeline import StageMove
from app.services import pipeline_move_rules
from app.services.action_permissions import ProductAction, has_permission
from app.services.recruitment_move_policy import (
    NO_RIGHTS_VIEWER,
    IntegrationMovePolicy,
    MoveTarget,
    UserMovePolicy,
)
from app.services.service_account_auth import ServicePrincipal

V1 = "/api/integrations/v1"


# ── Bez bazy: polityka ruchu konta serwisowego ───────────────────────────────


def _principal(*scopes: str) -> ServicePrincipal:
    return ServicePrincipal(
        account_id=7,
        slug="automat-testowy",
        key_id="k1",
        scopes=frozenset(scopes or ("recruitments:write", "recruitments:read")),
        name="Automat testowy",
    )


class _NoDb:
    """Sesja, której polityka nie ma prawa dotknąć w danym przypadku."""

    async def scalar(self, *_args, **_kwargs):  # pragma: no cover - strażnik
        raise AssertionError("polityka nie powinna czytać bazy")


class _NameDb:
    """Sesja oddająca nazwę etapu bieżącego wiersza karty."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def scalar(self, *_args, **_kwargs):
        return self.name


def _stage_def(name: str, *, terminal: str | None = None, legacy: str | None = None):
    return SimpleNamespace(
        id=11,
        name=name,
        legacy_enum_value=legacy,
        is_terminal=terminal is not None,
        terminal_type=SimpleNamespace(value=terminal) if terminal else None,
        category=SimpleNamespace(value="terminal" if terminal else "internal"),
    )


def _target(
    *,
    column: str,
    legacy: PipelineStage = PipelineStage.new,
    stage_def=None,
    fresh_pair: bool = False,
    **data,
) -> MoveTarget:
    return MoveTarget(
        data=StageMove(candidate_id=5, job_id=9, stage_def_id=11, **data),
        job=SimpleNamespace(id=9, client_id=987654321),
        stage_def=stage_def or _stage_def("Etap"),
        legacy_enum=legacy,
        target_column=column,
        fresh_pair=fresh_pair,
    )


def _current(monkeypatch, column: str, *, row=None, arrives: bool = True) -> None:
    async def gate_row(_db, *, candidate_id, job_id):
        return row, column

    async def arrives_before(_db, *, candidate_id, job_id):
        return arrives

    monkeypatch.setattr(pipeline_move_rules, "gate_stage_row", gate_row)
    monkeypatch.setattr(
        pipeline_move_rules, "arrives_from_before_client_send", arrives_before
    )


async def _refused(policy: IntegrationMovePolicy, target: MoveTarget) -> dict:
    with pytest.raises(HTTPException) as err:
        await policy.assert_move_allowed(target)
    assert err.value.status_code == 403, err.value.detail
    assert err.value.detail["error"] == "requires_screen_decision"
    assert err.value.detail["message"]
    return err.value.detail


@pytest.mark.asyncio
async def test_key_moves_between_ordinary_columns_and_to_verified(monkeypatch):
    policy = IntegrationMovePolicy(_principal(), _NoDb())
    _current(monkeypatch, "new")
    await policy.assert_move_allowed(
        _target(column="screening", legacy=PipelineStage.screening)
    )
    await policy.assert_move_allowed(
        _target(column="verified", legacy=PipelineStage.verified)
    )
    await policy.assert_move_allowed(_target(column="cv_qc"))
    _current(monkeypatch, "cv_qc")
    await policy.assert_move_allowed(
        _target(column="screening", legacy=PipelineStage.screening)
    )
    # Po wysłaniu karta chodzi między kolumnami klienta (bez zatrudnienia).
    _current(monkeypatch, "client_interview", arrives=False)
    await policy.assert_move_allowed(
        _target(column="cv_sent", legacy=PipelineStage.cv_sent)
    )
    await policy.assert_move_allowed(
        _target(column="contract", legacy=PipelineStage.negotiation)
    )
    assert policy.can_terminal_transition() and policy.can_edit_rates()


@pytest.mark.asyncio
async def test_hire_is_a_screen_decision() -> None:
    policy = IntegrationMovePolicy(_principal(), _NoDb())
    for target in (
        _target(column="hired", legacy=PipelineStage.hired),
        _target(
            column="hired",
            legacy=PipelineStage.hired,
            stage_def=_stage_def("Zatrudniony", terminal="hired"),
        ),
        _target(column="hired", legacy=PipelineStage.onboarding),
    ):
        assert (await _refused(policy, target))["reason"] == "hire"


@pytest.mark.asyncio
async def test_crossing_to_the_client_is_a_screen_decision(monkeypatch) -> None:
    policy = IntegrationMovePolicy(_principal(), _NoDb())
    for current in ("new", "screening", "verified", "cv_qc"):
        _current(monkeypatch, current)
        for column, legacy in (
            ("cv_sent", PipelineStage.cv_sent),
            ("client_interview", PipelineStage.client_interview),
            ("contract", PipelineStage.negotiation),
        ):
            detail = await _refused(policy, _target(column=column, legacy=legacy))
            assert detail["reason"] == "client_send"


@pytest.mark.asyncio
async def test_cpro_queue_is_a_screen_decision(monkeypatch) -> None:
    _current(monkeypatch, "cv_qc")
    policy = IntegrationMovePolicy(_principal(), _NoDb())
    into_queue = _target(column="cv_qc", stage_def=_stage_def("Wysłać do Cpro"))
    assert (await _refused(policy, into_queue))["reason"] == "cpro_queue"

    # Karta stojąca w kolejce Cpro: „✓ Wrzucone” i zwrot robi osoba od Cpro.
    in_queue = SimpleNamespace(stage_def_id=31)
    _current(monkeypatch, "cv_qc", row=in_queue, arrives=False)
    policy = IntegrationMovePolicy(_principal(), _NameDb("Wysłać do Cpro"))
    out_of_queue = _target(column="screening", legacy=PipelineStage.screening)
    assert (await _refused(policy, out_of_queue))["reason"] == "cpro_queue"


@pytest.mark.asyncio
async def test_rates_and_delivery_lead_fields_are_screen_decisions() -> None:
    policy = IntegrationMovePolicy(_principal(), _NoDb())
    cases = {
        "client_rate": {"client_rate_value": "150"},
        "candidate_rate": {"expected_rate_value": "120"},
        "hire": {"hired_signed_via": "uop"},
        "delivery_lead_decision": {"ended_by": "delivery_lead"},
    }
    for reason, data in cases.items():
        target = _target(column="screening", legacy=PipelineStage.screening, **data)
        assert (await _refused(policy, target))["reason"] == reason


@pytest.mark.asyncio
async def test_closing_is_allowed_from_every_column_in_progress(monkeypatch):
    # Karta w kolejce Cpro też: zamknięcie nie czyta nazwy bieżącego etapu.
    in_queue = SimpleNamespace(stage_def_id=31)
    policy = IntegrationMovePolicy(_principal(), _NoDb())
    for current in ("new", "cv_qc", "cv_sent", "client_interview", "contract"):
        _current(monkeypatch, current, row=in_queue)
        await policy.assert_move_allowed(
            _target(column="closed", legacy=PipelineStage.rejected)
        )
        await policy.assert_move_allowed(
            _target(
                column="closed",
                stage_def=_stage_def("Rezygnacja", terminal="withdrawn"),
            )
        )
    assert policy.may_send_rejection_email is False


@pytest.mark.asyncio
async def test_hired_card_does_not_move_by_key(monkeypatch) -> None:
    _current(monkeypatch, "hired")
    policy = IntegrationMovePolicy(_principal(), _NoDb())
    for target in (
        _target(column="contract", legacy=PipelineStage.negotiation),
        _target(column="closed", legacy=PipelineStage.rejected),
    ):
        assert (await _refused(policy, target))["reason"] == "hire"


@pytest.mark.asyncio
async def test_pair_outside_the_recruitment_is_409_not_a_proposal() -> None:
    policy = IntegrationMovePolicy(_principal(), _NoDb())
    with pytest.raises(HTTPException) as err:
        await policy.assert_move_allowed(_target(column="new", fresh_pair=True))
    assert err.value.status_code == 409
    assert err.value.detail["error"] == "not_in_recruitment"


@pytest.mark.asyncio
async def test_policy_checks_its_scope_itself() -> None:
    policy = IntegrationMovePolicy(_principal("recruitments:read"), _NoDb())
    for call in (
        policy.ensure_job_access(9),
        policy.assert_can_act(candidate_id=5, job_id=9),
        policy.assert_move_allowed(_target(column="screening")),
    ):
        with pytest.raises(HTTPException) as err:
            await call
        assert err.value.status_code == 403
        assert err.value.detail["error"] == "insufficient_scope"


@pytest.mark.asyncio
async def test_key_author_is_nobody_and_viewer_has_no_rights() -> None:
    from app.api.candidate_access import user_can_view_client_rate
    from app.models.user import UserRole

    policy = IntegrationMovePolicy(_principal(), _NoDb())
    assert policy.actor_id is None and policy.mover is None
    assert policy.actor.name == "Integracja: Automat testowy"
    viewer = policy.viewer
    assert viewer is NO_RIGHTS_VIEWER and viewer.id is None
    assert not viewer.has_any_role(*UserRole)
    assert not any(has_permission(viewer, action) for action in ProductAction)
    assert user_can_view_client_rate(viewer) is False
    # 12 h blokada nie dotyczy integracji — bez odczytu bazy.
    await policy.assert_can_act(candidate_id=5, job_id=9)


@pytest.mark.asyncio
async def test_user_policy_calls_the_screen_gates(monkeypatch) -> None:
    from app.models.user import UserRole

    calls: list[tuple] = []
    user = SimpleNamespace(
        id=42, has_any_role=lambda *roles: UserRole.recruiter in roles
    )

    async def membership(db, who, job_id):
        calls.append(("membership", who, job_id))

    async def load_process(db, *, candidate_id, job_id):
        calls.append(("load_process", candidate_id, job_id))
        return "proces"

    async def can_act(db, *, process, user):
        calls.append(("can_act", process, user))

    monkeypatch.setattr(pipeline_api, "ensure_job_membership", membership)
    monkeypatch.setattr(pipeline_api.candidate_claim, "load_process", load_process)
    monkeypatch.setattr(pipeline_api.candidate_claim, "assert_can_act", can_act)
    policy = UserMovePolicy(user, db="sesja")

    await policy.ensure_job_access(9)
    await policy.assert_can_act(candidate_id=5, job_id=9)
    await policy.assert_move_allowed(_target(column="hired"))  # ekran: bez listy
    assert calls == [
        ("membership", user, 9),
        ("load_process", 5, 9),
        ("can_act", "proces", user),
    ]
    assert policy.actor_id == 42 and policy.viewer is user and policy.mover is user
    assert policy.may_send_rejection_email is True
    assert policy.can_terminal_transition() is True
    assert policy.can_edit_rates() is True
    sourcer_like = UserMovePolicy(
        SimpleNamespace(id=1, has_any_role=lambda *r: False), None
    )
    assert sourcer_like.can_terminal_transition() is False


def test_key_move_leaves_history_but_no_ranking_entry() -> None:
    from app.models.activity import Activity
    from app.models.user_activity import UserActivity

    added: list = []
    db = SimpleNamespace(add=added.append)
    stage = SimpleNamespace(id=3, candidate_id=5, job_id=9)
    pipeline_api._record_stage_change(
        db,
        stage=stage,
        stage_def=None,
        legacy_enum=PipelineStage.screening,
        actor_id=None,
        stage_display_name="Screening",
    )
    assert [type(row) for row in added] == [Activity]
    assert added[0].user_id is None

    added.clear()
    pipeline_api._record_stage_change(
        db,
        stage=stage,
        stage_def=None,
        legacy_enum=PipelineStage.screening,
        actor_id=42,
        stage_display_name="Screening",
    )
    assert [type(row) for row in added] == [Activity, UserActivity]


# ── Na bazie: trasy v1 ───────────────────────────────────────────────────────


async def _key(app_client: AsyncClient, headers: dict, scopes: list[str]) -> str:
    from tests.test_service_accounts import _account_with_key

    _, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return api_key


def _h(api_key: str, idem: str | None = None) -> dict:
    return {"X-API-Key": api_key, "Idempotency-Key": idem or str(uuid.uuid4())}


_STAGES = (
    # (klucz, nazwa, kod, kategoria, typ zamknięcia)
    ("new", "Nowi", "new", "internal", None),
    ("screening", "Screening", "screening", "internal", None),
    ("verified", "Zweryfikowany", "verified", "internal", None),
    ("qc", "QC CV", "interview", "internal", None),
    ("cv_sent", "CV wysłane", "cv_sent", "external", None),
    ("client", "Rozmowa u klienta", "client_interview", "external", None),
    ("hired", "Zatrudniony", "hired", "terminal", "hired"),
    ("rejected", "Odrzucony", "rejected", "terminal", "rejected"),
)


async def _world(*, champion_profile: dict | None = None) -> dict:
    """Rekrutacja z szablonem jak na Tablicy (zmyślony klient i szablon)."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
        TerminalType,
    )

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"V1R Klient {unique}")
        template = PipelineTemplate(name=f"V1R szablon {unique}")
        db.add_all([client, template])
        await db.flush()
        defs = {}
        for order, (key, name, code, category, terminal) in enumerate(_STAGES):
            stage_def = PipelineStageDef(
                template_id=template.id,
                name=name,
                order=order if terminal is None else 90 + order,
                category=StageCategoryEnum(category),
                legacy_enum_value=code,
                is_terminal=terminal is not None,
                terminal_type=TerminalType(terminal) if terminal else None,
            )
            db.add(stage_def)
            defs[key] = stage_def
        await db.flush()
        job = Job(
            title=f"V1R Java {unique}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=template.id,
            champion_profile=champion_profile,
        )
        db.add(job)
        await db.commit()
        return {
            "job_id": job.id,
            "client_id": client.id,
            "defs": {key: d.id for key, d in defs.items()},
        }


async def _candidate(*, status: str = "active") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Iwo",
            lastname=f"Zmyślony-{unique}",
            email=f"v1r-{unique}@example.com",
            status=CandidateStatus(status),
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _applied(candidate_id: int, job_id: int) -> None:
    """Dowód zgłoszenia do tej rekrutacji — źródło „ogłoszenie”."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSourceEvent(
                candidate_id=candidate_id,
                job_id=job_id,
                channel=SourceChannel("posting"),
            )
        )
        await db.commit()


async def _stage_row(candidate_id: int, job_id: int, *, stage_def_id: int, code: str):
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage(code),
                stage_def_id=stage_def_id,
                moved_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
        )
        await db.commit()


async def _stage_count(candidate_id: int, job_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(CandidateStage.id)).where(
                    CandidateStage.candidate_id == candidate_id,
                    CandidateStage.job_id == job_id,
                )
            )
        )


async def _on_board(app_client, api_key: str, world: dict) -> int:
    """Osoba ze zgłoszeniem dodana kluczem do „Nowych”."""
    cid = await _candidate()
    await _applied(cid, world["job_id"])
    resp = await app_client.post(
        f"{V1}/recruitments/{world['job_id']}/candidates",
        headers=_h(api_key),
        json={"candidate_ids": [cid]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["status"] == "added", resp.text
    return cid


async def _move(app_client, api_key: str, world: dict, cid: int, key: str, **extra):
    return await app_client.post(
        f"{V1}/recruitments/{world['job_id']}/moves",
        headers=_h(api_key),
        json={"candidate_id": cid, "to_stage_def_id": world["defs"][key], **extra},
    )


@pytest.mark.asyncio
class TestAddToRecruitment:
    async def test_applicant_lands_on_board_and_others_become_proposals(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        from app.core.database import AsyncSessionLocal
        from app.models.job_proposal import JobProposal
        from app.models.note import SYSTEM_NOTE_SOURCE, Note
        from app.models.recruitment_pipeline import CandidateStage
        from app.models.recruitment_process import RecruitmentProcess

        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        applicant, stranger = await _candidate(), await _candidate()
        await _applied(applicant, world["job_id"])

        resp = await app_client.post(
            f"{V1}/recruitments/{world['job_id']}/candidates",
            headers=_h(api_key),
            json={
                "candidate_ids": [applicant, stranger, applicant],
                "note": "Zgłoszenie z formularza automatu.",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["added"] == 1 and body["proposed"] == 1 and body["skipped"] == 0
        first, second = body["items"]
        assert first["candidate_id"] == applicant and first["status"] == "added"
        assert first["stage_def_id"] == world["defs"]["new"]
        assert second == {
            "candidate_id": stranger,
            "status": "proposed",
            "reason": None,
            "reason_label": None,
            "card_id": None,
            "stage_def_id": None,
            "process_state_version": None,
            "warnings": [],
        }

        async with AsyncSessionLocal() as db:
            card = await db.get(CandidateStage, first["card_id"])
            assert card.candidate_id == applicant and card.moved_by is None
            process = await db.scalar(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.candidate_id == applicant,
                    RecruitmentProcess.job_id == world["job_id"],
                )
            )
            assert process.entry_source == "auto_match"
            assert process.claimed_by_user_id is None
            note = await db.scalar(
                select(Note).where(
                    Note.candidate_id == applicant,
                    Note.job_id == world["job_id"],
                    Note.content == "Zgłoszenie z formularza automatu.",
                )
            )
            assert note.author_id is None
            assert note.external_source == SYSTEM_NOTE_SOURCE
            proposal = await db.scalar(
                select(JobProposal).where(
                    JobProposal.job_id == world["job_id"],
                    JobProposal.candidate_id == stranger,
                )
            )
            assert proposal is not None and proposal.source == "job_board"
        assert await _stage_count(stranger, world["job_id"]) == 0

    async def test_dry_run_gives_verdicts_and_writes_nothing(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        applicant, stranger = await _candidate(), await _candidate()
        blacklisted = await _candidate(status="blacklisted")
        await _applied(applicant, world["job_id"])

        resp = await app_client.post(
            f"{V1}/recruitments/{world['job_id']}/candidates",
            headers=_h(api_key),
            params={"dry_run": "true"},
            json={"candidate_ids": [applicant, stranger, blacklisted]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dry_run"] is True
        statuses = {item["candidate_id"]: item for item in body["items"]}
        assert statuses[applicant]["status"] == "added"
        assert statuses[stranger]["status"] == "proposed"
        assert statuses[blacklisted]["status"] == "blocked"
        assert statuses[blacklisted]["reason"] == "blacklisted"
        for cid in (applicant, stranger, blacklisted):
            assert await _stage_count(cid, world["job_id"]) == 0

    async def test_open_and_closed_cards_and_hard_blocks(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        in_progress, closed = await _candidate(), await _candidate()
        blacklisted = await _candidate(status="blacklisted")
        for cid in (in_progress, closed, blacklisted):
            await _applied(cid, world["job_id"])
        await _stage_row(
            in_progress, world["job_id"], stage_def_id=world["defs"]["new"], code="new"
        )
        await _stage_row(
            closed,
            world["job_id"],
            stage_def_id=world["defs"]["rejected"],
            code="rejected",
        )

        resp = await app_client.post(
            f"{V1}/recruitments/{world['job_id']}/candidates",
            headers=_h(api_key),
            json={"candidate_ids": [in_progress, closed, blacklisted, 2_000_000_000]},
        )
        assert resp.status_code == 200, resp.text
        items = {item["candidate_id"]: item for item in resp.json()["items"]}
        assert items[in_progress]["status"] == "already_in_job"
        assert items[closed]["status"] == "closed_in_job"
        assert items[closed]["process_state_version"] == 0
        assert "Odrzucony" in items[closed]["reason_label"]
        assert items[blacklisted]["status"] == "blocked"
        assert items[blacklisted]["reason"] == "blacklisted"
        assert items[2_000_000_000]["status"] == "blocked"
        assert items[2_000_000_000]["reason"] == "candidate_not_found"

    async def test_entry_column_only(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        cid = await _candidate()
        await _applied(cid, world["job_id"])
        resp = await app_client.post(
            f"{V1}/recruitments/{world['job_id']}/candidates",
            headers=_h(api_key),
            json={"candidate_ids": [cid], "stage_def_id": world["defs"]["cv_sent"]},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "validation_error"
        assert await _stage_count(cid, world["job_id"]) == 0


@pytest.mark.asyncio
class TestMoveCard:
    async def test_ordinary_move_has_no_person_and_no_ranking_entry(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        from app.core.database import AsyncSessionLocal
        from app.models.activity import Activity
        from app.models.recruitment_pipeline import CandidateStage
        from app.models.user_activity import UserActivity

        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        cid = await _on_board(app_client, api_key, world)

        resp = await _move(app_client, api_key, world, cid, "screening")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["column"] == "screening" and body["stage"] == "screening"
        assert body["stage_def_id"] == world["defs"]["screening"]
        assert body["process_state_version"] >= 2

        async with AsyncSessionLocal() as db:
            card = await db.get(CandidateStage, body["card_id"])
            assert card.moved_by is None
            history = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "pipeline",
                    Activity.entity_id == body["card_id"],
                    Activity.action == "stage_changed",
                )
            )
            assert history.user_id is None
            assert str(history.details.get("via", "")).startswith("integration:")
            ranking = await db.scalar(
                select(func.count(UserActivity.id)).where(
                    UserActivity.entity_type == "pipeline",
                    UserActivity.entity_id == body["card_id"],
                )
            )
            assert ranking == 0

        # Dalej i z powrotem — zwykłe ruchy między kolumnami w toku.
        assert (
            await _move(app_client, api_key, world, cid, "verified")
        ).status_code == 200
        assert (await _move(app_client, api_key, world, cid, "qc")).status_code == 200
        back = await _move(app_client, api_key, world, cid, "screening")
        assert back.status_code == 200, back.text

    async def test_hire_and_sending_to_the_client_need_the_screen(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        cid = await _on_board(app_client, api_key, world)
        assert (
            await _move(app_client, api_key, world, cid, "verified")
        ).status_code == 200
        before = await _stage_count(cid, world["job_id"])

        for key, reason in (
            ("cv_sent", "client_send"),
            ("client", "client_send"),
            ("hired", "hire"),
        ):
            resp = await _move(app_client, api_key, world, cid, key)
            assert resp.status_code == 403, resp.text
            error = resp.json()["error"]
            assert error["code"] == "requires_screen_decision"
            assert error["details"]["reason"] == reason
        assert await _stage_count(cid, world["job_id"]) == before

    async def test_verified_without_requirements_is_the_screen_409(
        self, app_client: AsyncClient, app_auth_headers: dict, monkeypatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "VERIFIED_GATE_ENABLED", True)
        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world(
            champion_profile={
                "screening_questions": [
                    {"id": "q1", "question": "Ile lat pracy z Javą?"}
                ]
            }
        )
        cid = await _on_board(app_client, api_key, world)

        resp = await _move(app_client, api_key, world, cid, "verified")
        assert resp.status_code == 409, resp.text
        error = resp.json()["error"]
        assert error["code"] == "VERIFIED_REQUIREMENTS_MISSING"
        assert error["details"]["missing"] == ["screening_sheet", "candidate_rate"]

    async def test_stale_state_version_is_409(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        cid = await _on_board(app_client, api_key, world)

        resp = await _move(
            app_client, api_key, world, cid, "screening", expected_state_version=999
        )
        assert resp.status_code == 409, resp.text
        error = resp.json()["error"]
        assert error["code"] == "PIPELINE_VERSION_CONFLICT"
        assert error["details"]["current_state_version"] != 999

    async def test_rejection_needs_a_reason_and_sends_no_email(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        from app.core.database import AsyncSessionLocal
        from app.models.rejection_email import ScheduledRejectionEmail

        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        cid = await _on_board(app_client, api_key, world)

        bare = await _move(app_client, api_key, world, cid, "rejected")
        assert bare.status_code == 422, bare.text

        resp = await _move(
            app_client,
            api_key,
            world,
            cid,
            "rejected",
            rejection_reason="Kandydat wybrał inną ofertę.",
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["column"] == "closed" and body["ended_by"] == "recruiter"
        async with AsyncSessionLocal() as db:
            mails = await db.scalar(
                select(func.count(ScheduledRejectionEmail.id)).where(
                    ScheduledRejectionEmail.candidate_id == cid,
                    ScheduledRejectionEmail.job_id == world["job_id"],
                )
            )
        assert mails == 0

        # Przywrócenie zamkniętej karty to zwykły ruch.
        restored = await _move(app_client, api_key, world, cid, "new")
        assert restored.status_code == 200, restored.text

    async def test_global_blacklist_warns_and_passes_with_acknowledge(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        from app.core.database import AsyncSessionLocal
        from app.models.candidate import Candidate, CandidateStatus

        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        cid = await _on_board(app_client, api_key, world)
        async with AsyncSessionLocal() as db:
            cand = await db.get(Candidate, cid)
            cand.status = CandidateStatus.blacklisted
            await db.commit()

        warned = await _move(app_client, api_key, world, cid, "screening")
        assert warned.status_code == 409, warned.text
        assert warned.json()["error"]["code"] == "ELIGIBILITY_WARNING"

        passed = await _move(
            app_client, api_key, world, cid, "screening", acknowledge_eligibility=True
        )
        assert passed.status_code == 200, passed.text
        assert passed.json()["eligibility_acknowledged"] == "blacklisted"

    async def test_person_outside_the_recruitment_is_409(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        cid = await _candidate()
        await _applied(cid, world["job_id"])

        resp = await _move(app_client, api_key, world, cid, "new")
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "not_in_recruitment"
        assert await _stage_count(cid, world["job_id"]) == 0

    async def test_replay_with_the_same_key_moves_once(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        from app.services.integration_receipts import REPLAYED_HEADER

        api_key = await _key(app_client, app_auth_headers, ["recruitments:write"])
        world = await _world()
        cid = await _on_board(app_client, api_key, world)
        before = await _stage_count(cid, world["job_id"])
        idem = str(uuid.uuid4())
        payload = {"candidate_id": cid, "to_stage_def_id": world["defs"]["screening"]}
        url = f"{V1}/recruitments/{world['job_id']}/moves"

        first = await app_client.post(url, headers=_h(api_key, idem), json=payload)
        again = await app_client.post(url, headers=_h(api_key, idem), json=payload)
        assert first.status_code == 200, first.text
        assert again.status_code == 200, again.text
        assert again.headers.get(REPLAYED_HEADER) == "true"
        assert again.json() == first.json()
        assert await _stage_count(cid, world["job_id"]) == before + 1


@pytest.mark.asyncio
class TestScope:
    @pytest.mark.parametrize("path", ["candidates", "moves"])
    async def test_read_scope_is_not_enough_and_jwt_is_401(
        self, app_client: AsyncClient, app_auth_headers: dict, path: str
    ):
        api_key = await _key(app_client, app_auth_headers, ["recruitments:read"])
        world = await _world()
        cid = await _candidate()
        body = (
            {"candidate_ids": [cid]}
            if path == "candidates"
            else {"candidate_id": cid, "to_stage_def_id": world["defs"]["new"]}
        )
        url = f"{V1}/recruitments/{world['job_id']}/{path}"

        resp = await app_client.post(url, headers=_h(api_key), json=body)
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"
        resp = await app_client.post(url, headers=app_auth_headers, json=body)
        assert resp.status_code == 401, resp.text
        assert await _stage_count(cid, world["job_id"]) == 0
