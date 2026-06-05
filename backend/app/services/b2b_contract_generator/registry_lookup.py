"""Auto-uzupełnianie danych firmy z rejestrów państwowych.

Trzy źródła (wszystkie po NIP/KRS, parametry sanityzowane do cyfr):

  - **CEIDG API v3** (`dane.biznes.gov.pl`) — JDG; jedyne źródło z **pełną nazwą
    firmy** (np. „Management Services - Olaf Moczydłowski"). Wymaga tokenu
    (`settings.CEIDG_API_TOKEN`); bez tokenu pomijane.
  - **Biała Lista MF** (`wl-api.mf.gov.pl`) — JDG + spółki; dla JDG zwraca
    **imię i nazwisko** właściciela (pole `person`), nie nazwę firmy. Zawsze
    dostępne, bez auth — główny fallback.
  - **KRS OpenAPI** (`api-krs.ms.gov.pl`) — tylko spółki, po numerze KRS.

Zwracany kształt: ``{name, person, nip, regon, krs, address, source}``.
``person`` = osoba fizyczna (JDG) → trafia do pola „Imię i nazwisko";
``name`` = nazwa firmy (pełna z CEIDG, lub nazwisko z Białej Listy dla JDG,
lub nazwa spółki). Błędy/timeouty → ``None`` (UI wraca do wpisu ręcznego).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_WL_BASE = "https://wl-api.mf.gov.pl"
_KRS_BASE = "https://api-krs.ms.gov.pl"
_CEIDG_BASE = "https://dane.biznes.gov.pl"
_TIMEOUT = httpx.Timeout(8.0)


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


async def lookup_by_nip(nip: str) -> dict | None:
    """Biała Lista MF — po NIP (10 cyfr). Działa dla JDG i spółek.

    Dla JDG ``name`` = nazwisko/imię właściciela (Biała Lista nie ma pełnej
    nazwy firmy), które wystawiamy też jako ``person``. Dla spółek (jest KRS)
    ``name`` = nazwa spółki, ``person`` = ``None``.
    """
    clean = _digits(nip)
    if len(clean) != 10:
        return None
    today = datetime.now(timezone.utc).astimezone().date().isoformat()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_WL_BASE}/api/search/nip/{clean}", params={"date": today}
            )
        if resp.status_code != 200:
            return None
        subject = (resp.json().get("result") or {}).get("subject")
        if not subject:
            return None
        address = subject.get("workingAddress") or subject.get("residenceAddress")
        krs = subject.get("krs")
        name = subject.get("name")
        return {
            "name": name,
            # JDG (brak KRS) → `name` to osoba fizyczna; spółka → brak osoby.
            "person": None if krs else name,
            "nip": subject.get("nip"),
            "regon": subject.get("regon"),
            "krs": krs,
            "address": address,
            "source": "biala_lista",
        }
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Biała Lista lookup failed for NIP %s: %s", clean, exc)
        return None


async def lookup_by_ceidg(nip: str) -> dict | None:
    """CEIDG API v3 — po NIP, z pełną nazwą firmy JDG. Wymaga tokenu."""
    token = settings.CEIDG_API_TOKEN
    if not token:
        return None
    clean = _digits(nip)
    if len(clean) != 10:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_CEIDG_BASE}/api/ceidg/v3/firmy",
                params={"nip": clean},
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            logger.info("CEIDG lookup non-200 (%s) for NIP %s", resp.status_code, clean)
            return None
        return _parse_ceidg(resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("CEIDG lookup failed for NIP %s: %s", clean, exc)
        return None


def _parse_ceidg(data: dict) -> dict | None:
    firmy = data.get("firmy") or []
    if not firmy:
        return None
    f = firmy[0]
    owner = f.get("wlasciciel") or {}
    person = (
        " ".join(p for p in [owner.get("imie"), owner.get("nazwisko")] if p).strip()
        or None
    )
    address = _ceidg_address(f.get("adresDzialalnosci") or {})
    return {
        "name": f.get("nazwa"),
        "person": person,
        "nip": owner.get("nip") or f.get("nip"),
        "regon": owner.get("regon") or f.get("regon"),
        "krs": None,
        "address": address,
        "source": "ceidg",
    }


def _ceidg_address(adr: dict) -> str | None:
    if not adr:
        return None
    street = " ".join(p for p in [adr.get("ulica"), adr.get("budynek")] if p).strip()
    if adr.get("lokal"):
        street = f"{street}/{adr['lokal']}".strip("/")
    tail = " ".join(p for p in [adr.get("kod"), adr.get("miasto")] if p).strip()
    full = ", ".join(p for p in [street, tail] if p)
    return full.upper() or None


async def lookup_by_krs(krs: str) -> dict | None:
    """KRS OpenAPI — po numerze KRS (10 cyfr, padded). Tylko spółki."""
    clean = _digits(krs)
    if not clean:
        return None
    clean = clean.zfill(10)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for rejestr in ("P", "S"):
                resp = await client.get(
                    f"{_KRS_BASE}/api/krs/OdpisAktualny/{clean}",
                    params={"rejestr": rejestr, "format": "json"},
                )
                if resp.status_code != 200:
                    continue
                parsed = _parse_krs(resp.json())
                if parsed:
                    return parsed
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("KRS lookup failed for KRS %s: %s", clean, exc)
    return None


def _parse_krs(data: dict) -> dict | None:
    try:
        odpis = data["odpis"]
        d1 = odpis["dane"]["dzial1"]
        podmiot = d1["danePodmiotu"]
        ident = podmiot.get("identyfikatory", {})
        adr = d1["siedzibaIAdres"]["adres"]
        street = " ".join(p for p in [adr.get("ulica"), adr.get("nrDomu")] if p).strip()
        if adr.get("nrLokalu"):
            street = f"{street}/{adr['nrLokalu']}"
        tail = " ".join(
            p for p in [adr.get("kodPocztowy"), adr.get("miejscowosc")] if p
        ).strip()
        address = ", ".join(p for p in [street, tail] if p)
        return {
            "name": podmiot.get("nazwa"),
            "person": None,
            "nip": ident.get("nip"),
            "regon": ident.get("regon"),
            "krs": odpis.get("naglowekA", {}).get("numerKRS"),
            "address": address or None,
            "source": "krs",
        }
    except (KeyError, TypeError):
        return None


async def lookup_company(nip: str | None = None, krs: str | None = None) -> dict | None:
    """CEIDG (pełna nazwa JDG, jeśli token) → Biała Lista → KRS (fallback)."""
    if nip:
        ceidg = await lookup_by_ceidg(nip)
        if ceidg and ceidg.get("name"):
            return ceidg
        wl = await lookup_by_nip(nip)
        if wl:
            return wl
    if krs:
        return await lookup_by_krs(krs)
    return None
