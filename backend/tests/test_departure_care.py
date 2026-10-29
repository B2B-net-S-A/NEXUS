"""Odejście rekrutera: jego kandydatów domyka Delivery Lead rekrutacji (0617).

Decyzje Artura z 28.10.2026: każde wyłączenie konta dzieli żywe pary osoby
po rekrutacjach (DL rekrutacji → główny DL klienta → Head of Recruitment),
DL domyka sam w ramach obowiązków, a „Prowadzi”, Liga, KPI i premie zostają
przy osobie, która odeszła. Tylko nowe odejścia.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, update

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_job_owner import CandidateJobOwner
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.pair_departure_care import PairDepartureCare
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import departure_care
from app.services.account_deactivation import deactivate_account
from app.services.departure_care import (
    CareGroup,
    CareRow,
    columns_text,
    notice_text,
    people_phrase,
    reminder_text,
    rows_payload,
)
from app.services.hr import placement_bonuses

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0617_pair_departure_care.py"
T0 = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


# ── bez bazy ────────────────────────────────────────────────────────────────


def test_migration_chains_after_timesheets_permission() -> None:
    spec = importlib.util.spec_from_file_location("m0614", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0617_pair_departure_care"
    assert module.down_revision == "0616_autofill_more_reasons"


def test_ddl_is_idempotent_and_mirrored_in_entrypoint() -> None:
    from app.services.departure_care_schema import ENUM_DDL, TABLE_DDL

    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "departure_care_schema" in entrypoint
    assert "*_DEPARTURE_CARE_DDL," in entrypoint
    assert ENUM_DDL in entrypoint
    for statement in TABLE_DDL:
        assert "IF NOT EXISTS" in _collapse(statement), statement


def test_deep_health_probes_the_care_table() -> None:
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    block = main[main.index("    core_checks = [") :]
    block = block[: block.index("\n    ]")]
    assert '("pair_departure_care", PairDepartureCare)' in block


def test_every_deactivation_path_hands_over() -> None:
    """Ustawienia (PATCH i DELETE), sprawa odejścia i M365 idą przez
    ``deactivate_account`` albo wołają wprost; Compass i SSO nadrabia pętla."""
    central = (BACKEND / "app" / "services" / "account_deactivation.py").read_text(
        encoding="utf-8"
    )
    assert "hand_over_safely(db, user, actor_id=actor_id)" in central
    admin = (BACKEND / "app" / "api" / "admin.py").read_text(encoding="utf-8")
    assert "hand_over_safely(db, user, actor_id=_admin.id)" in admin
    triggers = (BACKEND / "app" / "services" / "notification_triggers.py").read_text(
        encoding="utf-8"
    )
    assert '"departed_care": await _departed_care(db, now)' in triggers
    for action in (
        "user_deactivated",
        "hr_lifecycle_deactivated",
        "compass_lifecycle_deactivated",
        "sso_aad_role_denied",
        "admin_aad_role_denied",
        "m365_account_gone_deactivated",
        "active_changed",
    ):
        assert action in departure_care.DEACTIVATION_TRACES


def test_only_new_departures_are_swept() -> None:
    """Decyzja Artura 28.10: 608 par sprzed wdrożenia zostaje bez zmian."""
    assert departure_care.SWEEP_SINCE >= datetime(2026, 10, 28, tzinfo=timezone.utc)


def test_mail_is_required_and_comes_from_the_bell() -> None:
    from app.services.notification_delivery import (
        BELL_MAIL_TYPES,
        DEPARTED_CARE_KIND,
        REQUIRED_KINDS,
    )

    assert DEPARTED_CARE_KIND in REQUIRED_KINDS
    assert BELL_MAIL_TYPES[DEPARTED_CARE_KIND] == ("departed_pairs_care",)


def test_people_phrase_declines() -> None:
    assert people_phrase(1) == "1 osoba"
    assert people_phrase(3) == "3 osoby"
    assert people_phrase(12) == "12 osób"
    assert people_phrase(22) == "22 osoby"
    assert people_phrase(78) == "78 osób"


def test_columns_text_starts_closest_to_the_client() -> None:
    text = columns_text({"new": 41, "client_interview": 3, "cv_sent": 18})
    assert text == "3 rozmowa u klienta, 18 CV wysłane, 41 nowi"


def test_notice_says_who_left_how_many_and_that_it_is_not_credited() -> None:
    group = CareGroup(
        caretaker_id=2,
        caretaker_name="Delivery Lead",
        pairs=78,
        job_ids={1, 2, 3},
        clients=["Bank Przykładowy"],
        columns={"client_interview": 3, "new": 75},
    )
    title, message = notice_text("Anna Przykładowa", group)
    assert title == "Odejście z firmy: Anna P. — 78 osób do domknięcia"
    assert "w 3 rekrutacjach (Bank Przykładowy)" in message
    assert "domykasz Ty: 3 rozmowa u klienta, 75 nowi" in message
    assert "nie liczy się do Ligi, KPI ani premii" in message


def test_reminder_names_the_escalation() -> None:
    title, message = reminder_text("Anna Przykładowa", 5)
    assert title == "Przypomnienie: 5 osób do domknięcia — odejście: Anna P."
    assert ".." not in message
    assert "Head of Recruitment" in message


def _care(candidate_id: int, column: str, departed: int = 9) -> CareRow:
    return CareRow(
        candidate_id=candidate_id,
        candidate_name=f"Kandydat {candidate_id}",
        job_id=100 + candidate_id % 2,
        job_title="Programista",
        client_name="Bank Przykładowy",
        column=column,
        moved_at=T0,
        departed_user_id=departed,
        departed_name=f"Osoba {departed}",
        caretaker_user_id=2,
        caretaker_name="Delivery Lead",
        via="job_dl",
        since=T0 + timedelta(days=candidate_id),
        reminded_at=None,
    )


def test_rows_payload_groups_by_person_and_sorts_closest_to_client() -> None:
    groups = rows_payload(
        [
            _care(1, "new"),
            _care(2, "client_interview"),
            _care(3, "cv_sent"),
            _care(4, "screening", departed=8),
        ]
    )
    assert [g["departed_user_id"] for g in groups] == [9, 8]
    first = groups[0]
    assert first["pairs"] == 3
    assert first["jobs"] == 2
    assert first["since"] == T0 + timedelta(days=1)
    assert [r["column"] for r in first["rows"]] == [
        "client_interview",
        "cv_sent",
        "new",
    ]
    assert list(first["columns"]) == ["client_interview", "cv_sent", "new"]


# ── z bazą (CI) ─────────────────────────────────────────────────────────────


async def _user(db, *roles: str, active: bool = True) -> User:
    tag = uuid.uuid4().hex[:8]
    user = User(
        email=f"care-{tag}@example.com",
        password_hash=hash_password(f"T3st_{tag}!Care"),
        name=f"Osoba Przykładowa {tag}",
        role=UserRole(roles[0]),
        roles=list(roles),
        is_active=active,
    )
    db.add(user)
    await db.flush()
    return user


async def _pair(db, candidate: Candidate, job: Job, *moves) -> None:
    for minutes, (stage, mover) in enumerate(moves):
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=stage,
                moved_by=mover.id,
                moved_at=T0 + timedelta(minutes=minutes),
            )
        )


async def _candidate(db, tag: str, n: int) -> Candidate:
    candidate = Candidate(
        name="Jan", lastname=f"Przykładowy-{tag}-{n}", email=f"c{n}-{tag}@example.com"
    )
    db.add(candidate)
    await db.flush()
    return candidate


async def _world() -> dict:
    """Rekruter pracował w dwóch rekrutacjach u dwóch DL-i i w trzeciej bez
    DL-a, u klienta z głównym DL-em."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, "recruiter")
        other = await _user(db, "recruiter")
        dl_a = await _user(db, "delivery_lead")
        dl_b = await _user(db, "delivery_lead", "recruiter")
        head = await _user(db, "delivery_lead")
        admin = await _user(db, "admin")
        client_a = Client(name=f"Firma A {tag}")
        client_b = Client(name=f"Firma B {tag}")
        db.add_all([client_a, client_b])
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=head.id, client_id=client_b.id, is_head=True
            )
        )
        job_a = Job(
            title=f"A {tag}",
            client_id=client_a.id,
            status=JobStatus.published,
            delivery_lead_id=dl_a.id,
        )
        job_b = Job(
            title=f"B {tag}",
            client_id=client_a.id,
            status=JobStatus.published,
            delivery_lead_id=dl_b.id,
        )
        job_c = Job(title=f"C {tag}", client_id=client_b.id, status=JobStatus.published)
        job_closed = Job(
            title=f"D {tag}",
            client_id=client_a.id,
            status=JobStatus.closed,
            delivery_lead_id=dl_a.id,
        )
        db.add_all([job_a, job_b, job_c, job_closed])
        await db.flush()
        c = [await _candidate(db, tag, n) for n in range(7)]
        # A: zweryfikowany przez rekrutera, CV wysłał DL — para rekrutera.
        await _pair(
            db,
            c[0],
            job_a,
            (PipelineStage.new, recruiter),
            (PipelineStage.verified, recruiter),
            (PipelineStage.cv_sent, dl_a),
        )
        # A: dodany przez rekrutera, bez weryfikacji.
        await _pair(db, c[1], job_a, (PipelineStage.new, recruiter))
        # A: odrzucony — para nie żyje.
        await _pair(
            db,
            c[2],
            job_a,
            (PipelineStage.new, recruiter),
            (PipelineStage.rejected, recruiter),
        )
        # A: dodany przez rekrutera, zweryfikował ktoś inny — nie jego.
        await _pair(
            db,
            c[3],
            job_a,
            (PipelineStage.new, recruiter),
            (PipelineStage.verified, other),
        )
        # B: screening rekrutera.
        await _pair(
            db,
            c[4],
            job_b,
            (PipelineStage.new, recruiter),
            (PipelineStage.screening, recruiter),
        )
        # C (bez DL-a) → główny DL klienta.
        await _pair(db, c[5], job_c, (PipelineStage.new, recruiter))
        # Zamknięta rekrutacja — para nie żyje.
        await _pair(db, c[6], job_closed, (PipelineStage.new, recruiter))
        await db.commit()
        return {
            "recruiter": recruiter.id,
            "other": other.id,
            "dl_a": dl_a.id,
            "dl_b": dl_b.id,
            "head": head.id,
            "admin": admin.id,
            "client_a": client_a.id,
            "jobs": [job_a.id, job_b.id, job_c.id, job_closed.id],
            "candidates": [x.id for x in c],
        }


