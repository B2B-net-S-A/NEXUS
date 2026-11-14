"""Sumy zatwierdzonych list płac pod pliki urzędowe (K7a) — bez formatu plików.

* **Miesiąc deklaracji ZUS** = miesiąc daty wypłaty: wszystkie zatwierdzone
  listy z wypłatą w tym miesiącu. Ubezpieczony = osoba × kod tytułu; pozycje
  osoby z tym samym kodem (np. dwa zlecenia u klientów) sumują się w jednym
  bloku RCA. Składki są już zaokrąglone na pozycjach — tu tylko sumy.
* **Rok PIT** = rok daty wypłaty: otwarcie roku z Enovy + zatwierdzone listy.
  UoP idzie do przychodów ze stosunku pracy (z wpłatą pracodawcy PPK), zlecenie
  i dzieło do art. 13 pkt 8; podatek ryczałtowy (do 200 zł) osobno — PIT-8AR.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_payroll_lists import (
    PayrollList,
    PayrollListLine,
    PayrollParameterVersion,
)
from app.services.hr.payroll_lists.engine import ZERO
from app.services.hr.payroll_lists.sources import openings, person_key
from app.services.hr.payroll_periods import month_end

#: Sumy składek na bloku RCA (klucze wyniku silnika).
ZUS_FIELDS: tuple[str, ...] = (
    "pension_basis",
    "sickness_basis",
    "accident_basis",
    "health_basis",
    "pension_employee",
    "pension_employer",
    "disability_employee",
    "disability_employer",
    "sickness_employee",
    "accident_employer",
    "health",
    "labour_fund",
    "fgsp",
    "ppk_employer",
)
#: ``social`` — wszystkie składki społeczne osoby, ``social_exempt`` — ich część
#: od przychodu zwolnionego (ulgi), której nie odlicza się od dochodu.
PIT_FIELDS: tuple[str, ...] = (
    "revenue",
    "kup",
    "social",
    "social_exempt",
    "health",
    "advance",
    "exempt",
)


def d(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw if raw not in (None, "") else "0"))
    except ArithmeticError:
        return ZERO


@dataclass
class InsuredMonth:
    person_key: str
    kind: str
    user_id: Optional[int]
    candidate_id: Optional[int]
    name: str
    amounts: dict[str, Decimal] = field(
        default_factory=lambda: {key: ZERO for key in ZUS_FIELDS}
    )
    insured: bool = False  # czy pozycja podlega jakimkolwiek składkom
    notes: set[str] = field(default_factory=set)
    parameter_version_ids: set[int] = field(default_factory=set)


@dataclass
class DeclarationMonth:
    year: int
    month: int
    list_numbers: list[str]
    accident_rate: Optional[Decimal]
    insured: list[InsuredMonth]

    @property
    def labour_fund(self) -> Decimal:
        return sum((item.amounts["labour_fund"] for item in self.insured), ZERO)

    @property
    def fgsp(self) -> Decimal:
        return sum((item.amounts["fgsp"] for item in self.insured), ZERO)


async def approved_in_month(
    db: AsyncSession, year: int, month: int
) -> list[PayrollList]:
    return list(
        await db.scalars(
            select(PayrollList)
            .where(
                PayrollList.status == "approved",
                PayrollList.pay_date >= date(year, month, 1),
                PayrollList.pay_date <= month_end(year, month),
            )
            .order_by(PayrollList.pay_date, PayrollList.id)
        )
    )


async def declaration_month(
    db: AsyncSession, year: int, month: int
) -> DeclarationMonth:
    lists = await approved_in_month(db, year, month)
    by_key: dict[tuple[str, str], InsuredMonth] = {}
    accident_rate: Optional[Decimal] = None
    for lst in lists:
        for line in await db.scalars(
            select(PayrollListLine)
            .where(PayrollListLine.list_id == lst.id)
            .order_by(PayrollListLine.id)
        ):
            result = line.result or {}
            if not result:
                continue
            key = (person_key(line), line.kind)
            item = by_key.get(key)
            if item is None:
                item = InsuredMonth(
                    person_key=key[0],
                    kind=line.kind,
                    user_id=line.user_id,
                    candidate_id=line.candidate_id,
                    name=line.person_name,
                )
                by_key[key] = item
            for name in ZUS_FIELDS:
                item.amounts[name] += d(result.get(name))
            if d(result.get("zus_due")) > 0:
                item.insured = True
            item.notes.update(result.get("notes") or [])
            item.parameter_version_ids.add(lst.parameter_version_id)
    if lists:
        # Stopa wypadkowa z parametrów ostatniej listy miesiąca (jedna na DRA).
        version = await db.get(PayrollParameterVersion, lists[-1].parameter_version_id)
        if version is not None and version.params.get("accident_employer_rate"):
            accident_rate = d(version.params["accident_employer_rate"])
    insured = sorted(
        (item for item in by_key.values() if item.insured),
        key=lambda item: (item.name.casefold(), item.person_key, item.kind),
    )
    return DeclarationMonth(
        year=year,
        month=month,
        list_numbers=[lst.number for lst in lists],
        accident_rate=accident_rate,
        insured=insured,
    )


@dataclass
class PitYear:
    person_key: str
    user_id: Optional[int]
    candidate_id: Optional[int]
    name: str
    employment: dict[str, Decimal] = field(
        default_factory=lambda: {key: ZERO for key in PIT_FIELDS}
    )
    mandate: dict[str, Decimal] = field(
        default_factory=lambda: {key: ZERO for key in PIT_FIELDS}
    )
    ppk_employer_revenue: Decimal = ZERO
    flat_tax: Decimal = ZERO
    flat_revenue: Decimal = ZERO
    from_opening: bool = False


@dataclass
class TaxYear:
    year: int
    people: list[PitYear]
    #: miesiąc wypłaty → (zaliczki UoP, zaliczki art. 13 pkt 8)
    advances: dict[int, tuple[Decimal, Decimal]]
    #: miesiąc wypłaty → podatek ryczałtowy (art. 30 ust. 1 pkt 5a)
    flat_taxes: dict[int, Decimal]


def _add_line(person: PitYear, kind: str, result: dict[str, Any]) -> None:
    if result.get("tax_kind") == "flat":
        person.flat_tax += d(result.get("pit"))
        person.flat_revenue += d(result.get("revenue"))
        return
    bucket = person.employment if kind == "uop" else person.mandate
    bucket["revenue"] += d(result.get("revenue"))
    bucket["kup"] += d(result.get("kup"))
    bucket["social"] += d(result.get("social_employee"))
    bucket["social_exempt"] += d(result.get("social_employee")) - d(
        result.get("social_deductible")
    )
    bucket["health"] += d(result.get("health"))
    bucket["advance"] += d(result.get("pit"))
    bucket["exempt"] += d(result.get("exempt_revenue"))
    if kind == "uop":
        person.ppk_employer_revenue += d(result.get("ppk_employer_taxable"))


async def tax_year(db: AsyncSession, year: int) -> TaxYear:
    people: dict[str, PitYear] = {}
    advances: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    flat_taxes: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for key, opening in (await openings(db, year)).items():
        amounts = opening.amounts or {}
        person = PitYear(
            person_key=key,
            user_id=opening.user_id,
            candidate_id=opening.candidate_id,
            name="",
            from_opening=True,
        )
        for prefix, bucket in (("uop", person.employment), ("mandate", person.mandate)):
            for name in PIT_FIELDS:
                bucket[name] += d(amounts.get(f"{prefix}_{name}"))
        person.flat_tax += d(amounts.get("flat_tax"))
        people[key] = person
    lists = list(
        await db.scalars(
            select(PayrollList)
            .where(
                PayrollList.status == "approved",
                PayrollList.pay_date >= date(year, 1, 1),
                PayrollList.pay_date <= date(year, 12, 31),
            )
            .order_by(PayrollList.pay_date, PayrollList.id)
        )
    )
    for lst in lists:
        for line in await db.scalars(
            select(PayrollListLine)
            .where(PayrollListLine.list_id == lst.id)
            .order_by(PayrollListLine.id)
        ):
            result = line.result or {}
            if not result:
                continue
            key = person_key(line)
            person = people.get(key)
            if person is None:
                person = PitYear(
                    person_key=key,
                    user_id=line.user_id,
                    candidate_id=line.candidate_id,
                    name=line.person_name,
                )
                people[key] = person
            if not person.name:
                person.name = line.person_name
            _add_line(person, line.kind, result)
            month = lst.pay_date.month
            if result.get("tax_kind") == "flat":
                flat_taxes[month] += d(result.get("pit"))
            elif line.kind == "uop":
                advances[month][0] += d(result.get("pit"))
            else:
                advances[month][1] += d(result.get("pit"))
    return TaxYear(
        year=year,
        people=sorted(people.values(), key=lambda p: (p.name.casefold(), p.person_key)),
        advances={
            month: (pair[0], pair[1]) for month, pair in sorted(advances.items())
        },
        flat_taxes=dict(sorted(flat_taxes.items())),
    )


__all__ = [
    "DeclarationMonth",
    "InsuredMonth",
    "PIT_FIELDS",
    "PitYear",
    "TaxYear",
    "ZUS_FIELDS",
    "approved_in_month",
    "d",
    "declaration_month",
    "tax_year",
]
