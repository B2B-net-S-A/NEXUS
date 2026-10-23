"""Tablica otwartych rekrutacji na stronie głównej kariery (etap 6, 20.10.2026).

Decyzje Artura z 20.10.2026 (makiety 8aVZkzVxkVnkVVNBUDgL4h, plansze 6b–6e):

* D1 = A — tablica pokazuje KAŻDĄ otwartą rekrutację z opublikowaną wersją
  opisu (``job_public_profile.published_version``); przełącznik „pokazuj na
  mojej stronie” dotyczy tylko strony rekrutera.
* D2 = A — karta prowadzi na link rekrutacji prowadzącego, więc zgłoszenie
  z tablicy dostaje jego blokadę 12 h, liczy się mu w „Z linków” i budzi jego
  dzwonek. „Zostaw CV” bez rekrutacji idzie stałym linkiem Head of
  Recruitment (baza + jego „Moi ludzie” + dzwonek).

Link prowadzącego powstaje przy pierwszym zbudowaniu tablicy, na której jego
rekrutacja ma się pojawić — nie przy zatwierdzeniu opisu, bo prowadzący
zmienia się później (zmiana rekrutera, przekazanie), a tablica sama dobiera
link nowej osoby. Kto miał już link do tej rekrutacji i go wyłączył, nie
dostaje nowego — karta bierze wtedy najnowszy aktywny link innej osoby,
a rekrutacja bez żadnego aktywnego linku nie trafia na tablicę.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competence_category import CompetenceCategory
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobStatus
from app.models.job_public_profile import JobPublicProfile
from app.models.user import User, UserRole
from app.services import career_theme as ct
from app.services import job_public_profile as jpp
from app.services.career_slugs import (
    RESERVED_RECRUITER_SLUGS,
    first_name,
    suggest_recruiter_slug,
)

logger = logging.getLogger(__name__)

# Klucz blokady doradczej: dwa procesy budujące tablicę naraz nie tworzą
# dwóch linków tej samej osoby do tej samej rekrutacji.
_LINK_LOCK_KEY = "career_board_links"

# Ile wymagań niesie karta: scena ma najwyżej pięć punktów (``sceneItems``).
_BOARD_SKILLS = 5

# Cztery kategorie kompetencji → klucz filtra na tablicy. ``data_ai`` jest
# nieaktywne od 0371 i liczy się jako infra (competence-categories.md).
_CATEGORY_KEYS = {
    "software_development": "development",
    "infrastructure_operations": "infra",
    "data_ai": "infra",
    "security_quality": "qa",
    "management_delivery": "management",
}


def public_category(category_slug: Optional[str]) -> Optional[str]:
    """Klucz kategorii na stronach kariery (tablica i strona rekrutera)."""
    return _CATEGORY_KEYS.get(category_slug or "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active(link: CandidateInviteLink, now: datetime) -> bool:
    if link.revoked:
        return False
    return link.expires_at is None or link.expires_at > now


async def _lead_id(db: AsyncSession, job: Job, users: dict[int, User]) -> Optional[int]:
    """Prowadzący, który pracuje i ma aktywne konto — inaczej ``None``."""
    from app.services.job_previous_recruiters import working_owner_id

    owner_id = await working_owner_id(db, job)
    if owner_id is None:
        return None
    user = users.get(owner_id) or await db.get(User, owner_id)
    if user is None or not user.is_active:
        return None
    users[owner_id] = user
    return owner_id


async def _new_job_link(
    db: AsyncSession,
    job: Job,
    owner_id: int,
    title: str,
    *,
    label: str = "Tablica kariery",
    via: str = "career_board",
) -> CandidateInviteLink:
    """Link rekrutacji prowadzącego (albo Head of Recruitment, gdy nikt nie
    prowadzi) — jak „Udostępnij”, tylko bez okna.

    Przypisanie priorytetowe zamrażamy tak samo jak ``POST /api/invite-links``
    (gałąź bez wyjątku): aktywny członek planu dostaje swoje przypisanie.
    Sekret istnieje tylko jako skrót — kandydat wchodzi po slugu.
    """
    from app.models.recruitment_priority import PriorityMemberStatus
    from app.services.priority_work_policy import current_priority_assignment

    origin_assignment_id: Optional[int] = None
    priority_compliant: Optional[bool] = None
    assignment, member, _plan = await current_priority_assignment(
        db, user_id=owner_id, job_id=job.id
    )
    if (
        assignment is not None
        and member is not None
        and member.status == PriorityMemberStatus.active
    ):
        origin_assignment_id = assignment.id
        priority_compliant = True

    secret = secrets.token_urlsafe(36)
    link = CandidateInviteLink(
        token=f"v2${secrets.token_hex(16)}",
        token_sha256=hashlib.sha256(secret.encode()).hexdigest(),
        created_by=owner_id,
        kind="job",
        slug=await jpp.safe_job_slug(db, job, title),
        job_id=job.id,
        origin_assignment_id=origin_assignment_id,
        priority_compliant_at_create=priority_compliant,
        label=label,
        expires_at=None,
    )
    db.add(link)
    await db.flush()
    from app.services.priority_work_service import audit_event

    # Ten sam ślad co `POST /api/invite-links`, bez aktora — założyła tablica
    # albo „Opublikuj na stronie” z ogłoszenia.
    audit_event(
        db,
        "invite_link_created",
        job_id=job.id,
        subject_user_id=owner_id,
        assignment_id=origin_assignment_id,
        payload={"slug": link.slug, "via": via},
    )
    logger.info(
        "career_board: utworzono link rekrutacji %s dla osoby %s (%s)",
        job.id,
        owner_id,
        via,
    )
    return link


async def own_job_link(
    db: AsyncSession, job: Job, user_id: int
) -> Optional[CandidateInviteLink]:
    """Najnowszy aktywny link rekrutacji tej osoby (ze slugiem)."""
    now = _now()
    links = await db.scalars(
        select(CandidateInviteLink)
        .where(
            CandidateInviteLink.kind == "job",
            CandidateInviteLink.job_id == job.id,
            CandidateInviteLink.created_by == user_id,
            CandidateInviteLink.slug.is_not(None),
        )
        .order_by(CandidateInviteLink.created_at.desc())
    )
    return next((link for link in links if _active(link, now)), None)


async def ensure_own_job_link(
    db: AsyncSession, job: Job, user_id: int, title: str
) -> Optional[CandidateInviteLink]:
    """Link osoby, która publikuje stronę z ogłoszenia (21.10.2026): ma od razu
    co skopiować, a zgłoszenia z jej linku liczą się jej.

    Kto swój link do tej rekrutacji wyłączył, nie dostaje nowego (``None``) —
    jak na tablicy: wyłączony link to decyzja człowieka.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": _LINK_LOCK_KEY}
    )
    existing = await own_job_link(db, job, user_id)
    if existing is not None:
        return existing
    revoked = await db.scalar(
        select(CandidateInviteLink.token)
        .where(
            CandidateInviteLink.kind == "job",
            CandidateInviteLink.job_id == job.id,
            CandidateInviteLink.created_by == user_id,
            CandidateInviteLink.revoked.is_(True),
        )
        .limit(1)
    )
    if revoked is not None:
        return None
    return await _new_job_link(
        db, job, user_id, title, label="Ogłoszenie", via="job_ad_career"
    )


