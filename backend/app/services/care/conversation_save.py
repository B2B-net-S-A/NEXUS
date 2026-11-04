"""Okno „Rozmowa” (przebudowa opieki, 22.10.2026) — wszystko poza samą rozmową.

Zapis idzie w JEDNEJ transakcji żądania (sesja trasy commituje na końcu):
rozmowa (``records.add_conversation``) → karta technologiczna z „Co
u klienta” (tylko gdy przyszedł ``client_state``) → odpowiedzi na pytania
z mapy klienta → sprawy („Coś do załatwienia?”) → dzwonek popytu do DL
(rozmowa z „klient zatrudnia”). Błąd walidacji którejkolwiek części
cofa całość — nie zostaje rozmowa bez karty albo sprawa bez rozmowy.

* **Karta z rozmowy** = ostatni stan (ostatnia sfinalizowana karta
  kontraktu) + zmiany z okna; „bez zmian” (``confirmed`` bez ``changes``)
  zapisuje świeże źródło z tym samym stanem. Karta jest sfinalizowana
  (status „OK”) i wie, z której rozmowy powstała
  (``tech_cards.care_conversation_id``). Bez żadnej technologii karty nie
  ma — rozmowa zapisuje się bez niej (karta „OK” wymaga technologii, reguła
  ``records.save_tech_card``); bez stanu i bez zmian nic się nie zapisuje.
* **Menedżer konsultanta** z „Co u klienta” trafia na kontrakt, gdy kontrakt
  go nie ma; innego menedżera zmienia tylko DL klienta albo admin (ta sama
  reguła co akcept propozycji) — inaczej zostaje stary
  (``manager_kept: true`` w odpowiedzi).
* **Świeżość „Co u klienta”** (makieta P3): wiersz nieruszony = „bez zmian”
  i potwierdzony datą rozmowy — front wysyła ``rows`` ze stanem każdego
  wiersza, karta z rozmowy dostaje datę rozmowy, a ślad
  ``care.client_state_confirmed`` mówi, które wiersze potwierdzono, a które
  zmieniono.
* **Odpowiedzi na luki**: „komu podlega” → ``client_people.update_contact_org``
  (prawo edycji kontaktów klienta, inaczej 403 przed zapisem czegokolwiek);
  notatka przy tym pytaniu zapisuje się zawsze jako ogólna notatka o kliencie
  (``reports_to_note``) — także bez wybranej osoby,
  technologie działu → notatka o stacku klienta (wiedza o kliencie, którą
  czyta mapa) z nazwami ze słownika; nazwy spoza słownika idą do kolejki
  „Nazwy z rozmów do przejrzenia”.
* **Klient zatrudnia**: role i źródło z górnego poziomu ciała zapisują się
  przy rozmowie (``care_conversations.client_hiring_roles/source``) — także
  bez „Co u klienta”, gdy karta się nie zapisuje; popyt bierze je, gdy
  rozmowa nie ma karty. Puste ``client_hiring_note`` dostaje role tekstem.
* **Sprawy**: najwyżej 5 z rozmowy i 20 z rozmów na osobę na dobę, przez
  ``admin_cases.service.create_case`` z kontraktem; opis = link do rozmowy
  i notatka z rozmowy (makieta S5: „opis z notatki”; opieka nie zbiera stawek
  ani danych o zdrowiu, więc notatka ich nie niesie). Zapisujący opiekę bez uprawnienia
  „Sprawy” (``is_handler``) zakłada sprawę tylko bez osoby (trafia do „Bez
  osoby” u obsługi) albo przypisaną do siebie i nigdy w obszarze
  „Negocjacje” (audyt bezpieczeństwa 22.10.2026 — dzwonki do dowolnych osób).

Bez danych o zdrowiu i bez stawek — jak cała opieka.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.admin_case import AdminCase
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.contract_care import CareConversation, ClientArea, TechCard
from app.models.skill import Skill
from app.models.user import User, UserRole
from app.services import contract_client_manager
from app.services.care import access as care_access
from app.services.care import card as care_card
from app.services.care import client_people, demand, records
from app.services.care import skills as care_skills
from app.services.care.access import CareContract
from app.services.care.demand import CONVERSATIONS_HIRING, TECH_CARDS_LINK, clean_roles
from app.services.care.week import client_managers
from app.services.client_access import record_client_audit, resolve_client_access
from app.services.contract_care_schema import NAME_MAX, SHORT_TEXT_MAX
from app.services.hr import audit

MAX_CASES = 5
#: Sprawy z rozmów jednej osoby w dobie kalendarza firmy.
MAX_CASES_PER_DAY = 20
#: Początek opisu sprawy z rozmowy — po nim liczy się dzienny limit.
CASE_DESCRIPTION_PREFIX = "Z rozmowy opiekuna z konsultantem "
_UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_ENTITY

UNKNOWN_GAP = "Nie ma takiego pytania z mapy klienta."
ORG_DENIED = (
    "„Komu podlega” zapisuje osoba z prawem edycji kontaktów klienta — "
    "usuń tę odpowiedź albo poproś Delivery Leada klienta."
)
CASES_OFF = "Moduł „Sprawy” nie jest włączony — usuń sprawy z rozmowy."
TOO_MANY_CASES = f"Z jednej rozmowy założysz najwyżej {MAX_CASES} spraw."
TOO_MANY_CASES_TODAY = (
    f"Dziś założono już z rozmów {MAX_CASES_PER_DAY} spraw — kolejne załóż "
    "jutro albo poproś obsługę Spraw."
)
CASE_ASSIGNEE_DENIED = (
    "Sprawę z rozmowy możesz zostawić bez osoby (przydzieli obsługa Spraw) "
    "albo wziąć na siebie — innej osobie przydziela obsługa."
)
CASE_AREA_DENIED = "Sprawę w obszarze „Negocjacje” zakłada obsługa Spraw."


@dataclass(frozen=True)
class GapAnswer:
    key: str
    reports_to_contact_id: Optional[int] = None
    skill_ids: tuple[int, ...] = ()
    new_skill_names: tuple[str, ...] = ()
    note: Optional[str] = None


@dataclass(frozen=True)
class CaseRequest:
    title: str
    area: str
    assignee_user_id: Optional[int] = None
    due_on: Optional[date] = None


@dataclass
class Extras:
    """Część okna „Rozmowa” poza rozmową (wszystko opcjonalne)."""

    #: ``{"confirmed": bool, "changes": {...}}``; ``changes`` niesie tylko
    #: wysłane pola (``None`` ≠ brak pola — np. koniec projektu „nie wiem”).
    client_state: Optional[dict[str, Any]] = None
    gap_answers: Sequence[GapAnswer] = field(default_factory=tuple)
    cases: Sequence[CaseRequest] = field(default_factory=tuple)
    #: „Klient zatrudnia” (górny poziom ciała) — role i źródło informacji.
    hiring_roles: Sequence[str] = field(default_factory=tuple)
    hiring_source: Optional[str] = None


@dataclass
class Saved:
    tech_card_id: Optional[int] = None
    case_ids: list[int] = field(default_factory=list)
    demand_notified: int = 0
    manager_kept: bool = False


def month_end(value: str) -> date:
    """„YYYY-MM” → ostatni dzień miesiąca (koniec projektu na karcie)."""

    try:
        year, month = (int(part) for part in value.split("-", 1))
        return date(year, month, calendar.monthrange(year, month)[1])
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            _UNPROCESSABLE, "Koniec projektu podaj jako miesiąc RRRR-MM."
        ) from exc


def parse_gap_key(key: str) -> tuple[str, int]:
    kind, _, raw = (key or "").partition(":")
    if kind not in {"reports_to", "area", "single", "category"} or not raw.isdigit():
        raise HTTPException(_UNPROCESSABLE, UNKNOWN_GAP)
    if kind == "category" and int(raw) >= len(care_card.CATEGORY_GROUPS):
        raise HTTPException(_UNPROCESSABLE, UNKNOWN_GAP)
    return kind, int(raw)


#: Wiersze „Co u klienta” w śladzie potwierdzenia (lustro ``ClientStateRow``).
CLIENT_STATE_ROWS = (
    "area",
    "manager",
    "team",
    "technologies",
    "vendors",
    "project_end",
)


def confirmed_rows(rows: Optional[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(potwierdzone bez zmian, zmienione) wiersze — w stałej kolejności okna."""

    rows = rows or {}
    same = [row for row in CLIENT_STATE_ROWS if rows.get(row) == "same"]
    changed = [row for row in CLIENT_STATE_ROWS if rows.get(row) == "change"]
    return same, changed


