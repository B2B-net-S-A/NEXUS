"""Fikcyjny zespół do przeklikania modułu „Ludzie w NEXUSIE” na lokalnym stosie.

Zakłada konta z kartotekami (przełożona, rekruterzy, Delivery Lead, pracownik
recepcji z uprawnieniem „Sprzęt”, Kadry, Finanse), pule urlopowe na bieżący rok
i włącza wszystkie moduły. Dane są WYŁĄCZNIE fikcyjne (repozytorium jest
publiczne) — nazwiska w stylu harnessów, adresy w domenie ``example.com``.

Bramki bezpieczeństwa jak w ``seed_e2e.py``, bo skrypt pisze hasła:

* ``HR_DEMO_SEED_CONFIRM=nexus-hr-demo`` — bez tego koniec z błędem,
* baza z więcej niż ``MAX_FOREIGN_USERS`` kontami spoza demo/E2E jest
  odrzucana — to nie może pobiec na produkcji.

Użycie (kontener lokalnego stosu)::

    HR_DEMO_SEED_CONFIRM=nexus-hr-demo HR_DEMO_SEED_PASSWORD=... \
        python scripts/seed_hr_demo.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from datetime import date, datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.scheduling import business_today  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.academy import AcademyApplication, AcademyProgram  # noqa: E402
from app.models.app_setting import AppSetting  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.models.client import Client  # noqa: E402
from app.models.contract import Contract, ContractStatus, ContractType  # noqa: E402
from app.models.team_structure import DeliveryLeadClientAssignment  # noqa: E402
from app.models.hr_profile import EmployeeProfile, LeaveEntitlement  # noqa: E402
from app.models.section_permission import UserActionOverride  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services.hr_foundation_schema import (  # noqa: E402
    HR_MODULE_KEYS,
    HR_MODULES_SETTING,
)

logger = logging.getLogger("seed_hr_demo")

CONFIRM_TOKEN = "nexus-hr-demo"
MAX_FOREIGN_USERS = 10
DEMO_DOMAIN = "@hr-demo.example.com"


@dataclass(frozen=True)
class DemoPerson:
    key: str
    name: str
    role: UserRole
    employment_type: str
    job_title: str
    department: str
    manager: Optional[str] = None
    location: str = "onsite"
    entitlement: Optional[str] = "26"
    carried: str = "0"
    grants: tuple[str, ...] = field(default_factory=tuple)

    @property
    def email(self) -> str:
        return f"{self.key}{DEMO_DOMAIN}"


PEOPLE: tuple[DemoPerson, ...] = (
    DemoPerson(
        "marta",
        "Marta Przełożona",
        UserRole.head_of_recruitment,
        "uop",
        "Head of Recruitment",
        "Rekrutacja IT",
        entitlement="26",
    ),
    DemoPerson(
        "anna",
        "Anna Przykładowa",
        UserRole.recruiter,
        "b2b",
        "Rekruterka",
        "Rekrutacja IT",
        manager="marta",
    ),
    DemoPerson(
        "dawid",
        "Dawid Demo",
        UserRole.recruiter,
        "uop",
        "Rekruter",
        "Rekrutacja IT",
        manager="marta",
        location="remote",
        carried="2",
    ),
    DemoPerson(
        "borys",
        "Borys Wzorcowy",
        UserRole.delivery_lead,
        "b2b",
        "Delivery Lead",
        "Delivery",
        manager="marta",
    ),
    DemoPerson(
        "celina",
        "Celina Testowa",
        UserRole.employee,
        "zlecenie",
        "Recepcja",
        "Administracja",
        manager="marta",
        entitlement=None,
        grants=("equipment", "cases"),
    ),
    DemoPerson(
        "ewa",
        "Ewa Kadrowa",
        UserRole.employee,
        "uop",
        "Specjalistka ds. kadr",
        "Administracja",
        manager="marta",
        grants=("people_admin",),
    ),
    DemoPerson(
        "filip",
        "Filip Finansowy",
        UserRole.finance,
        "b2b",
        "Finanse",
        "Finanse",
        manager="marta",
    ),
)


class SeedRefused(RuntimeError):
    """Skrypt odmówił zasiewu — bramka bezpieczeństwa nie przeszła."""


async def seed(db: AsyncSession, password: str) -> dict[str, int]:
    if len(password) < 12:
        raise SeedRefused("HR_DEMO_SEED_PASSWORD musi mieć co najmniej 12 znaków.")
    total = int(await db.scalar(select(func.count()).select_from(User)) or 0)
    ours = int(
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.email.like(f"%{DEMO_DOMAIN}")
                | User.email.like("e2e-%@example.com")
                | User.email.like("pytest-%@example.com")
            )
        )
        or 0
    )
    if total - ours > MAX_FOREIGN_USERS:
        raise SeedRefused(
            f"Baza ma {total - ours} kont spoza demo — to nie jest lokalny stos."
        )

    users: dict[str, User] = {}
    created = 0
    for person in PEOPLE:
        user = await db.scalar(select(User).where(User.email == person.email))
        if user is None:
            user = User(
                email=person.email,
                password_hash=hash_password(password),
                name=person.name,
                role=person.role,
                roles=[person.role.value],
                is_active=True,
                email_verified=True,
                profile_completed=True,
            )
            db.add(user)
            await db.flush()
            created += 1
        users[person.key] = user

    year = business_today().year
    for person in PEOPLE:
        user = users[person.key]
        manager = users[person.manager] if person.manager else None
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == user.id)
        )
        if profile is None:
            db.add(
                EmployeeProfile(
                    user_id=user.id,
                    manager_user_id=manager.id if manager else None,
                    employment_type=person.employment_type,
                    employment_status="active",
                    default_location=person.location,
                    job_title=person.job_title,
                    department=person.department,
                )
            )
        await db.execute(
            insert(LeaveEntitlement)
            .values(
                user_id=user.id,
                year=year,
                entitlement_days=Decimal(person.entitlement)
                if person.entitlement
                else None,
                carried_over_days=Decimal(person.carried),
                used_initial_days=Decimal("0"),
            )
            .on_conflict_do_nothing(constraint="uq_leave_entitlements_user_year")
        )
        for action in person.grants:
            await db.execute(
                insert(UserActionOverride)
                .values(user_id=user.id, action=action, access="manage")
                .on_conflict_do_nothing()
            )

    contracts = await _seed_client_and_contracts(db, users["borys"])
    await _seed_academy(db)

    modules = {key: True for key in HR_MODULE_KEYS}
    statement = insert(AppSetting).values(key=HR_MODULES_SETTING, value=modules)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key], set_={"value": modules}
        )
    )
    await db.commit()
    return {"created": created, "people": len(PEOPLE), "contracts": contracts}


DEMO_CLIENT = "Klient Demo Bank (fikcja)"


async def _seed_client_and_contracts(db: AsyncSession, delivery_lead: User) -> int:
    """Fikcyjny klient z DL, sprzętem „od nas” i dwoma kontraktami konsultantów.

    Jeden trwa (opieka, mapa technologii, premie), drugi startuje za 10 dni
    (zadanie „przygotuj zestaw” i sprawa wejścia z przeglądu kontraktów).
    """
    client = await db.scalar(select(Client).where(Client.name == DEMO_CLIENT))
    if client is None:
        client = Client(name=DEMO_CLIENT)
        db.add(client)
        await db.flush()
    await db.execute(
        text("UPDATE clients SET equipment_provider = 'nasz' WHERE id = :id"),
        {"id": client.id},
    )
    assigned = await db.scalar(
        select(DeliveryLeadClientAssignment).where(
            DeliveryLeadClientAssignment.client_id == client.id,
            DeliveryLeadClientAssignment.delivery_lead_user_id == delivery_lead.id,
        )
    )
    if assigned is None:
        db.add(
            DeliveryLeadClientAssignment(
                client_id=client.id,
                delivery_lead_user_id=delivery_lead.id,
                is_head=True,
            )
        )
    today = business_today()
    created = 0
    for key, first, last, start, status in (
        (
            "konsultant1",
            "Jan",
            "Konsultant",
            today - timedelta(days=75),
            ContractStatus.active,
        ),
        (
            "konsultant2",
            "Ola",
            "Wejściowa",
            today + timedelta(days=10),
            ContractStatus.draft,
        ),
    ):
        email = f"{key}{DEMO_DOMAIN}"
        candidate = await db.scalar(select(Candidate).where(Candidate.email == email))
        if candidate is None:
            candidate = Candidate(name=first, lastname=last, email=email)
            db.add(candidate)
            await db.flush()
        contract = await db.scalar(
            select(Contract).where(
                Contract.candidate_id == candidate.id, Contract.client_id == client.id
            )
        )
        if contract is None:
            db.add(
                Contract(
                    candidate_id=candidate.id,
                    client_id=client.id,
                    status=status,
                    contract_type=ContractType("b2b"),
                    start_date=start,
                    end_date=None,
                    rate_client=165,
                    rate_candidate=120,
                    margin=45,
                    currency="PLN",
                )
            )
            created += 1
    await db.flush()
    return created


DEMO_ACADEMY = "Akademia Demo (fikcja)"


async def _seed_academy(db: AsyncSession) -> None:
    """Fikcyjny program Akademii z dwiema osobami w najbliższej edycji.

    Jedna ma podpisaną umowę i miesiąc edycji (zadanie zestawu dla recepcji),
    druga zaliczyła zadanie i czeka na umowę (liczona do najbliższej edycji).
    """
    program = await db.scalar(
        select(AcademyProgram).where(AcademyProgram.name == DEMO_ACADEMY)
    )
    if program is None:
        program = AcademyProgram(name=DEMO_ACADEMY)
        db.add(program)
        await db.flush()
    today = business_today()
    next_month = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    now = datetime.now(timezone.utc)
    for key, first, last, status in (
        ("akademia1", "Iga", "Uczestniczka", "signed"),
        ("akademia2", "Kuba", "Kandydat", "task_passed"),
    ):
        email = f"{key}{DEMO_DOMAIN}"
        candidate = await db.scalar(select(Candidate).where(Candidate.email == email))
        if candidate is None:
            candidate = Candidate(name=first, lastname=last, email=email)
            db.add(candidate)
            await db.flush()
        exists = await db.scalar(
            select(AcademyApplication.id).where(
                AcademyApplication.program_id == program.id,
                AcademyApplication.candidate_id == candidate.id,
            )
        )
        if exists is None:
            db.add(
                AcademyApplication(
                    program_id=program.id,
                    candidate_id=candidate.id,
                    applied_at=now - timedelta(days=20),
                    status=status,
                    task_result="passed",
                    signed_at=now if status == "signed" else None,
                    cohort_month=next_month if status == "signed" else None,
                )
            )
    await db.flush()


async def _main() -> int:
    if os.environ.get("HR_DEMO_SEED_CONFIRM") != CONFIRM_TOKEN:
        logger.error("Brak HR_DEMO_SEED_CONFIRM=%s — zasiew odrzucony.", CONFIRM_TOKEN)
        return 2
    password = os.environ.get("HR_DEMO_SEED_PASSWORD", "")
    async with AsyncSessionLocal() as db:
        try:
            result = await seed(db, password)
        except SeedRefused as exc:
            logger.error("%s", exc)
            return 2
    logger.info("Zespół demo: nowe=%d, osób=%d", result["created"], result["people"])
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(asyncio.run(_main()))
