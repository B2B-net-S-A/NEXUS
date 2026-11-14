"""Lista płac miesiąca (K7a): „Przelicz”, zatwierdzenie drugą osobą, anulowanie.

* **Przelicz** (Płace) — miesiąc Płac musi być zamknięty (linie zamrożone).
  Lista bierze parametry obowiązujące w dniu wypłaty (domyślnie dzień wypłaty
  z Ustawień → Płace w miesiącu po okresie), dane płacowe osób, stan roku
  i liczy pozycje silnikiem. Szkic można przeliczać dowolnie; zatwierdzonej nie.
  Przeliczenie listy z wypłatą wcześniejszą niż już zatwierdzona lista tego roku
  = 409 (limity narastające by się rozjechały).
* **Zatwierdź** — druga osoba z Płac: nie ta, która liczyła listę, i bez
  własnej pozycji na liście (403). Zatwierdzenie zbiera dane jeszcze raz;
  inny skrót niż przy przeliczeniu = 409 „przelicz listę”. Problemy
  blokujące (brak kwoty, brak danych osoby, parametry niepotwierdzone albo
  z poprzedniego roku) = 409 z listą problemów.
* **Anuluj** — z powodem; zatwierdzonej nie anuluje się, gdy jest zatwierdzona
  lista z późniejszą wypłatą w tym roku albo wypłata jest oznaczona jako
  wykonana. Kolejna lista okresu dostaje numer z przyrostkiem (``LP/RRRR/MM/2``).
* **Kwoty Płac** (``payroll_gross_inputs``) i **otwarcie roku**
  (``payroll_year_openings``) zmienia osoba z Płac — nie swoje (403, admin może).

Kwoty pozycji widzą tylko Płace i administrator (D2) — bramka w routerze.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.contract import Contract, ContractType
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_payroll_lists import (
    PayrollGrossInput,
    PayrollList,
    PayrollListLine,
    PayrollParameterVersion,
    PayrollYearOpening,
)
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr import audit
from app.services.hr.bank import settings as bank_settings
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollError,
    PayrollForbidden,
    PayrollNotFound,
)
from app.services.hr.payroll_lists import engine, parameters, person_data, sources
from app.services.hr.payroll_lists import params as params_rules
from app.services.hr.payroll_lists.engine import ZERO, Result, Title, YearToDate
from app.services.hr.payroll_lists.person_data import Subject
from app.services.hr.payroll_periods import (
    add_months,
    get_period,
    lock_period_shared,
    month_end,
    month_start,
    validate_period,
)
from app.services.hr_payroll_lists_schema import GROSS_MAX, NOTE_MAX
from app.services.ledger.closing import next_business_day

#: Problem → (zdanie na ekranie, blokuje zatwierdzenie).
PROBLEMS: dict[str, tuple[str, bool]] = {
    "params_to_confirm": ("Parametry płac czekają na potwierdzenie Płac.", True),
    "params_previous_year": (
        "Parametry płac są z poprzedniego roku — dodaj wersję od 1 stycznia.",
        True,
    ),
    "person_data_missing": (
        "Brak danych płacowych osoby — PESEL, PIT-2, koszty, ulgi.",
        True,
    ),
    "person_data_unreadable": ("Nie udało się odczytać danych płacowych osoby.", True),
    "identity": ("Brak PESEL-u albo dokumentu z datą urodzenia i płcią.", True),
    "first_name": ("Brak imienia w danych płacowych.", True),
    "last_name": ("Brak nazwiska w danych płacowych.", True),
    "gross_missing": (
        "Brak kwoty brutto — wpisz ją albo przyjmij rozliczenie klienta.",
        True,
    ),
    "settlement_not_accepted": (
        "Rozliczenie klienta za ten miesiąc nie jest przyjęte — przyjmij je albo wpisz kwotę.",
        True,
    ),
    "rate_missing": ("Godziny bez stawki — wpisz kwotę brutto.", True),
    "currency": (
        "Kwota w innej walucie niż złoty — wpisz kwotę brutto w złotych.",
        True,
    ),
    "mandate_own_employer": (
        "Zlecenie u własnego pracodawcy — składki jak z umowy o pracę; wpisz kwotę "
        "łącznie jako UoP.",
        True,
    ),
    "employment_type_missing": ("Osoba bez formy współpracy w kartotece.", True),
    "contract_without_person": (
        "Kontrakt zleceniowy bez kandydata — nie wiadomo, komu wypłacić.",
        True,
    ),
    "skipped_zero": (
        "Kwota 0 wpisana przez Płace — osoba pominięta w tym miesiącu.",
        False,
    ),
    "files_data": (
        "Brakuje danych do KEDU i PIT-11 (adres, urząd, kod tytułu).",
        False,
    ),
}
KINDS_LABEL = {"uop": "Umowa o pracę", "zlecenie": "Zlecenie", "dzielo": "Dzieło"}
SOURCE_LABEL = {
    "payroll_line": "„Mój miesiąc” i premie",
    "client_settlement": "rozliczenie klienta",
    "manual": "kwota wpisana przez Płace",
    "missing": "brak kwoty",
}
TOTAL_FIELDS: tuple[str, ...] = (
    "gross",
    "net",
    "social_employee",
    "health",
    "pit",
    "employer_social",
    "pension_employer",
    "disability_employer",
    "accident_employer",
    "labour_fund",
    "fgsp",
    "zus_due",
    "ppk_employee",
    "ppk_employer",
    "employer_cost",
)


def blocking(code: str) -> bool:
    return PROBLEMS.get(code, ("", True))[1]


def problem_view(code: str) -> dict[str, Any]:
    label, block = PROBLEMS.get(code, (code, True))
    return {"code": code, "label": label, "blocking": block}


# ── Daty ─────────────────────────────────────────────────────────────────────


def default_pay_date(year: int, month: int, payout_day: int) -> date:
    following = add_months(year, month, 1)
    last = month_end(*following).day
    return date(following[0], following[1], min(payout_day, last))


def check_pay_date(year: int, month: int, pay: date) -> date:
    latest = month_end(*add_months(year, month, 2))
    if not month_start(year, month) <= pay <= latest:
        raise PayrollError(
            "Data wypłaty: od początku miesiąca pracy do końca drugiego miesiąca po nim."
        )
    return pay


def deadlines(pay: date) -> dict[str, str]:
    """ZUS i PPK do 15., zaliczki PIT do 20. miesiąca po wypłacie (dzień roboczy)."""

    year, month = add_months(pay.year, pay.month, 1)
    return {
        "pay_date": pay.isoformat(),
        "zus": next_business_day(date(year, month, 15)).isoformat(),
        "ppk": next_business_day(date(year, month, 15)).isoformat(),
        "pit": next_business_day(date(year, month, 20)).isoformat(),
        "declaration_month": f"{pay.year}-{pay.month:02d}",
    }


# ── Zebranie danych ──────────────────────────────────────────────────────────


@dataclass
class Prepared:
    period: PayrollPeriod
    pay_date: date
    version: PayrollParameterVersion
    params: params_rules.Params
    gathered: sources.Gathered
    persons: dict[str, dict[str, Any]] = field(default_factory=dict)
    person_versions: dict[str, int] = field(default_factory=dict)
    unreadable: set[str] = field(default_factory=set)
    profiles: dict[int, EmployeeProfile] = field(default_factory=dict)
    ytd: dict[str, YearToDate] = field(default_factory=dict)
    ppk: dict[str, Decimal] = field(default_factory=dict)
    ppk_list_id: Optional[int] = None
    list_problems: list[dict[str, Any]] = field(default_factory=list)
    source_hash: str = ""


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


async def collect(
    db: AsyncSession,
    period: PayrollPeriod,
    pay: date,
    *,
    exclude_list_id: Optional[int],
) -> Prepared:
    version = await parameters.version_for(db, pay)
    if version is None:
        raise PayrollConflict(
            "Brak parametrów płac na dzień wypłaty — dodaj je w parametrach płac.",
            code="parameters_missing",
        )
    try:
        params = params_rules.parse(version.params)
    except params_rules.ParamsError as exc:
        raise PayrollConflict(
            f"Parametry płac są niepoprawne: {exc.message}", code="parameters_invalid"
        ) from None
    gathered = await sources.gather(db, period)
    prepared = Prepared(
        period=period, pay_date=pay, version=version, params=params, gathered=gathered
    )
    list_problems = [dict(item) for item in gathered.problems]
    if version.status != "confirmed":
        list_problems.append({"code": "params_to_confirm", "blocking": True})
    if version.effective_from.year < pay.year:
        list_problems.append({"code": "params_previous_year", "blocking": True})
    user_ids = {s.user_id for s in gathered.sources if s.user_id is not None}
    candidate_ids = {
        s.candidate_id for s in gathered.sources if s.candidate_id is not None
    }
    records = await person_data.records_for(db, user_ids, candidate_ids)
    for key, record in records.items():
        prepared.person_versions[key] = record.version
        try:
            prepared.persons[key] = person_data.decrypt(record)
        except person_data.PersonDataError:
            prepared.unreadable.add(key)
    if user_ids:
        prepared.profiles = {
            profile.user_id: profile
            for profile in await db.scalars(
                select(EmployeeProfile).where(EmployeeProfile.user_id.in_(user_ids))
            )
        }
    prepared.ytd = await sources.year_to_date(
        db, year=pay.year, up_to=pay, exclude_list_id=exclude_list_id
    )
    prepared.ppk_list_id, prepared.ppk = await sources.previous_ppk_employer(
        db, before=pay, exclude_list_id=exclude_list_id
    )
    prepared.list_problems = list_problems
    prepared.source_hash = hashlib.sha256(
        _canonical(
            {
                "period": [period.id, period.year, period.month, period.close_count],
                "pay_date": pay.isoformat(),
                "version": version.id,
                "sources": [s.fingerprint() for s in gathered.sources],
                "problems": gathered.problems,
                "persons": prepared.person_versions,
                "unreadable": sorted(prepared.unreadable),
                "students": {
                    str(uid): [
                        bool(p.student_contribution_exempt),
                        p.contribution_exempt_until.isoformat()
                        if p.contribution_exempt_until
                        else None,
                    ]
                    for uid, p in sorted(prepared.profiles.items())
                },
                "ytd": {key: s.to_json() for key, s in sorted(prepared.ytd.items())},
                "ppk": {key: str(v) for key, v in sorted(prepared.ppk.items())},
                "ppk_list": prepared.ppk_list_id,
            }
        ).encode()
    ).hexdigest()
    return prepared


@dataclass
class Computed:
    source: sources.Source
    result: Optional[Result]
    problems: list[str]
    missing_files: list[str]


def calculate(prepared: Prepared) -> list[Computed]:
    """Silnik po osobach: UoP przed zleceniem, stan roku przechodzi z pozycji na pozycję."""

    params = prepared.params
    first = month_start(prepared.period.year, prepared.period.month)
    last = month_end(prepared.period.year, prepared.period.month)
    by_person: OrderedDict[str, list[sources.Source]] = OrderedDict()
    for item in prepared.gathered.sources:
        by_person.setdefault(item.person_key, []).append(item)
    out: list[Computed] = []
    for key, items in by_person.items():
        data = prepared.persons.get(key)
        person_problems: list[str] = []
        missing_files: list[str] = []
        if key in prepared.unreadable:
            person_problems.append("person_data_unreadable")
        elif data is None:
            person_problems.append("person_data_missing")
        else:
            missing = person_data.missing_fields(data, contractor=key.startswith("c"))
            person_problems.extend(person_data.blocks_calculation(missing))
            missing_files = [
                code for code in missing if code in person_data.FILE_FIELDS
            ]
            if missing_files:
                person_problems.append("files_data")
        user_id = items[0].user_id
        profile = prepared.profiles.get(user_id) if user_id is not None else None
        tax = person_data.person_tax(data or {}, profile, youth_age=params.youth_age)
        flags = person_data.mandate_flags(data or {})
        has_uop = any(item.kind == "uop" for item in items)
        fund_basis = sum(
            (
                item.gross
                for item in items
                if item.kind in ("uop", "zlecenie") and item.gross
            ),
            ZERO,
        )
        state = prepared.ytd.get(key, YearToDate())
        ppk_taxable = prepared.ppk.get(key, ZERO)
        for item in items:
            problems = list(dict.fromkeys([*item.problems, *person_problems]))
            if has_uop and item.kind == "zlecenie":
                problems.append("mandate_own_employer")
            if item.gross is None:
                out.append(Computed(item, None, problems, missing_files))
                continue
            title = Title(
                kind=item.kind,
                gross=item.gross,
                work_start=first,
                work_end=last,
                pay_date=prepared.pay_date,
                pension_insurance=flags["pension_insurance"],
                sickness_voluntary=flags["sickness_voluntary"],
                accident_insurance=flags["accident_insurance"],
                flat_tax_allowed=not has_uop,
                ppk_employer_taxable=ppk_taxable,
                labour_fund_basis=fund_basis,
            )
            ppk_taxable = ZERO
            result = engine.calculate(title, tax, state, params)
            state = result.ytd_after
            out.append(Computed(item, result, problems, missing_files))
    return out


def totals_of(computed: list[Computed], pay: date) -> dict[str, Any]:
    sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_kind: dict[str, dict[str, Any]] = {}
    people: set[str] = set()
    flat = ZERO
    for item in computed:
        people.add(item.source.person_key)
        kind = by_kind.setdefault(item.source.kind, {"lines": 0, "gross": ZERO})
        kind["lines"] += 1
        if item.result is None:
            continue
        kind["gross"] += item.result.gross
        for name in TOTAL_FIELDS:
            sums[name] += getattr(item.result, name)
        if item.result.tax_kind == "flat":
            flat += item.result.pit
    return {
        "people": len(people),
        "lines": len(computed),
        **{name: str(sums[name]) for name in TOTAL_FIELDS},
        "pit_scale": str(sums["pit"] - flat),
        "pit_flat": str(flat),
        "by_kind": {
            kind: {"lines": data["lines"], "gross": str(data["gross"])}
            for kind, data in sorted(by_kind.items())
        },
        "deadlines": deadlines(pay),
    }


def blocking_problems(
    prepared: Prepared, computed: list[Computed]
) -> list[dict[str, Any]]:
    out = [item for item in prepared.list_problems if item.get("blocking")]
    for item in computed:
        for code in item.problems:
            if blocking(code):
                out.append({"code": code, "person": item.source.name, "blocking": True})
    return out


# ── Odczyt ───────────────────────────────────────────────────────────────────


async def live_list(
    db: AsyncSession, period_id: int, *, lock: bool = False
) -> Optional[PayrollList]:
    query = select(PayrollList).where(
        PayrollList.period_id == period_id, PayrollList.status != "cancelled"
    )
    if lock:
        query = query.with_for_update()
    return await db.scalar(query)


async def get_list(
    db: AsyncSession, list_id: int, *, lock: bool = False
) -> PayrollList:
    query = select(PayrollList).where(PayrollList.id == list_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    found = await db.scalar(query)
    if found is None:
        raise PayrollNotFound("Nie ma takiej listy płac.")
    return found


async def lines_of(db: AsyncSession, list_id: int) -> list[PayrollListLine]:
    return list(
        await db.scalars(
            select(PayrollListLine)
            .where(PayrollListLine.list_id == list_id)
            .order_by(PayrollListLine.id)
        )
    )


async def _number(db: AsyncSession, period: PayrollPeriod) -> str:
    base = f"LP/{period.year}/{period.month:02d}"
    count = len(
        list(
            await db.scalars(
                select(PayrollList.id).where(PayrollList.period_id == period.id)
            )
        )
    )
    return base if count == 0 else f"{base}/{count + 1}"


# ── Przelicz ─────────────────────────────────────────────────────────────────


async def compute(
    db: AsyncSession,
    *,
    actor: User,
    year: int,
    month: int,
    pay_date: Optional[date],
) -> PayrollList:
    """Liczy szkic listy okresu (bez commita)."""

    validate_period(year, month)
    period = await lock_period_shared(db, year, month)
    if period.status != "closed":
        raise PayrollConflict(
            "Najpierw zamknij miesiąc w Płacach — lista liczy się z zamrożonych linii.",
            code="period_open",
        )
    current = await live_list(db, period.id, lock=True)
    if current is not None and current.status == "approved":
        raise PayrollConflict(
            "Lista jest zatwierdzona — żeby policzyć ją od nowa, najpierw ją anuluj.",
            code="list_approved",
        )
    if pay_date is None:
        payout_day = (await bank_settings.load_settings(db)).payout_day
        pay = current.pay_date if current else default_pay_date(year, month, payout_day)
    else:
        pay = check_pay_date(year, month, pay_date)
    exclude = current.id if current else None
    later = await sources.later_approved(
        db, year=pay.year, after=pay, exclude_list_id=exclude
    )
    if later is not None:
        raise PayrollConflict(
            f"Jest zatwierdzona lista {later.number} z późniejszą wypłatą — limity "
            "narastające by się rozjechały. Anuluj ją albo zmień datę wypłaty.",
            code="later_list_approved",
        )
    prepared = await collect(db, period, pay, exclude_list_id=exclude)
    computed = calculate(prepared)
    problems = [
        *prepared.list_problems,
        *(
            {"code": code, "person": item.source.name, "blocking": blocking(code)}
            for item in computed
            for code in item.problems
        ),
    ]
    if current is None:
        current = PayrollList(
            period_id=period.id,
            year=year,
            month=month,
            number=await _number(db, period),
            status="draft",
            pay_date=pay,
            parameter_version_id=prepared.version.id,
        )
        db.add(current)
        await db.flush()
    else:
        await db.execute(
            delete(PayrollListLine).where(PayrollListLine.list_id == current.id)
        )
    current.pay_date = pay
    current.parameter_version_id = prepared.version.id
    current.totals = totals_of(computed, pay)
    current.problems = problems
    current.source_hash = prepared.source_hash
    current.computed_by = actor.id
    current.computed_at = local_now()
    for item in computed:
        result = item.result
        db.add(
            PayrollListLine(
                list_id=current.id,
                user_id=item.source.user_id,
                candidate_id=item.source.candidate_id,
                contract_id=item.source.contract_id,
                person_name=item.source.name[:255],
                kind=item.source.kind,
                source=item.source.source,
                gross=result.gross if result else None,
                net=result.net if result else None,
                pit=result.pit if result else None,
                social_employee=result.social_employee if result else None,
                health=result.health if result else None,
                employer_social=result.employer_social if result else None,
                employer_cost=result.employer_cost if result else None,
                basis={**item.source.basis, "missing_files": item.missing_files},
                result=result.to_json() if result else {},
                problems=item.problems,
            )
        )
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_list",
        entity_id=current.id,
        action="payroll_list_computed",
        sensitivity="payroll",
        details={
            "number": current.number,
            "lines": len(computed),
            "blocking": sum(1 for p in problems if p.get("blocking")),
            "parameter_version_id": prepared.version.id,
        },
    )
    return current


# ── Zatwierdź i anuluj ───────────────────────────────────────────────────────


async def approval_refusal(
    db: AsyncSession, actor: User, lst: PayrollList
) -> Optional[str]:
    """Powód, dla którego ta osoba nie zatwierdzi listy; ``None`` = może (bez danych)."""

    if lst.status != "draft":
        return "Zatwierdza się tylko listę policzoną i niezatwierdzoną."
    if lst.computed_by == actor.id:
        return "Tę listę policzyłeś Ty — zatwierdza druga osoba z Płac."
    own = await db.scalar(
        select(
            exists().where(
                PayrollListLine.list_id == lst.id, PayrollListLine.user_id == actor.id
            )
        )
    )
    if own:
        return "Na liście jest Twoja pozycja — zatwierdza inna osoba z Płac."
    return None


async def approve(db: AsyncSession, *, actor: User, list_id: int) -> PayrollList:
    # Kolejność blokad jak w „Przelicz”: najpierw okres (FOR SHARE), potem lista.
    found = await get_list(db, list_id)
    period = await lock_period_shared(db, found.year, found.month)
    lst = await get_list(db, list_id, lock=True)
    refusal = await approval_refusal(db, actor, lst)
    if refusal is not None:
        status = 409 if lst.status != "draft" else 403
        raise PayrollError(refusal, status, code="approval_refused")
    if period.status != "closed":
        raise PayrollConflict(
            "Miesiąc Płac został ponownie otwarty — zamknij go i przelicz listę.",
            code="period_open",
        )
    version = await db.scalar(
        select(PayrollParameterVersion)
        .where(PayrollParameterVersion.id == lst.parameter_version_id)
        .with_for_update(read=True)
    )
    if version is None or version.replaced_at is not None:
        raise PayrollConflict(
            "Parametry płac zmieniły się po przeliczeniu — przelicz listę.",
            code="stale_list",
        )
    later = await sources.later_approved(
        db, year=lst.pay_date.year, after=lst.pay_date, exclude_list_id=lst.id
    )
    if later is not None:
        raise PayrollConflict(
            f"Jest zatwierdzona lista {later.number} z późniejszą wypłatą — przelicz "
            "tę listę po jej anulowaniu albo zmień datę wypłaty.",
            code="later_list_approved",
        )
    prepared = await collect(db, period, lst.pay_date, exclude_list_id=lst.id)
    if prepared.source_hash != lst.source_hash or prepared.version.id != version.id:
        raise PayrollConflict(
            "Dane listy zmieniły się po przeliczeniu (kwoty, dane osób, parametry "
            "albo inne listy) — przelicz listę i zatwierdź ją ponownie.",
            code="stale_list",
        )
    computed = calculate(prepared)
    block = blocking_problems(prepared, computed)
    if block:
        raise PayrollError(
            "Listy nie da się zatwierdzić — najpierw rozwiąż problemy.",
            409,
            code="list_blocked",
            data={
                "problems": [
                    {**problem_view(item["code"]), "person": item.get("person")}
                    for item in block
                ]
            },
        )
    lst.status = "approved"
    lst.approved_by = actor.id
    lst.approved_at = local_now()
    lst.problems = [
        *prepared.list_problems,
        *(
            {"code": code, "person": item.source.name, "blocking": blocking(code)}
            for item in computed
            for code in item.problems
        ),
    ]
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_list",
        entity_id=lst.id,
        action="payroll_list_approved",
        sensitivity="payroll",
        details={"number": lst.number, "lines": len(computed)},
    )
    return lst


def _reason(raw: Optional[str]) -> str:
    text = " ".join((raw or "").split())
    if len(text) < 3:
        raise PayrollError("Podaj powód anulowania (co najmniej 3 znaki).")
    if len(text) > NOTE_MAX:
        raise PayrollError(f"Powód: najwyżej {NOTE_MAX} znaków.")
    return text


async def cancel(
    db: AsyncSession, *, actor: User, list_id: int, reason: Optional[str]
) -> PayrollList:
    text = _reason(reason)
    lst = await get_list(db, list_id, lock=True)
    if lst.status == "cancelled":
        raise PayrollConflict("Lista jest już anulowana.", code="list_cancelled")
    if lst.paid_at is not None:
        raise PayrollConflict(
            "Wypłata z tej listy jest oznaczona jako wykonana — korektę zrób kolejną "
            "listą.",
            code="list_paid",
        )
    if lst.status == "approved":
        later = await sources.later_approved(
            db, year=lst.pay_date.year, after=lst.pay_date, exclude_list_id=lst.id
        )
        if later is not None:
            raise PayrollConflict(
                f"Najpierw anuluj listę {later.number} — ma późniejszą wypłatę i liczy "
                "się od tej.",
                code="later_list_approved",
            )
    previous = lst.status
    lst.status = "cancelled"
    lst.cancelled_by = actor.id
    lst.cancelled_at = local_now()
    lst.cancel_reason = text
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_list",
        entity_id=lst.id,
        action="payroll_list_cancelled",
        sensitivity="payroll",
        details={"number": lst.number, "previous_status": previous},
    )
    return lst


async def approved_list_for_period(
    db: AsyncSession, year: int, month: int
) -> Optional[PayrollList]:
    period = await get_period(db, year, month)
    if period is None:
        return None
    found = await live_list(db, period.id)
    return found if found is not None and found.status == "approved" else None


# ── Kwoty Płac ───────────────────────────────────────────────────────────────


def _gross(raw: Any) -> Decimal:
    if isinstance(raw, bool) or raw is None:
        raise PayrollError("Kwota brutto: liczba.")
    try:
        value = Decimal(str(raw).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise PayrollError("Kwota brutto: liczba.") from None
    if not value.is_finite() or value != value.quantize(Decimal("0.01")):
        raise PayrollError("Kwota brutto: najwyżej dwa miejsca po przecinku.")
    if not Decimal("0") <= value <= Decimal(GROSS_MAX):
        raise PayrollError("Kwota brutto: od 0 do 10 000 000 zł.")
    return value


async def set_gross_input(
    db: AsyncSession,
    *,
    actor: User,
    year: int,
    month: int,
    user_id: Optional[int],
    contract_id: Optional[int],
    kind: str,
    gross: Optional[Any],
    note: Optional[str],
) -> Optional[PayrollGrossInput]:
    """Kwota Płac na miesiąc; ``gross=None`` usuwa wpis (bez commita)."""

    validate_period(year, month)
    if (user_id is None) == (contract_id is None):
        raise PayrollError("Kwota dotyczy osoby z zespołu albo kontraktu.")
    if kind not in ("uop", "zlecenie", "dzielo"):
        raise PayrollError("Forma: umowa o pracę, zlecenie albo dzieło.")
    if user_id is not None:
        if user_id == actor.id and not actor.has_role(UserRole.admin):
            raise PayrollForbidden(
                "Swojej kwoty nie wpisujesz sam — zrobi to druga osoba z Płac."
            )
        if (
            await db.scalar(
                select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id)
            )
            is None
        ):
            raise PayrollNotFound("Nie ma takiej osoby.")
    else:
        contract = await db.scalar(select(Contract).where(Contract.id == contract_id))
        if contract is None or contract.contract_type != ContractType.uzlecenie:
            raise PayrollNotFound("Nie ma takiego kontraktu zleceniowego.")
        if kind != "zlecenie":
            raise PayrollError("Kontrakt u klienta to umowa zlecenia.")
    period = await lock_period_shared(db, year, month)
    # Blokada listy czeka na trwające zatwierdzenie — kwota nie minie się z nim.
    live = await live_list(db, period.id, lock=True)
    if live is not None and live.status == "approved":
        raise PayrollConflict(
            "Lista tego miesiąca jest zatwierdzona — anuluj ją, żeby zmienić kwotę.",
            code="list_approved",
        )
    query = select(PayrollGrossInput).where(PayrollGrossInput.period_id == period.id)
    if user_id is not None:
        query = query.where(
            PayrollGrossInput.user_id == user_id, PayrollGrossInput.kind == kind
        )
    else:
        query = query.where(PayrollGrossInput.contract_id == contract_id)
    current = await db.scalar(query.with_for_update())
    if gross is None:
        if current is not None:
            await db.delete(current)
            action = "payroll_gross_input_removed"
        else:
            return None
        item: Optional[PayrollGrossInput] = None
    else:
        amount = _gross(gross)
        text = " ".join((note or "").split())
        if not 3 <= len(text) <= NOTE_MAX:
            raise PayrollError("Opisz, skąd kwota (od 3 do 500 znaków).")
        if current is None:
            current = PayrollGrossInput(
                period_id=period.id,
                user_id=user_id,
                contract_id=contract_id,
                kind=kind,
                gross=amount,
                note=text,
            )
            db.add(current)
        else:
            current.gross = amount
            current.note = text
        current.entered_by = actor.id
        current.entered_at = local_now()
        item = current
        action = "payroll_gross_input_saved"
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="payroll_gross_input",
        entity_id=item.id if item else None,
        action=action,
        sensitivity="payroll",
        details={
            "year": year,
            "month": month,
            "kind": kind,
            "contract_id": contract_id,
        },
    )
    return item


# ── Otwarcie roku ────────────────────────────────────────────────────────────


def clean_amounts(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise PayrollError("Kwoty otwarcia: zły format.")
    unknown = set(raw) - set(sources.OPENING_KEYS)
    if unknown:
        raise PayrollError("Nieznana pozycja otwarcia roku.")
    out: dict[str, str] = {}
    for key in sources.OPENING_KEYS:
        if raw.get(key) in (None, ""):
            continue
        try:
            value = Decimal(str(raw[key]).replace(" ", "").replace(",", "."))
        except InvalidOperation:
            raise PayrollError("Kwoty otwarcia: liczby.") from None
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("100000000"):
            raise PayrollError("Kwoty otwarcia: od 0 do 100 000 000 zł.")
        out[key] = str(value.quantize(Decimal("0.01")))
    return out


async def set_opening(
    db: AsyncSession,
    *,
    actor: User,
    subject: Subject,
    year: int,
    through_month: int,
    amounts: Any,
    note: Optional[str],
) -> PayrollYearOpening:
    if not 2020 <= year <= 2100 or not 1 <= through_month <= 12:
        raise PayrollError("Rok i miesiąc otwarcia poza zakresem.")
    if subject.user_id is not None and subject.user_id == actor.id:
        if not actor.has_role(UserRole.admin):
            raise PayrollForbidden(
                "Swojego otwarcia roku nie wpisujesz sam — zrobi to druga osoba z Płac."
            )
    await person_data.subject_name(db, subject)
    clean = clean_amounts(amounts)
    for _lst, line in await sources.approved_lines(db, year=year):
        if sources.person_key(line) == subject.key:
            raise PayrollConflict(
                "Ta osoba ma już zatwierdzoną listę płac w tym roku — otwarcie roku "
                "zmienisz po anulowaniu list.",
                code="opening_in_use",
            )
    query = select(PayrollYearOpening).where(PayrollYearOpening.year == year)
    if subject.user_id is not None:
        query = query.where(PayrollYearOpening.user_id == subject.user_id)
    else:
        query = query.where(PayrollYearOpening.candidate_id == subject.candidate_id)
    current = await db.scalar(query.with_for_update())
    text = " ".join((note or "").split())[:NOTE_MAX] or None
    if current is None:
        current = PayrollYearOpening(
            user_id=subject.user_id,
            candidate_id=subject.candidate_id,
            year=year,
            through_month=through_month,
            amounts=clean,
            note=text,
        )
        db.add(current)
    else:
        current.through_month = through_month
        current.amounts = clean
        current.note = text
    current.entered_by = actor.id
    current.entered_at = local_now()
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=subject.user_id,
        entity_type="payroll_year_opening",
        entity_id=current.id,
        action="payroll_year_opening_saved",
        sensitivity="payroll",
        details={
            "year": year,
            "through_month": through_month,
            "fields": sorted(clean),
            "candidate_id": subject.candidate_id,
        },
    )
    return current


# ── Odpowiedzi ───────────────────────────────────────────────────────────────


async def _names(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, str]:
    clean = {i for i in ids if i is not None}
    if not clean:
        return {}
    return {
        int(uid): str(name)
        for uid, name in (
            await db.execute(select(User.id, User.name).where(User.id.in_(clean)))
        ).all()
    }


def line_payload(line: PayrollListLine) -> dict[str, Any]:
    result = line.result or {}
    notes = [
        {"code": code, "label": engine.NOTE_LABELS.get(code, code)}
        for code in result.get("notes", [])
    ]
    return {
        "id": line.id,
        "person_key": sources.person_key(line),
        "user_id": line.user_id,
        "candidate_id": line.candidate_id,
        "contract_id": line.contract_id,
        "person_name": line.person_name,
        "kind": line.kind,
        "kind_label": KINDS_LABEL.get(line.kind, line.kind),
        "source": line.source,
        "source_label": SOURCE_LABEL.get(line.source, line.source),
        "gross": None if line.gross is None else str(line.gross),
        "net": None if line.net is None else str(line.net),
        "pit": None if line.pit is None else str(line.pit),
        "social_employee": None
        if line.social_employee is None
        else str(line.social_employee),
        "health": None if line.health is None else str(line.health),
        "employer_social": None
        if line.employer_social is None
        else str(line.employer_social),
        "employer_cost": None
        if line.employer_cost is None
        else str(line.employer_cost),
        "basis": line.basis or {},
        "result": result,
        "notes": notes,
        "problems": [problem_view(code) for code in line.problems or []],
        "payee_last4": line.payee_last4,
    }


async def list_payload(
    db: AsyncSession, lst: PayrollList, *, viewer: User
) -> dict[str, Any]:
    lines = await lines_of(db, lst.id)
    version = await db.get(PayrollParameterVersion, lst.parameter_version_id)
    names = await _names(
        db,
        {
            lst.computed_by,
            lst.approved_by,
            lst.cancelled_by,
            lst.paid_by,
            lst.transfers_created_by,
        },
    )
    refusal = await approval_refusal(db, viewer, lst)
    blocked = [p for p in (lst.problems or []) if p.get("blocking")]
    return {
        "id": lst.id,
        "number": lst.number,
        "status": lst.status,
        "year": lst.year,
        "month": lst.month,
        "pay_date": lst.pay_date.isoformat(),
        "parameter_version": {
            "id": version.id,
            "effective_from": version.effective_from.isoformat(),
            "status": version.status,
            "live": version.replaced_at is None,
        }
        if version
        else None,
        "totals": lst.totals or {},
        "problems": [
            {
                **problem_view(p.get("code", "")),
                **{k: v for k, v in p.items() if k != "code"},
            }
            for p in lst.problems or []
        ],
        "computed_by": names.get(lst.computed_by) if lst.computed_by else None,
        "computed_at": lst.computed_at.isoformat() if lst.computed_at else None,
        "approved_by": names.get(lst.approved_by) if lst.approved_by else None,
        "approved_at": lst.approved_at.isoformat() if lst.approved_at else None,
        "cancelled_by": names.get(lst.cancelled_by) if lst.cancelled_by else None,
        "cancelled_at": lst.cancelled_at.isoformat() if lst.cancelled_at else None,
        "cancel_reason": lst.cancel_reason,
        "transfers_created_at": lst.transfers_created_at.isoformat()
        if lst.transfers_created_at
        else None,
        "paid_at": lst.paid_at.isoformat() if lst.paid_at else None,
        "paid_by": names.get(lst.paid_by) if lst.paid_by else None,
        "can_approve": refusal is None and not blocked,
        "approve_refusal": refusal
        or ("Najpierw rozwiąż problemy blokujące." if blocked else None),
        "lines": [line_payload(line) for line in lines],
    }


async def month_payload(
    db: AsyncSession, *, viewer: User, year: int, month: int
) -> dict[str, Any]:
    validate_period(year, month)
    period = await get_period(db, year, month)
    payout_day = (await bank_settings.load_settings(db)).payout_day
    history: list[dict[str, Any]] = []
    current: Optional[PayrollList] = None
    if period is not None:
        for item in await db.scalars(
            select(PayrollList)
            .where(PayrollList.period_id == period.id)
            .order_by(PayrollList.id.desc())
        ):
            if item.status == "cancelled":
                history.append(
                    {
                        "id": item.id,
                        "number": item.number,
                        "cancelled_at": item.cancelled_at.isoformat()
                        if item.cancelled_at
                        else None,
                        "cancel_reason": item.cancel_reason,
                    }
                )
            elif current is None:
                current = item
    inputs: list[dict[str, Any]] = []
    if period is not None:
        for item in await db.scalars(
            select(PayrollGrossInput).where(PayrollGrossInput.period_id == period.id)
        ):
            inputs.append(
                {
                    "id": item.id,
                    "user_id": item.user_id,
                    "contract_id": item.contract_id,
                    "kind": item.kind,
                    "gross": str(item.gross),
                    "note": item.note,
                    "entered_at": item.entered_at.isoformat()
                    if item.entered_at
                    else None,
                }
            )
    return {
        "year": year,
        "month": month,
        "period_status": period.status if period else "open",
        "default_pay_date": default_pay_date(year, month, payout_day).isoformat(),
        "list": await list_payload(db, current, viewer=viewer) if current else None,
        "cancelled": history,
        "inputs": inputs,
        "can_compute": bool(
            period is not None
            and period.status == "closed"
            and (current is None or current.status == "draft")
        ),
    }


__all__ = [
    "PROBLEMS",
    "Prepared",
    "approval_refusal",
    "approve",
    "approved_list_for_period",
    "calculate",
    "cancel",
    "check_pay_date",
    "clean_amounts",
    "collect",
    "compute",
    "deadlines",
    "default_pay_date",
    "get_list",
    "line_payload",
    "lines_of",
    "list_payload",
    "live_list",
    "month_payload",
    "set_gross_input",
    "set_opening",
    "totals_of",
]
