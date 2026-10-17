"""Komunikaty do konsultantów — grupy odbiorców i wykluczenia (O12, M7).

Konsultant = kandydat z aktywnym albo kończącym się kontraktem
(``care.access.live_contracts``) w zakresie czytającego: Delivery Lead — swoi
klienci, reszta — wszyscy. Jedna osoba z dwoma kontraktami dostaje jeden mail
(liczy się kontrakt z najpóźniejszym startem: jego klient i opiekun).

Grupy: wszyscy, klient, opiekun (ten sam łańcuch co w opiece:
``effective_owners``), forma współpracy z kontraktu, kończący zamówienie w N
dni (``CareContract.end_date`` — ta sama data co w planie opieki), wybrane
osoby. Wykluczenia: brak poprawnego e-maila (umowa przed profilem,
``contract_candidate_contact``), wypisani z informacyjnych — obowiązkowy idzie
do wszystkich z grupy.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.care_announcement import CareAnnouncementOptOut
from app.models.contract import Contract, ContractType
from app.services.care import access as care_access
from app.services.contract_candidate_contact import resolve_contact
from app.services.hr.employment_terms import terms

GROUPS: tuple[str, ...] = ("all", "client", "owner", "form", "ending", "selected")
#: Klucze form jak w ``employment_terms`` (lustro słów we froncie).
FORM_BY_CONTRACT: dict[str, str] = {
    ContractType.b2b.value: "b2b",
    ContractType.uop.value: "uop",
    ContractType.uzlecenie.value: "zlecenie",
}
FORMS: tuple[str, ...] = ("b2b", "uop", "zlecenie")
ENDING_DAYS_MAX = 180
LIST_MAX = 1000

_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


class AudienceError(ValueError):
    """Zła grupa odbiorców (422)."""


@dataclass(frozen=True)
class Audience:
    group: str
    client_ids: tuple[int, ...] = ()
    owner_user_ids: tuple[int, ...] = ()
    forms: tuple[str, ...] = ()
    ending_days: Optional[int] = None
    candidate_ids: tuple[int, ...] = ()

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"group": self.group}
        if self.group == "client":
            out["client_ids"] = list(self.client_ids)
        elif self.group == "owner":
            out["owner_user_ids"] = list(self.owner_user_ids)
        elif self.group == "form":
            out["forms"] = list(self.forms)
        elif self.group == "ending":
            out["ending_days"] = self.ending_days
        elif self.group == "selected":
            out["candidate_ids"] = list(self.candidate_ids)
        return out


def _ids(raw: object, label: str) -> tuple[int, ...]:
    if not isinstance(raw, list) or not raw:
        raise AudienceError(f"Wybierz co najmniej jedną pozycję: {label}.")
    if len(raw) > LIST_MAX:
        raise AudienceError(f"Najwyżej {LIST_MAX} pozycji: {label}.")
    out: list[int] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise AudienceError(f"Nieprawidłowa pozycja: {label}.")
        if value not in out:
            out.append(value)
    return tuple(out)


def parse_audience(raw: object) -> Audience:
    if not isinstance(raw, Mapping):
        raise AudienceError("Wybierz, do kogo idzie komunikat.")
    group = raw.get("group")
    if group not in GROUPS:
        raise AudienceError("Wybierz, do kogo idzie komunikat.")
    if group == "client":
        return Audience(group, client_ids=_ids(raw.get("client_ids"), "klient"))
    if group == "owner":
        return Audience(
            group, owner_user_ids=_ids(raw.get("owner_user_ids"), "opiekun")
        )
    if group == "selected":
        return Audience(group, candidate_ids=_ids(raw.get("candidate_ids"), "osoby"))
    if group == "form":
        forms = raw.get("forms")
        if (
            not isinstance(forms, list)
            or not forms
            or any(f not in FORMS for f in forms)
        ):
            raise AudienceError("Wybierz formę współpracy: B2B, UoP albo zlecenie.")
        return Audience(group, forms=tuple(dict.fromkeys(forms)))
    if group == "ending":
        days = raw.get("ending_days")
        if (
            isinstance(days, bool)
            or not isinstance(days, int)
            or not (1 <= days <= ENDING_DAYS_MAX)
        ):
            raise AudienceError(
                f"Liczba dni do końca zamówienia: od 1 do {ENDING_DAYS_MAX}."
            )
        return Audience(group, ending_days=days)
    return Audience("all")


@dataclass(frozen=True)
class Person:
    candidate_id: int
    contract_id: int
    client_id: int
    client_name: str
    name: str
    first_name: Optional[str]
    email: Optional[str]
    form: str
    end_date: Optional[date]
    owner_user_id: Optional[int]
    owner_name: Optional[str]
    #: ``pending`` (dostanie) albo powód wykluczenia.
    status: str


def valid_email(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip()
    return cleaned if cleaned and _EMAIL_RE.match(cleaned) else None


async def _contact_rows(
    db: AsyncSession, contract_ids: Iterable[int]
) -> dict[int, tuple[Optional[str], str, Optional[str], Optional[str]]]:
    """contract_id → (e-mail rozstrzygnięty, forma, imię, nazwisko)."""

    ids = sorted(set(contract_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                Contract.id,
                Contract.candidate_email,
                Contract.contract_type,
                Candidate.email,
                Candidate.name,
                Candidate.lastname,
            )
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.id.in_(ids))
        )
    ).all()
    out = {}
    for contract_id, contract_email, contract_type, profile_email, first, last in rows:
        contact = resolve_contact(
            contract_email=contract_email,
            contract_phone=None,
            candidate=SimpleNamespace(email=profile_email, phone=None),
        )
        type_value = getattr(contract_type, "value", contract_type)
        out[contract_id] = (
            contact.email,
            FORM_BY_CONTRACT.get(str(type_value), "b2b"),
            first,
            last,
        )
    return out


async def opted_out(db: AsyncSession, candidate_ids: Iterable[int]) -> set[int]:
    ids = sorted(set(candidate_ids))
    if not ids:
        return set()
    rows = await db.scalars(
        select(CareAnnouncementOptOut.candidate_id).where(
            CareAnnouncementOptOut.candidate_id.in_(ids)
        )
    )
    return set(rows.all())


def _latest_per_person(
    contracts: Iterable[care_access.CareContract],
) -> list[care_access.CareContract]:
    best: dict[int, care_access.CareContract] = {}
    for contract in contracts:
        if contract.candidate_id is None:
            continue  # kontrakt bez kandydata nie ma do kogo pisać (RODO zeruje e-mail)
        current = best.get(contract.candidate_id)
        key = (contract.start_date or date.min, contract.id)
        if current is None or key > (current.start_date or date.min, current.id):
            best[contract.candidate_id] = contract
    return sorted(best.values(), key=lambda c: (c.client_name, c.candidate_name or ""))


async def people_in_scope(
    db: AsyncSession, allowed: frozenset[int] | None
) -> tuple[list[care_access.CareContract], dict[int, care_access.OwnerChoice]]:
    contracts = _latest_per_person(
        await care_access.live_contracts(db, allowed=allowed)
    )
    owners = await care_access.effective_owners(db, contracts)
    return contracts, owners


async def resolve(
    db: AsyncSession,
    *,
    allowed: frozenset[int] | None,
    audience: Audience,
    kind: str,
) -> list[Person]:
    """Osoby grupy z powodem wykluczenia (``pending`` = dostanie)."""

    if audience.group == "client":
        for client_id in audience.client_ids:
            care_access.assert_client_in_scope(client_id, allowed)
    contracts, owners = await people_in_scope(db, allowed)
    contacts = await _contact_rows(db, (c.id for c in contracts))
    today = business_today()
    horizon = today + timedelta(days=audience.ending_days or 0)

    def member(contract: care_access.CareContract) -> bool:
        if audience.group == "client":
            return contract.client_id in audience.client_ids
        if audience.group == "owner":
            return owners[contract.id].user_id in audience.owner_user_ids
        if audience.group == "form":
            return contacts.get(contract.id, (None, "b2b"))[1] in audience.forms
        if audience.group == "ending":
            end = contract.end_date
            return end is not None and today <= end <= horizon
        if audience.group == "selected":
            return contract.candidate_id in audience.candidate_ids
        return True

    chosen = [contract for contract in contracts if member(contract)]
    owner_names = await care_access.user_names(
        db, (owners[c.id].user_id for c in chosen)
    )
    opted = (
        await opted_out(db, (c.candidate_id for c in chosen))
        if kind == "informational"
        else set()
    )
    people: list[Person] = []
    for contract in chosen:
        email, form, first, _last = contacts.get(contract.id, (None, "b2b", None, None))
        email = valid_email(email)
        owner_id = owners[contract.id].user_id
        if email is None:
            status = "excluded_no_email"
        elif contract.candidate_id in opted:
            status = "excluded_opted_out"
        else:
            status = "pending"
        people.append(
            Person(
                candidate_id=contract.candidate_id,
                contract_id=contract.id,
                client_id=contract.client_id,
                client_name=contract.client_name,
                name=contract.candidate_name or "Konsultant",
                first_name=(first or "").strip() or None,
                email=email,
                form=form,
                end_date=contract.end_date,
                owner_user_id=owner_id,
                owner_name=owner_names.get(owner_id) if owner_id else None,
                status=status,
            )
        )
    return people


async def options(db: AsyncSession, allowed: frozenset[int] | None) -> dict[str, Any]:
    """Listy do wyboru grupy: klienci, opiekunowie, formy, osoby — z liczbą osób."""

    contracts, owners = await people_in_scope(db, allowed)
    contacts = await _contact_rows(db, (c.id for c in contracts))
    owner_names = await care_access.user_names(
        db, (choice.user_id for choice in owners.values())
    )
    clients: dict[int, dict[str, Any]] = {}
    owner_counts: dict[int, int] = {}
    form_counts: dict[str, int] = {}
    for contract in contracts:
        entry = clients.setdefault(
            contract.client_id,
            {"id": contract.client_id, "name": contract.client_name, "consultants": 0},
        )
        entry["consultants"] += 1
        owner_id = owners[contract.id].user_id
        if owner_id is not None:
            owner_counts[owner_id] = owner_counts.get(owner_id, 0) + 1
        form = contacts.get(contract.id, (None, "b2b"))[1]
        form_counts[form] = form_counts.get(form, 0) + 1
    return {
        "clients": sorted(clients.values(), key=lambda row: row["name"]),
        "owners": sorted(
            (
                {"id": uid, "name": owner_names.get(uid, "—"), "consultants": count}
                for uid, count in owner_counts.items()
            ),
            key=lambda row: row["name"],
        ),
        "forms": [
            {
                "value": form,
                "label": terms(form)["form_short"],
                "consultants": form_counts.get(form, 0),
            }
            for form in FORMS
        ],
        "consultants": [
            {
                "candidate_id": contract.candidate_id,
                "name": contract.candidate_name or "Konsultant",
                "client_name": contract.client_name,
            }
            for contract in sorted(contracts, key=lambda c: c.candidate_name or "")
        ],
        "total": len(contracts),
    }


def audience_label(
    audience: Mapping[str, Any],
    *,
    client_names: Mapping[int, str],
    owner_names: Mapping[int, str],
) -> str:
    """„Do kogo” w liście komunikatów (dane z zapisanej grupy)."""

    group = audience.get("group")
    if group == "client":
        names = [client_names.get(cid, "—") for cid in audience.get("client_ids") or []]
        return "klient: " + ", ".join(names)
    if group == "owner":
        names = [
            owner_names.get(uid, "—") for uid in audience.get("owner_user_ids") or []
        ]
        return "opiekun: " + ", ".join(names)
    if group == "form":
        forms = [terms(form)["form_short"] for form in audience.get("forms") or []]
        return "forma: " + ", ".join(forms)
    if group == "ending":
        return f"kończący zamówienie w {audience.get('ending_days')} dni"
    if group == "selected":
        return f"wybrane osoby ({len(audience.get('candidate_ids') or [])})"
    return "wszyscy aktywni konsultanci"
