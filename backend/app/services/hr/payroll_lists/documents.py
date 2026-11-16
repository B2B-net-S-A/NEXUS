"""Pliki do wysyłki ręcznej z zatwierdzonych list płac (K7a): KEDU, zgłoszenia, PIT.

Ten moduł zbiera dane z bazy (``aggregates``, ``registrations``, dane osób)
i oddaje je czystym generatorom formatów (``kedu``, ``pit_forms``,
``forms_pdf``). Pełny PESEL i adres trafiają wyłącznie do pliku; ślad pobrania
zapisuje router (bez numerów).

* **KEDU miesiąca** (DRA + RCA) — zatwierdzone listy z wypłatą w miesiącu.
  Osoba bez danych do plików (identyfikator, imię, nazwisko, kod tytułu)
  blokuje cały plik (409 z listą osób): DRA bez kogoś z RCA byłaby błędna.
* **Zgłoszenia** (ZUA, ZZA, ZWUA) — zdarzenia z zakresu dat. Pozycja bez
  kompletnych danych albo wyrejestrowanie pracownika (tryb i podstawa
  rozwiązania umowy — NEXUS ich nie zna) wypada z pliku z powodem; plik
  powstaje z reszty. Wyrejestrowanie od dnia po ostatnim dniu tytułu.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hr.payroll_errors import PayrollConflict, PayrollNotFound
from app.models.hr_payroll_lists import PayrollParameterVersion
from app.services.hr.payroll_lists import (
    aggregates,
    kedu,
    parameters,
    person_data,
    pit_forms,
    registrations,
    sources,
)
from app.services.hr.payroll_lists.engine import ZERO, age_reached, birthday

CITIZENSHIP = {"PL": "POLSKIE"}


@dataclass(frozen=True)
class Skipped:
    name: str
    kind: str
    reason: str

    def payload(self) -> dict[str, str]:
        return {"name": self.name, "kind": self.kind, "reason": self.reason}


async def _payer(db: AsyncSession) -> kedu.KeduPayer:
    company = await parameters.load_company(db)
    if not company.regon:
        raise PayrollConflict(
            "Uzupełnij REGON płatnika w parametrach płac — bez niego nie ma pliku KEDU.",
            code="company_missing",
        )
    return kedu.KeduPayer(
        nip=company.nip, regon=company.regon, short_name=company.short_name
    )


def kedu_person(data: dict[str, Any]) -> kedu.KeduPerson:
    if data.get("pesel"):
        id_type, number = "P", str(data["pesel"])
    else:
        id_type = "1" if data.get("document_type") == "id_card" else "2"
        number = str(data.get("document_number") or "")
    return kedu.KeduPerson(
        last_name=str(data.get("last_name") or ""),
        first_name=str(data.get("first_name") or ""),
        id_type=id_type,
        id_number=number,
    )


def _missing_for_files(data: Optional[dict[str, Any]], contractor: bool) -> list[str]:
    if data is None:
        return ["person_data"]
    missing = person_data.missing_fields(data, contractor=contractor)
    return [
        code
        for code in missing
        if code in ("identity", "first_name", "last_name", "zus_title_code")
    ]


async def _persons(
    db: AsyncSession, keys: set[str]
) -> dict[str, Optional[dict[str, Any]]]:
    """Dane osób po kluczach list (także ``r<pseudonim>`` po usunięciu kandydata)."""

    records = await person_data.records_by_keys(db, keys)
    out: dict[str, Optional[dict[str, Any]]] = {}
    for key, record in records.items():
        try:
            out[key] = person_data.decrypt(record)
        except person_data.PersonDataError:
            out[key] = None
    return out


async def kedu_month_file(
    db: AsyncSession, *, year: int, month: int, created_on: date
) -> tuple[bytes, str, list[str]]:
    """KEDU (DRA + RCA) za miesiąc wypłaty; nazwa pliku i numery list w środku."""

    declaration = await aggregates.declaration_month(db, year, month)
    if not declaration.list_numbers:
        raise PayrollNotFound("Brak zatwierdzonych list płac z wypłatą w tym miesiącu.")
    payer = await _payer(db)
    persons = await _persons(db, {item.person_key for item in declaration.insured})
    blocked: list[dict[str, Any]] = []
    insured: list[kedu.KeduInsured] = []
    for item in declaration.insured:
        data = persons.get(item.person_key)
        missing = _missing_for_files(data, not item.person_key.startswith("u"))
        if missing or data is None:
            blocked.append(
                {
                    "person": item.name,
                    "missing": [
                        person_data.FIELD_LABELS.get(code, "dane płacowe")
                        for code in missing
                    ],
                }
            )
            continue
        amounts = item.amounts
        insured.append(
            kedu.KeduInsured(
                person=kedu_person(data),
                title_code=str(data["zus_title_code"]),
                pension_basis=amounts["pension_basis"],
                sickness_basis=amounts["sickness_basis"],
                accident_basis=amounts["accident_basis"],
                pension_employee=amounts["pension_employee"],
                disability_employee=amounts["disability_employee"],
                sickness_employee=amounts["sickness_employee"],
                pension_employer=amounts["pension_employer"],
                disability_employer=amounts["disability_employer"],
                accident_employer=amounts["accident_employer"],
                health_basis=amounts["health_basis"],
                health=amounts["health"],
                ppk_employer=amounts["ppk_employer"],
                work_time=person_data.work_time_of(data)
                if item.kind == "uop"
                else None,
                annual_limit_code="2" if "pension_limit" in item.notes else None,
            )
        )
    if blocked:
        raise PayrollConflict(
            "Uzupełnij dane płacowe osób — bez nich nie ma pliku KEDU.",
            code="kedu_data_missing",
            data={"people": blocked},
        )
    if declaration.accident_rate is None:
        raise PayrollConflict(
            "Brak stopy wypadkowej w parametrach list.", code="parameters_invalid"
        )
    content = kedu.render_month(
        kedu.KeduMonth(
            year=year,
            month=month,
            payer=payer,
            insured=insured,
            labour_fund=declaration.labour_fund,
            fgsp=declaration.fgsp,
            accident_rate=declaration.accident_rate,
            created_on=created_on,
        )
    )
    return content, f"kedu-dra-rca-{year}-{month:02d}.xml", declaration.list_numbers


def _address(data: dict[str, Any]) -> Optional[kedu.KeduAddress]:
    address = data.get("address") or {}
    if not address.get("postal_code") or not address.get("city"):
        return None
    return kedu.KeduAddress(
        postal_code=str(address["postal_code"]),
        city=str(address["city"]),
        municipality=str(address.get("commune") or ""),
        street=str(address.get("street") or ""),
        house_number=str(address.get("house_number") or ""),
        flat_number=str(address.get("flat_number") or ""),
    )


def registration_item(
    event: registrations.RegistrationEvent,
) -> tuple[Optional[kedu.KeduRegistration], Optional[str]]:
    """Zdarzenie → pozycja pliku albo powód pominięcia (bez danych osoby)."""

    data = event.data
    if event.problems:
        labels = ", ".join(
            person_data.FIELD_LABELS.get(code, "dane płacowe")
            for code in event.problems
        )
        return None, f"Brakuje: {labels}."
    born = person_data.birth_date_of(data)
    if born is None:
        return None, "Brakuje daty urodzenia."
    person = kedu_person(data)
    title_code = str(data["zus_title_code"])
    sex = person_data.sex_of(data)
    if event.kind == "ZWUA":
        if event.title_kind == "uop":
            return None, (
                "Wyrejestrowanie pracownika wymaga trybu i podstawy rozwiązania umowy "
                "— uzupełnij je w e-Płatniku."
            )
        return (
            kedu.KeduRegistration(
                kind="ZWUA",
                person=person,
                birth_date=born,
                title_code=title_code,
                date_from=event.on + timedelta(days=1),
                sex=sex,
                reason_code="100",
            ),
            None,
        )
    nfz = person_data.nfz_code_of(data)
    if nfz is None:
        return None, "Brakuje oddziału NFZ (województwo w adresie albo kod 01R–16R)."
    flags = person_data.mandate_flags(data)
    social = event.kind == "ZUA"
    uop = event.title_kind == "uop"
    return (
        kedu.KeduRegistration(
            kind=event.kind,
            person=person,
            birth_date=born,
            title_code=title_code,
            date_from=event.on,
            nfz_code=nfz,
            sex=sex,
            citizenship=CITIZENSHIP.get(str(data.get("citizenship") or "PL")),
            address=_address(data),
            pension=social,
            disability=social,
            sickness=social and uop,
            accident=social and (uop or flags["accident_insurance"]),
            voluntary_sickness=social and not uop and flags["sickness_voluntary"],
        ),
        None,
    )


async def registrations_file(
    db: AsyncSession, *, date_from: date, date_to: date, created_on: date
) -> tuple[Optional[bytes], str, list[dict[str, Any]], list[Skipped]]:
    """Zgłoszenia z zakresu dat: plik (``None``, gdy nic nie przeszło), lista, pominięte."""

    if date_to < date_from or (date_to - date_from).days > 92:
        raise PayrollConflict(
            "Zakres zgłoszeń: najwyżej kwartał, koniec nie przed początkiem.",
            code="bad_range",
        )
    found = await registrations.events(db, date_from, date_to)
    items: list[kedu.KeduRegistration] = []
    skipped: list[Skipped] = []
    for event in found:
        item, reason = registration_item(event)
        if item is None:
            skipped.append(Skipped(event.name, event.kind, reason or ""))
        else:
            items.append(item)
    content = None
    if items:
        content = kedu.render_registrations(await _payer(db), items, created_on)
    name = f"kedu-zgloszenia-{date_from.isoformat()}-{date_to.isoformat()}.xml"
    return content, name, [registrations.event_payload(e) for e in found], skipped


# ── PIT-11, PIT-4R, PIT-8AR ──────────────────────────────────────────────────


@dataclass
class PersonYear:
    person_key: str
    user_id: Optional[int]
    candidate_id: Optional[int]
    name: str
    entries: list[pit_forms.Pit11Entry] = field(default_factory=list)


@dataclass
class TaxYearData:
    year: int
    people: list[PersonYear]
    pit4r: dict[int, pit_forms.Pit4rMonth]
    pit8ar: dict[int, Decimal]
    from_opening: bool


async def _tax_payer(db: AsyncSession) -> pit_forms.TaxPayer:
    company = await parameters.load_company(db)
    if not company.tax_office_code:
        raise PayrollConflict(
            "Uzupełnij kod urzędu skarbowego płatnika w parametrach płac.",
            code="company_missing",
        )
    return pit_forms.TaxPayer(
        nip=company.nip,
        full_name=company.name,
        tax_office_code=company.tax_office_code,
    )


def _opening_entries(amounts: dict[str, Any]) -> list[pit_forms.Pit11Entry]:
    """Otwarcie roku z Enovy → pozycje syntetyczne (zwolnienie = ulga dla młodych)."""

    out: list[pit_forms.Pit11Entry] = []
    for prefix, kind in (("uop", "uop"), ("mandate", "zlecenie")):
        revenue = aggregates.d(amounts.get(f"{prefix}_revenue"))
        if revenue <= 0:
            continue
        social = aggregates.d(amounts.get(f"{prefix}_social"))
        exempt = aggregates.d(amounts.get(f"{prefix}_exempt"))
        out.append(
            pit_forms.Pit11Entry(
                kind=kind,
                revenue=revenue,
                exempt_revenue=exempt,
                kup=aggregates.d(amounts.get(f"{prefix}_kup")),
                advance=aggregates.d(amounts.get(f"{prefix}_advance")),
                social=social,
                social_deductible=social
                - aggregates.d(amounts.get(f"{prefix}_social_exempt")),
                health=aggregates.d(amounts.get(f"{prefix}_health")),
                relief="youth" if exempt > 0 else None,
            )
        )
    return out


async def tax_year_data(db: AsyncSession, year: int) -> TaxYearData:
    """Pozycje PIT-11 osób oraz miesiące PIT-4R i PIT-8AR (miesiąc = wypłata)."""

    rows = await sources.approved_lines(db, year=year)
    openings = await sources.openings(db, year)
    keys = {sources.person_key(line) for _l, line in rows} | set(openings)
    persons = await _persons(db, keys)
    versions: dict[int, dict[str, Any]] = {}
    people: dict[str, PersonYear] = {}
    pit4r: dict[int, list[Any]] = defaultdict(lambda: [ZERO, ZERO, set()])
    pit8ar: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for key, opening in openings.items():
        people[key] = PersonYear(
            key,
            opening.user_id,
            opening.candidate_id,
            "",
            _opening_entries(opening.amounts or {}),
        )
    for lst, line in rows:
        result = line.result or {}
        if not result:
            continue
        if lst.parameter_version_id not in versions:
            version = await db.get(PayrollParameterVersion, lst.parameter_version_id)
            versions[lst.parameter_version_id] = dict(version.params) if version else {}
        params = versions[lst.parameter_version_id]
        key = sources.person_key(line)
        person = people.setdefault(
            key, PersonYear(key, line.user_id, line.candidate_id, line.person_name)
        )
        person.name = person.name or line.person_name
        data = persons.get(key) or {}
        born = person_data.birth_date_of(data)
        sex = person_data.sex_of(data)
        senior_years = int(
            params.get("senior_age_female" if sex == "F" else "senior_age_male") or 65
        )
        youth_years = int(params.get("youth_age") or 26)
        flat = result.get("tax_kind") == "flat"
        person.entries.append(
            pit_forms.Pit11Entry(
                kind=line.kind,
                revenue=aggregates.d(result.get("revenue")),
                exempt_revenue=aggregates.d(result.get("exempt_revenue")),
                kup=aggregates.d(result.get("kup")),
                advance=aggregates.d(result.get("pit")),
                social=aggregates.d(result.get("social_employee")),
                social_deductible=aggregates.d(result.get("social_deductible")),
                health=aggregates.d(result.get("health")),
                flat_tax=flat,
                relief=pit_forms.relief_from_notes(result.get("notes") or []),
                under26=bool(born and lst.pay_date <= birthday(born, youth_years)),
                senior_age=bool(
                    sex in ("F", "M")
                    and age_reached(born, senior_years, lst.pay_date)
                    and aggregates.d(result.get("social_employee")) > 0
                ),
            )
        )
        month = lst.pay_date.month
        if flat:
            pit8ar[month] += aggregates.d(result.get("pit"))
        elif result.get("tax_kind") == "scale":
            bucket = pit4r[month]
            if line.kind == "uop":
                bucket[0] += aggregates.d(result.get("pit"))
                bucket[2].add(key)
            else:
                bucket[1] += aggregates.d(result.get("pit"))
    return TaxYearData(
        year=year,
        people=sorted(people.values(), key=lambda p: (p.name.casefold(), p.person_key)),
        pit4r={
            month: pit_forms.Pit4rMonth(
                employment_advances=values[0],
                mandate_advances=values[1],
                employment_taxpayers=len(values[2]),
            )
            for month, values in sorted(pit4r.items())
        },
        pit8ar=dict(sorted(pit8ar.items())),
        from_opening=bool(openings),
    )


def pit11_person(data: dict[str, Any]) -> pit_forms.Pit11Person:
    address = data.get("address") or {}
    born = person_data.birth_date_of(data)
    if born is None:
        raise PayrollConflict("Brakuje daty urodzenia.", code="pit_data_missing")
    return pit_forms.Pit11Person(
        last_name=str(data.get("last_name") or ""),
        first_name=str(data.get("first_name") or ""),
        birth_date=born,
        tax_office_code=str(data.get("tax_office_code") or ""),
        pesel=data.get("pesel"),
        nip=None if data.get("pesel") else data.get("nip"),
        address=pit_forms.PersonAddress(
            city=str(address.get("city") or ""),
            country_code=str(address.get("country") or "PL"),
            voivodeship=str(address.get("voivodeship") or ""),
            county=str(address.get("county") or ""),
            municipality=str(address.get("commune") or ""),
            street=str(address.get("street") or ""),
            house_number=str(address.get("house_number") or ""),
            flat_number=str(address.get("flat_number") or ""),
            postal_code=str(address.get("postal_code") or ""),
        )
        if address
        else None,
    )


def pit11_missing(data: Optional[dict[str, Any]], contractor: bool) -> list[str]:
    if data is None:
        return ["person_data"]
    missing = person_data.missing_fields(data, contractor=contractor)
    out = [
        c
        for c in missing
        if c in ("identity", "first_name", "last_name", "address", "tax_office_code")
    ]
    if not data.get("pesel") and not data.get("nip"):
        out.append("nip")
    return out


@dataclass(frozen=True)
class Pit11File:
    person_key: str
    name: str
    document: Optional[pit_forms.FormDocument]
    missing: list[str]


async def pit11_documents(db: AsyncSession, year: int) -> list[Pit11File]:
    data_year = await tax_year_data(db, year)
    payer = await _tax_payer(db)
    persons = await _persons(db, {p.person_key for p in data_year.people})
    out: list[Pit11File] = []
    for person in data_year.people:
        entries = [e for e in person.entries if not e.flat_tax]
        if not entries:
            continue
        data = persons.get(person.person_key)
        missing = pit11_missing(data, not person.person_key.startswith("u"))
        if missing or data is None:
            out.append(Pit11File(person.person_key, person.name, None, missing))
            continue
        kup_code = 3 if data.get("kup") == "increased" else 1
        amounts = pit_forms.pit11_amounts(entries, kup_code=kup_code)
        document = pit_forms.pit11_document(year, payer, pit11_person(data), amounts)
        out.append(Pit11File(person.person_key, person.name, document, []))
    return out


async def pit4r_document(db: AsyncSession, year: int) -> pit_forms.FormDocument:
    data_year = await tax_year_data(db, year)
    if not data_year.pit4r:
        raise PayrollNotFound("Brak zaliczek z zatwierdzonych list w tym roku.")
    return pit_forms.pit4r_document(year, await _tax_payer(db), data_year.pit4r)


async def pit8ar_document(db: AsyncSession, year: int) -> pit_forms.FormDocument:
    data_year = await tax_year_data(db, year)
    if not data_year.pit8ar:
        raise PayrollNotFound(
            "Brak podatku ryczałtowego z zatwierdzonych list w tym roku."
        )
    return pit_forms.pit8ar_document(year, await _tax_payer(db), data_year.pit8ar)


__all__ = [
    "Pit11File",
    "PersonYear",
    "TaxYearData",
    "pit11_documents",
    "pit11_missing",
    "pit11_person",
    "pit4r_document",
    "pit8ar_document",
    "tax_year_data",
    "Skipped",
    "kedu_month_file",
    "kedu_person",
    "registration_item",
    "registrations_file",
]
