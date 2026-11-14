"""Wersje parametrów płac (``payroll_parameter_versions``) i dane płatnika.

* Edycja tylko Płace (uprawnienie „Płace”, admin zawsze) — bramka w routerze.
* Zmiana = nowa wersja od 1. dnia miesiąca. Wersja z tą samą datą zostaje jako
  zastąpiona (historia z różnicami), chyba że użyła jej zatwierdzona lista
  płac — wtedy 409: zmianę wpisuje się od kolejnego miesiąca.
* „Do potwierdzenia” → „Potwierdzone” robi osoba z Płac po sprawdzeniu
  wartości (zasiew 2026 wchodzi jako do potwierdzenia).
* Ślad w ``hr_audit_events`` z różnicami (parametry nie są danymi osób).

Dane płatnika do KEDU, PIT i przelewów (``app_settings['hr_payroll_company']``):
REGON, nazwa skrócona, kod urzędu skarbowego płatnika, rachunek składkowy ZUS
(NRS) i mikrorachunek podatkowy. NIP i pełna nazwa — z ``COMPANY_PL``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.app_setting import AppSetting
from app.models.hr_payroll_lists import PayrollList, PayrollParameterVersion
from app.models.user import User
from app.services.b2b_documents.company_party import COMPANY_PL
from app.services.hr import audit
from app.services.hr.bank.accounts import AccountError, normalize_nrb
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollError,
    PayrollNotFound,
)
from app.services.hr.payroll_lists import params as params_rules
from app.services.hr_payroll_lists_schema import NOTE_MAX

COMPANY_KEY = "hr_payroll_company"
_REGON = re.compile(r"^([0-9]{9}|[0-9]{14})$")
_TAX_OFFICE = re.compile(r"^[0-9]{4}$")


# ── Wersje ───────────────────────────────────────────────────────────────────


async def all_versions(db: AsyncSession) -> list[PayrollParameterVersion]:
    return list(
        await db.scalars(
            select(PayrollParameterVersion).order_by(
                PayrollParameterVersion.effective_from.desc(),
                PayrollParameterVersion.created_at.desc(),
                PayrollParameterVersion.id.desc(),
            )
        )
    )


async def version_for(
    db: AsyncSession, on: date, *, lock: bool = False
) -> Optional[PayrollParameterVersion]:
    query = (
        select(PayrollParameterVersion)
        .where(
            PayrollParameterVersion.replaced_at.is_(None),
            PayrollParameterVersion.effective_from <= on,
        )
        .order_by(PayrollParameterVersion.effective_from.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update(read=True)
    return await db.scalar(query)


async def used_by_approved_list(db: AsyncSession, version_id: int) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    PayrollList.parameter_version_id == version_id,
                    PayrollList.status == "approved",
                )
            )
        )
    )


def _first_day(value: date) -> date:
    if value.day != 1:
        raise PayrollError("Parametry obowiązują od 1. dnia miesiąca.")
    if not date(2020, 1, 1) <= value <= date(2100, 12, 1):
        raise PayrollError("Data obowiązywania poza zakresem.")
    return value


def _note(raw: Optional[str]) -> Optional[str]:
    text = " ".join((raw or "").split())
    if len(text) > NOTE_MAX:
        raise PayrollError(f"Uwaga: najwyżej {NOTE_MAX} znaków.")
    return text or None


async def save_version(
    db: AsyncSession,
    *,
    actor: User,
    effective_from: date,
    values: dict[str, Any],
    note: Optional[str],
) -> PayrollParameterVersion:
    """Nowa wersja od daty (bez commita). Zastępuje nieużytą wersję z tą datą."""

    start = _first_day(effective_from)
    clean = params_rules.normalized(values)
    current = await db.scalar(
        select(PayrollParameterVersion)
        .where(
            PayrollParameterVersion.effective_from == start,
            PayrollParameterVersion.replaced_at.is_(None),
        )
        .with_for_update()
    )
    previous = current or await version_for(db, start)
    if current is not None:
        if await used_by_approved_list(db, current.id):
            raise PayrollConflict(
                "Te parametry policzyły już zatwierdzoną listę płac — zmianę wpisz "
                "od kolejnego miesiąca.",
                code="parameters_in_use",
            )
        current.replaced_at = local_now()
        current.replaced_by = actor.id
        await db.flush()
    version = PayrollParameterVersion(
        effective_from=start,
        params=clean,
        status="to_confirm",
        source="manual",
        note=_note(note),
        created_by=actor.id,
    )
    db.add(version)
    await db.flush()
    changes = params_rules.diff(previous.params if previous else {}, clean)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_parameter_version",
        entity_id=version.id,
        action="payroll_parameters_saved",
        sensitivity="payroll",
        details={
            "effective_from": start.isoformat(),
            "replaced_id": current.id if current else None,
            "changes": changes,
        },
    )
    return version


async def confirm_version(
    db: AsyncSession, *, actor: User, version_id: int
) -> PayrollParameterVersion:
    version = await db.scalar(
        select(PayrollParameterVersion)
        .where(PayrollParameterVersion.id == version_id)
        .with_for_update()
    )
    if version is None or version.replaced_at is not None:
        raise PayrollNotFound("Nie ma takiej wersji parametrów.")
    if version.status != "confirmed":
        version.status = "confirmed"
        version.confirmed_by = actor.id
        version.confirmed_at = local_now()
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=None,
            entity_type="payroll_parameter_version",
            entity_id=version.id,
            action="payroll_parameters_confirmed",
            sensitivity="payroll",
            details={"effective_from": version.effective_from.isoformat()},
        )
        await db.flush()
    return version


async def withdraw_version(db: AsyncSession, *, actor: User, version_id: int) -> None:
    """Wycofanie wersji (np. wpisanej z błędną datą) — tylko nieużytej."""

    version = await db.scalar(
        select(PayrollParameterVersion)
        .where(PayrollParameterVersion.id == version_id)
        .with_for_update()
    )
    if version is None or version.replaced_at is not None:
        raise PayrollNotFound("Nie ma takiej wersji parametrów.")
    if await used_by_approved_list(db, version.id):
        raise PayrollConflict(
            "Tej wersji użyła zatwierdzona lista płac — nie da się jej wycofać.",
            code="parameters_in_use",
        )
    version.replaced_at = local_now()
    version.replaced_by = actor.id
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_parameter_version",
        entity_id=version.id,
        action="payroll_parameters_withdrawn",
        sensitivity="payroll",
        details={"effective_from": version.effective_from.isoformat()},
    )
    await db.flush()


def version_payload(
    version: PayrollParameterVersion,
    previous: Optional[PayrollParameterVersion],
    *,
    in_use: bool,
) -> dict[str, Any]:
    return {
        "id": version.id,
        "effective_from": version.effective_from.isoformat(),
        "status": version.status,
        "source": version.source,
        "note": version.note,
        "params": dict(version.params),
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "confirmed_by": version.confirmed_by,
        "confirmed_at": version.confirmed_at.isoformat()
        if version.confirmed_at
        else None,
        "replaced_at": version.replaced_at.isoformat() if version.replaced_at else None,
        "live": version.replaced_at is None,
        "in_use": in_use,
        "changes": params_rules.diff(
            previous.params if previous else {}, version.params
        )
        if previous is not None
        else [],
    }


async def history_payload(db: AsyncSession, *, on: date) -> dict[str, Any]:
    """Wszystkie wersje (najnowsze najpierw) z różnicą do poprzedniej żywej wersji."""

    versions = await all_versions(db)
    used = set(
        await db.scalars(
            select(PayrollList.parameter_version_id).where(
                PayrollList.status == "approved"
            )
        )
    )
    live = sorted(
        (v for v in versions if v.replaced_at is None), key=lambda v: v.effective_from
    )
    previous_live: dict[int, Optional[PayrollParameterVersion]] = {}
    for index, version in enumerate(live):
        previous_live[version.id] = live[index - 1] if index else None
    items = []
    for version in versions:
        if version.replaced_at is None:
            previous = previous_live.get(version.id)
        else:
            previous = next(
                (
                    v
                    for v in reversed(live)
                    if v.effective_from < version.effective_from
                ),
                None,
            )
        items.append(version_payload(version, previous, in_use=version.id in used))
    current = await version_for(db, on)
    return {
        "catalog": params_rules.catalog(),
        "current_id": current.id if current else None,
        "versions": items,
    }


# ── Dane płatnika ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Company:
    nip: str
    name: str
    short_name: str
    regon: Optional[str]
    tax_office_code: Optional[str]
    zus_account: Optional[str]
    tax_account: Optional[str]

    def missing(self) -> list[str]:
        out = []
        if not self.regon:
            out.append("regon")
        if not self.tax_office_code:
            out.append("tax_office_code")
        return out


def _company(raw: Any) -> Company:
    data = raw if isinstance(raw, dict) else {}

    def text(key: str) -> Optional[str]:
        value = data.get(key)
        return value if isinstance(value, str) and value else None

    return Company(
        nip=COMPANY_PL["nip"],
        name=COMPANY_PL["name"],
        short_name=text("short_name") or COMPANY_PL["short"],
        regon=text("regon"),
        tax_office_code=text("tax_office_code"),
        zus_account=text("zus_account"),
        tax_account=text("tax_account"),
    )


async def load_company(db: AsyncSession) -> Company:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == COMPANY_KEY))
    return _company(raw)


def clean_company(values: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    regon = "".join(str(values.get("regon") or "").split())
    if regon:
        if not _REGON.match(regon):
            raise PayrollError("REGON: 9 albo 14 cyfr.")
        out["regon"] = regon
    short = " ".join(str(values.get("short_name") or "").split())
    if short:
        if len(short) > 31:
            raise PayrollError("Nazwa skrócona płatnika: najwyżej 31 znaków (ZUS).")
        out["short_name"] = short
    office = "".join(str(values.get("tax_office_code") or "").split())
    if office:
        if not _TAX_OFFICE.match(office):
            raise PayrollError("Kod urzędu skarbowego płatnika: 4 cyfry.")
        out["tax_office_code"] = office
    for key, label in (
        ("zus_account", "Rachunek składkowy ZUS"),
        ("tax_account", "Mikrorachunek podatkowy"),
    ):
        raw = values.get(key)
        if raw:
            try:
                out[key] = normalize_nrb(str(raw))
            except AccountError:
                raise PayrollError(f"{label}: 26 cyfr numeru NRB.") from None
    return out


async def save_company(
    db: AsyncSession, *, actor: User, values: dict[str, Any]
) -> Company:
    clean = clean_company(values)
    statement = insert(AppSetting).values(
        key=COMPANY_KEY, value=clean, updated_by=actor.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.id},
        )
    )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="app_setting",
        entity_id=COMPANY_KEY,
        action="payroll_company_saved",
        sensitivity="payroll",
        details={"fields": sorted(clean)},
    )
    await db.flush()
    return _company(clean)


def company_payload(company: Company) -> dict[str, Any]:
    return {
        "nip": company.nip,
        "name": company.name,
        "short_name": company.short_name,
        "regon": company.regon,
        "tax_office_code": company.tax_office_code,
        "zus_account": company.zus_account,
        "tax_account": company.tax_account,
        "missing": company.missing(),
    }


__all__ = [
    "COMPANY_KEY",
    "Company",
    "all_versions",
    "clean_company",
    "company_payload",
    "confirm_version",
    "history_payload",
    "load_company",
    "save_company",
    "save_version",
    "used_by_approved_list",
    "version_for",
    "version_payload",
    "withdraw_version",
]
