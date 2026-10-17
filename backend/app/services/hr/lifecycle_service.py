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
  ostatniego dnia, wyłączenie konta (``deactivation``) dzień później, ale
  dopiero po przekazaniu całej pracy — oba robi pętla (``lifecycle_jobs``);
  „Wyłącz konto teraz” z nieprzekazaną pracą wymaga jawnego „mimo to”.
  Sprawy z nieprzekazaną pracą nie da się zamknąć. „Cofnij odejście” działa,
  dopóki praca nie zaczęła przechodzić i konto nie jest zamknięte.
* Terminy zadań w dniach roboczych firmy od startu albo ostatniego dnia
  (``lifecycle_dates``).

Moduły Spraw i Sprzętu dostają zdarzenia przez ``lifecycle_integrations``
(``lifecycle_hooks``) — jedno miejsce, bez importu ich kodu tutaj. Szablony
są w ``lifecycle_templates``, odczyt i kształt odpowiedzi w
``lifecycle_payloads``; ich nazwy są dostępne także stąd (trasy i testy).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
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
from app.services.hr.lifecycle_errors import LifecycleConflict, LifecycleError
from app.services.hr.lifecycle_hooks import LifecycleEvent, lifecycle_integrations
from app.services.hr.lifecycle_payloads import (
    case_handovers,
    case_link,
    case_payload,
    case_tasks,
    handover_started,
    latest_case_for,
    person_name,
    task_payload,
    template_payload,
)
from app.services.hr.lifecycle_templates import (
    ItemInput,
    pick_template,
    save_template,
    template_items,
    templates,
    validate_item,
)
from app.services.hr.notify import notify_each
from app.services.hr_foundation_schema import WORKING_STATUSES, EmploymentStatus
from app.services.hr_lifecycle_schema import (
    EXIT_INITIATORS,
    EXIT_REASONS,
    LIVE_CASE_STATUSES,
    TRANSFER_KINDS,
)
from app.services.user_email import find_user_by_email, normalize_email

#: Pola kartoteki, które kreator wejścia zapisuje przy starcie.
PROFILE_FIELDS: tuple[str, ...] = tuple(
    field for field in people.EDITABLE_FIELDS if field not in ("employment_status",)
)
_DATE_FIELDS = ("hired_on", "work_start_date", "last_working_day")


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
    """Zadania z szablonu zgodne z bieżącym szablonem i datą sprawy — w miejscu.

    * pozycja ze zrobionym albo pominiętym zadaniem — nic (zrobione nie wraca),
    * pozycja z otwartym zadaniem — nowy termin, tytuł i wykonawca w tym samym
      wierszu (notatka zostaje); nadmiarowe kopie tej samej pozycji znikają,
    * pozycja bez zadania — nowe zadanie,
    * otwarte zadanie z pozycji spoza bieżącego szablonu (zmiana szablonu) —
      znika. Zadania ręczne i odpięte (``template_item_id`` NULL) zostają.
    """

    tasks = list(
        await db.scalars(
            select(LifecycleTask)
            .where(
                LifecycleTask.case_id == case.id,
                LifecycleTask.template_item_id.is_not(None),
            )
            .order_by(LifecycleTask.id)
        )
    )
    items = (
        await template_items(db, case.template_id)
        if case.template_id is not None
        else []
    )
    wanted = {item.id for item in items}
    by_item: dict[int, list[LifecycleTask]] = {}
    for task in tasks:
        if task.template_item_id not in wanted:
            if task.status == "open":
                await db.delete(task)
            continue
        by_item.setdefault(task.template_item_id, []).append(task)
    for planned in await plan_tasks(db, items, anchor_of(case)):
        existing = by_item.get(planned.item_id, [])
        if any(task.status != "open" for task in existing):
            for task in existing:
                if task.status == "open":
                    await db.delete(task)
            continue
        if existing:
            task, *copies = existing
            for copy in copies:
                await db.delete(copy)
        else:
            task = LifecycleTask(case_id=case.id, template_item_id=planned.item_id)
            db.add(task)
        task.position = planned.position
        task.title = planned.title
        task.category = planned.category
        task.assignee_kind = planned.assignee_kind
        task.assignee_user_id = assignee_for(case, planned.assignee_kind)
        task.due_date = planned.due_date
    await db.flush()


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
    if profile.employment_status == EmploymentStatus.exited:
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
    previous_manager_id = case.manager_user_id
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
        from app.services.hr.handover import (  # noqa: PLC0415
            plan_handovers,
            retarget_default_receivers,
        )

        await plan_handovers(db, case)
        if "manager_user_id" in changed:
            # Przekazanie jeszcze nie ruszyło (`_ensure_editable`): domyślny
            # przejmujący to przełożony, więc idzie za zmianą przełożonego.
            await retarget_default_receivers(
                db, case, previous_manager_id=previous_manager_id
            )
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
        values["employment_status"] = EmploymentStatus.onboarding.value
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
        profile.employment_status = EmploymentStatus.offboarding
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
                and profile.employment_status == EmploymentStatus.offboarding
            ):
                profile.employment_status = EmploymentStatus.active
                if profile.last_working_day == case.last_working_day:
                    profile.last_working_day = None
                profile.updated_by = actor.id
            elif (
                case.kind == "onboarding"
                and profile.employment_status == EmploymentStatus.onboarding
            ):
                profile.employment_status = EmploymentStatus.pending
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
    if was_active:
        # Sprawy i Sprzęt zamykają to, co założyły przy starcie.
        await lifecycle_integrations(
            db,
            case,
            "offboarding_cancelled"
            if case.kind == "offboarding"
            else "onboarding_cancelled",
        )
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
    if case.kind == "offboarding":
        from app.services.hr.handover import kinds_label, unfinished_kinds  # noqa: PLC0415

        pending = unfinished_kinds(await case_handovers(db, case.id))
        if pending:
            # Zamknięta sprawa wypada z pętli przekazania — praca zostałaby
            # przy osobie, która odeszła.
            raise LifecycleConflict(
                f"Praca nie została przekazana ({kinds_label(pending)}). "
                "Wskaż przejmującego — pętla dokończy przekazanie, potem zamknij sprawę."
            )
    case.status = "done"
    case.completed_at = local_now()
    if case.kind == "onboarding" and case.user_id is not None:
        profile = await people.profile_of(db, case.user_id)
        if (
            profile is not None
            and profile.employment_status == EmploymentStatus.onboarding
        ):
            profile.employment_status = EmploymentStatus.active
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
    from app.services.hr.handover import plan_handovers, receiver_issue  # noqa: PLC0415

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
            problem = await receiver_issue(db, receiver, work_kind, case)
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


