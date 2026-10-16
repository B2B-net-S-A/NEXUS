"""Wejście i odejście — sprawy, zadania i przebieg („Ludzie w NEXUSIE”, krok E4).

Prowadzą Kadry (``people_admin``) i admin; przełożony widzi sprawę swojego
człowieka i odhacza jej zadania; wykonawca odhacza swoje zadania
(``lifecycle_access``).

* **Wejście** — szkic z kontem NEXUSA albo z adresem nowej osoby (konto
  zakłada admin w Ustawieniach → Użytkownicy albo powstaje przy pierwszym
  logowaniu Microsoft; NEXUS nie ma zaproszeń). „Rozpocznij” wymaga konta:
  zakłada albo uzupełnia kartotekę (status ``onboarding``), wysyła zadania.
* **Odejście** — ostatni dzień, kto zrezygnował i powód (słownik, bez danych
  o zdrowiu), przełożony; przekazanie pracy (``handover``) po 18:00
  ostatniego dnia, wyłączenie konta (``deactivation``) dzień później — oba
  robi pętla (``lifecycle_jobs``). „Cofnij odejście” działa, dopóki praca nie
  zaczęła przechodzić i konto nie jest zamknięte.
* Terminy zadań w dniach roboczych firmy od startu albo ostatniego dnia
  (``lifecycle_dates``).

Moduły Spraw i Sprzętu dostają zdarzenia przez ``lifecycle_integrations`` —
jedno miejsce, bez importu ich kodu tutaj.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable, Literal, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.hr_lifecycle import (
    LifecycleCase,
    LifecycleTask,
    LifecycleTemplate,
    LifecycleTemplateItem,
    WorkHandover,
)
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr import audit, people
from app.services.hr.calendar import load_calendar
from app.services.hr.lifecycle_access import POOL_KINDS, pool_member_ids
from app.services.hr.lifecycle_dates import (
    calendar_window,
    deactivate_on_for,
    shift_working_days,
)
from app.services.hr_lifecycle_schema import (
    ASSIGNEE_KINDS,
    EXIT_INITIATORS,
    EXIT_REASONS,
    LIVE_CASE_STATUSES,
    MAX_OFFSET_AFTER,
    MAX_OFFSET_BEFORE,
    TASK_CATEGORIES,
    TRANSFER_KINDS,
)
from app.services.user_email import find_user_by_email, normalize_email

logger = logging.getLogger(__name__)

LifecycleEvent = Literal[
    "onboarding_started",
    "offboarding_started",
    "offboarding_cancelled",
    "exit_executed",
]

#: Statusy kartoteki, z którymi osoba „już u nas pracuje” (wejście = konflikt).
WORKING_STATUSES: tuple[str, ...] = ("onboarding", "active", "offboarding")

#: Pola kartoteki, które kreator wejścia zapisuje przy starcie.
PROFILE_FIELDS: tuple[str, ...] = tuple(
    field for field in people.EDITABLE_FIELDS if field not in ("employment_status",)
)
_DATE_FIELDS = ("hired_on", "work_start_date", "last_working_day")


class LifecycleError(ValueError):
    """Błąd walidacji z komunikatem dla użytkownika (422)."""


class LifecycleConflict(Exception):
    """Stan sprawy nie pozwala na zmianę (409)."""


# ── Szablony ─────────────────────────────────────────────────────────────────


async def templates(
    db: AsyncSession, *, kind: Optional[str] = None
) -> list[LifecycleTemplate]:
    statement = select(LifecycleTemplate).order_by(
        LifecycleTemplate.kind,
        LifecycleTemplate.is_active.desc(),
        LifecycleTemplate.name,
    )
    if kind is not None:
        statement = statement.where(LifecycleTemplate.kind == kind)
    return list(await db.scalars(statement))


async def template_items(
    db: AsyncSession, template_id: int
) -> list[LifecycleTemplateItem]:
    return list(
        await db.scalars(
            select(LifecycleTemplateItem)
            .where(LifecycleTemplateItem.template_id == template_id)
            .order_by(LifecycleTemplateItem.position, LifecycleTemplateItem.id)
        )
    )


async def pick_template(
    db: AsyncSession,
    kind: str,
    *,
    employment_type: Optional[str] = None,
    department: Optional[str] = None,
) -> Optional[LifecycleTemplate]:
    """Najlepiej pasujący aktywny szablon: dział i forma > forma > dział > ogólny."""

    candidates = [t for t in await templates(db, kind=kind) if t.is_active]

    def score(template: LifecycleTemplate) -> tuple[int, int]:
        if template.employment_type and template.employment_type != employment_type:
            return (-1, 0)
        if template.department and (
            (template.department or "").strip().lower()
            != (department or "").strip().lower()
        ):
            return (-1, 0)
        return (
            int(bool(template.department)) * 2 + int(bool(template.employment_type)),
            -template.id,
        )

    ranked = sorted(candidates, key=score, reverse=True)
    if not ranked or score(ranked[0])[0] < 0:
        return None
    return ranked[0]


@dataclass(frozen=True)
class ItemInput:
    title: str
    category: str
    assignee_kind: str
    due_offset_days: int


def _validate_item(item: ItemInput) -> ItemInput:
    title = item.title.strip()
    if not title:
        raise LifecycleError("Każde zadanie potrzebuje tytułu.")
    if item.category not in TASK_CATEGORIES:
        raise LifecycleError("Nieznana kategoria zadania.")
    if item.assignee_kind not in ASSIGNEE_KINDS:
        raise LifecycleError("Nieznany wykonawca zadania.")
    if not -MAX_OFFSET_BEFORE <= item.due_offset_days <= MAX_OFFSET_AFTER:
        raise LifecycleError(
            f"Termin to od {MAX_OFFSET_BEFORE} dni roboczych przed "
            f"do {MAX_OFFSET_AFTER} po dacie sprawy."
        )
    return ItemInput(
        title[:200], item.category, item.assignee_kind, item.due_offset_days
    )


async def save_template(
    db: AsyncSession,
    *,
    actor: User,
    template_id: Optional[int],
    kind: str,
    name: str,
    is_active: bool,
    employment_type: Optional[str],
    department: Optional[str],
    items: list[ItemInput],
) -> LifecycleTemplate:
    """Zakłada albo zmienia szablon razem z listą pozycji (lista zastępuje starą).

    Zadania już założonych spraw zostają — szablon to przepis na nowe sprawy.
    """

    clean_name = name.strip()
    if not clean_name:
        raise LifecycleError("Podaj nazwę szablonu.")
    clean_items = [_validate_item(item) for item in items]
    if template_id is None:
        template = LifecycleTemplate(kind=kind, created_by=actor.id)
        db.add(template)
    else:
        template = await db.get(LifecycleTemplate, template_id)
        if template is None:
            raise LookupError(template_id)
        if template.kind != kind:
            raise LifecycleError("Rodzaju szablonu nie można zmienić.")
    template.name = clean_name[:160]
    template.is_active = is_active
    template.employment_type = employment_type or None
    template.department = (department or "").strip()[:200] or None
    template.updated_by = actor.id
    await db.flush()
    await db.execute(
        delete(LifecycleTemplateItem).where(
            LifecycleTemplateItem.template_id == template.id
        )
    )
    for position, item in enumerate(clean_items):
        db.add(
            LifecycleTemplateItem(
                template_id=template.id,
                position=position,
                title=item.title,
                category=item.category,
                assignee_kind=item.assignee_kind,
                due_offset_days=item.due_offset_days,
            )
        )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="lifecycle_template",
        entity_id=template.id,
        action="template_saved",
        details={"kind": kind, "items": len(clean_items), "active": is_active},
    )
    await db.flush()
    return template


# ── Zadania z terminami ──────────────────────────────────────────────────────


def anchor_of(case: LifecycleCase) -> date:
    anchor = case.start_date if case.kind == "onboarding" else case.last_working_day
    assert anchor is not None
    return anchor


def assignee_for(case: LifecycleCase, assignee_kind: str) -> Optional[int]:
    """Konkretna osoba dla zadania; pule (Kadry, recepcja, IT) zostają bez osoby."""

    if assignee_kind == "manager":
        return case.manager_user_id
    if assignee_kind == "person":
        return case.user_id
    return None


@dataclass(frozen=True)
class PlannedTask:
    item_id: Optional[int]
    position: int
    title: str
    category: str
    assignee_kind: str
    due_date: date


async def plan_tasks(
    db: AsyncSession, items: list[LifecycleTemplateItem], anchor: date
) -> list[PlannedTask]:
    start, end = calendar_window(anchor)
    calendar = await load_calendar(db, start, end)
    return [
        PlannedTask(
            item_id=item.id,
            position=item.position,
            title=item.title,
            category=item.category,
            assignee_kind=item.assignee_kind,
            due_date=shift_working_days(calendar, anchor, item.due_offset_days),
        )
        for item in items
    ]


async def _replan_template_tasks(db: AsyncSession, case: LifecycleCase) -> None:
    """Otwarte zadania z szablonu od nowa (zamknięte i ręczne zostają)."""

    await db.execute(
        delete(LifecycleTask).where(
            LifecycleTask.case_id == case.id,
            LifecycleTask.status == "open",
            LifecycleTask.template_item_id.is_not(None),
        )
    )
    if case.template_id is None:
        return
    closed_items = set(
        await db.scalars(
            select(LifecycleTask.template_item_id).where(
                LifecycleTask.case_id == case.id,
                LifecycleTask.template_item_id.is_not(None),
            )
        )
    )
    items = [
        item
        for item in await template_items(db, case.template_id)
        if item.id not in closed_items
    ]
    for planned in await plan_tasks(db, items, anchor_of(case)):
        db.add(
            LifecycleTask(
                case_id=case.id,
                template_item_id=planned.item_id,
                position=planned.position,
                title=planned.title,
                category=planned.category,
                assignee_kind=planned.assignee_kind,
                assignee_user_id=assignee_for(case, planned.assignee_kind),
                due_date=planned.due_date,
            )
        )
    await db.flush()


async def case_tasks(db: AsyncSession, case_id: int) -> list[LifecycleTask]:
    return list(
        await db.scalars(
            select(LifecycleTask)
            .where(LifecycleTask.case_id == case_id)
            .order_by(
                LifecycleTask.due_date.asc().nulls_last(),
                LifecycleTask.position,
                LifecycleTask.id,
            )
        )
    )


# ── Zakładanie spraw ─────────────────────────────────────────────────────────


async def _validate_manager(
    db: AsyncSession, *, manager_user_id: Optional[int], subject_id: Optional[int]
) -> None:
    if manager_user_id is None:
        return
    if subject_id is not None and manager_user_id == subject_id:
        raise LifecycleError("Osoba nie może być swoim własnym przełożonym.")
    manager = await db.get(User, manager_user_id)
    if manager is None or not manager.is_active:
        raise LifecycleError("Wybrany przełożony nie ma aktywnego konta.")


async def _ensure_no_live_case(
    db: AsyncSession,
    *,
    user_id: Optional[int],
    kind: str,
    skip_case_id: Optional[int] = None,
) -> None:
    if user_id is None:
        return
    statement = select(LifecycleCase.id).where(
        LifecycleCase.user_id == user_id,
        LifecycleCase.kind == kind,
        LifecycleCase.status.in_(LIVE_CASE_STATUSES),
    )
    if skip_case_id is not None:
        statement = statement.where(LifecycleCase.id != skip_case_id)
    if await db.scalar(statement.limit(1)) is not None:
        label = "wejścia" if kind == "onboarding" else "odejścia"
        raise LifecycleConflict(f"Ta osoba ma już otwartą sprawę {label}.")


def _clean_profile_values(values: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in values.items():
        if key not in PROFILE_FIELDS:
            continue
        if isinstance(value, date):
            value = value.isoformat()
        clean[key] = value
    return clean


def _profile_values_for_db(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    for key in _DATE_FIELDS:
        if isinstance(out.get(key), str):
            out[key] = date.fromisoformat(out[key])
    return out


async def create_onboarding(
    db: AsyncSession,
    *,
    actor: User,
    user_id: Optional[int],
    email: Optional[str],
    name: Optional[str],
    start_date: date,
    template_id: Optional[int],
    manager_user_id: Optional[int],
    profile_values: dict[str, Any],
) -> LifecycleCase:
    pending_email: Optional[str] = None
    pending_name: Optional[str] = None
    if user_id is None:
        normalized = normalize_email(email)
        if not normalized or "@" not in normalized:
            raise LifecycleError("Wybierz konto albo podaj e-mail nowej osoby.")
        existing = await find_user_by_email(db, normalized)
        if existing is not None:
            user_id = existing.id
        else:
            pending_email = normalized[:255]
            pending_name = (name or "").strip()[:255] or None
            if not pending_name:
                raise LifecycleError("Podaj imię i nazwisko nowej osoby.")
            if await db.scalar(
                select(LifecycleCase.id).where(
                    LifecycleCase.user_id.is_(None),
                    LifecycleCase.status == "draft",
                    LifecycleCase.pending_email == pending_email,
                )
            ):
                raise LifecycleConflict("Szkic wejścia z tym adresem już istnieje.")
    if user_id is not None:
        user = await db.get(User, user_id)
        if user is None:
            raise LookupError(user_id)
        profile = await people.profile_of(db, user_id)
        if profile is not None and profile.employment_status in WORKING_STATUSES:
            raise LifecycleConflict(
                "Ta osoba już u nas pracuje — wejście zakłada się nowej osobie "
                "albo osobie, która wraca po odejściu."
            )
        await _ensure_no_live_case(db, user_id=user_id, kind="onboarding")
    await _validate_manager(db, manager_user_id=manager_user_id, subject_id=user_id)
    values = _clean_profile_values(profile_values)
    values["work_start_date"] = start_date.isoformat()
    if manager_user_id is not None:
        values["manager_user_id"] = manager_user_id
    template = await _resolve_template(
        db,
        template_id,
        kind="onboarding",
        employment_type=values.get("employment_type"),
        department=values.get("department"),
    )
    case = LifecycleCase(
        user_id=user_id,
        pending_email=pending_email,
        pending_name=pending_name,
        kind="onboarding",
        status="draft",
        template_id=template.id if template else None,
        start_date=start_date,
        owner_user_id=actor.id,
        manager_user_id=manager_user_id,
        profile_values=values,
        created_by=actor.id,
    )
    db.add(case)
    await db.flush()
    await _replan_template_tasks(db, case)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="lifecycle_case",
        entity_id=case.id,
        action="onboarding_created",
        details={
            "start_date": start_date.isoformat(),
            "has_account": user_id is not None,
        },
    )
    return case


async def _resolve_template(
    db: AsyncSession,
    template_id: Optional[int],
    *,
    kind: str,
    employment_type: Optional[str],
    department: Optional[str],
) -> Optional[LifecycleTemplate]:
    if template_id is None:
        return await pick_template(
            db, kind, employment_type=employment_type, department=department
        )
    template = await db.get(LifecycleTemplate, template_id)
    if template is None or template.kind != kind:
        raise LifecycleError("Wybrany szablon nie pasuje do tej sprawy.")
    if not template.is_active:
        raise LifecycleError("Wybrany szablon jest wyłączony.")
    return template


def _validate_exit(
    exit_initiator: Optional[str], exit_reason: Optional[str], exit_note: Optional[str]
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if exit_initiator is not None and exit_initiator not in EXIT_INITIATORS:
        raise LifecycleError("Nieznane „kto zakończył współpracę”.")
    if exit_reason is not None and exit_reason not in EXIT_REASONS:
        raise LifecycleError("Nieznany powód odejścia.")
    note = (exit_note or "").strip()[:500] or None
    return exit_initiator, exit_reason, note


async def create_offboarding(
    db: AsyncSession,
    *,
    actor: User,
    user_id: int,
    last_working_day: date,
    exit_initiator: Optional[str],
    exit_reason: Optional[str],
    exit_note: Optional[str],
    manager_user_id: Optional[int],
    manager_given: bool,
    template_id: Optional[int],
    today: Optional[date] = None,
) -> LifecycleCase:
    profile = await people.profile_of(db, user_id)
    if profile is None:
        raise LookupError(user_id)
    if profile.employment_status == "exited":
        raise LifecycleConflict("Ta osoba zakończyła już współpracę.")
    if last_working_day < (today or business_today()):
        raise LifecycleError(
            "Ostatni dzień pracy nie może być w przeszłości — przekazanie pracy "
            "i wyłączenie konta wykonałyby się od razu."
        )
    await _ensure_no_live_case(db, user_id=user_id, kind="offboarding")
    manager_id = manager_user_id if manager_given else profile.manager_user_id
    await _validate_manager(db, manager_user_id=manager_id, subject_id=user_id)
    initiator, reason, note = _validate_exit(exit_initiator, exit_reason, exit_note)
    template = await _resolve_template(
        db,
        template_id,
        kind="offboarding",
        employment_type=profile.employment_type,
        department=profile.department,
    )
    case = LifecycleCase(
        user_id=user_id,
        kind="offboarding",
        status="draft",
        template_id=template.id if template else None,
        last_working_day=last_working_day,
        deactivate_on=deactivate_on_for(last_working_day),
        owner_user_id=actor.id,
        manager_user_id=manager_id,
        exit_initiator=initiator,
        exit_reason=reason,
        exit_note=note,
        created_by=actor.id,
    )
    db.add(case)
    await db.flush()
    await _replan_template_tasks(db, case)
    from app.services.hr.handover import plan_handovers  # noqa: PLC0415

    await plan_handovers(db, case)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="lifecycle_case",
        entity_id=case.id,
        action="offboarding_created",
        details={"last_working_day": last_working_day.isoformat()},
    )
    return case


def handover_started(case: LifecycleCase, handovers: list[WorkHandover]) -> bool:
    return case.handover_executed_at is not None or any(
        row.status == "done" for row in handovers
    )


async def case_handovers(db: AsyncSession, case_id: int) -> list[WorkHandover]:
    rows = await db.scalars(select(WorkHandover).where(WorkHandover.case_id == case_id))
    order = {kind: index for index, kind in enumerate(TRANSFER_KINDS)}
    return sorted(rows, key=lambda row: order.get(row.work_kind, 99))


async def _ensure_editable(db: AsyncSession, case: LifecycleCase) -> None:
    if case.status not in LIVE_CASE_STATUSES:
        raise LifecycleConflict("Sprawa jest zamknięta.")
    if case.kind == "offboarding":
        if case.account_closed_at is not None:
            raise LifecycleConflict("Konto zostało już wyłączone.")
        if handover_started(case, await case_handovers(db, case.id)):
            raise LifecycleConflict("Praca została już przekazana.")


async def update_case(
    db: AsyncSession,
    case: LifecycleCase,
    *,
    actor: User,
    values: dict[str, Any],
    today: Optional[date] = None,
) -> LifecycleCase:
    """Zmiana dat, przełożonego, szablonu albo powodu — przed wykonaniem."""

    await _ensure_editable(db, case)
    changed: list[str] = []
    replan = False
    if (
        "manager_user_id" in values
        and values["manager_user_id"] != case.manager_user_id
    ):
        await _validate_manager(
            db, manager_user_id=values["manager_user_id"], subject_id=case.user_id
        )
        case.manager_user_id = values["manager_user_id"]
        changed.append("manager_user_id")
        await _reassign_manager_tasks(db, case)
    if "template_id" in values and values["template_id"] != case.template_id:
        template = await _resolve_template(
            db,
            values["template_id"],
            kind=case.kind,
            employment_type=None,
            department=None,
        )
        case.template_id = template.id if template else None
        changed.append("template_id")
        replan = True
    if case.kind == "onboarding":
        if values.get("start_date") and values["start_date"] != case.start_date:
            case.start_date = values["start_date"]
            case.profile_values = {
                **(case.profile_values or {}),
                "work_start_date": case.start_date.isoformat(),
            }
            changed.append("start_date")
            replan = True
        if "profile_values" in values and values["profile_values"] is not None:
            merged = {
                **(case.profile_values or {}),
                **_clean_profile_values(values["profile_values"]),
            }
            merged["work_start_date"] = case.start_date.isoformat()
            case.profile_values = merged
            changed.append("profile_values")
        if case.user_id is None:
            if values.get("pending_name"):
                case.pending_name = values["pending_name"].strip()[:255]
                changed.append("pending_name")
    else:
        new_last = values.get("last_working_day")
        if new_last and new_last != case.last_working_day:
            if new_last < (today or business_today()):
                raise LifecycleError("Ostatni dzień pracy nie może być w przeszłości.")
            case.last_working_day = new_last
            case.deactivate_on = deactivate_on_for(new_last)
            changed.append("last_working_day")
            replan = True
            if case.status == "active" and case.user_id is not None:
                profile = await people.profile_of(db, case.user_id)
                if profile is not None:
                    profile.last_working_day = new_last
        exit_fields = {
            key: values[key]
            for key in ("exit_initiator", "exit_reason", "exit_note")
            if key in values
        }
        if exit_fields:
            initiator, reason, note = _validate_exit(
                exit_fields.get("exit_initiator", case.exit_initiator),
                exit_fields.get("exit_reason", case.exit_reason),
                exit_fields.get("exit_note", case.exit_note),
            )
            case.exit_initiator, case.exit_reason, case.exit_note = (
                initiator,
                reason,
                note,
            )
            changed.append("exit")
    if replan:
        await _replan_template_tasks(db, case)
    if case.kind == "offboarding":
        from app.services.hr.handover import plan_handovers  # noqa: PLC0415

        await plan_handovers(db, case)
    if changed:
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=case.user_id,
            entity_type="lifecycle_case",
            entity_id=case.id,
            action="case_updated",
            details={"fields": sorted(changed)},
        )
    await db.flush()
    return case


async def _reassign_manager_tasks(db: AsyncSession, case: LifecycleCase) -> None:
    for task in await case_tasks(db, case.id):
        if task.assignee_kind == "manager" and task.status == "open":
            task.assignee_user_id = case.manager_user_id


async def _link_pending_account(db: AsyncSession, case: LifecycleCase) -> None:
    """Szkic z adresem nowej osoby → konto, gdy już powstało."""

    if case.user_id is not None or not case.pending_email:
        return
    user = await find_user_by_email(db, case.pending_email)
    if user is None:
        raise LifecycleConflict(
            "Konta tej osoby jeszcze nie ma. Zakłada je admin w Ustawieniach → "
            "Użytkownicy albo powstaje przy pierwszym logowaniu przez Microsoft."
        )
    profile = await people.profile_of(db, user.id)
    if profile is not None and profile.employment_status in WORKING_STATUSES:
        raise LifecycleConflict(
            "Konto z tym adresem ma już kartotekę osoby pracującej."
        )
    await _ensure_no_live_case(
        db, user_id=user.id, kind="onboarding", skip_case_id=case.id
    )
    case.user_id = user.id
    case.pending_email = None
    for task in await case_tasks(db, case.id):
        if task.assignee_kind == "person":
            task.assignee_user_id = user.id


async def start_case(
    db: AsyncSession, case: LifecycleCase, *, actor: User
) -> LifecycleCase:
    """Szkic → w toku: kartoteka, zadania do wykonawców, zdarzenie dla modułów."""

    if case.status != "draft":
        raise LifecycleConflict("Sprawa jest już rozpoczęta albo zamknięta.")
    now = local_now()
    if case.kind == "onboarding":
        await _link_pending_account(db, case)
        assert case.user_id is not None
        values = _profile_values_for_db(case.profile_values or {})
        values["employment_status"] = "onboarding"
        values.setdefault("hired_on", case.start_date)
        values["manager_user_id"] = case.manager_user_id
        try:
            if await people.profile_of(db, case.user_id) is None:
                await people.create_profile(
                    db, user_id=case.user_id, values=values, actor=actor
                )
            else:
                values["last_working_day"] = None
                await people.update_profile(
                    db, user_id=case.user_id, values=values, actor=actor
                )
        except people.HrPeopleError as exc:
            raise LifecycleError(str(exc)) from exc
    else:
        assert case.user_id is not None
        if case.last_working_day < business_today():
            raise LifecycleError(
                "Ostatni dzień pracy minął — popraw datę przed startem."
            )
        profile = await people.profile_of(db, case.user_id)
        if profile is None:
            raise LookupError(case.user_id)
        profile.employment_status = "offboarding"
        profile.last_working_day = case.last_working_day
        profile.updated_by = actor.id
    case.status = "active"
    case.started_at = now
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=case.user_id,
        entity_type="lifecycle_case",
        entity_id=case.id,
        action=f"{case.kind}_started",
    )
    await notify_assignees(db, case, await case_tasks(db, case.id), actor_id=actor.id)
    await lifecycle_integrations(
        db,
        case,
        "onboarding_started" if case.kind == "onboarding" else "offboarding_started",
    )
    return case


async def cancel_case(
    db: AsyncSession, case: LifecycleCase, *, actor: User
) -> LifecycleCase:
    """„Cofnij odejście” / anulowanie wejścia — tylko przed wykonaniem."""

    await _ensure_editable(db, case)
    was_active = case.status == "active"
    case.status = "cancelled"
    case.cancelled_at = local_now()
    case.cancelled_by = actor.id
    if case.user_id is not None and was_active:
        profile = await people.profile_of(db, case.user_id)
        if profile is not None:
            if (
                case.kind == "offboarding"
                and profile.employment_status == "offboarding"
            ):
                profile.employment_status = "active"
                if profile.last_working_day == case.last_working_day:
                    profile.last_working_day = None
                profile.updated_by = actor.id
            elif (
                case.kind == "onboarding" and profile.employment_status == "onboarding"
            ):
                profile.employment_status = "pending"
                profile.updated_by = actor.id
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=case.user_id,
        entity_type="lifecycle_case",
        entity_id=case.id,
        action=f"{case.kind}_cancelled",
    )
    await db.flush()
    if case.kind == "offboarding" and was_active:
        await lifecycle_integrations(db, case, "offboarding_cancelled")
    return case


async def complete_case(
    db: AsyncSession, case: LifecycleCase, *, actor: User
) -> LifecycleCase:
    if case.status != "active":
        raise LifecycleConflict("Zamknąć można tylko sprawę w toku.")
    if case.kind == "offboarding" and case.account_closed_at is None:
        raise LifecycleConflict(
            "Odejście zamyka się po wyłączeniu konta (dzień po ostatnim dniu pracy)."
        )
    case.status = "done"
    case.completed_at = local_now()
    if case.kind == "onboarding" and case.user_id is not None:
        profile = await people.profile_of(db, case.user_id)
        if profile is not None and profile.employment_status == "onboarding":
            profile.employment_status = "active"
            profile.updated_by = actor.id
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=case.user_id,
        entity_type="lifecycle_case",
        entity_id=case.id,
        action=f"{case.kind}_completed",
    )
    await db.flush()
    return case


async def set_receivers(
    db: AsyncSession,
    case: LifecycleCase,
    *,
    actor: User,
    receivers: dict[str, Optional[int]],
) -> list[WorkHandover]:
    from app.services.hr.handover import plan_handovers, receiver_problem  # noqa: PLC0415

    if case.kind != "offboarding":
        raise LifecycleConflict("Przekazanie pracy dotyczy odejścia.")
    if case.status not in LIVE_CASE_STATUSES:
        raise LifecycleConflict("Sprawa jest zamknięta.")
    unknown = sorted(set(receivers) - set(TRANSFER_KINDS))
    if unknown:
        raise LifecycleError(f"Nieznany rodzaj pracy: {', '.join(unknown)}.")
    rows = {row.work_kind: row for row in await plan_handovers(db, case)}
    changed: list[str] = []
    for work_kind, receiver_id in receivers.items():
        row = rows[work_kind]
        if row.status == "done":
            if receiver_id != row.receiver_user_id:
                raise LifecycleConflict("Ta praca została już przekazana.")
            continue
        if receiver_id is not None:
            receiver = await db.get(User, receiver_id)
            problem = receiver_problem(receiver, work_kind, case.user_id)
            if problem is not None:
                from app.services.hr.handover import RECEIVER_ERRORS  # noqa: PLC0415

                raise LifecycleError(RECEIVER_ERRORS[problem])
        if row.receiver_user_id != receiver_id:
            row.receiver_user_id = receiver_id
            if row.status == "failed":
                row.status = "planned"
                row.error = None
            changed.append(work_kind)
    if changed:
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=case.user_id,
            entity_type="lifecycle_case",
            entity_id=case.id,
            action="receivers_set",
            details={"kinds": sorted(changed)},
        )
    await db.flush()
    return list(rows.values())


# ── Zadania ──────────────────────────────────────────────────────────────────


async def add_task(
    db: AsyncSession,
    case: LifecycleCase,
    *,
    actor: User,
    title: str,
    category: str,
    assignee_kind: str,
    assignee_user_id: Optional[int],
    due_date: Optional[date],
) -> LifecycleTask:
    if case.status not in LIVE_CASE_STATUSES:
        raise LifecycleConflict("Sprawa jest zamknięta.")
    item = _validate_item(ItemInput(title, category, assignee_kind, 0))
    if assignee_user_id is not None:
        assignee = await db.get(User, assignee_user_id)
        if assignee is None or not assignee.is_active:
            raise LifecycleError("Wykonawca nie ma aktywnego konta.")
    else:
        assignee_user_id = assignee_for(case, item.assignee_kind)
    position = len(await case_tasks(db, case.id))
    task = LifecycleTask(
        case_id=case.id,
        position=position,
        title=item.title,
        category=item.category,
        assignee_kind=item.assignee_kind,
        assignee_user_id=assignee_user_id,
        due_date=due_date,
    )
    db.add(task)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=case.user_id,
        entity_type="lifecycle_task",
        entity_id=task.id,
        action="task_added",
        details={"case_id": case.id},
    )
    if case.status == "active":
        await notify_assignees(db, case, [task], actor_id=actor.id)
    return task


async def update_task(
    db: AsyncSession,
    task: LifecycleTask,
    case: LifecycleCase,
    *,
    actor: User,
    status: Optional[str],
    note: Optional[str],
    note_given: bool,
) -> LifecycleTask:
    if case.status not in LIVE_CASE_STATUSES:
        raise LifecycleConflict("Sprawa jest zamknięta.")
    changed: list[str] = []
    if status is not None and status != task.status:
        task.status = status
        if status == "open":
            task.done_at = None
            task.done_by = None
        else:
            task.done_at = local_now()
            task.done_by = actor.id
        changed.append("status")
    if note_given:
        task.note = (note or "").strip()[:500] or None
        changed.append("note")
    if changed:
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=case.user_id,
            entity_type="lifecycle_task",
            entity_id=task.id,
            action="task_updated",
            details={"fields": changed, "status": task.status},
        )
    await db.flush()
    return task


# ── Powiadomienia ────────────────────────────────────────────────────────────


async def person_name(db: AsyncSession, case: LifecycleCase) -> str:
    if case.user_id is not None:
        name = await db.scalar(select(User.name).where(User.id == case.user_id))
        if name:
            return name
    return case.pending_name or "nowa osoba"


def case_link(case: LifecycleCase) -> str:
    if case.kind == "offboarding" and case.user_id is not None:
        return f"/people/{case.user_id}/offboarding"
    return f"/people/new/{case.id}"


async def task_recipients(
    db: AsyncSession, case: LifecycleCase, tasks: list[LifecycleTask]
) -> dict[int, list[LifecycleTask]]:
    """Kto dostaje dzwonek: osoba z zadania, pula — jej członkowie.

    Zadanie przełożonego bez przełożonego trafia do Kadr (nie znika).
    """

    pools: dict[str, list[int]] = {}
    out: dict[int, list[LifecycleTask]] = {}
    for task in tasks:
        if task.status != "open":
            continue
        if task.assignee_user_id is not None:
            out.setdefault(task.assignee_user_id, []).append(task)
            continue
        pool = (
            task.assignee_kind if task.assignee_kind in POOL_KINDS else "people_admin"
        )
        if pool not in pools:
            pools[pool] = await pool_member_ids(db, pool)
        for user_id in pools[pool]:
            out.setdefault(user_id, []).append(task)
    return out


async def notify_assignees(
    db: AsyncSession,
    case: LifecycleCase,
    tasks: list[LifecycleTask],
    *,
    actor_id: Optional[int],
    reminder: bool = False,
) -> int:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    name = await person_name(db, case)
    label = "wejście" if case.kind == "onboarding" else "odejście"
    sent = 0
    for user_id, items in (await task_recipients(db, case, tasks)).items():
        if user_id == actor_id:
            continue
        titles = "; ".join(task.title for task in items[:3])
        more = f" i {len(items) - 3} więcej" if len(items) > 3 else ""
        title = (
            f"Zaległe zadania: {label} — {name}"
            if reminder
            else f"Zadania: {label} — {name}"
        )
        try:
            async with db.begin_nested():
                created = await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=f"{titles}{more}.",
                    ntype=NotificationType.hr_lifecycle_task,
                    related_entity_type="lifecycle_case",
                    related_entity_id=case.id,
                    link=case_link(case),
                )
            sent += int(created is not None)
        except Exception:  # noqa: BLE001 — dzwonek nie cofa zapisu sprawy
            logger.exception(
                "hr_lifecycle notification failed case=%s user=%s", case.id, user_id
            )
    return sent


# ── Haki dla innych modułów ──────────────────────────────────────────────────

LifecycleHook = Callable[[AsyncSession, LifecycleCase, str], Awaitable[None]]


async def _cases_hook(db: AsyncSession, case: LifecycleCase, event: str) -> None:
    """Sprawy administracja@: odejście zakłada sprawę (idempotentnie po kluczu)."""
    if event != "offboarding_started":
        return
    from app.services.admin_cases.hooks import open_case_for_offboarding

    await open_case_for_offboarding(db, case.user_id, case.id)


def _integration_hooks() -> list[LifecycleHook]:
    return [_cases_hook]


async def lifecycle_integrations(
    db: AsyncSession, case: LifecycleCase, event: LifecycleEvent
) -> None:
    """Jedno miejsce, w którym moduły Spraw i Sprzętu dowiadują się o sprawie.

    Kontrakt (dla koordynatora, który wpina haki):

    * ``event``:
      - ``onboarding_started`` — wejście ruszyło (``case.start_date``,
        ``case.user_id``, ``case.manager_user_id``); Sprzęt: zadanie „Wydaj
        zestaw” na 2 dni robocze przed startem,
      - ``offboarding_started`` — odejście ruszyło (``case.last_working_day``,
        ``case.deactivate_on``); Sprawy: sprawa „Odejście: <osoba>” powiązana
        przez ``lifecycle_case_id``; Sprzęt: zadanie zwrotu rzeczy osoby,
      - ``offboarding_cancelled`` — „Cofnij odejście”; Sprawy/Sprzęt zamykają
        lub anulują to, co założyły przy starcie,
      - ``exit_executed`` — konto zamknięte (``case.account_close_result``);
        Sprzęt: niezwrócone rzeczy → dzwonek do recepcji i przełożonego.
    * Hak dostaje sesję W TRAKCIE transakcji sprawy: dopisuje swoje wiersze,
      nie commituje. Wyjątek haka jest logowany i cofany savepointem — sprawa
      idzie dalej (moduł poboczny nie blokuje odejścia).
    * Hak ma być idempotentny po ``(case.id, event)`` — pętla może wołać
      ``exit_executed`` po restarcie drugi raz dla tej samej sprawy tylko,
      gdy commit pierwszego przebiegu nie doszedł.
    """

    for hook in _integration_hooks():
        try:
            async with db.begin_nested():
                await hook(db, case, event)
        except Exception:  # noqa: BLE001 — moduł poboczny nie blokuje sprawy
            logger.exception(
                "hr_lifecycle integration failed case=%s event=%s hook=%s",
                case.id,
                event,
                getattr(hook, "__qualname__", hook),
            )


# ── Odczyt ───────────────────────────────────────────────────────────────────


def template_payload(
    template: LifecycleTemplate, items: list[LifecycleTemplateItem]
) -> dict[str, Any]:
    return {
        "id": template.id,
        "kind": template.kind,
        "name": template.name,
        "is_active": template.is_active,
        "employment_type": template.employment_type,
        "department": template.department,
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "category": item.category,
                "assignee_kind": item.assignee_kind,
                "due_offset_days": item.due_offset_days,
            }
            for item in items
        ],
    }


async def _names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    ids.discard(None)  # type: ignore[arg-type]
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {user_id: name for user_id, name in rows.all()}


def task_payload(
    task: LifecycleTask, names: dict[int, str], *, can_toggle: bool, today: date
) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "category": task.category,
        "assignee_kind": task.assignee_kind,
        "assignee_user_id": task.assignee_user_id,
        "assignee_name": names.get(task.assignee_user_id)
        if task.assignee_user_id
        else None,
        "due_date": task.due_date,
        "status": task.status,
        "overdue": task.status == "open"
        and task.due_date is not None
        and task.due_date < today,
        "done_at": task.done_at,
        "done_by_name": names.get(task.done_by) if task.done_by else None,
        "note": task.note,
        "from_template": task.template_item_id is not None,
        "can_toggle": can_toggle,
    }


async def case_payload(
    db: AsyncSession,
    case: LifecycleCase,
    *,
    viewer: User,
    scope: str,
    with_work: bool = True,
) -> dict[str, Any]:
    from app.services.hr.handover import WORK_KINDS, work_summary  # noqa: PLC0415
    from app.services.hr.lifecycle_access import can_toggle  # noqa: PLC0415
    from app.services.hr.lifecycle_dates import handover_moment  # noqa: PLC0415

    tasks = await case_tasks(db, case.id)
    handovers = await case_handovers(db, case.id) if case.kind == "offboarding" else []
    ids = {
        case.manager_user_id,
        case.owner_user_id,
        case.user_id,
        *(task.assignee_user_id for task in tasks),
        *(task.done_by for task in tasks),
        *(row.receiver_user_id for row in handovers),
    }
    names = await _names(db, {i for i in ids if i is not None})
    today = business_today()
    template_name = (
        await db.scalar(
            select(LifecycleTemplate.name).where(
                LifecycleTemplate.id == case.template_id
            )
        )
        if case.template_id
        else None
    )
    started = handover_started(case, handovers)
    payload: dict[str, Any] = {
        "id": case.id,
        "kind": case.kind,
        "status": case.status,
        "user_id": case.user_id,
        "person_name": await person_name(db, case),
        "pending_email": case.pending_email if scope == "admin" else None,
        "template_id": case.template_id,
        "template_name": template_name,
        "start_date": case.start_date,
        "last_working_day": case.last_working_day,
        "deactivate_on": case.deactivate_on,
        "handover_at": handover_moment(case.last_working_day)
        if case.last_working_day
        else None,
        "manager_user_id": case.manager_user_id,
        "manager_name": names.get(case.manager_user_id)
        if case.manager_user_id
        else None,
        "owner_name": names.get(case.owner_user_id) if case.owner_user_id else None,
        "started_at": case.started_at,
        "handover_executed_at": case.handover_executed_at,
        "account_closed_at": case.account_closed_at,
        "account_close_result": case.account_close_result,
        "completed_at": case.completed_at,
        "cancelled_at": case.cancelled_at,
        "scope": scope,
        "can_manage": scope == "admin",
        "can_cancel": scope == "admin"
        and case.status in LIVE_CASE_STATUSES
        and case.account_closed_at is None
        and not started,
        "tasks": [
            task_payload(
                task, names, can_toggle=can_toggle(scope, viewer, task), today=today
            )
            for task in tasks
        ],
        "progress": {
            "done": sum(1 for task in tasks if task.status != "open"),
            "total": len(tasks),
            "overdue": sum(
                1
                for task in tasks
                if task.status == "open" and task.due_date and task.due_date < today
            ),
        },
    }
    if scope in ("admin", "manager"):
        payload["exit_initiator"] = case.exit_initiator
        payload["exit_reason"] = case.exit_reason
        payload["exit_note"] = case.exit_note
        if case.kind == "onboarding":
            payload["profile_values"] = case.profile_values or {}
    if case.kind == "offboarding":
        counts: dict[str, int] = {}
        if with_work and case.user_id is not None and case.last_working_day is not None:
            counts = await work_summary(
                db, case.user_id, last_working_day=case.last_working_day
            )
        by_kind = {row.work_kind: row for row in handovers}
        payload["work"] = [
            {
                "kind": kind.key,
                "label": kind.label,
                "note": kind.note,
                "transferable": kind.transferable,
                "count": counts.get(kind.key),
                "receiver_user_id": by_kind[kind.key].receiver_user_id
                if kind.key in by_kind
                else None,
                "receiver_name": names.get(by_kind[kind.key].receiver_user_id)
                if kind.key in by_kind and by_kind[kind.key].receiver_user_id
                else None,
                "status": by_kind[kind.key].status if kind.key in by_kind else None,
                "planned_count": by_kind[kind.key].item_count
                if kind.key in by_kind
                else None,
                "result": by_kind[kind.key].result if kind.key in by_kind else None,
                "error": by_kind[kind.key].error if kind.key in by_kind else None,
            }
            for kind in WORK_KINDS
        ]
    return payload


async def latest_case_for(db: AsyncSession, user_id: int) -> Optional[LifecycleCase]:
    """Ostatnia sprawa osoby (żywa przed zamkniętą)."""

    rows = list(
        await db.scalars(
            select(LifecycleCase)
            .where(LifecycleCase.user_id == user_id)
            .order_by(LifecycleCase.created_at.desc(), LifecycleCase.id.desc())
        )
    )
    live = [row for row in rows if row.status in LIVE_CASE_STATUSES]
    return (live or rows or [None])[0]


__all__ = [
    "LifecycleConflict",
    "LifecycleError",
    "add_task",
    "cancel_case",
    "case_payload",
    "complete_case",
    "create_offboarding",
    "create_onboarding",
    "lifecycle_integrations",
    "notify_assignees",
    "save_template",
    "set_receivers",
    "start_case",
    "update_case",
    "update_task",
]
