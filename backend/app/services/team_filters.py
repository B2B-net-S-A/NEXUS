"""Filtry wyników zespołu: rola i klient (decyzja Artura z 10.11.2026).

Jedna reguła dla pulpitu „Aktywność rekrutacyjna”, listy „Kto się liczy”,
tabeli „Ludzie” w Insights → Zespół, kafla „Wyniki zespołu” i raportu
„Aktywność zespołu”. Opis: ``docs/claude/finanse-insights/filtry-rola-i-klient.md``.

- **Rekruterzy** = konta z rolą rekrutera (także Delivery Lead i TCM, którzy
  ją mają), bez Head of Recruitment i admina. Ta sama grupa co lista osób
  w „Kto” (``has_any_role(recruiter)``), bez kont kierownictwa.
- **Delivery Leadzi** = konta z rolą Delivery Leada. Grupy mogą się nakładać:
  DL z rolą rekrutera jest w obu.
- **Klient** = klient rekrutacji, w której para osiągnęła etap
  (``jobs.client_id``). Wpisy DynaReportera nie mają rekrutacji, więc przy
  wybranym kliencie nie wchodzą do liczby.

Konto bez względu na ``is_active``: dorobek osoby, która odeszła, liczy się
do jej grupy, tak jak do sumy firmy.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole

TeamRoleFilter = Literal["all", "recruiter", "delivery_lead"]

_LEADERSHIP = (UserRole.admin, UserRole.head_of_recruitment)

# Warunek na `credited.job_id` — klient rekrutacji; NULL = wszyscy klienci.
CLIENT_JOB_FILTER = """
    (
        CAST(:client_id AS integer) IS NULL
        OR {job_column} IN (
            SELECT filter_job.id FROM jobs filter_job
            WHERE filter_job.client_id = CAST(:client_id AS integer)
        )
    )
"""


def client_job_filter(job_column: str) -> str:
    return CLIENT_JOB_FILTER.format(job_column=job_column)


def in_role_group(user: User, role: TeamRoleFilter) -> bool:
    if role == "all":
        return True
    if role == "recruiter":
        return user.has_any_role(UserRole.recruiter) and not user.has_any_role(
            *_LEADERSHIP
        )
    return user.has_any_role(UserRole.delivery_lead)


async def team_role_user_ids(
    db: AsyncSession, role: TeamRoleFilter
) -> frozenset[int] | None:
    """Id kont w grupie roli; ``None`` = bez filtra („Wszyscy”)."""
    if role == "all":
        return None
    users = (await db.scalars(select(User))).all()
    return frozenset(user.id for user in users if in_role_group(user, role))


__all__ = [
    "TeamRoleFilter",
    "client_job_filter",
    "in_role_group",
    "team_role_user_ids",
]
