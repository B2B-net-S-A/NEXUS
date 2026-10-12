"""Dzwonek „nasz konsultant w innej rekrutacji” (12.10.2026, D3 i D4).

Delivery Lead klienta, u którego osoba pracuje, dowiaduje się, że jej CV
poszło do innego klienta albo że została tam zatrudniona. Samo dodanie do
rekrutacji nie dzwoni — to mówi znacznik „Pracuje u nas”.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.scheduling import business_today
from app.models.notification import NotificationType
from app.schemas.candidate import EmploymentMarker, EmploymentMarkerClient
from app.services.consultant_elsewhere_notifications import (
    EVENT_CV_SENT,
    EVENT_HIRED,
    bell_content,
    clients_elsewhere,
    employment_phrase,
    stage_event,
)

# ── reguła (bez bazy) ───────────────────────────────────────────────────────


def _def(
    name: str,
    order: int,
    *,
    code: str | None = None,
    category: str = "internal",
    terminal_type: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        order=order,
        legacy_enum_value=code,
        category=category,
        terminal_type=terminal_type,
    )


VERIFIED = _def("Zweryfikowany", 3, code="verified")
CV_SENT = _def("CV wysłane", 5, code="cv_sent", category="external")
INTERVIEW = _def("Rozmowa u klienta", 6, code="client_interview", category="external")
HIRED = _def("Zatrudniony", 9, code="hired", category="terminal", terminal_type="hired")
REJECTED = _def(
    "Odrzucony", 10, code="rejected", category="terminal", terminal_type="rejected"
)


@pytest.mark.parametrize(
    "new, previous, code, expected",
    [
        (CV_SENT, VERIFIED, "cv_sent", EVENT_CV_SENT),
        (CV_SENT, None, "cv_sent", EVENT_CV_SENT),
        (HIRED, INTERVIEW, "hired", EVENT_HIRED),
        # Ruch wstecz (z rozmowy z powrotem na „CV wysłane”) nie dzwoni.
        (CV_SENT, INTERVIEW, "cv_sent", None),
        (CV_SENT, CV_SENT, "cv_sent", None),
        (INTERVIEW, CV_SENT, "client_interview", None),
        (REJECTED, CV_SENT, "rejected", None),
        (VERIFIED, None, "verified", None),
    ],
)
def test_stage_event_reads_forward_moves_to_cv_sent_and_hired(
    new, previous, code, expected
):
    assert stage_event(new, previous, stage_code=code) == expected


def test_stage_event_recognises_a_template_stage_by_its_terminal_type():
    """Etap z szablonu przeniesionego z Traffita: własna nazwa, bez kodu."""
    placed = _def("Placement", 9, category="terminal", terminal_type="hired")

    assert stage_event(placed, INTERVIEW, stage_code=None) == EVENT_HIRED


def test_stage_event_reads_a_row_without_stage_definition_from_its_code():
    assert stage_event(None, None, stage_code="cv_sent") == EVENT_CV_SENT
    assert stage_event(None, None, stage_code="hired") == EVENT_HIRED
    assert stage_event(None, None, stage_code="screening") is None


def _client(
    client_id: int, name: str, phase: str = "working", **extra
) -> EmploymentMarkerClient:
    return EmploymentMarkerClient(
        client_id=client_id, client_name=name, phase=phase, **extra
    )


def test_clients_elsewhere_drops_the_recruitment_client_family():
    marker = EmploymentMarker(
        phase="working",
        source="contract",
        clients=[_client(1, "Obecny"), _client(2, "Klient rekrutacji")],
    )

    assert [c.client_id for c in clients_elsewhere(marker, {2, 3})] == [1]
    assert clients_elsewhere(None, {2}) == []


def test_employment_phrase_names_working_and_starting_clients():
    assert (
        employment_phrase([_client(1, "Bank Przykładowy")])
        == "Pracuje u nas u klienta Bank Przykładowy."
    )
    assert (
        employment_phrase(
            [
                _client(1, "Bank Przykładowy"),
                _client(
                    2, "Telekom Przykładowy", "starting", starts_on=date(2026, 11, 1)
                ),
            ]
        )
        == "Pracuje u nas u klienta Bank Przykładowy i zaczyna u klienta "
        "Telekom Przykładowy od 01.11.2026."
    )


def test_hired_bell_carries_the_recruiters_answer_and_changes_nothing():
    title, message = bell_content(
        event=EVENT_HIRED,
        candidate_name="Anna Przykładowa",
        clients=[_client(1, "Bank Przykładowy")],
        job_title="Senior Java Developer",
        job_client_name="Ubezpieczenia Przykładowe",
        mover_name="Olga Rekruterska",
        hired_engagement="switch",
    )

    assert title == "Zatrudnienie w innej rekrutacji: Anna Przykładowa"
    assert message == (
        "Olga Rekruterska oznaczył(a) zatrudnienie osoby Anna Przykładowa "
        "w rekrutacji „Senior Java Developer” (Ubezpieczenia Przykładowe). "
        "Pracuje u nas u klienta Bank Przykładowy. "
        "Rekruter: przechodzi do nowego klienta, obecna współpraca się kończy. "
        "Obecna umowa i zamówienie zostają bez zmian, dopóki ich nie zakończysz."
    )


def test_hired_bell_without_an_answer_says_so():
    """Podpis w Generatorze albo automat — okna z pytaniem nie było."""
    _, message = bell_content(
        event=EVENT_HIRED,
        candidate_name="Anna Przykładowa",
        clients=[_client(1, "Bank Przykładowy")],
        job_title="Senior Java Developer",
        job_client_name=None,
        mover_name=None,
        hired_engagement=None,
    )

    assert "Ktoś z zespołu oznaczył(a) zatrudnienie" in message
    assert "Nie podano, co z obecną współpracą." in message


def test_cv_sent_bell_is_short_and_carries_no_amounts():
    title, message = bell_content(
        event=EVENT_CV_SENT,
        candidate_name="Anna Przykładowa",
        clients=[_client(1, "Bank Przykładowy")],
        job_title="Senior Java Developer",
        job_client_name="Ubezpieczenia Przykładowe",
        mover_name="Olga Rekruterska",
        hired_engagement=None,
    )

    assert title == "CV wysłane do innego klienta: Anna Przykładowa"
    assert message == (
        "Olga Rekruterska wysłał(a) CV osoby Anna Przykładowa w rekrutacji "
        "„Senior Java Developer” (Ubezpieczenia Przykładowe). "
        "Pracuje u nas u klienta Bank Przykładowy."
    )


# ── na prawdziwym schemacie ─────────────────────────────────────────────────


async def _seed(*, with_lead: bool = True) -> dict:
    """Osoba z trwającą umową u klienta X i rekrutacja u klienta Y."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus
    from app.models.job import Job, JobStatus
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]

    def user(label: str, role: UserRole) -> User:
        return User(
            email=f"elsewhere-{label}-{tag}@example.com",
            password_hash="test-only",
            name=f"{label.capitalize()} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
        )

    async with AsyncSessionLocal() as db:
        current = Client(name=f"ElsewhereCurrent-{tag}")
        target = Client(name=f"ElsewhereTarget-{tag}")
        candidate = Candidate(
            name="Anna",
            lastname=f"Elsewhere-{tag}",
            email=f"elsewhere-{tag}@example.com",
        )
        lead = user("lead", UserRole.delivery_lead)
        recruiter = user("recruiter", UserRole.recruiter)
        admin = user("admin", UserRole.admin)
        db.add_all([current, target, candidate, lead, recruiter, admin])
        await db.flush()
        job = Job(
            title=f"ElsewhereJob-{tag}", status=JobStatus.published, client_id=target.id
        )
        db.add_all(
            [
                job,
                Contract(
                    candidate_id=candidate.id,
                    client_id=current.id,
                    start_date=business_today() - timedelta(days=90),
                    status=ContractStatus.active,
                ),
            ]
        )
        if with_lead:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=lead.id, client_id=current.id, is_head=True
                )
            )
        await db.commit()
        return {
            "tag": tag,
            "current": current.id,
            "target": target.id,
            "candidate": candidate.id,
            "job": job.id,
            "lead": lead.id,
            "recruiter": recruiter.id,
            "admin": admin.id,
        }


