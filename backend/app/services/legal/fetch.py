"""Pobieranie tekstów aktów: API ELI Sejmu i CELLAR Urzędu Publikacji UE.

Ustalone na API 25.11.2026:

* **ELI** — ``GET /eli/acts/<akt>`` ma w ``references["Inf. o tekście
  jednolitym"]`` listę obwieszczeń z tekstem jednolitym. Najnowsze (po roku
  i pozycji) to ``GET /eli/acts/<tj>``: ``legalStatusDate`` (stan prawny =
  początek obowiązywania wersji), ``textHTML`` i ``texts``. HTML jest dla
  części tekstów; reszta ma tylko PDF typu ``T`` (``/text/T/<plik>``).
  Tekst HTML samego aktu (``/eli/acts/DU/1964/93/text.html``) to brzmienie
  pierwotne — KC z 1964 r. ma tam art. 61 bez § 2 — więc go nie bierzemy.
  Zmiany ogłoszone po dacie stanu prawnego (``Akty zmieniające`` z późniejszą
  datą) trafiają do ``meta.amendments_after``: tekst jednolity ich nie obejmuje.
* **EUR-Lex** — strona ``eur-lex.europa.eu`` odpowiada automatom 202 z pustą
  treścią (wyzwanie WAF), więc tekst bierzemy z CELLAR
  (``publications.europa.eu/resource/celex/<CELEX>``, XHTML po polsku), a
  najnowszą wersję skonsolidowaną (``0<CELEX>-<RRRRMMDD>``) z SPARQL.
  Link dla ludzi zostaje do EUR-Lex.

Same zapytania GET o dane publiczne; bez danych firmy.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import httpx

from app.services.legal import parse
from app.services.legal.acts import SOURCE_ELI, ActSpec

logger = logging.getLogger(__name__)

ELI_BASE = "https://api.sejm.gov.pl/eli/acts"
ISAP_DETAILS = "https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id={address}"
CELLAR_CELEX = "https://publications.europa.eu/resource/celex/{celex}"
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
EURLEX_HUMAN = "https://eur-lex.europa.eu/legal-content/PL/TXT/?uri=CELEX:{celex}"

TIMEOUT = httpx.Timeout(60.0, connect=15.0)
MAX_BYTES = 40 * 1024 * 1024
USER_AGENT = "legal-corpus/1.0"


class FetchError(RuntimeError):
    """Źródło nie odpowiedziało albo odpowiedź nie nadaje się do odczytu."""


@dataclass(frozen=True)
class VersionPlan:
    """Najnowsza wersja tekstu aktu w źródle (bez pobierania treści)."""

    ident: str
    valid_from: date
    published_on: Optional[date]
    url: str
    format: str
    download_url: str
    title: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchedText:
    plan: VersionPlan
    units: list[parse.ParsedUnit]
    content_hash: str


def _date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _eli_sort_key(ident: str) -> tuple[int, int]:
    match = re.match(r"^[A-Z]+/(\d{4})/(\d+)$", ident)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )


async def _get_json(http: httpx.AsyncClient, url: str) -> dict[str, Any]:
    try:
        response = await http.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise FetchError(f"brak odpowiedzi ({type(exc).__name__})") from exc
    if response.status_code != 200:
        raise FetchError(f"HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise FetchError("odpowiedź nie jest JSON-em") from exc
    if not isinstance(payload, dict):
        raise FetchError("odpowiedź nie jest obiektem JSON")
    return payload


async def _get_bytes(
    http: httpx.AsyncClient, url: str, headers: Optional[dict[str, str]] = None
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    try:
        async with http.stream("GET", url, headers=headers or {}) as response:
            if response.status_code != 200:
                raise FetchError(f"HTTP {response.status_code}")
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise FetchError("plik większy niż limit")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise FetchError(f"brak odpowiedzi ({type(exc).__name__})") from exc
    if not size:
        raise FetchError("pusta odpowiedź")
    return b"".join(chunks)


# ── ELI ─────────────────────────────────────────────────────────────────────


def eli_plan_from(act: dict[str, Any], tj: Optional[dict[str, Any]]) -> VersionPlan:
    """Plan wersji z metadanych aktu i najnowszego tekstu jednolitego (czyste)."""
    source = tj or act
    ident = str(source.get("ELI") or "")
    if not ident:
        raise FetchError("brak identyfikatora ELI")
    files = source.get("texts") or []
    if source.get("textHTML"):
        fmt, download = "html", f"{ELI_BASE}/{ident}/text.html"
    else:
        pdf = next((f for f in files if f.get("type") == "T"), None) or next(
            (f for f in files if f.get("type") in ("O", "I")), None
        )
        if pdf is None or not pdf.get("fileName"):
            raise FetchError("tekst jednolity bez HTML i PDF")
        fmt = "pdf"
        download = f"{ELI_BASE}/{ident}/text/{pdf['type']}/{pdf['fileName']}"
    valid_from = (
        _date(source.get("legalStatusDate"))
        or _date(source.get("promulgation"))
        or _date(source.get("announcementDate"))
    )
    if valid_from is None:
        raise FetchError("brak daty stanu prawnego")
    amendments = [
        {"id": str(item.get("id")), "date": str(item.get("date"))}
        for item in (act.get("references") or {}).get("Akty zmieniające") or []
        if _date(item.get("date")) and _date(item.get("date")) > valid_from
    ]
    amendments.sort(key=lambda item: item["date"])
    address = source.get("address")
    return VersionPlan(
        ident=ident,
        valid_from=valid_from,
        published_on=_date(source.get("promulgation")),
        url=ISAP_DETAILS.format(address=address) if address else download,
        format=fmt,
        download_url=download,
        title=act.get("title"),
        meta={
            "amendments_after": amendments[:200],
            "legal_status_date": str(source.get("legalStatusDate") or ""),
            "source_url": download,
            "base_act": act.get("ELI"),
        },
    )


async def eli_plan(http: httpx.AsyncClient, spec: ActSpec) -> VersionPlan:
    act = await _get_json(http, f"{ELI_BASE}/{spec.ident}")
    tj_refs = (act.get("references") or {}).get("Inf. o tekście jednolitym") or []
    tj_ids = sorted(
        (str(ref.get("id")) for ref in tj_refs if ref.get("id")),
        key=_eli_sort_key,
        reverse=True,
    )
    tj = await _get_json(http, f"{ELI_BASE}/{tj_ids[0]}") if tj_ids else None
    return eli_plan_from(act, tj)


# ── CELLAR (EUR-Lex) ────────────────────────────────────────────────────────

_SPARQL_QUERY = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?celex ?date WHERE {{
  ?w cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(STR(?celex), "0{base}-"))
  OPTIONAL {{ ?w cdm:act_consolidated_date ?date }}
}} ORDER BY DESC(?celex) LIMIT 5"""


