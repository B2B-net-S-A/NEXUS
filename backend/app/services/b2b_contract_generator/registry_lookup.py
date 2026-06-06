"""Auto-uzupełnianie danych firmy z rejestrów państwowych.

Cel: dla JDG pokazać **pełną nazwę firmy** (np. „Management Services - Olaf
Moczydłowski"), a nie samo imię i nazwisko właściciela.

Źródła (po NIP/KRS, parametry sanityzowane do cyfr):

  - **Wyszukiwarka firm biznes.gov.pl** (`/api/data-warehouse/SearchAdvance`) —
    publiczne połączone CEIDG+KRS; jedyne BEZ-TOKENOWE źródło z pełną nazwą
    firmy JDG. Akamai blokuje requesty „botowe" → wysyłamy realistyczne
    nagłówki przeglądarki (zweryfikowane z IP Hetznera: 200). To główne źródło
    NAZWY. (Endpoint oznaczony „nie do przetwarzania maszynowego" — używamy go
    tylko do pojedynczych, interaktywnych zapytań wyzwalanych przez użytkownika.)
  - **CEIDG API v3** (`dane.biznes.gov.pl`) — oficjalne API maszynowe, ale
    wymaga tokenu (`settings.CEIDG_API_TOKEN`). Jeśli token jest — ma priorytet
    nad biznes.gov.pl.
  - **Biała Lista MF** (`wl-api.mf.gov.pl`) — adres siedziby + osoba (dla JDG
    imię+nazwisko właściciela) + REGON + KRS. Zawsze dostępna; fallback nazwy.
  - **KRS OpenAPI** (`api-krs.ms.gov.pl`) — po numerze KRS (spółki).

Zwracany kształt: ``{name, person, nip, regon, krs, address, source}``.
``name`` = pełna nazwa firmy; ``person`` = osoba fizyczna (JDG) → pole „Imię i
nazwisko". Błędy/timeouty → ``None`` (UI wraca do wpisu ręcznego).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_WL_BASE = "https://wl-api.mf.gov.pl"
_KRS_BASE = "https://api-krs.ms.gov.pl"
_CEIDG_BASE = "https://dane.biznes.gov.pl"
_BIZNES_BASE = "https://www.biznes.gov.pl/pl/wyszukiwarka-firm/api/data-warehouse"
_TIMEOUT = httpx.Timeout(10.0)

# Akamai przed biznes.gov.pl odrzuca „gołe" requesty (generic UA → 403). Pełny
# zestaw nagłówków przeglądarki przechodzi (zweryfikowane lokalnie i z Hetznera).
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    "Referer": "https://www.biznes.gov.pl/pl/wyszukiwarka-firm/",
    "sec-ch-ua": '"Chromium";v="147", "Not.A/Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


async def lookup_by_biznes(nip: str) -> dict | None:
    """Wyszukiwarka firm biznes.gov.pl — pełna nazwa firmy (JDG i spółki)."""
    clean = _digits(nip)
    if len(clean) != 10:
        return None
    url = f"{_BIZNES_BASE}/SearchAdvance"
    params = {"nip": clean, "pageNumber": 0, "pageSize": 20}
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_BROWSER_HEADERS
        ) as client:
            resp = None
            for attempt in range(2):  # endpoint MSWF bywa chwilowo 500
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    break
                if attempt == 0:
                    await asyncio.sleep(0.4)
            if resp is None or resp.status_code != 200:
                code = resp.status_code if resp is not None else "?"
                logger.info("biznes.gov.pl lookup non-200 (%s) NIP %s", code, clean)
                return None
            companies = resp.json().get("companyList") or []
            if not companies:
                return None
            c = companies[0]
            name = (c.get("name") or "").strip() or None
            return {
                "name": name,
                "nip": c.get("nip"),
                "regon": c.get("regon"),
                "krs": c.get("krs"),
                "source": (c.get("source") or "").upper(),  # CEIDG (JDG) | KRS
            }
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("biznes.gov.pl lookup failed NIP %s: %s", clean, exc)
        return None


async def lookup_by_nip(nip: str) -> dict | None:
    """Biała Lista MF — po NIP (10 cyfr). Adres + osoba (JDG) + REGON + KRS.

    Dla JDG ``name`` = nazwisko/imię właściciela (Biała Lista nie ma pełnej
    nazwy firmy), które wystawiamy też jako ``person``. Dla spółek ``name`` =
    nazwa spółki, ``person`` = ``None``.
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
    """CEIDG API v3 — pełna nazwa firmy JDG. Wymaga tokenu (opcjonalne)."""
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
        "source": "CEIDG",
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


def _merge(name_src: dict, bl: dict | None) -> dict:
    """Złóż wynik: NAZWA z name_src (biznes/CEIDG), ADRES + osoba z Białej Listy."""
    src = (name_src.get("source") or "").upper()
    # JDG, gdy źródło nazwy to CEIDG, albo Biała Lista nie ma KRS.
    is_jdg = src == "CEIDG" or (bl is not None and not bl.get("krs"))
    person = name_src.get("person") or (bl.get("name") if bl else None)
    return {
        "name": name_src.get("name"),
        "person": person if is_jdg else None,
        "nip": name_src.get("nip") or (bl.get("nip") if bl else None),
        "regon": name_src.get("regon") or (bl.get("regon") if bl else None),
        "krs": (bl.get("krs") if bl else None) or name_src.get("krs"),
        "address": (bl.get("address") if bl else None) or name_src.get("address"),
        "source": name_src.get("source") or "biznes",
    }


async def lookup_company(nip: str | None = None, krs: str | None = None) -> dict | None:
    """Pełna nazwa firmy z biznes.gov.pl (lub CEIDG, jeśli token) + adres/osoba
    z Białej Listy. KRS jako fallback po numerze KRS."""
    if nip:
        # Adres/osobę zawsze z Białej Listy; nazwę z preferowanego źródła.
        if settings.CEIDG_API_TOKEN:
            bl, name_src = await asyncio.gather(
                lookup_by_nip(nip), lookup_by_ceidg(nip)
            )
            if not (name_src and name_src.get("name")):
                name_src = await lookup_by_biznes(nip)
        else:
            bl, name_src = await asyncio.gather(
                lookup_by_nip(nip), lookup_by_biznes(nip)
            )
        if name_src and name_src.get("name"):
            return _merge(name_src, bl)
        if bl:
            return bl  # graceful fallback (sama Biała Lista — nazwisko właściciela)
    if krs:
        return await lookup_by_krs(krs)
    return None
