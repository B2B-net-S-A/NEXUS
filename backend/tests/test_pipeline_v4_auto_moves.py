"""Pipeline v4 (23.09.2026): automatyczne ruchy kart i dane odznak.

* ``auto_advance`` — karta jedzie wyłącznie do przodu; proces zamknięty
  i karta już dalej zostają nietknięte; pozycja liczona po szablonie.
* terminy od klienta przesuwają kartę na „Rozmowa u klienta”;
* ``compute_badge`` / ``interview_badges_for_job`` — jedna odznaka terminarza;
* ``order_status_for_pairs`` — czy zatrudniona para ma uzupełnione zamówienie.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.activity import Activity
from app.models.calendar_event import CalendarEvent, EventType
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.job import Job, JobStatus
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
    TerminalType,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.hired_order_status import order_status_for_pairs
from app.services.interview_cycle import (
    DebriefRef,
    EventRef,
    PairSnapshot,
    SlotRef,
    compute_badge,
    interview_badges_for_job,
)
from app.services.pipeline_auto_move import auto_advance

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)  # wtorek, 14:00 w PL


# ── Dane ─────────────────────────────────────────────────────────────────────


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"v4-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"V4_{tag}!pw"),
            name=f"V4 {role.value} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    token = create_access_token(uid, role.value, roles=[role.value])
    return uid, {"Authorization": f"Bearer {token}"}


async def _pair(
    *,
    stage: PipelineStage,
    recruiter_id: int | None = None,
    dl_id: int | None = None,
    template_id: int | None = None,
    stage_def_id: int | None = None,
) -> tuple[int, int, int]:
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"V4Client-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"V4Job-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter_id,
            delivery_lead_id=dl_id,
            pipeline_template_id=template_id,
        )
        cand = Candidate(
            name="Ola",
            lastname=f"Auto-{tag}",
            email=f"v4-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=stage,
                stage_def_id=stage_def_id,
                moved_by=recruiter_id,
                moved_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        await db.commit()
        return job.id, cand.id, client.id


async def _latest(candidate_id: int, job_id: int) -> CandidateStage:
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        assert row is not None
        return row


async def _advance(candidate_id: int, job_id: int, actor: int | None):
    async with AsyncSessionLocal() as db:
        moved = await auto_advance(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            target=PipelineStage.client_interview,
            actor_user_id=actor,
            source="test",
            note="Auto: test",
        )
        await db.commit()
        return moved


# ── auto_advance ─────────────────────────────────────────────────────────────


async def test_auto_advance_moves_card_from_cv_sent():
    rec_id, _ = await _user(UserRole.recruiter)
    job_id, cand_id, _ = await _pair(stage=PipelineStage.cv_sent, recruiter_id=rec_id)

    moved = await _advance(cand_id, job_id, rec_id)

    assert moved is not None
    latest = await _latest(cand_id, job_id)
    assert latest.stage == PipelineStage.client_interview
    assert latest.notes == "Auto: test"
    async with AsyncSessionLocal() as db:
        audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "pipeline",
                Activity.entity_id == latest.id,
                Activity.action == "stage_changed",
            )
        )
        assert audit is not None
        assert audit.details["source"] == "test"
        assert audit.details["from_stage"] == "cv_sent"


@pytest.mark.parametrize(
    "stage",
    [
        PipelineStage.client_interview,
        PipelineStage.acceptance,
        PipelineStage.hired,
        PipelineStage.rejected,
    ],
)
async def test_auto_advance_never_moves_back_or_reopens(stage: PipelineStage):
    rec_id, _ = await _user(UserRole.recruiter)
    job_id, cand_id, _ = await _pair(stage=stage, recruiter_id=rec_id)
    before = await _latest(cand_id, job_id)

    assert await _advance(cand_id, job_id, rec_id) is None

    after = await _latest(cand_id, job_id)
    assert after.id == before.id
    assert after.stage == stage


async def test_auto_advance_without_pipeline_pair_does_nothing():
    rec_id, _ = await _user(UserRole.recruiter)
    job_id, _cand_id, _ = await _pair(stage=PipelineStage.cv_sent, recruiter_id=rec_id)
    async with AsyncSessionLocal() as db:
        other = Candidate(
            name="Brak",
            lastname=f"Pary-{uuid.uuid4().hex[:6]}",
            status=CandidateStatus.active,
        )
        db.add(other)
        await db.commit()
        other_id = other.id
    assert await _advance(other_id, job_id, rec_id) is None
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(CandidateStage.id).where(
                CandidateStage.candidate_id == other_id,
                CandidateStage.job_id == job_id,
            )
        )
        assert count is None


async def _template() -> dict[str, int]:
    """Szablon z etapem własnym (kod `new`) ZA rozmową u klienta."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        tpl = PipelineTemplate(name=f"V4 szablon {tag}")
        db.add(tpl)
        await db.flush()

        def stage_def(name, order, legacy, *, category, terminal=None):
            return PipelineStageDef(
                template_id=tpl.id,
                name=name,
                order=order,
                category=category,
                is_terminal=terminal is not None,
                terminal_type=terminal,
                legacy_enum_value=legacy,
            )

        defs = {
            "early": stage_def(
                "Własny wczesny", 1, None, category=StageCategoryEnum.internal
            ),
            "cv": stage_def(
                "CV wysłane", 2, "cv_sent", category=StageCategoryEnum.internal
            ),
            "ci": stage_def(
                "Rozmowa u klienta",
                3,
                "client_interview",
                category=StageCategoryEnum.external,
            ),
            "late": stage_def(
                "Własny po rozmowie", 4, None, category=StageCategoryEnum.external
            ),
            "reserve": stage_def(
                "Rezerwa",
                9,
                "rejected",
                category=StageCategoryEnum.terminal,
                terminal=TerminalType.rejected,
            ),
        }
        db.add_all(defs.values())
        await db.commit()
        return {"template": tpl.id, **{k: v.id for k, v in defs.items()}}


