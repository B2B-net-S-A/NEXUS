"""Ustawienia wystawiania faktur sprzedaży (``app_settings['client_invoice_issue']``, E4).

Dane sprzedawcy, rachunki per waluta, domyślny termin płatności, nazwa usługi
w pozycji, wzory numerów serii, domyślna stawka VAT i jej nadpisanie przy
kliencie. Nic z tego nie stoi w kodzie: brak wiersza = puste dane sprzedawcy,
a wysyłka do KSeF czeka, aż Finanse je uzupełnią.

„Następny numer” serii w miesiącu nie jest tutaj, tylko w
``client_invoice_series`` (``numbering.py``): numer nadaje się pod blokadą
wiersza, a JSON w ``app_settings`` takiej blokady nie daje.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services.client_invoice_issue_schema import SERIES
from app.services.client_invoicing.fa3_build import VAT_RATES
from app.services.client_sales_invoices_schema import CURRENCIES
from app.services.order_client_identity import nip_checksum_valid

SETTING_KEY = "client_invoice_issue"
#: Wzory jak w eBI24 (archiwum 2026): miesiąc bez zera, „/UE”, „/Benefit”, „/KORUE”.
DEFAULT_SERIES: dict[str, str] = {
    "PL": "{n}/{m}/{yyyy}",
    "UE": "{n}/{m}/{yyyy}/UE",
    "ZAL": "ZAL/{n}/{m}/{yyyy}",
    "KOR": "KOR/{n}/{m}/{yyyy}",
    "BEN": "{n}/{m}/{yyyy}/Benefit",
    "KORUE": "{n}/{m}/{yyyy}/KORUE",
}
SERIES_LABELS: dict[str, str] = {
    "PL": "Krajowa",
    "UE": "Nabywca z UE",
    "ZAL": "Zaliczkowa",
    "KOR": "Korekta",
    "BEN": "Refaktura benefitu",
    "KORUE": "Korekta faktury UE",
}
#: Seria bez rachunku na fakturze — refaktura rozliczana kompensatą (potrąceniem).
COMPENSATION_SERIES = frozenset({"BEN"})
COMPENSATION_LABEL = "Kompensata"
DEFAULT_PAYMENT_DAYS = 14
DEFAULT_VAT = "23"
DEFAULT_SERVICE_NAME = "Usługi informatyczne"
PATTERN_TOKENS = ("{n}", "{yyyy}")
MONTH_TOKENS = ("{m}", "{mm}")
PATTERN_MAX = 40
TEXT_MAX = 255
ACCOUNT_MIN, ACCOUNT_MAX = 10, 34
PAYMENT_DAYS_MAX = 180


class IssueSettingsError(ValueError):
    """Odmowa zapisu ustawień — komunikat dla Finansów."""


def _text(raw: Any, limit: int = TEXT_MAX) -> str:
    return " ".join(str(raw or "").split())[:limit]


def _account(raw: Any) -> dict[str, str]:
    data = raw if isinstance(raw, dict) else {}
    return {
        "number": "".join(str(data.get("number") or "").split()).upper()[:ACCOUNT_MAX],
        "bank": _text(data.get("bank")),
        "swift": _text(data.get("swift"), 11).upper(),
    }


def _days(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if 0 <= value <= PAYMENT_DAYS_MAX else default


def normalize(raw: object) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    seller = data.get("seller") if isinstance(data.get("seller"), dict) else {}
    accounts = data.get("accounts") if isinstance(data.get("accounts"), dict) else {}
    series = data.get("series") if isinstance(data.get("series"), dict) else {}
    overrides = data.get("clients") if isinstance(data.get("clients"), dict) else {}
    default_vat = str(data.get("default_vat") or DEFAULT_VAT)
    clients: dict[str, dict[str, Any]] = {}
    for key, value in overrides.items():
        if not str(key).isdigit() or not isinstance(value, dict):
            continue
        entry: dict[str, Any] = {}
        if str(value.get("vat_rate") or "") in VAT_RATES:
            entry["vat_rate"] = str(value["vat_rate"])
        if value.get("payment_days") not in (None, ""):
            entry["payment_days"] = _days(
                value.get("payment_days"), DEFAULT_PAYMENT_DAYS
            )
        # Rachunek przy kliencie (decyzja Artura 16.11.2026: Nordea płaci w EUR
        # na inny rachunek niż reszta klientów) — tylko waluty z numerem.
        raw_accounts = value.get("accounts")
        if isinstance(raw_accounts, dict):
            own = {
                currency: _account(raw_accounts.get(currency))
                for currency in CURRENCIES
            }
            own = {k: v for k, v in own.items() if v["number"]}
            if own:
                entry["accounts"] = own
        if entry:
            clients[str(int(key))] = entry
    return {
        "seller": {
            "name": _text(seller.get("name")),
            "nip": "".join(ch for ch in str(seller.get("nip") or "") if ch.isdigit())[
                :10
            ],
            "address_l1": _text(seller.get("address_l1")),
            "address_l2": _text(seller.get("address_l2")),
            "issue_place": _text(seller.get("issue_place"), 64),
        },
        "accounts": {
            currency: _account(accounts.get(currency)) for currency in CURRENCIES
        },
        "payment_days": _days(data.get("payment_days"), DEFAULT_PAYMENT_DAYS),
        "default_vat": default_vat if default_vat in VAT_RATES else DEFAULT_VAT,
        "exemption_basis": _text(data.get("exemption_basis")),
        "service_name": _text(data.get("service_name"), 120) or DEFAULT_SERVICE_NAME,
        "series": {
            code: _text(series.get(code), PATTERN_MAX) or DEFAULT_SERIES[code]
            for code in SERIES
        },
        "clients": clients,
    }


def validate(data: dict[str, Any]) -> None:
    seller = data["seller"]
    if seller["nip"] and not nip_checksum_valid(seller["nip"]):
        raise IssueSettingsError("NIP sprzedawcy ma złą sumę kontrolną.")
    accounts = [
        ("", currency, account) for currency, account in data["accounts"].items()
    ]
    for client_id, entry in data["clients"].items():
        for currency, account in (entry.get("accounts") or {}).items():
            accounts.append((f" klienta {client_id}", currency, account))
    for where, currency, account in accounts:
        number = account["number"]
        if number and not (
            ACCOUNT_MIN <= len(number) <= ACCOUNT_MAX and number.isalnum()
        ):
            raise IssueSettingsError(
                f"Numer rachunku {currency}{where} ma mieć od 10 do 34 liter i cyfr."
            )
    for code, pattern in data["series"].items():
        if any(token not in pattern for token in PATTERN_TOKENS) or not any(
            token in pattern for token in MONTH_TOKENS
        ):
            raise IssueSettingsError(
                f"Wzór serii „{SERIES_LABELS[code]}” musi zawierać {{n}}, miesiąc "
                "({m} albo {mm}) i {yyyy}."
            )
    patterns = list(data["series"].values())
    if len(set(patterns)) != len(patterns):
        raise IssueSettingsError("Każda seria musi mieć inny wzór numeru.")


def seller_missing(data: dict[str, Any]) -> list[str]:
    """Czego brakuje do wysłania faktury (puste = komplet)."""

    seller = data["seller"]
    missing = []
    if not seller["name"]:
        missing.append("nazwa sprzedawcy")
    if not seller["nip"]:
        missing.append("NIP sprzedawcy")
    if not seller["address_l1"]:
        missing.append("adres sprzedawcy")
    return missing


async def load(db: AsyncSession) -> dict[str, Any]:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return normalize(raw)


async def save(
    db: AsyncSession, raw: dict[str, Any], *, actor_id: int
) -> dict[str, Any]:
    """Zapis (bez commita); ``IssueSettingsError`` przy złych danych."""

    value = normalize(raw)
    validate(value)
    statement = insert(AppSetting).values(
        key=SETTING_KEY, value=value, updated_by=actor_id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
    return value


def client_vat(data: dict[str, Any], client_id: int, *, eu_buyer: bool) -> str:
    """Stawka dla nowej pozycji: nadpisanie przy kliencie, nabywca z UE, domyślna."""

    override = data["clients"].get(str(client_id), {}).get("vat_rate")
    if override:
        return override
    return "np II" if eu_buyer else data["default_vat"]


def account_for(
    data: dict[str, Any], client_id: Optional[int], currency: str, series_code: str
) -> Optional[dict[str, str]]:
    """Rachunek na fakturze: brak przy kompensacie, rachunek klienta, domyślny waluty."""

    if series_code in COMPENSATION_SERIES:
        return None
    own = (
        (data.get("clients") or {})
        .get(str(client_id), {})
        .get("accounts", {})
        .get(currency)
    )
    account = own or (data.get("accounts") or {}).get(currency) or {}
    return account if account.get("number") else None


def client_payment_days(data: dict[str, Any], client_id: int) -> int:
    value: Optional[int] = data["clients"].get(str(client_id), {}).get("payment_days")
    return value if value is not None else data["payment_days"]


__all__ = [
    "DEFAULT_SERIES",
    "SERIES_LABELS",
    "SETTING_KEY",
    "IssueSettingsError",
    "account_for",
    "client_payment_days",
    "client_vat",
    "load",
    "normalize",
    "save",
    "seller_missing",
    "validate",
]
