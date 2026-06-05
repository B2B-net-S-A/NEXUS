"""Auto-uzupełnianie danych firmy z rejestrów państwowych.

Dwa źródła (publiczne, bez auth):
  - **Biała Lista MF** (`wl-api.mf.gov.pl`) — wyszukiwanie po NIP; obejmuje
    JDG (Partner) i spółki (Klient). Główne źródło.
  - **KRS OpenAPI** (`api-krs.ms.gov.pl`) — po numerze KRS; tylko spółki.
    Fallback / dla użytkowników, którzy mają tylko KRS.

Bezpieczeństwo: parametry sanityzowane do cyfr (brak ryzyka SSRF/path-inject);
bazowe URL-e stałe. Błędy/timeouty → ``None`` (UI wraca do wpisu ręcznego).
"""

from __future__ import annotations

import logging
from datetime import timezone, datetime

import httpx

logger = logging.getLogger(__name__)

_WL_BASE = "https://wl-api.mf.gov.pl"
_KRS_BASE = "https://api-krs.ms.gov.pl"
_TIMEOUT = httpx.Timeout(8.0)


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


async def lookup_by_nip(nip: str) -> dict | None:
    """Biała Lista MF — po NIP (10 cyfr). Działa dla JDG i spółek."""
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
        return {
            "name": subject.get("name"),
            "nip": subject.get("nip"),
            "regon": subject.get("regon"),
            "krs": subject.get("krs"),
            "address": address,
            "source": "biala_lista",
        }
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Biała Lista lookup failed for NIP %s: %s", clean, exc)
        return None


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
            "nip": ident.get("nip"),
            "regon": ident.get("regon"),
            "krs": odpis.get("naglowekA", {}).get("numerKRS"),
            "address": address or None,
            "source": "krs",
        }
    except (KeyError, TypeError):
        return None


async def lookup_company(nip: str | None = None, krs: str | None = None) -> dict | None:
    """NIP najpierw (uniwersalne), potem KRS jako fallback."""
    if nip:
        data = await lookup_by_nip(nip)
        if data:
            return data
    if krs:
        return await lookup_by_krs(krs)
    return None
