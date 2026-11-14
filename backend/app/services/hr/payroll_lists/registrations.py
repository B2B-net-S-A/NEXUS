"""Zdarzenia do zgłoszeń ZUS (K7a): początek i koniec tytułu do ubezpieczeń.

Zgłoszenie składa się w 7 dni od powstania tytułu — zanim powstanie lista płac
— dlatego zgłoszenia nie wynikają z listy, tylko z dat umów w zakresie:

* **zespół** — kartoteka z formą ``uop`` albo ``zlecenie``: początek
  ``work_start_date`` (albo ``hired_on``), koniec ``last_working_day``,
* **zleceniobiorca u klienta** — kontrakt ``uzlecenie``: ``start_date``
  i ``end_date`` (bez szkiców i unieważnionych).

Rodzaj zgłoszenia: umowa o pracę i zlecenie z obowiązkowymi emerytalnym
i rentowymi — ZUA; zlecenie przy zbiegu tytułów (tylko zdrowotna) — ZZA;
uczeń i student do 26 lat na zleceniu — bez zgłoszenia. Koniec tytułu — ZWUA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.contract import Contract, ContractType
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr.payroll_lists import person_data
from app.services.hr.payroll_lists.sources import MANDATE_STATUSES

KINDS = ("ZUA", "ZZA", "ZWUA")


@dataclass
class RegistrationEvent:
    kind: str  # ZUA | ZZA | ZWUA
    person_key: str
    user_id: Optional[int]
    candidate_id: Optional[int]
    contract_id: Optional[int]
    name: str
    title_kind: str  # uop | zlecenie
    on: date
    data: dict[str, Any] = field(default_factory=dict, repr=False)
    problems: list[str] = field(default_factory=list)


def _kind_for_start(title_kind: str, data: dict[str, Any], on: date) -> Optional[str]:
    if title_kind == "uop":
        return "ZUA"
    student_until = data.get("student_exempt_until")
    if student_until and date.fromisoformat(student_until) >= on:
        return None
    flags = person_data.mandate_flags(data)
    return "ZUA" if flags["pension_insurance"] else "ZZA"


async def events(
    db: AsyncSession, date_from: date, date_to: date
) -> list[RegistrationEvent]:
    """Początki i końce tytułów w zakresie dat (włącznie), z danymi osób."""

    out: list[RegistrationEvent] = []
    start = EmployeeProfile.work_start_date
    team = (
        await db.execute(
            select(EmployeeProfile, User.name)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(
                EmployeeProfile.employment_type.in_(("uop", "zlecenie")),
                or_(
                    and_(start >= date_from, start <= date_to),
                    and_(
                        start.is_(None),
                        EmployeeProfile.hired_on >= date_from,
                        EmployeeProfile.hired_on <= date_to,
                    ),
                    and_(
                        EmployeeProfile.last_working_day >= date_from,
                        EmployeeProfile.last_working_day <= date_to,
                    ),
                ),
            )
        )
    ).all()
    contracts = (
        await db.execute(
            select(Contract, Candidate.name, Candidate.lastname)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                Contract.contract_type == ContractType.uzlecenie,
                Contract.status.in_(MANDATE_STATUSES),
                or_(
                    and_(
                        Contract.start_date >= date_from, Contract.start_date <= date_to
                    ),
                    and_(Contract.end_date >= date_from, Contract.end_date <= date_to),
                ),
            )
        )
    ).all()
    records = await person_data.records_for(
        db,
        {profile.user_id for profile, _name in team},
        {contract.candidate_id for contract, _f, _l in contracts},
    )

    def data_of(key: str) -> tuple[dict[str, Any], list[str]]:
        record = records.get(key)
        if record is None:
            return {}, ["person_data_missing"]
        try:
            data = person_data.decrypt(record)
        except person_data.PersonDataError:
            return {}, ["person_data_unreadable"]
        missing = person_data.missing_fields(data, contractor=key.startswith("c"))
        return data, person_data.blocks_files(missing)

    for profile, name in team:
        key = f"u{profile.user_id}"
        data, problems = data_of(key)
        began = profile.work_start_date or profile.hired_on
        if began is not None and date_from <= began <= date_to:
            kind = _kind_for_start(profile.employment_type, data, began)
            student = profile.student_contribution_exempt and (
                profile.contribution_exempt_until is None
                or profile.contribution_exempt_until >= began
            )
            if student and profile.employment_type == "zlecenie":
                kind = None
            if kind:
                out.append(
                    RegistrationEvent(
                        kind,
                        key,
                        profile.user_id,
                        None,
                        None,
                        str(name),
                        profile.employment_type,
                        began,
                        data,
                        list(problems),
                    )
                )
        ended = profile.last_working_day
        if ended is not None and date_from <= ended <= date_to:
            out.append(
                RegistrationEvent(
                    "ZWUA",
                    key,
                    profile.user_id,
                    None,
                    None,
                    str(name),
                    profile.employment_type,
                    ended,
                    data,
                    list(problems),
                )
            )
    for contract, first, last in contracts:
        key = f"c{contract.candidate_id}"
        name = " ".join(part for part in (first, last) if part)
        data, problems = data_of(key)
        if contract.start_date and date_from <= contract.start_date <= date_to:
            kind = _kind_for_start("zlecenie", data, contract.start_date)
            if kind:
                out.append(
                    RegistrationEvent(
                        kind,
                        key,
                        None,
                        contract.candidate_id,
                        contract.id,
                        name,
                        "zlecenie",
                        contract.start_date,
                        data,
                        list(problems),
                    )
                )
        if contract.end_date and date_from <= contract.end_date <= date_to:
            out.append(
                RegistrationEvent(
                    "ZWUA",
                    key,
                    None,
                    contract.candidate_id,
                    contract.id,
                    name,
                    "zlecenie",
                    contract.end_date,
                    data,
                    list(problems),
                )
            )
    out.sort(key=lambda e: (e.on, e.name.casefold(), e.kind))
    return out


def event_payload(event: RegistrationEvent) -> dict[str, Any]:
    """Na ekran: bez danych osoby (PESEL, adres zostają w pliku)."""

    return {
        "kind": event.kind,
        "person_key": event.person_key,
        "user_id": event.user_id,
        "candidate_id": event.candidate_id,
        "contract_id": event.contract_id,
        "name": event.name,
        "title_kind": event.title_kind,
        "on": event.on.isoformat(),
        "problems": [
            {"code": code, "label": person_data.FIELD_LABELS.get(code, "dane płacowe")}
            for code in event.problems
        ],
    }


__all__ = ["KINDS", "RegistrationEvent", "event_payload", "events"]