#: Notatka z rozmowy w opisie sprawy — tyle znaków (reszta zostaje w rozmowie).
CASE_NOTE_MAX = 2000


def case_description(occurred_on: date, contract_id: int, note: Optional[str]) -> str:
    """Opis sprawy z rozmowy: prefiks limitu dziennego, link do rozmowy, notatka."""

    text = (
        CASE_DESCRIPTION_PREFIX
        + f"{occurred_on.strftime('%d.%m.%Y')}: /care?contract={contract_id}"
    )
    cleaned = (note or "").replace("\x00", "").strip()
    if not cleaned:
        return text
    if len(cleaned) > CASE_NOTE_MAX:
        cleaned = cleaned[: CASE_NOTE_MAX - 1].rstrip() + "…"
    return f"{text}\n\nNotatka z rozmowy:\n{cleaned}"


# ── Walidacja przed zapisem ─────────────────────────────────────────────────


def case_request_problem(
    request: CaseRequest, *, actor_id: int, handler: bool
) -> Optional[str]:
    """Odmowa sprawy z rozmowy dla zapisującego bez uprawnienia „Sprawy”."""

    if handler:
        return None
    if request.area == "negotiation":
        return CASE_AREA_DENIED
    if request.assignee_user_id not in (None, actor_id):
        return CASE_ASSIGNEE_DENIED
    return None


