"""Sprawdzenie firmy Partnera w rejestrze w chwili generowania umowy B2B.

Ticket 6 (28.09.2026): dane firmy w umowie bywały nieaktualne — formularz
wypełniał się z profilu kandydata, z zapisanej umowy albo z lookupu zrobionego
dni wcześniej. Przed każdym „Pobierz DOCX" generator pyta rejestr jeszcze raz:

  - JDG → CEIDG API v3 po NIP (``settings.CEIDG_API_TOKEN``),
  - spółka → KRS OpenAPI (odpis aktualny) po numerze KRS; numer podaje
    wołający albo ustalamy go z Białej Listy MF po NIP.

Wynik jest WYŁĄCZNIE informacją: ostrzeżenia (działalność zawieszona albo
wykreślona w CEIDG; likwidacja, upadłość albo wykreślenie w KRS) nie blokują
generowania, a niedostępny rejestr daje status ``unverified`` z powodem po
polsku — nigdy wyjątek i nigdy „wszystko w porządku".

Co mówią rejestry (sprawdzone na żywych danych 28.09.2026):

  - CEIDG: ``firmy[].status`` ∈ AKTYWNY, ZAWIESZONY, WYKRESLONY,
    OCZEKUJE_NA_ROZPOCZECIE_DZIALANOSCI, WYLACZNIE_W_FORMIE_SPOLKI; brak
    firmy = HTTP 204. Daty zawieszenia/wykreślenia są tylko w szczegółach
    wpisu (``/firma/{id}``).
  - KRS: likwidacja i upadłość siedzą w dziale 6 (``likwidacja``,
    ``postepowanieUpadlosciowe``), a nazwa dostaje dopisek „W LIKWIDACJI" /
    „W UPADŁOŚCI". Spółka wykreślona NIE ma odpisu aktualnego (HTTP 204) —
    wykreślenie widać dopiero w odpisie pełnym jako ostatni wpis
    „WYKREŚLENIE Z KRAJOWEGO REJESTRU SĄDOWEGO". ``stanPozycji`` NIE mówi
    o wykreśleniu (3, 4, 5 mają też podmioty aktywne).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.services.b2b_contract_generator.entity_type import COMPANY, SOLE_TRADER
from app.services.b2b_contract_generator.registry_lookup import (
    _CEIDG_BASE,
    _KRS_BASE,
    _TIMEOUT,
    _ceidg_address,
    _digits,
    _parse_krs,
    lookup_by_biznes,
    lookup_by_nip,
    pick_current_ceidg_firm,
)

logger = logging.getLogger(__name__)

VERIFIED = "verified"
UNVERIFIED = "unverified"

REGISTRY_CEIDG = "ceidg"
REGISTRY_KRS = "krs"

WARN_CEIDG_SUSPENDED = "ceidg_suspended"
WARN_CEIDG_DELETED = "ceidg_deleted"
WARN_KRS_LIQUIDATION = "krs_liquidation"
WARN_KRS_BANKRUPTCY = "krs_bankruptcy"
WARN_KRS_DELETED = "krs_deleted"

# Sufit całego sprawdzenia: użytkownik czeka na nie po kliknięciu „Pobierz
# DOCX”, a pojedyncze zapytania mają własny limit 10 s (CEIDG + szczegóły
# wpisu + dwa odpisy KRS mogłyby razem przekroczyć minutę).
_TOTAL_TIMEOUT_SECONDS = 30.0

_CEIDG_ID = re.compile(r"^[0-9A-Fa-f-]{32,36}$")


# ── Czyste reguły (bez sieci) ────────────────────────────────────────────────


def _has_content(value: Any) -> bool:
    """Czy wpis działu 6 niesie jakąkolwiek treść (a nie same puste obiekty)."""
    if isinstance(value, dict):
        return any(_has_content(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_content(v) for v in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None and value is not False


def _pl_date(value: Any) -> str | None:
    """„2026-09-24" albo „24.09.2026" → „24.09.2026"; reszta → None."""
    text = str(value or "").strip()[:10]
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
        return text
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return None


