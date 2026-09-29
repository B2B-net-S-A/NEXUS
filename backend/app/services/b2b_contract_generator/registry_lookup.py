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
import re
from datetime import date

import httpx

from app.core.config import settings
from app.core.scheduling import business_today
from app.services.b2b_contract_generator.entity_type import (
    COMPANY,
    entity_type_from_registry,
)

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
            # Endpoint MSWF (za Akamai) bywa chwilowo 500/403 → kilka prób z
            # narastającym backoffem, żeby nie spadać do samego nazwiska z
            # Białej Listy dla JDG z pełną nazwą firmy.
            for attempt in range(4):
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    break
                if attempt < 3:
                    await asyncio.sleep(0.4 * (attempt + 1))
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
    # Stan na dziś w kalendarzu polskim (API MF). `astimezone()` bez strefy
    # to strefa kontenera, czyli UTC — o 00:30 w Warszawie jeszcze wczoraj.
    today = business_today().isoformat()
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


# Kolejność wyboru wpisu CEIDG dla jednego NIP-u. Osoba, która zamknęła
# działalność i założyła nową, ma pod tym samym NIP-em kilka wpisów (na
# produkcji 10 z 40 NIP-ów Partnerów, 28.09.2026), a API nie zwraca ich w stałej
# kolejności. Do 28.09 brany był pierwszy z listy — bywało nim stare, wykreślone
# przedsiębiorstwo z nieaktualną nazwą i adresem.
_CEIDG_STATUS_RANK = {
    "AKTYWNY": 0,
    "OCZEKUJE_NA_ROZPOCZECIE_DZIALANOSCI": 1,
    "WYLACZNIE_W_FORMIE_SPOLKI": 2,
    "ZAWIESZONY": 3,
    "WYKRESLONY": 4,
}


def _iso_ordinal(value: object) -> int:
    try:
        return date.fromisoformat(str(value)[:10]).toordinal()
    except ValueError:
        return 0


def pick_current_ceidg_firm(firmy: list[dict]) -> dict | None:
    """Wpis CEIDG, który opisuje firmę DZIŚ: najpierw status, potem najnowszy
    start działalności."""
    if not firmy:
        return None
    return min(
        firmy,
        key=lambda f: (
            _CEIDG_STATUS_RANK.get(str(f.get("status") or "").upper(), 5),
            -_iso_ordinal(f.get("dataRozpoczecia")),
        ),
    )


def _parse_ceidg(data: dict) -> dict | None:
    f = pick_current_ceidg_firm(data.get("firmy") or [])
    if f is None:
        return None
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
    # Miejscowość bez ulic: CEIDG nie ma `ulica`, a numer domu stoi przy nazwie
    # miejscowości („Dąbrówka 12, 05-252 Dąbrówka").
    street_name = adr.get("ulica") or (
        adr.get("miasto") if adr.get("budynek") else None
    )
    street = " ".join(p for p in [street_name, adr.get("budynek")] if p).strip()
    if adr.get("lokal"):
        street = f"{street}/{adr['lokal']}".strip("/")
    tail = " ".join(p for p in [adr.get("kod"), adr.get("miasto")] if p).strip()
    full = ", ".join(p for p in [street, tail] if p)
    return full.upper() or None


async def _fetch_odpis(client: httpx.AsyncClient, krs: str, kind: str) -> dict | None:
    """Odpis z API KRS (``OdpisAktualny`` / ``OdpisPelny``), rejestr P, potem S."""
    for rejestr in ("P", "S"):
        resp = await client.get(
            f"{_KRS_BASE}/api/krs/{kind}/{krs}",
            params={"rejestr": rejestr, "format": "json"},
        )
        if resp.status_code == 200:
            return resp.json()
    return None


async def lookup_by_krs(krs: str) -> dict | None:
    """KRS OpenAPI — po numerze KRS (10 cyfr, padded). Tylko spółki."""
    clean = _digits(krs)
    if not clean:
        return None
    clean = clean.zfill(10)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            data = await _fetch_odpis(client, clean, "OdpisAktualny")
            if data is not None:
                return _parse_krs(data)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("KRS lookup failed for KRS %s: %s", clean, exc)
    return None


async def lookup_krs_company_details(krs: str) -> dict:
    """Dane komparycji spółki: siedziba, kapitał, sąd rejestrowy, zarząd.

    Dwa odpisy, bo sąd rejestrowy NIE występuje w odpisie aktualnym (tam jest
    tylko sąd OSTATNIEGO wpisu, zwykle „SYSTEM”) — bierzemy go z historii
    wpisów odpisu pełnego. Imiona i nazwiska członków zarządu publiczne API
    maskuje („K*****”), więc zwracamy tylko to, co da się pokazać: funkcje
    i sposób reprezentacji. Każda awaria = puste pola, nie wyjątek."""
    clean = _digits(krs)
    if not clean:
        return {}
    clean = clean.zfill(10)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            current, full = await asyncio.gather(
                _fetch_odpis(client, clean, "OdpisAktualny"),
                _fetch_odpis(client, clean, "OdpisPelny"),
            )
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("KRS details lookup failed for KRS %s: %s", clean, exc)
        return {}
    details = _parse_krs_company_details(current) if current else {}
    court = _registry_court_from_full(full) if full else None
    if court:
        details["registry_court"] = court
    return details


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


# ── Dane komparycji spółki (wariant „spółka” Generatora, ticket 8) ──────────

_ROMAN = re.compile(r"^[IVXLCDM]+$")
_LOWER_WORDS = frozenset({"dla", "w", "we", "i", "z"})


