"""Kto dostaje dzwonek i mail, gdy odbiorców wybiera zapytanie — wzorzec z bazą.

Uzupełnia ``test_notify_golden.py`` (bramy dzwonka i maila liczone bez bazy).
Tu odbiorców wybiera producent zapytaniem do bazy: Rada i admini, osoby
przypisane do rekrutacji, rekruter kandydata, Delivery Lead klienta. Test
zakłada w jednej transakcji obsadę fikcyjnych kont i obiektów (firma: jedno
konto na rolę z ``PERSONAS``; rekrutacja z prowadzącym, DL-em, przypisanymi,
uczestnikiem kategorii i poprzednim rekruterem; dwóch kandydatów), woła
funkcję producenta i bramkę dzwonka (``filter_notification_recipients``,
ta sama co w ``emit``), a na końcu wycofuje transakcję — nic nie zostaje
w bazie wspólnej z innymi testami.

Wynik porównuje z ``tests/data/notify_golden/relations_db.json``. Zmiana =
czerwony test z listą „rodzaj: ±konto (było/jest)”. Zamierzoną zmianę
przegeneruj i dołącz diff do PR-a:

    cd backend && NOTIFY_GOLDEN_WRITE=1 python -m pytest \\
        tests/test_notify_golden.py tests/test_notify_golden_db.py

Przypadki z historii mają osobne asercje (``test_historia_*``): wzorzec da się
przegenerować, a te asercje trzeba świadomie zmienić.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from tests._authz_matrix import PERSONAS
from tests._notify_matrix import WRITE_ENV, check_or_write, failure_message, kind

pytestmark = pytest.mark.not_static

_WRITE = os.environ.get(WRITE_ENV) == "1"

# Relacje do rekrutacji: etykieta = rola (relacja). Konta firmy bez relacji
# mają etykietę persony, czyli „spoza zespołu”.
LEAD = "recruiter (prowadzący rekrutację)"
JOB_DL = "delivery_lead (DL rekrutacji)"
ASSIGNED = "recruiter (aktywne przypisanie)"
AUTHOR = "recruiter (aktywne przypisanie, autor wiadomości)"
CANDIDATE_RECRUITER = "recruiter (rekruter kandydata, aktywne przypisanie)"
COLLABORATOR = "recruiter (współpracownik dodany ręcznie)"
CATEGORY_CC = "recruiter (uczestnik kategorii, auto_cc)"
PARKED = "recruiter (poprzedni rekruter)"
CLIENT_DL = "delivery_lead (DL klienta)"
BOARD_OFF = "board (konto wyłączone)"
NAMED_BOARD_REPORT = "admin (imienne nadanie maila Rady)"

#: Persony bez imiennych nadań — w bazie liczy się rola i polityka sekcji.
_ROLE_PERSONAS = tuple(
    persona for persona in PERSONAS if not persona.grants and not persona.revokes
)
_ADMIN_LIKE = {"admin", NAMED_BOARD_REPORT}


@asynccontextmanager
async def _isolated_session() -> AsyncIterator[AsyncSession]:
    """Sesja w transakcji zewnętrznej; commit producenta to tylko punkt zapisu."""

    async with engine.connect() as conn:
        outer = await conn.begin()
        db = AsyncSessionLocal(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            await db.close()
            await outer.rollback()


class _Cast:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ids: dict[str, int] = {}
        self.tag = uuid.uuid4().hex[:8]

    async def user(
        self,
        label: str,
        role: UserRole,
        extra: tuple[UserRole, ...] = (),
        **columns,
    ) -> User:
        slug = "".join(ch if ch.isalnum() else "-" for ch in label)[:40]
        user = User(
            email=f"notify-golden-{slug}-{self.tag}@example.com",
            name=f"Golden {label}",
            role=role,
            roles=[role.value, *(r.value for r in extra)],
            is_active=columns.pop("is_active", True),
            email_verified=True,
            profile_completed=True,
            **columns,
        )
        self.db.add(user)
        await self.db.flush()
        self.ids[label] = user.id
        return user

    @property
    def labels(self) -> dict[int, str]:
        return {uid: label for label, uid in self.ids.items()}


async def _seed(db: AsyncSession) -> tuple[_Cast, dict[str, int]]:
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
    from app.models.job_previous_recruiter import JobPreviousRecruiter
    from app.models.app_setting import AppSetting
    from app.models.job_work_assignment import JobWorkAssignment
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.services.notification_role_mutes import SETTING_KEY as ROLE_MUTES

    # Wyłączenie grupy dla roli zostawione w bazie przez inny test ucięłoby tu
    # odbiorców. Usunięcie wraca razem z transakcją — inni go nie widzą.
    await db.execute(delete(AppSetting).where(AppSetting.key == ROLE_MUTES))
    cast = _Cast(db)
    for persona in _ROLE_PERSONAS:
        await cast.user(persona.key, persona.role, persona.extra_roles)
    await cast.user(BOARD_OFF, UserRole.board, is_active=False)
    await cast.user(NAMED_BOARD_REPORT, UserRole.admin, receives_board_report=True)

    for label in (
        LEAD,
        ASSIGNED,
        AUTHOR,
        CANDIDATE_RECRUITER,
        COLLABORATOR,
        CATEGORY_CC,
        PARKED,
    ):
        await cast.user(label, UserRole.recruiter)
    await cast.user(JOB_DL, UserRole.delivery_lead)
    await cast.user(CLIENT_DL, UserRole.delivery_lead)

    client = Client(name=f"Notify golden {cast.tag}")
    bare_client = Client(name=f"Notify golden bez DL {cast.tag}")
    db.add_all([client, bare_client])
    await db.flush()
    db.add(
        DeliveryLeadClientAssignment(
            delivery_lead_user_id=cast.ids[CLIENT_DL], client_id=client.id
        )
    )
    job = Job(
        title=f"Notify golden {cast.tag}",
        client_id=client.id,
        recruiter_id=cast.ids[LEAD],
        delivery_lead_id=cast.ids[JOB_DL],
        status=JobStatus.published,
        is_open=True,
    )
    db.add(job)
    await db.flush()
    now = datetime.now(timezone.utc)
    for label in (ASSIGNED, AUTHOR, CANDIDATE_RECRUITER):
        db.add(
            JobWorkAssignment(
                job_id=job.id,
                user_id=cast.ids[label],
                role="recruiter",
                source="manual",
                state="active",
                assigned_at=now,
            )
        )
    for label, source in (
        (COLLABORATOR, JobCollaboratorSource.manual),
        (CATEGORY_CC, JobCollaboratorSource.auto_cc),
        (PARKED, JobCollaboratorSource.manual),
    ):
        db.add(
            JobCollaborator(
                job_id=job.id,
                user_id=cast.ids[label],
                added_by=cast.ids[LEAD],
                source=source,
            )
        )
    db.add(
        JobPreviousRecruiter(
            job_id=job.id,
            user_id=cast.ids[PARKED],
            via="collaborator",
            reason="priority",
        )
    )
    await db.flush()
    return cast, {"job": job.id, "client": client.id, "bare_client": bare_client.id}


async def _gate(db, ids, ntype: NotificationType, **context) -> list[int]:
    """Bramka dzwonka — ta sama, którą ``emit`` pyta przed zapisem wiersza."""

    from app.services.notification_access import filter_notification_recipients

    users = await filter_notification_recipients(db, ids, ntype, **context)
    return [user.id for user in users]


async def _stage_world(db: AsyncSession, cast: _Cast, job_id: int) -> dict:
    """Szablon „Nowe → Odrzucony” z jedną regułą „rekruter rekrutacji” i dwóch
    kandydatów: z własnym rekruterem (właściciel procesu) i bez rekrutera."""

    from app.models.candidate import Candidate
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
        TerminalType,
    )
    from app.models.recruitment_process import RecruitmentProcess
    from app.models.stage_notification import RecipientType, StageNotificationRule

    template = PipelineTemplate(name=f"Notify golden {cast.tag}")
    db.add(template)
    await db.flush()
    new = PipelineStageDef(
        template_id=template.id,
        name="Nowe",
        order=1,
        category=StageCategoryEnum.internal,
        legacy_enum_value="new",
    )
    rejected = PipelineStageDef(
        template_id=template.id,
        name="Odrzucony",
        order=9,
        category=StageCategoryEnum.terminal,
        is_terminal=True,
        terminal_type=TerminalType.rejected,
        legacy_enum_value="rejected",
    )
    db.add_all([new, rejected])
    await db.flush()
    db.add(
        StageNotificationRule(
            stage_def_id=rejected.id,
            recipient_type=RecipientType.job_recruiter,
            notify_inapp=True,
            notify_email=False,
        )
    )
    owned = Candidate(name="Golden", lastname=f"Z rekruterem {cast.tag}")
    orphan = Candidate(name="Golden", lastname=f"Bez rekrutera {cast.tag}")
    db.add_all([owned, orphan])
    await db.flush()
    db.add(
        RecruitmentProcess(
            job_id=job_id,
            candidate_id=owned.id,
            attempt_no=1,
            owner_user_id=cast.ids[CANDIDATE_RECRUITER],
        )
    )
    await db.flush()
    return {"new": new, "rejected": rejected, "owned": owned, "orphan": orphan}


async def _stage_move(db, world, job, candidate, mover_id) -> list[int]:
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services.stage_notification_resolver import resolve_recipients

    previous = CandidateStage(
        candidate_id=candidate.id,
        job_id=job.id,
        stage=PipelineStage.new,
        stage_def_id=world["new"].id,
        moved_by=None,
    )
    moved = CandidateStage(
        candidate_id=candidate.id,
        job_id=job.id,
        stage=PipelineStage.rejected,
        stage_def_id=world["rejected"].id,
        moved_by=mover_id,
    )
    recipients = await resolve_recipients(
        db,
        new_stage=moved,
        previous_stage=previous,
        job=job,
        candidate=candidate,
        mover_user_id=mover_id,
    )
    return [r.user_id for r in recipients if r.notify_inapp]


async def _compute(db: AsyncSession) -> tuple[dict[str, dict], dict[str, list[str]]]:
    from app.models.app_setting import AppSetting
    from app.models.job import Job
    from app.services import (
        candidate_data_access_alerts,
        hired_order_status,
        job_p0,
        new_person_setup,
    )
    from app.services.board import notify as board_notify
    from app.services.board import votes as board_votes
    from app.services.board_placement_alerts import board_members
    from app.services.delivery_alert_recipients import (
        load_delivery_alert_recipient_scope,
    )
    from app.services.job_membership import list_job_assigned_ids
    from app.services.mention_parser import parse_mentions
    from app.services.month_check import mail as month_check_mail
    from app.services.stage_notification_resolver import resolve_recipients
    from app.tasks import daily_digest_email, kpi_email_reports

    cast, refs = await _seed(db)
    labels = cast.labels
    out: dict[str, dict] = {}

    def put(key: str, source, ids) -> None:
        out[key] = kind(source, "firma i rekrutacja", labels, ids).as_json()

    # ── Rada nadzorcza ──
    board = await board_notify.recipient_ids(db)
    for ntype in (
        NotificationType.board_krs_entry,
        NotificationType.board_meeting_pack,
    ):
        put(
            f"{ntype.value} [dzwonek do Rady]",
            board_notify.recipient_ids,
            await _gate(db, board, ntype),
        )
    put(
        "board_vote [wynik uchwały]",
        board_notify.recipient_ids,
        await _gate(db, board, NotificationType.board_vote),
    )
    put(
        "board_vote [projekt uchwały: skład z wysyłki]",
        board_votes.board_member_ids,
        await _gate(
            db, await board_votes.board_member_ids(db), NotificationType.board_vote
        ),
    )
    put(
        "board_monthly_report [mail: Podsumowanie Rady]",
        kpi_email_reports._board_recipients,
        [u.id for u in await kpi_email_reports._board_recipients(db)],
    )
    put(
        "board_placement_alert [mail]",
        board_members,
        [u.id for u in await board_members(db)],
    )

    # ── Alarmy i sprawy całej firmy ──
    put(
        "candidate_data_access_alert",
        candidate_data_access_alerts._recipients,
        await _gate(
            db,
            await candidate_data_access_alerts._recipients(db),
            NotificationType.candidate_data_access_alert,
        ),
    )
    put(
        "new_person_signed_in",
        new_person_setup.recipients,
        await _gate(
            db,
            await new_person_setup.recipients(db),
            NotificationType.new_person_signed_in,
        ),
    )
    finance = await hired_order_status.finance_recipient_ids(db)
    for ntype in (
        NotificationType.hired_order_missing,
        NotificationType.cpro_invoice_buyer,
    ):
        put(
            ntype.value,
            hired_order_status.finance_recipient_ids,
            await _gate(db, finance, ntype),
        )
    put(
        "job_p0_requested",
        job_p0.head_of_recruitment_recipients,
        await _gate(
            db,
            await job_p0.head_of_recruitment_recipients(db),
            NotificationType.job_p0_requested,
        ),
    )
    put(
        "daily_digest [mail: poranny skrót]",
        daily_digest_email._recipients,
        [u.id for u in await daily_digest_email._recipients(db)],
    )
    put(
        "kpi_weekly_report [mail]",
        kpi_email_reports._recipients,
        [
            u.id
            for u in await kpi_email_reports._recipients(
                db, (UserRole.head_of_recruitment,)
            )
        ],
    )
    await db.merge(
        AppSetting(key=month_check_mail.SETTING_KEY, value={"to_finance": True})
    )
    await db.flush()
    by_email = dict(
        (await db.execute(select(User.email, User.id).where(User.id.in_(labels)))).all()
    )
    put(
        "month_check_report [mail, wysyłka do Finansów włączona]",
        month_check_mail.recipients,
        [by_email.get(address) for address in await month_check_mail.recipients(db)],
    )

    # ── Klient: koniec zamówienia (alerty Delivery) ──
    scope = await load_delivery_alert_recipient_scope(db)
    ending = NotificationType.client_order_ending_30d
    for label, client_id in (
        ("klient z DL-em", refs["client"]),
        ("klient bez DL-a", refs["bare_client"]),
    ):
        put(
            f"{ending.value} [{label}]",
            "app.services.delivery_alert_recipients."
            "DeliveryAlertRecipientScope.bell_recipients",
            await _gate(db, scope.bell_recipients(client_id, ending), ending),
        )

    # ── Czat rekrutacji ──
    job_id = refs["job"]
    author = cast.ids[AUTHOR]
    chat = {"related_entity_type": "job_chat_message", "link": f"/jobs/{job_id}"}
    assigned = [uid for uid in await list_job_assigned_ids(db, job_id) if uid != author]
    put(
        "job_chat_message [czat rekrutacji, pisze przypisany]",
        list_job_assigned_ids,
        await _gate(db, assigned, NotificationType.job_chat_message, **chat),
    )
    everyone = [
        uid
        for uid in await parse_mentions(db, "@wszyscy pilne", job_id)
        if uid != author
    ]
    put(
        "job_chat_mention [@wszyscy w czacie rekrutacji]",
        parse_mentions,
        await _gate(db, everyone, NotificationType.job_chat_mention, **chat),
    )

    # ── Ruch etapu (Nowe → Odrzucony, reguła „rekruter rekrutacji”) ──
    world = await _stage_world(db, cast, job_id)
    job = await db.get(Job, job_id)
    for label, candidate, mover in (
        ("kandydat z rekruterem, przesuwa inny rekruter z zespołu", "owned", ASSIGNED),
        ("kandydat z rekruterem, ruch automatu", "owned", None),
        ("kandydat bez rekrutera, przesuwa rekruter z zespołu", "orphan", ASSIGNED),
        ("kandydat bez rekrutera, ruch automatu", "orphan", None),
    ):
        put(
            f"stage_rule [Nowe → Odrzucony: {label}]",
            resolve_recipients,
            await _stage_move(
                db,
                world,
                job,
                world[candidate],
                cast.ids[mover] if mover else None,
            ),
        )
    return out, {"firma i rekrutacja": sorted(labels.values())}


@pytest.fixture(scope="module")
async def relations_db() -> tuple[dict[str, dict], dict[str, list[str]]]:
    async with _isolated_session() as db:
        return await _compute(db)


def _recipients(relations_db, key: str) -> set[str]:
    kinds, _ = relations_db
    return set(kinds[key]["odbiorcy"])


async def test_db_relations_match_golden(relations_db) -> None:
    kinds, casts = relations_db
    lines = check_or_write(
        "relations_db",
        kinds,
        write=_WRITE,
        description=(
            "Wybór odbiorców liczony zapytaniami producenta na obsadzie "
            "fikcyjnych kont (lista w „obsady”), po bramce dzwonka. Etykieta "
            "konta: persona (spoza zespołu) albo „rola (relacja)”."
        ),
        extra={"obsady": casts},
    )
    assert not lines, failure_message(lines)


# ── Przypadki z historii ─────────────────────────────────────────────────────


async def test_historia_materialy_rady_tylko_rada_i_admini(relations_db) -> None:
    """02.11.2026 „Podsumowanie Rady” dostało 11 osób (5 z Finansów).
    Dzwonki Rady (wpis KRS, pakiet na posiedzenie, wynik uchwały): aktywna
    Rada i admini. Projekt uchwały: tylko skład Rady. Mail z wynikami: Rada
    i osoba z imiennym nadaniem — sama rola admin go nie otwiera."""

    for key in (
        "board_krs_entry [dzwonek do Rady]",
        "board_meeting_pack [dzwonek do Rady]",
        "board_vote [wynik uchwały]",
    ):
        assert _recipients(relations_db, key) == {"board"} | _ADMIN_LIKE, key
    assert _recipients(
        relations_db, "board_vote [projekt uchwały: skład z wysyłki]"
    ) == {"board"}
    report = _recipients(relations_db, "board_monthly_report [mail: Podsumowanie Rady]")
    assert report == {"board", NAMED_BOARD_REPORT}
    for key in (
        "board_krs_entry [dzwonek do Rady]",
        "board_monthly_report [mail: Podsumowanie Rady]",
    ):
        got = _recipients(relations_db, key)
        for outsider in ("finance", "head_of_recruitment", "delivery_lead", BOARD_OFF):
            assert outsider not in got, (key, outsider)


async def test_historia_czat_rekrutacji_tylko_przypisani(relations_db) -> None:
    """18.11.2026: dzwonek o wiadomości w czacie rekrutacji szedł do całego
    „zespołu” z nagłówka (admini, uczestnicy kategorii). Dostają go tylko
    przypisani, poza autorem; ta sama lista co ``@wszyscy``."""

    expected = {LEAD, JOB_DL, ASSIGNED, CANDIDATE_RECRUITER, COLLABORATOR}
    message = _recipients(
        relations_db, "job_chat_message [czat rekrutacji, pisze przypisany]"
    )
    assert message == expected
    for outsider in (
        "admin",
        "head_of_recruitment",
        "recruiter",
        CATEGORY_CC,
        PARKED,
        AUTHOR,
    ):
        assert outsider not in message, outsider
    assert (
        _recipients(relations_db, "job_chat_mention [@wszyscy w czacie rekrutacji]")
        == expected
    )


async def test_historia_ruch_etapu_tylko_rekruter_kandydata(relations_db) -> None:
    """10.11 i 18.11.2026: ruch etapu cudzego kandydata dzwonił prowadzącemu
    (49%, potem 61% dzwonków ruchu). Dostaje go rekruter kandydata — nie
    prowadzący i nie inni rekruterzy z zespołu."""

    prefix = "stage_rule [Nowe → Odrzucony: "
    for label in (
        "kandydat z rekruterem, przesuwa inny rekruter z zespołu",
        "kandydat z rekruterem, ruch automatu",
    ):
        assert _recipients(relations_db, f"{prefix}{label}]") == {CANDIDATE_RECRUITER}
    # Kandydat w „Nowych” bez rekrutera należy do tego, kto go przesunął —
    # ruch nie dzwoni prowadzącemu jak o jego człowieku (18.11.2026).
    assert (
        _recipients(
            relations_db,
            f"{prefix}kandydat bez rekrutera, przesuwa rekruter z zespołu]",
        )
        == set()
    )
    others = {LEAD, ASSIGNED, AUTHOR, COLLABORATOR, CATEGORY_CC, PARKED, "recruiter"}
    for key in (k for k in relations_db[0] if k.startswith(prefix) and "przesuwa" in k):
        assert not _recipients(relations_db, key) & others, key


def test_seed_labels_are_unique() -> None:
    labels = [persona.key for persona in _ROLE_PERSONAS] + [
        LEAD,
        JOB_DL,
        ASSIGNED,
        AUTHOR,
        CANDIDATE_RECRUITER,
        COLLABORATOR,
        CATEGORY_CC,
        PARKED,
        CLIENT_DL,
        BOARD_OFF,
        NAMED_BOARD_REPORT,
    ]
    assert len(labels) == len(set(labels))