async def _move(
    world: dict, stage: str, *, mover_key: str = "recruiter", **kwargs
) -> int:
    """Wiersz etapu (stary zapis, bez definicji) + dzwonek — jak efekt po commicie."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.user import User
    from app.services.consultant_elsewhere_notifications import (
        notify_current_client_leads,
    )

    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=world["candidate"],
            job_id=world["job"],
            stage=PipelineStage(stage),
            moved_by=world[mover_key],
            moved_at=datetime.now(timezone.utc),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        sent = await notify_current_client_leads(
            db,
            new_stage=row,
            previous_stage=None,
            job=await db.get(Job, world["job"]),
            candidate=await db.get(Candidate, world["candidate"]),
            mover=await db.get(User, world[mover_key]),
            **kwargs,
        )
        await db.commit()
        return sent


async def _bells(user_id: int) -> list:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type
                == NotificationType.consultant_in_other_recruitment,
            )
            .order_by(Notification.id)
        )
        return list(rows.scalars().all())


async def test_cv_sent_rings_the_current_clients_lead_once_per_pair():
    world = await _seed()

    assert await _move(world, "cv_sent") == 1
    # Karta cofnięta i wysłana jeszcze raz: nowy wiersz etapu, ten sam temat.
    assert await _move(world, "cv_sent") == 0

    [bell] = await _bells(world["lead"])
    assert bell.title == f"CV wysłane do innego klienta: Anna Elsewhere-{world['tag']}"
    assert f"ElsewhereCurrent-{world['tag']}" in bell.message
    assert bell.link == f"/jobs/{world['job']}?candidate={world['candidate']}"
    assert bell.related_entity_type == "candidate_stage"
    # Admin jest zapasem, nie stałym odbiorcą — klient ma Delivery Leada.
    assert await _bells(world["admin"]) == []
    # Rekruter, który wysłał CV, nie dzwoni sam do siebie.
    assert await _bells(world["recruiter"]) == []


async def test_hire_rings_again_and_carries_the_answer():
    world = await _seed()
    await _move(world, "cv_sent")

    assert await _move(world, "hired", hired_engagement="parallel") == 1

    bells = await _bells(world["lead"])
    assert [b.title.split(":")[0] for b in bells] == [
        "CV wysłane do innego klienta",
        "Zatrudnienie w innej rekrutacji",
    ]
    assert "Rekruter: będzie pracować równolegle u obu klientów." in bells[1].message


async def test_the_lead_who_moves_the_card_is_not_replaced_by_admins():
    """Jedyny Delivery Lead klienta sam wysyła CV — nikt nie musi się dowiadywać."""
    world = await _seed()

    assert await _move(world, "cv_sent", mover_key="lead") == 0
    assert await _bells(world["lead"]) == []
    assert await _bells(world["admin"]) == []


async def test_client_without_a_lead_falls_back_to_admins():
    world = await _seed(with_lead=False)

    assert await _move(world, "cv_sent") >= 1
    [bell] = await _bells(world["admin"])
    assert bell.title.startswith("CV wysłane do innego klienta")
    assert await _bells(world["lead"]) == []


async def test_recruitment_at_the_clients_own_client_rings_nobody():
    """Praca u klienta TEJ rekrutacji to dzisiejsze ostrzeżenie przy ruchu."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    world = await _seed()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job"])
        job.client_id = world["current"]
        await db.commit()

    assert await _move(world, "cv_sent") == 0
    assert await _move(world, "hired") == 0
    assert await _bells(world["lead"]) == []


async def test_other_stages_do_not_ring():
    world = await _seed()

    assert await _move(world, "screening") == 0
    assert await _move(world, "client_interview") == 0
    assert await _bells(world["lead"]) == []


async def test_employed_elsewhere_client_ids_names_the_current_client():
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.consultant_elsewhere_notifications import (
        employed_elsewhere_client_ids,
    )

    world = await _seed()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job"])
        found = await employed_elsewhere_client_ids(
            db, candidate_id=world["candidate"], job=job
        )

    assert found == [world["current"]]
