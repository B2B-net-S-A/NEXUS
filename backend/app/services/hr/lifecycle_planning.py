"""Zadania sprawy ze ścieżki: warunki pozycji, wykonawcy i terminy (etap 3).

Wspólne dla wejścia osoby z kontem (``lifecycle_service``) i wejścia
konsultanta przy kontrakcie (``lifecycle_entry``):

* **warunki** pozycji (O1) — forma współpracy, sprzęt od nas / od klienta,
  student. Pozycja bez warunków jest zawsze. Nieznany sprzęt (klient bez
  ustawienia) wyłącza pozycje z warunkiem sprzętu — tak samo jak hak Sprzętu,
  który zestaw zakłada tylko przy „sprzęt od nas”. Nieznany status studenta
  (konsultant nie ma kartoteki) zostawia pozycję z dopiskiem, żeby ktoś ją
  sprawdził, zamiast cicho jej nie zakładać,
* **wykonawca to rola** — przełożony, osoba, opiekun kontraktu, Delivery Lead
  klienta albo pula (Kadry, recepcja, IT, administracja). Konsultant nie ma
  konta, więc jego zadania („osoba”) i zadania „przełożonego” odhacza opiekun
  kontraktu (O6),
* **terminy** w dniach roboczych firmy od startu albo ostatniego dnia.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_lifecycle import (
    LifecycleCase,
    LifecycleTask,
    LifecycleTemplate,
    LifecycleTemplateItem,
)
from app.services.hr.calendar import load_calendar
from app.services.hr.employment_terms import FORM_SHORT_LABELS
from app.services.hr.lifecycle_dates import calendar_window, shift_working_days

#: Pule wykonawców bez konkretnej osoby w zadaniu.
POOL_KINDS: frozenset[str] = frozenset(
    {"people_admin", "reception", "it", "administration"}
)
#: Dopisek pozycji z warunkiem „student”, gdy statusu nie znamy.
STUDENT_UNKNOWN_HINT = (
    "Dotyczy studenta do 26. roku życia — jeśli osoba nie jest studentem, "
    "oznacz jako pominięte."
)


@dataclass(frozen=True)
class CaseFacts:
    """To, od czego zależą warunki i wykonawcy zadań jednej sprawy."""

    #: ``uop`` / ``b2b`` / ``zlecenie`` (``None`` = nie wiadomo).
    employment_type: Optional[str] = None
    #: ``ours`` / ``client`` (``None`` = klient bez ustawienia).
    equipment: Optional[str] = None
    #: ``None`` = nie wiadomo (konsultant nie ma kartoteki).
    student: Optional[bool] = None
    client_name: Optional[str] = None
    #: Rola wykonawcy → konto (pule zostają bez konta).
    assignees: dict[str, Optional[int]] | None = None


def item_applies(conditions: dict[str, Any] | None, facts: CaseFacts) -> bool:
    """Czy pozycja z tymi warunkami należy do sprawy z tymi faktami."""

    conditions = conditions or {}
    forms = conditions.get("employment_types")
    if forms and facts.employment_type not in forms:
        return False
    equipment = conditions.get("equipment")
    if equipment and facts.equipment != equipment:
        return False
    if conditions.get("student") is True and facts.student is False:
        return False
    return True


def item_source(conditions: dict[str, Any] | None) -> str:
    """Pozycja z warunkiem formy pochodzi „z formy”, reszta „ze ścieżki”."""

    return "form" if (conditions or {}).get("employment_types") else "path"


def item_source_label(
    conditions: dict[str, Any] | None, facts: CaseFacts
) -> Optional[str]:
    if item_source(conditions) != "form":
        return None
    return FORM_SHORT_LABELS.get(facts.employment_type or "")


def item_description(item: LifecycleTemplateItem, facts: CaseFacts) -> Optional[str]:
    description = item.description
    if (item.conditions or {}).get("student") is True and facts.student is None:
        description = (
            f"{description} {STUDENT_UNKNOWN_HINT}"
            if description
            else STUDENT_UNKNOWN_HINT
        )
    return description[:500] if description else None


def assignee_of(facts: CaseFacts, assignee_kind: str) -> Optional[int]:
    """Konkretna osoba dla roli; pule (Kadry, recepcja, IT, administracja) bez osoby."""

    if assignee_kind in POOL_KINDS:
        return None
    return (facts.assignees or {}).get(assignee_kind)


def team_assignees(case: LifecycleCase) -> dict[str, Optional[int]]:
    """Wejście i odejście osoby z kontem: role opieki prowadzi przełożony."""

    return {
        "manager": case.manager_user_id,
        "person": case.user_id,
        "care_owner": case.manager_user_id,
        "delivery_lead": case.manager_user_id,
    }


async def team_facts(db: AsyncSession, case: LifecycleCase) -> CaseFacts:
    """Fakty sprawy osoby z kontem: forma z kreatora albo kartoteki, sprzęt od nas."""

    from app.services.hr import people  # noqa: PLC0415

    profile = await people.profile_of(db, case.user_id) if case.user_id else None
    employment = (case.profile_values or {}).get("employment_type") or (
        profile.employment_type if profile is not None else None
    )
    student = bool(profile.student_contribution_exempt) if profile is not None else None
    return CaseFacts(
        employment_type=employment or "uop",
        equipment="ours",
        student=student,
        assignees=team_assignees(case),
    )


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


def anchor_of(case: LifecycleCase) -> date:
    anchor = case.start_date if case.kind == "onboarding" else case.last_working_day
    assert anchor is not None
    return anchor


async def _template_items(
    db: AsyncSession, template_id: int
) -> list[LifecycleTemplateItem]:
    return list(
        await db.scalars(
            select(LifecycleTemplateItem)
            .where(LifecycleTemplateItem.template_id == template_id)
            .order_by(LifecycleTemplateItem.position, LifecycleTemplateItem.id)
        )
    )


def _apply(
    task: LifecycleTask, item: LifecycleTemplateItem, facts: CaseFacts, due: date
) -> None:
    task.position = item.position
    task.title = item.title
    task.category = item.category
    task.assignee_kind = item.assignee_kind
    task.assignee_user_id = assignee_of(facts, item.assignee_kind)
    task.due_date = due
    task.description = item_description(item, facts)
    task.required = item.required
    task.requires_file = item.requires_file
    task.key = item.key or None
    task.source = item_source(item.conditions)
    task.source_label = item_source_label(item.conditions, facts)
    task.due_offset_days = item.due_offset_days


async def replan_template_tasks(
    db: AsyncSession, case: LifecycleCase, facts: CaseFacts
) -> None:
    """Zadania ze ścieżki zgodne z jej bieżącą wersją i datą sprawy — w miejscu.

    * pozycja ze zrobionym albo pominiętym zadaniem — nic (zrobione nie wraca),
    * pozycja z otwartym zadaniem — nowy termin, tytuł i wykonawca w tym samym
      wierszu (notatka zostaje); nadmiarowe kopie tej samej pozycji znikają,
    * pozycja bez zadania — nowe zadanie,
    * otwarte zadanie z pozycji spoza ścieżki albo spoza warunków sprawy —
      znika. Zadania ręczne, z pakietu klienta i odpięte
      (``template_item_id`` NULL) zostają.

    Po przeliczeniu sprawa jest na bieżącej wersji ścieżki.
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
    template = (
        await db.get(LifecycleTemplate, case.template_id)
        if case.template_id is not None
        else None
    )
    items = [
        item
        for item in (await _template_items(db, template.id) if template else [])
        if item_applies(item.conditions, facts)
    ]
    by_id = {item.id: item for item in items}
    by_item: dict[int, list[LifecycleTask]] = {}
    for task in tasks:
        if task.template_item_id not in by_id:
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
        _apply(task, by_id[planned.item_id], facts, planned.due_date)
    case.template_version = template.version if template else None
    await db.flush()