async def _deactivate(world: dict) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, world["recruiter"], with_for_update=True)
        await deactivate_account(
            db,
            user,
            action="user_deactivated",
            actor_id=world["admin"],
            details={"target_email": user.email},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_preview_splits_live_pairs_per_delivery_lead() -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, world["recruiter"])
        data = await departure_care.preview(db, user)
    assert data["pairs"] == 4
    assert data["jobs"] == 3
    assert data["unassigned"] == 0
    by_user = {c["user_id"]: c for c in data["caretakers"]}
    assert by_user[world["dl_a"]]["pairs"] == 2
    assert by_user[world["dl_a"]]["via"] == ["job_dl"]
    assert by_user[world["dl_b"]]["pairs"] == 1
    assert by_user[world["head"]]["via"] == ["client_dl"]


@pytest.mark.asyncio
async def test_deactivation_hands_pairs_to_delivery_leads_and_keeps_owner() -> None:
    world = await _world()
    await _deactivate(world)
    cand = world["candidates"]
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(PairDepartureCare).where(
                    PairDepartureCare.departed_user_id == world["recruiter"]
                )
            )
        ).all()
        assert {(r.candidate_id, r.caretaker_user_id) for r in rows} == {
            (cand[0], world["dl_a"]),
            (cand[1], world["dl_a"]),
            (cand[4], world["dl_b"]),
            (cand[5], world["head"]),
        }
        # „Prowadzi” przypięte do osoby, która odeszła.
        owners = (
            await db.scalars(
                select(CandidateJobOwner).where(
                    CandidateJobOwner.candidate_id.in_([cand[0], cand[1]])
                )
            )
        ).all()
        assert {o.owner_user_id for o in owners} == {world["recruiter"]}
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.departed_pairs_care,
                    Notification.related_entity_id == world["recruiter"],
                )
            )
        ).all()
        assert {b.user_id for b in bells} == {
            world["dl_a"],
            world["dl_b"],
            world["head"],
        }
        assert all(b.link == f"/departed-care?from={world['recruiter']}" for b in bells)
        trace = await db.scalar(
            select(Activity).where(
                Activity.entity_id == world["recruiter"],
                Activity.action == departure_care.HANDED_OVER_ACTION,
            )
        )
        assert trace is not None and trace.details["pairs"] == 4


