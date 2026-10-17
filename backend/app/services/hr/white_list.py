"""Biała lista VAT — wykaz podatników MF (``wl-api.mf.gov.pl``), R6/R7/R9.

Dwie funkcje dla Rozliczeń zespołu:

* ``search(db, nip, on_date)`` — wpis z wykazu na dzień: nazwa, status VAT,
  rachunki i identyfikator zapytania (``requestId``). „Pobierz z białej listy”
  w danych do rozliczeń osoby; ``None`` = NIP-u nie ma w wykazie,
* ``check(db, nip, account, on_date)`` — czy rachunek jest przypisany do NIP-u
  w wykazie tego dnia, z identyfikatorem zapytania jako dowodem (sprawdzenie
  rachunku przed paczką przelewów).

Tryby (``WHITE_LIST_MODE``): ``off`` — bez zapytań, każde wywołanie kończy
się ``WhiteListError("disabled")`` (awaria nie może wyglądać jak „brak
w wykazie”); ``simulate`` — fikcyjny wpis liczony z NIP-u (lokalne
przeklikanie, bez sieci); ``test`` — ``wl-test.mf.gov.pl``; ``live`` —
``wl-api.mf.gov.pl``.

Wykaz ma dzienny limit zapytań (100), więc wynik pamiętamy do końca dnia
w kalendarzu firmy: ten sam NIP (i rachunek) tego dnia nie idzie do MF drugi
raz, a ponowione wywołanie oddaje ten sam ``request_id``. Pamięć jest w procesie
(API to jeden proces uvicorna); restart ją czyści, ślad zostaje w bazie.

Każde wywołanie dopisuje do sesji wywołującego wpis śladu
(``hr_audit_events``: ``white_list_search`` / ``white_list_check``) z NIP-em,
dniem, wynikiem i ``request_id`` — bez commita, wchodzi razem z pracą
wywołującego. Pełnego rachunku nie ma w logach, w śladzie ani w komunikatach
błędów: tylko cztery ostatnie cyfry.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, business_today, local_now
from app.services.hr import audit
from app.services.order_client_identity import nip_checksum_valid

logger = logging.getLogger(__name__)

MODES = ("off", "simulate", "test", "live")
BASE_URLS = {"test": "https://wl-test.mf.gov.pl", "live": "https://wl-api.mf.gov.pl"}
TIMEOUT = httpx.Timeout(10.0)
#: Dzienne limity zapytań (zachowawczo 100 dla obu metod — tyle podaje
#: specyfikacja Rozliczeń; licznik zeruje się o północy w Warszawie).
DAILY_LIMITS = {"search": 100, "check": 100}
#: Więcej różnych zapytań dziennie się nie zdarza; limit chroni pamięć procesu.
MEMORY_MAX = 2000

#: Status VAT z wykazu → wartości ``VAT_STATUSES`` schematu rozliczeń.
VAT_STATUS_FROM_REGISTRY = {
    "czynny": "active",
    "zwolniony": "exempt",
    "niezarejestrowany": "unregistered",
}

_ACCOUNT_SEPARATORS = re.compile(r"[\s  -]")
_REGISTRY_ZONE = ZoneInfo(DEFAULT_TZ)

ERROR_MESSAGES = {
    "disabled": "Sprawdzanie na białej liście VAT jest wyłączone.",
    "invalid_nip": "NIP musi mieć 10 cyfr i poprawną sumę kontrolną.",
    "invalid_account": (
        "Numer rachunku musi mieć 26 cyfr (albo PL i 26 cyfr) "
        "i poprawną sumę kontrolną."
    ),
    "invalid_date": "Białą listę można sprawdzić na dziś albo na dzień z przeszłości.",
    "quota_exceeded": (
        "Dzienny limit zapytań do białej listy VAT jest wyczerpany. "
        "Spróbuj jutro albo wpisz dane ręcznie."
    ),
    "unavailable": "Wykaz podatników VAT nie odpowiada. Spróbuj za chwilę.",
    "rejected": "Wykaz podatników VAT odrzucił zapytanie.",
}
#: Kod HTTP dla tras, które przekazują błąd dalej.
ERROR_HTTP_STATUS = {
    "disabled": 409,
    "invalid_nip": 422,
    "invalid_account": 422,
    "invalid_date": 422,
    "quota_exceeded": 429,
    "unavailable": 503,
    "rejected": 502,
}


class WhiteListError(Exception):
    """Nie mamy odpowiedzi wykazu. ``message`` — zdanie dla UI, bez rachunku."""

    def __init__(
        self,
        code: str,
        *,
        status: Optional[int] = None,
        registry_code: Optional[str] = None,
    ) -> None:
        self.code = code
        self.status = status
        self.registry_code = registry_code
        super().__init__(self.label)

    @property
    def message(self) -> str:
        text = ERROR_MESSAGES.get(self.code, ERROR_MESSAGES["unavailable"])
        if self.code == "rejected" and self.registry_code:
            return f"{text[:-1]} ({self.registry_code})."
        return text

    @property
    def http_status(self) -> int:
        return ERROR_HTTP_STATUS.get(self.code, 503)

    @property
    def label(self) -> str:
        detail = self.registry_code or self.status
        return f"{self.code} ({detail})" if detail else self.code


@dataclass(frozen=True)
class WhiteListEntry:
    """Wpis z wykazu na dzień ``on_date``."""

    nip: str
    name: Optional[str]
    #: ``active`` / ``exempt`` / ``unregistered`` albo ``None`` (nieznany status).
    vat_status: Optional[str]
    #: Rachunki z wykazu — 26 cyfr (NRB), w kolejności z wykazu.
    accounts: tuple[str, ...]
    has_virtual_accounts: bool
    request_id: str
    requested_at: Optional[datetime]
    on_date: date
    #: ``True`` = wynik z pamięci dnia (bez nowego zapytania do MF).
    cached: bool = False

    def lists_account(self, account: str) -> bool:
        return normalize_account(account) in self.accounts


@dataclass(frozen=True)
class WhiteListCheck:
    """Wynik sprawdzenia rachunku — dowód do paczki przelewów."""

    nip: str
    account_last4: str
    listed: bool
    request_id: str
    requested_at: Optional[datetime]
    on_date: date
    cached: bool = False


# ── Numery ───────────────────────────────────────────────────────────────────


def clean_nip(raw: str) -> str:
    """10 cyfr z poprawną sumą kontrolną (spacje i myślniki pomijane)."""

    digits = re.sub(r"[\s-]", "", str(raw or ""))
    if digits.upper().startswith("PL"):
        digits = digits[2:]
    if not nip_checksum_valid(digits):
        raise WhiteListError("invalid_nip")
    return digits


def _nrb_checksum_valid(digits: str) -> bool:
    # IBAN PL: BBAN + „PL” jako 2521 + cyfry kontrolne; reszta z dzielenia przez 97 = 1.
    return int(f"{digits[2:]}2521{digits[:2]}") % 97 == 1


def normalize_account(raw: str) -> str:
    """Rachunek jako 26 cyfr (NRB); ``PL``, spacje i myślniki pomijane.

    Zła długość albo suma kontrolna = ``WhiteListError("invalid_account")``
    (bez numeru w komunikacie).
    """

    text = _ACCOUNT_SEPARATORS.sub("", str(raw or "")).upper()
    if text.startswith("PL"):
        text = text[2:]
    if len(text) != 26 or not text.isdigit() or not _nrb_checksum_valid(text):
        raise WhiteListError("invalid_account")
    return text


def account_valid(raw: str) -> bool:
    try:
        normalize_account(raw)
    except WhiteListError:
        return False
    return True


def last4(account: str) -> str:
    return normalize_account(account)[-4:]


def current_mode() -> str:
    mode = str(getattr(settings, "WHITE_LIST_MODE", "off") or "off").strip().lower()
    return mode if mode in MODES else "off"


# ── Pamięć dnia ──────────────────────────────────────────────────────────────


@dataclass
class _DayMemory:
    day: date
    results: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    used: dict[str, int] = field(default_factory=lambda: {"search": 0, "check": 0})


_memory: Optional[_DayMemory] = None


def _today_memory() -> _DayMemory:
    global _memory
    today = business_today()
    if _memory is None or _memory.day != today:
        _memory = _DayMemory(day=today)
    return _memory


def reset_memory() -> None:
    """Czyści pamięć dnia i liczniki (testy, zmiana trybu)."""

    global _memory
    _memory = None


def usage() -> dict[str, Any]:
    """Zużycie limitu dziś — dla karty stanu, bez danych zapytań."""

    memory = _today_memory()
    return {
        "day": memory.day.isoformat(),
        "used": dict(memory.used),
        "limits": dict(DAILY_LIMITS),
    }


def _consume(memory: _DayMemory, method: str) -> None:
    if memory.used[method] >= DAILY_LIMITS[method]:
        raise WhiteListError("quota_exceeded")
    memory.used[method] += 1


def _remember(memory: _DayMemory, key: tuple[Any, ...], value: Any) -> None:
    if len(memory.results) >= MEMORY_MAX:
        memory.results.clear()
    memory.results[key] = value


def _account_key(account: str) -> str:
    # Klucz pamięci bez numeru rachunku wprost.
    return hashlib.sha256(account.encode("ascii")).hexdigest()


# ── Zapytania ────────────────────────────────────────────────────────────────


def _http_client(base_url: str) -> httpx.AsyncClient:
    """Klient wykazu; testy podmieniają go na fałszywy serwer (bez sieci)."""

    return httpx.AsyncClient(
        base_url=base_url, timeout=TIMEOUT, headers={"Accept": "application/json"}
    )


def _requested_at(raw: Any) -> Optional[datetime]:
    # Wykaz podaje czas zapytania po polsku: „19-11-2019 14:58:49”.
    if not isinstance(raw, str):
        return None
    try:
        moment = datetime.strptime(raw.strip(), "%d-%m-%Y %H:%M:%S")
    except ValueError:
        return None
    return moment.replace(tzinfo=_REGISTRY_ZONE)


async def _registry_result(mode: str, path: str, on_date: date) -> dict[str, Any]:
    """``result`` z odpowiedzi wykazu. Ścieżka może nieść rachunek — nie logujemy jej."""

    try:
        async with _http_client(BASE_URLS[mode]) as client:
            response = await client.get(path, params={"date": on_date.isoformat()})
    except httpx.HTTPError as exc:
        logger.warning("white_list: brak odpowiedzi wykazu (%s)", type(exc).__name__)
        raise WhiteListError("unavailable") from None
    status = response.status_code
    if status == 429:
        raise WhiteListError("quota_exceeded", status=status)
    if status >= 500:
        logger.warning("white_list: wykaz odpowiedział %s", status)
        raise WhiteListError("unavailable", status=status)
    try:
        payload = response.json()
    except ValueError:
        logger.warning("white_list: odpowiedź wykazu nie jest JSON-em (%s)", status)
        raise WhiteListError("unavailable", status=status) from None
    if status != 200:
        registry_code = str((payload or {}).get("code") or "")[:16] or None
        message = str((payload or {}).get("message") or "").lower()
        logger.info("white_list: wykaz odrzucił zapytanie %s %s", status, registry_code)
        if "limit" in message:
            raise WhiteListError("quota_exceeded", status=status)
        raise WhiteListError("rejected", status=status, registry_code=registry_code)
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or not result.get("requestId"):
        raise WhiteListError("unavailable", status=status)
    return result


def _entry_from_subject(
    subject: dict[str, Any], request_id: str, requested_at, on_date: date
) -> WhiteListEntry:
    accounts: list[str] = []
    for raw in subject.get("accountNumbers") or []:
        try:
            account = normalize_account(raw)
        except WhiteListError:
            continue
        if account not in accounts:
            accounts.append(account)
    status = str(subject.get("statusVat") or "").strip().lower()
    name = " ".join(str(subject.get("name") or "").split())[:255] or None
    return WhiteListEntry(
        nip=str(subject.get("nip") or ""),
        name=name,
        vat_status=VAT_STATUS_FROM_REGISTRY.get(status),
        accounts=tuple(accounts),
        has_virtual_accounts=bool(subject.get("hasVirtualAccounts")),
        request_id=str(request_id)[:64],
        requested_at=requested_at,
        on_date=on_date,
    )


async def _search_registry(
    mode: str, nip: str, on_date: date
) -> tuple[Optional[WhiteListEntry], str]:
    result = await _registry_result(mode, f"/api/search/nip/{nip}", on_date)
    request_id = str(result["requestId"])[:64]
    subject = result.get("subject")
    if not isinstance(subject, dict):
        return None, request_id
    entry = _entry_from_subject(
        subject, request_id, _requested_at(result.get("requestDateTime")), on_date
    )
    # Wykaz zwraca podmiot po NIP-ie; inny NIP w odpowiedzi = nie ufamy wpisowi.
    if entry.nip != nip:
        raise WhiteListError("unavailable")
    return entry, request_id


async def _check_registry(
    mode: str, nip: str, account: str, on_date: date
) -> WhiteListCheck:
    result = await _registry_result(
        mode, f"/api/check/nip/{nip}/bank-account/{account}", on_date
    )
    assigned = str(result.get("accountAssigned") or "").strip().upper()
    if assigned not in {"TAK", "NIE"}:
        raise WhiteListError("unavailable")
    return WhiteListCheck(
        nip=nip,
        account_last4=account[-4:],
        listed=assigned == "TAK",
        request_id=str(result["requestId"])[:64],
        requested_at=_requested_at(result.get("requestDateTime")),
        on_date=on_date,
    )


# ── Tryb symulacji (fikcyjne dane, bez sieci) ───────────────────────────────


def simulated_accounts(nip: str) -> tuple[str, ...]:
    """Dwa fikcyjne rachunki z poprawną sumą kontrolną, stałe dla NIP-u."""

    accounts = []
    for index in (1, 2):
        bban = f"10900000{nip}{index:06d}"
        check = 98 - int(f"{bban}252100") % 97
        accounts.append(f"{check:02d}{bban}")
    return tuple(accounts)


def _simulated_request_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"sim-{digest[:12]}"


def _simulated_entry(nip: str, on_date: date) -> WhiteListEntry:
    return WhiteListEntry(
        nip=nip,
        name=f"Działalność Przykładowa {nip[-4:]}",
        vat_status="active",
        accounts=simulated_accounts(nip),
        has_virtual_accounts=False,
        request_id=_simulated_request_id("search", nip, on_date.isoformat()),
        requested_at=local_now(),
        on_date=on_date,
    )


def _simulated_check(nip: str, account: str, on_date: date) -> WhiteListCheck:
    return WhiteListCheck(
        nip=nip,
        account_last4=account[-4:],
        listed=account in simulated_accounts(nip),
        request_id=_simulated_request_id(
            "check", nip, _account_key(account), on_date.isoformat()
        ),
        requested_at=local_now(),
        on_date=on_date,
    )


# ── Interfejs dla Rozliczeń ──────────────────────────────────────────────────


def _prepared(on_date: date) -> str:
    if on_date > business_today():
        raise WhiteListError("invalid_date")
    mode = current_mode()
    if mode == "off":
        raise WhiteListError("disabled")
    return mode


async def search(
    db: AsyncSession,
    nip: str,
    on_date: date,
    *,
    actor_id: Optional[int] = None,
    subject_user_id: Optional[int] = None,
) -> Optional[WhiteListEntry]:
    """Wpis z wykazu na dzień; ``None`` = NIP-u nie ma w wykazie.

    Błędy (wyłączony tryb, zły NIP, limit, awaria MF) = ``WhiteListError``.
    """

    clean = clean_nip(nip)
    mode = _prepared(on_date)
    memory = _today_memory()
    key = ("search", mode, clean, on_date)
    cached = key in memory.results
    if cached:
        entry, request_id = memory.results[key]
    else:
        _consume(memory, "search")
        if mode == "simulate":
            entry = _simulated_entry(clean, on_date)
            request_id = entry.request_id
        else:
            entry, request_id = await _search_registry(mode, clean, on_date)
        _remember(memory, key, (entry, request_id))
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=subject_user_id,
        entity_type="white_list",
        entity_id=clean,
        action="white_list_search",
        details={
            "on_date": on_date.isoformat(),
            "found": entry is not None,
            "vat_status": entry.vat_status if entry else None,
            "accounts": len(entry.accounts) if entry else 0,
            "request_id": request_id,
            "cached": cached,
            "mode": mode,
        },
    )
    if entry is None:
        return None
    return replace(entry, cached=cached)


async def check(
    db: AsyncSession,
    nip: str,
    account: str,
    on_date: date,
    *,
    actor_id: Optional[int] = None,
    subject_user_id: Optional[int] = None,
) -> WhiteListCheck:
    """Czy rachunek jest w wykazie dla NIP-u w dniu ``on_date``.

    ``listed=False`` to odpowiedź wykazu („NIE”); brak odpowiedzi to
    ``WhiteListError`` — paczka przelewów traktuje go jak niesprawdzony rachunek.
    """

    clean = clean_nip(nip)
    clean_account = normalize_account(account)
    mode = _prepared(on_date)
    memory = _today_memory()
    key = ("check", mode, clean, _account_key(clean_account), on_date)
    cached = key in memory.results
    if cached:
        result = memory.results[key]
    else:
        _consume(memory, "check")
        if mode == "simulate":
            result = _simulated_check(clean, clean_account, on_date)
        else:
            result = await _check_registry(mode, clean, clean_account, on_date)
        _remember(memory, key, result)
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=subject_user_id,
        entity_type="white_list",
        entity_id=clean,
        action="white_list_check",
        details={
            "on_date": on_date.isoformat(),
            "listed": result.listed,
            "account_last4": result.account_last4,
            "request_id": result.request_id,
            "cached": cached,
            "mode": mode,
        },
    )
    return replace(result, cached=cached)


__all__ = [
    "WhiteListCheck",
    "WhiteListEntry",
    "WhiteListError",
    "account_valid",
    "check",
    "clean_nip",
    "current_mode",
    "last4",
    "normalize_account",
    "reset_memory",
    "search",
    "simulated_accounts",
    "usage",
]
