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

import logging
import re
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services.client_invoice_issue_schema import SERIES
from app.services.client_invoicing import rebate
from app.services.client_invoicing.fa3_build import VAT_RATES
from app.services.client_sales_invoices_schema import CURRENCIES
from app.services.order_client_identity import nip_checksum_valid

logger = logging.getLogger(__name__)

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
#: Nabywcy klienta (Nordea: Abp, Rahoitus, oddział w Polsce — nabywca zależy od kontraktu).
BUYERS_MAX = 10
BUYER_CODE = re.compile(r"b\d{1,3}")
BUYER_FIELDS = (
    "name",
    "number",
    "address_l1",
    "address_l2",
    "country",
    "delivery_l1",
    "delivery_l2",
    "delivery_country",
)


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


def _country(raw: Any) -> str:
    value = "".join(ch for ch in str(raw or "").upper() if ch.isalpha())[:2]
    return "EL" if value == "GR" else value


def _buyers(raw: Any, reserved: Iterable[str] = ()) -> list[dict[str, str]]:
    """Lista nabywców klienta; wpis bez nazwy odpada, nowy dostaje kod ``b<n>``.

    Nowy nabywca nie dostaje kodu zajętego w przypisaniach kontraktów
    (``reserved``): usunięcie b2 i dodanie innej spółki w jednym zapisie dałoby
    jej kontrakty b2 (przegląd 23.11.2026).
    """

    items = raw if isinstance(raw, list) else []
    out: list[dict[str, str]] = []
    used: set[str] = {str(code) for code in reserved}
    for item in items[:BUYERS_MAX]:
        if not isinstance(item, dict) or not _text(item.get("name")):
            continue
        entry = {
            "name": _text(item.get("name")),
            "number": "".join(
                ch for ch in str(item.get("number") or "").upper() if ch.isalnum()
            )[:32],
            "address_l1": _text(item.get("address_l1")),
            "address_l2": _text(item.get("address_l2")),
            "country": _country(item.get("country")) or "PL",
            "delivery_l1": _text(item.get("delivery_l1")),
            "delivery_l2": _text(item.get("delivery_l2")),
            "delivery_country": _country(item.get("delivery_country")),
        }
        code = str(item.get("code") or "")
        if BUYER_CODE.fullmatch(code) and code not in {e.get("code") for e in out}:
            entry["code"] = code
            used.add(code)
        out.append(entry)
    next_no = 1
    for entry in out:
        if "code" in entry:
            continue
        while f"b{next_no}" in used:
            next_no += 1
        entry["code"] = f"b{next_no}"
        used.add(entry["code"])
    return out


def _contract_buyers(raw: Any, codes: set[str]) -> dict[str, str]:
    data = raw if isinstance(raw, dict) else {}
    return {
        str(int(key)): str(value)
        for key, value in data.items()
        if str(key).isdigit() and str(value) in codes
    }


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
        # Rabat roczny od obrotu (decyzja Artura 16.11.2026: Nordea, progi z umowy
        # ramowej jako dane). Zapis sprawdza warunki ostro (``save``); tu, przy
        # odczycie, złe warunki odpadają z logiem, żeby nie zatrzymać wystawiania.
        try:
            terms = rebate.parse_terms(value.get("rebate"))
        except rebate.RebateTermsError:
            logger.warning(
                "client_invoice_issue: złe warunki rabatu klienta %s", int(key)
            )
            terms = None
        if terms is not None:
            entry["rebate"] = rebate.to_json(terms)
        raw_mapping = value.get("contract_buyers")
        buyers = _buyers(
            value.get("buyers"),
            raw_mapping.values() if isinstance(raw_mapping, dict) else (),
        )
        if buyers:
            entry["buyers"] = buyers
            mapping = _contract_buyers(raw_mapping, {b["code"] for b in buyers})
            if mapping:
                entry["contract_buyers"] = mapping
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


def _check_rebates(raw: dict[str, Any]) -> None:
    overrides = raw.get("clients") if isinstance(raw.get("clients"), dict) else {}
    for key, value in overrides.items():
        if not isinstance(value, dict):
            continue
        try:
            rebate.parse_terms(value.get("rebate"))
        except rebate.RebateTermsError as exc:
            raise IssueSettingsError(f"{exc} (klient {key})") from exc


def client_rebate(
    data: dict[str, Any], client_id: Optional[int]
) -> Optional[rebate.Terms]:
    """Warunki rabatu rocznego przy kliencie (``None`` = bez rabatu)."""

    if client_id is None:
        return None
    raw = data["clients"].get(str(client_id), {}).get("rebate")
    try:
        return rebate.parse_terms(raw)
    except rebate.RebateTermsError:
        return None


async def load(db: AsyncSession) -> dict[str, Any]:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return normalize(raw)


async def save(
    db: AsyncSession, raw: dict[str, Any], *, actor_id: int
) -> dict[str, Any]:
    """Zapis (bez commita); ``IssueSettingsError`` przy złych danych."""

    _check_rebates(raw)
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


def client_buyers(
    data: dict[str, Any], client_id: Optional[int]
) -> list[dict[str, str]]:
    """Nabywcy klienta z ustawień (pusta lista = nabywcą jest klient z kartoteki)."""

    if client_id is None:
        return []
    return list((data.get("clients") or {}).get(str(client_id), {}).get("buyers") or [])


def buyer_for_contract(
    data: dict[str, Any], client_id: Optional[int], contract_id: Optional[int]
) -> Optional[dict[str, str]]:
    """Nabywca przypisany do kontraktu osoby; ``None`` = nieprzypisany."""

    if client_id is None or contract_id is None:
        return None
    entry = (data.get("clients") or {}).get(str(client_id), {})
    code = (entry.get("contract_buyers") or {}).get(str(contract_id))
    return next((b for b in entry.get("buyers") or [] if b["code"] == code), None)


def remember_buyer(
    data: dict[str, Any], client_id: int, contract_ids: Iterable[int], code: str
) -> bool:
    """Przypisuje kontrakty do nabywcy (w miejscu); ``True``, gdy coś się zmieniło."""

    entry = (data.get("clients") or {}).get(str(client_id))
    if not entry or code not in {b["code"] for b in entry.get("buyers") or []}:
        return False
    mapping = entry.setdefault("contract_buyers", {})
    changed = False
    for contract_id in contract_ids:
        if mapping.get(str(contract_id)) != code:
            mapping[str(contract_id)] = code
            changed = True
    return changed


def client_payment_days(data: dict[str, Any], client_id: int) -> int:
    value: Optional[int] = data["clients"].get(str(client_id), {}).get("payment_days")
    return value if value is not None else data["payment_days"]


__all__ = [
    "DEFAULT_SERIES",
    "SERIES_LABELS",
    "SETTING_KEY",
    "IssueSettingsError",
    "account_for",
    "buyer_for_contract",
    "client_buyers",
    "client_payment_days",
    "client_rebate",
    "client_vat",
    "load",
    "normalize",
    "remember_buyer",
    "save",
    "seller_missing",
    "validate",
]