def _links_of_active_owners(
    links: list[CandidateInviteLink], active_ids: set[int]
) -> list[CandidateInviteLink]:
    """Linki osób z aktywnym kontem — decyzja Artura 22.10.2026 (audyt F62).

    Wyłączenie konta unieważnia tylko link ``recruiter``; link ``job`` osoby,
    która odeszła, zostaje „aktywny” bez końca. Na tablicy i w canonical nie
    może stać (imię byłego pracownika publicznie i w Google), więc rekrutacja
    z samymi takimi linkami dostaje link Head of Recruitment.
    """
    return [link for link in links if link.created_by in active_ids]


async def _active_owner_ids(
    db: AsyncSession, links: list[CandidateInviteLink]
) -> set[int]:
    owner_ids = {link.created_by for link in links}
    if not owner_ids:
        return set()
    return set(
        await db.scalars(
            select(User.id).where(User.id.in_(owner_ids), User.is_active.is_(True))
        )
    )


def _pick_link(
    links: list[CandidateInviteLink],
    lead_id: Optional[int],
    now: datetime,
    *,
    fallback_id: Optional[int] = None,
) -> tuple[Optional[CandidateInviteLink], Optional[int]]:
    """``(link karty, czyj link założyć)`` — najwyżej jedno z dwóch.

    Kolejność: aktywny link prowadzącego → nowy link prowadzącego, gdy nie ma
    aktywnego, a sam żadnego nie wyłączył (nigdy nie miał albo wygasł) →
    najnowszy aktywny link rekrutacji → bez prowadzącego nowy link Head of
    Recruitment (``fallback_id``), o ile ten swojego nie wyłączył. Wyłączony
    link to decyzja człowieka; wygasły nie — decyzja Artura 21.10.2026:
    tablica nie gubi rekrutacji przez wygasły link albo brak prowadzącego.
    ``links`` są posortowane od najnowszego i należą wyłącznie do osób
    z aktywnym kontem (``_links_of_active_owners``, decyzja 22.10.2026).
    """
    if lead_id is not None:
        own = [link for link in links if link.created_by == lead_id]
        for link in own:
            if _active(link, now):
                return link, None
        if not any(link.revoked for link in own):
            return None, lead_id
    for link in links:
        if _active(link, now):
            return link, None
    if lead_id is None and fallback_id is not None:
        if not any(link.revoked for link in links if link.created_by == fallback_id):
            return None, fallback_id
    return None, None


