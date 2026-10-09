"""Lightweight user-directory endpoint for authenticated UI pickers.

Different from `/api/admin/users` (which returns activity stats and is admin-
only). This is a minimal, read-only listing that any logged-in user can call
to populate a recruiter/owner picker. Always excludes inactive accounts and
read-only (`user` role) viewers — neither is a legitimate job owner.
"""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User, UserRole, known_roles
from app.api.deps import OperationalUser, CurrentUser
from app.schemas.job import UserBrief
from app.services import notification_email_prefs
from app.services.jarvis.prefs import (
    UNLOCKABLE_CHARACTERS,
    JarvisPrefs,
    JarvisPrefsUpdate,
    apply_update,
    effective_prefs,
    unlocked_characters,
)

router = APIRouter()


# ── Preferences schemas ────────────────────────────────────────────────────


class UserPreferencesUpdate(BaseModel):
    """Patch body for `/me/preferences`. All fields optional — pass only the
    ones you want to change."""

    kpi_coach_enabled: Optional[bool] = Field(
        default=None,
        description="Włącza/wyłącza in-app coaching KPI (praise + remind + EOD).",
    )
    jarvis: Optional[JarvisPrefsUpdate] = Field(
        default=None,
        description="Wygląd i zachowanie maskotki Jarvisa (tylko zmieniane pola).",
    )
    daily_digest_email_enabled: Optional[bool] = Field(
        default=None,
        description="Poranny skrót „Twój dzień w NEXUSIE” mailem — tylko to konto.",
    )


class JarvisPrefsResponse(JarvisPrefs):
    unlocked_characters: list[str]
    # postać → jak ją odblokować (tylko te, których ta osoba jeszcze nie ma)
    locked_characters: dict[str, str]


class UserPreferencesResponse(BaseModel):
    kpi_coach_enabled: bool
    jarvis: JarvisPrefsResponse
    daily_digest_email_enabled: bool
    # Czy skrót w ogóle może trafić do tego konta (rola z listy skrótu) —
    # bez tego przełącznik obiecywałby mail, którego konto nie dostaje.
    daily_digest_email_available: bool


async def _preferences_response(
    db: AsyncSession, user: User
) -> UserPreferencesResponse:
    prefs = effective_prefs(user.jarvis_prefs)
    unlocked = await unlocked_characters(db, user.id)
    if prefs.character not in unlocked:
        # Odblokowanie mogło zniknąć (ranking przeliczony) — pokazujemy
        # domyślną postać, zapis zostaje nietknięty.
        prefs = prefs.model_copy(update={"character": "robot"})
    from app.tasks.daily_digest_email import DIGEST_ROLES

    return UserPreferencesResponse(
        kpi_coach_enabled=user.kpi_coach_enabled,
        daily_digest_email_enabled=user.daily_digest_email_enabled,
        daily_digest_email_available=user.has_any_role(*DIGEST_ROLES),
        jarvis=JarvisPrefsResponse(
            **prefs.model_dump(),
            unlocked_characters=unlocked,
            locked_characters={
                key: hint
                for key, hint in UNLOCKABLE_CHARACTERS.items()
                if key not in unlocked
            },
        ),
    )


# Roles that can meaningfully own or collaborate on a job. `user` (viewer)
# is deliberately excluded — viewers should never appear in an owner picker.
_DEFAULT_ROLES = [
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.recruiter,
]

# Role, których dawne (nieaktywne) konta mogą być autorem albo adresatem
# wzmianki w starej notatce.
_MENTION_HISTORY_ROLES = [
    *_DEFAULT_ROLES,
    UserRole.head_of_recruitment,
    UserRole.finance,
]


@router.get("", response_model=List[UserBrief])
async def list_users(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    roles: Optional[List[str]] = Query(
        None,
        description=(
            "Filter by role. Repeat the param for multiple values "
            "(e.g. `?roles=recruiter&roles=delivery_lead`). Defaults to "
            "ownership-eligible roles (excludes read-only viewers)."
        ),
    ),
    q: Optional[str] = Query(None, description="Case-insensitive match on name/email."),
):
    """Directory listing for owner/collaborator pickers."""
    # Napisy, nie enum: otwarta karta ze starą wersją aplikacji pyta jeszcze
    # o `tac` i `sourcer` (od 0411 to rekruter) — nie może dostać 422.
    target_roles = known_roles(roles) if roles else _DEFAULT_ROLES
    if not target_roles:
        raise HTTPException(status_code=422, detail="Nieznana rola w filtrze.")
    effective_role_filter = or_(
        User.role.in_(target_roles),
        *(User.roles.contains([role.value]) for role in target_roles),
    )
    query = (
        select(User)
        .where(User.is_active.is_(True))
        .where(effective_role_filter)
        .order_by(User.name)
    )
    if q:
        needle = f"%{q}%"
        query = query.where((User.name.ilike(needle)) | (User.email.ilike(needle)))
    result = await db.execute(query)
    return [UserBrief.model_validate(u) for u in result.scalars().all()]


