"""Sprawy administracja@ — dostęp, zapis i powiadomienia (odczyt: ``queries``).

Dostęp (decyzja planu „Ludzie w NEXUSIE”, 16.10.2026):

* **obsługa** — uprawnienie „Sprawy” (``ProductAction.cases``; domyślnie rola
  Talent Community Manager) albo admin: widzi i zmienia wszystkie sprawy,
* **przypisany** bez uprawnienia — widzi i komentuje wyłącznie sprawy, do
  których jest przypisany; nic w nich nie zmienia.

Powiadomienie ``admin_case_assigned`` dostaje przypisany przy utworzeniu
i zmianie przypisania — nie wtedy, gdy przypisuje sam siebie. W Compassie
powiadomienie dla INNEJ osoby odrzucała polityka bazy i nikt tego nie widział
(audyt 22.09, INT-22); tu idzie przez ``hr.notify.notify_each`` (osobny
punkt zapisu), więc jego porażka nie wywraca sprawy, ale zostaje w logu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.admin_case import AdminCase, AdminCaseComment
from app.models.contract import Contract
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.admin_cases import rules
from app.services.admin_cases_schema import AREAS, PRIORITIES, STATUSES
from app.services.hr import audit
from app.services.hr.notify import notify_each

ENTITY = "admin_case"
COMMENT_MAX = 10_000
DESCRIPTION_MAX = 20_000

STALE_DETAIL = (
    "Sprawa została zmieniona w międzyczasie. Odśwież widok i spróbuj ponownie."
)


class CaseError(ValueError):
    """Odmowa z komunikatem dla użytkownika (422)."""


class CaseConflict(Exception):
    """Zapis na nieaktualnej wersji sprawy (409)."""


def is_handler(user: User) -> bool:
    return user.has_role(UserRole.admin) or has_permission(user, ProductAction.cases)


def may_read(user: User, case: AdminCase) -> bool:
    return is_handler(user) or case.assignee_user_id == user.id


async def module_enabled(db: AsyncSession) -> bool:
    """Przełącznik modułu „cases” — automaty nie zakładają spraw w ciemnym module."""

    from app.services.hr import modules as hr_modules

    return (await hr_modules.load_modules(db)).get(hr_modules.HrModule.cases, False)


async def has_assigned_cases(db: AsyncSession, user_id: int) -> bool:
    found = await db.scalar(
        select(AdminCase.id).where(AdminCase.assignee_user_id == user_id).limit(1)
    )
    return found is not None


async def get_case(
    db: AsyncSession, case_id: int, *, lock: bool = False
) -> Optional[AdminCase]:
    """``lock`` = ``SELECT … FOR UPDATE``: kontrola wersji przy „Weź” musi
    czytać wiersz pod blokadą, inaczej dwa równoległe zapisy z tą samą
    wersją przechodzą oba (audyt 22.10, F14)."""

    if not lock:
        return await db.get(AdminCase, case_id)
    return await db.scalar(
        select(AdminCase)
        .where(AdminCase.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


# ── Walidacja wejścia ────────────────────────────────────────────────────────


async def _active_user(db: AsyncSession, user_id: int, label: str) -> User:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise CaseError(f"{label}: nie ma takiego aktywnego konta.")
    return user


async def _validate_links(db: AsyncSession, values: dict[str, Any]) -> None:
    if values.get("assignee_user_id") is not None:
        await _active_user(db, values["assignee_user_id"], "Osoba odpowiedzialna")
    if values.get("subject_user_id") is not None:
        if await db.get(User, values["subject_user_id"]) is None:
            raise CaseError("Osoba: nie ma takiego konta.")
    if values.get("contract_id") is not None:
        if await db.get(Contract, values["contract_id"]) is None:
            raise CaseError("Nie ma takiego kontraktu.")


def _clean_text(value: Optional[str], *, limit: int) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.replace("\x00", "").strip()
    if len(cleaned) > limit:
        raise CaseError(f"Tekst może mieć najwyżej {limit} znaków.")
    return cleaned or None


def _clean_title(value: str) -> str:
    title = " ".join(value.replace("\x00", "").split())
    if len(title) < 3:
        raise CaseError("Tytuł musi mieć co najmniej 3 znaki.")
    if len(title) > rules.TITLE_MAX:
        raise CaseError(f"Tytuł może mieć najwyżej {rules.TITLE_MAX} znaków.")
    return title


def _apply_status(case: AdminCase, status: str) -> None:
    if status not in STATUSES:
        raise CaseError("Nieprawidłowy status sprawy.")
    if rules.is_terminal(status):
        if case.closed_at is None:
            case.closed_at = datetime.now(timezone.utc)
    else:
        case.closed_at = None
    case.status = status


# ── Powiadomienie ────────────────────────────────────────────────────────────


async def notify_assignee(
    db: AsyncSession, case: AdminCase, *, actor_id: Optional[int]
) -> bool:
    """Dzwonek „Przypisano Ci sprawę” (nie do siebie). Porażka nie przerywa zapisu."""

    sent = await notify_each(
        db,
        [case.assignee_user_id],
        exclude=[actor_id],
        title="Przypisano Ci sprawę administracja@",
        message=case.title,
        ntype=NotificationType.admin_case_assigned,
        related_entity_type=ENTITY,
        related_entity_id=case.id,
        link=f"/people/cases/{case.id}",
        log_tag="admin_cases",
    )
    return sent > 0


# ── Zapis ────────────────────────────────────────────────────────────────────


async def create_case(
    db: AsyncSession, *, actor: User, values: dict[str, Any]
) -> AdminCase:
    """Sprawa ręczna („Nowa sprawa”). Termin domyślnie z priorytetu."""

    await _validate_links(db, values)
    priority = values.get("priority") or "P2"
    if priority not in PRIORITIES:
        raise CaseError("Nieprawidłowy priorytet.")
    area = values.get("area") or rules.DEFAULT_AREA
    if area not in AREAS:
        raise CaseError("Nieprawidłowy obszar.")
    try:
        checklist = rules.normalize_checklist(values.get("checklist") or [])
    except rules.ChecklistError as exc:
        raise CaseError(str(exc)) from exc
    case = AdminCase(
        title=_clean_title(values.get("title") or ""),
        area=area,
        priority=priority,
        status="new",
        due_on=values.get("due_on") or rules.due_date_for(priority, local_now()),
        follow_up_on=values.get("follow_up_on"),
        assignee_user_id=values.get("assignee_user_id"),
        checklist=checklist,
        description=_clean_text(values.get("description"), limit=DESCRIPTION_MAX),
        source="manual",
        contract_id=values.get("contract_id"),
        subject_user_id=values.get("subject_user_id"),
        created_by=actor.id,
    )
    db.add(case)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=case.subject_user_id,
        entity_type=ENTITY,
        entity_id=case.id,
        action="case_created",
        details={"area": case.area, "priority": case.priority, "source": "manual"},
    )
    await notify_assignee(db, case, actor_id=actor.id)
    return case


#: Pola, które obsługa zmienia w PATCH (``None`` czyści pole tam, gdzie wolno).
EDITABLE_FIELDS: tuple[str, ...] = (
    "title",
    "area",
    "priority",
    "status",
    "due_on",
    "follow_up_on",
    "assignee_user_id",
    "checklist",
    "description",
    "contract_id",
    "subject_user_id",
)
_NOT_NULL_FIELDS = frozenset({"title", "area", "priority", "status", "checklist"})


def _same_version(current: datetime, expected: datetime) -> bool:
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    return abs((current - expected).total_seconds()) < 0.001


async def update_case(
    db: AsyncSession,
    case: AdminCase,
    *,
    actor: User,
    changes: dict[str, Any],
    expected_updated_at: Optional[datetime] = None,
) -> list[str]:
    """Zmienia pola sprawy; zwraca nazwy zmienionych pól (do śladu i odpowiedzi)."""

    unknown = sorted(set(changes) - set(EDITABLE_FIELDS))
    if unknown:
        raise CaseError(f"Nieznane pola: {', '.join(unknown)}.")
    for field in _NOT_NULL_FIELDS & set(changes):
        if changes[field] is None:
            raise CaseError(
                "Tytuł, obszar, priorytet, status i checklista są wymagane."
            )
    if expected_updated_at is not None and not _same_version(
        case.updated_at, expected_updated_at
    ):
        raise CaseConflict(STALE_DETAIL)
    # Sprawdzamy tylko zmienione powiązania: formularz odsyła wszystkie pola,
    # a osoba przypisana dawniej mogła już odejść.
    await _validate_links(
        db,
        {key: value for key, value in changes.items() if getattr(case, key) != value},
    )

    previous_assignee = case.assignee_user_id
    previous_contract = case.contract_id
    changed: list[str] = []
    for field, value in changes.items():
        if field == "title":
            value = _clean_title(value)
        elif field == "area" and value not in AREAS:
            raise CaseError("Nieprawidłowy obszar.")
        elif field == "priority" and value not in PRIORITIES:
            raise CaseError("Nieprawidłowy priorytet.")
        elif field == "checklist":
            try:
                value = rules.normalize_checklist(value)
            except rules.ChecklistError as exc:
                raise CaseError(str(exc)) from exc
        elif field == "description":
            value = _clean_text(value, limit=DESCRIPTION_MAX)
        if getattr(case, field) == value:
            continue
        if field == "status":
            _apply_status(case, value)
        else:
            setattr(case, field, value)
        changed.append(field)

    if not changed:
        return changed
    case.updated_at = datetime.now(timezone.utc)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=case.subject_user_id,
        entity_type=ENTITY,
        entity_id=case.id,
        action="case_updated",
        details={"fields": changed, "status": case.status},
    )
    if "contract_id" in changed:
        # Ślad przypięcia do kontraktu — oś konsultanta pokazuje go jako
        # „case_linked” (``queries.contract_case_events``).
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=case.subject_user_id,
            entity_type=ENTITY,
            entity_id=case.id,
            action="case_linked" if case.contract_id is not None else "case_unlinked",
            details={
                "contract_id": case.contract_id,
                "previous_contract_id": previous_contract,
                "source": "manual",
            },
        )
    if "assignee_user_id" in changed and case.assignee_user_id != previous_assignee:
        await notify_assignee(db, case, actor_id=actor.id)
    if "checklist" in changed and case.lifecycle_case_id is not None:
        # Sprawa „Wejście konsultanta”: jej checklista to zadania Administracji
        # z listy wejścia (etap 3), więc odhaczenie tutaj odhacza zadanie.
        from app.services.admin_cases.hooks import sync_entry_tasks_from_checklist

        await sync_entry_tasks_from_checklist(db, case, actor_id=actor.id)
    return changed


async def close_case(db: AsyncSession, case: AdminCase, *, actor: User) -> bool:
    if case.status == "closed":
        return False
    _apply_status(case, "closed")
    case.updated_at = datetime.now(timezone.utc)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=case.subject_user_id,
        entity_type=ENTITY,
        entity_id=case.id,
        action="case_closed",
    )
    return True


async def add_comment(
    db: AsyncSession, case: AdminCase, *, actor: User, body: str
) -> AdminCaseComment:
    text_value = (body or "").replace("\x00", "").strip()
    if not text_value:
        raise CaseError("Komentarz nie może być pusty.")
    if len(text_value) > COMMENT_MAX:
        raise CaseError(f"Komentarz może mieć najwyżej {COMMENT_MAX} znaków.")
    comment = AdminCaseComment(
        case_id=case.id, author_user_id=actor.id, body=text_value
    )
    db.add(comment)
    # Sprawa z nowym komentarzem idzie w górę listy (jak w Compassie).
    case.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return comment


@dataclass(frozen=True)
class AutomaticCase:
    """Sprawa zakładana przez automat (mail, kontrakt, odejście, import)."""

    title: str
    area: str
    priority: str
    source: str
    source_key: str
    due_on: Optional[date] = None
    description: Optional[str] = None
    contract_id: Optional[int] = None
    subject_user_id: Optional[int] = None
    lifecycle_case_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    #: Pozycje ``{text, done}`` po ``rules.normalize_checklist``.
    checklist: tuple[dict[str, Any], ...] = ()


async def open_automatic_case(
    db: AsyncSession, spec: AutomaticCase
) -> tuple[AdminCase, bool]:
    """Zakłada sprawę raz na ``source_key``; zwraca ``(sprawa, czy_nowa)``.

    ``ON CONFLICT DO NOTHING`` na unikalnym kluczu — dwa przebiegi automatu
    (albo dwa kontenery naraz) nie założą dwóch spraw.
    """

    statement = (
        insert(AdminCase)
        .values(
            title=spec.title[: rules.TITLE_MAX],
            area=spec.area,
            priority=spec.priority,
            status="new",
            due_on=spec.due_on or rules.due_date_for(spec.priority, local_now()),
            description=spec.description,
            source=spec.source,
            source_key=spec.source_key,
            contract_id=spec.contract_id,
            subject_user_id=spec.subject_user_id,
            lifecycle_case_id=spec.lifecycle_case_id,
            assignee_user_id=spec.assignee_user_id,
            checklist=[dict(item) for item in spec.checklist],
        )
        .on_conflict_do_nothing(index_elements=[AdminCase.source_key])
        .returning(AdminCase.id)
    )
    new_id = await db.scalar(statement)
    if new_id is None:
        existing = await db.scalar(
            select(AdminCase).where(AdminCase.source_key == spec.source_key)
        )
        if existing is None:  # konflikt bez wiersza = sprawę ktoś właśnie skasował
            raise RuntimeError(f"admin case {spec.source_key!r} vanished")
        return existing, False
    case = await db.get(AdminCase, new_id)
    if case is None:
        raise RuntimeError(f"admin case {new_id} vanished after insert")
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=case.subject_user_id,
        entity_type=ENTITY,
        entity_id=case.id,
        action="case_created",
        details={"area": case.area, "priority": case.priority, "source": case.source},
    )
    await notify_assignee(db, case, actor_id=None)
    return case, True
