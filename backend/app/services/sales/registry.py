"""Klient rejestrów państwowych dla kart Sprzedaży: biała lista VAT i KRS.

Decyzja Artura z 13.11.2026 (krok 6 planu botów): NIP, KRS, REGON, nazwa
prawna i miasto siedziby mają być potwierdzone u źródła. Dwa darmowe,
publiczne API bez klucza:

* Wykaz podatników VAT MF (``wl-api.mf.gov.pl``, metoda ``search``): po NIP-ie
  nazwa, REGON, KRS, adres siedziby i status VAT. Limit: 100 zapytań ``search``
  dziennie (do 30 NIP-ów w jednym), po wyczerpaniu blokada do 0:00. Ten sam
  limit zużywają Rozliczenia (``services/hr/white_list.py``), więc Sprzedaż
  bierze najwyżej ``DAILY_MF_QUERIES`` zapytań, a noc pyta paczkami po 30.
* KRS (``api-krs.ms.gov.pl``, odpis aktualny rejestru przedsiębiorców): po
  numerze KRS nazwa, NIP, REGON, miejscowość siedziby, likwidacja i upadłość.
  Brak odpisu aktualnego (204) sprawdza odpis pełny: ostatni wpis
  „WYKREŚLENIE” to firma wykreślona.

Zapis na karty, historia i harmonogram: ``services/sales/registry_cards.py``.

Odpowiedź rejestru to dane z zewnątrz: model pydantic, limity długości, NIP
z sumą kontrolną, KRS i REGON z cyfr. Moduł nie loguje treści odpowiedzi.
Reguły: ``docs/claude/sprzedaz/dane-firm-z-rejestrow.md``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Optional

import httpx
from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError

from app.services.order_client_identity import nip_checksum_valid
from app.services.sales import companies as company_service
from app.services.sales.signals import _clean

logger = logging.getLogger(__name__)

MF_BASE = "https://wl-api.mf.gov.pl"
KRS_BASE = "https://api-krs.ms.gov.pl"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
#: Próby jednego zapytania: timeout, błąd sieci i 5xx ponawiamy, 4xx nie.
ATTEMPTS = 3
BACKOFF_SECONDS = 0.5

#: Najwięcej NIP-ów w jednym zapytaniu ``search/nips`` (specyfikacja MF).
MF_BATCH = 30
#: Długości kolumn ``sales_companies``: dłuższa wartość z rejestru nie trafia na kartę.
FIELD_LIMITS = {
    "legal_name": 500,
    "nip": 15,
    "krs": 20,
    "regon": 14,
    "hq_city": 120,
    "hq_country": 2,
}

#: Stan firmy w rejestrze.
ACTIVE = "active"
REMOVED = "removed"
LIQUIDATION = "liquidation"
BANKRUPTCY = "bankruptcy"
VAT_REMOVED = "vat_removed"
NOT_FOUND = "not_found"
INVALID_NIP = "invalid_nip"
VAT_STATUS = {
    "czynny": "active",
    "zwolniony": "exempt",
    "niezarejestrowany": "unregistered",
}


class RegistryUnavailable(Exception):
    """Rejestr nie odpowiedział (timeout, sieć, 5xx) po wszystkich próbach."""


class RegistryQuotaExceeded(RegistryUnavailable):
    """MF odmówił z powodu dziennego limitu zapytań."""


# ── Walidacja odpowiedzi ─────────────────────────────────────────────────


def _text(limit: int):
    def check(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = _clean(str(value))
        return cleaned[:limit] or None

    return AfterValidator(check)


def _digits_only(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


Name = Annotated[Optional[str], _text(500)]
Address = Annotated[Optional[str], _text(300)]
Short = Annotated[Optional[str], _text(60)]
Digits = Annotated[Optional[str], AfterValidator(_digits_only)]


class _External(BaseModel):
    # Rejestr dokłada pola bez zapowiedzi: nieznane pomijamy, znane walidujemy.
    model_config = ConfigDict(extra="ignore")


class VatSubject(_External):
    name: Name = None
    nip: Digits = None
    statusVat: Short = None
    regon: Digits = None
    krs: Digits = None
    residenceAddress: Address = None
    workingAddress: Address = None
    removalDate: Short = None


class _VatEntry(_External):
    identifier: Digits = None
    subjects: Optional[list[VatSubject]] = None


class _VatEntries(_External):
    entries: Optional[list[_VatEntry]] = None
    requestId: Short = None


class VatBatchResponse(_External):
    result: _VatEntries


class _KrsIds(_External):
    nip: Digits = None
    regon: Digits = None


class _KrsSubject(_External):
    nazwa: Name = None
    identyfikatory: Optional[_KrsIds] = None


class _KrsSeat(_External):
    kraj: Short = None
    miejscowosc: Short = None


class _KrsSeatAddress(_External):
    siedziba: Optional[_KrsSeat] = None


class _KrsSection1(_External):
    danePodmiotu: Optional[_KrsSubject] = None
    siedzibaIAdres: Optional[_KrsSeatAddress] = None


class _KrsData(_External):
    dzial1: Optional[_KrsSection1] = None
    dzial6: Optional[dict[str, Any]] = None


class _KrsOdpis(_External):
    dane: Optional[_KrsData] = None


class KrsResponse(_External):
    odpis: _KrsOdpis


class _KrsEntry(_External):
    opis: Short = None
    dataWpisu: Short = None


class _KrsFullHeader(_External):
    wpis: Optional[list[_KrsEntry]] = None


class _KrsFullOdpis(_External):
    naglowekP: Optional[_KrsFullHeader] = None


class KrsFullResponse(_External):
    odpis: _KrsFullOdpis


# ── Wynik rejestru ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class VatRecord:
    name: Optional[str]
    nip: Optional[str]
    regon: Optional[str]
    krs: Optional[str]
    city: Optional[str]
    vat_status: str
    removed: bool
    url: str


@dataclass(frozen=True)
class KrsRecord:
    krs: str
    state: str
    url: str
    name: Optional[str] = None
    nip: Optional[str] = None
    regon: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    removed_on: Optional[str] = None


_POSTAL_CITY = re.compile(r"\b\d{2}-\d{3}\s+(.+)$")


def city_name(value: Optional[str]) -> Optional[str]:
    """„BIELSKO-BIAŁA” → „Bielsko-Biała”: rejestry piszą wielkimi literami."""

    if not value:
        return None
    return value.strip().title()[: FIELD_LIMITS["hq_city"]] or None


def city_from_address(address: Optional[str]) -> Optional[str]:
    """„ALEJE X 160, 02-326 WARSZAWA” → „Warszawa” (miasto po kodzie pocztowym)."""

    match = _POSTAL_CITY.search((address or "").strip())
    return city_name(match.group(1)) if match else None


def valid_nip(value: Optional[str]) -> Optional[str]:
    digits = company_service.nip_digits(value)
    return digits if digits and nip_checksum_valid(digits) else None


def valid_krs(value: Optional[str]) -> Optional[str]:
    digits = _digits_only(value)
    if not digits or len(digits) > 10 or not int(digits):
        return None
    return digits.zfill(10)


def valid_regon(value: Optional[str]) -> Optional[str]:
    """REGON 9 albo 14 cyfr; KRS pisze 9-cyfrowy jako 14 z „00000” na końcu."""

    digits = _digits_only(value)
    if not digits:
        return None
    if len(digits) == 14 and digits.endswith("00000"):
        digits = digits[:9]
    return digits if len(digits) in (9, 14) else None


def vat_url(nip: str, on_date: date) -> str:
    return f"{MF_BASE}/api/search/nip/{nip}?date={on_date.isoformat()}"


def krs_url(krs: str) -> str:
    return f"{KRS_BASE}/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json"


def parse_vat_batch(
    data: Any, nips: list[str], on_date: date
) -> dict[str, Optional[VatRecord]]:
    """Odpowiedź ``search/nips`` → wpis na NIP; ``None`` = NIP-u nie ma w wykazie."""

    try:
        parsed = VatBatchResponse.model_validate(data)
    except ValidationError as exc:
        raise RegistryUnavailable("vat: invalid response") from exc
    wanted = set(nips)
    found: dict[str, Optional[VatRecord]] = {nip: None for nip in nips}
    for entry in parsed.result.entries or []:
        if entry.identifier not in wanted:
            continue
        subjects = [s for s in entry.subjects or [] if s.nip == entry.identifier]
        if not subjects:
            continue
        # Kilka wpisów pod jednym NIP-em: najpierw czynny podatnik.
        subject = sorted(subjects, key=lambda s: s.removalDate is not None)[0]
        status = VAT_STATUS.get((subject.statusVat or "").casefold(), "unknown")
        found[entry.identifier] = VatRecord(
            name=subject.name,
            nip=entry.identifier,
            regon=valid_regon(subject.regon),
            krs=valid_krs(subject.krs),
            city=city_from_address(subject.residenceAddress or subject.workingAddress),
            vat_status=status,
            removed=subject.removalDate is not None or status == "unregistered",
            url=vat_url(entry.identifier, on_date),
        )
    return found


def parse_krs(data: Any, krs: str) -> KrsRecord:
    try:
        parsed = KrsResponse.model_validate(data)
    except ValidationError as exc:
        raise RegistryUnavailable("krs: invalid response") from exc
    section = (
        parsed.odpis.dane.dzial1 if parsed.odpis.dane else None
    ) or _KrsSection1()
    subject = section.danePodmiotu or _KrsSubject()
    ids = subject.identyfikatory or _KrsIds()
    seat = (
        section.siedzibaIAdres.siedziba if section.siedzibaIAdres else None
    ) or _KrsSeat()
    section6 = (parsed.odpis.dane.dzial6 if parsed.odpis.dane else None) or {}
    state = ACTIVE
    if section6.get("postepowanieUpadlosciowe"):
        state = BANKRUPTCY
    elif section6.get("likwidacja"):
        state = LIQUIDATION
    country = (seat.kraj or "").casefold()
    return KrsRecord(
        krs=krs,
        state=state,
        url=krs_url(krs),
        name=subject.nazwa,
        nip=valid_nip(ids.nip),
        regon=valid_regon(ids.regon),
        city=city_name(seat.miejscowosc),
        country="PL" if country == "polska" else None,
    )


def parse_krs_full(data: Any, krs: str) -> KrsRecord:
    """Odpis pełny firmy bez odpisu aktualnego: wykreślona albo nieznana."""

    try:
        parsed = KrsFullResponse.model_validate(data)
    except ValidationError as exc:
        raise RegistryUnavailable("krs: invalid response") from exc
    entries = (parsed.odpis.naglowekP.wpis if parsed.odpis.naglowekP else None) or []
    last = entries[-1] if entries else None
    if last and "WYKREŚLENIE" in (last.opis or "").upper():
        return KrsRecord(
            krs=krs, state=REMOVED, url=krs_url(krs), removed_on=last.dataWpisu
        )
    return KrsRecord(krs=krs, state=NOT_FOUND, url=krs_url(krs))


# ── Klient HTTP ──────────────────────────────────────────────────────────


async def _get(
    client: httpx.AsyncClient, url: str, params: dict[str, str]
) -> httpx.Response:
    """GET z ponowieniem: timeout, sieć i 5xx; 4xx wraca do wywołującego."""

    for attempt in range(ATTEMPTS):
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError:
            response = None
        if response is not None and response.status_code < 500:
            return response
        if attempt < ATTEMPTS - 1:
            await asyncio.sleep(BACKOFF_SECONDS * (attempt + 1))
    raise RegistryUnavailable("no answer")


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise RegistryUnavailable("invalid json") from exc


async def fetch_vat(
    client: httpx.AsyncClient, nips: list[str], on_date: date
) -> dict[str, Optional[VatRecord]]:
    """Jedno zapytanie ``search/nips`` (do 30 NIP-ów) = jedno zapytanie z limitu."""

    if not nips or len(nips) > MF_BATCH:
        raise ValueError("1–30 NIP-ów na zapytanie")
    response = await _get(
        client,
        f"{MF_BASE}/api/search/nips/{','.join(nips)}",
        {"date": on_date.isoformat()},
    )
    if response.status_code == 429:
        raise RegistryQuotaExceeded("vat quota")
    if response.status_code != 200:
        body = _json(response) if response.content else {}
        message = str((body or {}).get("message") or "").casefold()
        if "limit" in message:
            raise RegistryQuotaExceeded("vat quota")
        raise RegistryUnavailable(f"vat http {response.status_code}")
    return parse_vat_batch(_json(response), nips, on_date)


async def fetch_krs(client: httpx.AsyncClient, krs: str) -> KrsRecord:
    params = {"rejestr": "P", "format": "json"}
    response = await _get(client, f"{KRS_BASE}/api/krs/OdpisAktualny/{krs}", params)
    if response.status_code == 200:
        return parse_krs(_json(response), krs)
    if response.status_code not in (204, 404):
        raise RegistryUnavailable(f"krs http {response.status_code}")
    full = await _get(client, f"{KRS_BASE}/api/krs/OdpisPelny/{krs}", params)
    if full.status_code == 200:
        return parse_krs_full(_json(full), krs)
    if full.status_code in (204, 404):
        return KrsRecord(krs=krs, state=NOT_FOUND, url=krs_url(krs))
    raise RegistryUnavailable(f"krs http {full.status_code}")


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"Accept": "application/json", "User-Agent": "NEXUS-sales-registry"},
    )