def _since(date_pl: str | None) -> str:
    return f" (od {date_pl})" if date_pl else ""


def ceidg_warnings(firm: dict, detail: dict | None = None) -> list[dict]:
    """Ostrzeżenia dla wybranego wpisu CEIDG. Daty bierzemy ze szczegółów."""
    status = str(firm.get("status") or "").upper()
    detail = detail or {}
    if status == "ZAWIESZONY":
        when = _pl_date(detail.get("dataZawieszenia"))
        return [
            {
                "code": WARN_CEIDG_SUSPENDED,
                "message": (
                    "Działalność gospodarcza Partnera jest ZAWIESZONA w CEIDG"
                    f"{_since(when)}."
                ),
            }
        ]
    if status == "WYKRESLONY":
        when = _pl_date(detail.get("dataWykreslenia"))
        return [
            {
                "code": WARN_CEIDG_DELETED,
                "message": (
                    "Działalność gospodarcza Partnera jest WYKREŚLONA z CEIDG"
                    f"{_since(when)}."
                ),
            }
        ]
    return []


def krs_warnings(odpis: dict) -> list[dict]:
    """Ostrzeżenia z odpisu aktualnego KRS: likwidacja i upadłość."""
    dane = odpis.get("dane") or {}
    name = str(
        ((dane.get("dzial1") or {}).get("danePodmiotu") or {}).get("nazwa") or ""
    ).upper()
    dzial6 = dane.get("dzial6") or {}
    warnings: list[dict] = []

    if _has_content(dzial6.get("likwidacja")) or "W LIKWIDACJI" in name:
        warnings.append(
            {
                "code": WARN_KRS_LIQUIDATION,
                "message": "W KRS jest wpis o likwidacji spółki (spółka w likwidacji).",
            }
        )

    bankruptcy = dzial6.get("postepowanieUpadlosciowe")
    if _has_content(bankruptcy) or "W UPADŁOŚCI" in name:
        entries = bankruptcy if isinstance(bankruptcy, list) else [bankruptcy or {}]
        first = next((e for e in entries if isinstance(e, dict)), {})
        declared = _pl_date(
            (first.get("informacjaOOgloszeniuUpadlosci") or {}).get("data")
        )
        ended = _has_content(first.get("opisZakonczeniaProcesuUpadlosci"))
        details = ", ".join(
            part
            for part in (
                f"ogłoszona {declared}" if declared else None,
                "postępowanie zakończone" if ended else None,
            )
            if part
        )
        warnings.append(
            {
                "code": WARN_KRS_BANKRUPTCY,
                "message": (
                    "W KRS jest wpis o upadłości spółki"
                    + (f" ({details})" if details else "")
                    + "."
                ),
            }
        )
    return warnings


def krs_deletion_date(odpis_pelny: dict) -> tuple[bool, str | None]:
    """Czy ostatni wpis odpisu pełnego to wykreślenie z KRS — i kiedy."""
    header = odpis_pelny.get("naglowekP") or {}
    entries = [w for w in (header.get("wpis") or []) if isinstance(w, dict)]
    if not entries:
        return False, None
    last = entries[-1]
    if "WYKREŚL" not in str(last.get("opis") or "").upper():
        return False, None
    return True, _pl_date(last.get("dataWpisu"))


def _company_from_ceidg(firm: dict) -> dict:
    owner = firm.get("wlasciciel") or {}
    person = (
        " ".join(p for p in [owner.get("imie"), owner.get("nazwisko")] if p).strip()
        or None
    )
    return {
        "name": (firm.get("nazwa") or "").strip() or None,
        "person": person,
        "nip": owner.get("nip") or firm.get("nip"),
        "regon": owner.get("regon") or firm.get("regon"),
        "krs": None,
        "address": _ceidg_address(firm.get("adresDzialalnosci") or {}),
        "entity_type": SOLE_TRADER,
    }


