"""K7b — zapis Płac: pensje UoP, składniki miesiąca, oznaczenia L4, historia z Enovy.

Wszystko pod blokadą list płac (``lists.serialize``), bo zmienia wejście
liczenia. Zasady jak przy kwotach Płac (K7a): swojej pensji, składnika ani
oznaczenia nie zmienia się samemu (403, administrator może); miesiąc
z zatwierdzoną listą jest zamknięty (409 — najpierw anulowanie listy).
Ślad w ``hr_audit_events`` z ``sensitivity='payroll'`` bez kwot.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.hr_leave import LeaveRequest
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_payroll_k7b import (
    PayrollAbsenceMark,
    PayrollBasisMonth,
    PayrollComponent,
    PayrollSalary,
)
from app.models.hr_payroll_lists import PayrollList, PayrollListLine
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.finance_ledger import identifiers
from app.services.finance_ledger.counterparty_import import ImportFileError, _sheet_rows
from app.services.hr import audit
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollError,
    PayrollForbidden,
    PayrollNotFound,
)
from app.services.hr.payroll_lists import salary as rules
from app.services.hr.payroll_lists.lists import live_list, serialize
from app.services.hr.payroll_periods import (
    get_period,
    lock_period_shared,
    validate_period,
)
from app.services.hr_payroll_k7b_schema import COMPONENT_KINDS, SICK_RATES
from app.services.hr_payroll_lists_schema import GROSS_MAX, NOTE_MAX
from app.services.ledger.opening import parse_amount

COMPONENT_LABELS: dict[str, str] = {
    "variable": "Składniki zmienne (w podstawach, np. nadgodziny)",
    "other": "Inne składniki poza podstawami (np. nagroda)",
    "sick_base": "Podstawa chorobowego wpisana ręcznie",
    "equivalent_days": "Dni urlopu do ekwiwalentu wpisane ręcznie",
}
SICK_RATE_LABELS: dict[str, str] = {
    "80": "80% (zwykłe L4)",
    "100": "100% (ciąża, wypadek w drodze, dawstwo)",
    "zus": "zasiłek z ZUS od 1. dnia (np. opieka)",
}
MAX_BYTES = 2 * 1024 * 1024
HEADER_SCAN_ROWS = 10


def _own(actor: User, user_id: int, what: str) -> None:
    if user_id == actor.id and not actor.has_role(UserRole.admin):
        raise PayrollForbidden(
            f"{what} nie zmieniasz sam — zrobi to druga osoba z Rozliczeń albo administrator."
        )


def _note(raw: Optional[str], *, required: bool) -> Optional[str]:
    text = " ".join((raw or "").split())
    if not text:
        if required:
            raise PayrollError("Opisz, skąd kwota (od 3 do 500 znaków).")
        return None
    if not 3 <= len(text) <= NOTE_MAX:
        raise PayrollError("Opis: od 3 do 500 znaków.")
    return text


def _amount(raw: Any, label: str, *, allow_zero: bool = False) -> Decimal:
    if isinstance(raw, bool) or raw is None:
        raise PayrollError(f"{label}: liczba.")
    try:
        value = Decimal(str(raw).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise PayrollError(f"{label}: liczba.") from None
    if not value.is_finite() or value != value.quantize(Decimal("0.01")):
        raise PayrollError(f"{label}: najwyżej dwa miejsca po przecinku.")
    low = Decimal("0") if allow_zero else Decimal("0.01")
    if not low <= value <= Decimal(GROSS_MAX):
        raise PayrollError(f"{label}: od {low} do 10 000 000.")
    return value


async def _team_member(db: AsyncSession, user_id: int) -> EmployeeProfile:
    profile = await db.scalar(
        select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
    )
    if profile is None:
        raise PayrollNotFound("Nie ma takiej osoby.")
    return profile


async def _last_approved_month(db: AsyncSession) -> Optional[tuple[int, int]]:
    row = (
        await db.execute(
            select(PayrollList.year, PayrollList.month)
            .where(PayrollList.status == "approved")
            .order_by(PayrollList.year.desc(), PayrollList.month.desc())
            .limit(1)
        )
    ).first()
    return (int(row[0]), int(row[1])) if row else None


# ── Pensje ───────────────────────────────────────────────────────────────────


def salary_payload(row: PayrollSalary) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "monthly_amount": str(row.monthly_amount),
        "fte": str(row.fte),
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "note": row.note,
        "set_by": row.set_by,
        "set_at": row.set_at.isoformat() if row.set_at else None,
    }


async def salaries(db: AsyncSession) -> list[PayrollSalary]:
    return list(
        await db.scalars(
            select(PayrollSalary).order_by(
                PayrollSalary.user_id, PayrollSalary.effective_from.desc()
            )
        )
    )


def _fte(raw: Any) -> Decimal:
    try:
        value = Decimal(str(raw if raw is not None else "1").replace(",", "."))
    except InvalidOperation:
        raise PayrollError("Etat: ułamek od 0,01 do 1.") from None
    if not value.is_finite() or not Decimal("0.01") <= value <= 1:
        raise PayrollError("Etat: ułamek od 0,01 do 1.")
    if value != value.quantize(Decimal("0.001")):
        raise PayrollError("Etat: najwyżej trzy miejsca po przecinku.")
    return value


async def set_salary(
    db: AsyncSession,
    *,
    actor: User,
    user_id: int,
    monthly_amount: Any,
    fte: Any,
    effective_from: date,
    note: Optional[str],
) -> PayrollSalary:
    """Pensja od 1. dnia miesiąca; poprzednia trwająca kończy się dzień wcześniej."""

    await serialize(db)
    _own(actor, user_id, "Swojej pensji")
    profile = await _team_member(db, user_id)
    if profile.employment_type != "uop":
        raise PayrollError("Pensję wpisuje się osobie na umowie o pracę.")
    if effective_from.day != 1:
        raise PayrollError("Pensja obowiązuje od 1. dnia miesiąca.")
    validate_period(effective_from.year, effective_from.month)
    last = await _last_approved_month(db)
    if last is not None and (effective_from.year, effective_from.month) <= last:
        raise PayrollConflict(
            f"Lista za {last[1]:02d}.{last[0]} jest zatwierdzona — zmiana pensji "
            "obowiązuje od kolejnego miesiąca.",
            code="list_approved",
        )
    amount = _amount(monthly_amount, "Pensja")
    share = _fte(fte)
    text = _note(note, required=False)
    current = await db.scalar(
        select(PayrollSalary)
        .where(
            PayrollSalary.user_id == user_id,
            PayrollSalary.effective_from == effective_from,
        )
        .with_for_update()
    )
    previous = await db.scalar(
        select(PayrollSalary)
        .where(
            PayrollSalary.user_id == user_id,
            PayrollSalary.effective_from < effective_from,
        )
        .order_by(PayrollSalary.effective_from.desc())
        .limit(1)
        .with_for_update()
    )
    if previous is not None and (
        previous.effective_to is None or previous.effective_to >= effective_from
    ):
        previous.effective_to = effective_from - timedelta(days=1)
    following = await db.scalar(
        select(PayrollSalary)
        .where(
            PayrollSalary.user_id == user_id,
            PayrollSalary.effective_from > effective_from,
        )
        .order_by(PayrollSalary.effective_from)
        .limit(1)
    )
    end = following.effective_from - timedelta(days=1) if following else None
    if current is None:
        current = PayrollSalary(
            user_id=user_id,
            monthly_amount=amount,
            fte=share,
            effective_from=effective_from,
            effective_to=end,
            note=text,
        )
        db.add(current)
    else:
        current.monthly_amount = amount
        current.fte = share
        current.note = text
        current.effective_to = end
    current.set_by = actor.id
    current.set_at = local_now()
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="payroll_salary",
        entity_id=current.id,
        action="payroll_salary_set",
        sensitivity="payroll",
        details={"effective_from": effective_from.isoformat()},
    )
    return current


async def delete_salary(db: AsyncSession, *, actor: User, salary_id: int) -> None:
    await serialize(db)
    row = await db.scalar(
        select(PayrollSalary).where(PayrollSalary.id == salary_id).with_for_update()
    )
    if row is None:
        raise PayrollNotFound("Nie ma takiej pensji.")
    _own(actor, row.user_id, "Swojej pensji")
    used = await db.scalar(
        select(PayrollListLine.id)
        .join(PayrollList, PayrollList.id == PayrollListLine.list_id)
        .where(
            PayrollList.status == "approved",
            PayrollListLine.user_id == row.user_id,
            PayrollListLine.basis["salary_id"].astext == str(row.id),
        )
        .limit(1)
    )
    if used is not None:
        raise PayrollConflict(
            "Z tej pensji policzono zatwierdzoną listę — dodaj nową pensję od kolejnego "
            "miesiąca zamiast usuwać.",
            code="salary_used",
        )
    previous = await db.scalar(
        select(PayrollSalary)
        .where(
            PayrollSalary.user_id == row.user_id,
            PayrollSalary.effective_to == row.effective_from - timedelta(days=1),
        )
        .with_for_update()
    )
    if previous is not None:
        previous.effective_to = row.effective_to
    await db.delete(row)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=row.user_id,
        entity_type="payroll_salary",
        entity_id=salary_id,
        action="payroll_salary_removed",
        sensitivity="payroll",
        details={"effective_from": row.effective_from.isoformat()},
    )


# ── Składniki miesiąca ───────────────────────────────────────────────────────


async def _open_period(db: AsyncSession, year: int, month: int) -> PayrollPeriod:
    validate_period(year, month)
    period = await lock_period_shared(db, year, month)
    live = await live_list(db, period.id, lock=True)
    if live is not None and live.status == "approved":
        raise PayrollConflict(
            "Lista tego miesiąca jest zatwierdzona — anuluj ją, żeby zmienić składniki.",
            code="list_approved",
        )
    return period


def component_payload(item: PayrollComponent) -> dict[str, Any]:
    return {
        "user_id": item.user_id,
        "kind": item.kind,
        "label": COMPONENT_LABELS[item.kind],
        "amount": str(item.amount),
        "note": item.note,
        "entered_by": item.entered_by,
        "entered_at": item.entered_at.isoformat() if item.entered_at else None,
    }


async def components(db: AsyncSession, year: int, month: int) -> list[PayrollComponent]:
    period = await get_period(db, year, month)
    if period is None:
        return []
    return list(
        await db.scalars(
            select(PayrollComponent)
            .where(PayrollComponent.period_id == period.id)
            .order_by(PayrollComponent.user_id, PayrollComponent.kind)
        )
    )


async def set_component(
    db: AsyncSession,
    *,
    actor: User,
    year: int,
    month: int,
    user_id: int,
    kind: str,
    amount: Optional[Any],
    note: Optional[str],
) -> Optional[PayrollComponent]:
    """Składnik miesiąca; ``amount=None`` usuwa wpis (bez commita)."""

    await serialize(db)
    if kind not in COMPONENT_KINDS:
        raise PayrollError("Nieznany rodzaj składnika.")
    _own(actor, user_id, "Swoich składników")
    await _team_member(db, user_id)
    period = await _open_period(db, year, month)
    current = await db.scalar(
        select(PayrollComponent)
        .where(
            PayrollComponent.period_id == period.id,
            PayrollComponent.user_id == user_id,
            PayrollComponent.kind == kind,
        )
        .with_for_update()
    )
    if amount is None:
        if current is None:
            return None
        await db.delete(current)
        await db.flush()
        _audit_component(db, actor, user_id, kind, year, month, removed=True)
        return None
    if kind == "equivalent_days":
        value = _amount(amount, "Dni urlopu", allow_zero=True)
        if value > 366 or value != value.to_integral_value():
            raise PayrollError("Dni urlopu: liczba całkowita do 366.")
    else:
        value = _amount(amount, COMPONENT_LABELS[kind], allow_zero=kind != "sick_base")
    text = _note(note, required=True)
    assert text is not None
    if current is None:
        current = PayrollComponent(
            period_id=period.id, user_id=user_id, kind=kind, amount=value, note=text
        )
        db.add(current)
    else:
        current.amount = value
        current.note = text
    current.entered_by = actor.id
    current.entered_at = local_now()
    await db.flush()
    _audit_component(db, actor, user_id, kind, year, month, removed=False)
    return current


def _audit_component(
    db: AsyncSession,
    actor: User,
    user_id: int,
    kind: str,
    year: int,
    month: int,
    *,
    removed: bool,
) -> None:
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="payroll_component",
        entity_id=None,
        action="payroll_component_removed" if removed else "payroll_component_set",
        sensitivity="payroll",
        details={"kind": kind, "period": f"{year}-{month:02d}"},
    )


# ── Nieobecności miesiąca i oznaczenia L4 ────────────────────────────────────


async def absences(db: AsyncSession, year: int, month: int) -> list[dict[str, Any]]:
    """Zatwierdzone nieobecności osób z pensją w miesiącu (tylko dla Płac, D6)."""

    from app.services.hr.leave_policy import LEAVE_TYPE_LABELS

    first, last = rules.month_bounds(year, month)
    with_salary = {
        row.user_id
        for row in await db.scalars(
            select(PayrollSalary).where(
                PayrollSalary.effective_from <= last,
                or_(
                    PayrollSalary.effective_to.is_(None),
                    PayrollSalary.effective_to >= first,
                ),
            )
        )
    }
    if not with_salary:
        return []
    names = {
        int(uid): str(name)
        for uid, name in (
            await db.execute(select(User.id, User.name).where(User.id.in_(with_salary)))
        ).all()
    }
    rows = list(
        await db.scalars(
            select(LeaveRequest)
            .where(
                LeaveRequest.user_id.in_(with_salary),
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= last,
                LeaveRequest.end_date >= first,
            )
            .order_by(LeaveRequest.start_date)
        )
    )
    marks = (
        {
            mark.leave_request_id: mark
            for mark in await db.scalars(
                select(PayrollAbsenceMark).where(
                    PayrollAbsenceMark.leave_request_id.in_([row.id for row in rows])
                )
            )
        }
        if rows
        else {}
    )
    out = []
    for row in rows:
        mark = marks.get(row.id)
        out.append(
            {
                "id": str(row.id),
                "user_id": row.user_id,
                "person": names.get(row.user_id, ""),
                "leave_type": row.leave_type,
                "label": LEAVE_TYPE_LABELS.get(row.leave_type, row.leave_type),
                "start": row.start_date.isoformat(),
                "end": row.end_date.isoformat(),
                "sick": row.leave_type == rules.SICK_TYPE,
                "sick_rate": mark.sick_rate if mark else "80",
                "waiting_exempt": bool(mark.waiting_exempt) if mark else False,
                "note": mark.note if mark else None,
            }
        )
    return out


async def set_mark(
    db: AsyncSession,
    *,
    actor: User,
    leave_request_id: uuid.UUID,
    sick_rate: str,
    waiting_exempt: bool,
    note: Optional[str],
) -> PayrollAbsenceMark:
    await serialize(db)
    request = await db.scalar(
        select(LeaveRequest).where(LeaveRequest.id == leave_request_id)
    )
    if request is None or request.leave_type != rules.SICK_TYPE:
        raise PayrollNotFound("Nie ma takiego zwolnienia lekarskiego.")
    _own(actor, request.user_id, "Swojego zwolnienia")
    if sick_rate not in SICK_RATES:
        raise PayrollError("Stawka: 80%, 100% albo zasiłek z ZUS.")
    for year, month in {
        (request.start_date.year, request.start_date.month),
        (request.end_date.year, request.end_date.month),
    }:
        period = await get_period(db, year, month)
        live = await live_list(db, period.id) if period else None
        if live is not None and live.status == "approved":
            raise PayrollConflict(
                f"Lista za {month:02d}.{year} jest zatwierdzona — anuluj ją, żeby "
                "zmienić oznaczenie.",
                code="list_approved",
            )
    mark = await db.scalar(
        select(PayrollAbsenceMark)
        .where(PayrollAbsenceMark.leave_request_id == leave_request_id)
        .with_for_update()
    )
    if mark is None:
        mark = PayrollAbsenceMark(
            leave_request_id=leave_request_id, user_id=request.user_id
        )
        db.add(mark)
    mark.sick_rate = sick_rate
    mark.waiting_exempt = bool(waiting_exempt)
    mark.note = _note(note, required=False)
    mark.set_by = actor.id
    mark.set_at = local_now()
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=request.user_id,
        entity_type="payroll_absence_mark",
        entity_id=None,
        action="payroll_absence_marked",
        sensitivity="payroll",
        details={"sick_rate": sick_rate, "waiting_exempt": bool(waiting_exempt)},
    )
    return mark


# ── Historia podstaw z Enovy ─────────────────────────────────────────────────

HISTORY_COLUMNS: dict[str, str] = {
    "person": "Pracownik",
    "period": "Okres (RRRR-MM)",
    "fixed_paid": "Stałe wypłacone",
    "fixed_full": "Stałe za pełny miesiąc",
    "variable": "Zmienne",
    "leave_variable": "Urlopowe za zmienne",
    "nominal_hours": "Godziny nominalne",
    "worked_hours": "Godziny przepracowane",
    "paid_hours": "Godziny płatne",
    "full_month": "Pełny miesiąc",
}
REQUIRED_HISTORY = (
    "person",
    "period",
    "fixed_paid",
    "fixed_full",
    "nominal_hours",
    "worked_hours",
)


def history_column(header: str) -> Optional[str]:
    word = identifiers.fold(header)
    if not word:
        return None
    if word.startswith(("pracownik", "osoba", "nazwisko", "imie")):
        return "person"
    if word.startswith(("okres", "miesiac")):
        return "period"
    if word.startswith("stal"):
        return "fixed_full" if "peln" in word else "fixed_paid"
    if word.startswith("urlop"):
        return "leave_variable"
    if word.startswith("zmienn"):
        return "variable"
    if word.startswith(("godzin", "godz")):
        if "nomin" in word or "wymiar" in word:
            return "nominal_hours"
        if "przeprac" in word:
            return "worked_hours"
        if "plat" in word:
            return "paid_hours"
    if word.startswith("pelnymiesiac"):
        return "full_month"
    return None


@dataclass
class HistoryParse:
    rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    columns: dict[str, str] = field(default_factory=dict)


def _period(raw: str) -> Optional[tuple[int, int]]:
    text = (raw or "").strip().replace(".", "-").replace("/", "-")
    parts = [part for part in text.split("-") if part]
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    first, second = int(parts[0]), int(parts[1])
    year, month = (first, second) if first > 12 else (second, first)
    if not 2020 <= year <= 2100 or not 1 <= month <= 12:
        return None
    return year, month


def parse_history(content: bytes) -> HistoryParse:
    if len(content) > MAX_BYTES:
        raise ImportFileError("Plik jest za duży (najwyżej 2 MB).")
    sheet = _sheet_rows(content)
    header_index: Optional[int] = None
    columns: dict[int, str] = {}
    for index, row in enumerate(sheet[:HEADER_SCAN_ROWS]):
        found = {pos: history_column(cell) for pos, cell in enumerate(row)}
        found = {pos: key for pos, key in found.items() if key}
        if {"person", "period"} <= set(found.values()):
            header_index, columns = index, found
            break
    if header_index is None:
        raise ImportFileError(
            "Nie znaleziono nagłówka z kolumnami „Pracownik” i „Okres”."
        )
    keys = set(columns.values())
    missing = [HISTORY_COLUMNS[key] for key in REQUIRED_HISTORY if key not in keys]
    if missing:
        raise ImportFileError("Brakuje kolumn: " + ", ".join(missing) + ".")
    parsed = HistoryParse(
        columns={key: sheet[header_index][pos].strip() for pos, key in columns.items()}
    )
    for offset, row in enumerate(sheet[header_index + 1 :], start=header_index + 2):
        cells = {
            key: (row[pos] if pos < len(row) else "") for pos, key in columns.items()
        }
        if not any(str(value).strip() for value in cells.values()):
            continue
        person = " ".join(str(cells.get("person") or "").split())
        period = _period(str(cells.get("period") or ""))
        if not person or period is None:
            parsed.errors.append(
                {
                    "line": offset,
                    "message": "Brak osoby albo okres nie w formacie RRRR-MM.",
                }
            )
            continue
        values: dict[str, Decimal] = {}
        broken: list[str] = []
        for key in (
            "fixed_paid",
            "fixed_full",
            "variable",
            "leave_variable",
            "nominal_hours",
            "worked_hours",
            "paid_hours",
        ):
            raw = str(cells.get(key) or "").strip()
            if not raw and key not in REQUIRED_HISTORY:
                continue
            value = parse_amount(raw)
            if value is None or value < 0:
                broken.append(HISTORY_COLUMNS[key])
                continue
            values[key] = value
        if broken:
            parsed.errors.append(
                {"line": offset, "message": "Nieczytelne: " + ", ".join(broken) + "."}
            )
            continue
        values.setdefault("variable", Decimal("0"))
        values.setdefault("leave_variable", Decimal("0"))
        values.setdefault("paid_hours", values["worked_hours"])
        if not (
            values["worked_hours"] <= values["paid_hours"] <= values["nominal_hours"]
        ):
            parsed.errors.append(
                {
                    "line": offset,
                    "message": "Godziny: przepracowane ≤ płatne ≤ nominalne.",
                }
            )
            continue
        full_raw = identifiers.fold(str(cells.get("full_month") or "tak"))
        parsed.rows.append(
            {
                "line": offset,
                "person": person,
                "year": period[0],
                "month": period[1],
                **values,
                "full_month": full_raw not in ("nie", "n", "0", "false"),
            }
        )
    if not parsed.rows and not parsed.errors:
        raise ImportFileError("Plik nie ma żadnego wiersza historii.")
    return parsed


def name_key(name: str) -> frozenset[str]:
    return frozenset(
        identifiers.fold(token) for token in name.replace(",", " ").split() if token
    )


async def _uop_people(db: AsyncSession) -> dict[frozenset[str], list[tuple[int, str]]]:
    rows = (
        await db.execute(
            select(User.id, User.name)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(EmployeeProfile.employment_type == "uop")
        )
    ).all()
    out: dict[frozenset[str], list[tuple[int, str]]] = {}
    for uid, name in rows:
        out.setdefault(name_key(str(name)), []).append((int(uid), str(name)))
    return out


async def import_history(
    db: AsyncSession, *, actor: User, content: bytes, save: bool
) -> dict[str, Any]:
    """Podgląd albo zapis historii podstaw z Enovy (bez commita)."""

    parsed = parse_history(content)
    people = await _uop_people(db)
    matched: list[dict[str, Any]] = []
    errors = list(parsed.errors)
    for row in parsed.rows:
        found = people.get(name_key(row["person"]), [])
        if len(found) != 1:
            errors.append(
                {
                    "line": row["line"],
                    "message": "Nie znaleziono jednej osoby na umowie o pracę o tym imieniu "
                    "i nazwisku."
                    if not found
                    else "Dwie osoby o tym imieniu i nazwisku — popraw plik.",
                }
            )
            continue
        uid, name = found[0]
        if uid == actor.id and not actor.has_role(UserRole.admin):
            errors.append(
                {"line": row["line"], "message": "Swojej historii nie wczytujesz sam."}
            )
            continue
        matched.append({**row, "user_id": uid, "name": name})
    seen: set[tuple[int, int, int]] = set()
    for row in matched:
        key = (row["user_id"], row["year"], row["month"])
        if key in seen:
            errors.append(
                {
                    "line": row["line"],
                    "message": "Ten miesiąc osoby jest w pliku drugi raz.",
                }
            )
        seen.add(key)
    payload = {
        "columns": parsed.columns,
        "rows": [
            {
                "line": row["line"],
                "user_id": row["user_id"],
                "person": row["name"],
                "period": f"{row['year']}-{row['month']:02d}",
                "fixed_paid": str(row["fixed_paid"]),
                "fixed_full": str(row["fixed_full"]),
                "variable": str(row["variable"]),
                "leave_variable": str(row["leave_variable"]),
                "nominal_hours": str(row["nominal_hours"]),
                "worked_hours": str(row["worked_hours"]),
                "paid_hours": str(row["paid_hours"]),
                "full_month": row["full_month"],
            }
            for row in matched
        ],
        "errors": errors[:50],
        "errors_total": len(errors),
        "saved": False,
    }
    if not save:
        return payload
    if errors or not matched:
        raise PayrollError("Historii nie zapisano — popraw błędy z podglądu.")
    await serialize(db)
    digest = hashlib.sha256(content).hexdigest()
    for row in matched:
        current = await db.scalar(
            select(PayrollBasisMonth)
            .where(
                PayrollBasisMonth.user_id == row["user_id"],
                PayrollBasisMonth.year == row["year"],
                PayrollBasisMonth.month == row["month"],
            )
            .with_for_update()
        )
        if current is None:
            current = PayrollBasisMonth(
                user_id=row["user_id"], year=row["year"], month=row["month"]
            )
            db.add(current)
        current.fixed_paid = row["fixed_paid"]
        current.fixed_full = row["fixed_full"]
        current.variable = row["variable"]
        current.leave_variable = row["leave_variable"]
        current.nominal_hours = row["nominal_hours"]
        current.worked_hours = row["worked_hours"]
        current.paid_hours = row["paid_hours"]
        current.full_month = row["full_month"]
        current.source = "enova"
        current.file_sha256 = digest
        current.entered_by = actor.id
        current.entered_at = local_now()
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_basis_months",
        entity_id=None,
        action="payroll_basis_history_imported",
        sensitivity="payroll",
        details={"rows": len(matched), "people": len({r["user_id"] for r in matched})},
    )
    payload["saved"] = True
    return payload


async def history_rows(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(PayrollBasisMonth, User.name)
            .join(User, User.id == PayrollBasisMonth.user_id)
            .order_by(User.name, PayrollBasisMonth.year, PayrollBasisMonth.month)
        )
    ).all()
    return [
        {
            "user_id": row.user_id,
            "person": str(name),
            "period": f"{row.year}-{row.month:02d}",
            "fixed_paid": str(row.fixed_paid),
            "fixed_full": str(row.fixed_full),
            "variable": str(row.variable),
            "leave_variable": str(row.leave_variable),
            "nominal_hours": str(row.nominal_hours),
            "worked_hours": str(row.worked_hours),
            "paid_hours": str(row.paid_hours),
            "full_month": row.full_month,
        }
        for row, name in rows
    ]


__all__ = [
    "COMPONENT_LABELS",
    "SICK_RATE_LABELS",
    "absences",
    "component_payload",
    "components",
    "delete_salary",
    "history_rows",
    "import_history",
    "parse_history",
    "salaries",
    "salary_payload",
    "set_component",
    "set_mark",
    "set_salary",
]