async def test_auto_advance_compares_template_positions_not_codes():
    rec_id, _ = await _user(UserRole.recruiter)
    tpl = await _template()

    # Etap własny ZA rozmową (kod `new`) — karta jest dalej, nie cofamy jej.
    job_late, cand_late, _ = await _pair(
        stage=PipelineStage.new,
        recruiter_id=rec_id,
        template_id=tpl["template"],
        stage_def_id=tpl["late"],
    )
    assert await _advance(cand_late, job_late, rec_id) is None

    # Etap własny PRZED rozmową (też kod `new`) — ruch na etap szablonu.
    job_early, cand_early, _ = await _pair(
        stage=PipelineStage.new,
        recruiter_id=rec_id,
        template_id=tpl["template"],
        stage_def_id=tpl["early"],
    )
    moved = await _advance(cand_early, job_early, rec_id)
    assert moved is not None
    latest = await _latest(cand_early, job_early)
    assert latest.stage == PipelineStage.client_interview
    assert latest.stage_def_id == tpl["ci"]

    # Terminalny etap szablonu („Rezerwa”) — proces zamknięty.
    job_res, cand_res, _ = await _pair(
        stage=PipelineStage.rejected,
        recruiter_id=rec_id,
        template_id=tpl["template"],
        stage_def_id=tpl["reserve"],
    )
    assert await _advance(cand_res, job_res, rec_id) is None


# ── Terminy od klienta → „Rozmowa u klienta” ────────────────────────────────


def _future(days: int) -> str:
    base = datetime.now(timezone.utc) + timedelta(days=days)
    return base.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()


async def test_slot_request_moves_card_to_client_interview(app_client: AsyncClient):
    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _pair(
        stage=PipelineStage.cv_sent, recruiter_id=rec_id, dl_id=dl_id
    )

    created = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(3)}, {"start": _future(4)}],
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["moved_to_client_interview"] is True
    latest = await _latest(cand_id, job_id)
    assert latest.stage == PipelineStage.client_interview
    assert latest.moved_by == dl_id
    async with AsyncSessionLocal() as db:
        audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "pipeline",
                Activity.entity_id == latest.id,
            )
        )
        assert audit is not None
        assert audit.details["source"] == "interview_slots"