def over_daily_limit(already_today: int, adding: int) -> bool:
    return already_today + adding > MAX_CASES_PER_DAY


async def cases_opened_today(db: AsyncSession, user_id: int) -> int:
    """Sprawy z rozmów założone dziś (kalendarz firmy) przez tę osobę."""

    start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        await db.scalar(
            select(func.count(AdminCase.id)).where(
                AdminCase.created_by == user_id,
                AdminCase.created_at >= start,
                AdminCase.description.like(f"{CASE_DESCRIPTION_PREFIX}%"),
            )
        )
        or 0
    )


async def precheck(
    db: AsyncSession, contract: CareContract, extras: Extras, *, user: User
) -> None:
    """Odmowy, które muszą paść, zanim cokolwiek się zapisze."""

    if len(extras.cases) > MAX_CASES:
        raise HTTPException(_UNPROCESSABLE, TOO_MANY_CASES)
    if extras.cases:
        from app.services.admin_cases import service as cases_service  # noqa: PLC0415

        if not await cases_service.module_enabled(db):
            raise HTTPException(status.HTTP_409_CONFLICT, CASES_OFF)
        handler = cases_service.is_handler(user)
        for request in extras.cases:
            problem = case_request_problem(request, actor_id=user.id, handler=handler)
            if problem:
                raise HTTPException(status.HTTP_403_FORBIDDEN, problem)
        if over_daily_limit(await cases_opened_today(db, user.id), len(extras.cases)):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_CASES_TODAY)
    needs_org = False
    for answer in extras.gap_answers:
        kind, _ = parse_gap_key(answer.key)
        if kind == "reports_to" and answer.reports_to_contact_id is not None:
            needs_org = True
    if needs_org:
        access = await resolve_client_access(db, user, contract.client_id)
        if not access.can_edit_contacts:
            raise HTTPException(status.HTTP_403_FORBIDDEN, ORG_DENIED)


# ── Karta z rozmowy ─────────────────────────────────────────────────────────


async def _may_replace_manager(db: AsyncSession, user: User, client_id: int) -> bool:
    if user.has_role(UserRole.admin):
        return True
    if not user.has_role(UserRole.delivery_lead):
        return False
    scope = await care_access.allowed_client_ids(user, db)
    return scope is None or client_id in scope


async def _set_manager(
    db: AsyncSession,
    contract: CareContract,
    contact_id: int,
    *,
    user: User,
) -> bool:
    """Menedżer z rozmowy na kontrakt; ``False`` = został poprzedni."""

    await contract_client_manager.assert_contact_of_client(
        db, contact_id=contact_id, client_id=contract.client_id
    )
    row = await db.get(Contract, contract.id, with_for_update=True)
    current = row.client_pm_contact_id
    if current == contact_id:
        return True
    if current is not None and not await _may_replace_manager(
        db, user, contract.client_id
    ):
        return False
    row.client_pm_contact_id = contact_id
    audit.record(
        db,
        actor_user_id=user.id,
        subject_user_id=None,
        entity_type="contract",
        entity_id=contract.id,
        action="care.client_manager_set",
        details={
            "client_id": contract.client_id,
            "contact_id": contact_id,
            "previous_contact_id": current,
            "source": "conversation",
        },
    )
    record_client_audit(
        db,
        client_id=contract.client_id,
        actor_id=user.id,
        action="client_managers_set",
        details={"contract_ids": [contract.id], "source": "conversation"},
    )
    return True