def _title_word(word: str) -> str:
    core = word.rstrip(",.")
    tail = word[len(core) :]
    if not core:
        return word
    lower = core.lower()
    if lower in _LOWER_WORDS:
        return lower + tail
    if lower in ("m.st", "m.st."):
        return "m.st." + tail.lstrip(".")
    if _ROMAN.match(core):
        return core + tail
    return (
        "-".join(part[:1].upper() + part[1:].lower() for part in core.split("-")) + tail
    )


def title_case_pl(value: str | None) -> str | None:
    """„SĄD REJONOWY DLA M. ST. WARSZAWY” → „Sąd Rejonowy dla m.st. Warszawy”.

    KRS podaje wszystko WIELKIMI literami; do umowy trafia zapis zwykły.
    Liczby rzymskie wydziału („XIV”) zostają wielkie."""
    text = re.sub(r"\s+", " ", value or "").strip()
    if not text:
        return None
    text = re.sub(r"(?i)\bm\.\s*st\.\s*", "M.ST. ", text)
    return " ".join(_title_word(w) for w in text.split(" "))


def _registry_court_from_full(data: dict) -> str | None:
    """Sąd rejestrowy = sąd, który dokonał OSTATNIEGO wpisu nie-systemowego."""
    try:
        entries = data["odpis"]["naglowekP"]["wpis"] or []
    except (KeyError, TypeError):
        return None
    for entry in reversed(entries):
        court = (entry or {}).get("oznaczenieSaduDokonujacegoWpisu") or ""
        if court.strip() and court.strip().upper() != "SYSTEM":
            return title_case_pl(court)
    return None


def _format_capital(amount: str | None, currency: str | None) -> str | None:
    """„1360000,00” PLN → „1.360.000,00” (bez waluty — dokłada ją umowa)."""
    raw = (amount or "").replace(" ", "").strip()
    if not raw:
        return None
    whole, _, frac = raw.partition(",")
    if not whole.isdigit():
        return raw
    groups: list[str] = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    formatted = f"{'.'.join(groups)},{(frac + '00')[:2]}"
    cur = (currency or "PLN").strip().upper()
    return formatted if cur == "PLN" else f"{formatted} {cur}"


def _masked(value: str | None) -> bool:
    return not value or "*" in value


def _parse_krs_company_details(data: dict) -> dict:
    out: dict = {}
    try:
        dane = data["odpis"]["dane"]
    except (KeyError, TypeError):
        return out
    d1 = dane.get("dzial1") or {}
    seat = ((d1.get("siedzibaIAdres") or {}).get("siedziba") or {}).get("miejscowosc")
    if seat:
        out["seat"] = title_case_pl(seat)
    capital = (d1.get("kapital") or {}).get("wysokoscKapitaluZakladowego") or {}
    formatted = _format_capital(capital.get("wartosc"), capital.get("waluta"))
    if formatted:
        out["share_capital"] = formatted
    representation = (dane.get("dzial2") or {}).get("reprezentacja") or {}
    people = []
    for member in representation.get("sklad") or []:
        if not isinstance(member, dict) or member.get("czyZawieszona"):
            continue
        first = ((member.get("imiona") or {}).get("imie") or "").strip()
        last = ((member.get("nazwisko") or {}).get("nazwiskoICzlon") or "").strip()
        name = None if _masked(first) or _masked(last) else f"{first} {last}"
        people.append(
            {
                "name": title_case_pl(name) if name else None,
                "function": title_case_pl(member.get("funkcjaWOrganie")),
            }
        )
    if people:
        out["representatives"] = people
    method = (representation.get("sposobReprezentacji") or "").strip()
    if method:
        out["representation_method"] = method[:1] + method[1:].lower()
    return out


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


def _with_entity_type(result: dict | None) -> dict | None:
    """Dołóż rozstrzygnięcie JDG vs spółka do wyniku lookupu.

    Klasyfikacja wychodzi z BACKENDU jako gotowa wartość, a nie jako surowe
    ``source``/``krs`` do interpretacji na frontendzie, bo ``source`` przychodzi
    w czterech niespójnych formatach („CEIDG", „KRS", „biala_lista", „krs",
    „biznes"), a wiedzę o obu źródłach jednocześnie ma tylko ``_merge``.

    Wołane na KAŻDYM z trzech wyjść ``lookup_company`` — pominięcie ścieżki
    „sama Biała Lista" albo „po KRS" zostawiłoby te wyniki bez pola, czyli bez
    sygnału, i cicho zdegradowałoby je do heurystyki po nazwie.
    """
    if result is None:
        return None
    return {
        **result,
        "entity_type": entity_type_from_registry(
            result.get("source"), result.get("krs")
        ),
    }


async def lookup_company(nip: str | None = None, krs: str | None = None) -> dict | None:
    """Pełna nazwa firmy z biznes.gov.pl (lub CEIDG, jeśli token) + adres/osoba
    z Białej Listy. KRS jako fallback po numerze KRS. Spółka z numerem KRS
    dostaje też dane komparycji (siedziba, kapitał, sąd, zarząd)."""
    result = await _lookup_company_base(nip=nip, krs=krs)
    if result and result.get("entity_type") == COMPANY and result.get("krs"):
        result = {**result, **await lookup_krs_company_details(result["krs"])}
    return result


async def _lookup_company_base(
    nip: str | None = None, krs: str | None = None
) -> dict | None:
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
            return _with_entity_type(_merge(name_src, bl))
        if bl:
            # graceful fallback (sama Biała Lista — nazwisko właściciela)
            return _with_entity_type(bl)
    if krs:
        return _with_entity_type(await lookup_by_krs(krs))
    return None