@pytest.mark.asyncio
async def test_hand_over_is_idempotent() -> None:
    world = await _world()
    await _deactivate(world)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, world["recruiter"])
        again = await departure_care.hand_over(db, user, actor_id=world["admin"])
        await db.commit()
    assert again == []


@pytest.mark.asyncio
async def test_dl_verifying_a_departed_pair_gets_no_bonus() -> None:
    """DL z rolą rekrutera daje „Zweryfikowany” parze po odejściu — premia
    rekrutera dalej wskazuje osobę, która odeszła (decyzja Artura 28.10)."""
    world = await _world()
    await _deactivate(world)
    cand = world["candidates"][4]
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=cand,
                job_id=world["jobs"][1],
                stage=PipelineStage.verified,
                moved_by=world["dl_b"],
                moved_at=T0 + timedelta(hours=2),
            )
        )
        await db.flush()
        verifiers = await placement_bonuses.load_verifiers(
            db, {(cand, world["jobs"][1])}
        )
        assert verifiers[(cand, world["jobs"][1])] == world["recruiter"]
        contract = Contract(
            candidate_id=cand,
            client_id=world["client_a"],
            job_id=world["jobs"][1],
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=40),
            rate_client=Decimal("150"),
            rate_candidate=Decimal("104"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
        )
        context = await placement_bonuses.load_context(db, [contract])
        assert context.people(contract)[1] == world["recruiter"]
        await db.rollback()