async def save_client_state(
    db: AsyncSession,
    contract: CareContract,
    conversation: CareConversation,
    client_state: dict[str, Any],
    *,
    user: User,
    today: date,
    now: datetime,
) -> tuple[Optional[int], bool]:
    """Karta z rozmowy (ostatni stan + zmiany). Zwraca (id karty, menedżer został)."""

    changes: dict[str, Any] = dict(client_state.get("changes") or {})
    base = await care_card.latest_card(db, contract.id)
    manager_kept = False
    if changes.get("manager_contact_id") is not None:
        manager_kept = not await _set_manager(
            db, contract, int(changes["manager_contact_id"]), user=user
        )
    # Sama zmiana menedżera nie robi karty (menedżer żyje na kontrakcie).
    if base is None and not set(changes) - {"manager_contact_id"}:
        return None, manager_kept

    base_skills: list[int] = []
    base_vendors: list[int] = []
    if base is not None:
        skills, vendors = await records.card_relations(db, [base.id])
        base_skills = skills.get(base.id, [])
        base_vendors = vendors.get(base.id, [])

    skill_ids = list(changes["skill_ids"]) if "skill_ids" in changes else base_skills
    new_names = [
        name.strip()[:NAME_MAX]
        for name in changes.get("new_skill_names") or []
        if name and name.strip()
    ]
    # Karta „OK” wymaga technologii; bez niej rozmowa zapisuje się bez karty
    # (opiekun nie traci rozmowy przez puste „Co u klienta”).
    if not skill_ids and not new_names:
        return None, manager_kept

    if "vendors" in changes:
        vendor_ids: list[int] = []
        new_vendor_names = [
            name.strip()[:NAME_MAX]
            for name in changes.get("vendors") or []
            if name and name.strip()
        ]
    else:
        vendor_ids, new_vendor_names = base_vendors, []

    if "area_id" in changes or changes.get("new_area_name"):
        area_id = changes.get("area_id")
        new_area_name = changes.get("new_area_name")
    else:
        area_id = base.client_area_id if base is not None else None
        new_area_name = None

    if "hiring_roles" in changes:
        roles = [r for r in changes.get("hiring_roles") or [] if r and r.strip()]
        hiring = bool(roles) or conversation.client_hiring
        hiring_source = changes.get("hiring_source") if hiring else None
    else:
        # „Klient zatrudnia” to zdarzenie tej rozmowy, nie stan karty: bez
        # zaznaczenia nowa karta nie dziedziczy popytu (audyt 22.10, F1).
        hiring = conversation.client_hiring
        roles = list(base.hiring_roles or []) if base is not None and hiring else []
        hiring_source = (
            (changes.get("hiring_source") or (base.hiring_source if base else None))
            if hiring
            else None
        )

    if "project_end_month" in changes:
        month = changes.get("project_end_month")
        project_end_on = month_end(month) if month else None
        project_end_unknown = month is None
    elif base is not None:
        project_end_on = base.project_end_on
        project_end_unknown = base.project_end_unknown
    else:
        project_end_on, project_end_unknown = None, False

    def pick(name: str, base_value: Any) -> Any:
        return changes[name] if name in changes else base_value

    card = await records.save_tech_card(
        db,
        contract,
        records.TechCardInput(
            interview_on=conversation.occurred_on,
            finalize=True,
            status="ok",
            satisfaction=conversation.satisfaction,
            client_area_id=None if new_area_name else area_id,
            new_area_name=new_area_name,
            skill_ids=tuple(skill_ids),
            skill_names=tuple(new_names),
            vendor_ids=tuple(vendor_ids),
            new_vendor_names=tuple(new_vendor_names),
            hiring=True if hiring else None,
            hiring_source=hiring_source,
            hiring_roles=tuple(roles),
            project_end_on=project_end_on,
            project_end_unknown=project_end_unknown,
            team_size=pick("team_size", base.team_size if base else None),
            team_externals=pick(
                "team_externals", base.team_externals if base else None
            ),
            initiatives=tuple(base.initiatives or []) if base is not None else (),
        ),
        actor_id=user.id,
        today=today,
        now=now,
    )
    await db.execute(
        update(TECH_CARDS_LINK)
        .where(TECH_CARDS_LINK.c.id == card.id)
        .values(care_conversation_id=conversation.id)
    )
    return card.id, manager_kept