async def _first_hor_id(db: AsyncSession) -> Optional[int]:
    """Head of Recruitment dla rekrutacji bez prowadzącego — jak „Zostaw CV”:
    pierwszy aktywny (najniższe id)."""
    return await db.scalar(
        select(User.id)
        .where(User.is_active.is_(True), _is_hor_clause())
        .order_by(User.id)
        .limit(1)
    )


async def canonical_job_slug(db: AsyncSession, job: Job) -> Optional[str]:
    """Slug linku, pod którym rekrutacja stoi (albo stanie) na tablicy.

    Ta sama reguła co karta tablicy (``_pick_link``), ale bez zakładania linku:
    gdy tablica dopiero założy link, bierzemy najnowszy aktywny link
    rekrutacji. Strona ``/r/<slug>`` podaje go jako canonical i identyfikator
    JobPosting — jedna rekrutacja, wiele linków, jedna oferta w Google (audyt
    21.10.2026).
    """
    links = list(
        await db.scalars(
            select(CandidateInviteLink)
            .where(
                CandidateInviteLink.kind == "job",
                CandidateInviteLink.job_id == job.id,
                CandidateInviteLink.slug.is_not(None),
            )
            .order_by(CandidateInviteLink.created_at.desc())
        )
    )
    links = _links_of_active_owners(links, await _active_owner_ids(db, links))
    now = _now()
    lead_id = await _lead_id(db, job, {})
    link, _owner = _pick_link(links, lead_id, now)
    if link is None:
        link = next((item for item in links if _active(item, now)), None)
    return link.slug if link is not None else None