def _company_from_krs(data: dict) -> dict | None:
    parsed = _parse_krs(data)
    if parsed is None:
        return None
    return {
        "name": parsed.get("name"),
        "person": None,
        "nip": parsed.get("nip"),
        "regon": parsed.get("regon"),
        "krs": parsed.get("krs"),
        "address": parsed.get("address"),
        "entity_type": COMPANY,
    }


def _result(
    status: str,
    *,
    registry: str | None = None,
    company: dict | None = None,
    warnings: list[dict] | None = None,
    message: str | None = None,
) -> dict:
    return {
        "status": status,
        "registry": registry,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "company": company,
        "warnings": warnings or [],
        "message": message,
    }


def _unverified(message: str, *, registry: str | None = None) -> dict:
    return _result(UNVERIFIED, registry=registry, message=message)


# ── Rejestry (I/O) ───────────────────────────────────────────────────────────


class _RegistryDown(Exception):
    """Rejestr nie odpowiedział albo odpowiedział błędem."""


async def _ceidg_firms(client: httpx.AsyncClient, nip: str) -> list[dict] | None:
    """Wpisy CEIDG dla NIP-u; ``[]`` = brak firmy, ``None`` = brak klucza API."""
    token = settings.CEIDG_API_TOKEN
    if not token:
        return None
    resp = await client.get(
        f"{_CEIDG_BASE}/api/ceidg/v3/firmy",
        params={"nip": nip},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code in (204, 404):
        return []
    if resp.status_code != 200:
        raise _RegistryDown(f"CEIDG HTTP {resp.status_code}")
    return [f for f in (resp.json().get("firmy") or []) if isinstance(f, dict)]


async def _ceidg_detail(client: httpx.AsyncClient, firm: dict) -> dict | None:
    """Szczegóły wpisu (daty zawieszenia/wykreślenia). Brak = bez daty."""
    firm_id = str(firm.get("id") or "")
    if not _CEIDG_ID.fullmatch(firm_id):
        return None
    try:
        resp = await client.get(
            f"{_CEIDG_BASE}/api/ceidg/v3/firma/{firm_id}",
            headers={"Authorization": f"Bearer {settings.CEIDG_API_TOKEN}"},
        )
        if resp.status_code != 200:
            return None
        body = resp.json().get("firma")
        if isinstance(body, list):
            body = body[0] if body else None
        return body if isinstance(body, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


async def _verify_krs(client: httpx.AsyncClient, krs: str) -> dict:
    for rejestr in ("P", "S"):
        resp = await client.get(
            f"{_KRS_BASE}/api/krs/OdpisAktualny/{krs}",
            params={"rejestr": rejestr, "format": "json"},
        )
        if resp.status_code in (204, 404):
            continue
        if resp.status_code != 200:
            raise _RegistryDown(f"KRS HTTP {resp.status_code}")
        data = resp.json()
        return _result(
            VERIFIED,
            registry=REGISTRY_KRS,
            company=_company_from_krs(data),
            warnings=krs_warnings(data.get("odpis") or {}),
        )

    # Brak odpisu aktualnego: spółka wykreślona albo numer, którego nie ma.
    for rejestr in ("P", "S"):
        resp = await client.get(
            f"{_KRS_BASE}/api/krs/OdpisPelny/{krs}",
            params={"rejestr": rejestr, "format": "json"},
        )
        if resp.status_code in (204, 404):
            continue
        if resp.status_code != 200:
            raise _RegistryDown(f"KRS HTTP {resp.status_code}")
        deleted, when = krs_deletion_date(resp.json().get("odpis") or {})
        if deleted:
            return _result(
                VERIFIED,
                registry=REGISTRY_KRS,
                company={"krs": krs, "entity_type": COMPANY},
                warnings=[
                    {
                        "code": WARN_KRS_DELETED,
                        "message": "Spółka została WYKREŚLONA z KRS"
                        + (f" ({when})" if when else "")
                        + ".",
                    }
                ],
            )
    return _unverified(f"W KRS nie ma podmiotu o numerze {krs}.", registry=REGISTRY_KRS)


async def _verify(nip: str, krs: str) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        if krs:
            try:
                return await _verify_krs(client, krs.zfill(10))
            except (httpx.HTTPError, ValueError, _RegistryDown) as exc:
                logger.info("KRS verification failed: %s", type(exc).__name__)
                return _unverified(
                    "Rejestr KRS jest chwilowo niedostępny.", registry=REGISTRY_KRS
                )

        ceidg_down = False
        try:
            firms = await _ceidg_firms(client, nip)
        except (httpx.HTTPError, ValueError, _RegistryDown) as exc:
            logger.info("CEIDG verification failed: %s", type(exc).__name__)
            firms, ceidg_down = None, True

        if firms:
            firm = pick_current_ceidg_firm(firms) or firms[0]
            warnings = ceidg_warnings(firm)
            if warnings:
                warnings = ceidg_warnings(firm, await _ceidg_detail(client, firm))
            return _result(
                VERIFIED,
                registry=REGISTRY_CEIDG,
                company=_company_from_ceidg(firm),
                warnings=warnings,
            )

        # Nie ma JDG pod tym NIP-em (albo CEIDG milczy) → spółka? Numer KRS
        # z Białej Listy, a gdy ta nie odpowie — z wyszukiwarki biznes.gov.pl.
        # Biała Lista dopiero tutaj, nie równolegle z CEIDG: ma dzienny limit
        # zapytań „search”, a przy JDG jej odpowiedź do niczego się nie przyda.
        white_list = await lookup_by_nip(nip)
        krs_number = _digits((white_list or {}).get("krs"))
        if not krs_number and not white_list:
            krs_number = _digits((await lookup_by_biznes(nip) or {}).get("krs"))
        if krs_number:
            try:
                return await _verify_krs(client, krs_number.zfill(10))
            except (httpx.HTTPError, ValueError, _RegistryDown) as exc:
                logger.info("KRS verification failed: %s", type(exc).__name__)
                return _unverified(
                    "Rejestr KRS jest chwilowo niedostępny.", registry=REGISTRY_KRS
                )

        if ceidg_down:
            return _unverified(
                "Rejestr CEIDG jest chwilowo niedostępny.", registry=REGISTRY_CEIDG
            )
        if firms is None:
            return _unverified(
                "Brak połączenia z CEIDG (nie skonfigurowano klucza API).",
                registry=REGISTRY_CEIDG,
            )
        return _unverified(
            f"Firmy o NIP {nip} nie ma w CEIDG, a Biała Lista MF nie podaje "
            "dla niej numeru KRS."
        )


async def verify_company(nip: str | None = None, krs: str | None = None) -> dict:
    """Najnowsze dane firmy z CEIDG albo KRS + ostrzeżenia o jej statusie.

    Nigdy nie rzuca: każda awaria kończy się ``status = unverified`` z powodem,
    bo sprawdzenie jest informacją dla człowieka, a nie bramką generowania.
    """
    nip_digits = _digits(nip)
    krs_digits = _digits(krs)
    if not krs_digits and len(nip_digits) != 10:
        return _unverified(
            "Nie podano poprawnego NIP-u (10 cyfr), więc firmy nie sprawdzono "
            "w rejestrze."
        )
    try:
        return await asyncio.wait_for(
            _verify(nip_digits, krs_digits), timeout=_TOTAL_TIMEOUT_SECONDS
        )
    except TimeoutError:
        logger.info("Company registry verification timed out")
        return _unverified("Rejestr nie odpowiedział w wyznaczonym czasie.")
    except Exception:  # noqa: BLE001 — wynik doradczy, awaria nie może zablokować umowy
        logger.exception("Company registry verification crashed")
        return _unverified("Sprawdzenie firmy w rejestrze nie powiodło się.")