async def test_slot_request_leaves_card_that_is_already_further(
    app_client: AsyncClient,
):
    rec_id, _ = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, _ = await _pair(
        stage=PipelineStage.acceptance, recruiter_id=rec_id, dl_id=dl_id
    )
    before = await _latest(cand_id, job_id)

    created = await app_client.post(
        "/api/interview-cycle/slots",
        headers=dl_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "slots": [{"start": _future(3)}],
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["moved_to_client_interview"] is False
    assert (await _latest(cand_id, job_id)).id == before.id


# ── Odznaka terminarza ──────────────────────────────────────────────────────


def _iv(start: datetime, minutes: int = 60, ev_id: int = 7) -> EventRef:
    return EventRef(
        id=ev_id,
        start=start,
        end=start + timedelta(minutes=minutes),
        title="R",
        status="scheduled",
    )


def _req(status: str, *, count: int = 3, chosen=None, respond_by=None) -> SlotRef:
    slots = tuple(
        {
            "start": (NOW + timedelta(days=2 + i)).isoformat(),
            "end": (NOW + timedelta(days=2 + i, hours=1)).isoformat(),
        }
        for i in range(count)
    )
    return SlotRef(
        id=3,
        status=status,
        slots=slots,
        chosen_index=chosen,
        respond_by=respond_by,
        recruiter_id=11,
        created_by=22,
        duration_minutes=60,
        note=None,
        event_id=None,
    )


def _b(pair: PairSnapshot) -> dict | None:
    return compute_badge(pair, NOW, call_window_minutes=30)


def test_badge_none_for_empty_pair():
    assert _b(PairSnapshot(1, 2)) is None


def test_badge_choose_slot_counts_proposals_and_turns_urgent_after_deadline():
    badge = _b(PairSnapshot(1, 2, slot_request=_req("awaiting_recruiter")))
    assert badge["kind"] == "choose_slot"
    assert badge["label"] == "Wybierz termin · 3 propozycje"
    assert badge["tone"] == "wait"
    one = _b(PairSnapshot(1, 2, slot_request=_req("awaiting_recruiter", count=1)))
    assert one["label"] == "Wybierz termin · 1 propozycja"
    five = _b(PairSnapshot(1, 2, slot_request=_req("awaiting_recruiter", count=5)))
    assert five["label"] == "Wybierz termin · 5 propozycji"
    late = _b(
        PairSnapshot(
            1,
            2,
            slot_request=_req(
                "awaiting_recruiter", respond_by=NOW - timedelta(hours=1)
            ),
        )
    )
    assert late["tone"] == "urgent"


def test_badge_awaiting_dl_shows_chosen_slot_in_business_time():
    badge = _b(PairSnapshot(1, 2, slot_request=_req("awaiting_dl", chosen=0)))
    assert badge["kind"] == "awaiting_dl"
    # 12.06.2031 12:00 UTC = czwartek 14:00 w Warszawie (CEST).
    assert badge["label"] == "Czeka na DL · czw 12.06 · 14:00"
    assert badge["tone"] == "wait"


def test_badge_upcoming_interview_slot_prep_done_and_prep2():
    start = NOW + timedelta(days=2)  # czwartek
    slot = _b(PairSnapshot(1, 2, interview=_iv(start)))
    assert slot["kind"] == "slot"
    assert slot["label"] == "czw 12.06 · 14:00"
    assert slot["tone"] == "info"

    prep = EventRef(8, NOW - timedelta(hours=3), None, "P", "completed")
    done = _b(PairSnapshot(1, 2, interview=_iv(start), preps=[prep]))
    assert done["kind"] == "prep_done"
    assert done["label"] == "czw 12.06 · 14:00 · Prep ✓"
    assert done["tone"] == "ok"

    prep2 = EventRef(9, NOW + timedelta(days=1), None, "P2", "scheduled")
    tomorrow = _b(PairSnapshot(1, 2, interview=_iv(start), preps=[prep, prep2]))
    assert tomorrow["kind"] == "prep2"
    assert tomorrow["label"] == "Prep 2 jutro"


def test_badge_call_due_beats_everything_and_debrief_closes_it():
    ended = _iv(NOW - timedelta(minutes=78))  # koniec 18 min temu
    badge = _b(
        PairSnapshot(1, 2, interview=ended, slot_request=_req("awaiting_recruiter"))
    )
    assert badge["kind"] == "call_due"
    assert badge["label"] == "Zadzwoń · 18 min po rozmowie"
    assert badge["tone"] == "urgent"

    late = _b(PairSnapshot(1, 2, interview=_iv(NOW - timedelta(hours=5))))
    assert late["kind"] == "call_due"
    assert late["label"] == "Zadzwoń · debrief zaległy"

    done = _b(
        PairSnapshot(
            1,
            2,
            interview=_iv(NOW - timedelta(hours=5)),
            debrief=DebriefRef(1, 5, "yes", None, None, None),
        )
    )
    assert done == {
        "kind": "debrief_done",
        "label": "Debrief ✓",
        "tone": "ok",
        "at": (NOW - timedelta(hours=5)).isoformat(),
    }


async def test_interview_badges_for_job_only_for_pairs_in_cycle():
    rec_id, _ = await _user(UserRole.recruiter)
    job_id, with_slots, _ = await _pair(
        stage=PipelineStage.client_interview, recruiter_id=rec_id
    )
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        quiet = Candidate(
            name="Cisza",
            lastname=f"Bez-{uuid.uuid4().hex[:6]}",
            status=CandidateStatus.active,
        )
        with_event = Candidate(
            name="Ewa",
            lastname=f"Rozmowa-{uuid.uuid4().hex[:6]}",
            status=CandidateStatus.active,
        )
        db.add_all([quiet, with_event])
        await db.flush()
        db.add_all(
            [
                ClientInterviewSlotRequest(
                    candidate_id=with_slots,
                    job_id=job_id,
                    created_by=rec_id,
                    recruiter_id=rec_id,
                    slots=[
                        {
                            "start": (now + timedelta(days=3)).isoformat(),
                            "end": (now + timedelta(days=3, hours=1)).isoformat(),
                        },
                        {
                            "start": (now + timedelta(days=4)).isoformat(),
                            "end": (now + timedelta(days=4, hours=1)).isoformat(),
                        },
                    ],
                    duration_minutes=60,
                ),
                CalendarEvent(
                    title="Rozmowa u klienta",
                    event_type=EventType.client_interview,
                    start_time=now + timedelta(days=5),
                    end_time=now + timedelta(days=5, hours=1),
                    created_by=rec_id,
                    candidate_id=with_event.id,
                    job_id=job_id,
                ),
            ]
        )
        await db.commit()
        quiet_id, event_id = quiet.id, with_event.id

    async with AsyncSessionLocal() as db:
        badges = await interview_badges_for_job(
            db, job_id=job_id, candidate_ids=[with_slots, quiet_id, event_id]
        )

    assert set(badges) == {with_slots, event_id}
    assert badges[with_slots]["kind"] == "choose_slot"
    assert badges[with_slots]["label"] == "Wybierz termin · 2 propozycje"
    assert badges[event_id]["kind"] == "slot"
    # Karta i dok dostają kroki cyklu (kreski postępu) i id rozmowy.
    assert [s["key"] for s in badges[event_id]["steps"]] == [
        "slots", "choice", "prep", "prep2", "interview", "call", "debrief"
    ]
    assert badges[event_id]["steps"][0]["state"] == "done"
    assert isinstance(badges[event_id]["interview_event_id"], int)
    assert badges[with_slots]["interview_event_id"] is None
    assert badges[with_slots]["steps"][1]["state"] in {"current", "todo", "waiting", "overdue"}
    async with AsyncSessionLocal() as db:
        assert await interview_badges_for_job(db, job_id=job_id, candidate_ids=[]) == {}


# ── Status zamówienia zatrudnionej pary ─────────────────────────────────────


async def _contract(
    candidate_id: int, job_id: int, client_id: int, *, status=ContractStatus.active
) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            job_id=job_id,
            contract_type=ContractType.b2b,
            status=status,
            start_date=date(2031, 6, 1),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def _order(contract_id: int, client_id: int, **values) -> int:
    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title="Zamówienie testowe",
            **values,
        )
        db.add(order)
        await db.commit()
        return order.id


