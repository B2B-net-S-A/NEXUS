"""Historia stawek godzinowych pracowników (``employee_rates``).

Reguły (Compass ``internal-rates.ts`` + naprawy):

* stawka obowiązuje od 1. dnia miesiąca (CHECK w bazie),
* zmiana wstecz najwyżej o 12 miesięcy, licząc od miesiąca „dziś” w kalendarzu
  firmy — Compass liczył „przyszły miesiąc” w UTC (``internal-rates.ts:78-86``),
* nowa stawka domyka poprzednią w tej samej transakcji (``effective_to`` =
  dzień przed nową) i sama kończy się dzień przed kolejną, jeśli taka jest,
* ta sama data „od” = poprawka istniejącego kroku,
* nic nie zmienia się w zamkniętym miesiącu płac (409) — także w miesiącu,
  który właśnie się zamyka: miesiące od daty stawki do „dziś” są sprawdzane pod
  blokadą współdzieloną, ZANIM zablokujemy historię stawek (kolejność jak przy
  akceptacjach: okres, potem reszta),
* osoba dostaje dzwonek ``hr_rate_changed`` BEZ kwoty (Compass miał typ
  ``rate_changed``, którego nikt nie wysyłał); kwota zostaje w
  ``hr_audit_events`` z ``sensitivity='payroll'``,
* umowa zlecenie (etap 2, D7): stawka godzinowa nie niższa niż minimalna
  stawka roku ``effective_from`` (ustawa o minimalnym wynagrodzeniu za pracę;
  2025: 30,50 zł, 2026: 31,40 zł brutto). Tabela lat to ustawienie Płac
  ``app_settings['hr_minimum_hourly_rates']`` — nowy rok dopisują Płace bez
  wdrożenia. Brak minimum dla roku = zapis bez kontroli i ostrzeżenie.
  Stawka z poprzedniego roku obowiązuje dalej w nowym (także po usunięciu
  kroku nowego roku), więc raport miesiąca płac sprawdza tę samą regułą
  (``mandate_minimum_shortfall``) stawkę obowiązującą w miesiącu i ostrzega
  przed zamknięciem (``payroll_report.minimum_rate_warnings``),
* własnej stawki nie ustawia ani nie usuwa nikt z Płac — robi to druga osoba
  z Płac albo administrator (decyzja Artura 19.10.2026, ``ensure_not_own_rate``);
  administratorowi wolno, ślad w ``hr_audit_events`` jak przy każdej zmianie.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today

from app.models.app_setting import AppSetting
from app.models.hr_payroll import EmployeeRate
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.services.hr import audit
from app.services.hr.employment_terms import terms
from app.services.hr.notify import notify_each
from app.services.hr.payroll_errors import (
    PayrollError,
    PayrollForbidden,
    PayrollNotFound,
)
from app.services.hr.payroll_periods import (
    add_months,
    assert_range_open,
    lock_months_shared,
)
from app.services.hr_payroll_schema import CURRENCIES
from app.services.hr_foundation_schema import EmploymentType

logger = logging.getLogger(__name__)

RATE_BACKDATE_MAX_MONTHS = 12
OWN_RATE_SET_DETAIL = (
    "Własnej stawki nie ustawiasz — zrobi to druga osoba z Płac albo administrator."
)
OWN_RATE_DELETE_DETAIL = (
    "Własnej stawki nie usuwasz — zrobi to druga osoba z Płac albo administrator."
)
RATE_AHEAD_MAX_MONTHS = 24
RATE_MAX = Decimal("9999999.99")

MINIMUM_RATES_SETTING = "hr_minimum_hourly_rates"
#: Minimalna stawka godzinowa na zleceniu (zł brutto) — rozporządzenia RM.
DEFAULT_MINIMUM_RATES: dict[int, Decimal] = {
    2025: Decimal("30.50"),
    2026: Decimal("31.40"),
}
MINIMUM_RATE_MAX = Decimal("1000")
MANDATE_FORM = EmploymentType.zlecenie


# ── Minimalna stawka godzinowa na zleceniu (D7) ───────────────────────────────


def format_pln(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def parse_minimum_rates(raw: Any) -> dict[int, Decimal]:
    """``{"2026": "31.40", …}`` → ``{2026: Decimal("31.40")}``; błąd = ``PayrollError``."""

    if not isinstance(raw, dict):
        raise PayrollError("Minimalne stawki to lista: rok i kwota.")
    rates: dict[int, Decimal] = {}
    for key, value in raw.items():
        try:
            year = int(str(key))
            amount = Decimal(str(value))
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise PayrollError(f"Nieprawidłowy wpis minimalnej stawki: {key}.") from exc
        if not 2020 <= year <= 2100:
            raise PayrollError("Rok minimalnej stawki: od 2020 do 2100.")
        if not amount.is_finite() or amount <= 0 or amount > MINIMUM_RATE_MAX:
            raise PayrollError(
                f"Minimalna stawka w {year}: kwota większa od 0 i najwyżej "
                f"{MINIMUM_RATE_MAX} zł."
            )
        rates[year] = amount.quantize(Decimal("0.01"))
    return dict(sorted(rates.items()))


def minimum_rates_payload(rates: dict[int, Decimal]) -> dict[str, str]:
    return {str(year): f"{amount:.2f}" for year, amount in sorted(rates.items())}


async def load_minimum_rates(db: AsyncSession) -> dict[int, Decimal]:
    """Tabela z Ustawień; brak albo zepsuty wpis = stawki domyślne (bez blokady)."""

    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == MINIMUM_RATES_SETTING)
    )
    if raw is None:
        return dict(DEFAULT_MINIMUM_RATES)
    try:
        return parse_minimum_rates(raw)
    except PayrollError:
        logger.warning("[payroll] zepsute %s — stawki domyślne", MINIMUM_RATES_SETTING)
        return dict(DEFAULT_MINIMUM_RATES)


async def save_minimum_rates(
    db: AsyncSession, raw: Any, *, actor_id: int
) -> dict[int, Decimal]:
    """Waliduje i zapisuje tabelę minimalnych stawek (bez commita)."""

    rates = parse_minimum_rates(raw)
    statement = insert(AppSetting).values(
        key=MINIMUM_RATES_SETTING,
        value=minimum_rates_payload(rates),
        updated_by=actor_id,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
    return rates


def mandate_minimum_shortfall(
    *,
    employment_type: Optional[str],
    hourly_rate: Decimal,
    currency: str,
    year: int,
    rates: dict[int, Decimal],
) -> Optional[Decimal]:
    """Minimum roku ``year``, gdy stawka zlecenia w złotych jest od niego niższa.

    Jedna reguła dla zapisu stawki (422) i raportu miesiąca płac (ostrzeżenie).
    Inna forma, inna waluta albo rok bez minimum = ``None``.
    """

    if employment_type != MANDATE_FORM or currency != "PLN":
        return None
    minimum = rates.get(year)
    if minimum is None or hourly_rate >= minimum:
        return None
    return minimum


def check_mandate_minimum(
    *,
    employment_type: Optional[str],
    hourly_rate: Decimal,
    currency: str,
    effective_from: date,
    rates: dict[int, Decimal],
) -> Optional[str]:
    """Stawka zlecenia poniżej minimum roku → ``PayrollError`` (422).

    Zwraca ostrzeżenie (bez blokady), gdy minimum dla roku nie jest ustawione
    albo stawka jest w innej walucie niż złoty. Inne formy — ``None``.
    """

    if employment_type != MANDATE_FORM:
        return None
    year = effective_from.year
    minimum = rates.get(year)
    if minimum is None:
        return (
            f"Minimalna stawka na zleceniu w {year} nie jest ustawiona "
            "(Ustawienia → Płace) — stawka zapisana bez kontroli."
        )
    if currency != "PLN":
        return (
            f"Minimalna stawka na zleceniu jest w złotych ({format_pln(minimum)} zł/h "
            f"w {year}) — sprawdź przeliczenie stawki w {currency}."
        )
    if (
        mandate_minimum_shortfall(
            employment_type=employment_type,
            hourly_rate=hourly_rate,
            currency=currency,
            year=year,
            rates=rates,
        )
        is not None
    ):
        raise PayrollError(
            f"Minimalna stawka na zleceniu w {year} to {format_pln(minimum)} zł/h brutto."
        )
    return None


async def mandate_minimum_check(
    db: AsyncSession,
    *,
    user_id: int,
    hourly_rate: Decimal,
    currency: str,
    effective_from: date,
) -> Optional[str]:
    """Kontrola minimum dla osoby z kartoteki (forma z ``employee_profiles``)."""

    employment_type = await db.scalar(
        select(EmployeeProfile.employment_type).where(
            EmployeeProfile.user_id == user_id
        )
    )
    if employment_type != MANDATE_FORM:
        return None
    return check_mandate_minimum(
        employment_type=employment_type,
        hourly_rate=hourly_rate,
        currency=(currency or "").strip().upper(),
        effective_from=effective_from,
        rates=await load_minimum_rates(db),
    )


def validate_effective_from(effective_from: date, today: date) -> None:
    if effective_from.day != 1:
        raise PayrollError("Stawka obowiązuje od 1. dnia miesiąca.")
    earliest = date(*add_months(today.year, today.month, -RATE_BACKDATE_MAX_MONTHS), 1)
    if effective_from < earliest:
        raise PayrollError(
            "Stawkę można zmienić wstecz najwyżej o "
            f"{RATE_BACKDATE_MAX_MONTHS} miesięcy (od {earliest:%d.%m.%Y})."
        )
    latest = date(*add_months(today.year, today.month, RATE_AHEAD_MAX_MONTHS), 1)
    if effective_from > latest:
        raise PayrollError(f"Stawkę można zaplanować najdalej na {latest:%m.%Y}.")


def validate_rate(hourly_rate: Decimal, currency: str) -> tuple[Decimal, str]:
    if not hourly_rate.is_finite() or hourly_rate < 0 or hourly_rate > RATE_MAX:
        raise PayrollError("Stawka musi być liczbą od 0 do 9 999 999,99.")
    code = (currency or "").strip().upper()
    if code not in CURRENCIES:
        raise PayrollError("Waluta stawki: PLN, EUR albo USD.")
    # HALF_UP jak raport płac (``payroll_report.money``); RATE_MAX ma dwa miejsca
    # po przecinku, więc wynik zaokrąglenia nie wyjdzie poza zakres.
    return hourly_rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), code


def rate_payload(rate: EmployeeRate) -> dict[str, Any]:
    return {
        "id": rate.id,
        "user_id": rate.user_id,
        "hourly_rate": str(rate.hourly_rate),
        "currency": rate.currency,
        "effective_from": rate.effective_from.isoformat(),
        "effective_to": rate.effective_to.isoformat() if rate.effective_to else None,
        "reason": rate.reason,
        "set_by": rate.set_by,
    }


def rate_on(rates: list[EmployeeRate], day: date) -> Optional[EmployeeRate]:
    """Stawka obowiązująca w dniu ``day`` (historia posortowana dowolnie)."""

    for rate in rates:
        if rate.effective_from <= day and (
            rate.effective_to is None or rate.effective_to >= day
        ):
            return rate
    return None


def rate_to_close(
    earlier: list[EmployeeRate], effective_from: date
) -> Optional[EmployeeRate]:
    """Stawka do domknięcia dniem przed nową: tylko ta, która w tym dniu trwa.

    ``earlier`` — kroki sprzed nowej daty, rosnąco. Ostatni z nich, zakończony
    przed nową datą (luka z importu Compassa: stawka z końcem, bez następnej),
    zostaje nietknięty — inaczej luka wypełniłaby się starą stawką: miesiące
    bez stawki liczyłyby się nią zamiast ostrzeżenia ``missing_rates``, a zamknięty
    miesiąc zmieniałby się bez 409, bo blokada i kontrola zamkniętych miesięcy
    zaczynają się od nowej daty (audyt A2, 19.10.2026).
    """

    if not earlier:
        return None
    before = earlier[-1]
    if before.effective_to is None or before.effective_to >= effective_from:
        return before
    return None


async def history(db: AsyncSession, user_id: int) -> list[EmployeeRate]:
    rows = await db.scalars(
        select(EmployeeRate)
        .where(EmployeeRate.user_id == user_id)
        .order_by(EmployeeRate.effective_from.desc())
    )
    return list(rows)


async def _locked_history(db: AsyncSession, user_id: int) -> list[EmployeeRate]:
    profile = await db.scalar(
        select(EmployeeProfile.id)
        .where(EmployeeProfile.user_id == user_id)
        .with_for_update()
    )
    if profile is None:
        raise PayrollNotFound("Ta osoba nie ma kartoteki pracownika.")
    rows = await db.scalars(
        select(EmployeeRate)
        .where(EmployeeRate.user_id == user_id)
        .order_by(EmployeeRate.effective_from)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _notify(db: AsyncSession, rate: EmployeeRate) -> None:
    # Zakładka „Premie i stawka” / „Wynagrodzenie dodatkowe i stawka” (21.10.2026).
    form = await db.scalar(
        select(EmployeeProfile.employment_type).where(
            EmployeeProfile.user_id == rate.user_id
        )
    )
    # Dzwonek nie cofa zapisu stawki (``notify_each`` łapie awarię).
    await notify_each(
        db,
        [rate.user_id],
        title="Zmiana Twojej stawki",
        message=(
            f"Nowa stawka obowiązuje od {rate.effective_from:%d.%m.%Y}. "
            f"Szczegóły w „Moim czasie” → {terms(form)['bonuses_tab']}."
        ),
        ntype=NotificationType.hr_rate_changed,
        link="/my-time?tab=bonuses",
        related_entity_type="employee_rate",
        related_entity_id=rate.id,
        log_tag="payroll",
    )


def ensure_not_own_rate(
    user_id: int, *, actor_id: int, actor_is_admin: bool, deleting: bool = False
) -> None:
    """Własna stawka = 403, chyba że zmienia ją administrator (decyzja 19.10.2026).

    Bo osoba z Płac podniosłaby sobie stawkę bez drugiej pary oczu.
    """

    if user_id == actor_id and not actor_is_admin:
        raise PayrollForbidden(
            OWN_RATE_DELETE_DETAIL if deleting else OWN_RATE_SET_DETAIL
        )


async def set_rate(
    db: AsyncSession,
    *,
    user_id: int,
    hourly_rate: Decimal,
    currency: str,
    effective_from: date,
    reason: Optional[str],
    actor_id: int,
    today: date,
    actor_is_admin: bool = False,
) -> EmployeeRate:
    """Nowa stawka od 1. dnia miesiąca (albo poprawka kroku z tą samą datą)."""

    ensure_not_own_rate(user_id, actor_id=actor_id, actor_is_admin=actor_is_admin)
    validate_effective_from(effective_from, today)
    amount, code = validate_rate(hourly_rate, currency)
    await mandate_minimum_check(
        db,
        user_id=user_id,
        hourly_rate=amount,
        currency=code,
        effective_from=effective_from,
    )
    note = (reason or "").strip() or None
    if note and len(note) > 500:
        raise PayrollError("Powód zmiany: najwyżej 500 znaków.")

    await lock_months_shared(db, effective_from, today)
    rows = await _locked_history(db, user_id)
    same = next((r for r in rows if r.effective_from == effective_from), None)
    earlier = [r for r in rows if r.effective_from < effective_from]
    later = [r for r in rows if r.effective_from > effective_from]
    new_to = later[0].effective_from - timedelta(days=1) if later else None
    await assert_range_open(db, effective_from, new_to)

    previous: Optional[dict[str, Any]] = None
    if same is not None:
        previous = {"hourly_rate": str(same.hourly_rate), "currency": same.currency}
        same.hourly_rate = amount
        same.currency = code
        same.reason = note
        same.set_by = actor_id
        rate = same
    else:
        before = rate_to_close(earlier, effective_from)
        if before is not None:
            previous = {
                "hourly_rate": str(before.hourly_rate),
                "currency": before.currency,
            }
            before.effective_to = effective_from - timedelta(days=1)
            # Indeks „jedna otwarta stawka” sprawdza każdy wiersz od razu.
            await db.flush()
        rate = EmployeeRate(
            user_id=user_id,
            hourly_rate=amount,
            currency=code,
            effective_from=effective_from,
            effective_to=new_to,
            reason=note,
            set_by=actor_id,
        )
        db.add(rate)
    await db.flush()

    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=user_id,
        entity_type="employee_rate",
        entity_id=rate.id,
        action="rate_set" if same is None else "rate_corrected",
        sensitivity="payroll",
        details={
            "effective_from": effective_from.isoformat(),
            "effective_to": new_to.isoformat() if new_to else None,
            "hourly_rate": str(amount),
            "currency": code,
            "previous": previous,
        },
    )
    await _notify(db, rate)
    return rate


async def delete_rate(
    db: AsyncSession, *, rate_id: int, actor_id: int, actor_is_admin: bool = False
) -> int:
    """Usuwa pomyłkowy krok; poprzedni krok przejmuje jego okres. Zwraca ``user_id``."""

    found = (
        await db.execute(
            select(EmployeeRate.user_id, EmployeeRate.effective_from).where(
                EmployeeRate.id == rate_id
            )
        )
    ).first()
    if found is None:
        raise PayrollNotFound("Nie ma takiej stawki.")
    user_id = found.user_id
    ensure_not_own_rate(
        user_id, actor_id=actor_id, actor_is_admin=actor_is_admin, deleting=True
    )
    # Data „od” kroku się nie zmienia (ta sama data = poprawka w miejscu), więc
    # blokada od niej do „dziś” obejmuje każdy miesiąc, którego dotyczy usunięcie.
    await lock_months_shared(db, found.effective_from, business_today())
    rows = await _locked_history(db, user_id)
    rate = next((r for r in rows if r.id == rate_id), None)
    if rate is None:
        raise PayrollNotFound("Nie ma takiej stawki.")
    await assert_range_open(db, rate.effective_from, rate.effective_to)
    before = next(
        (r for r in rows if r.effective_to == rate.effective_from - timedelta(days=1)),
        None,
    )
    snapshot = rate_payload(rate)
    await db.delete(rate)
    await db.flush()
    if before is not None:
        before.effective_to = rate.effective_to
        await db.flush()
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=user_id,
        entity_type="employee_rate",
        entity_id=rate_id,
        action="rate_deleted",
        sensitivity="payroll",
        details={"deleted": snapshot},
    )
    return int(user_id)


__all__ = [
    "DEFAULT_MINIMUM_RATES",
    "MINIMUM_RATES_SETTING",
    "RATE_BACKDATE_MAX_MONTHS",
    "OWN_RATE_DELETE_DETAIL",
    "OWN_RATE_SET_DETAIL",
    "check_mandate_minimum",
    "ensure_not_own_rate",
    "format_pln",
    "load_minimum_rates",
    "mandate_minimum_shortfall",
    "mandate_minimum_check",
    "minimum_rates_payload",
    "parse_minimum_rates",
    "save_minimum_rates",
    "delete_rate",
    "history",
    "rate_on",
    "rate_payload",
    "set_rate",
    "validate_effective_from",
    "validate_rate",
]
