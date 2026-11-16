"""Bramka NEXUSA między Zbieraczem a Analitykiem.

Bot czyta cudze strony, więc jego numer aktu albo druku to twierdzenie, nie
fakt. Bramka:

* liczy odcisk pozycji (bez powtórek z kolejnych biegów),
* nadaje klasę źródła: ``lex`` dla LEX-u, ``official`` dla adresu z listy
  domen urzędowych, inaczej ``practice``,
* sama sprawdza numer w API Sejmu: akt ``/eli/acts/{DU|MP}/{rok}/{poz}``,
  druk ``/sejm/term10/processes/{nr}``. Numer, którego API nie zna (404),
  odpada (``rejected``). Pozycja bez numeru zostaje jako ``unverified``,
  nigdy jako fakt urzędowy. Błąd sieci też daje ``unverified``.

Sprawdzanie jest sekwencyjne, z krótkim limitem czasu i najwyżej
``MAX_LOOKUPS`` zapytaniami na bieg. Transakcja bazy jest zamknięta na czas
zapytań do sieci. Logi: same liczby.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.law_radar import LawRadarItem
from app.services.law_radar import schema

logger = logging.getLogger(__name__)

SEJM_API = "https://api.sejm.gov.pl"
SEJM_TERM = "term10"
MAX_LOOKUPS = 60
LOOKUP_TIMEOUT_SECONDS = 8.0
MAX_OFFICIAL_TEXT = 300

#: Domeny urzędowe (decyzja Artura 15.11.2026); ``gov.pl`` z poddomenami osobno.
OFFICIAL_HOSTS: frozenset[str] = frozenset(
    {
        "api.sejm.gov.pl",
        "sejm.gov.pl",
        "isap.sejm.gov.pl",
        "dziennikustaw.gov.pl",
        "monitorpolski.gov.pl",
        "gov.pl",
        "podatki.gov.pl",
        "ksef.podatki.gov.pl",
        "zus.pl",
        "eur-lex.europa.eu",
        "uodo.gov.pl",
        "pip.gov.pl",
        "orzeczenia.nsa.gov.pl",
        "eureka.mf.gov.pl",
        "legislacja.gov.pl",
    }
)
_OFFICIAL_SUFFIX = ".gov.pl"
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}")


_HOSTNAME = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)


def host_of(url: str) -> str:
    """Host z adresu; podejrzany adres (``\\``, dane logowania, dziwne znaki) to "".

    Przeglądarka czyta ``\\`` jak ``/``, a ``urlsplit`` jako część hosta, więc
    ``https://evil.com\\.gov.pl`` udawałby stronę urzędową (przegląd 15.11.2026).
    """

    if "\\" in url:
        return ""
    parts = urlsplit(url)
    if "@" in parts.netloc:
        return ""
    host = (parts.hostname or "").lower().rstrip(".")
    if not _HOSTNAME.match(host):
        return ""
    return host.removeprefix("www.")


def is_official_host(host: str) -> bool:
    if not host:
        return False
    return host in OFFICIAL_HOSTS or host.endswith(_OFFICIAL_SUFFIX)


def classify(source: str, url: str) -> str:
    if source == "lex":
        return "lex"
    return "official" if is_official_host(host_of(url)) else "practice"


def normalize_url(url: str) -> str:
    """Schemat i host małymi literami, bez kotwicy i końcowego ``/``."""

    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")
    )


def fingerprint(
    url: str, act_ref: Optional[str], print_no: Optional[str], published: date
) -> str:
    """Ta sama pozycja z kolejnego biegu ma ten sam odcisk.

    Data publikacji jest w odcisku, bo kolejny etap tego samego procesu
    (nowa data na tej samej stronie) to nowa wiadomość dla Analityka.
    """

    raw = "|".join(
        (normalize_url(url), act_ref or "", print_no or "", published.isoformat())
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def act_url(act_ref: str) -> str:
    publisher, year, position = act_ref.split("/")
    return f"{SEJM_API}/eli/acts/{publisher}/{int(year)}/{int(position)}"


def process_url(print_no: str) -> str:
    return f"{SEJM_API}/sejm/{SEJM_TERM}/processes/{int(print_no)}"


def _text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:MAX_OFFICIAL_TEXT] or None


def _date_text(value: Any) -> Optional[str]:
    if isinstance(value, str) and _DATE.match(value):
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def parse_act(data: dict[str, Any]) -> dict[str, Any]:
    """Z odpowiedzi ELI tylko to, co pokazujemy: tytuł, status, wejście w życie."""

    out = {
        "act_title": _text(data.get("title")),
        "act_status": _text(data.get("status")),
        "entry_into_force": _date_text(data.get("entryIntoForce")),
        "in_force": _text(data.get("inForce")),
    }
    return {key: value for key, value in out.items() if value is not None}


def parse_process(data: dict[str, Any]) -> dict[str, Any]:
    """Z procesu Sejmu: tytuł i ostatni etap (nazwa, data)."""

    stages = data.get("stages") if isinstance(data.get("stages"), list) else []
    last = (
        next((stage for stage in reversed(stages) if isinstance(stage, dict)), None)
        or {}
    )
    out = {
        "process_title": _text(data.get("title")),
        "official_stage": _text(last.get("stageName")),
        "official_stage_date": _date_text(last.get("date")),
    }
    return {key: value for key, value in out.items() if value is not None}


@dataclass(frozen=True)
class GateResult:
    gate: str
    reason: Optional[str] = None
    official: dict[str, Any] = field(default_factory=dict)


@dataclass
class SejmChecker:
    """Zapytania do API Sejmu dla jednego biegu: pamięć wyników i limit."""

    client: httpx.AsyncClient
    max_lookups: int = MAX_LOOKUPS
    lookups: int = 0
    errors: int = 0
    _cache: dict[str, tuple[str, Optional[dict[str, Any]]]] = field(
        default_factory=dict
    )

    async def fetch(self, url: str) -> tuple[str, Optional[dict[str, Any]]]:
        """``found`` z JSON-em, ``missing`` (404), ``error`` albo ``limit``."""

        if url in self._cache:
            return self._cache[url]
        if self.lookups >= self.max_lookups:
            return "limit", None
        self.lookups += 1
        try:
            response = await self.client.get(
                url, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError:
            self.errors += 1
            result: tuple[str, Optional[dict[str, Any]]] = ("error", None)
        else:
            if response.status_code == 404:
                result = ("missing", None)
            elif response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    data = None
                result = ("found", data) if isinstance(data, dict) else ("error", None)
                if result[0] == "error":
                    self.errors += 1
            else:
                self.errors += 1
                result = ("error", None)
        self._cache[url] = result
        return result

    async def check(
        self, act_ref: Optional[str], print_no: Optional[str]
    ) -> GateResult:
        if not act_ref and not print_no:
            return GateResult("unverified", "no_ref")
        official: dict[str, Any] = {}
        missing: Optional[str] = None
        unsure: Optional[str] = None
        for ref, url, parse, label in (
            (act_ref, act_url, parse_act, "act"),
            (print_no, process_url, parse_process, "print"),
        ):
            if not ref:
                continue
            outcome, data = await self.fetch(url(ref))
            if outcome == "missing":
                missing = missing or f"{label}_missing"
            elif outcome == "found" and data is not None:
                official.update(parse(data))
            else:
                unsure = unsure or ("limit" if outcome == "limit" else "network")
        if missing:
            return GateResult("rejected", missing, official)
        if unsure:
            return GateResult("unverified", unsure, official)
        return GateResult("verified", None, official)


async def verify_pending(
    db: AsyncSession,
    *,
    run_id: Optional[int] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, int]:
    """Sprawdź pozycje ``pending`` (jednego biegu albo wszystkie).

    Odczyt kończy transakcję przed siecią; zapis wyników w nowej transakcji.
    """

    query = select(LawRadarItem.id, LawRadarItem.act_ref, LawRadarItem.print_no).where(
        LawRadarItem.gate == "pending"
    )
    if run_id is not None:
        query = query.where(LawRadarItem.run_id == run_id)
    rows = (await db.execute(query.order_by(LawRadarItem.id))).all()
    await db.commit()
    counts = {gate: 0 for gate in schema.GATES if gate != "pending"}
    if not rows:
        return {**counts, "lookups": 0, "errors": 0}

    async def _run(
        http: httpx.AsyncClient,
    ) -> tuple[SejmChecker, list[tuple[int, GateResult]]]:
        checker = SejmChecker(http)
        results = []
        for item_id, act_ref, print_no in rows:
            results.append((item_id, await checker.check(act_ref, print_no)))
        return checker, results

    if client is None:
        async with httpx.AsyncClient(timeout=LOOKUP_TIMEOUT_SECONDS) as own:
            checker, results = await _run(own)
    else:
        checker, results = await _run(client)

    for item_id, result in results:
        await db.execute(
            update(LawRadarItem)
            .where(LawRadarItem.id == item_id, LawRadarItem.gate == "pending")
            .values(
                gate=result.gate, gate_reason=result.reason, official=result.official
            )
        )
        counts[result.gate] += 1
    await db.commit()
    summary = {**counts, "lookups": checker.lookups, "errors": checker.errors}
    logger.info(
        "law_radar gate run=%s items=%d verified=%d unverified=%d rejected=%d "
        "lookups=%d errors=%d",
        run_id,
        len(rows),
        counts["verified"],
        counts["unverified"],
        counts["rejected"],
        checker.lookups,
        checker.errors,
    )
    return summary
