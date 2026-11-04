"""Edycja Akademii od strony recepcji (etap 5 propozycji sprzętu, makieta „I”).

Edycja = program i miesiąc startu (``academy_applications.cohort_month``,
pierwszy dzień miesiąca); ``academy_sessions`` to terminy spotkań w biurze,
nie edycje. Do edycji przypięta jest check lista ``academy_edition_checklist``.
Uczestnik = zgłoszenie z tym ``cohort_month``, które zaliczyło zadanie — albo
odpadło po nim (rezygnacja, wykluczenie), albo ma u siebie sprzęt. Osoby przed
podpisem (zaliczone zadanie, wysłana umowa) nie mają jeszcze ``cohort_month``
— są w najbliższej edycji (``next_cohort``, ta sama reguła co daty programu
w dokumentach). Wiersz uczestnika składa
się z tego, co NEXUS już wie: status zgłoszenia, umowa (wysłana, podpisana,
komplet dokumentów z ``academy_documents``), hotel i bilet
(``academy_participant_logistics``), zestaw (aktywne wydania sprzętu) i protokół
wydania. PESEL i adres zostają w pliku umowy — tu ich nie ma.

Check lista to wzór recepcji (9 sekcji, 70 punktów) zapisany w kodzie
z kluczami ``item_key``. ``ensure_checklist`` zakłada brakujące punkty edycji
i nie rusza istniejących (odhaczenia, notatki ani etykiety), więc nowy punkt
wzoru dopisuje się do starych edycji przy pierwszym odczycie.

Haki zmiany statusu zgłoszenia (``on_status_changed``, woła je
``services/academy.perform_action``) biegną w savepoincie i tylko przy
włączonym module „Sprzęt”: awaria tej części nie blokuje zmiany statusu.

* ``signed`` → zadanie recepcji „wydanie” (``academy:<id>:kit``) z terminem
  ``KIT_LEAD_WORKDAYS`` dni roboczych przed startem programu,
* ``withdrew`` / ``rejected`` po zaliczonym zadaniu → hotel i bilet
  „zrobione” przechodzą na „do anulowania”, „do zrobienia” na „nie dotyczy”,
  otwarte zadanie wydania jest anulowane, a gdy osoba ma rzeczy — zadanie
  „zwrot” (``academy:<id>:return``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.academy import AcademyApplication, AcademyProgram
from app.models.academy_logistics import (
    AcademyEditionChecklistItem,
    AcademyParticipantLogistics,
)
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentItem,
    EquipmentModel,
    EquipmentProtocol,
    EquipmentTask,
)
from app.models.user import User
from app.services.academy_documents import program_dates
from app.services.academy_flow import STATUS_LABELS, next_cohort
from app.services.equipment import issuing, protocols, sanitize
from app.services.equipment import tasks as equipment_tasks
from app.services.equipment.registry import (
    EquipmentError,
    EquipmentNotFound,
    academy_participant_name,
)
from app.services.equipment_extras_schema import LOGISTICS_STATUSES

logger = logging.getLogger(__name__)

#: Ile dni roboczych przed startem programu recepcja ma gotowy zestaw.
KIT_LEAD_WORKDAYS = 3
#: Zgłoszenia, które są uczestnikami edycji (po zaliczonym zadaniu).
EDITION_STATUSES: tuple[str, ...] = ("task_passed", "contract_sent", "signed")
#: Uczestnicy przed podpisem — bez ``cohort_month``, liczeni do najbliższej edycji.
PENDING_STATUSES: tuple[str, ...] = ("task_passed", "contract_sent")
#: Wyjścia z programu — po zaliczonym zadaniu osoba zostaje w edycji jako „odpadła”.
LEFT_STATUSES: tuple[str, ...] = ("withdrew", "rejected")
NOTE_MAX = 500
EDITIONS_LIMIT = 60


class EditionNotFound(EquipmentNotFound):
    """Nie ma takiej akademii, punktu listy albo uczestnika edycji."""


@dataclass(frozen=True)
class Edition:
    """Edycja = program i pierwszy dzień miesiąca startu."""

    program: AcademyProgram
    cohort_month: date

    @property
    def key(self) -> str:
        return f"{self.cohort_month:%Y-%m}"


def pending_cohort() -> date:
    """Edycja, do której liczą się osoby przed podpisem (jak daty w dokumentach)."""
    return next_cohort(business_today())


# ── Wzór check listy (recepcja, 9 sekcji) ─────────────────────────────────────


@dataclass(frozen=True)
class ChecklistSection:
    key: str
    label: str
    items: tuple[tuple[str, str], ...]


#: Wzór check listy recepcji. Klucze są stałe (odhaczenia trzymają się klucza);
#: nowy punkt dopisuj na końcu sekcji z nowym kluczem, a etykiety zmieniaj
#: świadomie — istniejące edycje zachowują etykietę z chwili założenia.
CHECKLIST_TEMPLATE: tuple[ChecklistSection, ...] = (
    ChecklistSection(
        "informacje",
        "Informacje od prowadzącej",
        (
            (
                "info_start",
                "Otrzymać od prowadzącej informację, czy rusza kolejna edycja",
            ),
            ("info_date", "Otrzymać termin rozpoczęcia edycji"),
            ("info_count", "Otrzymać liczbę uczestników"),
            ("info_list", "Otrzymać imienną listę uczestników"),
            ("info_contract_data", "Otrzymać dane potrzebne do przygotowania umów"),
            (
                "info_travel_needs",
                "Sprawdzić, kto potrzebuje hotelu i biletu kolejowego",
            ),
            ("info_final_group", "Potwierdzić z prowadzącą ostateczny skład grupy"),
        ),
    ),
    ChecklistSection(
        "hotel_bilety",
        "Hotel i bilety",
        (
            ("travel_hotel_book", "Zarezerwować hotel dla uczestników"),
            ("travel_tickets_buy", "Kupić bilety kolejowe"),
            ("travel_hotel_send", "Wysłać każdej osobie potwierdzenie hotelu"),
            ("travel_tickets_send", "Wysłać każdej osobie bilet kolejowy"),
            ("travel_files", "Zapisać rezerwacje i bilety w folderze edycji"),
            (
                "travel_recheck",
                "Przed startem ponownie sprawdzić, czy skład grupy się nie zmienił",
            ),
        ),
    ),
    ChecklistSection(
        "umowy",
        "Umowy i dokumentacja",
        (
            ("contracts_prepare", "Przygotować umowę dla każdego uczestnika"),
            ("contracts_check", "Sprawdzić poprawność danych w umowach"),
            ("contracts_print", "Wydrukować umowy"),
            (
                "contracts_to_sign",
                "Przekazać umowy do podpisu osobie reprezentującej firmę",
            ),
            ("contracts_back", "Odebrać umowy podpisane przez firmę"),
            ("contracts_participants", "Dopilnować podpisania umów przez uczestników"),
            ("contracts_scan", "Zeskanować podpisane dokumenty"),
            ("contracts_save", "Zapisać skany w folderze edycji na dysku"),
            ("contracts_copy", "Przekazać egzemplarz umowy uczestnikowi"),
            ("contracts_billing", "Przekazać egzemplarz do rozliczeń"),
        ),
    ),
    ChecklistSection(
        "dostepy",
        "Dostępy",
        (
            ("access_grant", "Zlecić albo nadać potrzebne dostępy"),
            ("access_check", "Przed startem sprawdzić, czy wszystkie dostępy działają"),
            ("access_first_login", "Przygotować dane do pierwszego logowania"),
        ),
    ),
    ChecklistSection(
        "materialy",
        "Materiały",
        (
            ("materials_count", "Sprawdzić liczbę potrzebnych kompletów"),
            ("materials_book_print", "Wydrukować książkę Akademii"),
            ("materials_book_bind", "Złożyć i spiąć albo oprawić książki"),
            ("materials_exercises_print", "Wydrukować ćwiczenia"),
            ("materials_exercises_bind", "Złożyć i spiąć ćwiczenia"),
            ("materials_notebook", "Przygotować notes dla każdej osoby"),
            ("materials_pen", "Przygotować długopis dla każdej osoby"),
            (
                "materials_name_card",
                "Przygotować karteczkę z imieniem dla każdej osoby",
            ),
            ("materials_sets", "Skompletować zestaw materiałów dla każdego uczestnika"),
        ),
    ),
    ChecklistSection(
        "sprzet",
        "Sprzęt",
        (
            (
                "kit_availability",
                "Sprawdzić dostępność sprzętu dla wszystkich uczestników",
            ),
            ("kit_laptops", "Przygotować laptopy"),
            ("kit_phones", "Przygotować telefony"),
            ("kit_headsets", "Przygotować słuchawki"),
            ("kit_mice", "Przygotować myszki"),
            ("kit_chargers", "Przygotować zasilacze"),
            ("kit_mousepads", "Przygotować podkładki pod mysz"),
            ("kit_register", "Wpisać sprzęt i numery urządzeń do ewidencji"),
            (
                "kit_protocols",
                "Przygotować protokół przekazania sprzętu dla każdej osoby",
            ),
            ("kit_protocols_print", "Wydrukować protokoły"),
        ),
    ),
    ChecklistSection(
        "sala",
        "Sala i rozpoczęcie",
        (
            ("room_book", "Zarezerwować salę na cały okres edycji"),
            ("room_seats", "Sprawdzić liczbę przygotowanych stanowisk"),
            ("room_kit", "Rozłożyć sprzęt na stanowiskach"),
            (
                "room_materials",
                "Rozłożyć książki, ćwiczenia, notesy, długopisy i karteczki z imionami",
            ),
            ("room_handover", "Przekazać uczestnikom sprzęt"),
            ("room_protocols", "Dopilnować podpisania protokołów"),
            ("room_first_login", "Pomóc uczestnikom w pierwszym logowaniu"),
            (
                "room_walkthrough",
                "Wyjaśnić krok po kroku korzystanie ze sprzętu, systemów i dostępów",
            ),
        ),
    ),
    ChecklistSection(
        "rezygnacje",
        "Rezygnacje",
        (
            ("resign_info", "Otrzymać od prowadzącej informację o zmianie"),
            ("resign_list", "Zaktualizować listę uczestników"),
            ("resign_hotel", "Anulować albo zmienić rezerwację hotelu"),
            ("resign_ticket", "Anulować albo zmienić bilet kolejowy"),
            (
                "resign_send",
                "Wysłać nowe bilety albo rezerwacje osobom, których dotyczy zmiana",
            ),
            ("resign_register", "Zaktualizować ewidencję sprzętu"),
            ("resign_collect", "Odebrać sprzęt od osoby, która odpadła"),
            ("resign_protocol", "Przygotować i podpisać protokół zwrotu"),
            ("resign_access", "Zgłosić odebranie dostępów"),
            ("resign_billing", "Zaktualizować dokumenty przekazywane do rozliczeń"),
        ),
    ),
    ChecklistSection(
        "po_zakonczeniu",
        "Po zakończeniu",
        (
            ("after_contracts", "Sprawdzić komplet podpisanych umów"),
            (
                "after_protocols",
                "Sprawdzić komplet protokołów przekazania i zwrotu sprzętu",
            ),
            ("after_scans", "Uzupełnić brakujące skany"),
            ("after_folder", "Uporządkować folder edycji na dysku"),
            ("after_billing", "Potwierdzić przekazanie dokumentów do rozliczeń"),
            ("after_kit", "Sprawdzić zwrot i stan sprzętu"),
            ("after_close", "Zamknąć dokumentację edycji"),
        ),
    ),
)

_SECTION_LABELS = {section.key: section.label for section in CHECKLIST_TEMPLATE}
_SECTION_ORDER = {
    section.key: index for index, section in enumerate(CHECKLIST_TEMPLATE)
}


def template_rows() -> list[dict[str, Any]]:
    """Punkty wzoru z pozycją ``<nr sekcji>·100 + <nr punktu>`` (miejsce na dopiski)."""
    return [
        {
            "section_key": section.key,
            "item_key": key,
            "position": (section_no + 1) * 100 + item_no + 1,
            "label": label,
        }
        for section_no, section in enumerate(CHECKLIST_TEMPLATE)
        for item_no, (key, label) in enumerate(section.items)
    ]


# ── Edycja i uczestnicy ───────────────────────────────────────────────────────


def _holds_equipment():
    return exists().where(
        EquipmentAssignment.academy_application_id == AcademyApplication.id,
        EquipmentAssignment.returned_at.is_(None),
    )


def _is_participant():
    """Po zaliczonym zadaniu, odpadł po nim albo ma u siebie sprzęt."""
    return or_(
        AcademyApplication.status.in_(EDITION_STATUSES),
        and_(
            AcademyApplication.status.in_(LEFT_STATUSES),
            AcademyApplication.closed_stage.in_(EDITION_STATUSES),
        ),
        _holds_equipment(),
    )


def participant_filter(program_id: int, cohort_month: date):
    """Uczestnik edycji; do najbliższej trafiają też osoby przed podpisem."""
    member = [and_(AcademyApplication.cohort_month == cohort_month, _is_participant())]
    if cohort_month == pending_cohort():
        member.append(
            and_(
                AcademyApplication.cohort_month.is_(None),
                or_(
                    AcademyApplication.status.in_(PENDING_STATUSES),
                    _holds_equipment(),
                ),
            )
        )
    return and_(AcademyApplication.program_id == program_id, or_(*member))


async def get_edition(db: AsyncSession, program_id: int, cohort_month: date) -> Edition:
    program = await db.get(AcademyProgram, program_id)
    if program is None:
        raise EditionNotFound("Nie ma takiej akademii.")
    if cohort_month.day != 1:
        raise EquipmentError(
            "Edycję wskazuje miesiąc startu (pierwszy dzień miesiąca)."
        )
    return Edition(program=program, cohort_month=cohort_month)


def edition_payload(program: AcademyProgram, cohort_month: date) -> dict[str, Any]:
    start, end = program_dates(cohort_month)
    return {
        "program_id": program.id,
        "program_name": program.name,
        "cohort_month": cohort_month.isoformat(),
        "key": f"{cohort_month:%Y-%m}",
        "starts_on": start.isoformat(),
        "ends_on": end.isoformat(),
    }


async def ensure_checklist(
    db: AsyncSession, program_id: int, cohort_month: date
) -> int:
    """Zakłada brakujące punkty wzoru (idempotentnie); zwraca liczbę nowych."""
    statement = (
        insert(AcademyEditionChecklistItem)
        .values(
            [
                {"program_id": program_id, "cohort_month": cohort_month, **row}
                for row in template_rows()
            ]
        )
        .on_conflict_do_nothing(constraint="uq_academy_edition_checklist_item")
        .returning(AcademyEditionChecklistItem.id)
    )
    created = (await db.execute(statement)).scalars().all()
    return len(created)


async def _checklist(db: AsyncSession, edition: Edition) -> list[dict[str, Any]]:
    items = (
        await db.scalars(
            select(AcademyEditionChecklistItem)
            .where(
                AcademyEditionChecklistItem.program_id == edition.program.id,
                AcademyEditionChecklistItem.cohort_month == edition.cohort_month,
            )
            .order_by(
                AcademyEditionChecklistItem.position, AcademyEditionChecklistItem.id
            )
        )
    ).all()
    names = await _user_names(db, {item.done_by for item in items if item.done_by})
    sections: dict[str, dict[str, Any]] = {}
    for item in items:
        section = sections.setdefault(
            item.section_key,
            {
                "key": item.section_key,
                "label": _SECTION_LABELS.get(item.section_key, item.section_key),
                "done": 0,
                "total": 0,
                "items": [],
            },
        )
        section["total"] += 1
        section["done"] += int(item.done_at is not None)
        section["items"].append(checklist_item_payload(item, names.get(item.done_by)))
    return sorted(
        sections.values(),
        key=lambda s: _SECTION_ORDER.get(s["key"], len(_SECTION_ORDER)),
    )


def checklist_item_payload(
    item: AcademyEditionChecklistItem, done_by_name: Optional[str] = None
) -> dict[str, Any]:
    return {
        "id": item.id,
        "item_key": item.item_key,
        "label": item.label,
        "done": item.done_at is not None,
        "done_at": item.done_at.isoformat() if item.done_at else None,
        "done_by": done_by_name,
        "note": item.note,
    }


async def _user_names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(User.id, User.name, User.email).where(User.id.in_(ids))
    )
    return {uid: (name or email) for uid, name, email in rows.all()}


def _contract_state(
    application: AcademyApplication, documents_at: Optional[datetime]
) -> dict[str, Any]:
    if application.status == "withdrew":
        return {"state": "rezygnacja", "at": None}
    if application.status == "rejected":
        return {"state": "wykluczenie", "at": None}
    if application.signed_at is not None or application.status == "signed":
        at = application.signed_at
        return {"state": "podpisana", "at": at.isoformat() if at else None}
    if (
        application.contract_sent_at is not None
        or application.status == "contract_sent"
    ):
        at = application.contract_sent_at
        return {"state": "wyslana", "at": at.isoformat() if at else None}
    if documents_at is not None:
        return {"state": "dokumenty", "at": documents_at.isoformat()}
    return {"state": "brak", "at": None}


def _kit_state(application: AcademyApplication, active: int, returned: int) -> str:
    if active and application.status in LEFT_STATUSES:
        return "do_zwrotu"
    if active:
        return "wydany"
    if returned:
        return "zwrocony"
    return "brak"


async def _participants(db: AsyncSession, edition: Edition) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(AcademyApplication, Candidate, AcademyParticipantLogistics)
            .join(Candidate, Candidate.id == AcademyApplication.candidate_id)
            .outerjoin(
                AcademyParticipantLogistics,
                AcademyParticipantLogistics.application_id == AcademyApplication.id,
            )
            .where(participant_filter(edition.program.id, edition.cohort_month))
            .order_by(Candidate.lastname, Candidate.name, AcademyApplication.id)
        )
    ).all()
    if not rows:
        return []
    ids = [application.id for application, _c, _l in rows]
    documents = dict(
        (
            await db.execute(
                select(Activity.entity_id, func.max(Activity.created_at))
                .where(
                    Activity.entity_type == "candidate",
                    Activity.action == "academy_documents",
                    Activity.entity_id.in_(
                        [application.candidate_id for application, _c, _l in rows]
                    ),
                    Activity.details["program_id"].astext == str(edition.program.id),
                )
                .group_by(Activity.entity_id)
            )
        ).all()
    )
    assignments = (
        await db.execute(
            select(EquipmentAssignment, EquipmentModel.category, EquipmentModel.name)
            .join(EquipmentItem, EquipmentItem.id == EquipmentAssignment.item_id)
            .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
            .where(EquipmentAssignment.academy_application_id.in_(ids))
            .order_by(EquipmentAssignment.id)
        )
    ).all()
    active: dict[int, list[dict[str, Any]]] = {}
    returned: dict[int, int] = {}
    for assignment, category, name in assignments:
        owner = assignment.academy_application_id
        if assignment.returned_at is None:
            active.setdefault(owner, []).append(
                {
                    "assignment_id": assignment.id,
                    "item_id": assignment.item_id,
                    "category": category,
                    "name": name,
                }
            )
        else:
            returned[owner] = returned.get(owner, 0) + 1
    issue_protocols = (
        await db.scalars(
            select(EquipmentProtocol)
            .where(
                EquipmentProtocol.academy_application_id.in_(ids),
                EquipmentProtocol.kind == "wydanie",
                EquipmentProtocol.status != "anulowany",
            )
            .order_by(EquipmentProtocol.id)
        )
    ).all()
    latest_protocol = {p.academy_application_id: p for p in issue_protocols}
    out = []
    for application, candidate, logistics in rows:
        protocol = latest_protocol.get(application.id)
        items = active.get(application.id, [])
        out.append(
            {
                "application_id": application.id,
                "candidate_id": application.candidate_id,
                "full_name": academy_participant_name(candidate),
                "email": candidate.email,
                "city": candidate.city or candidate.location,
                "status": application.status,
                "status_label": STATUS_LABELS.get(
                    application.status, application.status
                ),
                "left": application.status in LEFT_STATUSES,
                "cohort_month": (
                    application.cohort_month.isoformat()
                    if application.cohort_month
                    else None
                ),
                "contract": _contract_state(
                    application, documents.get(application.candidate_id)
                ),
                "hotel": logistics.hotel if logistics else "do_zrobienia",
                "ticket": logistics.ticket if logistics else "do_zrobienia",
                "logistics_note": logistics.note if logistics else None,
                "kit": {
                    "state": _kit_state(
                        application, len(items), returned.get(application.id, 0)
                    ),
                    "items": items,
                },
                "protocol": (
                    {
                        "id": protocol.id,
                        "number": protocol.number,
                        "status": protocol.status,
                    }
                    if protocol
                    else None
                ),
            }
        )
    return out


async def edition_view(
    db: AsyncSession, program_id: int, cohort_month: date, *, can_issue: bool
) -> dict[str, Any]:
    """Check lista (zakładana przy pierwszym odczycie) i wiersze uczestników."""
    edition = await get_edition(db, program_id, cohort_month)
    await ensure_checklist(db, program_id, cohort_month)
    checklist = await _checklist(db, edition)
    participants = await _participants(db, edition)
    present = [p for p in participants if not p["left"]]
    return {
        "edition": edition_payload(edition.program, cohort_month),
        "checklist": checklist,
        "checklist_done": sum(s["done"] for s in checklist),
        "checklist_total": sum(s["total"] for s in checklist),
        "participants": participants,
        "summary": {
            "participants": len(present),
            "left": len(participants) - len(present),
            "contracts_signed": sum(
                1 for p in present if p["contract"]["state"] == "podpisana"
            ),
            "kits_issued": sum(1 for p in present if p["kit"]["state"] == "wydany"),
            "kits_to_return": sum(
                1 for p in participants if p["kit"]["state"] == "do_zwrotu"
            ),
            "protocols_confirmed": sum(
                1
                for p in present
                if p["protocol"] and p["protocol"]["status"] == "potwierdzony"
            ),
            "logistics_open": sum(
                1
                for p in participants
                for value in (p["hotel"], p["ticket"])
                if value in ("do_zrobienia", "do_anulowania")
            ),
        },
        "can_issue": can_issue,
    }


async def list_editions(
    db: AsyncSession, *, program_id: Optional[int] = None
) -> list[dict[str, Any]]:
    """Edycje z co najmniej jednym uczestnikiem, najnowsze pierwsze.

    Osoby przed podpisem (bez ``cohort_month``) liczą się do najbliższej
    edycji, więc ta pojawia się na liście, zanim ktokolwiek podpisze umowę.
    """
    present = func.count(AcademyApplication.id).filter(
        AcademyApplication.status.in_(EDITION_STATUSES)
    )
    people = func.count(AcademyApplication.id)
    scope = [] if program_id is None else [AcademyApplication.program_id == program_id]
    assigned = (
        await db.execute(
            select(
                AcademyApplication.program_id,
                AcademyApplication.cohort_month,
                present,
                people,
            )
            .where(
                AcademyApplication.cohort_month.is_not(None),
                _is_participant(),
                *scope,
            )
            .group_by(AcademyApplication.program_id, AcademyApplication.cohort_month)
        )
    ).all()
    pending = (
        await db.execute(
            select(AcademyApplication.program_id, present, people)
            .where(
                AcademyApplication.cohort_month.is_(None),
                or_(
                    AcademyApplication.status.in_(PENDING_STATUSES),
                    _holds_equipment(),
                ),
                *scope,
            )
            .group_by(AcademyApplication.program_id)
        )
    ).all()
    counts: dict[tuple[int, date], list[int]] = {}
    for program, cohort, here, everyone in assigned:
        counts[(program, cohort)] = [int(here or 0), int(everyone or 0)]
    upcoming = pending_cohort()
    for program, here, everyone in pending:
        row = counts.setdefault((program, upcoming), [0, 0])
        row[0] += int(here or 0)
        row[1] += int(everyone or 0)
    if not counts:
        return []
    programs = {
        p.id: p
        for p in (
            await db.scalars(
                select(AcademyProgram).where(
                    AcademyProgram.id.in_({key[0] for key in counts})
                )
            )
        ).all()
    }
    ordered = sorted(
        counts.items(), key=lambda kv: (-kv[0][1].toordinal(), programs[kv[0][0]].name)
    )
    return [
        {
            **edition_payload(programs[program], cohort),
            "participants": here,
            "people": everyone,
        }
        for (program, cohort), (here, everyone) in ordered[:EDITIONS_LIMIT]
    ]


# ── Zapis: check lista i logistyka ────────────────────────────────────────────


def _clean_note(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = sanitize.clean_text(value[: NOTE_MAX * 2])
    if cleaned.reasons:
        raise EquipmentError(
            "Notatka zawiera dane, których NEXUS nie przechowuje ("
            + ", ".join(cleaned.reasons)
            + ")."
        )
    return (cleaned.value or "")[:NOTE_MAX] or None


async def set_checklist_item(
    db: AsyncSession,
    program_id: int,
    cohort_month: date,
    item_id: int,
    values: dict[str, Any],
    *,
    actor: User,
) -> dict[str, Any]:
    """Odhacz / odznacz punkt i zmień notatkę (``values`` tylko z wysłanymi polami)."""
    item = await db.get(AcademyEditionChecklistItem, item_id, with_for_update=True)
    if (
        item is None
        or item.program_id != program_id
        or item.cohort_month != cohort_month
    ):
        raise EditionNotFound("Nie ma takiego punktu na liście tej edycji.")
    if "done" in values and values["done"] is not None:
        if values["done"] and item.done_at is None:
            item.done_at = datetime.now(timezone.utc)
            item.done_by = actor.id
        elif not values["done"]:
            item.done_at = None
            item.done_by = None
    if "note" in values:
        item.note = _clean_note(values["note"])
    await db.flush()
    names = await _user_names(db, {item.done_by} if item.done_by else set())
    return checklist_item_payload(item, names.get(item.done_by))


async def _participant(
    db: AsyncSession, program_id: int, cohort_month: date, application_id: int
) -> AcademyApplication:
    application = await db.scalar(
        select(AcademyApplication).where(
            AcademyApplication.id == application_id,
            participant_filter(program_id, cohort_month),
        )
    )
    if application is None:
        raise EditionNotFound("Ta osoba nie jest uczestnikiem tej edycji.")
    return application


async def _logistics_row(
    db: AsyncSession, application_id: int, *, defaults: Optional[dict[str, str]] = None
) -> AcademyParticipantLogistics:
    await db.execute(
        insert(AcademyParticipantLogistics)
        .values(application_id=application_id, **(defaults or {}))
        .on_conflict_do_nothing(
            index_elements=[AcademyParticipantLogistics.application_id]
        )
    )
    row = await db.scalar(
        select(AcademyParticipantLogistics)
        .where(AcademyParticipantLogistics.application_id == application_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def set_logistics(
    db: AsyncSession,
    program_id: int,
    cohort_month: date,
    application_id: int,
    values: dict[str, Any],
    *,
    actor: User,
) -> dict[str, Any]:
    """Hotel, bilet i notatka uczestnika (``values`` tylko z wysłanymi polami)."""
    await _participant(db, program_id, cohort_month, application_id)
    for field in ("hotel", "ticket"):
        value = values.get(field)
        if value is not None and value not in LOGISTICS_STATUSES:
            raise EquipmentError("Nieznany stan hotelu albo biletu.")
    row = await _logistics_row(db, application_id)
    for field in ("hotel", "ticket"):
        if values.get(field) is not None:
            setattr(row, field, values[field])
    if "note" in values:
        row.note = _clean_note(values["note"])
    row.updated_by = actor.id
    await db.flush()
    return {
        "application_id": application_id,
        "hotel": row.hotel,
        "ticket": row.ticket,
        "logistics_note": row.note,
    }


# ── Hurtowe wydanie zestawów ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Kit:
    application_id: int
    lines: Sequence[issuing.IssueLine]


async def issue_kits(
    db: AsyncSession,
    program_id: int,
    cohort_month: date,
    kits: Sequence[Kit],
    *,
    protocol_date: date,
    actor: User,
    with_link: bool = False,
) -> dict[str, Any]:
    """Ten sam zestaw kilku uczestnikom: osobny protokół na osobę.

    Każdy uczestnik w savepoincie — wszystko albo nic dla tej osoby; odmowa
    jednego (zajęta pozycja, rezygnacja) nie cofa pozostałych.
    """
    await get_edition(db, program_id, cohort_month)
    if not kits:
        raise EquipmentError("Wybierz co najmniej jednego uczestnika.")
    people = [kit.application_id for kit in kits]
    if len(set(people)) != len(people):
        raise EquipmentError("Ta sama osoba jest na liście dwa razy.")
    items = [line.item_id for kit in kits for line in kit.lines]
    if len(set(items)) != len(items):
        raise EquipmentError(
            "Ta sama pozycja jest przypisana dwóm osobom albo dwa razy jednej."
        )
    members = set(
        (
            await db.scalars(
                select(AcademyApplication.id).where(
                    AcademyApplication.id.in_(people),
                    participant_filter(program_id, cohort_month),
                )
            )
        ).all()
    )
    results: list[dict[str, Any]] = []
    for kit in kits:
        if kit.application_id not in members:
            results.append(
                {
                    "application_id": kit.application_id,
                    "ok": False,
                    "status": 404,
                    "message": "Ta osoba nie jest uczestnikiem tej edycji.",
                }
            )
            continue
        try:
            async with db.begin_nested():
                result = await issuing.issue(
                    db,
                    holder_kind="academy",
                    holder_id=kit.application_id,
                    lines=kit.lines,
                    protocol_date=protocol_date,
                    actor=actor,
                    with_link=with_link,
                )
        except EquipmentError as exc:
            results.append(
                {
                    "application_id": kit.application_id,
                    "ok": False,
                    "status": exc.status,
                    "message": exc.message,
                }
            )
            continue
        except Exception:  # noqa: BLE001 — jeden uczestnik nie cofa reszty
            logger.exception(
                "[academy_edition] wydanie zestawu nie wyszło application=%s",
                kit.application_id,
            )
            results.append(
                {
                    "application_id": kit.application_id,
                    "ok": False,
                    "status": 500,
                    "message": "Nie udało się wydać zestawu — spróbuj ponownie.",
                }
            )
            continue
        lines = await protocols.protocol_lines(db, result.protocol.id)
        results.append(
            {
                "application_id": kit.application_id,
                "ok": True,
                "protocol": protocols.protocol_payload(result.protocol, lines),
                "link_url": (
                    protocols.public_url(result.link_token)
                    if result.link_token
                    else None
                ),
            }
        )
    issued = sum(1 for r in results if r["ok"])
    return {"issued": issued, "failed": len(results) - issued, "results": results}


# ── Haki zmiany statusu zgłoszenia ────────────────────────────────────────────


def program_start(application: AcademyApplication) -> Optional[date]:
    """Start programu uczestnika: pierwszy dzień roboczy miesiąca edycji."""
    if application.cohort_month is None:
        return None
    return program_dates(application.cohort_month)[0]


async def _candidate_name(db: AsyncSession, application: AcademyApplication) -> str:
    return academy_participant_name(await db.get(Candidate, application.candidate_id))


async def _active_items(db: AsyncSession, application_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                EquipmentAssignment.academy_application_id == application_id,
                EquipmentAssignment.returned_at.is_(None),
            )
        )
        or 0
    )


async def kit_task(
    db: AsyncSession, application: AcademyApplication
) -> Optional[EquipmentTask]:
    """Zadanie „Przygotuj zestaw Akademii” (idempotentne po ``source_key``)."""
    if await _active_items(db, application.id):
        return None
    start = program_start(application)
    due: Optional[date] = None
    if start is not None:
        due = max(
            await equipment_tasks.workdays_before(db, start, KIT_LEAD_WORKDAYS),
            business_today(),
        )
    name = await _candidate_name(db, application)
    details = {
        "reason": "akademia",
        "program_start": start.isoformat() if start else None,
        "cohort_month": (
            application.cohort_month.isoformat() if application.cohort_month else None
        ),
    }
    task = await equipment_tasks.upsert_task(
        db,
        kind="wydanie",
        source_key=f"academy:{application.id}:kit",
        title=f"Przygotuj zestaw Akademii: {name}",
        due_on=due,
        academy_application_id=application.id,
        details=details,
    )
    if task.status == "anulowane":
        # Ponowny podpis po rezygnacji: zadanie wraca z nowym terminem.
        task.status = "otwarte"
        task.due_on = due
        task.done_at = None
        task.done_by = None
        task.details = {**(task.details or {}), **details}
        await db.flush()
    return task


_ON_LEAVE = {"zrobione": "do_anulowania", "do_zrobienia": "nie_dotyczy"}


async def on_left(
    db: AsyncSession,
    application: AcademyApplication,
    *,
    before: str,
    actor_id: Optional[int],
) -> dict[str, Any]:
    """Rezygnacja albo wykluczenie po zaliczonym zadaniu: logistyka, zadania, zwrot."""
    outcome: dict[str, Any] = {}
    existing = await db.get(AcademyParticipantLogistics, application.id)
    if existing is not None or before in EDITION_STATUSES:
        row = await _logistics_row(db, application.id)
        row.hotel = _ON_LEAVE.get(row.hotel, row.hotel)
        row.ticket = _ON_LEAVE.get(row.ticket, row.ticket)
        row.updated_by = actor_id
        outcome["hotel"] = row.hotel
        outcome["ticket"] = row.ticket
    cancelled = await db.execute(
        update(EquipmentTask)
        .where(
            EquipmentTask.academy_application_id == application.id,
            EquipmentTask.kind == "wydanie",
            EquipmentTask.status == "otwarte",
        )
        .values(
            status="anulowane", done_at=datetime.now(timezone.utc), done_by=actor_id
        )
    )
    outcome["kit_tasks_cancelled"] = int(cancelled.rowcount or 0)
    items = await _active_items(db, application.id)
    if items:
        name = await _candidate_name(db, application)
        task = await equipment_tasks.upsert_task(
            db,
            kind="zwrot",
            source_key=f"academy:{application.id}:return",
            title=f"Odbierz sprzęt: {name} (odejście z Akademii)",
            due_on=business_today(),
            academy_application_id=application.id,
            details={"reason": "rezygnacja_akademia", "items": items},
        )
        if task.status != "otwarte":
            task.status = "otwarte"
            task.due_on = business_today()
            task.done_at = None
            task.done_by = None
        outcome["return_task"] = task.id
    await db.flush()
    return outcome


async def on_status_changed(
    db: AsyncSession,
    application: AcademyApplication,
    *,
    before: str,
    actor_id: Optional[int],
) -> Optional[dict[str, Any]]:
    """Hak ``perform_action``: zadania recepcji i logistyka przy zmianie statusu.

    Biegnie w savepoincie — każda awaria jest logowana, a zmiana statusu
    zgłoszenia zostaje. Wyłączony moduł „Sprzęt” = nic.
    """
    after = application.status
    if after == before or after not in ("signed", *LEFT_STATUSES):
        return None
    try:
        async with db.begin_nested():
            from app.services.hr.modules import load_modules

            if not (await load_modules(db)).get("equipment"):
                return {"status": "disabled"}
            if after == "signed":
                task = await kit_task(db, application)
                return {"kit_task": task.id if task else None}
            return await on_left(db, application, before=before, actor_id=actor_id)
    except Exception as exc:  # noqa: BLE001 — moduł poboczny nie blokuje statusu
        logger.exception(
            "[academy_edition] hak statusu %s→%s zgłoszenia %s nie przeszedł",
            before,
            after,
            application.id,
        )
        return {"error": type(exc).__name__}


__all__ = [
    "CHECKLIST_TEMPLATE",
    "Edition",
    "EditionNotFound",
    "Kit",
    "edition_view",
    "ensure_checklist",
    "issue_kits",
    "kit_task",
    "list_editions",
    "on_status_changed",
    "set_checklist_item",
    "set_logistics",
]
