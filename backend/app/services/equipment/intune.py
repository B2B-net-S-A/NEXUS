"""Intune w ewidencji sprzętu (etap 4, D9): nocny odczyt urządzeń i rozjazdy.

Przebieg (``run_once``; pętla ``equipment_intune_sync`` raz na dobę od 05:30
Warszawy, ręcznie — admin):

1. rezerwacja dnia w ``hr_job_runs`` (``kind = equipment_intune_sync``):
   drugi nocny przebieg tego samego dnia nic nie robi, nieudany albo
   przerwany wolno powtórzyć, ręczny powtarza dzień, który już przeszedł,
2. odczyt CAŁEJ listy urządzeń (``intune_graph``) przed jakimkolwiek zapisem —
   awaria w połowie stronicowania nie oznacza niczego jako „zniknęło”,
3. upsert po ``intune_device_id``: egzemplarz po S/N (postać kanoniczna
   rejestru, bez wielkości liter), konto po UPN (``users.email``, potem
   ``users.microsoft_upn``, bez wielkości liter). Brak dopasowania po S/N
   nie zdejmuje powiązania ręcznego (``link_item``),
4. urządzenia nieobecnego w odpowiedzi ``missing_since`` dostaje raz (data
   pierwszego braku zostaje), powrót urządzenia je czyści,
5. stan w ``equipment_intune_sync_state`` (sonda health) — błąd jako kategoria
   bez treści odpowiedzi Graph.

Rozjazdy liczymy przy odczycie (``discrepancies``). Rejestru sami nie
zmieniamy (propozycja recepcji: „Do wyjaśnienia” z podpowiedzią, bez
automatycznej zmiany); urządzenie z ``resolution`` nie jest rozjazdem —
leży w ``resolved`` („Wyjaśnione i pominięte”), skąd recepcja może cofnąć
decyzję (``unresolve``) i urządzenie wraca na listę.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, false, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.academy import AcademyApplication
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentExternalPerson,
    EquipmentItem,
    EquipmentModel,
)
from app.models.equipment_intune import (
    EquipmentIntuneDevice,
    EquipmentIntuneSyncState,
)
from app.models.hr_ops import HrJobRun
from app.models.user import User
from app.services.equipment import identifiers, intune_graph, sanitize
from app.services.equipment.intune_graph import DeviceSource, IntuneSourceError
from app.services.equipment.registry import (
    EquipmentConflict,
    EquipmentError,
    EquipmentNotFound,
    candidate_name,
)
from app.services.equipment_extras_schema import INTUNE_RESOLUTIONS
from app.services.hr import audit
from app.services.hr.modules import load_modules

logger = logging.getLogger(__name__)

JOB_KIND = "equipment_intune_sync"
MODULE = "equipment"
#: Nocny przebieg od tej godziny (Warszawa) — przed pracą recepcji.
RUN_FROM = time(5, 30)
#: Rezerwacja starsza niż tyle bez zakończenia = przebieg przerwany.
STALE_CLAIM = timedelta(hours=1)
#: Sonda health: udany przebieg nie starszy niż doba z zapasem.
FRESH_FOR = timedelta(hours=26)
UPSERT_CHUNK = 500
NOTE_MAX = 500

#: Rodzaje rozjazdów w kolejności listy.
KINDS: tuple[str, ...] = (
    "zniknal_z_intune",
    "brak_w_ewidencji",
    "inny_posiadacz",
    "brak_w_intune",
)

_WARSAW = ZoneInfo(DEFAULT_TZ)

ERROR_TEXT: dict[str, str] = {
    "auth": (
        "NEXUS nie dostał tokenu aplikacji „NEXUS Kadry”. Sprawdź identyfikator "
        "i sekret rejestracji oraz tenanta."
    ),
    "forbidden": (
        "Microsoft odmówił odczytu urządzeń (403). Rejestracja nie ma jeszcze "
        "zgody administratora na DeviceManagementManagedDevices.Read.All."
    ),
    "throttled": (
        "Microsoft chwilowo ogranicza liczbę zapytań. Następny przebieg "
        "spróbuje ponownie."
    ),
    "server_error": (
        "Microsoft 365 nie odpowiedział poprawnie. Następny przebieg spróbuje ponownie."
    ),
    "timeout": (
        "Microsoft 365 nie odpowiedział na czas. Następny przebieg spróbuje ponownie."
    ),
    "network": (
        "Brak połączenia z Microsoft 365. Następny przebieg spróbuje ponownie."
    ),
    "empty_response": (
        "Intune zwrócił pustą listę urządzeń, więc niczego nie oznaczyliśmy jako "
        "zniknięte. Sprawdź uprawnienia rejestracji."
    ),
}
DEFAULT_ERROR_TEXT = "Odczyt z Intune się nie udał. Szczegóły są w logu serwera."


def error_text(code: Optional[str]) -> Optional[str]:
    """Kod z ``last_error`` („forbidden (403)”) → zdanie dla recepcji."""

    if not code:
        return None
    return ERROR_TEXT.get(code.split(" ", 1)[0], DEFAULT_ERROR_TEXT)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


# ── Przebieg ─────────────────────────────────────────────────────────────────


async def _claim(
    db: AsyncSession, period_key: str, now: datetime, *, manual: bool
) -> Optional[int]:
    stale = and_(HrJobRun.status == "claimed", HrJobRun.claimed_at < now - STALE_CLAIM)
    retake = HrJobRun.status != "claimed" if manual else HrJobRun.status == "failed"
    statement = (
        insert(HrJobRun)
        .values(kind=JOB_KIND, period_key=period_key, status="claimed", claimed_at=now)
        .on_conflict_do_update(
            constraint="uq_hr_job_runs_kind_period",
            set_={
                "status": "claimed",
                "claimed_at": now,
                "finished_at": None,
                "error": None,
            },
            where=or_(retake, stale),
        )
        .returning(HrJobRun.id)
    )
    claimed = await db.scalar(statement)
    await db.commit()
    return claimed


async def _finish(
    db: AsyncSession,
    run_id: int,
    *,
    status: str,
    counts: dict[str, Any],
    error: Optional[str] = None,
) -> None:
    await db.execute(
        update(HrJobRun)
        .where(HrJobRun.id == run_id)
        .values(status=status, counts=counts, error=error, finished_at=func.now())
    )


async def _save_state(
    db: AsyncSession, now: datetime, *, error: Optional[str], device_count: int = 0
) -> None:
    values: dict[str, Any] = {
        "last_run_at": now,
        "last_error": error,
        "updated_at": now,
    }
    if error is None:
        values.update(last_success_at=now, device_count=device_count)
    statement = insert(EquipmentIntuneSyncState).values(id=1, **values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[EquipmentIntuneSyncState.id], set_=values
        )
    )


async def _items_by_serial(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(EquipmentItem.id, EquipmentItem.serial_number)
        .where(EquipmentItem.serial_number.is_not(None))
        .order_by(EquipmentItem.id)
    )
    out: dict[str, int] = {}
    for item_id, serial in rows.all():
        key = identifiers.code(serial)
        if key:
            out.setdefault(key, item_id)
    return out


async def _users_by_login(db: AsyncSession, logins: set[str]) -> dict[str, int]:
    """UPN (małe litery) → konto: najpierw ``email``, potem ``microsoft_upn``."""

    if not logins:
        return {}
    rows = await db.execute(
        select(User.id, User.email, User.microsoft_upn)
        .where(
            or_(
                func.lower(User.email).in_(logins),
                func.lower(User.microsoft_upn).in_(logins),
            )
        )
        .order_by(User.id)
    )
    by_email: dict[str, int] = {}
    by_upn: dict[str, int] = {}
    for user_id, email, upn in rows.all():
        if email:
            by_email.setdefault(email.lower(), user_id)
        if upn:
            by_upn.setdefault(upn.lower(), user_id)
    out: dict[str, int] = {}
    for login in logins:
        user_id = by_email.get(login) or by_upn.get(login)
        if user_id is not None:
            out[login] = user_id
    return out


async def _store(
    db: AsyncSession, devices: list[intune_graph.IntuneDevice], now: datetime
) -> dict[str, int]:
    unique = {device.intune_device_id: device for device in devices}
    if not unique:
        alive = await db.scalar(
            select(func.count())
            .select_from(EquipmentIntuneDevice)
            .where(EquipmentIntuneDevice.missing_since.is_(None))
        )
        if alive:
            # Pusta odpowiedź przy znanych urządzeniach to prawie na pewno
            # odebrane uprawnienie, a nie firma bez komputerów.
            raise IntuneSourceError(None, category="empty_response")

    items = await _items_by_serial(db)
    users = await _users_by_login(
        db,
        {
            device.user_principal_name.lower()
            for device in unique.values()
            if device.user_principal_name
        },
    )
    returned = 0
    if unique:
        returned = (
            await db.scalar(
                select(func.count())
                .select_from(EquipmentIntuneDevice)
                .where(
                    EquipmentIntuneDevice.intune_device_id.in_(list(unique)),
                    EquipmentIntuneDevice.missing_since.is_not(None),
                )
            )
            or 0
        )

    rows: list[dict[str, Any]] = []
    for device in unique.values():
        serial = identifiers.code(device.serial_number)
        login = (device.user_principal_name or "").lower()
        rows.append(
            {
                "intune_device_id": device.intune_device_id,
                "device_name": device.device_name,
                "serial_number": device.serial_number,
                "manufacturer": device.manufacturer,
                "model": device.model,
                "operating_system": device.operating_system,
                "user_principal_name": device.user_principal_name,
                "user_id": users.get(login) if login else None,
                "item_id": items.get(serial) if serial else None,
                "compliance_state": device.compliance_state,
                "intune_last_sync_at": device.last_sync_at,
                "first_seen_at": now,
                "last_seen_at": now,
            }
        )

    created = 0
    for start in range(0, len(rows), UPSERT_CHUNK):
        statement = insert(EquipmentIntuneDevice).values(
            rows[start : start + UPSERT_CHUNK]
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            constraint="uq_equipment_intune_devices_device",
            set_={
                "device_name": excluded.device_name,
                "serial_number": excluded.serial_number,
                "manufacturer": excluded.manufacturer,
                "model": excluded.model,
                "operating_system": excluded.operating_system,
                "user_principal_name": excluded.user_principal_name,
                "user_id": excluded.user_id,
                # Brak dopasowania po S/N zostawia powiązanie ręczne.
                "item_id": func.coalesce(
                    excluded.item_id, EquipmentIntuneDevice.item_id
                ),
                "compliance_state": excluded.compliance_state,
                "intune_last_sync_at": excluded.intune_last_sync_at,
                "last_seen_at": excluded.last_seen_at,
                "missing_since": None,
                "updated_at": now,
            },
        ).returning(literal_column("(xmax = 0)"))
        result = await db.execute(statement)
        created += sum(1 for (inserted,) in result.all() if inserted)

    missing = await db.execute(
        update(EquipmentIntuneDevice)
        .where(
            EquipmentIntuneDevice.missing_since.is_(None),
            EquipmentIntuneDevice.last_seen_at < now,
        )
        .values(missing_since=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return {
        "devices": len(rows),
        "created": created,
        "returned": returned,
        "missing": missing.rowcount or 0,
        "matched_items": sum(1 for row in rows if row["item_id"]),
        "matched_users": sum(1 for row in rows if row["user_id"]),
    }


async def run_once(
    db: AsyncSession,
    *,
    source: Optional[DeviceSource] = None,
    mode: Optional[str] = None,
    now: Optional[datetime] = None,
    manual: bool = False,
) -> dict[str, Any]:
    """Jeden przebieg. Tryb ``off`` = ``{"status": "disabled"}`` i nic więcej.

    Nocny (``manual=False``) pilnuje modułu „Sprzęt”, godziny 05:30 Warszawy
    i jednego przebiegu na dzień. Ręczny (admin) czyta od razu, także przy
    wyłączonym module (przygotowanie przełączenia). Nie rzuca przy awarii
    Microsoftu: błąd ląduje w stanie i w wyniku.
    """

    mode = mode or intune_graph.current_mode()
    if mode == "off":
        return {"status": "disabled"}
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(_WARSAW)
    if not manual:
        if not (await load_modules(db)).get(MODULE):
            return {"status": "disabled", "reason": "module_off"}
        if local.time() < RUN_FROM:
            return {"status": "too_early"}

    run_id = await _claim(db, local.date().isoformat(), now, manual=manual)
    if run_id is None:
        return {"status": "skipped", "reason": "running" if manual else "already_ran"}

    active = source or intune_graph.source_for(mode, now=now)
    try:
        devices = await active.list_devices()
        counts = await _store(db, devices, now)
    except Exception as exc:  # noqa: BLE001 — przebieg do ponowienia, nie cichy sukces
        await db.rollback()
        if isinstance(exc, IntuneSourceError):
            code = exc.label
            logger.warning("equipment_intune: odczyt nieudany %s", code)
        else:
            code = f"internal: {type(exc).__name__}"
            logger.exception("equipment_intune: przebieg nieudany")
        await _save_state(db, now, error=code)
        await _finish(db, run_id, status="failed", counts={}, error=code)
        await db.commit()
        return {"status": "error", "error": code}

    await _save_state(db, now, error=None, device_count=counts["devices"])
    await _finish(db, run_id, status="done", counts=counts)
    await db.commit()
    logger.info("equipment_intune: przebieg %s", counts)
    return {"status": "ok", **counts}


# ── Stan i sonda health ──────────────────────────────────────────────────────


async def _state(db: AsyncSession) -> Optional[EquipmentIntuneSyncState]:
    return await db.scalar(
        select(EquipmentIntuneSyncState)
        .where(EquipmentIntuneSyncState.id == 1)
        .execution_options(populate_existing=True)
    )


def health_verdict(
    mode: str, state: Optional[EquipmentIntuneSyncState], now: datetime
) -> str:
    """``disabled`` przy ``off``; ``healthy`` = udany przebieg < 26 h i bez błędu."""

    if mode == "off":
        return "disabled"
    if state is None or state.last_success_at is None or state.last_error:
        return "degraded"
    return "healthy" if now - state.last_success_at < FRESH_FOR else "degraded"


async def health_state(db: AsyncSession, *, now: Optional[datetime] = None) -> str:
    return health_verdict(
        intune_graph.current_mode(), await _state(db), now or datetime.now(timezone.utc)
    )


async def sync_status(db: AsyncSession) -> dict[str, Any]:
    state = await _state(db)
    mode = intune_graph.current_mode()
    return {
        "mode": mode,
        "health": health_verdict(mode, state, datetime.now(timezone.utc)),
        "last_run_at": _iso(state.last_run_at) if state else None,
        "last_success_at": _iso(state.last_success_at) if state else None,
        "device_count": state.device_count if state else 0,
        "error": error_text(state.last_error) if state else None,
        "error_code": state.last_error if state else None,
    }


# ── Rozjazdy ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Holder:
    kind: str
    id: int
    name: str
    #: Loginy/e-maile posiadacza (małe litery); puste = nie ma z czym porównać.
    logins: frozenset[str]

    def payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "name": self.name}


def _logins(*values: Optional[str]) -> frozenset[str]:
    return frozenset(v.strip().lower() for v in values if v and v.strip())


async def _holders(
    db: AsyncSession, assignments: list[EquipmentAssignment]
) -> dict[int, _Holder]:
    """Posiadacz aktywnego wydania (klucz: id wydania).

    Konto porównujemy po identyfikatorze i loginach, kontrakt po e-mailu
    kandydata (nadpisanie z kontraktu, potem profil), osobę spoza NEXUSA po
    e-mailu służbowym. Uczestnika Akademii nie porównujemy: ma prywatny
    e-mail kandydata, a laptop z Akademii loguje się kontem szkoleniowym —
    każde porównanie dałoby fałszywy rozjazd.
    """

    def ids(column: str) -> list[int]:
        return [
            getattr(a, column) for a in assignments if getattr(a, column) is not None
        ]

    users: dict[int, _Holder] = {}
    if user_ids := ids("user_id"):
        for user in (await db.scalars(select(User).where(User.id.in_(user_ids)))).all():
            users[user.id] = _Holder(
                "user",
                user.id,
                user.name or user.email,
                _logins(user.email, user.microsoft_upn),
            )
    contracts: dict[int, _Holder] = {}
    if contract_ids := ids("contract_id"):
        rows = await db.execute(
            select(Contract.id, Contract.candidate_email, Candidate)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.id.in_(contract_ids))
        )
        for contract_id, override, candidate in rows.all():
            contracts[contract_id] = _Holder(
                "contract",
                contract_id,
                candidate_name(candidate),
                _logins(override or (candidate.email if candidate else None)),
            )
    external: dict[int, _Holder] = {}
    if external_ids := ids("external_person_id"):
        people = await db.scalars(
            select(EquipmentExternalPerson).where(
                EquipmentExternalPerson.id.in_(external_ids)
            )
        )
        for person in people.all():
            external[person.id] = _Holder(
                "external", person.id, person.full_name, _logins(person.work_email)
            )
    academy: dict[int, _Holder] = {}
    if application_ids := ids("academy_application_id"):
        rows = await db.execute(
            select(AcademyApplication.id, Candidate)
            .outerjoin(Candidate, Candidate.id == AcademyApplication.candidate_id)
            .where(AcademyApplication.id.in_(application_ids))
        )
        for application_id, candidate in rows.all():
            academy[application_id] = _Holder(
                "academy", application_id, candidate_name(candidate), frozenset()
            )

    out: dict[int, _Holder] = {}
    for assignment in assignments:
        holder = (
            users.get(assignment.user_id or 0)
            or contracts.get(assignment.contract_id or 0)
            or external.get(assignment.external_person_id or 0)
            or academy.get(assignment.academy_application_id or 0)
        )
        if holder is not None:
            out[assignment.id] = holder
    return out


def _other_holder(
    device: EquipmentIntuneDevice, device_user: Optional[User], holder: _Holder
) -> bool:
    """Czy użytkownik urządzenia z Intune to ktoś inny niż posiadacz z ewidencji."""

    device_logins = _logins(device.user_principal_name)
    if device_user is not None:
        device_logins |= _logins(device_user.email, device_user.microsoft_upn)
    if not device_logins:
        return False  # urządzenie bez użytkownika — nie ma z czym porównać
    if holder.kind == "user" and device.user_id == holder.id:
        return False
    if holder.kind != "user" and not holder.logins:
        return False  # kontrakt bez e-maila, Akademia — porównanie niemożliwe
    return not (holder.logins & device_logins)


def _device_payload(
    device: EquipmentIntuneDevice, user: Optional[User]
) -> dict[str, Any]:
    return {
        "id": device.id,
        "device_name": device.device_name,
        "serial_number": device.serial_number,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "operating_system": device.operating_system,
        "user_principal_name": device.user_principal_name,
        "user": {"id": user.id, "name": user.name or user.email} if user else None,
        "compliance_state": device.compliance_state,
        "last_sync_at": _iso(device.intune_last_sync_at),
        "last_seen_at": _iso(device.last_seen_at),
        "missing_since": _iso(device.missing_since),
        "item_id": device.item_id,
        "resolution": device.resolution,
        "resolution_note": device.resolution_note,
        "resolved_at": _iso(device.resolved_at),
    }


def _item_payload(item: EquipmentItem, model: EquipmentModel) -> dict[str, Any]:
    return {
        "id": item.id,
        "inventory_number": item.inventory_number,
        "serial_number": item.serial_number,
        "model_name": model.name,
        "category": model.category,
        "status": item.status,
    }


async def discrepancies(db: AsyncSession) -> dict[str, Any]:
    """Lista rozjazdów Intune ↔ ewidencja i liczniki (z „Zgodne”)."""

    state = await _state(db)
    checked = state is not None and state.last_success_at is not None
    device_rows = (
        await db.execute(
            select(EquipmentIntuneDevice, User)
            .outerjoin(User, User.id == EquipmentIntuneDevice.user_id)
            .order_by(EquipmentIntuneDevice.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    linked = {device.item_id for device, _ in device_rows if device.item_id}
    seen_serials = {
        key
        for device, _ in device_rows
        if (key := identifiers.code(device.serial_number))
    }

    issued_laptop = and_(
        EquipmentModel.category == "laptop",
        EquipmentItem.status == "wydany",
        # Laptop klienta nie jest w naszym Intune.
        EquipmentItem.ownership != "klienta",
    )
    condition = EquipmentItem.id.in_(linked) if linked else false()
    if checked:
        condition = or_(condition, issued_laptop)
    item_rows = (
        await db.execute(
            select(EquipmentItem, EquipmentModel, EquipmentAssignment)
            .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
            .outerjoin(
                EquipmentAssignment,
                and_(
                    EquipmentAssignment.item_id == EquipmentItem.id,
                    EquipmentAssignment.returned_at.is_(None),
                ),
            )
            .where(condition)
            .order_by(EquipmentItem.id)
        )
    ).all()
    holders = await _holders(
        db, [assignment for _, _, assignment in item_rows if assignment is not None]
    )
    items: dict[int, tuple[EquipmentItem, EquipmentModel, Optional[_Holder]]] = {
        item.id: (item, model, holders.get(assignment.id) if assignment else None)
        for item, model, assignment in item_rows
    }

    counts: dict[str, int] = {kind: 0 for kind in KINDS}
    counts.update(zgodne=0, wyjasnione=0)
    rows: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []

    def add(kind: str, device: Any, user: Any, item_id: Optional[int]) -> None:
        counts[kind] += 1
        entry = items.get(item_id) if item_id else None
        rows.append(
            {
                "key": f"device:{device.id}" if device else f"item:{item_id}",
                "kind": kind,
                "device": _device_payload(device, user) if device else None,
                "item": _item_payload(entry[0], entry[1]) if entry else None,
                "holder": entry[2].payload() if entry and entry[2] else None,
            }
        )

    for device, user in device_rows:
        if device.resolution:
            counts["wyjasnione"] += 1
            entry = items.get(device.item_id) if device.item_id else None
            resolved.append(
                {
                    "key": f"device:{device.id}",
                    "device": _device_payload(device, user),
                    "item": _item_payload(entry[0], entry[1]) if entry else None,
                    "holder": entry[2].payload() if entry and entry[2] else None,
                }
            )
        elif device.missing_since is not None:
            add("zniknal_z_intune", device, user, device.item_id)
        elif device.item_id is None or device.item_id not in items:
            add("brak_w_ewidencji", device, user, None)
        else:
            holder = items[device.item_id][2]
            if holder is not None and _other_holder(device, user, holder):
                add("inny_posiadacz", device, user, device.item_id)
            else:
                counts["zgodne"] += 1

    if checked:
        for item_id, (item, model, _) in items.items():
            if model.category != "laptop" or item.status != "wydany":
                continue
            if item.ownership == "klienta" or item_id in linked:
                continue
            if identifiers.code(item.serial_number) in seen_serials:
                continue
            add("brak_w_intune", None, None, item_id)

    order = {kind: index for index, kind in enumerate(KINDS)}
    rows.sort(
        key=lambda row: (
            order[row["kind"]],
            ((row["device"] or {}).get("device_name") or "").lower(),
            row["key"],
        )
    )
    resolved.sort(
        key=lambda row: (row["device"]["resolved_at"] or "", row["key"]), reverse=True
    )
    return {
        "rows": rows,
        "resolved": resolved,
        "counts": counts,
        "checked": checked,
        "devices": sum(1 for device, _ in device_rows if device.missing_since is None),
    }


# ── Decyzje recepcji ─────────────────────────────────────────────────────────


def _clean_note(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = sanitize.clean_text(value)
    if cleaned.reasons:
        raise EquipmentError(
            "Notatka zawiera dane, których NEXUS nie przechowuje ("
            + ", ".join(cleaned.reasons)
            + ")."
        )
    if cleaned.value and len(cleaned.value) > NOTE_MAX:
        raise EquipmentError(f"Notatka może mieć najwyżej {NOTE_MAX} znaków.")
    return cleaned.value


async def _device(db: AsyncSession, device_id: int) -> EquipmentIntuneDevice:
    device = await db.scalar(
        select(EquipmentIntuneDevice)
        .where(EquipmentIntuneDevice.id == device_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if device is None:
        raise EquipmentNotFound("Nie ma takiego urządzenia z Intune.")
    return device


async def _payload(db: AsyncSession, device: EquipmentIntuneDevice) -> dict[str, Any]:
    await db.flush()
    user = await db.get(User, device.user_id) if device.user_id else None
    return _device_payload(device, user)


async def resolve(
    db: AsyncSession,
    device_id: int,
    resolution: str,
    note: Optional[str],
    user: User,
) -> dict[str, Any]:
    """„Wyjaśnione” albo „Pomiń” — urządzenie znika z listy rozjazdów."""

    if resolution not in INTUNE_RESOLUTIONS:
        raise EquipmentError("Nieznana decyzja — wybierz „Wyjaśnione” albo „Pomiń”.")
    clean = _clean_note(note)
    device = await _device(db, device_id)
    device.resolution = resolution
    device.resolution_note = clean
    device.resolved_by = user.id
    device.resolved_at = datetime.now(timezone.utc)
    audit.record(
        db,
        actor_user_id=user.id,
        subject_user_id=device.user_id,
        entity_type="equipment_intune_device",
        entity_id=device.id,
        action="intune_resolved",
        details={"resolution": resolution, "with_note": clean is not None},
    )
    return await _payload(db, device)


async def unresolve(db: AsyncSession, device_id: int, user: User) -> dict[str, Any]:
    """„Cofnij decyzję” — urządzenie wraca na listę rozjazdów (o ile nim jest)."""

    device = await _device(db, device_id)
    if device.resolution is None:
        raise EquipmentConflict("To urządzenie nie ma decyzji do cofnięcia.")
    previous = device.resolution
    device.resolution = None
    device.resolution_note = None
    device.resolved_by = None
    device.resolved_at = None
    audit.record(
        db,
        actor_user_id=user.id,
        subject_user_id=device.user_id,
        entity_type="equipment_intune_device",
        entity_id=device.id,
        action="intune_resolution_undone",
        details={"previous": previous},
    )
    return await _payload(db, device)


async def link_item(
    db: AsyncSession, device_id: int, item_id: int, user: User
) -> dict[str, Any]:
    """Ręczne powiązanie urządzenia z egzemplarzem (np. S/N w rejestrze z literówką)."""

    device = await _device(db, device_id)
    item = await db.scalar(
        select(EquipmentItem).where(EquipmentItem.id == item_id).with_for_update()
    )
    if item is None:
        raise EquipmentNotFound("Nie ma takiego egzemplarza w rejestrze.")
    taken = await db.scalar(
        select(EquipmentIntuneDevice.id).where(
            EquipmentIntuneDevice.item_id == item_id,
            EquipmentIntuneDevice.id != device_id,
        )
    )
    if taken is not None:
        raise EquipmentConflict(
            "Ten egzemplarz jest już powiązany z innym urządzeniem z Intune."
        )
    device.item_id = item.id
    audit.record(
        db,
        actor_user_id=user.id,
        subject_user_id=device.user_id,
        entity_type="equipment_intune_device",
        entity_id=device.id,
        action="intune_linked",
        details={"item_id": item.id},
    )
    return await _payload(db, device)


__all__ = [
    "JOB_KIND",
    "KINDS",
    "discrepancies",
    "error_text",
    "health_state",
    "health_verdict",
    "link_item",
    "resolve",
    "run_once",
    "sync_status",
    "unresolve",
]
