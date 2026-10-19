"""Umowy z ludźmi (etap 5, E5) — szkic, walidacja, odczyty i przełącznik modułu.

Kadry przygotowują umowę albo aneks z wgranego wzoru (``agreements_templates``),
oglądają PDF, wysyłają do podpisu przez Autenti (``agreements_signing``) albo
oznaczają podpis ręcznie ze skanem. Po podpisie dane przechodzą do kartoteki
same (``agreements_effects``). Stany i kolumny — docstring
``hr_agreements_schema``.

Reguły szkicu:

* osoba ma kartotekę i nie odeszła; nikt nie przygotowuje umowy sam sobie
  (także admin — jak przy premiach),
* stawka > 0 w PLN/EUR/USD; na zleceniu nie niższa niż minimalna stawka roku
  (D7, ``app_settings['hr_minimum_hourly_rates']`` — ta sama reguła co zapis
  stawki w Płacach), rok bez minimum = zapis z ostrzeżeniem,
* stawka w historii stawek obowiązuje od 1. dnia miesiąca, więc aneks zaczyna
  się 1. dnia miesiąca, a umowa od połowy miesiąca nie może zmienić stawki,
  którą osoba już ma na ten miesiąc; zmiana wstecz najwyżej o 12 miesięcy,
* na zleceniu potwierdzanie godzin (art. 8b) jest obowiązkowe,
* najwyżej jedna umowa i jeden aneks w toku na osobę.

Moduł jest za przełącznikiem ``app_settings['hr_agreements']`` (domyślnie
wyłączony; admin widzi ekrany zawsze) i wymaga włączonego modułu „Ludzie”.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.hr_agreement import (
    HrAgreement,
    HrAgreementTemplate,
    HrAgreementTemplateVersion,
)
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr import agreements_templates as templates
from app.services.hr import audit, payroll_rates
from app.services.hr.agreements_errors import (
    AgreementConflict,
    AgreementError,
    AgreementNotFound,
)
from app.services.hr.bank.settings import load_settings as load_payment_settings
from app.services.hr.payroll_errors import PayrollError
from app.services.hr.program import program_enabled
from app.services.hr_agreements_schema import (
    CURRENCIES,
    LIVE_STATUSES,
    RATE_MAX,
    REASON_MAX_LENGTH,
)
from app.services.hr_foundation_schema import EmploymentStatus, EmploymentType

logger = logging.getLogger(__name__)

SETTINGS_KEY = "hr_agreements"
MODULE_DISABLED_DETAIL = "Ten moduł nie jest jeszcze włączony."

STATUS_LABELS: dict[str, str] = {
    "draft": "szkic",
    "sent": "wysłana do podpisu",
    "signed": "podpisana",
    "rejected": "odrzucona przez osobę",
    "cancelled": "anulowana",
}
CHANNEL_LABELS: dict[str, str] = {"autenti": "Autenti", "manual": "ręcznie, ze skanem"}

#: Pola szkicu, które Kadry zmieniają (``PATCH``).
EDITABLE_FIELDS: tuple[str, ...] = (
    "template_id",
    "base_agreement_id",
    "hourly_rate",
    "currency",
    "start_date",
    "end_date",
    "agreement_date",
    "hours_confirmation",
    "payout_day",
    "coordinator_user_id",
)

_LIVE_INDEX = "ux_hr_agreements_live"
_RATE_MAX = Decimal(RATE_MAX)


# ── Przełącznik modułu ────────────────────────────────────────────────────────


async def load_enabled(db: AsyncSession) -> bool:
    """Brak wpisu albo wpis bez ``enabled: true`` = moduł wyłączony; wyłączony
    program „Ludzi w NEXUSIE” zamyka go zawsze."""

    if not program_enabled():
        return False
    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SETTINGS_KEY)
    )
    return isinstance(raw, dict) and raw.get("enabled") is True


async def save_enabled(db: AsyncSession, enabled: bool, *, actor_id: int) -> bool:
    statement = insert(AppSetting).values(
        key=SETTINGS_KEY, value={"enabled": bool(enabled)}, updated_by=actor_id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="hr_agreements_settings",
        entity_id=None,
        action="module_switched",
        details={"enabled": bool(enabled)},
    )
    return bool(enabled)


def open_for(user: User, enabled: bool) -> bool:
    if not program_enabled():
        return False
    return enabled or user.has_role(UserRole.admin)


def autenti_configured() -> bool:
    """Autenti włączone w env i z danymi logowania (bez nich tylko podpis ręczny)."""

    return bool(
        app_settings.AUTENTI_ENABLED
        and app_settings.AUTENTI_CLIENT_ID
        and app_settings.AUTENTI_CLIENT_SECRET
    )


# ── Odczyty ───────────────────────────────────────────────────────────────────


async def get_agreement(
    db: AsyncSession, agreement_id: int, *, lock: bool = False
) -> HrAgreement:
    query = select(HrAgreement).where(HrAgreement.id == agreement_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    agreement = await db.scalar(query)
    if agreement is None:
        raise AgreementNotFound("Nie ma takiej umowy.")
    return agreement


def title(agreement: HrAgreement) -> str:
    start = agreement.start_date.strftime("%d.%m.%Y")
    if agreement.kind == "annex":
        return f"Aneks: stawka od {start}"
    return f"{templates.KIND_LABELS[agreement.employment_type]} od {start}"


def rate_basis(employment_type: str) -> str:
    return "netto" if employment_type == EmploymentType.b2b else "brutto"


def rate_from(agreement_kind: str, start_date: date) -> date:
    """Dzień, od którego stawka wchodzi do historii (zawsze 1. dzień miesiąca)."""

    return start_date if agreement_kind == "annex" else start_date.replace(day=1)


def actions(agreement: HrAgreement, *, writer: bool, autenti: bool) -> dict[str, bool]:
    status = agreement.status
    return {
        "edit": writer and status == "draft",
        "send": writer and status == "draft" and autenti,
        "withdraw": writer and status == "sent",
        "cancel": writer and status in LIVE_STATUSES,
        "mark_signed": writer and status == "draft",
        "apply": writer and status == "signed" and agreement.applied_at is None,
    }


def _iso(value: Optional[date | datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def agreement_payload(
    agreement: HrAgreement,
    *,
    names: Mapping[int, str],
    template: Optional[dict[str, Any]],
    writer: bool,
    autenti: bool,
) -> dict[str, Any]:
    return {
        "id": agreement.id,
        "user_id": agreement.user_id,
        "person_name": names.get(agreement.user_id),
        "kind": agreement.kind,
        "employment_type": agreement.employment_type,
        "form_label": templates.KIND_LABELS[agreement.employment_type],
        "title": title(agreement),
        "status": agreement.status,
        "status_label": STATUS_LABELS[agreement.status],
        "template": template,
        "base_agreement_id": agreement.base_agreement_id,
        "hourly_rate": str(agreement.hourly_rate),
        "currency": agreement.currency,
        "rate_basis": rate_basis(agreement.employment_type),
        "rate_from": rate_from(agreement.kind, agreement.start_date).isoformat(),
        "start_date": agreement.start_date.isoformat(),
        "end_date": _iso(agreement.end_date),
        "agreement_date": agreement.agreement_date.isoformat(),
        "hours_confirmation": agreement.hours_confirmation,
        "payout_day": agreement.payout_day,
        "coordinator_user_id": agreement.coordinator_user_id,
        "coordinator_name": names.get(agreement.coordinator_user_id or 0),
        "signing_channel": agreement.signing_channel,
        "signing_channel_label": CHANNEL_LABELS.get(agreement.signing_channel or ""),
        "sent_at": _iso(agreement.sent_at),
        "signed_on": _iso(agreement.signed_on),
        "signed_at": _iso(agreement.signed_at),
        "manual_reason": agreement.manual_reason,
        "rejected_at": _iso(agreement.rejected_at),
        "cancelled_at": _iso(agreement.cancelled_at),
        "cancel_reason": agreement.cancel_reason,
        "last_error": agreement.last_error,
        "applied_at": _iso(agreement.applied_at),
        "apply_error": agreement.apply_error,
        "document_id": agreement.document_id,
        "symfonia_pending": agreement.symfonia_pending,
        "created_at": _iso(agreement.created_at),
        "actions": actions(agreement, writer=writer, autenti=autenti),
    }


async def _names_for(db: AsyncSession, rows: list[HrAgreement]) -> dict[int, str]:
    ids = {row.user_id for row in rows} | {
        row.coordinator_user_id for row in rows if row.coordinator_user_id
    }
    if not ids:
        return {}
    result = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {row.id: row.name or "" for row in result}


async def _template_infos(
    db: AsyncSession, rows: list[HrAgreement]
) -> dict[int, dict[str, Any]]:
    ids = {row.template_version_id for row in rows}
    if not ids:
        return {}
    result = await db.execute(
        select(
            HrAgreementTemplateVersion.id,
            HrAgreementTemplateVersion.version,
            HrAgreementTemplate.id.label("template_id"),
            HrAgreementTemplate.name,
            HrAgreementTemplate.kind,
        )
        .join(
            HrAgreementTemplate,
            HrAgreementTemplate.id == HrAgreementTemplateVersion.template_id,
        )
        .where(HrAgreementTemplateVersion.id.in_(ids))
    )
    return {
        row.id: {
            "template_id": row.template_id,
            "version_id": row.id,
            "name": row.name,
            "kind": row.kind,
            "version": row.version,
        }
        for row in result
    }


async def payloads(
    db: AsyncSession, rows: list[HrAgreement], *, writer: bool
) -> list[dict[str, Any]]:
    names = await _names_for(db, rows)
    infos = await _template_infos(db, rows)
    autenti = autenti_configured()
    return [
        agreement_payload(
            row,
            names=names,
            template=infos.get(row.template_version_id),
            writer=writer,
            autenti=autenti,
        )
        for row in rows
    ]


async def payload(db: AsyncSession, agreement: HrAgreement, *, writer: bool) -> dict:
    return (await payloads(db, [agreement], writer=writer))[0]


async def list_for_person(db: AsyncSession, user_id: int) -> list[HrAgreement]:
    rows = await db.scalars(
        select(HrAgreement)
        .where(HrAgreement.user_id == user_id)
        .order_by(HrAgreement.created_at.desc(), HrAgreement.id.desc())
    )
    return list(rows)


async def _profile(db: AsyncSession, user_id: int) -> EmployeeProfile:
    profile = await db.scalar(
        select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
    )
    if profile is None:
        raise AgreementNotFound(
            "Ta osoba nie ma kartoteki — najpierw dodaj ją w „Ludziach”."
        )
    return profile


async def person_overview(
    db: AsyncSession, user_id: int, *, writer: bool, payroll: bool = False
) -> dict[str, Any]:
    """Umowy osoby + wartości domyślne nowej umowy dla okna „Nowa umowa albo aneks”.

    ``payroll`` — widz ma uprawnienie Płac albo jest adminem: tylko on dostaje
    stawkę z ostatniej umowy w wartościach domyślnych i tylko jego podpis
    przepisuje stawkę do historii (``applies_rate``; decyzja Artura 19.10.2026).
    """

    person = await db.get(User, user_id)
    if person is None:
        raise AgreementNotFound("Nie ma takiej osoby.")
    profile = await _profile(db, user_id)
    rows = await list_for_person(db, user_id)
    payout_day = (await load_payment_settings(db)).payout_day
    last_signed = next(
        (row for row in rows if row.status == "signed" and row.kind == "agreement"),
        None,
    )
    coordinator_name = None
    if profile.manager_user_id:
        coordinator_name = await db.scalar(
            select(User.name).where(User.id == profile.manager_user_id)
        )
    return {
        "person": {
            "user_id": user_id,
            "name": person.name,
            "employment_type": profile.employment_type,
            "employment_status": profile.employment_status,
        },
        "defaults": {
            "employment_type": profile.employment_type,
            "payout_day": payout_day,
            "coordinator_user_id": profile.manager_user_id,
            "coordinator_name": coordinator_name,
            "hours_confirmation": bool(profile.timesheet_required),
            "currency": last_signed.currency if last_signed else "PLN",
            "hourly_rate": (
                str(last_signed.hourly_rate) if last_signed and payroll else None
            ),
            "base_agreement_id": last_signed.id if last_signed else None,
            "agreement_date": business_today().isoformat(),
        },
        "minimum_rates": payroll_rates.minimum_rates_payload(
            await payroll_rates.load_minimum_rates(db)
        ),
        "autenti_configured": autenti_configured(),
        "can_write": writer,
        "applies_rate": payroll,
        "agreements": await payloads(db, rows, writer=writer),
    }


# ── Szkic: walidacja i zapis ─────────────────────────────────────────────────


@dataclass(frozen=True)
class Draft:
    """Wartości szkicu po walidacji (bez zapisu)."""

    kind: str
    employment_type: str
    template_version_id: int
    base_agreement_id: Optional[int]
    hourly_rate: Decimal
    currency: str
    start_date: date
    end_date: Optional[date]
    agreement_date: date
    hours_confirmation: bool
    payout_day: Optional[int]
    coordinator_user_id: Optional[int]


def _decimal(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError) as exc:
        raise AgreementError("Stawka musi być liczbą, np. 32,00.") from exc
    if not amount.is_finite() or amount <= 0 or amount > _RATE_MAX:
        raise AgreementError("Stawka musi być większa od 0 i najwyżej 9 999 999,99.")
    if amount != amount.quantize(Decimal("0.01")):
        raise AgreementError("Stawka ma najwyżej dwa miejsca po przecinku.")
    return amount.quantize(Decimal("0.01"))


def _date(value: Any, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise AgreementError(f"{label}: podaj datę w formacie RRRR-MM-DD.") from exc


def _optional_date(value: Any, label: str) -> Optional[date]:
    return None if value in (None, "") else _date(value, label)


async def _template_version(
    db: AsyncSession, template_id: Any
) -> tuple[HrAgreementTemplate, HrAgreementTemplateVersion]:
    try:
        template_key = int(template_id)
    except (TypeError, ValueError) as exc:
        raise AgreementError("Wybierz wzór umowy.") from exc
    template = await db.get(HrAgreementTemplate, template_key)
    if template is None:
        raise AgreementError("Nie ma takiego wzoru umowy.")
    if not template.is_active:
        raise AgreementError("Ten wzór jest wycofany — wybierz wzór w użyciu.")
    version = await templates.latest_version(db, template.id)
    if version is None:
        raise AgreementError("Wzór nie ma jeszcze pliku — dodaj wersję wzoru.")
    return template, version


async def _rate_conflict(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    start: date,
    amount: Decimal,
    currency: str,
) -> None:
    """Umowa od połowy miesiąca nie może przepisać stawki dni przed swoim początkiem."""

    if kind == "annex" or start.day == 1:
        return
    current = payroll_rates.rate_on(
        await payroll_rates.history(db, user_id), start.replace(day=1)
    )
    if current is None:
        return
    if current.hourly_rate == amount and current.currency == currency:
        return
    raise AgreementError(
        f"Stawka w historii obowiązuje od 1. dnia miesiąca, a ta osoba ma już stawkę "
        f"na {start:%m.%Y}. Zacznij umowę 1. dnia miesiąca albo zostaw na ten miesiąc "
        "dotychczasową stawkę."
    )


async def _base_agreement(
    db: AsyncSession, base_id: Any, *, user_id: int
) -> Optional[HrAgreement]:
    if base_id in (None, ""):
        return None
    try:
        key = int(base_id)
    except (TypeError, ValueError) as exc:
        raise AgreementError("Wybierz umowę, którą zmienia aneks.") from exc
    base = await db.get(HrAgreement, key)
    if (
        base is None
        or base.user_id != user_id
        or base.kind != "agreement"
        or base.status != "signed"
    ):
        raise AgreementError(
            "Aneks może zmieniać tylko podpisaną umowę tej samej osoby."
        )
    return base


async def _coordinator(db: AsyncSession, value: Any, *, user_id: int) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        key = int(value)
    except (TypeError, ValueError) as exc:
        raise AgreementError("Wybierz koordynatora z listy.") from exc
    if key == user_id:
        raise AgreementError("Koordynatorem nie może być ta sama osoba.")
    active = await db.scalar(select(User.is_active).where(User.id == key))
    if not active:
        raise AgreementError("Koordynator musi mieć aktywne konto w NEXUSIE.")
    return key


def _payout_day(value: Any, employment_type: str, default: int) -> Optional[int]:
    if employment_type == EmploymentType.b2b:
        # B2B płaci się z faktury w terminie z danych do rozliczeń.
        return None
    if value in (None, ""):
        return default
    try:
        day = int(value)
    except (TypeError, ValueError) as exc:
        raise AgreementError("Dzień wypłaty to liczba od 1 do 31.") from exc
    if not 1 <= day <= 31:
        raise AgreementError("Dzień wypłaty to liczba od 1 do 31.")
    return day


async def validate_draft(
    db: AsyncSession,
    *,
    user_id: int,
    values: Mapping[str, Any],
    current: Optional[HrAgreement] = None,
) -> tuple[Draft, Optional[str]]:
    """Wartości szkicu po regułach modułu + ostrzeżenie o minimalnej stawce."""

    profile = await _profile(db, user_id)
    if profile.employment_status == EmploymentStatus.exited:
        raise AgreementConflict(
            "Ta osoba odeszła — umowy z nią już się nie przygotowuje."
        )

    def pick(key: str, fallback: Any) -> Any:
        return values[key] if key in values else fallback

    if "template_id" in values or current is None:
        template, version = await _template_version(db, values.get("template_id"))
        version_id = version.id
        template_kind = template.kind
    else:
        version_obj, template_obj = await templates.version_with_template(
            db, current.template_version_id
        )
        version_id, template_kind = version_obj.id, template_obj.kind
    kind = "annex" if template_kind == "annex" else "agreement"
    if current is not None and kind != current.kind:
        raise AgreementError(
            "Szkic umowy nie zmienia się w aneks ani odwrotnie — anuluj go i przygotuj nowy."
        )

    base = None
    if kind == "annex":
        base = await _base_agreement(
            db,
            pick("base_agreement_id", current.base_agreement_id if current else None),
            user_id=user_id,
        )
        employment_type = base.employment_type if base else profile.employment_type
    else:
        employment_type = template_kind

    amount = _decimal(pick("hourly_rate", current.hourly_rate if current else None))
    currency = str(
        pick("currency", current.currency if current else "PLN") or ""
    ).upper()
    if currency not in CURRENCIES:
        raise AgreementError("Waluta stawki: PLN, EUR albo USD.")
    start = _date(
        pick("start_date", current.start_date if current else None), "Od kiedy"
    )
    end = _optional_date(
        pick("end_date", current.end_date if current else None), "Do kiedy"
    )
    if end is not None and end < start:
        raise AgreementError("Data końca nie może być przed datą początku.")
    if kind == "annex" and start.day != 1:
        raise AgreementError(
            "Aneks zmienia stawkę od 1. dnia miesiąca — tak liczy historia stawek."
        )
    try:
        payroll_rates.validate_effective_from(rate_from(kind, start), business_today())
    except PayrollError as exc:
        raise AgreementError(exc.message) from exc
    agreement_date = _date(
        pick("agreement_date", current.agreement_date if current else business_today()),
        "Data zawarcia",
    )
    hours = bool(
        pick(
            "hours_confirmation",
            current.hours_confirmation if current else profile.timesheet_required,
        )
    )
    if kind == "agreement" and employment_type == EmploymentType.zlecenie and not hours:
        raise AgreementError(
            "Na umowie zlecenia potwierdzanie godzin jest obowiązkowe (art. 8b ustawy "
            "o minimalnym wynagrodzeniu)."
        )
    payout_default = (await load_payment_settings(db)).payout_day
    payout = _payout_day(
        pick("payout_day", current.payout_day if current else None),
        employment_type,
        payout_default,
    )
    coordinator = await _coordinator(
        db,
        pick(
            "coordinator_user_id",
            current.coordinator_user_id if current else profile.manager_user_id,
        ),
        user_id=user_id,
    )

    try:
        warning = payroll_rates.check_mandate_minimum(
            employment_type=employment_type,
            hourly_rate=amount,
            currency=currency,
            effective_from=start,
            rates=await payroll_rates.load_minimum_rates(db),
        )
    except PayrollError as exc:
        raise AgreementError(exc.message) from exc
    await _rate_conflict(
        db, user_id=user_id, kind=kind, start=start, amount=amount, currency=currency
    )
    return (
        Draft(
            kind=kind,
            employment_type=employment_type,
            template_version_id=version_id,
            base_agreement_id=base.id if base else None,
            hourly_rate=amount,
            currency=currency,
            start_date=start,
            end_date=end,
            agreement_date=agreement_date,
            hours_confirmation=hours,
            payout_day=payout,
            coordinator_user_id=coordinator,
        ),
        warning,
    )


def ensure_not_self(actor: User, user_id: int) -> None:
    if actor.id == user_id:
        raise AgreementError(
            "Umowy ze sobą nie przygotowujesz — poproś drugą osobę z Kadr.", status=403
        )


def _draft_details(draft: Draft) -> dict[str, Any]:
    return {
        "kind": draft.kind,
        "employment_type": draft.employment_type,
        "template_version_id": draft.template_version_id,
        "hourly_rate": str(draft.hourly_rate),
        "currency": draft.currency,
        "start_date": draft.start_date.isoformat(),
        "end_date": _iso(draft.end_date),
        "hours_confirmation": draft.hours_confirmation,
    }


async def _flush_live(db: AsyncSession) -> None:
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        if _LIVE_INDEX not in str(exc.orig):
            raise
        raise AgreementConflict(
            "Ta osoba ma już umowę albo aneks w przygotowaniu — dokończ go albo anuluj."
        ) from exc


async def create_draft(
    db: AsyncSession, *, user_id: int, values: Mapping[str, Any], actor: User
) -> tuple[HrAgreement, Optional[str]]:
    ensure_not_self(actor, user_id)
    draft, warning = await validate_draft(db, user_id=user_id, values=values)
    live = await db.scalar(
        select(HrAgreement.id).where(
            HrAgreement.user_id == user_id,
            HrAgreement.kind == draft.kind,
            HrAgreement.status.in_(LIVE_STATUSES),
        )
    )
    if live is not None:
        raise AgreementConflict(
            "Ta osoba ma już "
            + ("aneks" if draft.kind == "annex" else "umowę")
            + " w przygotowaniu — dokończ go albo anuluj."
        )
    agreement = HrAgreement(
        user_id=user_id,
        kind=draft.kind,
        employment_type=draft.employment_type,
        template_version_id=draft.template_version_id,
        base_agreement_id=draft.base_agreement_id,
        status="draft",
        hourly_rate=draft.hourly_rate,
        currency=draft.currency,
        start_date=draft.start_date,
        end_date=draft.end_date,
        agreement_date=draft.agreement_date,
        hours_confirmation=draft.hours_confirmation,
        payout_day=draft.payout_day,
        coordinator_user_id=draft.coordinator_user_id,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(agreement)
    await _flush_live(db)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="hr_agreement",
        entity_id=agreement.id,
        action="agreement_created",
        sensitivity="payroll",
        details=_draft_details(draft),
    )
    return agreement, warning


async def update_draft(
    db: AsyncSession, agreement_id: int, values: Mapping[str, Any], *, actor: User
) -> tuple[HrAgreement, Optional[str]]:
    agreement = await get_agreement(db, agreement_id, lock=True)
    ensure_not_self(actor, agreement.user_id)
    if agreement.status != "draft":
        raise AgreementConflict("Zmieniać można tylko szkic umowy.")
    clean = {key: value for key, value in values.items() if key in EDITABLE_FIELDS}
    draft, warning = await validate_draft(
        db, user_id=agreement.user_id, values=clean, current=agreement
    )
    for key in (
        "template_version_id",
        "base_agreement_id",
        "hourly_rate",
        "currency",
        "start_date",
        "end_date",
        "agreement_date",
        "hours_confirmation",
        "payout_day",
        "coordinator_user_id",
    ):
        setattr(agreement, key, getattr(draft, key))
    agreement.updated_by = actor.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=agreement.user_id,
        entity_type="hr_agreement",
        entity_id=agreement.id,
        action="agreement_updated",
        sensitivity="payroll",
        details={"fields": sorted(clean), **_draft_details(draft)},
    )
    return agreement, warning


def clean_reason(value: Any, *, label: str = "Powód") -> str:
    reason = " ".join(str(value or "").split())
    if not reason:
        raise AgreementError(f"{label}: wpisz, dlaczego.")
    if len(reason) > REASON_MAX_LENGTH:
        raise AgreementError(f"{label}: najwyżej {REASON_MAX_LENGTH} znaków.")
    return reason


__all__ = [
    "CHANNEL_LABELS",
    "Draft",
    "EDITABLE_FIELDS",
    "MODULE_DISABLED_DETAIL",
    "SETTINGS_KEY",
    "STATUS_LABELS",
    "actions",
    "agreement_payload",
    "autenti_configured",
    "clean_reason",
    "create_draft",
    "ensure_not_self",
    "get_agreement",
    "list_for_person",
    "load_enabled",
    "open_for",
    "payload",
    "payloads",
    "person_overview",
    "rate_basis",
    "rate_from",
    "save_enabled",
    "title",
    "update_draft",
    "validate_draft",
]
