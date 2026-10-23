"""Katalog ludzi i kartoteka pracownika („Ludzie w NEXUSIE”, krok E0).

Zakres widoczności (rozstrzyga ``viewer_scope``):

* **wizytówka** — każdy, kto ma kartotekę albo Kadry: imię, stanowisko, dział,
  przełożony, miejsce pracy, telefon służbowy, status (bez formy umowy i dat),
* **pełna kartoteka** — sama osoba, jej przełożony (bezpośredni), Kadry
  i Finanse (Płace),
* **forma umowy** (UoP / B2B / zlecenie i pola od niej zależne) — tylko sama
  osoba, jej bezpośredni przełożony, admin i Finanse (decyzja Artura
  19.10.2026); Kadry bez Płac dostają kartotekę bez formy. Rozstrzyga
  ``form_viewer`` — jedna reguła dla katalogu, kartoteki, „Struktury”
  i „Mojego zespołu” (Jarvis czyta te same trasy),
* stawki i kwoty — nigdy tutaj (moduł Płace, uprawnienie ``payroll``).

Zapis kartoteki tylko przez Kadry (``people_admin``); formę mogą zmienić
także Kadry, które jej nie widzą (decyzja Artura 19.10.2026). Każda zmiana
zostawia wiersz w ``hr_audit_events`` z nazwami pól.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import CompanyDayOff, EmployeeProfile, LeaveEntitlement
from app.models.oauth_client import OAuthClient
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.core.scheduling import business_today
from app.services.hr import audit
from app.services.hr.leave_policy import statutory_entitlement
from app.services.hr_foundation_schema import (
    DIVISIONS,
    EMPLOYMENT_STATUSES,
    EMPLOYMENT_TYPES,
    LOCATIONS,
    WORKING_STATUSES,
    EmploymentStatus,
    EmploymentType,
)

Scope = Literal["none", "card", "full"]

#: Statusy widoczne w katalogu (osoba pracuje albo kończy).
DIRECTORY_STATUSES: tuple[str, ...] = WORKING_STATUSES

#: Pola kartoteki, które Kadry mogą zmieniać.
EDITABLE_FIELDS: tuple[str, ...] = (
    "manager_user_id",
    "employment_type",
    "employment_status",
    "hired_on",
    "work_start_date",
    "last_working_day",
    "default_location",
    "timesheet_required",
    "can_log_overtime",
    "job_title",
    "department",
    "phone",
    "division",
    # Etap 2 (D8, D9): uczeń/student na zleceniu, staż do urlopu na UoP.
    "student_contribution_exempt",
    "contribution_exempt_until",
    "leave_seniority_years",
    "zus_certificate_received_on",
)

#: Pola, które mają sens tylko przy danej formie (``_form_rules``).
STUDENT_FIELDS: tuple[str, ...] = (
    "student_contribution_exempt",
    "contribution_exempt_until",
)
UOP_FIELDS: tuple[str, ...] = ("leave_seniority_years", "zus_certificate_received_on")

_MAX_MANAGER_CHAIN = 50


class HrPeopleError(ValueError):
    """Błąd walidacji z komunikatem dla użytkownika (po polsku)."""


def is_people_admin(user: User) -> bool:
    return has_permission(user, ProductAction.people_admin)


def sees_every_form(user: User) -> bool:
    """Formę umowy każdej osoby widzą admin i Finanse (uprawnienie „Płace”)."""

    return user.has_role(UserRole.admin) or has_permission(user, ProductAction.payroll)


async def profile_of(db: AsyncSession, user_id: int) -> Optional[EmployeeProfile]:
    return await db.scalar(
        select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
    )


async def has_live_profile(db: AsyncSession, user_id: int) -> bool:
    """Żywa kartoteka osoby w firmie.

    Rada nadzorcza (0490) nie jest pracownikiem: konto zakłada pierwsze
    logowanie jako „Pracownik” razem z kartoteką, która po zmianie roli
    zostaje — nie otwiera katalogu ludzi, samoobsługi ani zgód (audyt 22.10.2026).
    """
    row = (
        await db.execute(
            select(EmployeeProfile.employment_status, User.role, User.roles)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(EmployeeProfile.user_id == user_id)
        )
    ).first()
    if row is None or row.employment_status == EmploymentStatus.exited:
        return False
    board = UserRole.board
    return row.role != board and board.value not in (row.roles or ())


async def can_supervise(db: AsyncSession, user_id: Optional[int]) -> bool:
    """Czy konto może mieć podwładnych: aktywne, a kartoteka (jeśli jest) ≠ ``exited``.

    Konto bez kartoteki (np. zarząd) się liczy — ta sama reguła co żywy
    przełożony w ``recipients.supervisor_of``. Kto odszedł albo ma wyłączone
    konto, nie ma podwładnych w żadnym zakresie („Mój zespół”, akceptacje,
    kolejki, pełna kartoteka), dopóki Kadry nie przepną jego ludzi.
    """

    if user_id is None:
        return False
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return False
    status = await db.scalar(
        select(EmployeeProfile.employment_status).where(
            EmployeeProfile.user_id == user_id
        )
    )
    return status != EmploymentStatus.exited


async def direct_report_ids(db: AsyncSession, manager_user_id: int) -> set[int]:
    """Bezpośredni podwładni z kartoteką (≠ ``exited``) żywego przełożonego."""

    if not await can_supervise(db, manager_user_id):
        return set()
    rows = await db.scalars(
        select(EmployeeProfile.user_id).where(
            EmployeeProfile.manager_user_id == manager_user_id,
            EmployeeProfile.employment_status != EmploymentStatus.exited,
        )
    )
    return set(rows)


async def viewer_scope(
    db: AsyncSession, viewer: User, subject: EmployeeProfile
) -> Scope:
    if (
        viewer.id == subject.user_id
        or is_people_admin(viewer)
        or sees_every_form(viewer)
    ):
        return "full"
    # Ta sama reguła co ``direct_report_ids``: osoba, która odeszła, nie jest
    # już „podwładnym” — były przełożony widzi jej wizytówkę (audyt A4, 19.10.2026).
    if (
        subject.manager_user_id is not None
        and subject.manager_user_id == viewer.id
        and subject.employment_status != EmploymentStatus.exited
        and await can_supervise(db, viewer.id)
    ):
        return "full"
    if await has_live_profile(db, viewer.id):
        return "card"
    return "none"


@dataclass(frozen=True)
class PersonRow:
    user: User
    profile: EmployeeProfile
    manager_name: Optional[str]


async def directory(db: AsyncSession) -> list[PersonRow]:
    rows = (
        await db.execute(
            select(EmployeeProfile, User)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(EmployeeProfile.employment_status.in_(DIRECTORY_STATUSES))
            .order_by(User.name, User.id)
        )
    ).all()
    manager_ids = {p.manager_user_id for p, _ in rows if p.manager_user_id}
    names: dict[int, str] = {}
    if manager_ids:
        names = dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(manager_ids))
                )
            ).all()
        )
    return [
        PersonRow(
            user=user,
            profile=profile,
            manager_name=names.get(profile.manager_user_id)
            if profile.manager_user_id
            else None,
        )
        for profile, user in rows
    ]


def card_payload(row: PersonRow) -> dict[str, Any]:
    profile = row.profile
    return {
        "user_id": row.user.id,
        "name": row.user.name,
        "email": row.user.email,
        "job_title": profile.job_title,
        "department": profile.department,
        "phone": profile.phone,
        "default_location": profile.default_location,
        "employment_status": profile.employment_status,
        "manager_user_id": profile.manager_user_id,
        "manager_name": row.manager_name,
    }


def contributions_from(profile: EmployeeProfile) -> Optional[date]:
    """Od kiedy Płace naliczają składki uczniowi/studentowi (dzień po końcu zwolnienia)."""

    if not profile.student_contribution_exempt or not profile.contribution_exempt_until:
        return None
    return profile.contribution_exempt_until + timedelta(days=1)


#: Daty, które widzą tylko osoba i Finanse (Płace) — przełożony widzi sam znacznik
#: „student” (z końca zwolnienia da się policzyć wiek; przegląd 17.10.2026),
#: Kadry bez Płac nie widzą formy (19.10.2026), więc i tych dat.
HR_ONLY_FIELDS = (
    "contribution_exempt_until",
    "contributions_from",
    "leave_seniority_years",
    "zus_certificate_received_on",
    "suggested_entitlement_days",
)

#: Pola, z których da się odczytać formę umowy (znacznik studenta jest tylko
#: na zleceniu, staż i ZUS tylko na UoP) — znikają razem z formą.
FORM_FIELDS = ("student_contribution_exempt", *HR_ONLY_FIELDS)


@dataclass(frozen=True)
class FormViewer:
    """Kto czyta formę umowy (decyzja Artura 19.10.2026).

    Forma: sama osoba, jej bezpośredni (żywy) przełożony, admin, Finanse.
    Daty zależne od formy (zwolnienie ze składek, staż, ZUS): bez przełożonego.
    Zastępca przełożonego nie ma pełnej kartoteki, więc i formy.
    """

    viewer_id: int
    everyone: bool
    report_ids: frozenset[int]

    def sees(self, user_id: int) -> bool:
        return self.everyone or user_id == self.viewer_id or user_id in self.report_ids

    def sees_dates(self, user_id: int) -> bool:
        return self.everyone or user_id == self.viewer_id


async def form_viewer(db: AsyncSession, viewer: User) -> FormViewer:
    everyone = sees_every_form(viewer)
    return FormViewer(
        viewer_id=viewer.id,
        everyone=everyone,
        report_ids=frozenset()
        if everyone
        else frozenset(await direct_report_ids(db, viewer.id)),
    )


def form_payload(profile: EmployeeProfile, form: FormViewer) -> dict[str, Any]:
    """Forma umowy w zakresie czytającego — jedyne źródło tego pola.

    ``employment_type`` = ``None``: forma ukryta przed czytającym.
    ``employment_type_pending`` — forma „do uzupełnienia” (kartoteka założona
    z konta; wartość to tylko domyślne B2B, którym liczą urlopy i czas). Ten
    znacznik widzą wszyscy z pełną kartoteką, bo nie zdradza formy.
    """

    pending = bool(profile.employment_type_pending)
    if not form.sees(profile.user_id):
        return {"employment_type": None, "employment_type_pending": pending}
    out: dict[str, Any] = {
        "employment_type": profile.employment_type,
        "employment_type_pending": pending,
        "student_contribution_exempt": profile.student_contribution_exempt,
    }
    if form.sees_dates(profile.user_id):
        out.update(
            {
                "contribution_exempt_until": profile.contribution_exempt_until,
                "contributions_from": contributions_from(profile),
                "leave_seniority_years": profile.leave_seniority_years,
                "zus_certificate_received_on": profile.zus_certificate_received_on,
                # Podpowiedź wymiaru urlopu 20/26 (D9) — pulę zatwierdzają Kadry.
                "suggested_entitlement_days": statutory_entitlement(
                    profile.employment_type, profile.leave_seniority_years
                ),
            }
        )
    return out


def full_payload(row: PersonRow, *, form: FormViewer) -> dict[str, Any]:
    return {**_full_payload(row), **form_payload(row.profile, form)}


def _full_payload(row: PersonRow) -> dict[str, Any]:
    profile = row.profile
    return {
        **card_payload(row),
        "hired_on": profile.hired_on,
        "work_start_date": profile.work_start_date,
        "last_working_day": profile.last_working_day,
        "timesheet_required": profile.timesheet_required,
        "can_log_overtime": profile.can_log_overtime,
        "division": profile.division,
        "manager_pending": manager_pending(profile),
        "roles": [role.value for role in row.user.get_all_roles()],
    }


def manager_pending(profile: EmployeeProfile) -> bool:
    """Przełożony „do uzupełnienia”: kartoteka z konta, której nikt go nie dał."""

    return bool(profile.created_from_account) and profile.manager_user_id is None


async def person_row(db: AsyncSession, user_id: int) -> Optional[PersonRow]:
    found = (
        await db.execute(
            select(EmployeeProfile, User)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(EmployeeProfile.user_id == user_id)
        )
    ).first()
    if found is None:
        return None
    profile, user = found
    manager_name = None
    if profile.manager_user_id:
        manager_name = await db.scalar(
            select(User.name).where(User.id == profile.manager_user_id)
        )
    return PersonRow(user=user, profile=profile, manager_name=manager_name)


async def users_without_profile(db: AsyncSession) -> list[dict[str, Any]]:
    """Aktywne konta bez kartoteki (do „Dodaj osobę” w Kadrach).

    Konta techniczne (``automation``, konta integracji) i stary podgląd
    (``user``) pomijamy — to nie są ludzie zatrudnieni w firmie.
    """

    rows = await db.scalars(
        select(User)
        .outerjoin(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .where(User.is_active.is_(True), EmployeeProfile.id.is_(None))
        .order_by(User.name, User.id)
    )
    integration_ids = await integration_account_ids(db)
    return [
        {"user_id": user.id, "name": user.name, "email": user.email}
        for user in rows
        if is_staff_account(user, integration_ids=integration_ids)
    ]


#: Role, które nie są pracą w firmie: konto techniczne „Automatyzacje”, stary
#: podgląd (``user``) i Rada nadzorcza (0490) — bez kartoteki.
NON_STAFF_ROLES = frozenset({UserRole.automation, UserRole.user, UserRole.board})


async def integration_account_ids(db: AsyncSession) -> frozenset[int]:
    """Konta, w których imieniu działają klienci OAuth (``acting_user_id``, 0311).

    To konta integracji (scrapery pracuj.pl / JJIT), nie ludzie. Rola zostaje
    rekrutacyjna, bo przez nią idzie RBAC zapisu kandydatów — „Automatyzacje”
    są tylko do odczytu — więc rozpoznajemy je po kliencie, nie po roli
    (decyzja Artura 20.10.2026).
    """

    rows = await db.scalars(
        select(OAuthClient.acting_user_id).where(
            OAuthClient.acting_user_id.is_not(None)
        )
    )
    return frozenset(rows)


def is_staff_account(user: User, *, integration_ids: Collection[int]) -> bool:
    """Konto pracownicze: ma mieć kartotekę, gdy jest aktywne (19.10.2026).

    Niepotwierdzona rejestracja (``email_verified`` = false) jeszcze nie jest
    osobą w firmie. Konta serwisowe kluczy API żyją w ``service_accounts``,
    konta integracji OAuth podaje ``integration_account_ids``.
    """

    return (
        bool(user.email_verified)
        and user.id not in integration_ids
        and not (set(user.get_all_roles()) & NON_STAFF_ROLES)
    )


#: Klucz blokady zmian przełożonych (``pg_advisory_xact_lock``): sprawdzenie
#: pętli czyta łańcuch cudzych kartotek, więc dwie równoległe zmiany (A pod B
#: i B pod A) przeszłyby obie. Biorą ją: kartoteka, „Struktura” i przekazanie
#: podwładnych przy odejściu.
_STRUCTURE_LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock(hashtext('hr_manager_structure'))"
)


async def lock_structure(db: AsyncSession) -> None:
    """Blokada zmian przełożonych do końca transakcji."""

    await db.execute(_STRUCTURE_LOCK_SQL)


async def creates_manager_loop(
    db: AsyncSession, *, user_ids: Collection[int], manager_user_id: int
) -> bool:
    """Czy przepięcie ``user_ids`` pod ``manager_user_id`` tworzy pętlę.

    Pętla powstaje, gdy idąc od nowego przełożonego w górę (obecne kartoteki)
    trafimy na którąś z przepinanych osób — wtedy ona byłaby nad samą sobą.
    Istniejąca już pętla wyżej w łańcuchu też się liczy (nie dokładamy do niej).
    """

    seen = set(user_ids)
    current: Optional[int] = manager_user_id
    for _ in range(_MAX_MANAGER_CHAIN):
        if current is None:
            return False
        if current in seen:
            return True
        seen.add(current)
        current = await db.scalar(
            select(EmployeeProfile.manager_user_id).where(
                EmployeeProfile.user_id == current
            )
        )
    return False


async def validate_managers(
    db: AsyncSession, *, user_ids: Collection[int], manager_user_id: Optional[int]
) -> None:
    """Reguły przełożonego dla jednej osoby albo wielu naraz („Struktura”).

    Nie sam sobie, przełożony z aktywnym kontem, który nie odszedł (kartoteka
    ``exited`` — jak w ``can_supervise``), bez pętli — także wtedy, gdy
    przepinamy zbiór osób (A i B naraz pod osobę, która podlega A).
    """

    if manager_user_id is None:
        return
    if manager_user_id in set(user_ids):
        raise HrPeopleError("Osoba nie może być swoim własnym przełożonym.")
    manager = await db.get(User, manager_user_id)
    if manager is None or not manager.is_active:
        raise HrPeopleError("Wybrany przełożony nie ma aktywnego konta.")
    if not await can_supervise(db, manager_user_id):
        raise HrPeopleError(
            "Wybrany przełożony zakończył współpracę — wybierz osobę, która pracuje."
        )
    # Cykl (A → B → A) zablokowałby akceptacje: nikt nie byłby „nad” nikim.
    if await creates_manager_loop(
        db, user_ids=user_ids, manager_user_id=manager_user_id
    ):
        raise HrPeopleError(
            "Ten wybór tworzy pętlę przełożonych — sprawdź, komu podlega wybrana osoba."
        )


async def _validate_manager(
    db: AsyncSession, *, user_id: int, manager_user_id: Optional[int]
) -> None:
    if manager_user_id is not None:
        await lock_structure(db)
    await validate_managers(db, user_ids=[user_id], manager_user_id=manager_user_id)


def _validate_values(values: dict[str, Any]) -> None:
    if (
        "employment_type" in values
        and values["employment_type"] not in EMPLOYMENT_TYPES
    ):
        raise HrPeopleError("Nieznana forma zatrudnienia.")
    if (
        "employment_status" in values
        and values["employment_status"] not in EMPLOYMENT_STATUSES
    ):
        raise HrPeopleError("Nieznany status zatrudnienia.")
    if "default_location" in values and values["default_location"] not in LOCATIONS:
        raise HrPeopleError("Nieznane domyślne miejsce pracy.")
    if values.get("division") is not None and values["division"] not in DIVISIONS:
        raise HrPeopleError("Nieznany pion firmy.")
    start = values.get("work_start_date")
    last = values.get("last_working_day")
    if start and last and last < start:
        raise HrPeopleError("Ostatni dzień pracy nie może być przed datą startu.")
    seniority = values.get("leave_seniority_years")
    if seniority is not None and not 0 <= seniority <= 60:
        raise HrPeopleError("Staż do urlopu podaje się w latach, od 0 do 60.")
    certificate = values.get("zus_certificate_received_on")
    if certificate is not None and certificate > business_today():
        raise HrPeopleError("Data zaświadczenia z ZUS nie może być z przyszłości.")


def _form_rules(
    clean: dict[str, Any], *, employment_type: str, current: Optional[EmployeeProfile]
) -> dict[str, Any]:
    """Pola zależne od formy (etap 2, D8 i D9).

    Znacznik ucznia/studenta tylko na zleceniu; zmiana formy na inną zdejmuje
    go razem z datą (inaczej Płace dostałyby przypomnienie o składkach osoby na
    B2B). Data końca zwolnienia tylko przy znaczniku. Staż do urlopu
    i zaświadczenie ZUS wpisuje się tylko na umowie o pracę (po zmianie formy
    zostają — przydadzą się przy powrocie na UoP).
    """

    out = dict(clean)
    flag = out.get(
        "student_contribution_exempt",
        current.student_contribution_exempt if current is not None else False,
    )
    if employment_type != EmploymentType.zlecenie:
        if out.get("student_contribution_exempt"):
            raise HrPeopleError(
                "Znacznik ucznia lub studenta dotyczy tylko umowy zlecenie."
            )
        if out.get("contribution_exempt_until") is not None:
            raise HrPeopleError(
                "Datę końca zwolnienia ze składek wpisuje się tylko przy umowie zlecenie."
            )
        if current is not None and current.student_contribution_exempt:
            out["student_contribution_exempt"] = False
            out["contribution_exempt_until"] = None
    elif not flag:
        if out.get("contribution_exempt_until") is not None:
            raise HrPeopleError(
                "Datę końca zwolnienia ze składek wpisuje się przy znaczniku "
                "ucznia lub studenta."
            )
        if current is not None and current.contribution_exempt_until is not None:
            out["contribution_exempt_until"] = None
    if employment_type != EmploymentType.uop:
        for key in UOP_FIELDS:
            if out.get(key) is not None:
                raise HrPeopleError(
                    "Staż do urlopu i zaświadczenie z ZUS dotyczą umowy o pracę."
                )
    if out.get("student_contribution_exempt") is None:
        out.pop("student_contribution_exempt", None)
    return out


async def create_profile(
    db: AsyncSession, *, user_id: int, values: dict[str, Any], actor: User
) -> EmployeeProfile:
    target = await db.get(User, user_id)
    if target is None:
        raise LookupError(user_id)
    if await profile_of(db, user_id) is not None:
        raise HrPeopleError("Ta osoba ma już kartotekę.")
    clean = {key: value for key, value in values.items() if key in EDITABLE_FIELDS}
    _validate_values(clean)
    clean = _form_rules(
        clean,
        employment_type=clean.get("employment_type") or EmploymentType.b2b,
        current=None,
    )
    await _validate_manager(
        db, user_id=user_id, manager_user_id=clean.get("manager_user_id")
    )
    profile = EmployeeProfile(user_id=user_id, updated_by=actor.id, **clean)
    db.add(profile)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="employee_profile",
        entity_id=profile.id,
        action="profile_created",
        details={"fields": sorted(clean)},
    )
    return profile


async def update_profile(
    db: AsyncSession, *, user_id: int, values: dict[str, Any], actor: User
) -> EmployeeProfile:
    profile = await profile_of(db, user_id)
    if profile is None:
        raise LookupError(user_id)
    clean = {key: value for key, value in values.items() if key in EDITABLE_FIELDS}
    merged = {
        "work_start_date": profile.work_start_date,
        "last_working_day": profile.last_working_day,
        **clean,
    }
    _validate_values({**clean, **merged})
    clean = _form_rules(
        clean,
        employment_type=clean.get("employment_type") or profile.employment_type,
        current=profile,
    )
    # Formularz kartoteki wysyła przełożonego zawsze; bez zmiany nie ma czego
    # sprawdzać (przełożony, który odszedł, nie blokuje edycji telefonu).
    if (
        "manager_user_id" in clean
        and clean["manager_user_id"] != profile.manager_user_id
    ):
        await _validate_manager(
            db, user_id=user_id, manager_user_id=clean["manager_user_id"]
        )
    changed = sorted(
        key for key, value in clean.items() if getattr(profile, key) != value
    )
    if "employment_type" in clean and profile.employment_type_pending:
        # Forma „do uzupełnienia” (kartoteka z konta): zapis ją potwierdza,
        # także gdy to ta sama wartość co domyślna.
        profile.employment_type_pending = False
        if "employment_type" not in changed:
            changed = sorted([*changed, "employment_type"])
    previous_manager_id = profile.manager_user_id
    for key in changed:
        setattr(profile, key, clean[key])
    if changed:
        profile.updated_by = actor.id
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=user_id,
            entity_type="employee_profile",
            entity_id=profile.id,
            action="profile_updated",
            details={"fields": changed},
        )
    if "manager_user_id" in changed:
        # Odchodząca osoba: sprawa odejścia idzie za nowym przełożonym.
        from app.services.hr.lifecycle_service import (  # noqa: PLC0415
            follow_profile_manager,
        )

        await db.flush()
        await follow_profile_manager(
            db,
            user_id=user_id,
            previous_manager_id=previous_manager_id,
            manager_user_id=profile.manager_user_id,
            actor_id=actor.id,
            source="profile",
        )
    return profile


async def entitlements_of(db: AsyncSession, user_id: int) -> list[LeaveEntitlement]:
    rows = await db.scalars(
        select(LeaveEntitlement)
        .where(LeaveEntitlement.user_id == user_id)
        .order_by(LeaveEntitlement.year.desc())
    )
    return list(rows)


async def set_entitlement(
    db: AsyncSession,
    *,
    user_id: int,
    year: int,
    entitlement_days: Optional[Decimal],
    carried_over_days: Decimal,
    used_initial_days: Decimal,
    reason: Optional[str],
    actor: User,
) -> LeaveEntitlement:
    profile = await profile_of(db, user_id)
    if profile is None:
        raise LookupError(user_id)
    # D6: pula płatnych dni tylko na umowie o pracę i na B2B z pulą w umowie.
    if profile.employment_type == EmploymentType.zlecenie and any(
        value is not None and value > 0
        for value in (entitlement_days, carried_over_days, used_initial_days)
    ):
        raise HrPeopleError(
            "Na umowie zlecenie nie ma puli płatnych dni — nieobecność jest bez "
            "wynagrodzenia. Pulę ustawia się na umowie o pracę albo na B2B "
            "z płatnymi dniami w umowie."
        )
    for value in (entitlement_days, carried_over_days, used_initial_days):
        if value is not None and (value < 0 or value > 366):
            raise HrPeopleError("Liczba dni musi być między 0 a 366.")
        if value is not None and (value * 2) % 1 != 0:
            raise HrPeopleError("Dni podaje się w pełnych dniach albo połówkach.")
    row = await db.scalar(
        select(LeaveEntitlement).where(
            LeaveEntitlement.user_id == user_id, LeaveEntitlement.year == year
        )
    )
    if row is None:
        row = LeaveEntitlement(user_id=user_id, year=year)
        db.add(row)
    row.entitlement_days = entitlement_days
    row.carried_over_days = carried_over_days
    row.used_initial_days = used_initial_days
    row.reason = reason
    row.set_by = actor.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="leave_entitlement",
        entity_id=row.id,
        action="entitlement_set",
        details={"year": year},
    )
    return row


async def days_off(
    db: AsyncSession, *, year: Optional[int] = None
) -> list[CompanyDayOff]:
    statement = select(CompanyDayOff).order_by(CompanyDayOff.day)
    if year is not None:
        statement = statement.where(
            CompanyDayOff.day >= date(year, 1, 1),
            CompanyDayOff.day <= date(year, 12, 31),
        )
    return list(await db.scalars(statement))


async def add_day_off(
    db: AsyncSession, *, day: date, name: str, kind: str, actor: User
) -> CompanyDayOff:
    name = name.strip()
    if not name:
        raise HrPeopleError("Podaj nazwę dnia wolnego.")
    if kind not in ("company", "bridge"):
        raise HrPeopleError("Nieznany rodzaj dnia wolnego.")
    if day.weekday() >= 5:
        raise HrPeopleError("Weekend i tak jest wolny — wybierz dzień roboczy.")
    if await db.scalar(select(CompanyDayOff.id).where(CompanyDayOff.day == day)):
        raise HrPeopleError("Ten dzień jest już na liście dni wolnych.")
    row = CompanyDayOff(day=day, name=name[:120], kind=kind, created_by=actor.id)
    db.add(row)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="company_day_off",
        entity_id=row.id,
        action="day_off_added",
        details={"day": day.isoformat()},
    )
    await _recount_leave(db, day=day, actor=actor, added=True)
    return row


async def remove_day_off(db: AsyncSession, *, day_off_id: int, actor: User) -> None:
    row = await db.get(CompanyDayOff, day_off_id)
    if row is None:
        raise LookupError(day_off_id)
    day = row.day
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="company_day_off",
        entity_id=row.id,
        action="day_off_removed",
        details={"day": day.isoformat()},
    )
    await db.delete(row)
    await db.flush()
    await _recount_leave(db, day=day, actor=actor, added=False)


async def _recount_leave(
    db: AsyncSession, *, day: date, actor: User, added: bool
) -> None:
    """Złożone wnioski obejmujące ``day`` dostają dni wg nowego kalendarza —
    inaczej dzień wolny dodany po złożeniu wniosku dalej zjadałby pulę."""

    from app.services.hr import leave_service

    await leave_service.recount_for_company_day_off(
        db, day=day, actor=actor, added=added
    )
