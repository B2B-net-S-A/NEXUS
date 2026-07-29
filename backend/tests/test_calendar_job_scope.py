"""Zakres oferty na zapisach kalendarza — obie strony bramki (P2-12 / P2-14).

#984 dołożył ``ensure_optional_job_membership`` do trzech tras zapisu
kalendarza (POST /calendar/events, PATCH /calendar/events/{id},
POST /calendar/events/m365-invite). Sama bramka jest potrzebna, ale w dwóch
miejscach mierzyła nie to, co trzeba:

- **P2-12** — kolejka kontaktu jest KANDYDATO-globalna: jeden właściciel
  prowadzi kandydata przez wszystkie jego otwarte oferty, a sprawę domyka
  dopiero spotkanie na KAŻDEJ z nich. Właścicielem zostaje się przez
  członkostwo w JEDNEJ z tych ofert, więc bramka blokowała zaprojektowane
  przekazanie na pozostałych — koordynator wręczał sprawę, której właściciel
  nie mógł domknąć.
- **P2-14** — w PATCH-u bramka biegła PO pętli ``setattr``, czyli przeciw
  wartości JUŻ zmienionej. Twórca wydarzenia tracił edycję własnego wpisu, gdy
  tylko wypadł z zespołu oferty (za surowo), a jawne ``"job_id": null``
  zerowało atrybut przed sprawdzeniem, więc odpięcie od oferty — razem z
  rozmontowaniem przekazania kontaktu — przechodziło bez żadnej kontroli
  (za luźno).

Każdy przypadek ma parę: kto MA dostać 403 i kto MUSI dalej przechodzić.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_contact import (
    CandidateContactCase,
    CandidateContactOpportunity,
    CandidateContactState,
)
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio

_START = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _new_user(db, role: UserRole = UserRole.recruiter) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    user = User(
        email=f"calscope-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"Cal Scope {suffix}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, pwd


async def _new_job(db, *, recruiter_id: Optional[int]) -> Job:
    suffix = uuid.uuid4().hex[:6]
    client = Client(name=f"CalScope Client {suffix}")
    db.add(client)
    await db.flush()
    job = Job(
        title=f"CalScope Job {suffix}",
        client_id=client.id,
        recruiter_id=recruiter_id,
        status=JobStatus.published,
    )
    db.add(job)
    await db.flush()
    return job


async def _new_candidate(db) -> Candidate:
    suffix = uuid.uuid4().hex[:8]
    candidate = Candidate(
        name="Cal",
        lastname=f"Scope-{suffix}",
        email=f"calscope-cand-{suffix}@example.com",
        status=CandidateStatus.active,
    )
    db.add(candidate)
    await db.flush()
    return candidate


async def _new_event(
    db,
    *,
    created_by: int,
    job_id: Optional[int],
    candidate_id: Optional[int],
    event_type: EventType = EventType.screening,
) -> CalendarEvent:
    event = CalendarEvent(
        title=f"CalScope Event {uuid.uuid4().hex[:6]}",
        event_type=event_type,
        start_time=_START,
        end_time=_START + timedelta(hours=1),
        all_day=False,
        candidate_id=candidate_id,
        job_id=job_id,
        created_by=created_by,
        status=EventStatus.scheduled,
    )
    db.add(event)
    await db.flush()
    return event


async def _open_contact_case(
    db, *, candidate_id: int, owner_user_id: int, job_ids: list[int]
) -> CandidateContactCase:
    """Sprawa kontaktu z otwartą szansą na każdej z podanych ofert."""
    case = CandidateContactCase(
        candidate_id=candidate_id,
        owner_user_id=owner_user_id,
        state=CandidateContactState.handoff_pending.value,
    )
    db.add(case)
    await db.flush()
    for job_id in job_ids:
        db.add(
            CandidateContactOpportunity(
                case_id=case.id,
                candidate_id=candidate_id,
                job_id=job_id,
                source="shortlist",
                linked_at=_START,
            )
        )
    await db.flush()
    return case


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_body(*, candidate_id: int, job_id: Optional[int]) -> dict[str, Any]:
    return {
        "title": "Screening",
        "event_type": "screening",
        "start_time": _START.isoformat(),
        "end_time": (_START + timedelta(hours=1)).isoformat(),
        "candidate_id": candidate_id,
        "job_id": job_id,
    }


@pytest_asyncio.fixture
async def scope_setup(app_client: AsyncClient) -> dict[str, Any]:
    """Właściciel sprawy jest członkiem oferty A, ale NIE oferty B ani C.

    Sprawa kontaktu obejmuje A i B — czyli dokładnie ten zakres, który
    koordynator już wręczył. Oferta C jest kontrolą negatywną.
    """
    async with AsyncSessionLocal() as db:
        owner, owner_pwd = await _new_user(db)
        stranger, stranger_pwd = await _new_user(db)
        job_a = await _new_job(db, recruiter_id=owner.id)
        job_b = await _new_job(db, recruiter_id=stranger.id)
        job_c = await _new_job(db, recruiter_id=stranger.id)
        candidate = await _new_candidate(db)
        await _open_contact_case(
            db,
            candidate_id=candidate.id,
            owner_user_id=owner.id,
            job_ids=[job_a.id, job_b.id],
        )
        await db.commit()
        data = {
            "owner_id": owner.id,
            "owner_email": owner.email,
            "owner_password": owner_pwd,
            "stranger_id": stranger.id,
            "stranger_email": stranger.email,
            "stranger_password": stranger_pwd,
            "job_a": job_a.id,
            "job_b": job_b.id,
            "job_c": job_c.id,
            "candidate_id": candidate.id,
        }
    data["owner_headers"] = await _login(
        app_client, data["owner_email"], data["owner_password"]
    )
    data["stranger_headers"] = await _login(
        app_client, data["stranger_email"], data["stranger_password"]
    )
    return data


# ── P2-12: tworzenie wydarzenia ──────────────────────────────────────────────


async def test_member_can_create_event_for_own_job(
    app_client: AsyncClient, scope_setup: dict[str, Any]
) -> None:
    resp = await app_client.post(
        "/api/calendar/events",
        headers=scope_setup["owner_headers"],
        json=_create_body(
            candidate_id=scope_setup["candidate_id"], job_id=scope_setup["job_a"]
        ),
    )
    assert resp.status_code == 201, resp.text


async def test_non_member_without_contact_case_cannot_create_event(
    app_client: AsyncClient, scope_setup: dict[str, Any], monkeypatch
) -> None:
    """Obca oferta bez żadnego tytułu do niej = 403. Bramka musi zostać."""
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    resp = await app_client.post(
        "/api/calendar/events",
        headers=scope_setup["owner_headers"],
        json=_create_body(
            candidate_id=scope_setup["candidate_id"], job_id=scope_setup["job_c"]
        ),
    )
    assert resp.status_code == 403, resp.text


async def test_contact_owner_can_create_meeting_for_foreign_job(
    app_client: AsyncClient, scope_setup: dict[str, Any], monkeypatch
) -> None:
    """P2-12: właściciel sprawy umawia spotkanie na ofercie spoza swojego zespołu.

    Bez tego sprawa jest nie do domknięcia — ``_recompute_case_after_
    opportunities`` wymaga spotkania na KAŻDEJ otwartej szansie, a jedyną
    ścieżką ustawienia ``meeting_event_id`` są właśnie trasy kalendarza.
    """
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    resp = await app_client.post(
        "/api/calendar/events",
        headers=scope_setup["owner_headers"],
        json=_create_body(
            candidate_id=scope_setup["candidate_id"], job_id=scope_setup["job_b"]
        ),
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        opportunity = await db.scalar(
            select(CandidateContactOpportunity).where(
                CandidateContactOpportunity.candidate_id == scope_setup["candidate_id"],
                CandidateContactOpportunity.job_id == scope_setup["job_b"],
            )
        )
    # Przekazanie faktycznie się zapisało — 201 nie jest tu pustym przebiegiem.
    assert opportunity is not None
    assert opportunity.meeting_event_id == resp.json()["id"]


async def test_contact_owner_scope_is_limited_to_own_case(
    app_client: AsyncClient, scope_setup: dict[str, Any], monkeypatch
) -> None:
    """Cudza sprawa nie nadaje zakresu — właścicielem jest ktoś inny."""
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    resp = await app_client.post(
        "/api/calendar/events",
        headers=scope_setup["stranger_headers"],
        json=_create_body(
            candidate_id=scope_setup["candidate_id"], job_id=scope_setup["job_a"]
        ),
    )
    assert resp.status_code == 403, resp.text


async def test_contact_owner_scope_requires_an_open_opportunity(
    app_client: AsyncClient, scope_setup: dict[str, Any], monkeypatch
) -> None:
    """Zamknięta szansa nie nadaje zakresu — przekazanie się skończyło."""
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateContactOpportunity).where(
                CandidateContactOpportunity.candidate_id == scope_setup["candidate_id"],
                CandidateContactOpportunity.job_id == scope_setup["job_b"],
            )
        )
        row.closed_at = _START
        row.closed_reason = "test"
        await db.commit()

    resp = await app_client.post(
        "/api/calendar/events",
        headers=scope_setup["owner_headers"],
        json=_create_body(
            candidate_id=scope_setup["candidate_id"], job_id=scope_setup["job_b"]
        ),
    )
    assert resp.status_code == 403, resp.text


async def test_contact_owner_scope_is_off_when_module_disabled(
    app_client: AsyncClient, scope_setup: dict[str, Any], monkeypatch
) -> None:
    """Flaga wyłączona (domyślnie na prod) → zero zmiany zachowania."""
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", False)
    resp = await app_client.post(
        "/api/calendar/events",
        headers=scope_setup["owner_headers"],
        json=_create_body(
            candidate_id=scope_setup["candidate_id"], job_id=scope_setup["job_b"]
        ),
    )
    assert resp.status_code == 403, resp.text


async def test_m365_invite_applies_the_same_scope_source(
    app_client: AsyncClient, scope_setup: dict[str, Any], monkeypatch
) -> None:
    """Ta sama para na zaproszeniu M365.

    Właściciel sprawy przechodzi bramkę i zatrzymuje się dopiero na braku
    połączenia z Microsoft 365 (412) — brak 403 jest tu dowodem przejścia,
    bez stawiania atrapy Graph API. Obcy dostaje 403 przed czymkolwiek.
    """
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    payload = {
        "candidate_id": scope_setup["candidate_id"],
        "title": "Rozmowa",
        "start": _START.isoformat(),
        "end": (_START + timedelta(hours=1)).isoformat(),
    }

    denied = await app_client.post(
        "/api/calendar/events/m365-invite",
        headers=scope_setup["owner_headers"],
        json={**payload, "job_id": scope_setup["job_c"]},
    )
    assert denied.status_code == 403, denied.text

    allowed = await app_client.post(
        "/api/calendar/events/m365-invite",
        headers=scope_setup["owner_headers"],
        json={**payload, "job_id": scope_setup["job_b"]},
    )
    assert allowed.status_code == 412, allowed.text


# ── P2-14: edycja wydarzenia ─────────────────────────────────────────────────


async def test_event_owner_may_edit_own_event_outside_the_job_team(
    app_client: AsyncClient, scope_setup: dict[str, Any]
) -> None:
    """P2-14 (a): zmiana pola niezwiązanego z ofertą nie dotyka zakresu oferty.

    ``user_can_mutate_event`` już zawęża do twórcy / admina / HoR, a wydarzenie
    powiązane z ofertą mógł stworzyć tylko ktoś, kto w chwili tworzenia
    przechodził bramkę. Po wypadnięciu z zespołu twórca dalej odwołuje i
    przekłada własne spotkanie.
    """
    async with AsyncSessionLocal() as db:
        event = await _new_event(
            db,
            created_by=scope_setup["owner_id"],
            job_id=scope_setup["job_b"],
            candidate_id=scope_setup["candidate_id"],
        )
        await db.commit()
        event_id = event.id

    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=scope_setup["owner_headers"],
        json={"status": "cancelled"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"


async def test_resending_an_unchanged_job_id_is_not_a_transition(
    app_client: AsyncClient, scope_setup: dict[str, Any]
) -> None:
    """Klient odsyłający cały obiekt nie robi przepięcia — nie może dostać 403.

    Bramkujemy zmianę wartości, nie obecność klucza w żądaniu; inaczej wystarczy
    zmiana kontraktu po stronie frontu, żeby problem (a) wrócił bocznymi drzwiami.
    """
    async with AsyncSessionLocal() as db:
        event = await _new_event(
            db,
            created_by=scope_setup["owner_id"],
            job_id=scope_setup["job_c"],
            candidate_id=scope_setup["candidate_id"],
        )
        await db.commit()
        event_id = event.id

    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=scope_setup["owner_headers"],
        json={"job_id": scope_setup["job_c"], "status": "completed"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["job_id"] == scope_setup["job_c"]


async def test_null_detach_requires_scope_on_the_job_being_detached(
    app_client: AsyncClient, scope_setup: dict[str, Any]
) -> None:
    """P2-14 (b): ``job_id: null`` nie może omijać bramki.

    Przed poprawką ``setattr`` zerował atrybut, ``ensure_optional_job_
    membership`` wracał na ``None`` i odpięcie przechodziło — a wraz z nim
    rozmontowanie przekazania kontaktu na ofercie, do której wołający nie ma
    dostępu.
    """
    async with AsyncSessionLocal() as db:
        event = await _new_event(
            db,
            created_by=scope_setup["owner_id"],
            job_id=scope_setup["job_c"],
            candidate_id=scope_setup["candidate_id"],
        )
        await db.commit()
        event_id = event.id

    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=scope_setup["owner_headers"],
        json={"job_id": None},
    )
    assert resp.status_code == 403, resp.text

    async with AsyncSessionLocal() as db:
        stored = await db.get(CalendarEvent, event_id)
        assert stored.job_id == scope_setup["job_c"]


async def test_member_may_detach_own_event_from_the_job(
    app_client: AsyncClient, scope_setup: dict[str, Any]
) -> None:
    """Odpięcie przez członka oferty to legalny ruch i musi dalej działać."""
    async with AsyncSessionLocal() as db:
        event = await _new_event(
            db,
            created_by=scope_setup["owner_id"],
            job_id=scope_setup["job_a"],
            candidate_id=scope_setup["candidate_id"],
        )
        await db.commit()
        event_id = event.id

    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=scope_setup["owner_headers"],
        json={"job_id": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["job_id"] is None


async def test_repointing_an_event_requires_scope_on_both_jobs(
    app_client: AsyncClient, scope_setup: dict[str, Any]
) -> None:
    """Przepięcie A → C: członkostwo w źródle nie wystarcza."""
    async with AsyncSessionLocal() as db:
        event = await _new_event(
            db,
            created_by=scope_setup["owner_id"],
            job_id=scope_setup["job_a"],
            candidate_id=scope_setup["candidate_id"],
        )
        await db.commit()
        event_id = event.id

    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=scope_setup["owner_headers"],
        json={"job_id": scope_setup["job_c"]},
    )
    assert resp.status_code == 403, resp.text


async def test_repointing_is_allowed_within_the_contact_case_scope(
    app_client: AsyncClient, scope_setup: dict[str, Any], monkeypatch
) -> None:
    """Przepięcie A → B mieści się w zakresie wręczonym właścicielowi sprawy."""
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    async with AsyncSessionLocal() as db:
        event = await _new_event(
            db,
            created_by=scope_setup["owner_id"],
            job_id=scope_setup["job_a"],
            candidate_id=scope_setup["candidate_id"],
        )
        await db.commit()
        event_id = event.id

    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=scope_setup["owner_headers"],
        json={"job_id": scope_setup["job_b"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["job_id"] == scope_setup["job_b"]


async def test_stranger_still_cannot_mutate_someone_elses_event(
    app_client: AsyncClient, scope_setup: dict[str, Any]
) -> None:
    """Bramka wydarzenia (twórca / admin / HoR) zostaje nietknięta."""
    async with AsyncSessionLocal() as db:
        event = await _new_event(
            db,
            created_by=scope_setup["owner_id"],
            job_id=scope_setup["job_a"],
            candidate_id=scope_setup["candidate_id"],
        )
        await db.commit()
        event_id = event.id

    resp = await app_client.patch(
        f"/api/calendar/events/{event_id}",
        headers=scope_setup["stranger_headers"],
        json={"title": "Przejęte"},
    )
    assert resp.status_code == 404, resp.text