# ── Odpowiedzi na luki ──────────────────────────────────────────────────────


async def _skill_names(db: AsyncSession, skill_ids: Sequence[int]) -> list[str]:
    ids = sorted(set(skill_ids))
    if not ids:
        return []
    rows = (
        await db.execute(
            select(Skill.id, Skill.canonical_name).where(Skill.id.in_(ids))
        )
    ).all()
    if len(rows) != len(ids):
        raise HTTPException(
            _UNPROCESSABLE, "Część technologii nie istnieje w słowniku."
        )
    return sorted(
        (care_skills.display_name(name) for _sid, name in rows), key=str.casefold
    )


def reports_to_note(
    occurred_on: date, contact_name: str, note: Optional[str]
) -> Optional[str]:
    """Treść notatki o kliencie z odpowiedzi „Komu podlega …?” (pusta = ``None``)."""

    cleaned = " ".join((note or "").split())
    if not cleaned:
        return None
    return (
        f"Z rozmowy z konsultantem {occurred_on.strftime('%d.%m.%Y')} "
        f"(komu podlega {contact_name}): {cleaned}"
    )


async def apply_gap_answers(
    db: AsyncSession,
    contract: CareContract,
    answers: Sequence[GapAnswer],
    *,
    actor_id: int,
    occurred_on: date,
) -> int:
    """Zapisuje odpowiedzi; zwraca liczbę zapisanych (pustych nie liczymy)."""

    saved = 0
    for answer in answers:
        kind, subject_id = parse_gap_key(answer.key)
        if kind == "reports_to":
            if answer.reports_to_contact_id is not None:
                await client_people.update_contact_org(
                    db,
                    client_id=contract.client_id,
                    contact_id=subject_id,
                    changes={"reports_to_contact_id": answer.reports_to_contact_id},
                    actor_id=actor_id,
                )
                saved += 1
            if " ".join((answer.note or "").split()):
                contact_name = await db.scalar(
                    select(Contact.name).where(
                        Contact.id == subject_id,
                        Contact.client_id == contract.client_id,
                    )
                )
                if contact_name is None:
                    raise HTTPException(_UNPROCESSABLE, UNKNOWN_GAP)
                db.add(
                    ClientKnowledge(
                        client_id=contract.client_id,
                        category=KnowledgeCategory.general,
                        content=reports_to_note(occurred_on, contact_name, answer.note),
                        added_by=actor_id,
                        source="care",
                    )
                )
                saved += 1
            continue
        names = await _skill_names(db, answer.skill_ids)
        extra = [
            name.strip()[:NAME_MAX]
            for name in answer.new_skill_names
            if name and name.strip()
        ]
        if extra:
            # Nazwy spoza słownika czekają w kolejce jak z karty technologicznej.
            resolved = await care_skills.resolve_card_names(
                db, extra, previous_unrecognized=[], actor_id=actor_id
            )
            names += await _skill_names(db, sorted(resolved.skill_ids))
            names += resolved.unrecognized
        note = " ".join((answer.note or "").split())
        if not names and not note:
            continue
        where = ""
        if kind == "category":
            where = f" ({care_card.CATEGORY_GROUPS[subject_id][0]})"
        if kind == "area":
            area_name = await db.scalar(
                select(ClientArea.name).where(
                    ClientArea.id == subject_id,
                    ClientArea.client_id == contract.client_id,
                )
            )
            if area_name is None:
                raise HTTPException(_UNPROCESSABLE, UNKNOWN_GAP)
            where = f" (dział {area_name})"
        parts = [f"Z rozmowy z konsultantem {occurred_on.strftime('%d.%m.%Y')}{where}:"]
        if names:
            parts.append(", ".join(dict.fromkeys(names)) + ".")
        if note:
            parts.append(note)
        db.add(
            ClientKnowledge(
                client_id=contract.client_id,
                category=KnowledgeCategory.tech_stack,
                content=" ".join(parts),
                added_by=actor_id,
                source="care",
            )
        )
        saved += 1
    await db.flush()
    return saved


# ── Sprawy ──────────────────────────────────────────────────────────────────


