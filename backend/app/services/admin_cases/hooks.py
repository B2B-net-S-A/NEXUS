"""Haki spraw administracja@ dla innych modułów (wpina je koordynator).

* ``open_case_for_new_contract`` — nowy kontrakt konsultanta zakłada sprawę
  „Wejście konsultanta: …” (obszar onboarding). W Compassie to samo robił
  import placementu, a sprawa miała konsultanta tylko jako pole tekstowe —
  tu jest spięta z kontraktem. Od etapu 3 (O1, 17.10.2026) sprawa jest częścią
  jednej listy wejścia: ``lifecycle_case_id`` wskazuje wejście konsultanta,
  a checklista to jego zadania „Administracja” (``sync_entry_checklist``
  w obie strony z ``sync_entry_tasks_from_checklist``); scalenie duplikatów
  kontraktu przepina sprawę na zachowane wejście (``relink_merged_entry``).
* ``open_case_for_offboarding`` — odejście pracownika (moduł cyklu życia)
  zakłada sprawę „Odejście: …” (obszar offboarding), jak w Compassie
  ``inbox_offboarding`` przy starcie offboardingu.
* ``open_case_for_contract_end`` — „Zakończ współpracę” konsultanta (okno
  kontraktu i masowe „Oznacz zakończone”, hak ``contract_hooks.contract_ended``)
  zakłada sprawę „Koniec współpracy: <osoba> · <klient>” (obszar offboarding,
  decyzja 7 z 22.10.2026). Prowadzi efektywny opiekun kontraktu (łańcuch
  opieki), termin = ostatni dzień, checklista z pakietu klienta i stanu opieki
  (``rules.end_of_cooperation_checklist``). „Cofnij zakończenie” i ponowne
  otwarcie kontraktu zamykają ją (``close_case_for_undone_end``); kolejne
  zakończenie otwiera sprawę zamkniętą przez automat jeszcze raz.

Oba są idempotentne po ``source_key`` (powtórne wywołanie oddaje tę samą
sprawę) i nie commitują — robi to wołający razem ze swoją zmianą. Przy
wyłączonym module „cases” nic nie zakładają i zwracają ``None``: do
przełączenia sprawy prowadzi Compass, a ciemna tablica zbierałaby duplikaty.

Gdy powód sprawy znika, automat ją zamyka (``close_automatic_case``, też po
``source_key``, z notatką obsługi): „Cofnij odejście”
(``close_case_for_cancelled_offboarding``), unieważniony kontrakt
(``close_case_for_voided_contract``) i kontrakt usunięty trwale
(``close_case_for_deleted_contract``). Sprawa już zamknięta albo zrobiona
zostaje, jak jest.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.admin_case import AdminCase, AdminCaseComment
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.admin_cases import rules
from app.services.admin_cases.queries import CANDIDATE_FULL_NAME
from app.services.admin_cases.service import (
    ENTITY,
    AutomaticCase,
    module_enabled,
    open_automatic_case,
)
from app.services.hr import audit

logger = logging.getLogger(__name__)


def contract_source_key(contract_id: int) -> str:
    return f"contract:{contract_id}:start"


def contract_end_source_key(contract_id: int) -> str:
    return f"contract:{contract_id}:end"


def offboarding_source_key(user_id: int, lifecycle_case_id: Optional[int]) -> str:
    if lifecycle_case_id is not None:
        return f"lifecycle:{lifecycle_case_id}:offboarding"
    return f"lifecycle:user:{user_id}:offboarding"


async def open_case_for_new_contract(
    db: AsyncSession, contract: Contract
) -> Optional[AdminCase]:
    """Sprawa wejścia konsultanta; termin = dzień startu, gdy jest przed nami."""

    if not await module_enabled(db):
        return None

    candidate_name = None
    if contract.candidate_id is not None:
        candidate_name = await db.scalar(
            select(CANDIDATE_FULL_NAME).where(Candidate.id == contract.candidate_id)
        )
    client_name = await db.scalar(
        select(Client.name).where(Client.id == contract.client_id)
    )
    who = candidate_name or f"kontrakt #{contract.id}"
    title = f"Wejście konsultanta: {who}"
    if client_name:
        title = f"{title} · {client_name}"
    start = contract.start_date
    entry = await _entry_of_contract(db, contract.id)
    case, _created = await open_automatic_case(
        db,
        AutomaticCase(
            title=title,
            area="onboarding",
            priority="P2",
            source="contract",
            source_key=contract_source_key(contract.id),
            due_on=start if start is not None and start >= business_today() else None,
            description=(
                f"Start u klienta {start.strftime('%d.%m.%Y')}." if start else None
            ),
            contract_id=contract.id,
            lifecycle_case_id=entry.id if entry is not None else None,
        ),
    )
    if entry is not None:
        await _link_entry(db, case, entry)
    return case


# ── Jedna lista wejścia konsultanta (etap 3, O1) ─────────────────────────────


async def _entry_of_contract(
    db: AsyncSession, contract_id: int
) -> Optional[LifecycleCase]:
    return await db.scalar(
        select(LifecycleCase).where(
            LifecycleCase.contract_id == contract_id,
            LifecycleCase.kind == "onboarding",
            LifecycleCase.audience == "consultant",
            LifecycleCase.status.in_(("draft", "active")),
        )
    )


async def _admin_tasks(db: AsyncSession, entry_id: int) -> list[LifecycleTask]:
    return list(
        await db.scalars(
            select(LifecycleTask)
            .where(
                LifecycleTask.case_id == entry_id,
                LifecycleTask.assignee_kind == "administration",
            )
            .order_by(LifecycleTask.due_date.asc().nulls_last(), LifecycleTask.id)
        )
    )


def _text_key(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def _merged_checklist(
    current: list[dict[str, Any]], tasks: list[LifecycleTask]
) -> list[dict[str, Any]]:
    """Checklista = zadania „Administracja” wejścia + pozycje dopisane ręcznie.

    Pozycja o tytule zadania bierze jego stan; zadania, których nie ma na
    liście, dochodzą na koniec; pozycje dopisane w Sprawach ręcznie zostają.
    """

    by_text = {_text_key(task.title): task for task in tasks}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in current or []:
        key = _text_key(item.get("text") or "")
        task = by_text.get(key)
        if task is not None:
            seen.add(key)
            out.append({"text": item.get("text"), "done": task.status != "open"})
        else:
            out.append({"text": item.get("text"), "done": item.get("done") is True})
    for key, task in by_text.items():
        if key not in seen:
            out.append(
                {
                    "text": task.title[: rules.CHECKLIST_TEXT_MAX],
                    "done": task.status != "open",
                }
            )
    return out[: rules.CHECKLIST_MAX_ITEMS]


async def _link_entry(db: AsyncSession, case: AdminCase, entry: LifecycleCase) -> None:
    if rules.is_terminal(case.status):
        return
    case.lifecycle_case_id = case.lifecycle_case_id or entry.id
    merged = _merged_checklist(case.checklist or [], await _admin_tasks(db, entry.id))
    if merged != (case.checklist or []):
        case.checklist = merged
    await db.flush()


async def sync_entry_checklist(
    db: AsyncSession, entry: LifecycleCase
) -> Optional[AdminCase]:
    """Zadanie „Administracja” odhaczone na liście wejścia → checklista sprawy."""

    if entry.audience != "consultant" or entry.contract_id is None:
        return None
    case = await db.scalar(
        select(AdminCase)
        .where(AdminCase.source_key == contract_source_key(entry.contract_id))
        .with_for_update()
    )
    if case is None:
        return None
    await _link_entry(db, case, entry)
    return case


async def relink_merged_entry(
    db: AsyncSession, cancelled_id: int, kept: LifecycleCase
) -> int:
    """Scalenie duplikatu kontraktu: sprawy wskazujące anulowane wejście → zachowane.

    Bez tego odhaczenie pozycji w Sprawach szło do anulowanej listy, a lista
    zachowanego kontraktu nie wiedziała o sprawie. Checklista otwartej sprawy
    bierze stan zadań „Administracja” zachowanej listy; zwraca liczbę spraw.
    """

    cases = list(
        await db.scalars(
            select(AdminCase)
            .where(AdminCase.lifecycle_case_id == cancelled_id)
            .with_for_update()
        )
    )
    for case in cases:
        case.lifecycle_case_id = kept.id
        await _link_entry(db, case, kept)
    await db.flush()
    return len(cases)


async def sync_entry_tasks_from_checklist(
    db: AsyncSession, case: AdminCase, *, actor_id: Optional[int]
) -> int:
    """Pozycja checklisty odhaczona w Sprawach → zadanie wejścia (ta sama rzecz).

    Do wywołania po zapisie checklisty sprawy z ``lifecycle_case_id``; zwraca
    liczbę zmienionych zadań. Ślad ``task_updated`` jak przy odhaczeniu na liście.
    """

    if case.lifecycle_case_id is None:
        return 0
    from app.core.scheduling import local_now  # noqa: PLC0415

    done = {
        _text_key(item.get("text") or ""): item.get("done") is True
        for item in case.checklist or []
    }
    changed = 0
    for task in await _admin_tasks(db, case.lifecycle_case_id):
        want = done.get(_text_key(task.title))
        if want is None or want == (task.status != "open"):
            continue
        task.status = "done" if want else "open"
        task.done_at = local_now() if want else None
        task.done_by = actor_id if want else None
        audit.record(
            db,
            actor_user_id=actor_id,
            subject_user_id=None,
            entity_type="lifecycle_task",
            entity_id=task.id,
            action="task_updated",
            details={"fields": ["status"], "status": task.status, "source": ENTITY},
        )
        changed += 1
    await db.flush()
    return changed


async def open_case_for_offboarding(
    db: AsyncSession, user_id: int, lifecycle_case_id: Optional[int]
) -> Optional[AdminCase]:
    """Sprawa odejścia pracownika; termin = ostatni dzień pracy z kartoteki."""

    if not await module_enabled(db):
        return None

    name = await db.scalar(select(User.name).where(User.id == user_id))
    last_day = await db.scalar(
        select(EmployeeProfile.last_working_day).where(
            EmployeeProfile.user_id == user_id
        )
    )
    case, _created = await open_automatic_case(
        db,
        AutomaticCase(
            title=f"Odejście: {name or f'konto #{user_id}'}",
            area="offboarding",
            priority="P2",
            source="lifecycle",
            source_key=offboarding_source_key(user_id, lifecycle_case_id),
            due_on=(
                last_day
                if last_day is not None and last_day >= business_today()
                else None
            ),
            description=(
                f"Ostatni dzień współpracy {last_day.strftime('%d.%m.%Y')}."
                if last_day
                else None
            ),
            subject_user_id=user_id,
            lifecycle_case_id=lifecycle_case_id,
        ),
    )
    return case


async def close_automatic_case(
    db: AsyncSession, source_key: str, *, note: str
) -> Optional[AdminCase]:
    """Zamyka sprawę automatu, której powód zniknął; zwraca ją (``None`` = nic).

    Notatka obsługi mówi, dlaczego sprawa zniknęła z tablicy — osoba, która ją
    prowadziła, nie szuka jej po omacku.
    """

    case = await db.scalar(
        select(AdminCase).where(AdminCase.source_key == source_key).with_for_update()
    )
    if case is None or rules.is_terminal(case.status):
        return None
    now = datetime.now(timezone.utc)
    case.status = "closed"
    case.closed_at = now
    case.updated_at = now
    db.add(AdminCaseComment(case_id=case.id, author_user_id=None, body=note))
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=case.subject_user_id,
        entity_type=ENTITY,
        entity_id=case.id,
        action="case_closed",
        details={"source": "automation", "source_key": source_key},
    )
    await db.flush()
    return case


async def close_case_for_cancelled_offboarding(
    db: AsyncSession, user_id: int, lifecycle_case_id: Optional[int]
) -> Optional[AdminCase]:
    """„Cofnij odejście” — sprawa „Odejście: …” nie ma już powodu."""

    return await close_automatic_case(
        db,
        offboarding_source_key(user_id, lifecycle_case_id),
        note="Odejście cofnięte w NEXUSIE — sprawa zamknięta automatycznie.",
    )


async def close_case_for_voided_contract(
    db: AsyncSession, contract_id: int
) -> Optional[AdminCase]:
    """Kontrakt unieważniony — wejścia konsultanta nie będzie."""

    return await close_automatic_case(
        db,
        contract_source_key(contract_id),
        note="Kontrakt unieważniony — sprawa zamknięta automatycznie.",
    )


async def close_case_for_deleted_contract(
    db: AsyncSession, contract_id: int
) -> Optional[AdminCase]:
    """Kontrakt trwale usunięty — FK zeruje ``contract_id``, a sprawa zostałaby
    otwarta bez kontraktu. Zamykamy ją przed usunięciem."""

    return await close_automatic_case(
        db,
        contract_source_key(contract_id),
        note="Kontrakt usunięty z NEXUSA — sprawa zamknięta automatycznie.",
    )


# ── Koniec współpracy konsultanta (decyzja 7, 22.10.2026) ────────────────────

#: Opinia menedżera z tylu ostatnich dni odhacza pozycję checklisty.
END_FEEDBACK_RECENT_DAYS = 30
#: Decyzja „Do przepięcia” z tylu ostatnich dni odhacza pozycję checklisty.
END_DECISION_RECENT_DAYS = 90


async def _end_checklist(db: AsyncSession, contract: Contract) -> list[dict[str, Any]]:
    """Checklista z pakietu klienta (sprzęt, dostępy) i stanu opieki."""

    from datetime import timedelta

    from app.models.contract_care import (
        ClientFeedbackScore,
        ClientFeedbackSession,
        RedeployQueueItem,
    )
    from app.services.equipment.errors import EquipmentNotFound
    from app.services.hr import client_pack

    try:
        pack = await client_pack.load_pack(db, contract.client_id)
    except EquipmentNotFound:
        pack = None
    today = business_today()
    feedback_done = (
        await db.scalar(
            select(ClientFeedbackScore.id)
            .join(
                ClientFeedbackSession,
                ClientFeedbackSession.id == ClientFeedbackScore.session_id,
            )
            .where(
                ClientFeedbackScore.contract_id == contract.id,
                ClientFeedbackSession.held_on
                >= today - timedelta(days=END_FEEDBACK_RECENT_DAYS),
            )
            .limit(1)
        )
        is not None
    )
    decision_done = (
        await db.scalar(
            select(RedeployQueueItem.id)
            .where(
                RedeployQueueItem.contract_id == contract.id,
                RedeployQueueItem.status.in_(("in_progress", "done", "dismissed")),
                RedeployQueueItem.updated_at
                >= datetime.now(timezone.utc)
                - timedelta(days=END_DECISION_RECENT_DAYS),
            )
            .limit(1)
        )
        is not None
    )
    return rules.end_of_cooperation_checklist(
        equipment_ours=pack is not None and pack.equipment_provider == "nasz",
        accesses=[item.name for item in pack.accesses] if pack is not None else [],
        feedback_done=feedback_done,
        decision_done=decision_done,
    )


async def _care_owner_id(db: AsyncSession, contract_id: int) -> Optional[int]:
    """Efektywny opiekun kontraktu (pole kontraktu → klient → DL).

    Awaria modułu opieki = sprawa bez osoby (obsługa ją weźmie), nie brak sprawy.
    """

    from app.services.care import access as care_access

    try:
        async with db.begin_nested():
            contracts = await care_access.contracts_by_id(db, [contract_id])
            if contract_id not in contracts:
                return None
            owners = await care_access.effective_owners(db, list(contracts.values()))
    except Exception:  # noqa: BLE001 — opiekun to dodatek do sprawy
        logger.exception(
            "[admin_cases] opiekun kontraktu %s nie policzony", contract_id
        )
        return None
    return owners[contract_id].user_id


async def _closed_by_automation(db: AsyncSession, case_id: int) -> bool:
    """Ostatnia zmiana sprawy to zamknięcie przez automat (nie przez człowieka).

    Człowiek zamyka przyciskiem (``case_closed`` z autorem) albo zmianą
    statusu (``case_updated``) — takiej sprawy automat nie otwiera.
    """

    from app.models.hr_ops import HrAuditEvent

    latest = (
        await db.execute(
            select(HrAuditEvent.action, HrAuditEvent.actor_user_id)
            .where(
                HrAuditEvent.entity_type == ENTITY,
                HrAuditEvent.entity_id == str(case_id),
                HrAuditEvent.action.in_(
                    ("case_closed", "case_updated", "case_reopened")
                ),
            )
            .order_by(HrAuditEvent.created_at.desc(), HrAuditEvent.id.desc())
            .limit(1)
        )
    ).first()
    return latest is not None and latest[0] == "case_closed" and latest[1] is None


async def open_case_for_contract_end(
    db: AsyncSession, contract: Contract
) -> Optional[AdminCase]:
    """Sprawa „Koniec współpracy” po zapisaniu zakończenia kontraktu.

    Idempotentnie po ``contract:<id>:end``: powtórne wywołanie oddaje tę samą
    sprawę i przesuwa termin otwartej sprawy na nowy ostatni dzień. Sprawa
    zamknięta przez automat (cofnięte zakończenie) wraca jako „Nowa”; zrobiona
    albo zamknięta przez człowieka zostaje, jak jest.
    """

    if not await module_enabled(db):
        return None
    if contract.status == ContractStatus.void:
        return None

    candidate_name = None
    if contract.candidate_id is not None:
        candidate_name = await db.scalar(
            select(CANDIDATE_FULL_NAME).where(Candidate.id == contract.candidate_id)
        )
    client_name = await db.scalar(
        select(Client.name).where(Client.id == contract.client_id)
    )
    who = candidate_name or f"kontrakt #{contract.id}"
    title = f"Koniec współpracy: {who}"
    if client_name:
        title = f"{title} · {client_name}"
    last_day = contract.end_date or contract.terminated_at
    due_on = last_day if last_day is not None and last_day >= business_today() else None
    description = (
        f"Ostatni dzień współpracy {last_day.strftime('%d.%m.%Y')}."
        if last_day
        else None
    )
    owner_id = await _care_owner_id(db, contract.id)
    case, created = await open_automatic_case(
        db,
        AutomaticCase(
            title=title,
            area="offboarding",
            priority="P2",
            source="contract",
            source_key=contract_end_source_key(contract.id),
            due_on=due_on,
            description=description,
            contract_id=contract.id,
            assignee_user_id=owner_id,
            checklist=tuple(await _end_checklist(db, contract)),
        ),
    )
    if created:
        return case
    if case.status == "closed" and await _closed_by_automation(db, case.id):
        now = datetime.now(timezone.utc)
        case.status = "new"
        case.closed_at = None
        case.updated_at = now
        case.due_on = due_on or rules.due_date_for(case.priority, local_now())
        case.description = description or case.description
        if case.assignee_user_id is None:
            case.assignee_user_id = owner_id
        db.add(
            AdminCaseComment(
                case_id=case.id,
                author_user_id=None,
                body="Zakończenie współpracy zapisane ponownie — sprawa otwarta.",
            )
        )
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=case.subject_user_id,
            entity_type=ENTITY,
            entity_id=case.id,
            action="case_reopened",
            details={"source": "automation", "source_key": case.source_key},
        )
        await db.flush()
    elif not rules.is_terminal(case.status) and due_on and case.due_on != due_on:
        case.due_on = due_on
        case.description = description
        case.updated_at = datetime.now(timezone.utc)
        await db.flush()
    return case


async def close_case_for_undone_end(
    db: AsyncSession, contract_id: int
) -> Optional[AdminCase]:
    """„Cofnij zakończenie” albo ponowne otwarcie kontraktu — końca nie będzie."""

    return await close_automatic_case(
        db,
        contract_end_source_key(contract_id),
        note="Zakończenie współpracy cofnięte — sprawa zamknięta automatycznie.",
    )
