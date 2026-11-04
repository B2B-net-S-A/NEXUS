"""Uczestnicy rekrutacji z kategorii kompetencji (``job_collaborators.source='auto_cc'``).

Rekrutacja z kategorią ma za uczestników WSZYSTKIE osoby tej kategorii —
1. i 2. priorytet. Lista idzie za zmianami: inna kategoria rekrutacji, ktoś
dopisany do kategorii albo z niej zdjęty, zmiana roli, wyłączone konto.

„Osoba kategorii” ma jedną definicję (``_member_conditions``): aktywne konto
z rolą rekrutera, sourcera albo TAC (główną albo dodatkową) i wierszem
``user_competence_categories`` dla tej kategorii, z dowolnym priorytetem.

Czego synchronizacja nie rusza:
- wierszy ``manual`` — osobę wskazał człowiek,
- wierszy z ``removed_from_auto_cc = true`` — ktoś zdjął tę osobę z tej
  rekrutacji i ta decyzja zostaje (wiersz blokuje ponowne dodanie),
- rekrutacji zamkniętych i „Zakończonych” — ich lista jest historią.
"""

import logging
from typing import Iterable, Optional

from sqlalchemy import Integer, delete, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competence_category import UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

# Kto może dostać request: role operacyjne, także jako druga rola Delivery
# Leada (decyzja Artura 24.09.2026).
# Od 0411 jedna rola — rekruter.
OPERATOR_ROLES = (UserRole.recruiter,)

# Lustro ``request_work_state.WORK_STATE_FINISHED`` (import stamtąd ciągnie
# pół warstwy rekrutacji do modułu, który czyta trasy ustawień).
_FINISHED_WORK_STATE = "finished"


def operator_clause():
    return or_(
        User.role.in_(OPERATOR_ROLES),
        *(User.roles.contains([role.value]) for role in OPERATOR_ROLES),
    )


def _member_conditions() -> tuple:
    """Warunki „osoba kategorii” dla złączenia ``user_competence_categories``
    z ``users`` — jedyne miejsce tej reguły."""
    return (User.is_active.is_(True), operator_clause())


def _open_job_conditions() -> tuple:
    return (
        Job.status != JobStatus.closed,
        Job.work_state != _FINISHED_WORK_STATE,
    )


def _ids(values: Optional[Iterable[int]]) -> Optional[list[int]]:
    if values is None:
        return None
    return sorted({int(v) for v in values if v is not None})


async def category_member_ids(
    db: AsyncSession, category_ids: Iterable[int]
) -> dict[int, set[int]]:
    """``{id kategorii: {id osób}}`` — każda podana kategoria ma klucz."""
    ids = _ids(category_ids) or []
    out: dict[int, set[int]] = {category_id: set() for category_id in ids}
    if not ids:
        return out
    rows = await db.execute(
        select(
            UserCompetenceCategory.competence_category_id,
            UserCompetenceCategory.user_id,
        )
        .join(User, User.id == UserCompetenceCategory.user_id)
        .where(
            UserCompetenceCategory.competence_category_id.in_(ids),
            *_member_conditions(),
        )
    )
    for category_id, user_id in rows.all():
        out[category_id].add(user_id)
    return out


async def participants_count(
    db: AsyncSession, category_ids: Iterable[int]
) -> dict[int, int]:
    """Ile osób ma kategoria — tyle uczestników dostanie jej rekrutacja."""
    ids = _ids(category_ids) or []
    out = {category_id: 0 for category_id in ids}
    if not ids:
        return out
    rows = await db.execute(
        select(
            UserCompetenceCategory.competence_category_id,
            func.count(UserCompetenceCategory.user_id.distinct()),
        )
        .join(User, User.id == UserCompetenceCategory.user_id)
        .where(
            UserCompetenceCategory.competence_category_id.in_(ids),
            *_member_conditions(),
        )
        .group_by(UserCompetenceCategory.competence_category_id)
    )
    for category_id, count in rows.all():
        out[category_id] = int(count)
    return out


async def sync_cc_participants(
    db: AsyncSession,
    *,
    job_ids: Optional[Iterable[int]] = None,
    category_ids: Optional[Iterable[int]] = None,
    added_by: Optional[int] = None,
) -> dict[str, int]:
    """Wyrównaj uczestników ``auto_cc`` z kategoriami rekrutacji.

    Zakres: rekrutacje niezamknięte i nie „Zakończone”, zawężone do
    ``job_ids`` i/lub ``category_ids`` (oba puste = wszystkie). Robi ``flush``,
    ale nie commituje — transakcja należy do wołającego.
    """
    jobs = _ids(job_ids)
    categories = _ids(category_ids)
    result = {"added": 0, "removed": 0}
    if jobs == [] or categories == []:
        return result

    # Sesje aplikacji nie robią autoflush — zmiana kategorii rekrutacji albo
    # składu kategorii, która czeka w sesji wołającego, musi być widoczna dla
    # zapytań niżej.
    await db.flush()

    scope = list(_open_job_conditions())
    if jobs is not None:
        scope.append(Job.id.in_(jobs))
    if categories is not None:
        scope.append(Job.competence_category_id.in_(categories))

    # Zdjęcie: wiersz automatu osoby, która nie należy do OBECNEJ kategorii
    # rekrutacji (także gdy rekrutacja nie ma już kategorii).
    still_member = (
        select(literal(1))
        .select_from(Job)
        .join(
            UserCompetenceCategory,
            UserCompetenceCategory.competence_category_id == Job.competence_category_id,
        )
        .join(User, User.id == UserCompetenceCategory.user_id)
        .where(
            Job.id == JobCollaborator.job_id,
            UserCompetenceCategory.user_id == JobCollaborator.user_id,
            *_member_conditions(),
        )
        .correlate(JobCollaborator)
        .exists()
    )
    removed = await db.execute(
        delete(JobCollaborator)
        .where(
            JobCollaborator.source == JobCollaboratorSource.auto_cc,
            JobCollaborator.removed_from_auto_cc.is_(False),
            JobCollaborator.job_id.in_(select(Job.id).where(*scope)),
            ~still_member,
        )
        .returning(JobCollaborator.id)
        .execution_options(synchronize_session=False)
    )
    result["removed"] = len(removed.all())

    # Dodanie: brakujące osoby kategorii. Istniejący wiersz pary (ręczny,
    # automatu albo zdjęty z rekrutacji) zostaje taki, jaki jest.
    members = (
        select(
            Job.id,
            User.id,
            literal(added_by, Integer),
            literal(JobCollaboratorSource.auto_cc, JobCollaborator.source.type),
        )
        .select_from(Job)
        .join(
            UserCompetenceCategory,
            UserCompetenceCategory.competence_category_id == Job.competence_category_id,
        )
        .join(User, User.id == UserCompetenceCategory.user_id)
        .where(*scope, *_member_conditions())
    )
    added = await db.execute(
        pg_insert(JobCollaborator)
        # Pozostałe kolumny (flaga zdjęcia, data dodania) mają wartości
        # domyślne w bazie.
        .from_select(
            ["job_id", "user_id", "added_by", "source"],
            members,
            include_defaults=False,
        )
        .on_conflict_do_nothing(index_elements=["job_id", "user_id"])
        .returning(JobCollaborator.id)
    )
    result["added"] = len(added.all())

    if result["added"] or result["removed"]:
        logger.info(
            "[auto_cc] jobs=%s categories=%s added=%d removed=%d",
            jobs if jobs is not None else "all",
            categories if categories is not None else "all",
            result["added"],
            result["removed"],
        )
    return result