async def add_missing_items(
    db: AsyncSession,
    case: LifecycleCase,
    template: LifecycleTemplate,
    facts: CaseFacts,
) -> list[LifecycleTask]:
    """„Dociągnij”: pozycje nowszej wersji, których sprawa jeszcze nie ma.

    Tylko dopisuje (O5) — zadań, które sprawa już ma, nie zmienia, a pozycje
    z wersji, na której sprawa powstała, zostają takie, jak były.
    """

    have = set(
        await db.scalars(
            select(LifecycleTask.template_item_id).where(
                LifecycleTask.case_id == case.id,
                LifecycleTask.template_item_id.is_not(None),
            )
        )
    )
    since = case.template_version or 0
    items = [
        item
        for item in await _template_items(db, template.id)
        if item.added_in_version > since
        and item.id not in have
        and item_applies(item.conditions, facts)
    ]
    added: list[LifecycleTask] = []
    for planned, item in zip(await plan_tasks(db, items, anchor_of(case)), items):
        task = LifecycleTask(case_id=case.id, template_item_id=item.id)
        _apply(task, item, facts, planned.due_date)
        db.add(task)
        added.append(task)
    case.template_version = template.version
    await db.flush()
    return added


__all__ = [
    "POOL_KINDS",
    "CaseFacts",
    "PlannedTask",
    "add_missing_items",
    "anchor_of",
    "assignee_of",
    "item_applies",
    "item_source",
    "plan_tasks",
    "replan_template_tasks",
    "team_assignees",
    "team_facts",
]
