"""
DynaMinds ATS — Seed v5
Adds CalendarEvents (5) and Notifications (8) for admin user.
Safe to run after existing seeds.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import Base
from app.models.user import User
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.calendar_event import CalendarEvent, EventType, EventStatus
from app.models.notification import Notification, NotificationType

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://dynaminds:dynaminds@localhost:5432/dynaminds"
)


def now_utc():
    return datetime.now(timezone.utc)


def next_weekday(days_ahead: int) -> datetime:
    return now_utc().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)


async def seed_v5():
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        # Check already seeded
        ev_result = await db.execute(select(CalendarEvent))
        existing_events = ev_result.scalars().all()
        if existing_events:
            print(f"V5 already seeded — {len(existing_events)} calendar events exist. Skipping.")
            await engine.dispose()
            return

        # Get admin user
        user_result = await db.execute(select(User).where(User.email == "artur@b2bnet.pl"))
        admin = user_result.scalar_one_or_none()
        if not admin:
            print("Admin user not found — run main seed first!")
            await engine.dispose()
            return

        admin_id = admin.id
        print(f"Seeding for admin: {admin.name} (id={admin_id})")

        # Get first few candidates and jobs for linking
        cands_result = await db.execute(select(Candidate).limit(5))
        candidates = cands_result.scalars().all()

        jobs_result = await db.execute(select(Job).limit(3))
        jobs = jobs_result.scalars().all()

        cand_ids = [c.id for c in candidates]
        job_ids = [j.id for j in jobs]
        cand_names = [f"{c.name} {c.lastname}" for c in candidates]
        job_titles = [j.title for j in jobs]

        # ── Calendar Events ──────────────────────────────────────────────────

        events = [
            CalendarEvent(
                title=f"Rozmowa kwalifikacyjna — {cand_names[0] if cand_names else 'Kandydat 1'}",
                description="Rozmowa techniczna — Angular/React, ocena poziomu senior",
                event_type=EventType.interview,
                start_time=next_weekday(1).replace(hour=10),
                end_time=next_weekday(1).replace(hour=11),
                all_day=False,
                candidate_id=cand_ids[0] if cand_ids else None,
                job_id=job_ids[0] if job_ids else None,
                attendees=["artur@b2bnet.pl", "rekruter@b2bnet.pl"],
                location="Google Meet",
                teams_link="https://meet.google.com/abc-defg-hij",
                created_by=admin_id,
                reminder_minutes=15,
                status=EventStatus.scheduled,
            ),
            CalendarEvent(
                title=f"Screening wstępny — {cand_names[1] if len(cand_names) > 1 else 'Kandydat 2'}",
                description="Pierwsza rozmowa telefoniczna, weryfikacja oczekiwań i motywacji",
                event_type=EventType.screening,
                start_time=next_weekday(1).replace(hour=14),
                end_time=next_weekday(1).replace(hour=14, minute=30),
                all_day=False,
                candidate_id=cand_ids[1] if len(cand_ids) > 1 else None,
                job_id=job_ids[1] if len(job_ids) > 1 else None,
                attendees=["artur@b2bnet.pl"],
                location="Telefon",
                created_by=admin_id,
                reminder_minutes=10,
                status=EventStatus.scheduled,
            ),
            CalendarEvent(
                title=f"Prep Call przed rozmową u klienta — {cand_names[2] if len(cand_names) > 2 else 'Kandydat 3'}",
                description="Przygotowanie kandydata przed rozmową z Nordea. Omówienie projektu, kultury firmy i spodziewanych pytań.",
                event_type=EventType.prep_call,
                start_time=next_weekday(2).replace(hour=9),
                end_time=next_weekday(2).replace(hour=9, minute=45),
                all_day=False,
                candidate_id=cand_ids[2] if len(cand_ids) > 2 else None,
                job_id=job_ids[0] if job_ids else None,
                attendees=["artur@b2bnet.pl"],
                location="Teams",
                teams_link="https://teams.microsoft.com/l/meetup-join/xyz",
                created_by=admin_id,
                reminder_minutes=30,
                status=EventStatus.scheduled,
            ),
            CalendarEvent(
                title="Spotkanie z klientem — Nordea Talent Review",
                description="Kwartalne spotkanie z Nordea dotyczące pipelinu kandydatów i planów rekrutacyjnych na Q2.",
                event_type=EventType.meeting,
                start_time=next_weekday(3).replace(hour=11),
                end_time=next_weekday(3).replace(hour=12, minute=30),
                all_day=False,
                attendees=["artur@b2bnet.pl", "olaf@b2bnet.pl", "nordea-hr@nordea.com"],
                location="Biuro Nordea, ul. Bema 1, Warszawa",
                created_by=admin_id,
                reminder_minutes=60,
                status=EventStatus.scheduled,
            ),
            CalendarEvent(
                title=f"Rozmowa finalna — {cand_names[3] if len(cand_names) > 3 else 'Kandydat 4'}",
                description="Ostatni etap procesu rekrutacyjnego. Oferta płacowa, warunki kontraktu B2B.",
                event_type=EventType.interview,
                start_time=next_weekday(4).replace(hour=15),
                end_time=next_weekday(4).replace(hour=16),
                all_day=False,
                candidate_id=cand_ids[3] if len(cand_ids) > 3 else None,
                job_id=job_ids[2] if len(job_ids) > 2 else None,
                attendees=["artur@b2bnet.pl"],
                location="Google Meet",
                created_by=admin_id,
                reminder_minutes=15,
                status=EventStatus.scheduled,
            ),
        ]

        for ev in events:
            db.add(ev)

        # ── Notifications ────────────────────────────────────────────────────

        notifications = [
            Notification(
                user_id=admin_id,
                title="Kontrakt kończy się za 14 dni",
                message=f"Kontrakt kandydata {cand_names[0] if cand_names else 'Kandydat'} wygasa za 14 dni. Skontaktuj się, aby omówić przedłużenie.",
                link=f"/candidates/{cand_ids[0]}" if cand_ids else "/contracts",
                notification_type=NotificationType.contract_ending,
                is_read=False,
            ),
            Notification(
                user_id=admin_id,
                title="Nowy kandydat dodany do rekrutacji",
                message=f"{cand_names[1] if len(cand_names) > 1 else 'Kandydat'} został dodany do procesu na stanowisko {job_titles[0] if job_titles else 'oferta'}.",
                link=f"/candidates/{cand_ids[1]}" if len(cand_ids) > 1 else "/candidates",
                notification_type=NotificationType.candidate_added,
                is_read=False,
            ),
            Notification(
                user_id=admin_id,
                title="Kandydat przeszedł do etapu Interview",
                message=f"{cand_names[2] if len(cand_names) > 2 else 'Kandydat'} awansował do etapu rozmowy kwalifikacyjnej.",
                link=f"/candidates/{cand_ids[2]}" if len(cand_ids) > 2 else "/candidates",
                notification_type=NotificationType.stage_changed,
                is_read=False,
            ),
            Notification(
                user_id=admin_id,
                title="Rozmowa zaplanowana na jutro",
                message=f"Rozmowa kwalifikacyjna z {cand_names[0] if cand_names else 'kandydatem'} jutro o 10:00.",
                link="/calendar",
                notification_type=NotificationType.interview_scheduled,
                is_read=False,
            ),
            Notification(
                user_id=admin_id,
                title="Kontrakt kończy się za 14 dni",
                message=f"Kontrakt kandydata {cand_names[3] if len(cand_names) > 3 else 'Kandydat'} wygasa wkrótce. Wymagana akcja.",
                link=f"/candidates/{cand_ids[3]}" if len(cand_ids) > 3 else "/contracts",
                notification_type=NotificationType.contract_ending,
                is_read=False,
            ),
            Notification(
                user_id=admin_id,
                title="Nowa aplikacja na stanowisko",
                message=f"Otrzymano nową aplikację na stanowisko {job_titles[1] if len(job_titles) > 1 else 'oferty'}.",
                link=f"/jobs/{job_ids[1]}" if len(job_ids) > 1 else "/jobs",
                notification_type=NotificationType.new_application,
                is_read=True,
            ),
            Notification(
                user_id=admin_id,
                title="Kandydat otrzymał ofertę",
                message=f"{cand_names[4] if len(cand_names) > 4 else 'Kandydat'} przeszedł do etapu Oferta. Wyślij warunki współpracy.",
                link=f"/candidates/{cand_ids[4]}" if len(cand_ids) > 4 else "/candidates",
                notification_type=NotificationType.stage_changed,
                is_read=True,
            ),
            Notification(
                user_id=admin_id,
                title="Prep Call zaplanowany",
                message=f"Prep call z {cand_names[2] if len(cand_names) > 2 else 'kandydatem'} zaplanowany na pojutrze o 09:00.",
                link="/calendar",
                notification_type=NotificationType.interview_scheduled,
                is_read=True,
            ),
        ]

        for notif in notifications:
            db.add(notif)

        await db.commit()
        print(f"✅ Seeded {len(events)} calendar events and {len(notifications)} notifications.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_v5())
