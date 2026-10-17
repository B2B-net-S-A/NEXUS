"""Wejście konsultanta: jedna lista zadań przy kontrakcie (etap 3, O1, O5, O6).

Konsultant nie ma konta w NEXUSIE, więc sprawa wejścia wisi na kontrakcie
(``lifecycle_cases.contract_id``, ``audience = 'consultant'``, klucz
``contract:{id}:entry``). Lista składa się z trzech źródeł:

* **ścieżka „Konsultant u klienta”** (aktywna ścieżka wejścia konsultanta) —
  pozycje z warunkami formy (z kontraktu), sprzętu („sprzęt od nas” klienta)
  i studenta; zestaw i wydanie sprzętu są tutaj (klucze ``equipment_kit``,
  ``equipment_issue``), a opis zestawu bierze rzeczy „od nas” z pakietu,
* **pakiet klienta** (``client_pack.pack_tasks``) — dokumenty od konsultanta,
  dostępy, odbiór rzeczy od klienta; awaria pakietu nie blokuje wejścia
  (lista powstaje bez niego, a karta „Z czego to powstało” to mówi),
* **forma współpracy** — pozycje ścieżki z warunkiem formy mają źródło „forma”.

Zakłada je hak startu kontraktu (``contract_hooks``) albo przegląd nadchodzących
startów; zmiana daty startu przelicza terminy otwartych zadań. Jedna lista
zamiast trzech (O1): sprawa administracja@ powstaje dalej, ale jej checklista to
zadania „Administracja” tej listy (``admin_cases.hooks``), a zestaw sprzętu to
zadanie recepcji z haka Sprzętu (lustro w ``task_mirrors``). Stare pozycje
``contract_onboarding_items`` zostają tylko do odczytu.

Wykonawcy: opiekun kontraktu (``care.access.effective_owners``; bez niego head
back office), Delivery Lead klienta (DL rekrutacji, a bez niego główny DL
klienta; bez DL — opiekun), pule Kadr, recepcji, IT i administracji. Zadania
„osoby” i „przełożonego” odhacza opiekun (O6). Terminy w dniach roboczych firmy.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask
from app.models.job import Job
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.hr import audit
from app.services.hr.calendar import load_calendar
from app.services.hr.employment_terms import FORM_SHORT_LABELS
from app.services.hr.lifecycle_dates import calendar_window, shift_working_days
from app.services.hr.lifecycle_planning import (
    CaseFacts,
    assignee_of,
    replan_template_tasks,
)
from app.services.hr.lifecycle_templates import pick_template
from app.services.hr.modules import HrModule, load_modules
from app.services.hr_lifecycle_schema import (
    KEY_EQUIPMENT_KIT,
    LIVE_CASE_STATUSES,
    MAX_OFFSET_AFTER,
    MAX_OFFSET_BEFORE,
    TASK_ASSIGNEES,
    TASK_CATEGORIES,
)

logger = logging.getLogger(__name__)

#: Kontrakt, który już nie wystartuje — wejścia nie zakładamy.
_CLOSED = (ContractStatus.void, ContractStatus.ended)
#: Forma z kontraktu → forma ścieżki (``uzlecenie`` to zlecenie).
_FORM_OF_CONTRACT: dict[str, str] = {
    "b2b": "b2b",
    "uop": "uop",
    "uzlecenie": "zlecenie",
}
#: ``clients.equipment_provider`` → warunek sprzętu.
_EQUIPMENT_OF_PROVIDER: dict[str, str] = {"nasz": "ours", "klienta": "client"}
#: Zadania pakietu idą za pozycjami ścieżki (lista i tak sortuje się po terminie).
_PACK_POSITION = 100

#: Dlaczego zakładka „Wejście” nie ma listy.
REASON_PAST_START = "past_start"
REASON_NO_START = "no_start"
REASON_CLOSED = "closed"
REASON_NO_PATH = "no_path"
REASON_MODULE_OFF = "module_off"


def entry_source_key(contract_id: int) -> str:
    return f"contract:{contract_id}:entry"


async def _module_on(db: AsyncSession) -> bool:
    return bool((await load_modules(db)).get(HrModule.lifecycle))


async def contract_entry_case(
    db: AsyncSession, contract_id: int, *, lock: bool = False
) -> Optional[LifecycleCase]:
    """Żywe wejście konsultanta tego kontraktu (``None`` = nie ma)."""

    statement = select(LifecycleCase).where(
        LifecycleCase.contract_id == contract_id,
        LifecycleCase.kind == "onboarding",
        LifecycleCase.audience == "consultant",
        LifecycleCase.status.in_(LIVE_CASE_STATUSES),
    )
    if lock:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def latest_contract_entry(
    db: AsyncSession, contract_id: int
) -> Optional[LifecycleCase]:
    """Wejście kontraktu w dowolnym stanie (żywe przed zamkniętym)."""

    return await db.scalar(
        select(LifecycleCase)
        .where(
            LifecycleCase.contract_id == contract_id,
            LifecycleCase.kind == "onboarding",
            LifecycleCase.audience == "consultant",
        )
        .order_by(
            LifecycleCase.status.in_(LIVE_CASE_STATUSES).desc(), LifecycleCase.id.desc()
        )
        .limit(1)
    )


# ── Kto prowadzi wejście ─────────────────────────────────────────────────────


async def _active(db: AsyncSession, user_id: Optional[int]) -> Optional[User]:
    if user_id is None:
        return None
    user = await db.get(User, user_id)
    return user if user is not None and user.is_active else None


async def _back_office_head(db: AsyncSession) -> Optional[int]:
    from app.services.hr.structure import load_division_heads  # noqa: PLC0415

    head = await _active(db, (await load_division_heads(db)).get("back_office"))
    return head.id if head else None


async def _care_owner(
    db: AsyncSession, contract_id: int
) -> tuple[Optional[int], Optional[str]]:
    """Opiekun kontraktu jedną regułą opieki (kontrakt → klient → DL)."""

    from app.services.care import access as care_access  # noqa: PLC0415

    contracts = await care_access.contracts_by_id(db, [contract_id])
    if contract_id not in contracts:
        return None, None
    choice = (await care_access.effective_owners(db, [contracts[contract_id]]))[
        contract_id
    ]
    return choice.user_id, choice.source


async def _client_delivery_lead(db: AsyncSession, contract: Contract) -> Optional[int]:
    """DL rekrutacji, z której przyszedł konsultant, a bez niego główny DL klienta."""

    if contract.job_id is not None:
        lead = await _active(
            db,
            await db.scalar(
                select(Job.delivery_lead_id).where(Job.id == contract.job_id)
            ),
        )
        if lead is not None and lead.has_role(UserRole.delivery_lead):
            return lead.id
    rows = await db.scalars(
        select(User)
        .join(
            DeliveryLeadClientAssignment,
            DeliveryLeadClientAssignment.delivery_lead_user_id == User.id,
        )
        .where(
            DeliveryLeadClientAssignment.client_id == contract.client_id,
            User.is_active.is_(True),
        )
        .order_by(
            DeliveryLeadClientAssignment.is_head.desc(), DeliveryLeadClientAssignment.id
        )
    )
    for user in rows:
        if user.has_role(UserRole.delivery_lead):
            return user.id
    return None


async def consultant_leads(db: AsyncSession, contract_id: int) -> set[int]:
    """Konta, które prowadzą wejście konsultanta jak przełożony.

    Opiekun kontraktu (jedną regułą opieki), każdy Delivery Lead klienta
    i DL rekrutacji, head back office.
    """

    contract = await db.get(Contract, contract_id)
    if contract is None:
        return set()
    out: set[int] = set()
    owner, _source = await _care_owner(db, contract_id)
    if owner is not None:
        out.add(owner)
    head = await _back_office_head(db)
    if head is not None:
        out.add(head)
    if contract.job_id is not None:
        job_lead = await db.scalar(
            select(Job.delivery_lead_id).where(Job.id == contract.job_id)
        )
        if job_lead is not None:
            out.add(job_lead)
    out.update(
        await db.scalars(
            select(DeliveryLeadClientAssignment.delivery_lead_user_id).where(
                DeliveryLeadClientAssignment.client_id == contract.client_id
            )
        )
    )
    return out


# ── Fakty kontraktu ──────────────────────────────────────────────────────────


async def entry_facts(db: AsyncSession, contract: Contract) -> CaseFacts:
    from app.services.equipment.registry import client_provider  # noqa: PLC0415

    contract_type = contract.contract_type
    form = _FORM_OF_CONTRACT.get(
        contract_type.value
        if isinstance(contract_type, ContractType)
        else str(contract_type or "")
    )
    provider = await client_provider(db, contract.client_id)
    owner, _source = await _care_owner(db, contract.id)
    if owner is None:
        owner = await _back_office_head(db)
    lead = await _client_delivery_lead(db, contract) or owner
    client_name = await db.scalar(
        select(Client.name).where(Client.id == contract.client_id)
    )
    return CaseFacts(
        employment_type=form,
        equipment=_EQUIPMENT_OF_PROVIDER.get(provider or ""),
        # Konsultant nie ma kartoteki — student nieznany (pozycja z dopiskiem).
        student=None,
        client_name=client_name,
        assignees={
            "care_owner": owner,
            "manager": owner,
            "person": owner,
            "delivery_lead": lead,
        },
    )


async def _candidate_name(db: AsyncSession, contract: Contract) -> Optional[str]:
    if contract.candidate_id is None:
        return None
    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname).where(
                Candidate.id == contract.candidate_id
            )
        )
    ).first()
    if row is None:
        return None
    joined = " ".join(part.strip() for part in row if part and part.strip())
    return joined or None


# ── Pakiet klienta ───────────────────────────────────────────────────────────


async def _pack_tasks(db: AsyncSession, client_id: int) -> tuple[list[Any], bool]:
    """Zadania pakietu i czy pakiet dało się przeczytać (awaria ≠ pusty pakiet)."""

    from app.services.hr import client_pack  # noqa: PLC0415

    try:
        async with db.begin_nested():
            return list(await client_pack.pack_tasks(db, client_id)), True
    except Exception:  # noqa: BLE001 — pakiet nie blokuje wejścia
        logger.exception(
            "hr_entry: pakiet klienta %s nie dał się przeczytać", client_id
        )
        return [], False


async def _equipment_ours(db: AsyncSession, client_id: int) -> Optional[str]:
    """„Od nas: laptop, słuchawki.” — opis pozycji zestawu z pakietu."""

    from app.services.hr import client_pack  # noqa: PLC0415

    try:
        async with db.begin_nested():
            pack = await client_pack.load_pack(db, client_id)
    except Exception:  # noqa: BLE001 — opis to dodatek
        logger.exception(
            "hr_entry: pakiet klienta %s (sprzęt) nie dał się przeczytać", client_id
        )
        return None
    names = [item.name for item in getattr(pack, "equipment_ours", ()) if item.name]
    return f"Od nas: {', '.join(names)}." if names else None


def _clamp(offset: int) -> int:
    return max(-MAX_OFFSET_BEFORE, min(MAX_OFFSET_AFTER, int(offset)))


async def _add_pack_tasks(
    db: AsyncSession,
    case: LifecycleCase,
    pack: list[Any],
    facts: CaseFacts,
) -> list[LifecycleTask]:
    if not pack:
        return []
    start, end = calendar_window(case.start_date)
    calendar = await load_calendar(db, start, end)
    added: list[LifecycleTask] = []
    for index, spec in enumerate(pack):
        role = spec.assignee if spec.assignee in TASK_ASSIGNEES else "care_owner"
        offset = _clamp(spec.offset_days)
        task = LifecycleTask(
            case_id=case.id,
            template_item_id=None,
            position=_PACK_POSITION + index,
            title=str(spec.title)[:200],
            category=spec.category if spec.category in TASK_CATEGORIES else "other",
            assignee_kind=role,
            assignee_user_id=assignee_of(facts, role),
            due_date=shift_working_days(calendar, case.start_date, offset),
            description=(spec.description or None) and str(spec.description)[:500],
            required=bool(spec.required),
            requires_file=bool(spec.requires_file),
            source="client",
            source_label=(facts.client_name or "")[:160] or None,
            due_offset_days=offset,
        )
        db.add(task)
        added.append(task)
    await db.flush()
    return added


async def _describe_kit(db: AsyncSession, case: LifecycleCase, client_id: int) -> None:
    ours = await _equipment_ours(db, client_id)
    if not ours:
        return
    kit = await db.scalar(
        select(LifecycleTask).where(
            LifecycleTask.case_id == case.id,
            LifecycleTask.key == KEY_EQUIPMENT_KIT,
            LifecycleTask.status == "open",
        )
    )
    if kit is not None:
        kit.description = ours[:500]


async def _redate_pack_tasks(db: AsyncSession, case: LifecycleCase) -> None:
    """Nowa data startu: otwarte zadania pakietu i ręczne z przesunięciem."""

    tasks = list(
        await db.scalars(
            select(LifecycleTask).where(
                LifecycleTask.case_id == case.id,
                LifecycleTask.template_item_id.is_(None),
                LifecycleTask.status == "open",
                LifecycleTask.due_offset_days.is_not(None),
            )
        )
    )
    if not tasks:
        return
    start, end = calendar_window(case.start_date)
    calendar = await load_calendar(db, start, end)
    for task in tasks:
        task.due_date = shift_working_days(
            calendar, case.start_date, task.due_offset_days
        )


# ── Zakładanie i życie wejścia ───────────────────────────────────────────────


def _closed(contract: Contract) -> bool:
    return contract.status in _CLOSED or contract.voided_at is not None


async def ensure_contract_entry(
    db: AsyncSession,
    contract: Contract,
    *,
    force: bool = False,
    actor_id: Optional[int] = None,
) -> Optional[LifecycleCase]:
    """Wejście konsultanta tego kontraktu — założone raz, potem aktualne terminy.

    Idempotentne (klucz ``contract:{id}:entry``, ``ON CONFLICT DO NOTHING``):
    drugi przebieg nie dubluje sprawy ani zadań; zmieniona data startu
    przelicza terminy otwartych zadań. Wyłączony moduł, kontrakt bez startu,
    zamknięty albo (bez ``force``) ze startem w przeszłości = ``None``.
    Sprawa zamknięta albo anulowana nie wraca.
    """

    if not await _module_on(db) or contract.start_date is None or _closed(contract):
        return None
    existing = await db.scalar(
        select(LifecycleCase)
        .where(LifecycleCase.source_key == entry_source_key(contract.id))
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.status in LIVE_CASE_STATUSES
            and existing.start_date != contract.start_date
        ):
            await refresh_entry(db, existing, contract)
        return existing if existing.status in LIVE_CASE_STATUSES else None
    if not force and contract.start_date < business_today():
        return None
    template = await pick_template(db, "onboarding", audience="consultant")
    pack, _pack_ok = await _pack_tasks(db, contract.client_id)
    if template is None and not pack:
        return None
    facts = await entry_facts(db, contract)
    now = local_now()
    case_id = await db.scalar(
        pg_insert(LifecycleCase)
        .values(
            user_id=None,
            pending_name=(
                await _candidate_name(db, contract) or f"kontrakt #{contract.id}"
            )[:255],
            kind="onboarding",
            status="active",
            audience="consultant",
            contract_id=contract.id,
            template_id=template.id if template else None,
            template_version=template.version if template else None,
            start_date=contract.start_date,
            owner_user_id=facts.assignees.get("care_owner")
            if facts.assignees
            else None,
            profile_values={},
            started_at=now,
            source_key=entry_source_key(contract.id),
            created_by=actor_id,
        )
        .on_conflict_do_nothing(index_elements=[LifecycleCase.source_key])
        .returning(LifecycleCase.id)
    )
    if case_id is None:  # równoległy przebieg właśnie założył
        return await contract_entry_case(db, contract.id)
    case = await db.get(LifecycleCase, case_id)
    assert case is not None
    await replan_template_tasks(db, case, facts)
    await _add_pack_tasks(db, case, pack, facts)
    await _describe_kit(db, case, contract.client_id)
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="lifecycle_case",
        entity_id=case.id,
        action="consultant_onboarding_created",
        details={
            "contract_id": contract.id,
            "template_version": case.template_version,
            "pack_tasks": len(pack),
        },
    )
    await db.flush()
    from app.services.hr.lifecycle_service import case_tasks, notify_assignees  # noqa: PLC0415

    await notify_assignees(db, case, await case_tasks(db, case.id), actor_id=actor_id)
    return case


async def refresh_entry(
    db: AsyncSession, case: LifecycleCase, contract: Contract
) -> LifecycleCase:
    """Zmiana daty startu kontraktu: terminy otwartych zadań od nowej daty."""

    previous = case.start_date
    case.start_date = contract.start_date
    facts = await entry_facts(db, contract)
    await replan_template_tasks(db, case, facts)
    await _redate_pack_tasks(db, case)
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=None,
        entity_type="lifecycle_case",
        entity_id=case.id,
        action="case_updated",
        details={
            "fields": ["start_date"],
            "source": "contract",
            "previous": previous.isoformat() if previous else None,
        },
    )
    await db.flush()
    return case


async def cancel_contract_entry(
    db: AsyncSession, contract_id: int, *, reason: str
) -> Optional[LifecycleCase]:
    """Kontrakt unieważniony — wejścia nie będzie (zrobione zostaje w historii)."""

    case = await contract_entry_case(db, contract_id, lock=True)
    if case is None:
        return None
    case.status = "cancelled"
    case.cancelled_at = local_now()
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=None,
        entity_type="lifecycle_case",
        entity_id=case.id,
        action="onboarding_cancelled",
        details={"source": "contract", "reason": reason, "contract_id": contract_id},
    )
    await db.flush()
    return case


async def delete_contract_entry(db: AsyncSession, contract_id: int) -> int:
    """Trwałe usunięcie kontraktu: jego wejście znika razem z nim (bez FK).

    Zadania idą kaskadą; sprawa administracja@ zamyka się osobnym hakiem.
    """

    ids = list(
        await db.scalars(
            select(LifecycleCase.id).where(
                LifecycleCase.contract_id == contract_id,
                LifecycleCase.audience == "consultant",
            )
        )
    )
    if not ids:
        return 0
    await db.execute(delete(LifecycleCase).where(LifecycleCase.id.in_(ids)))
    for case_id in ids:
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=None,
            entity_type="lifecycle_case",
            entity_id=case_id,
            action="consultant_onboarding_deleted",
            details={"contract_id": contract_id},
        )
    await db.flush()
    return len(ids)


async def merge_contract_entries(
    db: AsyncSession, loser_ids: list[int], survivor_id: int
) -> dict[str, int]:
    """Scalenie duplikatu kontraktu: wejścia przegranych idą za zachowanym.

    Żywa sprawa (szkic, w toku) jest jedna na kontrakt — zostaje sprawa
    zachowanego, a bez niej najstarsza z przegranych (dostaje klucz
    zachowanego, jeśli ten go nie ma); pozostałe żywe są anulowane ze śladem
    w audycie. Zakończone i anulowane przechodzą jako historia. Bez FK, więc
    scalenie woła to samo, zanim skasuje przegrane kontrakty.
    """

    if not loser_ids:
        return {"moved": 0, "cancelled": 0}
    rows = list(
        await db.scalars(
            select(LifecycleCase)
            .where(
                LifecycleCase.contract_id.in_([*loser_ids, survivor_id]),
                LifecycleCase.audience == "consultant",
            )
            .order_by(LifecycleCase.id)
            .with_for_update()
        )
    )
    live = sorted(
        (case for case in rows if case.status in LIVE_CASE_STATUSES),
        key=lambda case: (case.contract_id != survivor_id, case.id),
    )
    kept: dict[str, LifecycleCase] = {}
    cancelled = 0
    now = local_now()
    for case in live:
        if case.kind not in kept:
            kept[case.kind] = case
            continue
        case.status = "cancelled"
        case.cancelled_at = now
        cancelled += 1
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=None,
            entity_type="lifecycle_case",
            entity_id=case.id,
            action="consultant_onboarding_cancelled_on_merge",
            details={"contract_id": case.contract_id, "survivor_id": survivor_id},
        )
    survivor_key = entry_source_key(survivor_id)
    key_taken = any(case.source_key == survivor_key for case in rows)
    moved = 0
    for case in rows:
        if case.contract_id == survivor_id:
            continue
        case.contract_id = survivor_id
        moved += 1
        if not key_taken and kept.get(case.kind) is case:
            case.source_key = survivor_key
            key_taken = True
    await db.flush()
    return {"moved": moved, "cancelled": cancelled}


async def complete_task_by_key(
    db: AsyncSession, *, contract_id: int, key: str, actor_id: int
) -> bool:
    """Odhacza otwarte zadanie o kluczu ``key`` w wejściu tego kontraktu.

    Dla modułów obok (mail powitalny odhacza ``welcome_mail`` przy wysyłce).
    ``False`` bez wyjątku, gdy nie ma żywej sprawy, pozycji albo zadanie jest
    już zamknięte. Nie commituje — robi to wołający razem ze swoją zmianą.
    Ślad w audycie jak przy zwykłym odhaczeniu (``task_updated``).
    """

    case = await contract_entry_case(db, contract_id)
    if case is None:
        return False
    task = await db.scalar(
        select(LifecycleTask)
        .where(
            LifecycleTask.case_id == case.id,
            LifecycleTask.key == key,
            LifecycleTask.status == "open",
        )
        .order_by(LifecycleTask.id)
        .limit(1)
        .with_for_update()
    )
    if task is None:
        return False
    task.status = "done"
    task.done_at = local_now()
    task.done_by = actor_id
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=case.user_id,
        entity_type="lifecycle_task",
        entity_id=task.id,
        action="task_updated",
        details={"fields": ["status"], "status": "done", "key": key},
    )
    await db.flush()
    return True


# ── Odczyt zakładki „Wejście” ────────────────────────────────────────────────


async def composition(db: AsyncSession, contract: Contract) -> dict[str, Any]:
    """Karta „Z czego to powstało”: ścieżka, pakiet, forma, opiekun, menedżer."""

    from app.services.equipment.registry import client_provider  # noqa: PLC0415

    owner_id, owner_source = await _care_owner(db, contract.id)
    lead_id = await _client_delivery_lead(db, contract)
    names: dict[int, str] = {}
    ids = [user_id for user_id in (owner_id, lead_id) if user_id is not None]
    if ids:
        names = dict(
            (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
        )
    manager_name = contract.client_pm_name
    if contract.client_pm_contact_id is not None:
        manager_name = (
            await db.scalar(
                select(Contact.name).where(Contact.id == contract.client_pm_contact_id)
            )
            or manager_name
        )
    contract_type = contract.contract_type
    form = _FORM_OF_CONTRACT.get(
        contract_type.value
        if isinstance(contract_type, ContractType)
        else str(contract_type or "")
    )
    provider = await client_provider(db, contract.client_id)
    return {
        "client_id": contract.client_id,
        "client_name": await db.scalar(
            select(Client.name).where(Client.id == contract.client_id)
        ),
        "employment_type": form,
        "employment_label": FORM_SHORT_LABELS.get(form or ""),
        "equipment": _EQUIPMENT_OF_PROVIDER.get(provider or ""),
        "care_owner": {
            "id": owner_id,
            "name": names.get(owner_id),
            "source": owner_source,
        }
        if owner_id
        else None,
        "delivery_lead": {"id": lead_id, "name": names.get(lead_id)}
        if lead_id
        else None,
        "client_manager": manager_name,
    }


def missing_reason(contract: Contract, today: date) -> str:
    if contract.start_date is None:
        return REASON_NO_START
    if _closed(contract):
        return REASON_CLOSED
    if contract.start_date < today:
        return REASON_PAST_START
    return REASON_NO_PATH


__all__ = [
    "REASON_CLOSED",
    "REASON_MODULE_OFF",
    "REASON_NO_PATH",
    "REASON_NO_START",
    "REASON_PAST_START",
    "cancel_contract_entry",
    "complete_task_by_key",
    "composition",
    "consultant_leads",
    "contract_entry_case",
    "delete_contract_entry",
    "ensure_contract_entry",
    "entry_facts",
    "entry_source_key",
    "latest_contract_entry",
    "merge_contract_entries",
    "missing_reason",
    "refresh_entry",
]
