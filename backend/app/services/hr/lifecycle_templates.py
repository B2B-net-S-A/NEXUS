"""Szablony list zadań wejścia i odejścia („Ludzie w NEXUSIE”, krok E4).

Szablon to przepis na zadania nowych spraw: dobór najlepiej pasującego
(dział i forma > forma > dział > ogólny) i zapis listy pozycji w miejscu
(save_template). Zadania założonych już spraw zostają przy swoich
pozycjach — przeliczenie terminów robi lifecycle_service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_lifecycle import LifecycleTemplate, LifecycleTemplateItem
from app.models.user import User
from app.services.hr import audit
from app.services.hr.lifecycle_errors import LifecycleError
from app.services.hr_lifecycle_schema import (
    ASSIGNEE_KINDS,
    MAX_OFFSET_AFTER,
    MAX_OFFSET_BEFORE,
    TASK_CATEGORIES,
)


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
    #: Id istniejącej pozycji szablonu (edycja w miejscu); ``None`` = nowa
    #: albo z frontu, który id nie odsyła (wtedy dopasowanie po tytule).
    id: Optional[int] = None


def validate_item(item: ItemInput) -> ItemInput:
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
        title[:200], item.category, item.assignee_kind, item.due_offset_days, item.id
    )


def _title_key(title: str) -> str:
    return " ".join(title.split()).casefold()


def _match_items(
    existing: list[LifecycleTemplateItem], items: list[ItemInput]
) -> list[Optional[LifecycleTemplateItem]]:
    """Pozycja z formularza → istniejący wiersz szablonu (``None`` = nowa).

    Najpierw po id (pozycja z innego szablonu albo podana dwa razy = 422),
    potem — dla pozycji bez id — po tytule wśród jeszcze niedopasowanych.
    """

    by_id = {row.id: row for row in existing}
    taken: set[int] = set()
    matched: list[Optional[LifecycleTemplateItem]] = []
    for item in items:
        if item.id is None:
            matched.append(None)
            continue
        row = by_id.get(item.id)
        if row is None:
            raise LifecycleError(
                "Pozycja listy nie należy do tego szablonu — odśwież widok."
            )
        if row.id in taken:
            raise LifecycleError("Ta sama pozycja listy występuje dwa razy.")
        taken.add(row.id)
        matched.append(row)
    for index, item in enumerate(items):
        if matched[index] is not None:
            continue
        key = _title_key(item.title)
        row = next(
            (
                row
                for row in existing
                if row.id not in taken and _title_key(row.title) == key
            ),
            None,
        )
        if row is not None:
            taken.add(row.id)
            matched[index] = row
    return matched


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
    Pozycje zmieniają się W MIEJSCU (to samo id), bo zadania spraw wskazują
    pozycję, z której powstały: przeliczenie terminów rozpoznaje po niej, co
    już jest (bez dublowania i bez otwierania zrobionych). Pozycja usunięta
    z listy znika z szablonu, a jej zadania w sprawach zostają jako zwykłe
    zadania sprawy (``template_item_id`` → NULL) — z historią i bez kopii.
    """

    clean_name = name.strip()
    if not clean_name:
        raise LifecycleError("Podaj nazwę szablonu.")
    clean_items = [validate_item(item) for item in items]
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
    existing = await template_items(db, template.id) if template_id else []
    matched = _match_items(existing, clean_items)
    kept = {row.id for row in matched if row is not None}
    for row in existing:
        if row.id not in kept:
            await db.delete(row)
    for position, (item, row) in enumerate(zip(clean_items, matched)):
        if row is None:
            row = LifecycleTemplateItem(template_id=template.id)
            db.add(row)
        row.position = position
        row.title = item.title
        row.category = item.category
        row.assignee_kind = item.assignee_kind
        row.due_offset_days = item.due_offset_days
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


__all__ = [
    "ItemInput",
    "pick_template",
    "save_template",
    "template_items",
    "templates",
    "validate_item",
]
