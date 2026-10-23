"""„Do zrobienia” recepcji i przypomnienia (pętla ``equipment_reminders``).

Zadania zakłada NEXUS, nie człowiek z pamięci: start kontraktu u klienta,
który bierze sprzęt od nas (7 dni roboczych wcześniej, D7), koniec współpracy,
wejście i odejście pracownika, niepodpisany protokół. ``source_key`` jest
unikalny — wołanie tej samej funkcji drugi raz niczego nie dubluje, a zadanie
otwarte dostaje tylko nowy termin, gdy data startu albo końca się przesunęła.

Gdy powód zadania znika („Cofnij odejście”, anulowane wejście, unieważniony
kontrakt), automat je anuluje (``cancel_*``, znacznik ``auto_cancelled``
w ``details``); to samo zdarzenie powtórzone później (nowe odejście tej osoby)
otwiera je z powrotem. Zadania anulowanego przez recepcję automat nie otwiera.

Funkcje ``tasks_for_*`` wpina koordynator w pętle kontraktów i cyklu życia;
``run_once`` to jeden przebieg dziennych przypomnień (rezerwacja w
``hr_job_runs``, więc restart po nocnym wdrożeniu nie wysyła drugi raz).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, business_today, local_now
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.contract_equipment import (
    ContractEquipment,
    EquipmentOwner,
    EquipmentReturnStatus,
)
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentExternalPerson,
    EquipmentItem,
    EquipmentProtocol,
    EquipmentProtocolLine,
    EquipmentProtocolLink,
    EquipmentTask,
)
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.equipment.errors import EquipmentConflict, EquipmentNotFound
from app.services.equipment.holders import (
    AcademyCandidate,
    candidate_name,
    holder_of,
    resolve_holder,
)
from app.services.equipment.queries import join_academy_holder
from app.services.equipment.registry import client_provider
from app.services.hr import job_runs
from app.services.hr.calendar import load_calendar
from app.services.hr.lifecycle_dates import shift_working_days
from app.services.hr.notify import notify_each

#: Ile dni roboczych przed startem kontraktu recepcja przygotowuje zestaw (D7).
CONTRACT_START_LEAD_WORKDAYS = 7
#: Termin podpisu protokołu (dni kalendarzowe od wydania).
SIGNATURE_DUE_DAYS = 3
#: Przypomnienie obejmuje zadania z terminem do tylu dni naprzód.
REMIND_AHEAD_DAYS = 2
REMINDER_JOB = "equipment_reminders"
#: Dzwonek recepcji nie wychodzi w nocy (pętla budzi się częściej niż raz dziennie).
REMIND_FROM_HOUR = 7

_CLOSED_CONTRACT = (ContractStatus.void, ContractStatus.ended)
#: Znacznik w ``details``: zadanie anulował automat (powód zniknął).
AUTO_CANCELLED = "auto_cancelled"


async def workdays_before(db: AsyncSession, day: date, count: int) -> date:
    """``count`` dni roboczych przed ``day`` — kalendarz firmy jak w urlopach
    (święta ustawowe i dni wolne firmy)."""
    calendar = await load_calendar(db, day - timedelta(days=count * 3 + 14), day)
    return shift_working_days(calendar, day, -count)


async def upsert_task(
    db: AsyncSession,
    *,
    kind: str,
    source_key: str,
    title: str,
    due_on: Optional[date],
    contract_id: Optional[int] = None,
    user_id: Optional[int] = None,
    external_person_id: Optional[int] = None,
    academy_application_id: Optional[int] = None,
    protocol_id: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
) -> EquipmentTask:
    """Zadanie po ``source_key``: nowe raz, otwarte dostaje nowy termin i tytuł.

    Zadanie anulowane przez automat (powód zniknął, a teraz wrócił) otwiera
    się z powrotem; zrobione i anulowane przez człowieka zostają.
    """
    statement = (
        insert(EquipmentTask)
        .values(
            kind=kind,
            source_key=source_key,
            title=title[:300],
            due_on=due_on,
            contract_id=contract_id,
            user_id=user_id,
            external_person_id=external_person_id,
            academy_application_id=academy_application_id,
            protocol_id=protocol_id,
            details=details or {},
        )
        .on_conflict_do_nothing(index_elements=[EquipmentTask.source_key])
        .returning(EquipmentTask.id)
    )
    created = (await db.execute(statement)).scalar()
    task = await db.scalar(
        select(EquipmentTask).where(EquipmentTask.source_key == source_key)
    )
    assert task is not None
    if (
        created is None
        and task.status == "anulowane"
        and (task.details or {}).get(AUTO_CANCELLED)
    ):
        task.status = "otwarte"
        task.done_at = None
        task.done_by = None
        task.due_on = due_on
        task.title = title[:300]
        task.details = {
            **{
                key: value
                for key, value in (task.details or {}).items()
                if key not in (AUTO_CANCELLED, "cancel_reason")
            },
            **(details or {}),
        }
        await db.flush()
    elif created is None and task.status == "otwarte":
        if task.due_on != due_on or task.title != title[:300]:
            task.due_on = due_on
            task.title = title[:300]
            task.details = {**(task.details or {}), **(details or {})}
            await db.flush()
    return task


async def _contract_names(db: AsyncSession, contract: Contract) -> tuple[str, str]:
    candidate = await db.get(Candidate, contract.candidate_id)
    client = await db.get(Client, contract.client_id) if contract.client_id else None
    return candidate_name(candidate), (client.name if client else "")


async def _active_count(db: AsyncSession, **holder: int) -> int:
    ((column, value),) = holder.items()
    return int(
        await db.scalar(
            select(func.count()).where(
                getattr(EquipmentAssignment, column) == value,
                EquipmentAssignment.returned_at.is_(None),
            )
        )
        or 0
    )


async def tasks_for_contract_start(
    db: AsyncSession, contract: Contract
) -> Optional[EquipmentTask]:
    """Zestaw dla konsultanta, gdy klient ma „sprzęt od nas” (7 dni rob. przed startem)."""
    if contract.start_date is None or contract.status in _CLOSED_CONTRACT:
        return None
    if contract.start_date < business_today():
        return None
    if await client_provider(db, contract.client_id) != "nasz":
        return None
    if await _active_count(db, contract_id=contract.id):
        return None
    name, client = await _contract_names(db, contract)
    due = await workdays_before(db, contract.start_date, CONTRACT_START_LEAD_WORKDAYS)
    return await upsert_task(
        db,
        kind="wydanie",
        source_key=f"contract:{contract.id}:start",
        title=f"Przygotuj zestaw kontraktora: {name}",
        due_on=due,
        contract_id=contract.id,
        details={
            "start_date": contract.start_date.isoformat(),
            "client_name": client,
            "reason": "start_kontraktu",
        },
    )


async def tasks_for_contract_end(
    db: AsyncSession, contract: Contract
) -> Optional[EquipmentTask]:
    """Odbiór sprzętu na koniec współpracy (rejestr + wpisy ręczne zakładki)."""
    end = contract.end_date
    if end is None:
        return None
    ours = int(
        await db.scalar(
            select(func.count())
            .select_from(EquipmentAssignment)
            .join(EquipmentItem, EquipmentItem.id == EquipmentAssignment.item_id)
            .where(
                EquipmentAssignment.contract_id == contract.id,
                EquipmentAssignment.returned_at.is_(None),
                EquipmentItem.ownership == "nasz",
            )
        )
        or 0
    )
    clients = await _active_count(db, contract_id=contract.id) - ours
    legacy = int(
        await db.scalar(
            select(func.count()).where(
                ContractEquipment.contract_id == contract.id,
                ContractEquipment.assignment_id.is_(None),
                ContractEquipment.return_status == EquipmentReturnStatus.pending,
                ContractEquipment.owner == EquipmentOwner.ours,
            )
        )
        or 0
    )
    if ours + legacy == 0:
        return None
    name, client = await _contract_names(db, contract)
    return await upsert_task(
        db,
        kind="zwrot",
        source_key=f"contract:{contract.id}:end",
        title=f"Odbierz sprzęt: {name}",
        due_on=end,
        contract_id=contract.id,
        details={
            "end_date": end.isoformat(),
            "client_name": client,
            "items": ours + legacy,
            "client_items": clients,
            "reason": "koniec_wspolpracy",
        },
    )


async def tasks_for_person_exit(
    db: AsyncSession, user_id: int, last_day: date
) -> Optional[EquipmentTask]:
    """Odejście pracownika: zwrot wszystkiego, co ma w ewidencji, do ostatniego dnia."""
    user = await db.get(User, user_id)
    if user is None:
        raise EquipmentNotFound("Nie ma takiego konta.")
    count = await _active_count(db, user_id=user_id)
    if count == 0:
        return None
    return await upsert_task(
        db,
        kind="zwrot",
        source_key=f"user:{user_id}:exit",
        title=f"Odbierz sprzęt: {user.name or user.email}",
        due_on=last_day,
        user_id=user_id,
        details={
            "last_day": last_day.isoformat(),
            "items": count,
            "reason": "odejscie",
        },
    )


async def tasks_for_person_start(
    db: AsyncSession, user_id: int, start_date: date
) -> EquipmentTask:
    """Wejście pracownika: „Zestaw biura” na dzień startu (kreator w „Ludziach”)."""
    user = await db.get(User, user_id)
    if user is None:
        raise EquipmentNotFound("Nie ma takiego konta.")
    return await upsert_task(
        db,
        kind="wydanie",
        source_key=f"user:{user_id}:start",
        title=f"Przygotuj zestaw biura: {user.name or user.email}",
        due_on=start_date,
        user_id=user_id,
        details={"start_date": start_date.isoformat(), "reason": "wejscie"},
    )


async def cancel_open_task(
    db: AsyncSession, source_key: str, *, reason: str
) -> Optional[EquipmentTask]:
    """Anuluje OTWARTE zadanie automatu po ``source_key`` (zrobione zostaje)."""
    task = await db.scalar(
        select(EquipmentTask)
        .where(EquipmentTask.source_key == source_key)
        .with_for_update()
    )
    if task is None or task.status != "otwarte":
        return None
    task.status = "anulowane"
    task.done_at = datetime.now(timezone.utc)
    task.done_by = None
    task.details = {
        **(task.details or {}),
        AUTO_CANCELLED: True,
        "cancel_reason": reason,
    }
    await db.flush()
    return task


async def cancel_person_exit_task(
    db: AsyncSession, user_id: int
) -> Optional[EquipmentTask]:
    """„Cofnij odejście” — odbiór sprzętu nie jest potrzebny."""
    return await cancel_open_task(
        db, f"user:{user_id}:exit", reason="odejscie_cofniete"
    )


async def cancel_person_start_task(
    db: AsyncSession, user_id: int
) -> Optional[EquipmentTask]:
    """Anulowane wejście — zestaw biura nie jest potrzebny."""
    return await cancel_open_task(
        db, f"user:{user_id}:start", reason="wejscie_anulowane"
    )


async def cancel_contract_start_task(
    db: AsyncSession, contract_id: int
) -> Optional[EquipmentTask]:
    """Unieważniony kontrakt — zestawu kontraktora nikt nie odbierze."""
    return await cancel_open_task(
        db, f"contract:{contract_id}:start", reason="kontrakt_uniewazniony"
    )


async def ensure_signature_task(
    db: AsyncSession, protocol: EquipmentProtocol
) -> EquipmentTask:
    return await upsert_task(
        db,
        kind="podpis",
        source_key=f"protocol:{protocol.id}:podpis",
        # Numer protokołu idzie do drugiej linii agendy — w tytule zostaje osoba.
        title=f"Podpis protokołu: {protocol.holder_name}",
        due_on=protocol.protocol_date + timedelta(days=SIGNATURE_DUE_DAYS),
        contract_id=protocol.contract_id,
        user_id=protocol.user_id,
        external_person_id=protocol.external_person_id,
        academy_application_id=protocol.academy_application_id,
        protocol_id=protocol.id,
    )


async def close_holder_tasks(
    db: AsyncSession, *, kind: str, holder: dict[str, Optional[int]], actor: User
) -> int:
    conditions = [
        getattr(EquipmentTask, column) == value
        for column, value in holder.items()
        if value is not None
    ]
    if not conditions:
        return 0
    result = await db.execute(
        update(EquipmentTask)
        .where(
            EquipmentTask.kind == kind,
            EquipmentTask.status == "otwarte",
            EquipmentTask.protocol_id.is_(None),
            *conditions,
        )
        .values(status="zrobione", done_at=datetime.now(timezone.utc), done_by=actor.id)
    )
    return int(result.rowcount or 0)


async def list_tasks(db: AsyncSession, *, status: str = "otwarte") -> list[dict]:
    holder_name = func.coalesce(
        User.name,
        func.nullif(func.concat_ws(" ", Candidate.name, Candidate.lastname), ""),
        EquipmentExternalPerson.full_name,
        func.nullif(
            func.concat_ws(" ", AcademyCandidate.name, AcademyCandidate.lastname), ""
        ),
    )
    query = (
        join_academy_holder(
            select(
                EquipmentTask,
                holder_name,
                EquipmentProtocol.number,
                EquipmentProtocol.status,
                Client.name,
            )
            .outerjoin(User, User.id == EquipmentTask.user_id)
            .outerjoin(Contract, Contract.id == EquipmentTask.contract_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(
                EquipmentExternalPerson,
                EquipmentExternalPerson.id == EquipmentTask.external_person_id,
            ),
            EquipmentTask.academy_application_id,
        )
        .outerjoin(EquipmentProtocol, EquipmentProtocol.id == EquipmentTask.protocol_id)
        .order_by(EquipmentTask.due_on.asc().nulls_last(), EquipmentTask.id)
    )
    if status != "all":
        query = query.where(EquipmentTask.status == status)
    rows = (await db.execute(query.limit(300))).all()
    today = business_today()
    holders = {task.id: holder_of(task) or (None, None) for task, *_ in rows}
    # Skład protokołu (kategorie pozycji) — ikony w agendzie „Do zrobienia”.
    protocol_ids = {task.protocol_id for task, *_ in rows if task.protocol_id}
    categories: dict[int, list[str]] = {}
    if protocol_ids:
        for protocol_id, category in (
            await db.execute(
                select(
                    EquipmentProtocolLine.protocol_id, EquipmentProtocolLine.category
                )
                .where(EquipmentProtocolLine.protocol_id.in_(protocol_ids))
                .order_by(
                    EquipmentProtocolLine.protocol_id, EquipmentProtocolLine.position
                )
            )
        ).all():
            categories.setdefault(protocol_id, []).append(category)
    # Ostatni link do podpisu — „wysłany DD.MM” w drugiej linii zadania podpisu.
    link_sent: dict[int, date] = {}
    if protocol_ids:
        for protocol_id, sent_at in (
            await db.execute(
                select(
                    EquipmentProtocolLink.protocol_id,
                    func.max(EquipmentProtocolLink.created_at),
                )
                .where(EquipmentProtocolLink.protocol_id.in_(protocol_ids))
                .group_by(EquipmentProtocolLink.protocol_id)
            )
        ).all():
            link_sent[protocol_id] = business_date(sent_at)
    return [
        {
            "id": task.id,
            "kind": task.kind,
            "status": task.status,
            "title": task.title,
            "due_on": task.due_on.isoformat() if task.due_on else None,
            "overdue_days": (
                (today - task.due_on).days
                if task.due_on and task.status == "otwarte" and task.due_on < today
                else 0
            ),
            "holder": {
                "kind": holders[task.id][0],
                "id": holders[task.id][1],
                "name": name,
            },
            "protocol": (
                {
                    "id": task.protocol_id,
                    "number": number,
                    "status": protocol_status,
                    "categories": categories.get(task.protocol_id, []),
                    "client_name": client_name,
                    "link_sent_on": (
                        link_sent[task.protocol_id].isoformat()
                        if task.protocol_id in link_sent
                        else None
                    ),
                }
                if task.protocol_id
                else None
            ),
            "details": task.details or {},
        }
        for task, name, number, protocol_status, client_name in rows
    ]


async def set_task_status(
    db: AsyncSession, task_id: int, status: str, *, actor: User
) -> EquipmentTask:
    task = await db.get(EquipmentTask, task_id)
    if task is None:
        raise EquipmentNotFound("Nie ma takiego zadania.")
    if (task.details or {}).get(AUTO_CANCELLED):
        # Od decyzji recepcji zadanie jest jej — automat go już nie otworzy.
        task.details = {
            key: value
            for key, value in task.details.items()
            if key not in (AUTO_CANCELLED, "cancel_reason")
        }
    task.status = status
    if status == "otwarte":
        task.done_at = None
        task.done_by = None
    else:
        task.done_at = datetime.now(timezone.utc)
        task.done_by = actor.id
    await db.flush()
    return task


# ── „Przypomnij” o zwrocie (makieta Sprzętu, 19.10.2026) ──────────────────────

#: Link w dzwonku osoby: „Mój czas → Kartoteka” pokazuje jej sprzęt.
RETURN_REMINDER_LINK = "/my-time?tab=profile"


async def remind_holder(
    db: AsyncSession, task_id: int, *, actor: User
) -> dict[str, Any]:
    """Przypomnienie posiadaczowi o zwrocie sprzętu z otwartego zadania „zwrot”.

    Konto NEXUSA dostaje dzwonek i mail „Czas i ludzie”
    (``equipment_return_reminder`` — termin, bez listy sprzętu i kwot).
    Konsultant, osoba spoza NEXUSA i uczestnik Akademii nie mają konta:
    recepcja wysyła wiadomość ze swojej poczty (jak link do podpisu, D8),
    a trasa oddaje adres. Każde przypomnienie zostaje w ``details``.
    """
    task = await db.get(EquipmentTask, task_id, with_for_update=True)
    if task is None:
        raise EquipmentNotFound("Nie ma takiego zadania.")
    if task.kind != "zwrot" or task.status != "otwarte":
        raise EquipmentConflict("Przypomnieć można tylko o otwartym zwrocie sprzętu.")
    ref = holder_of(task)
    if ref is None:
        raise EquipmentConflict("To zadanie nie ma osoby, której można przypomnieć.")
    holder = await resolve_holder(db, *ref)
    today = business_today()
    channel = "powiadomienie" if holder.kind == "user" else "mail"
    if channel == "powiadomienie":
        # Zwrot z odejścia jest po terminie, gdy konto już wyłączone — dzwonek
        # by nie wyszedł, a firmowa skrzynka zwykle już nie istnieje.
        account = await db.get(User, holder.id)
        if account is None or not account.is_active:
            raise EquipmentConflict(
                "Konto tej osoby jest wyłączone — przypomnij telefonicznie."
            )
        due = f" do {task.due_on:%d.%m.%Y}" if task.due_on else ""
        sent = await notify_each(
            db,
            [holder.id],
            title="Zwrot sprzętu do recepcji",
            message=f"Recepcja prosi o zwrot sprzętu firmy{due}.",
            ntype=NotificationType.equipment_return_reminder,
            related_entity_type="equipment_task",
            related_entity_id=task.id,
            link=RETURN_REMINDER_LINK,
            log_tag="equipment",
        )
        # Wyciszone „Czas i ludzie” albo dzwonek już był dziś — recepcja
        # pisze ze swojej poczty, zamiast widzieć „wysłane”.
        if sent == 0:
            channel = "mail"
    if channel == "mail" and not holder.email:
        raise EquipmentConflict(
            "Ta osoba nie ma adresu e-mail w NEXUSIE — przypomnij telefonicznie."
        )
    task.details = {
        **(task.details or {}),
        "reminded_on": today.isoformat(),
        "reminded_by": actor.id,
        "reminders": int((task.details or {}).get("reminders") or 0) + 1,
    }
    await db.flush()
    return {
        "channel": channel,
        "email": holder.email if channel == "mail" else None,
        "reminded_on": today.isoformat(),
    }


# ── Przypomnienia ─────────────────────────────────────────────────────────────


async def reminder_recipients(db: AsyncSession) -> list[int]:
    """Konta z uprawnieniem „Sprzęt” (recepcja). Admin tylko, gdy nikogo innego nie ma."""
    from app.services.effective_access import resolve_effective_access

    users = list((await db.scalars(select(User).where(User.is_active.is_(True)))).all())
    if not users:
        return []
    await resolve_effective_access(db, users)
    holders = [u for u in users if has_permission(u, ProductAction.equipment)]
    reception = [u.id for u in holders if not u.has_role(UserRole.admin)]
    return reception or [u.id for u in holders]


async def run_once(
    db: AsyncSession, *, remind_from_hour: int = REMIND_FROM_HOUR
) -> dict[str, Any]:
    """Jeden dzienny przebieg: dzwonek ``equipment_task`` do recepcji.

    Idempotentny w obrębie dnia firmy (rezerwacja ``hr_job_runs``); bez
    otwartych zadań na najbliższe dni nikt nie dostaje dzwonka. Wyłączony
    moduł i godzina przed ``remind_from_hour`` (czas warszawski) = nic.
    """
    from app.services.hr.modules import HrModule, load_modules

    if not (await load_modules(db)).get(HrModule.equipment):
        return {"status": "disabled"}
    now = local_now()
    if now.hour < remind_from_hour:
        return {"status": "too_early"}
    today = business_today()
    # Rezerwacja wchodzi razem z dzwonkami (bez osobnego commitu).
    run_id = await job_runs.claim(
        db, REMINDER_JOB, today.isoformat(), now, commit=False
    )
    if run_id is None:
        return {"skipped": True}
    horizon = today + timedelta(days=REMIND_AHEAD_DAYS)
    due = list(
        (
            await db.scalars(
                select(EquipmentTask).where(
                    EquipmentTask.status == "otwarte",
                    EquipmentTask.due_on.is_not(None),
                    EquipmentTask.due_on <= horizon,
                )
            )
        ).all()
    )
    counts: dict[str, Any] = {"tasks": len(due), "notified": 0}
    if due:
        overdue = sum(1 for task in due if task.due_on and task.due_on < today)
        soon = len(due) - overdue
        message = (
            f"Po terminie: {overdue}. Na dziś i najbliższe dni: {soon}."
            if overdue
            else f"Na dziś i najbliższe dni: {soon}."
        )
        counts["notified"] = await notify_each(
            db,
            await reminder_recipients(db),
            title=f"Sprzęt: {len(due)} do zrobienia",
            message=message,
            ntype=NotificationType.equipment_task,
            related_entity_type="equipment_tasks",
            related_entity_id=None,
            link="/equipment?tab=tasks",
            log_tag="equipment",
        )
        await db.execute(
            update(EquipmentTask)
            .where(EquipmentTask.id.in_([task.id for task in due]))
            .values(last_reminded_on=today)
        )
    await job_runs.finish(db, run_id, status="done", counts=counts)
    return counts


__all__ = [
    "cancel_contract_start_task",
    "remind_holder",
    "cancel_person_exit_task",
    "cancel_person_start_task",
    "run_once",
    "tasks_for_contract_end",
    "tasks_for_contract_start",
    "tasks_for_person_exit",
    "tasks_for_person_start",
]
