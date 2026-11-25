"""SAOS (System Analizy Orzeczeń Sądowych): wyszukiwanie i treść orzeczenia.

API: ``https://www.saos.org.pl/api`` (dokumentacja
``https://www.saos.org.pl/help/index.php/dokumentacja-api``) — publiczne,
tylko GET, serwis sam zaprasza do „programowego API”. ``robots.txt`` ma
``Disallow: /api/`` — czytamy to jako zakaz dla robotów indeksujących, nie dla
klienta udokumentowanego API: nie chodzimy po linkach, pytamy celowanymi
zapytaniami, najwyżej jedno na sekundę (reguła asystenta prawnego).

Zasięg danych sprawdzony 25.11.2026: sądy powszechne na bieżąco (orzeczenia
z listopada 2026), Sąd Najwyższy tylko do 2016 r., sądów administracyjnych
w SAOS brak (0 wyników).
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional, Sequence

from app.services.legal_case_law import schema
from app.services.legal_case_law.http import PoliteClient

API = "https://www.saos.org.pl/api"
PUBLIC_URL = "https://www.saos.org.pl/judgments/{id}"
SEARCH_PAGE_URL = "https://www.saos.org.pl/search"
MIN_INTERVAL_SECONDS = 1.0
MAX_PAGE_SIZE = 100

#: Nasz rodzaj sądu → ``courtType`` SAOS.
COURT_TYPES: dict[str, str] = {
    "supreme": "SUPREME",
    "common": "COMMON",
    "administrative": "ADMINISTRATIVE",
    "constitutional": "CONSTITUTIONAL_TRIBUNAL",
    "appeal_chamber": "NATIONAL_APPEAL_CHAMBER",
}
_COURT_TYPE_BACK = {value: key for key, value in COURT_TYPES.items()}
_KINDS = {
    "SENTENCE": "judgment",
    "DECISION": "decision",
    "RESOLUTION": "resolution",
    "REGULATION": "order",
    "REASONS": "reasons",
}
_COURT_NAMES = {
    "supreme": "Sąd Najwyższy",
    "constitutional": "Trybunał Konstytucyjny",
    "appeal_chamber": "Krajowa Izba Odwoławcza",
    "administrative": "Sąd administracyjny",
    "common": "Sąd powszechny",
}

_BLOCK_TAG = re.compile(r"<\s*(br|/p|/div|/h[1-6]|/li|/tr)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


@dataclass(frozen=True)
class CaseRecord:
    """Orzeczenie po parsowaniu — kształt wiersza ``legal_cases`` bez id."""

    source: str
    source_id: str
    signature: str
    court: str
    court_type: str
    judgment_date: Optional[date]
    kind: str
    url: str
    summary: Optional[str]
    text: str
    topics: tuple[str, ...] = field(default=())

    @property
    def content_sha256(self) -> str:
        body = f"{self.summary or ''}\n{self.text}"
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


def html_to_text(value: Optional[str]) -> str:
    """Tekst orzeczenia bez znaczników (sądy powszechne podają HTML, SN tekst)."""
    if not value:
        return ""
    text = _BLOCK_TAG.sub("\n", value)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = _SPACES.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _court_name(data: dict[str, Any], court_type: str) -> str:
    division = data.get("division") or {}
    court = division.get("court") or {}
    if court.get("name"):
        name = str(court["name"])
    else:
        name = _COURT_NAMES.get(court_type, "Sąd")
    chambers = [c.get("name") for c in division.get("chambers") or [] if c.get("name")]
    if chambers:
        name = f"{name} — {', '.join(chambers)}"
    return name[: schema.COURT_MAX]


def parse_judgment(data: dict[str, Any]) -> Optional[CaseRecord]:
    """Rekord z ``data`` odpowiedzi ``/api/judgments/{id}``; ``None`` = bez treści."""
    judgment_id = data.get("id")
    court_type = _COURT_TYPE_BACK.get(str(data.get("courtType") or ""))
    signatures = [
        str(case.get("caseNumber")).strip()
        for case in data.get("courtCases") or []
        if case.get("caseNumber")
    ]
    text = html_to_text(data.get("textContent"))
    if judgment_id is None or court_type is None or not signatures or not text:
        return None
    summary = html_to_text(data.get("summary")) or None
    return CaseRecord(
        source="saos",
        source_id=str(judgment_id),
        signature=", ".join(signatures)[: schema.SIGNATURE_MAX],
        court=_court_name(data, court_type),
        court_type=court_type,
        judgment_date=_date(data.get("judgmentDate")),
        kind=_KINDS.get(str(data.get("judgmentType") or ""), "judgment"),
        url=PUBLIC_URL.format(id=int(judgment_id)),
        summary=summary,
        text=text,
    )


def search_params(
    query: str,
    *,
    court_type: Optional[str] = None,
    since: Optional[date] = None,
    page_size: int = 20,
    sort_by_citations: bool = True,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "all": query,
        "pageSize": max(1, min(page_size, MAX_PAGE_SIZE)),
        "pageNumber": 0,
    }
    if court_type:
        params["courtType"] = COURT_TYPES[court_type]
    if since:
        params["judgmentDateFrom"] = since.isoformat()
    if sort_by_citations:
        # SAOS nie sortuje po trafności; liczba powołań w innych orzeczeniach
        # wyciąga orzeczenia, na które sądy się powołują.
        params["sortingField"] = "REFERENCING_JUDGMENTS_COUNT"
        params["sortingDirection"] = "DESC"
    return params


def parse_search_ids(data: Optional[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for item in (data or {}).get("items") or []:
        try:
            ids.append(int(item["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return ids


async def search_ids(
    client: PoliteClient,
    query: str,
    *,
    court_type: Optional[str] = None,
    since: Optional[date] = None,
    limit: int = 20,
) -> list[int]:
    """Identyfikatory orzeczeń SAOS dla zapytania; awaria = pusta lista."""
    data = await client.get_json(
        f"{API}/search/judgments",
        search_params(query, court_type=court_type, since=since, page_size=limit),
    )
    return parse_search_ids(data)[:limit]


async def fetch_judgment(client: PoliteClient, judgment_id: int) -> Optional[CaseRecord]:
    """Pełna treść orzeczenia; awaria albo brak treści = ``None``."""
    data = await client.get_json(f"{API}/judgments/{int(judgment_id)}")
    payload = (data or {}).get("data")
    if not isinstance(payload, dict):
        return None
    return parse_judgment(payload)


async def fetch_many(
    client: PoliteClient, judgment_ids: Sequence[int]
) -> list[CaseRecord]:
    records: list[CaseRecord] = []
    for judgment_id in judgment_ids:
        record = await fetch_judgment(client, judgment_id)
        if record is not None:
            records.append(record)
    return records


def new_client(**overrides: Any) -> PoliteClient:
    return PoliteClient(name="saos", min_interval=MIN_INTERVAL_SECONDS, **overrides)
