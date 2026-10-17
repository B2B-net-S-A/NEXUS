"""Ustawienia płatności i słowniki Symfonii (``app_settings['hr_payment_settings']``).

Zmieniają je Płace w Ustawieniach → Płace (karta „Płatności i Symfonia”):

* **dzień wypłaty** zlecenia i UoP — termin rozliczenia to ten dzień następnego
  miesiąca (domyślnie 10.). Ten sam wpis czyta termin w rozliczeniu
  (``settlements.load_payout_day`` i ``settlements_rules.payout_date``),
* **paczka przelewów** (R9) — opcja, domyślnie WYŁĄCZONA: przelewy robią
  Finanse jak dziś (eBI24 albo bank). Włączona wymaga rachunku i nazwy nadawcy,
* **słowniki Symfonii** (R5) — dokładne nazwy zdarzeń nieobecności z „Definicji
  zdarzeń”, zdarzenie nadgodzin i początek dnia pracy (koniec normy 8 h =
  początek nadgodzin), kolumny premii (rodzaj premii NEXUSA → nazwa kolumny
  w szablonie importu), rodzaj umowy i forma płatności w szablonie rozliczeń
  umów. Puste pole = ten rodzaj nie trafia do pliku, a zestawienie PDF pokazuje
  go jako rzecz do wpisania ręcznie. L4 eksportujemy tylko po włączeniu „Płace
  nie pobierają e-ZLA z PUE ZUS” — inaczej Symfonia ma je z e-ZLA i plik by je
  zdublował.

Wartości domyślne pochodzą z dokumentacji Symfonii (17.10.2026) i czekają na
potwierdzenie Płac. Zepsuty wpis w bazie = wartości domyślne (z ostrzeżeniem
w logu, bez treści wpisu), zapis = walidacja i 422 z opisem.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services.hr.bank.accounts import AccountError, normalize_nrb
from app.services.hr.payroll_errors import PayrollError
from app.services.hr.settlements_rules import DEFAULT_PAYOUT_DAY, PAYMENT_SETTINGS_KEY
from app.services.hr_leave_schema import LEAVE_TYPES
from app.services.hr_payroll_schema import BONUS_CATEGORIES
from app.services.hr_settlement_schema import BATCH_FORMATS

logger = logging.getLogger(__name__)

#: Jeden wpis z rozliczeniami (R-A czyta z niego ``payout_day``).
SETTING_KEY = PAYMENT_SETTINGS_KEY
NAME_MAX = 100
#: Nazwa i adres nadawcy w Elixir-O: 4 linie po 35 znaków.
SENDER_NAME_MAX = 140

#: Nazwy zdarzeń z dokumentacji Symfonii ERP Kadry i Płace 2026 (do potwierdzenia
#: w „Definicjach zdarzeń” u Płac). Brak nazwy = do wpisania ręcznie.
DEFAULT_LEAVE_EVENTS: dict[str, str] = {
    "vacation": "Urlop wypoczynkowy",
    "on_demand": "Urlop wypoczynkowy na żądanie",
    "occasional": "Urlop okolicznościowy",
    "unpaid_leave": "Urlop bezpłatny",
    "childcare": "Opieka nad dzieckiem – art. 188 KP",
    "force_majeure": "Nieobecność z tytułu siły wyższej",
    "maternity": "Urlop macierzyński",
    "parental_leave": "Urlop rodzicielski",
    "childrearing": "Urlop wychowawczy",
    "sick_leave": "Choroba zwykła",
}
#: Kolumny premii w pliku dla szablonu „danych kadrowych” (jedna na rodzaj).
DEFAULT_BONUS_COMPONENTS: dict[str, str] = {
    "sales": "Premia sprzedażowa",
    "delivery_lead": "Premia Delivery Lead",
    "recruiter": "Premia rekrutacyjna",
    "league": "Premia Liga Mistrzów",
    "custom": "Premia uznaniowa",
}

_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
#: Najpóźniejszy początek dnia, przy którym 8 h normy kończy się przed północą.
LATEST_WORK_START_HOUR = 15


@dataclass(frozen=True)
class SymfoniaSettings:
    leave_events: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_LEAVE_EVENTS)
    )
    export_sick_leave: bool = False
    overtime_event: str = "Nadgodziny"
    work_start: str = "08:00"
    bonus_components: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_BONUS_COMPONENTS)
    )
    contract_kind: str = "zlecenie"
    payment_form: str = "przelew"


@dataclass(frozen=True)
class TransferBatchSettings:
    enabled: bool = False
    format: str = "elixir"
    sender_account: Optional[str] = None
    sender_name: str = ""


@dataclass(frozen=True)
class PaymentSettings:
    payout_day: int = DEFAULT_PAYOUT_DAY
    transfer_batch: TransferBatchSettings = field(default_factory=TransferBatchSettings)
    symfonia: SymfoniaSettings = field(default_factory=SymfoniaSettings)


DEFAULTS = PaymentSettings()


def _text(value: Any, label: str, *, limit: int = NAME_MAX) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PayrollError(f"{label}: tekst.")
    cleaned = value.strip()
    if _CONTROL.search(cleaned):
        raise PayrollError(f"{label}: bez znaków sterujących.")
    if len(cleaned) > limit:
        raise PayrollError(f"{label}: najwyżej {limit} znaków.")
    return cleaned


def _names(
    raw: Any, allowed: tuple[str, ...], defaults: Mapping[str, str], label: str
) -> dict[str, str]:
    if raw is None:
        return dict(defaults)
    if not isinstance(raw, Mapping):
        raise PayrollError(f"{label}: lista nazw.")
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise PayrollError(f"{label}: nieznane klucze {', '.join(unknown)}.")
    names: dict[str, str] = {}
    for key in allowed:
        value = _text(raw.get(key), f"{label} ({key})")
        if value:
            names[key] = value
    return names


def _bool(value: Any, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise PayrollError(f"{label}: tak albo nie.")
    return value


def _batch(raw: Any) -> TransferBatchSettings:
    raw = raw or {}
    if not isinstance(raw, Mapping):
        raise PayrollError("Paczka przelewów: niepoprawny format.")
    batch_format = raw.get("format") or "elixir"
    if batch_format not in BATCH_FORMATS:
        raise PayrollError("Format paczki: Elixir-O albo CSV.")
    account_raw = raw.get("sender_account")
    sender_account: Optional[str] = None
    if account_raw not in (None, ""):
        try:
            sender_account = normalize_nrb(str(account_raw))
        except AccountError as exc:
            raise PayrollError(f"Rachunek nadawcy: {exc}") from exc
    sender_name = _text(raw.get("sender_name"), "Nazwa nadawcy", limit=SENDER_NAME_MAX)
    enabled = _bool(raw.get("enabled"), "Paczka przelewów", False)
    if enabled and (sender_account is None or not sender_name):
        raise PayrollError("Paczka przelewów wymaga rachunku i nazwy nadawcy (firmy).")
    return TransferBatchSettings(
        enabled=enabled,
        format=batch_format,
        sender_account=sender_account,
        sender_name=sender_name,
    )


def _symfonia(raw: Any) -> SymfoniaSettings:
    raw = raw or {}
    if not isinstance(raw, Mapping):
        raise PayrollError("Symfonia: niepoprawny format.")
    work_start = raw.get("work_start") or "08:00"
    if not isinstance(work_start, str) or not _TIME.match(work_start):
        raise PayrollError("Początek dnia pracy: GG:MM, np. 08:00.")
    if int(work_start[:2]) > LATEST_WORK_START_HOUR:
        raise PayrollError("Początek dnia pracy: najpóźniej 15:59.")
    contract_kind = _text(raw.get("contract_kind", "zlecenie"), "Rodzaj umowy")
    payment_form = _text(raw.get("payment_form", "przelew"), "Forma płatności")
    if not contract_kind or not payment_form:
        raise PayrollError(
            "Rodzaj umowy i forma płatności są potrzebne w pliku rozliczeń zleceń."
        )
    return SymfoniaSettings(
        leave_events=_names(
            raw.get("leave_events"),
            LEAVE_TYPES,
            DEFAULT_LEAVE_EVENTS,
            "Zdarzenia nieobecności",
        ),
        export_sick_leave=_bool(raw.get("export_sick_leave"), "Eksport L4", False),
        overtime_event=_text(raw.get("overtime_event", "Nadgodziny"), "Nadgodziny"),
        work_start=work_start,
        bonus_components=_names(
            raw.get("bonus_components"),
            BONUS_CATEGORIES,
            DEFAULT_BONUS_COMPONENTS,
            "Kolumny premii",
        ),
        contract_kind=contract_kind,
        payment_form=payment_form,
    )


def parse_settings(raw: Any) -> PaymentSettings:
    """Słownik z bazy albo z formularza → ``PaymentSettings``; błąd = 422."""

    if raw is None:
        return DEFAULTS
    if not isinstance(raw, Mapping):
        raise PayrollError("Ustawienia płatności: niepoprawny format.")
    payout = raw.get("payout_day", DEFAULT_PAYOUT_DAY)
    if isinstance(payout, bool) or not isinstance(payout, int) or not 1 <= payout <= 31:
        raise PayrollError("Dzień wypłaty: liczba od 1 do 31.")
    return PaymentSettings(
        payout_day=payout,
        transfer_batch=_batch(raw.get("transfer_batch")),
        symfonia=_symfonia(raw.get("symfonia")),
    )


def as_payload(settings: PaymentSettings) -> dict[str, Any]:
    """Postać do zapisu w ``app_settings`` i do odpowiedzi API."""

    batch = settings.transfer_batch
    sym = settings.symfonia
    return {
        "payout_day": settings.payout_day,
        "transfer_batch": {
            "enabled": batch.enabled,
            "format": batch.format,
            "sender_account": batch.sender_account,
            "sender_name": batch.sender_name,
        },
        "symfonia": {
            "leave_events": dict(sym.leave_events),
            "export_sick_leave": sym.export_sick_leave,
            "overtime_event": sym.overtime_event,
            "work_start": sym.work_start,
            "bonus_components": dict(sym.bonus_components),
            "contract_kind": sym.contract_kind,
            "payment_form": sym.payment_form,
        },
    }


async def load_settings(db: AsyncSession) -> PaymentSettings:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    if raw is None:
        return DEFAULTS
    try:
        return parse_settings(raw)
    except PayrollError:
        logger.warning("[payments] zepsute %s — wartości domyślne", SETTING_KEY)
        return DEFAULTS


async def save_settings(
    db: AsyncSession, raw: Mapping[str, Any], *, actor_id: int
) -> PaymentSettings:
    """Zapis z formularza; pola, których formularz nie przysłał, zostają.

    Ten sam wpis czyta termin rozliczenia (``payout_day``) — zapis samych
    słowników nie może go zgubić, a inne klucze wpisu zostają nietknięte.
    """

    stored = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SETTING_KEY)
    )
    current = dict(stored) if isinstance(stored, Mapping) else {}
    merged = {
        **current,
        **{key: value for key, value in raw.items() if value is not None},
    }
    parsed = parse_settings(merged)
    value = {**current, **as_payload(parsed)}
    statement = insert(AppSetting).values(
        key=SETTING_KEY, value=value, updated_by=actor_id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
    return parsed


__all__ = [
    "DEFAULTS",
    "DEFAULT_BONUS_COMPONENTS",
    "DEFAULT_LEAVE_EVENTS",
    "DEFAULT_PAYOUT_DAY",
    "PaymentSettings",
    "SETTING_KEY",
    "SymfoniaSettings",
    "TransferBatchSettings",
    "as_payload",
    "load_settings",
    "parse_settings",
    "save_settings",
]