@pytest.mark.asyncio
async def test_open_care_closes_when_the_pair_ends_or_owner_changes() -> None:
    world = await _world()
    await _deactivate(world)
    cand = world["candidates"]
    async with AsyncSessionLocal() as db:
        before = await departure_care.open_care(db, caretaker_id=world["dl_a"])
        assert {r.candidate_id for r in before} == {cand[0], cand[1]}
        db.add(
            CandidateStage(
                candidate_id=cand[1],
                job_id=world["jobs"][0],
                stage=PipelineStage.rejected,
                moved_by=world["dl_a"],
                moved_at=T0 + timedelta(hours=3),
            )
        )
        owner = await db.get(CandidateJobOwner, (cand[0], world["jobs"][0]))
        owner.owner_user_id = world["other"]
        await db.flush()
        assert await departure_care.open_care(db, caretaker_id=world["dl_a"]) == []
        await db.rollback()


@pytest.mark.asyncio
async def test_follow_up_and_interview_default_go_to_the_caretaker() -> None:
    world = await _world()
    await _deactivate(world)
    pair = (world["candidates"][0], world["jobs"][0])
    async with AsyncSessionLocal() as db:
        assert await departure_care.caretaker_ids(db, [pair]) == {pair: world["dl_a"]}
        from app.services.interview_slots import default_recruiter_ids

        assert (await default_recruiter_ids(db, [pair]))[pair] == world["dl_a"]


@pytest.mark.asyncio
async def test_reminder_once_after_five_business_days() -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, world["recruiter"])
        user.is_active = False
        # Przejęcie w poniedziałek 12.10.2026.
        await departure_care.hand_over(db, user, actor_id=world["admin"], now=T0)
        # Dzwonek przejęcia z 12.10 — dobowy filtr duplikatów liczy dzień wpisu.
        await db.execute(
            update(Notification)
            .where(
                Notification.notification_type == NotificationType.departed_pairs_care,
                Notification.related_entity_id == world["recruiter"],
            )
            .values(created_at=T0)
        )
        # Piąty dzień roboczy jeszcze nie minął w czwartek 15.10.
        assert await departure_care.send_reminders(db, T0 + timedelta(days=3)) == 0
        # Poniedziałek 26.10, 10:00 czasu firmy: 10 dni roboczych po przejęciu.
        later = T0 + timedelta(days=14)
        assert await departure_care.send_reminders(db, later) == 3
        assert await departure_care.send_reminders(db, later + timedelta(days=1)) == 0
        overdue = await departure_care.overdue_by_caretaker(db, later)
        assert {o["user_id"]: o["pairs"] for o in overdue}[world["dl_a"]] == 2
        await db.rollback()


@pytest.mark.asyncio
async def test_sweep_picks_up_compass_deactivation_without_a_direct_call() -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, world["recruiter"])
        user.is_active = False
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="compass_lifecycle_deactivated",
                user_id=None,
                details={},
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await departure_care.sweep(db) >= 4
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows = await departure_care.open_care(db, departed_id=world["recruiter"])
        assert len(rows) == 4
