"""Pakiet klienta: co wejście konsultanta dostaje od klienta (etap 3, O2–O3).

Kontrakt między ścieżką wejścia (``lifecycle_*``) a pakietem klienta: ścieżka
„Konsultant u klienta” dokłada do zadań wejścia to, co zwraca ``pack_tasks``,
a mail powitalny bierze ``first_day``. Implementacja pakietu żyje w tym pliku.

Pakiet (zakładka klienta „Wejście u klienta”, makieta M5):

* **sprzęt** — flaga „od nas / od klienta” zostaje na kliencie
  (``clients.equipment_provider``, D7), lista rzeczy od nas i od klienta,
  wzory protokołu wydania i zwrotu (``None`` = wbudowany standard),
* **pierwszy dzień** — kto odbiera (domyślnie menedżer z kontraktu
  ``client_pm_contact_id``, zapasowo wskazany kontakt klienta), gdzie, o której
  i co zabrać,
* **dokumenty od konsultanta** — termin względem startu (dni robocze),
  wymagane, z plikiem; odhacza je opiekun (konsultant nie ma konta, O6),
* **dostępy** — kto po naszej stronie ich pilnuje i kiedy.

``pack_tasks`` NIE zwraca „Przygotuj zestaw” ani „Wydanie sprzętu i protokół”:
to pozycje ścieżki z warunkiem „sprzęt od nas” (klucze ``equipment_kit``,
``equipment_issue``) — inaczej dubel z zadaniem recepcji. Listę rzeczy od nas
ścieżka czyta z ``load_pack(...).equipment_ours``.

Zapis: cała część naraz (lista zastępuje listę), ``version`` rośnie przy
każdym zapisie, ``expected_version`` chroni przed nadpisaniem cudzej zmiany
(``0`` = osoba zaczęła od pustego pakietu — gdy pakiet już jest, 409). Flaga
sprzętu żyje na kliencie i zmienia się też poza pakietem (profil klienta,
Sprzęt), więc wersja pakietu jej nie pilnuje: ``equipment.provider`` przychodzi
tylko przy zmianie flagi, z ``expected_provider`` — wartością, od której osoba
zaczęła; inna wartość na kliencie = 409. Kto może zapisać którą część,
decyduje trasa (``api/client_onboarding.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.equipment import (
    ClientOnboardingPack,
    ClientOnboardingPackItem,
    EquipmentProtocolTemplate,
)
from app.models.user import User
from app.services import equipment_schema as schema
from app.services.client_access import record_client_audit
from app.services.equipment import registry
from app.services.equipment.errors import (
    EquipmentConflict,
    EquipmentError,
    EquipmentNotFound,
)
from app.services.hr_lifecycle_schema import MAX_OFFSET_AFTER, MAX_OFFSET_BEFORE


@dataclass(frozen=True)
class PackTask:
    """Zadanie wejścia z pakietu klienta (ten sam kształt co pozycja ścieżki)."""

    title: str
    description: Optional[str]
    #: Rola wykonawcy z ``hr_lifecycle_schema.TASK_ASSIGNEES``
    #: (np. ``care_owner``, ``delivery_lead``, ``reception``, ``administration``).
    assignee: str
    #: Dni robocze względem startu kontraktu (ujemne = przed startem).
    offset_days: int
    required: bool
    requires_file: bool
    #: Kategoria z ``hr_lifecycle_schema`` (accounts, equipment, documents…).
    category: str


@dataclass(frozen=True)
class FirstDay:
    """Pierwszy dzień u klienta — do maila powitalnego i karty wejścia."""

    contact_id: Optional[int]
    contact_name: Optional[str]
    place: Optional[str]
    time: Optional[str]
    bring: Optional[str]


# ── Pakiet ────────────────────────────────────────────────────────────────────

#: Kto po naszej stronie pilnuje dostępu (podzbiór
#: ``hr_lifecycle_schema.TASK_ASSIGNEES`` — pilnuje test; bez przełożonego
#: i samej osoby, bo konsultant nie ma konta).
ACCESS_ASSIGNEES: tuple[str, ...] = (
    "care_owner",
    "delivery_lead",
    "administration",
    "it",
    "reception",
)
ASSIGNEE_LABELS: dict[str, str] = {
    "care_owner": "Opiekun",
    "delivery_lead": "Delivery Lead",
    "administration": "Administracja",
    "it": "IT",
    "reception": "Recepcja",
}
#: Dokumenty od konsultanta odhacza opiekun (O6).
DOCUMENT_ASSIGNEE = "care_owner"
MAX_ITEMS_PER_SECTION = 30
MAX_TITLE = 200
#: Części zapisu i sekcje wierszy, które każda z nich zastępuje.
PART_SECTIONS: dict[str, tuple[str, ...]] = {
    "equipment": ("equipment_ours", "equipment_client"),
    "first_day": (),
    "documents": ("document",),
    "accesses": ("access",),
}
_TIME = re.compile(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$")
VERSION_CONFLICT = (
    "Ktoś zmienił pakiet w międzyczasie — odśwież i wprowadź zmiany jeszcze raz."
)
PROVIDER_CONFLICT = (
    "Ktoś zmienił w międzyczasie, kto daje sprzęt konsultantom tego klienta — "
    "odśwież i wybierz jeszcze raz."
)
_LIVE_CONTRACT = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.active,
    ContractStatus.ending,
)


@dataclass(frozen=True)
class PackItem:
    name: str
    note: Optional[str] = None
    assignee: Optional[str] = None
    offset_days: Optional[int] = None
    required: bool = True
    requires_file: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "note": self.note,
            "assignee": self.assignee,
            "offset_days": self.offset_days,
            "required": self.required,
            "requires_file": self.requires_file,
        }


@dataclass(frozen=True)
class Pack:
    """Pakiet klienta. Klient bez zapisanego pakietu = ``exists=False``, puste listy."""

    client_id: int
    exists: bool
    version: int
    equipment_provider: str
    issue_template_id: Optional[int] = None
    return_template_id: Optional[int] = None
    first_day_contact_id: Optional[int] = None
    first_day_place: Optional[str] = None
    first_day_time: Optional[str] = None
    first_day_bring: Optional[str] = None
    equipment_ours: tuple[PackItem, ...] = ()
    equipment_client: tuple[PackItem, ...] = ()
    documents: tuple[PackItem, ...] = ()
    accesses: tuple[PackItem, ...] = ()
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None


def _clean(value: Any, limit: int) -> Optional[str]:
    joined = " ".join(str(value or "").split())
    if not joined:
        return None
    if len(joined) > limit:
        raise EquipmentError(
            f"Tekst jest dłuższy niż {limit} znaków: „{joined[:40]}…”."
        )
    return joined


def _cut(value: str, limit: int = MAX_TITLE) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def normalize_time(value: Any) -> Optional[str]:
    raw = _clean(value, 5)
    if raw is None:
        return None
    match = _TIME.match(raw)
    if match is None:
        raise EquipmentError("Godzinę wpisz jak 9:00 albo 13:30.")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _offset(value: Any, *, required: bool) -> Optional[int]:
    if value is None:
        if required:
            raise EquipmentError("Podaj termin względem startu.")
        return None
    number = int(value)
    if not -MAX_OFFSET_BEFORE <= number <= MAX_OFFSET_AFTER:
        raise EquipmentError(
            f"Termin musi mieścić się między {MAX_OFFSET_BEFORE} dniami roboczymi "
            f"przed startem a {MAX_OFFSET_AFTER} po starcie."
        )
    return number


def _items(section: str, rows: Sequence[Mapping[str, Any]]) -> list[PackItem]:
    if len(rows) > MAX_ITEMS_PER_SECTION:
        raise EquipmentError(
            f"Najwyżej {MAX_ITEMS_PER_SECTION} pozycji w jednej części pakietu."
        )
    out: list[PackItem] = []
    for row in rows:
        name = _clean(row.get("name"), 200)
        if name is None:
            raise EquipmentError("Każda pozycja pakietu potrzebuje nazwy.")
        note = _clean(row.get("note"), 300)
        if section in ("equipment_ours", "equipment_client"):
            out.append(PackItem(name=name, note=note, required=False))
        elif section == "document":
            out.append(
                PackItem(
                    name=name,
                    note=note,
                    offset_days=_offset(row.get("offset_days"), required=True),
                    required=bool(row.get("required", True)),
                    requires_file=bool(row.get("requires_file", False)),
                )
            )
        else:
            assignee = row.get("assignee") or DOCUMENT_ASSIGNEE
            if assignee not in ACCESS_ASSIGNEES:
                raise EquipmentError(
                    "Dostęp prowadzi opiekun, Delivery Lead, administracja, IT albo recepcja."
                )
            out.append(
                PackItem(
                    name=name,
                    note=note,
                    assignee=assignee,
                    offset_days=_offset(row.get("offset_days"), required=True),
                    required=bool(row.get("required", False)),
                )
            )
    return out


async def _pack_row(
    db: AsyncSession, client_id: int, *, for_update: bool = False
) -> Optional[ClientOnboardingPack]:
    query = select(ClientOnboardingPack).where(
        ClientOnboardingPack.client_id == client_id
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query)


async def load_pack(db: AsyncSession, client_id: int) -> Pack:
    """Pakiet klienta (nigdy ``None``: bez zapisu — ``exists=False``, puste listy)."""

    provider = await registry.client_provider(db, client_id)
    if provider is None:
        raise EquipmentNotFound("Nie ma takiego klienta.")
    row = await _pack_row(db, client_id)
    if row is None:
        return Pack(
            client_id=client_id, exists=False, version=0, equipment_provider=provider
        )
    items = (
        await db.scalars(
            select(ClientOnboardingPackItem)
            .where(ClientOnboardingPackItem.pack_id == row.id)
            .order_by(
                ClientOnboardingPackItem.section, ClientOnboardingPackItem.position
            )
        )
    ).all()
    by_section: dict[str, list[PackItem]] = {key: [] for key in schema.PACK_SECTIONS}
    for item in items:
        by_section[item.section].append(
            PackItem(
                name=item.name,
                note=item.note,
                assignee=item.assignee,
                offset_days=item.offset_days,
                required=item.required,
                requires_file=item.requires_file,
            )
        )
    sections = {key: tuple(value) for key, value in by_section.items()}
    return Pack(
        client_id=client_id,
        exists=True,
        version=row.version,
        equipment_provider=provider,
        issue_template_id=row.issue_template_id,
        return_template_id=row.return_template_id,
        first_day_contact_id=row.first_day_contact_id,
        first_day_place=row.first_day_place,
        first_day_time=row.first_day_time,
        first_day_bring=row.first_day_bring,
        equipment_ours=sections["equipment_ours"],
        equipment_client=sections["equipment_client"],
        documents=sections["document"],
        accesses=sections["access"],
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


async def _check_template(
    db: AsyncSession, template_id: Optional[int], kind: str, current: Optional[int]
) -> Optional[int]:
    if template_id is None:
        return None
    template = await db.get(EquipmentProtocolTemplate, template_id)
    if template is None or template.kind != kind:
        raise EquipmentError(
            "Wybierz wzór protokołu " + ("wydania." if kind == "wydanie" else "zwrotu.")
        )
    if not template.is_active and template_id != current:
        raise EquipmentError("Ten wzór protokołu jest wycofany — wybierz inny.")
    return template.id


async def _check_contact(
    db: AsyncSession, contact_id: Optional[int], client_id: int
) -> Optional[int]:
    if contact_id is None:
        return None
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.client_id != client_id:
        raise EquipmentError("Osoba odbierająca musi być kontaktem tego klienta.")
    return contact.id


async def save_pack(
    db: AsyncSession,
    client_id: int,
    changes: Mapping[str, Any],
    *,
    actor: User,
    expected_version: Optional[int] = None,
) -> Pack:
    """Zapisuje przesłane części pakietu (``equipment``, ``first_day``,
    ``documents``, ``accesses``); część nieprzesłana zostaje bez zmian."""

    parts = [part for part in PART_SECTIONS if part in changes]
    if not parts:
        raise EquipmentError("Nie ma nic do zapisania.")
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('client_onboarding_pack'), :id)"),
        {"id": client_id},
    )
    current_provider = await registry.client_provider(db, client_id)
    if current_provider is None:
        raise EquipmentNotFound("Nie ma takiego klienta.")
    row = await _pack_row(db, client_id, for_update=True)
    if (
        expected_version is not None
        and row is not None
        and row.version != expected_version
    ):
        raise EquipmentConflict(VERSION_CONFLICT)
    equipment = changes.get("equipment") or {}
    provider = equipment.get("provider")
    expected_provider = equipment.get("expected_provider")
    if (
        provider is not None
        and expected_provider is not None
        and expected_provider != current_provider
        and provider != current_provider
    ):
        raise EquipmentConflict(PROVIDER_CONFLICT)
    created = row is None
    if row is None:
        row = ClientOnboardingPack(client_id=client_id, version=1)
        db.add(row)
        await db.flush()

    new_items: dict[str, list[PackItem]] = {}
    if "equipment" in changes:
        if provider is not None and provider != current_provider:
            await registry.set_client_provider(db, client_id, provider, actor=actor)
        row.issue_template_id = await _check_template(
            db, equipment.get("issue_template_id"), "wydanie", row.issue_template_id
        )
        row.return_template_id = await _check_template(
            db, equipment.get("return_template_id"), "zwrot", row.return_template_id
        )
        new_items["equipment_ours"] = _items(
            "equipment_ours", equipment.get("ours") or []
        )
        new_items["equipment_client"] = _items(
            "equipment_client", equipment.get("client") or []
        )
    if "first_day" in changes:
        first = changes["first_day"] or {}
        row.first_day_contact_id = await _check_contact(
            db, first.get("contact_id"), client_id
        )
        row.first_day_place = _clean(first.get("place"), 300)
        row.first_day_time = normalize_time(first.get("time"))
        row.first_day_bring = _clean(first.get("bring"), 500)
    if "documents" in changes:
        new_items["document"] = _items("document", changes["documents"] or [])
    if "accesses" in changes:
        new_items["access"] = _items("access", changes["accesses"] or [])

    if new_items:
        await db.execute(
            delete(ClientOnboardingPackItem).where(
                ClientOnboardingPackItem.pack_id == row.id,
                ClientOnboardingPackItem.section.in_(list(new_items)),
            )
        )
        for section, rows in new_items.items():
            for position, item in enumerate(rows, start=1):
                db.add(
                    ClientOnboardingPackItem(
                        pack_id=row.id,
                        section=section,
                        position=position,
                        name=item.name,
                        note=item.note,
                        assignee=item.assignee,
                        offset_days=item.offset_days,
                        required=item.required,
                        requires_file=item.requires_file,
                    )
                )
    if not created:
        row.version += 1
    row.updated_by = actor.id
    await db.flush()
    record_client_audit(
        db,
        client_id=client_id,
        actor_id=actor.id,
        action="onboarding_pack_updated",
        details={"parts": parts, "version": row.version},
    )
    db.expire(row)
    return await load_pack(db, client_id)


async def template_for(
    db: AsyncSession, client_id: Optional[int], kind: str
) -> Optional[EquipmentProtocolTemplate]:
    """Wgrany wzór protokołu z pakietu klienta (``None`` = standard).

    Wycofany wzór nie trafia do nowych protokołów — wtedy standard.
    """

    if client_id is None:
        return None
    column = (
        ClientOnboardingPack.issue_template_id
        if kind == "wydanie"
        else ClientOnboardingPack.return_template_id
    )
    template_id = await db.scalar(
        select(column).where(ClientOnboardingPack.client_id == client_id)
    )
    if template_id is None:
        return None
    template = await db.get(EquipmentProtocolTemplate, template_id)
    if template is None or not template.is_active or template.kind != kind:
        return None
    return template


async def live_contract_count(db: AsyncSession, client_id: int) -> int:
    """Kontrakty klienta, które pakiet jeszcze dotyczy (przed startem i w trakcie)."""

    return int(
        await db.scalar(
            select(func.count())
            .select_from(Contract)
            .where(
                Contract.client_id == client_id,
                Contract.status.in_(_LIVE_CONTRACT),
                Contract.voided_at.is_(None),
            )
        )
        or 0
    )


async def options(db: AsyncSession, client_id: int, pack: Pack) -> dict[str, Any]:
    """Listy wyboru do edycji pakietu: wzory, kontakty klienta, wykonawcy."""

    selected = [t for t in (pack.issue_template_id, pack.return_template_id) if t]
    templates = (
        await db.execute(
            select(
                EquipmentProtocolTemplate.id,
                EquipmentProtocolTemplate.kind,
                EquipmentProtocolTemplate.name,
                EquipmentProtocolTemplate.description,
                EquipmentProtocolTemplate.is_active,
            )
            .where(
                EquipmentProtocolTemplate.is_active.is_(True)
                | EquipmentProtocolTemplate.id.in_(selected or [-1])
            )
            .order_by(EquipmentProtocolTemplate.kind, EquipmentProtocolTemplate.name)
        )
    ).all()
    contacts = (
        await db.execute(
            select(Contact.id, Contact.name, Contact.position)
            .where(Contact.client_id == client_id)
            .order_by(Contact.name, Contact.id)
        )
    ).all()
    return {
        "templates": [
            {
                "id": row.id,
                "kind": row.kind,
                "name": row.name,
                "description": row.description,
                "is_active": row.is_active,
            }
            for row in templates
        ],
        "contacts": [
            {"id": row.id, "name": row.name, "position": row.position}
            for row in contacts
        ],
        "assignees": [
            {"value": value, "label": ASSIGNEE_LABELS[value]}
            for value in ACCESS_ASSIGNEES
        ],
    }


def pack_payload(pack: Pack) -> dict[str, Any]:
    return {
        "client_id": pack.client_id,
        "exists": pack.exists,
        "version": pack.version,
        "updated_at": pack.updated_at.isoformat() if pack.updated_at else None,
        "updated_by": pack.updated_by,
        "equipment": {
            "provider": pack.equipment_provider,
            "issue_template_id": pack.issue_template_id,
            "return_template_id": pack.return_template_id,
            "ours": [item.as_dict() for item in pack.equipment_ours],
            "client": [item.as_dict() for item in pack.equipment_client],
        },
        "first_day": {
            "contact_id": pack.first_day_contact_id,
            "place": pack.first_day_place,
            "time": pack.first_day_time,
            "bring": pack.first_day_bring,
        },
        "documents": [item.as_dict() for item in pack.documents],
        "accesses": [item.as_dict() for item in pack.accesses],
    }


# ── Kontrakt dla ścieżki wejścia i maila powitalnego ─────────────────────────


def _joined(parts: Iterable[Optional[str]]) -> Optional[str]:
    text_value = " · ".join(part for part in parts if part)
    return text_value or None


async def pack_tasks(db: AsyncSession, client_id: int) -> list[PackTask]:
    """Zadania pakietu klienta dla nowego wejścia (pusty pakiet = ``[]``)."""

    try:
        pack = await load_pack(db, client_id)
    except EquipmentNotFound:
        return []
    if not pack.exists:
        return []
    tasks: list[PackTask] = [
        PackTask(
            title=_cut(item.name),
            description=_joined((item.note, "konsultant przysyła, odhacza opiekun")),
            assignee=DOCUMENT_ASSIGNEE,
            offset_days=item.offset_days or 0,
            required=item.required,
            requires_file=item.requires_file,
            category="documents",
        )
        for item in pack.documents
    ]
    tasks += [
        PackTask(
            title=_cut(item.name),
            description=item.note,
            assignee=item.assignee or DOCUMENT_ASSIGNEE,
            offset_days=item.offset_days or 0,
            required=item.required,
            requires_file=False,
            category="accounts",
        )
        for item in pack.accesses
    ]
    if pack.equipment_client:
        tasks.append(
            PackTask(
                title=_cut(
                    "Odbiór od klienta: "
                    + ", ".join(item.name for item in pack.equipment_client)
                ),
                description=_joined(item.note for item in pack.equipment_client),
                assignee=DOCUMENT_ASSIGNEE,
                offset_days=0,
                required=False,
                requires_file=False,
                category="equipment",
            )
        )
    return tasks


async def first_day(db: AsyncSession, contract_id: int) -> Optional[FirstDay]:
    """Pierwszy dzień konsultanta tego kontraktu albo ``None`` bez pakietu.

    Odbiera menedżer z kontraktu (``client_pm_contact_id``, osoba z drzewa
    klienta); bez niego — kontakt wskazany w pakiecie. Kontakt innego
    klienta (dane sprzed walidacji) nie jest brany.
    """

    contract = await db.get(Contract, contract_id)
    if contract is None or contract.client_id is None:
        return None
    try:
        pack = await load_pack(db, contract.client_id)
    except EquipmentNotFound:
        return None
    if not pack.exists:
        return None
    contact: Optional[Contact] = None
    for candidate_id in (contract.client_pm_contact_id, pack.first_day_contact_id):
        if candidate_id is None:
            continue
        found = await db.get(Contact, candidate_id)
        if found is not None and found.client_id == contract.client_id:
            contact = found
            break
    return FirstDay(
        contact_id=contact.id if contact else None,
        contact_name=contact.name if contact else None,
        place=pack.first_day_place,
        time=pack.first_day_time,
        bring=pack.first_day_bring,
    )