async def open_cases(
    db: AsyncSession,
    contract: CareContract,
    conversation: CareConversation,
    requests: Sequence[CaseRequest],
    *,
    actor: User,
) -> list[int]:
    from app.services.admin_cases import service as cases_service  # noqa: PLC0415

    ids: list[int] = []
    for request in requests:
        try:
            case = await cases_service.create_case(
                db,
                actor=actor,
                values={
                    "title": request.title,
                    "area": request.area,
                    "assignee_user_id": request.assignee_user_id,
                    "due_on": request.due_on,
                    "contract_id": contract.id,
                    "description": case_description(
                        conversation.occurred_on, contract.id, conversation.note
                    ),
                },
            )
        except cases_service.CaseError as exc:
            raise HTTPException(_UNPROCESSABLE, str(exc)) from exc
        ids.append(case.id)
    return ids


# ── Popyt ───────────────────────────────────────────────────────────────────


async def save_hiring(
    db: AsyncSession,
    conversation: CareConversation,
    roles: Sequence[str],
    source: Optional[str],
) -> list[str]:
    """Role i źródło „klient zatrudnia” przy rozmowie; zwraca oczyszczone role."""

    cleaned = clean_roles(roles)
    if not conversation.client_hiring or (not cleaned and source is None):
        return cleaned
    await db.execute(
        update(CONVERSATIONS_HIRING)
        .where(CONVERSATIONS_HIRING.c.id == conversation.id)
        .values(client_hiring_roles=cleaned or None, client_hiring_source=source)
    )
    if cleaned and not (conversation.client_hiring_note or "").strip():
        conversation.client_hiring_note = ", ".join(cleaned)[:SHORT_TEXT_MAX]
    return cleaned


async def _demand_area(
    db: AsyncSession, contract: CareContract, tech_card_id: Optional[int]
) -> Optional[tuple[int, str]]:
    area_id: Optional[int] = None
    if tech_card_id is not None:
        area_id = await db.scalar(
            select(TechCard.client_area_id).where(TechCard.id == tech_card_id)
        )
    if area_id is None:
        manager = (await client_managers(db, [contract])).get(contract.id)
        if manager and manager.get("area"):
            return manager["area"]["id"], manager["area"]["name"]
        return None
    name = await db.scalar(select(ClientArea.name).where(ClientArea.id == area_id))
    return (area_id, name) if name is not None else None


async def notify_demand(
    db: AsyncSession,
    contract: CareContract,
    conversation: CareConversation,
    *,
    tech_card_id: Optional[int],
    actor_id: int,
    now: datetime,
    conversation_roles: Sequence[str] = (),
) -> int:
    if not conversation.client_hiring:
        return 0
    roles: list[str] = list(conversation_roles)
    if tech_card_id is not None:
        roles = list(
            await db.scalar(
                select(TechCard.hiring_roles).where(TechCard.id == tech_card_id)
            )
            or roles
        )
    return await demand.notify_leads(
        db,
        conversation=conversation,
        contract=contract,
        area=await _demand_area(db, contract, tech_card_id),
        roles=roles,
        actor_id=actor_id,
        now=now,
    )


async def save_extras(
    db: AsyncSession,
    contract: CareContract,
    conversation: CareConversation,
    extras: Extras,
    *,
    user: User,
    today: date,
    now: datetime,
) -> Saved:
    saved = Saved()
    if extras.client_state is not None:
        saved.tech_card_id, saved.manager_kept = await save_client_state(
            db,
            contract,
            conversation,
            extras.client_state,
            user=user,
            today=today,
            now=now,
        )
        same, changed = confirmed_rows(extras.client_state.get("rows"))
        if same or changed:
            audit.record(
                db,
                actor_user_id=user.id,
                subject_user_id=None,
                entity_type="contract",
                entity_id=contract.id,
                action="care.client_state_confirmed",
                details={
                    "conversation_id": conversation.id,
                    "tech_card_id": saved.tech_card_id,
                    "on": conversation.occurred_on.isoformat(),
                    "confirmed": same,
                    "changed": changed,
                },
            )
    await apply_gap_answers(
        db,
        contract,
        extras.gap_answers,
        actor_id=user.id,
        occurred_on=conversation.occurred_on,
    )
    saved.case_ids = await open_cases(
        db, contract, conversation, extras.cases, actor=user
    )
    hiring_roles = await save_hiring(
        db, conversation, extras.hiring_roles, extras.hiring_source
    )
    saved.demand_notified = await notify_demand(
        db,
        contract,
        conversation,
        tech_card_id=saved.tech_card_id,
        actor_id=user.id,
        now=now,
        conversation_roles=hiring_roles,
    )
    return saved