async def test_order_status_for_pairs():
    rec_id, _ = await _user(UserRole.recruiter)
    # Brak kontraktu.
    job_a, cand_a, _ = await _pair(stage=PipelineStage.hired, recruiter_id=rec_id)
    # Auto-szkic bez stawki przychodowej — to NIE jest uzupełnione zamówienie.
    job_b, cand_b, client_b = await _pair(
        stage=PipelineStage.hired, recruiter_id=rec_id
    )
    c_b = await _contract(cand_b, job_b, client_b)
    await _order(
        c_b, client_b, status=ClientOrderStatus.draft, start_date=date(2031, 6, 1)
    )
    # Uzupełnione: start + dodatnia stawka.
    job_c, cand_c, client_c = await _pair(
        stage=PipelineStage.hired, recruiter_id=rec_id
    )
    c_c = await _contract(cand_c, job_c, client_c)
    await _order(
        c_c,
        client_c,
        status=ClientOrderStatus.active,
        start_date=date(2031, 6, 1),
        rate_client=Decimal("180"),
    )
    # Anulowane uzupełnione zamówienie się nie liczy.
    job_d, cand_d, client_d = await _pair(
        stage=PipelineStage.hired, recruiter_id=rec_id
    )
    c_d = await _contract(cand_d, job_d, client_d)
    await _order(
        c_d,
        client_d,
        status=ClientOrderStatus.cancelled,
        start_date=date(2031, 6, 1),
        rate_client=Decimal("180"),
    )
    # Unieważniony kontrakt z uzupełnionym zamówieniem się nie liczy.
    job_e, cand_e, client_e = await _pair(
        stage=PipelineStage.hired, recruiter_id=rec_id
    )
    c_e = await _contract(cand_e, job_e, client_e, status=ContractStatus.void)
    await _order(
        c_e,
        client_e,
        status=ClientOrderStatus.active,
        start_date=date(2031, 6, 1),
        rate_client=Decimal("180"),
    )
    # Żywa linia zamówienia grupowego = zamówienie jest.
    job_f, cand_f, client_f = await _pair(
        stage=PipelineStage.hired, recruiter_id=rec_id
    )
    c_f = await _contract(cand_f, job_f, client_f)
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_f,
            order_number=f"MD-{uuid.uuid4().hex[:6]}",
            start_date=date(2031, 6, 1),
            status=GROUP_STATUS_ACTIVE,
            is_md_budget_based=False,
        )
        db.add(group)
        await db.commit()
        group_id = group.id
    await _order(
        c_f,
        client_f,
        status=ClientOrderStatus.draft,
        order_group_id=group_id,
    )

    async with AsyncSessionLocal() as db:
        result = await order_status_for_pairs(
            db,
            [
                (cand_a, job_a),
                (cand_b, job_b),
                (cand_c, job_c),
                (cand_d, job_d),
                (cand_e, job_e),
                (cand_f, job_f),
            ],
        )
        assert await order_status_for_pairs(db, []) == {}

    assert result == {
        (cand_a, job_a): "missing",
        (cand_b, job_b): "missing",
        (cand_c, job_c): "complete",
        (cand_d, job_d): "missing",
        (cand_e, job_e): "missing",
        (cand_f, job_f): "complete",
    }