async def deactivate_now(
    db: AsyncSession,
    case: LifecycleCase,
    *,
    actor: User,
    despite_handover: bool,
) -> LifecycleCase:
    """„Wyłącz konto teraz” — jedno konto, decyzja Kadr, w dniu wyłączenia.

    Najpierw przekazanie pracy (gdy jeszcze nie przeszła). Konto z nieprzekazaną
    pracą wyłącza się tylko jawnym „mimo to” (``despite_handover``) — wtedy
    zostaje to w śladzie, a pętla dalej próbuje przekazać pracę, gdy Kadry
    wskażą przejmującego (przekazanie widzi pracę wyłączonego konta).
    """

    from app.services.hr.deactivation import close_account  # noqa: PLC0415
    from app.services.hr.handover import (  # noqa: PLC0415
        execute_handover,
        kinds_label,
        unfinished_kinds,
    )
    from app.services.hr.lifecycle_dates import handover_due  # noqa: PLC0415

    if case.kind != "offboarding" or case.status != "active":
        raise LifecycleConflict("To nie jest odejście w toku.")
    if case.account_closed_at is not None:
        raise LifecycleConflict("Konto jest już zamknięte.")
    if case.deactivate_on is None or business_today() < case.deactivate_on:
        raise LifecycleConflict(
            "Konto wyłącza się najwcześniej dzień po ostatnim dniu pracy."
        )
    now = local_now()
    if case.handover_executed_at is None and handover_due(case.last_working_day, now):
        await execute_handover(db, case, now=now)
    pending = (
        unfinished_kinds(await case_handovers(db, case.id))
        if case.handover_executed_at is None
        else []
    )
    if pending and not despite_handover:
        raise LifecycleConflict(
            f"Praca nie została przekazana ({kinds_label(pending)}). Wskaż "
            "przejmującego albo wyłącz konto mimo to — praca zostanie przy osobie, "
            "dopóki ktoś jej nie przejmie."
        )
    await close_account(db, case, now=now, actor_id=actor.id)
    if pending:
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=case.user_id,
            entity_type="lifecycle_case",
            entity_id=case.id,
            action="account_closed_despite_handover",
            details={"kinds": pending},
        )
    await lifecycle_integrations(db, case, "exit_executed")
    await db.flush()
    return case


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
    item = validate_item(ItemInput(title, category, assignee_kind, 0))
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
    """Dzwonek do wykonawców (bez autora zmiany); nie cofa zapisu sprawy."""

    name = await person_name(db, case)
    label = "wejście" if case.kind == "onboarding" else "odejście"
    title = (
        f"Zaległe zadania: {label} — {name}"
        if reminder
        else f"Zadania: {label} — {name}"
    )
    sent = 0
    for user_id, items in (await task_recipients(db, case, tasks)).items():
        titles = "; ".join(task.title for task in items[:3])
        more = f" i {len(items) - 3} więcej" if len(items) > 3 else ""
        sent += await notify_each(
            db,
            [user_id],
            exclude=[actor_id],
            title=title,
            message=f"{titles}{more}.",
            ntype=NotificationType.hr_lifecycle_task,
            link=case_link(case),
            related_entity_type="lifecycle_case",
            related_entity_id=case.id,
            log_tag="hr_lifecycle",
        )
    return sent


__all__ = [
    "ItemInput",
    "LifecycleConflict",
    "LifecycleError",
    "LifecycleEvent",
    "add_task",
    "cancel_case",
    "case_handovers",
    "case_link",
    "case_payload",
    "case_tasks",
    "complete_case",
    "create_offboarding",
    "create_onboarding",
    "deactivate_now",
    "handover_started",
    "latest_case_for",
    "lifecycle_integrations",
    "notify_assignees",
    "person_name",
    "pick_template",
    "plan_tasks",
    "save_template",
    "set_receivers",
    "start_case",
    "task_payload",
    "template_items",
    "template_payload",
    "templates",
    "update_case",
    "update_task",
]