async def board_jobs(db: AsyncSession) -> list[dict[str, Any]]:
    """Karty tablicy — biała lista pól, od najnowszej otwartej rekrutacji.

    Nigdy klient, stawki, budżet, kody ani nazwisko: tytuł i podtytuł z wersji
    opublikowanej, miasto i tryb jak na stronie rekrutacji (z migawki
    i przełącznika „parametry”), imię właściciela linku karty.
    """
    rows = (
        await db.execute(
            select(Job, JobPublicProfile)
            .join(JobPublicProfile, JobPublicProfile.job_id == Job.id)
            .where(
                Job.status == JobStatus.published,
                JobPublicProfile.approved_at.is_not(None),
            )
            .order_by(Job.opened_at.desc().nulls_last(), Job.id.desc())
        )
    ).all()
    if not rows:
        return []

    job_ids = [job.id for job, _profile in rows]
    links_by_job: dict[int, list[CandidateInviteLink]] = {}
    for link in (
        await db.scalars(
            select(CandidateInviteLink)
            .where(
                CandidateInviteLink.kind == "job",
                CandidateInviteLink.job_id.in_(job_ids),
                CandidateInviteLink.slug.is_not(None),
            )
            .order_by(CandidateInviteLink.created_at.desc())
        )
    ).all():
        links_by_job.setdefault(link.job_id, []).append(link)
    active_ids = await _active_owner_ids(
        db, [link for links in links_by_job.values() for link in links]
    )
    links_by_job = {
        job_id: _links_of_active_owners(links, active_ids)
        for job_id, links in links_by_job.items()
    }

    category_slugs = dict(
        (await db.execute(select(CompetenceCategory.id, CompetenceCategory.slug))).all()
    )

    now = _now()
    users: dict[int, User] = {}
    names_cache: dict[Optional[int], list[str]] = {}
    hor_id = await _first_hor_id(db)
    locked = False
    cards: list[dict[str, Any]] = []
    for job, profile in rows:
        # Jedna rekrutacja z popsutym opisem (sekcje, migawka) nie może zdjąć
        # całej strony głównej — znika tylko jej karta. Błąd bazy idzie dalej:
        # transakcja i tak jest wtedy do wyrzucenia.
        try:
            version = await jpp.published_version(
                db, job, profile, names_cache=names_cache
            )
            params = jpp.visible_params(job, version.sections) if version else None
            # Wymagania do podglądu sceny (etap 7) — z tej samej projekcji co
            # strona rekrutacji, więc ukryta sekcja daje pustą listę.
            skills = (
                jpp.public_job_payload(
                    job,
                    title=version.title,
                    link_slug=None,
                    subtitle=None,
                    about=None,
                    sections=version.sections,
                )
                if version
                else None
            )
        except SQLAlchemyError:
            raise
        except Exception:
            logger.exception("career_board: pomijam rekrutację %s", job.id)
            continue
        if version is None or params is None or skills is None:
            continue
        links = links_by_job.get(job.id, [])
        lead_id = await _lead_id(db, job, users)
        link, owner_id = _pick_link(links, lead_id, now, fallback_id=hor_id)
        if owner_id is not None:
            if not locked:
                await db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": _LINK_LOCK_KEY},
                )
                locked = True
            # Po blokadzie: inny proces mógł właśnie utworzyć ten link.
            fresh = (
                await db.scalars(
                    select(CandidateInviteLink)
                    .where(
                        CandidateInviteLink.kind == "job",
                        CandidateInviteLink.job_id == job.id,
                        CandidateInviteLink.created_by == owner_id,
                        CandidateInviteLink.slug.is_not(None),
                    )
                    .order_by(CandidateInviteLink.created_at.desc())
                )
            ).all()
            link = next((item for item in fresh if _active(item, now)), None)
            if link is None:
                link = await _new_job_link(db, job, owner_id, version.title)
        if link is None:
            continue
        owner = users.get(link.created_by) or await db.get(User, link.created_by)
        if owner is not None:
            users[link.created_by] = owner
        category_slug = category_slugs.get(job.competence_category_id)
        cards.append(
            {
                "slug": link.slug,
                "title": version.title,
                "subtitle": version.subtitle,
                "city": params["city"],
                "remote_policy": params["remote_policy"],
                "category": public_category(category_slug),
                "theme": ct.resolve_theme(profile.theme, version.title, category_slug),
                "recruiter_first_name": first_name(owner.name if owner else None)
                or "Zespół",
                "must": [item["name"] for item in skills["must"]][:_BOARD_SKILLS],
                "nice": list(skills["nice"])[:_BOARD_SKILLS],
            }
        )
    if locked:
        await db.commit()
    return cards


def _is_hor_clause():
    return or_(
        User.role == UserRole.head_of_recruitment,
        User.roles.contains([UserRole.head_of_recruitment.value]),
    )