@router.get("/mentionable", response_model=List[UserBrief])
async def list_mentionable_users(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    job_id: Optional[int] = Query(
        None,
        description=(
            "Rekrutacja, której dotyczy notatka albo czat: jej zespół stoi na "
            "początku listy."
        ),
    ),
    candidate_id: Optional[int] = Query(
        None,
        description=(
            "Kandydat, którego czatu dotyczy wzmianka: osoby z jego rekrutacji "
            "stoją na początku listy. `job_id` ma pierwszeństwo."
        ),
    ),
    q: Optional[str] = Query(None, description="Case-insensitive match on name/email."),
    include_inactive: bool = Query(
        False,
        description=(
            "Dokłada nieaktywne konta ról wewnętrznych — do pokazania nazwiska "
            "przy wzmiance w historycznej notatce, nie do oznaczania."
        ),
    ),
):
    """Osoby, które można oznaczyć przez @.

    Zawsze wszystkie aktywne konta z odczytem tego, w czym się oznacza
    (`mention_parser.mentionable_users` — ta sama reguła co przy zapisie
    wzmianki). `job_id` / `candidate_id` zmieniają tylko kolejność: najpierw
    zespół. Do 08.10.2026 lista rekrutacji i czatu kandydata zawierała sam
    zespół, a lista ogólna pomijała Head of Recruitment i Finanse.
    """
    from app.services.candidate_membership import list_candidate_chat_member_ids
    from app.services.job_membership import list_job_member_ids
    from app.services.mention_parser import mentionable_users
    from app.services.section_permissions import ProductSection

    team_ids: set[int] = set()
    section = None
    if job_id is not None:
        section = ProductSection.pipeline
        team_ids = set(await list_job_member_ids(db, job_id))
    elif candidate_id is not None:
        section = ProductSection.sourcing
        team_ids = set(await list_candidate_chat_member_ids(db, candidate_id))

    users = await mentionable_users(db, section=section)
    if include_inactive:
        rows = await db.execute(
            select(User).where(
                User.is_active.is_(False),
                or_(
                    User.role.in_(_MENTION_HISTORY_ROLES),
                    *(
                        User.roles.contains([role.value])
                        for role in _MENTION_HISTORY_ROLES
                    ),
                ),
            )
        )
        users = [*users, *rows.scalars().all()]

    if q:
        needle = q.lower()
        users = [
            u
            for u in users
            if needle in (u.email or "").lower() or needle in (u.name or "").lower()
        ]
    users.sort(key=lambda u: (u.id not in team_ids, (u.name or u.email).lower()))
    return [UserBrief.model_validate(u) for u in users]


# ── Preferences ────────────────────────────────────────────────────────────


@router.get("/me/preferences", response_model=UserPreferencesResponse)
async def get_my_preferences(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Zwraca aktualne preferencje bieżącego użytkownika."""
    return await _preferences_response(db, current_user)


@router.patch("/me/preferences", response_model=UserPreferencesResponse)
async def update_my_preferences(
    payload: UserPreferencesUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Częściowa aktualizacja preferencji bieżącego użytkownika.

    Obsługuje dziś tylko `kpi_coach_enabled`. W przyszłości rozszerzymy o
    kolejne toggle (slack_channel, email_digest itp.).
    """
    changed = False
    if payload.kpi_coach_enabled is not None:
        current_user.kpi_coach_enabled = payload.kpi_coach_enabled
        changed = True

    if payload.daily_digest_email_enabled is not None:
        current_user.daily_digest_email_enabled = payload.daily_digest_email_enabled
        changed = True

    if payload.jarvis is not None:
        update = payload.jarvis
        if update.character is not None:
            unlocked = await unlocked_characters(db, current_user.id)
            if update.character not in unlocked:
                raise HTTPException(
                    status_code=403,
                    detail=UNLOCKABLE_CHARACTERS.get(
                        update.character, "Ta postać nie jest jeszcze odblokowana."
                    ),
                )
        try:
            merged = apply_update(effective_prefs(current_user.jarvis_prefs), update)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        current_user.jarvis_prefs = merged.model_dump()
        changed = True

    if changed:
        await db.commit()
        await db.refresh(current_user)

    return await _preferences_response(db, current_user)


# ── „Maile do Ciebie” (0427) ───────────────────────────────────────────────
#
# Lista maili stała do 09.10.2026 tylko w zakładce administratora (polityka
# całej firmy). Tu każde konto widzi swoje maile i każdy z nich wyłącza sobie.


class MyEmailNotification(BaseModel):
    id: str
    label: str
    description: str
    company_enabled: bool
    self_enabled: bool
    # Wynik końcowy: firmowo włączony, niewyłączony przez konto i bez blokady.
    receiving: bool
    state: Literal["on", "self_off", "company_off", "bell_muted", "role_muted"]
    note: Optional[str] = None


class MyEmailRef(BaseModel):
    id: str
    label: str


class MyAlwaysOnEmail(MyEmailRef):
    description: str


class MyEmailNotificationsResponse(BaseModel):
    # `false` = wysyłka maili z NEXUSA nie jest teraz skonfigurowana.
    channel_ready: bool
    items: List[MyEmailNotification]
    not_applicable: List[MyEmailRef]
    always_on: List[MyAlwaysOnEmail]


class MyEmailNotificationUpdate(BaseModel):
    enabled: bool


@router.get("/me/email-notifications", response_model=MyEmailNotificationsResponse)
async def get_my_email_notifications(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Które maile dostaje bieżące konto i które są wyłączone (i przez kogo)."""
    return await notification_email_prefs.my_view(db, current_user)


@router.put(
    "/me/email-notifications/{kind}", response_model=MyEmailNotificationsResponse
)
async def set_my_email_notification(
    kind: str,
    payload: MyEmailNotificationUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Włącz albo wyłącz jeden mail tylko temu kontu (dzwonek bez zmian)."""
    try:
        await notification_email_prefs.set_enabled(
            db, current_user, kind, payload.enabled
        )
    except notification_email_prefs.UnknownEmailKind as exc:
        raise HTTPException(status_code=422, detail="Nie ma takiego maila.") from exc
    except notification_email_prefs.EmailKindNotApplicable as exc:
        raise HTTPException(
            status_code=422,
            detail="Ten mail nie trafia do Twojego konta, więc nie ma czego wyłączać.",
        ) from exc
    await db.commit()
    await db.refresh(current_user)
    return await notification_email_prefs.my_view(db, current_user)
