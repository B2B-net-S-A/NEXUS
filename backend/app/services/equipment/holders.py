"""Posiadacze sprzętu: konto NEXUSA, kontrakt, osoba spoza NEXUSA, uczestnik Akademii.

Posiadacz to dokładnie jedno z czterech. Imię, nazwisko i e-mail uczestnika
Akademii pochodzą z kandydata zgłoszenia — PESEL-u i adresu z dokumentów
Akademii ewidencja nie widzi. Osoby spoza NEXUSA (bez konta) zakłada recepcja.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Sequence

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.academy import AcademyApplication, AcademyProgram
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentExternalPerson,
    EquipmentProtocol,
    EquipmentTask,
)
from app.models.user import User
from app.services.equipment import sanitize
from app.services.equipment.errors import (
    EquipmentConflict,
    EquipmentError,
    EquipmentNotFound,
)
from app.services.hr import audit

HolderKind = Literal["user", "contract", "external", "academy"]

#: Kontrakty, którym można wydać sprzęt (konsultant przed startem albo w trakcie).
ISSUABLE_CONTRACT_STATUSES = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.active,
    ContractStatus.ending,
)

#: Zgłoszenia Akademii, którym można wydać sprzęt (po zaliczonym zadaniu).
ISSUABLE_ACADEMY_STATUSES = ("task_passed", "contract_sent", "signed")

#: Kandydat zgłoszenia Akademii — osobny alias, bo ``Candidate`` bywa już
#: dołączony przez kontrakt w tym samym zapytaniu.
AcademyCandidate = aliased(Candidate, name="academy_candidate")


#: Posiadacz, którego dane usunięto (kandydat kontraktu na żądanie RODO,
#: zgłoszenie Akademii przy usunięciu albo scaleniu osoby).
DELETED_PERSON = "Osoba usunięta"

#: Odmowa usunięcia albo scalenia kandydata, gdy jako uczestnik Akademii ma
#: niezwrócony sprzęt — wydanie straciłoby posiadacza, a egzemplarz zostałby
#: „wydany” nikomu.
ACADEMY_EQUIPMENT_HELD = (
    "Ta osoba ma niezwrócony sprzęt jako uczestnik Akademii. Najpierw zwrot "
    "sprzętu w module „Sprzęt”, potem usunięcie albo scalenie profilu."
)


@dataclass(frozen=True)
class Holder:
    kind: HolderKind
    id: int
    name: str
    email: Optional[str]
    detail: Optional[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "detail": self.detail,
        }


def candidate_name(candidate: Candidate | None) -> str:
    if candidate is None:
        return "Konsultant"
    return (
        " ".join(p for p in (candidate.name, candidate.lastname) if p) or "Konsultant"
    )


async def resolve_holder(db: AsyncSession, kind: str, holder_id: int) -> Holder:
    if kind == "user":
        user = await db.get(User, holder_id)
        if user is None:
            raise EquipmentNotFound("Nie ma takiego konta.")
        return Holder(
            "user", user.id, user.name or user.email, user.email, "Konto NEXUSA"
        )
    if kind == "contract":
        # Kandydata usuniętego na żądanie (RODO) kontrakt przeżywa z pustym
        # ``candidate_id`` — sprzęt na nim trzeba dalej móc zwrócić.
        row = (
            await db.execute(
                select(Contract, Candidate, Client)
                .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
                .outerjoin(Client, Client.id == Contract.client_id)
                .where(Contract.id == holder_id)
            )
        ).first()
        if row is None:
            raise EquipmentNotFound("Nie ma takiego kontraktu.")
        contract, candidate, client = row
        detail = "Kontraktor"
        if client is not None:
            detail += f" · {client.name}"
        if contract.start_date:
            detail += f" · start {contract.start_date:%d.%m.%Y}"
        if candidate is None:
            return Holder("contract", contract.id, DELETED_PERSON, None, detail)
        email = contract.candidate_email or candidate.email
        return Holder("contract", contract.id, candidate_name(candidate), email, detail)
    if kind == "external":
        person = await db.get(EquipmentExternalPerson, holder_id)
        if person is None:
            raise EquipmentNotFound("Nie ma takiej osoby.")
        return Holder(
            "external",
            person.id,
            person.full_name,
            person.work_email,
            person.note or "Osoba spoza NEXUSA",
        )
    if kind == "academy":
        row = (
            await db.execute(
                select(AcademyApplication, Candidate, AcademyProgram)
                .join(Candidate, Candidate.id == AcademyApplication.candidate_id)
                .join(
                    AcademyProgram, AcademyProgram.id == AcademyApplication.program_id
                )
                .where(AcademyApplication.id == holder_id)
            )
        ).first()
        if row is None:
            raise EquipmentNotFound("Nie ma takiego zgłoszenia Akademii.")
        application, candidate, program = row
        return Holder(
            "academy",
            application.id,
            academy_participant_name(candidate),
            candidate.email,
            academy_detail(program.name, application.cohort_month),
        )
    raise EquipmentError("Nieznany rodzaj posiadacza.")


def academy_participant_name(candidate: Candidate | None) -> str:
    if candidate is None:
        return "Uczestnik Akademii"
    return (
        " ".join(p for p in (candidate.name, candidate.lastname) if p)
        or "Uczestnik Akademii"
    )


def academy_detail(program_name: str, cohort_month: Any) -> str:
    detail = f"Uczestnik Akademii · {program_name}"
    if cohort_month is not None:
        detail += f" · edycja {cohort_month:%m.%Y}"
    return detail


def holder_columns(kind: HolderKind, holder_id: int) -> dict[str, Optional[int]]:
    return {
        "user_id": holder_id if kind == "user" else None,
        "contract_id": holder_id if kind == "contract" else None,
        "external_person_id": holder_id if kind == "external" else None,
        "academy_application_id": holder_id if kind == "academy" else None,
    }


def holder_of(row: Any) -> tuple[HolderKind, int] | None:
    """(rodzaj, id) posiadacza z wiersza wydania, protokołu albo zadania."""
    if row.user_id is not None:
        return "user", row.user_id
    if row.contract_id is not None:
        return "contract", row.contract_id
    if row.external_person_id is not None:
        return "external", row.external_person_id
    if getattr(row, "academy_application_id", None) is not None:
        return "academy", row.academy_application_id
    return None


async def active_academy_assignments(
    db: AsyncSession,
    *,
    candidate_id: int | None = None,
    application_ids: Sequence[int] = (),
) -> list[int]:
    """Id niezwróconych wydań uczestnika Akademii — zgłoszeń osoby albo wskazanych.

    Usunięcie i scalenie kandydata pytają o to przed skasowaniem zgłoszeń
    (odmowa 409 ``ACADEMY_EQUIPMENT_HELD``); zwrócone wydania nie blokują.
    """
    if candidate_id is None and not application_ids:
        return []
    owner = (
        AcademyApplication.candidate_id == candidate_id
        if candidate_id is not None
        else AcademyApplication.id.in_([int(value) for value in application_ids])
    )
    return list(
        (
            await db.scalars(
                select(EquipmentAssignment.id)
                .join(
                    AcademyApplication,
                    AcademyApplication.id == EquipmentAssignment.academy_application_id,
                )
                .where(owner, EquipmentAssignment.returned_at.is_(None))
                .order_by(EquipmentAssignment.id)
            )
        ).all()
    )


async def search_academy_holders(
    db: AsyncSession, q: str, *, limit: int = 15
) -> list[dict]:
    """Uczestnicy Akademii po imieniu i nazwisku: po zaliczonym zadaniu albo z rzeczami.

    Osoba, która zrezygnowała, a nie oddała sprzętu, nadal jest do znalezienia
    (zwrot), ale wydać jej nic się nie da (``issuing``).
    """
    needle = f"%{q.strip()}%"
    if len(q.strip()) < 2:
        return []
    full = func.concat_ws(" ", Candidate.name, Candidate.lastname)
    holds = exists().where(
        EquipmentAssignment.academy_application_id == AcademyApplication.id,
        EquipmentAssignment.returned_at.is_(None),
    )
    rows = (
        await db.execute(
            select(AcademyApplication, Candidate, AcademyProgram)
            .join(Candidate, Candidate.id == AcademyApplication.candidate_id)
            .join(AcademyProgram, AcademyProgram.id == AcademyApplication.program_id)
            .where(
                or_(
                    AcademyApplication.status.in_(ISSUABLE_ACADEMY_STATUSES),
                    holds,
                ),
                full.ilike(needle),
            )
            # Najpierw osoby przed podpisem (najbliższa edycja), potem nowsze edycje.
            .order_by(
                AcademyApplication.cohort_month.desc().nulls_first(),
                AcademyApplication.id.desc(),
            )
            .limit(limit)
        )
    ).all()
    return [
        Holder(
            "academy",
            application.id,
            academy_participant_name(candidate),
            candidate.email,
            academy_detail(program.name, application.cohort_month),
        ).as_dict()
        for application, candidate, program in rows
    ]


async def search_holders(
    db: AsyncSession, q: str, *, limit: int = 15, kind: Optional[str] = None
) -> list[dict]:
    """Podpowiedzi posiadacza w kreatorze wydania: konta, kontrakty, osoby spoza.

    ``kind="academy"`` szuka wyłącznie uczestników Akademii (osobny tryb
    wyboru w kreatorze — import plików recepcji ich nie potrzebuje).
    """
    if kind == "academy":
        return await search_academy_holders(db, q, limit=limit)
    needle = f"%{q.strip()}%"
    if len(q.strip()) < 2:
        return []
    out: list[dict] = []
    users = (
        await db.scalars(
            select(User)
            .where(User.is_active.is_(True))
            .where(or_(User.name.ilike(needle), User.email.ilike(needle)))
            .order_by(User.name)
            .limit(limit)
        )
    ).all()
    out += [
        Holder("user", u.id, u.name or u.email, u.email, "Konto NEXUSA").as_dict()
        for u in users
    ]
    full = func.concat_ws(" ", Candidate.name, Candidate.lastname)
    contracts = (
        await db.execute(
            select(Contract, Candidate, Client)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(Contract.status.in_(ISSUABLE_CONTRACT_STATUSES))
            .where(full.ilike(needle))
            .order_by(Contract.start_date.desc().nulls_last())
            .limit(limit)
        )
    ).all()
    for contract, candidate, client in contracts:
        detail = "Kontraktor" + (f" · {client.name}" if client else "")
        if contract.start_date:
            detail += f" · start {contract.start_date:%d.%m.%Y}"
        out.append(
            Holder(
                "contract",
                contract.id,
                candidate_name(candidate),
                contract.candidate_email or candidate.email,
                detail,
            ).as_dict()
        )
    external = (
        await db.scalars(
            select(EquipmentExternalPerson)
            .where(EquipmentExternalPerson.full_name.ilike(needle))
            .order_by(EquipmentExternalPerson.full_name)
            .limit(limit)
        )
    ).all()
    out += [
        Holder(
            "external", p.id, p.full_name, p.work_email, p.note or "Osoba spoza NEXUSA"
        ).as_dict()
        for p in external
    ]
    return out


# ── Osoby spoza NEXUSA ────────────────────────────────────────────────────────


def external_payload(person: EquipmentExternalPerson) -> dict[str, Any]:
    return {
        "id": person.id,
        "full_name": person.full_name,
        "work_email": person.work_email,
        "note": person.note,
    }


async def list_external_people(db: AsyncSession, q: Optional[str]) -> list[dict]:
    query = select(EquipmentExternalPerson).order_by(EquipmentExternalPerson.full_name)
    if q and q.strip():
        query = query.where(EquipmentExternalPerson.full_name.ilike(f"%{q.strip()}%"))
    return [external_payload(p) for p in (await db.scalars(query.limit(100))).all()]


async def create_external_person(
    db: AsyncSession, values: dict[str, Any], *, actor: User
) -> EquipmentExternalPerson:
    name = " ".join((values.get("full_name") or "").split())
    if not name:
        raise EquipmentError("Podaj imię i nazwisko.")
    email = (values.get("work_email") or "").strip() or None
    if email and sanitize.is_private_email(email):
        raise EquipmentError(
            "Podaj e-mail służbowy — prywatnych adresów NEXUS nie przechowuje."
        )
    from app.services.equipment.registry import clean_notes  # noqa: PLC0415

    person = EquipmentExternalPerson(
        full_name=name,
        work_email=email,
        # D10 jak w notatce egzemplarza: klucz BitLocker (55 znaków) mieści się
        # w 200 znakach uwagi o osobie spoza NEXUSA (audyt 19.10.2026).
        note=clean_notes(values.get("note") or None, label="Uwaga"),
        created_by=actor.id,
    )
    db.add(person)
    await db.flush()
    return person


#: Protokoły, które idą za sprzętem na konto — jeszcze niezamknięte podpisem.
#: Potwierdzony zostaje przy osobie spoza NEXUSA (migawka z chwili wydania).
MOVABLE_PROTOCOL_STATUSES = ("oczekuje", "podpisany")


async def move_external_to_user(
    db: AsyncSession, person_id: int, user_id: int, *, actor: User
) -> dict[str, Any]:
    """„Przepisz na konto”: niezwrócony sprzęt osoby spoza NEXUSA przechodzi na konto.

    Nowa osoba w firmie dostaje sprzęt od razu jako osoba spoza NEXUSA, zanim
    powstanie jej konto (decyzja Artura 28.10.2026, wariant B). W jednej
    transakcji przechodzą aktywne wydania, otwarte zadania i protokoły przed
    potwierdzeniem; potwierdzone zostają z migawką (``holder_name``) i dostają
    wpis w dzienniku, na kogo przeszedł ich sprzęt. Zwrócone wydania zostają
    historią osoby spoza NEXUSA.
    """
    person = await db.get(EquipmentExternalPerson, person_id)
    if person is None:
        raise EquipmentNotFound("Nie ma takiej osoby spoza NEXUSA.")
    user = await db.get(User, user_id)
    if user is None:
        raise EquipmentNotFound("Nie ma takiego konta.")
    if not user.is_active:
        raise EquipmentConflict(
            f"Konto {user.name or user.email} jest nieaktywne — sprzęt przepiszesz "
            "tylko na aktywne konto NEXUSA."
        )
    assignments = (
        await db.scalars(
            select(EquipmentAssignment)
            .where(
                EquipmentAssignment.external_person_id == person.id,
                EquipmentAssignment.returned_at.is_(None),
            )
            .order_by(EquipmentAssignment.id)
            .with_for_update()
        )
    ).all()
    if not assignments:
        raise EquipmentConflict(
            f"{person.full_name} nie ma niezwróconego sprzętu — nie ma czego przepisać."
        )
    for assignment in assignments:
        # CHECK jednego posiadacza: najpierw zdejmujemy osobę spoza, potem konto.
        assignment.external_person_id = None
        assignment.user_id = user.id
    moved_protocols = list(
        (
            await db.scalars(
                update(EquipmentProtocol)
                .where(
                    EquipmentProtocol.external_person_id == person.id,
                    EquipmentProtocol.status.in_(MOVABLE_PROTOCOL_STATUSES),
                )
                .values(external_person_id=None, user_id=user.id)
                .returning(EquipmentProtocol.id)
            )
        ).all()
    )
    moved_tasks = list(
        (
            await db.scalars(
                update(EquipmentTask)
                .where(
                    EquipmentTask.external_person_id == person.id,
                    EquipmentTask.status == "otwarte",
                )
                .values(external_person_id=None, user_id=user.id)
                .returning(EquipmentTask.id)
            )
        ).all()
    )
    issue_protocols = {
        a.issue_protocol_id for a in assignments if a.issue_protocol_id is not None
    }
    confirmed = sorted(issue_protocols - set(moved_protocols))
    await db.flush()
    move = {
        "from_external_person_id": person.id,
        "to_user_id": user.id,
    }
    for protocol_id in confirmed:
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=user.id,
            entity_type="equipment_protocol",
            entity_id=protocol_id,
            action="equipment_holder_moved_to_user",
            details=move,
        )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user.id,
        entity_type="equipment_external_person",
        entity_id=person.id,
        action="equipment_moved_to_user",
        details={
            **move,
            "assignment_ids": [a.id for a in assignments],
            "protocol_ids": sorted(moved_protocols),
            "confirmed_protocol_ids": confirmed,
            "task_ids": sorted(moved_tasks),
        },
    )
    return {
        "holder": Holder(
            "user", user.id, user.name or user.email, user.email, "Konto NEXUSA"
        ).as_dict(),
        "assignments": len(assignments),
        "protocols": len(moved_protocols),
        "confirmed_protocols": len(confirmed),
        "tasks": len(moved_tasks),
    }