async def _free_recruiter_slug(db: AsyncSession, name: Optional[str]) -> str:
    base = suggest_recruiter_slug(name)
    for attempt in range(20):
        slug = base if attempt == 0 else f"{base}-{attempt + 1}"
        if slug in RESERVED_RECRUITER_SLUGS:
            continue
        taken = await db.scalar(
            select(CandidateInviteLink.token).where(CandidateInviteLink.slug == slug)
        )
        if taken is None:
            return slug
    return f"{base}-{secrets.token_hex(3)}"


def pick_cv_owner(
    hor_ids: list[int], links: list[CandidateInviteLink], now: datetime
) -> tuple[Optional[str], Optional[int]]:
    """``(slug aktywnego linku, HoR do założenia linku)`` — patrz ``board_cv_link``."""
    by_owner: dict[int, list[CandidateInviteLink]] = {}
    for link in links:
        by_owner.setdefault(link.created_by, []).append(link)
    for user_id in hor_ids:
        for link in by_owner.get(user_id, []):
            if _active(link, now):
                return link.slug, None
    return None, next((u for u in hor_ids if u not in by_owner), None)


def _cv(slug: str, hors: Any, links: Any) -> dict[str, str]:
    owner_id = next(link.created_by for link in links if link.slug == slug)
    owner = next(u for u in hors if u.id == owner_id)
    return {"slug": slug, "first_name": first_name(owner.name) or "Zespół"}


async def board_cv_link(db: AsyncSession) -> Optional[dict[str, str]]:
    """Link „Zostaw CV” (``slug`` i imię do podziękowania) — stały link Head of
    Recruitment.

    Reguła przy kilku HoR: pierwszy (najniższe id) z aktywnym stałym linkiem;
    gdy żaden go nie ma — pierwszy, który NIGDY nie miał stałego linku,
    dostaje go teraz (adres z imienia, jak podpowiedź w „Mój link”). HoR,
    który swój link wyłączył, nie dostaje nowego. Bez takiej osoby (zero HoR
    albo wszyscy wyłączyli link) ``None`` — tablica nie pokazuje „Zostaw CV”.
    """
    hors = (
        await db.scalars(
            select(User)
            .where(User.is_active.is_(True), _is_hor_clause())
            .order_by(User.id)
        )
    ).all()
    if not hors:
        logger.warning(
            "career_board: brak aktywnego Head of Recruitment — bez „Zostaw CV”"
        )
        return None
    links = (
        await db.scalars(
            select(CandidateInviteLink).where(
                CandidateInviteLink.kind == "recruiter",
                CandidateInviteLink.created_by.in_([u.id for u in hors]),
            )
        )
    ).all()
    slug, newcomer = pick_cv_owner([u.id for u in hors], list(links), _now())
    if slug is not None:
        return _cv(slug, hors, links)
    if newcomer is None:
        logger.warning(
            "career_board: Head of Recruitment wyłączył stały link — bez „Zostaw CV”"
        )
        return None
    newcomer_user = next(u for u in hors if u.id == newcomer)

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": _LINK_LOCK_KEY}
    )
    existing = await db.scalar(
        select(CandidateInviteLink).where(
            CandidateInviteLink.kind == "recruiter",
            CandidateInviteLink.created_by == newcomer,
            CandidateInviteLink.revoked.is_(False),
        )
    )
    if existing is not None:
        await db.commit()
        return {
            "slug": existing.slug,
            "first_name": first_name(newcomer_user.name) or "Zespół",
        }
    # Jak ``PUT /me/career-link``: sekret tylko jako skrót, wejście po slugu.
    link = CandidateInviteLink(
        token=f"v2${secrets.token_hex(16)}",
        token_sha256=hashlib.sha256(secrets.token_urlsafe(36).encode()).hexdigest(),
        created_by=newcomer,
        kind="recruiter",
        slug=await _free_recruiter_slug(db, newcomer_user.name),
        job_id=None,
        expires_at=None,
    )
    db.add(link)
    await db.commit()
    logger.info("career_board: utworzono stały link Head of Recruitment %s", newcomer)
    return {"slug": link.slug, "first_name": first_name(newcomer_user.name) or "Zespół"}
