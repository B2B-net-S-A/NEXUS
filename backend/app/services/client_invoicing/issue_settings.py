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
#: Kod adresu faktury w portalu CPro Nordei (``F206`` = Abp Finland). Mail CPro
#: „Invoice address was updated” podaje ten kod — tak NEXUS znajduje nabywcę z listy.
CPRO_CODE = re.compile(r"[A-Z]\d{2,5}")
BUYER_FIELDS = (
    "name",
    "number",
    "address_l1",
    "address_l2",
    "country",
    "delivery_l1",
    "delivery_l2",
    "delivery_country",
    "cpro_code",
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


def _cpro_code(raw: Any) -> str:
    value = "".join(str(raw or "").split()).upper()
    return value if CPRO_CODE.fullmatch(value) else ""


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
            "cpro_code": _cpro_code(item.get("cpro_code")),
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


#: Przypisanie zapisane przed „od miesiąca” (PR #3817) obowiązuje od początku.
SINCE_ALWAYS = "2000-01"
MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def _history(raw: Any) -> list[dict[str, str]]:
    """Historia nabywcy kontraktu: ``[{"code", "from": "RRRR-MM"}]`` rosnąco po miesiącu.

    Nabywca kontraktu się zmienia (Nordea: zmiana w portalu CPro od dnia, np.
    z Abp S.A. na Abp Finland od 15.09.2026), więc przypisanie ma miesiąc
    początku; wcześniejsze miesiące zostają przy poprzednim nabywcy.
    """

    items = [{"code": raw, "from": SINCE_ALWAYS}] if isinstance(raw, str) else raw
    by_month: dict[str, str] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        code, since = str(item.get("code") or ""), str(item.get("from") or "")
        if BUYER_CODE.fullmatch(code) and MONTH.fullmatch(since):
            by_month[since] = code
    out: list[dict[str, str]] = []
    for month in sorted(by_month):
        # Ten sam nabywca co miesiąc wcześniej to nie zmiana — jeden wpis.
        if not out or out[-1]["code"] != by_month[month]:
            out.append({"code": by_month[month], "from": month})
    return out


def _mapping_codes(raw: Any) -> set[str]:
    data = raw if isinstance(raw, dict) else {}
    return {item["code"] for value in data.values() for item in _history(value)}


def _contract_buyers(raw: Any, codes: set[str]) -> dict[str, list[dict[str, str]]]:
    data = raw if isinstance(raw, dict) else {}
    out = {}
    for key, value in data.items():
        if not str(key).isdigit():
            continue
        history = [item for item in _history(value) if item["code"] in codes]
        if history:
            out[str(int(key))] = history
    return out


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
            _mapping_codes(raw_mapping),
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
    for client_id, entry in data["clients"].items():
        seen: set[str] = set()
        for buyer in entry.get("buyers") or []:
            code = buyer.get("cpro_code") or ""
            if code and code in seen:
                raise IssueSettingsError(
                    f"Kod CPro {code} ma dwóch nabywców klienta {client_id}."
                )
            seen.add(code)
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


async def load(db: AsyncSession, *, lock: bool = False) -> dict[str, Any]:
    """Ustawienia; ``lock=True`` blokuje wiersz do końca transakcji (zapis po odczycie)."""

    query = select(AppSetting.value).where(AppSetting.key == SETTING_KEY)
    raw = await db.scalar(query.with_for_update() if lock else query)
    return normalize(raw)


async def save(
    db: AsyncSession, raw: dict[str, Any], *, actor_id: Optional[int]
) -> dict[str, Any]:
    """Zapis (bez commita); ``IssueSettingsError`` przy złych danych.

    ``actor_id=None`` = automat (nabywca z maila CPro, ``cpro_invoice_buyer``).
    """

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


#: Stawki krajowe: nie trafiają na fakturę do nabywcy z UE (usługa B2B w UE =
#: odwrotne obciążenie, „np II”). Ekran ustawień przy dodaniu klienta zapisuje
#: mu stawkę domyślną (23), więc bez tego drugi nabywca klienta z UE (Bosch
#: GmbH obok spółki polskiej, 28.11.2026) dostałby 23% zamiast „np II”.
DOMESTIC_VAT = frozenset({"23", "8", "5", "0 KR"})


def client_vat(data: dict[str, Any], client_id: int, *, eu_buyer: bool) -> str:
    """Stawka dla nowej pozycji: nadpisanie przy kliencie, nabywca z UE, domyślna.

    Nadpisanie krajowe nie dotyczy nabywcy z UE, a „np II” nabywcy krajowego."""

    override = data["clients"].get(str(client_id), {}).get("vat_rate")
    if eu_buyer:
        return override if override and override not in DOMESTIC_VAT else "np II"
    if override and override != "np II":
        return override
    return data["default_vat"]


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


def _code_in(history: list[dict[str, str]], period: str) -> Optional[str]:
    code = None
    for item in history:
        if item["from"] <= period:
            code = item["code"]
    return code


def buyer_by_cpro_code(
    data: dict[str, Any], client_id: Optional[int], cpro_code: Optional[str]
) -> Optional[dict[str, str]]:
    """Nabywca klienta z kodem adresu CPro (``F206``); ``None`` = żaden go nie ma."""

    code = _cpro_code(cpro_code)
    if not code:
        return None
    return next(
        (b for b in client_buyers(data, client_id) if b.get("cpro_code") == code),
        None,
    )


def buyer_for_contract(
    data: dict[str, Any],
    client_id: Optional[int],
    contract_id: Optional[int],
    period: str,
) -> Optional[dict[str, str]]:
    """Nabywca kontraktu osoby w miesiącu usługi (``RRRR-MM``); ``None`` = nieprzypisany."""

    if client_id is None or contract_id is None:
        return None
    entry = (data.get("clients") or {}).get(str(client_id), {})
    history = _history((entry.get("contract_buyers") or {}).get(str(contract_id)))
    code = _code_in(history, period)
    return next((b for b in entry.get("buyers") or [] if b["code"] == code), None)


def remember_buyer(
    data: dict[str, Any],
    client_id: int,
    contract_ids: Iterable[int],
    code: str,
    period: str,
) -> bool:
    """Kontrakty przy nabywcy od miesiąca ``period`` (w miejscu); ``True`` = zmiana.

    Późniejsze zmiany nabywcy zostają: poprawka sierpnia nie rusza września.
    """

    entry = (data.get("clients") or {}).get(str(client_id))
    if not entry or code not in {b["code"] for b in entry.get("buyers") or []}:
        return False
    if not MONTH.fullmatch(period):
        return False
    mapping = entry.setdefault("contract_buyers", {})
    changed = False
    for contract_id in contract_ids:
        history = _history(mapping.get(str(contract_id)))
        if _code_in(history, period) == code:
            continue
        history = [item for item in history if item["from"] != period]
        history.append({"code": code, "from": period})
        mapping[str(contract_id)] = _history(history)
        changed = True
    return changed


def keep_stored_mapping(raw: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    """Zapis z ekranu ustawień z przypisaniami kontraktów z bazy, nie z formularza.

    Ekran nie edytuje ``contract_buyers`` (zapisuje je wybór nabywcy w szkicu i mail
    CPro), a odsyła stan z chwili otwarcia. Bez tego karta otwarta przed mailem CPro
    skasowałaby przy zapisie wpis „od miesiąca” dopisany przez automat. Klient bez
    nabywców traci przypisania jak dotąd (``normalize``).
    """

    clients = raw.get("clients") if isinstance(raw.get("clients"), dict) else {}
    merged: dict[str, Any] = {}
    for key, value in clients.items():
        if not isinstance(value, dict):
            merged[key] = value
            continue
        entry = {k: v for k, v in value.items() if k != "contract_buyers"}
        mapping = (stored.get("clients") or {}).get(str(key), {}).get("contract_buyers")
        if mapping:
            entry["contract_buyers"] = mapping
        merged[key] = entry
    return {**raw, "clients": merged}


def client_payment_days(data: dict[str, Any], client_id: int) -> int:
    value: Optional[int] = data["clients"].get(str(client_id), {}).get("payment_days")
    return value if value is not None else data["payment_days"]


def client_payment_days_override(data: dict[str, Any], client_id: int) -> Optional[int]:
    """Termin ustawiony przy kliencie; ``None`` = brak nadpisania."""

    value: Optional[int] = data["clients"].get(str(client_id), {}).get("payment_days")
    return value


__all__ = [
    "DEFAULT_SERIES",
    "SERIES_LABELS",
    "SETTING_KEY",
    "IssueSettingsError",
    "account_for",
    "buyer_by_cpro_code",
    "buyer_for_contract",
    "client_buyers",
    "client_payment_days",
    "client_payment_days_override",
    "client_rebate",
    "client_vat",
    "keep_stored_mapping",
    "load",
    "normalize",
    "remember_buyer",
    "save",
    "seller_missing",
    "validate",
]