def latest_consolidated(bindings: list[dict[str, Any]]) -> Optional[tuple[str, date]]:
    """Najnowsza wersja skonsolidowana z wyniku SPARQL (czyste)."""
    best: Optional[tuple[str, date]] = None
    for row in bindings:
        celex = str((row.get("celex") or {}).get("value") or "")
        match = re.match(r"^0\d{4}[A-Z]\d{4}-(\d{8})$", celex)
        if not match:
            continue
        raw = match.group(1)
        when = _date(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
        if when and (best is None or when > best[1]):
            best = (celex, when)
    return best


async def eurlex_plan(http: httpx.AsyncClient, spec: ActSpec) -> VersionPlan:
    base = spec.ident[1:]
    try:
        response = await http.get(
            SPARQL,
            params={
                "query": _SPARQL_QUERY.format(base=base),
                "format": "application/sparql-results+json",
            },
        )
    except httpx.HTTPError as exc:
        raise FetchError(f"SPARQL bez odpowiedzi ({type(exc).__name__})") from exc
    if response.status_code != 200:
        raise FetchError(f"SPARQL HTTP {response.status_code}")
    try:
        bindings = response.json()["results"]["bindings"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FetchError("SPARQL: nieczytelna odpowiedź") from exc
    latest = latest_consolidated(bindings)
    if latest is None:
        raise FetchError("brak wersji skonsolidowanej")
    celex, when = latest
    download = CELLAR_CELEX.format(celex=celex)
    return VersionPlan(
        ident=celex,
        valid_from=when,
        published_on=None,
        url=EURLEX_HUMAN.format(celex=celex),
        format="xhtml",
        download_url=download,
        meta={"source_url": download, "base_celex": spec.ident},
    )


# ── pobranie i podział ──────────────────────────────────────────────────────


async def plan_for(http: httpx.AsyncClient, spec: ActSpec) -> VersionPlan:
    if spec.source == SOURCE_ELI:
        return await eli_plan(http, spec)
    return await eurlex_plan(http, spec)


def content_hash(units: list[parse.ParsedUnit]) -> str:
    digest = hashlib.sha256()
    for unit in units:
        digest.update(unit.key.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(unit.text.encode("utf-8"))
        digest.update(b"\x01")
    return digest.hexdigest()


async def fetch_text(http: httpx.AsyncClient, plan: VersionPlan) -> FetchedText:
    """Pobiera tekst wersji i dzieli go na jednostki (PDF w osobnym procesie)."""
    import asyncio

    from app.services.legal import pdf_worker

    if plan.format == "pdf":
        body = await _get_bytes(http, plan.download_url)
        handle, path = tempfile.mkstemp(prefix="legal-", suffix=".pdf")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(body)
            lines = await pdf_worker.read_lines(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if lines is None:
            raise FetchError("PDF nie dał się odczytać")
        units = parse.parse_lines(parse.pdf_body_lines(lines))
    elif plan.format == "html":
        body = await _get_bytes(http, plan.download_url, {"Accept": "text/html"})
        document = body.decode("utf-8", "replace")
        units = await asyncio.to_thread(
            lambda: parse.parse_lines(parse.eli_html_lines(document))
        )
    else:
        body = await _get_bytes(
            http,
            plan.download_url,
            {"Accept": "application/xhtml+xml", "Accept-Language": "pol"},
        )
        document = body.decode("utf-8", "replace")
        units = await asyncio.to_thread(
            lambda: parse.parse_lines(parse.eurlex_lines(document))
        )
    articles = sum(1 for unit in units if unit.kind == parse.KIND_ART)
    if articles < 3:
        raise FetchError(f"tekst bez jednostek redakcyjnych ({articles} art.)")
    return FetchedText(plan=plan, units=units, content_hash=content_hash(units))
