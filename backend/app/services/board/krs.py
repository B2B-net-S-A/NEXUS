"""Odpis pełny KRS spółki dla Rady nadzorczej (R1).

Co noc pobiera odpis pełny z publicznego API KRS, zapisuje go, gdy treść się
zmieniła, zakłada w rejestrze dokumentów wiersze z wzmianek (sprawozdania,
uchwały zatwierdzające, zmiany statutu) i daje dzwonek Radzie i adminom
o nowym wpisie. API maskuje imiona i nazwiska członków organów — NEXUS liczy
skład i funkcje, nazwisk nie ma.

Wynik pobrania to dodatek: awaria API zostawia ostatni odpis, ekran pokazuje
jego datę.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.board_document import BoardDocument, BoardKrsSnapshot
from app.services.b2b_documents.company_party import COMPANY_PL

logger = logging.getLogger(__name__)

KRS_BASE = "https://api-krs.ms.gov.pl"
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
ATTEMPTS = 3

_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def company_krs() -> str:
    return str(COMPANY_PL["krs"]).zfill(10)


# ── parser ──────────────────────────────────────────────────────────────────


def parse_pl_date(text: Any) -> Optional[date]:
    """Pierwsza data „DD.MM.RRRR” w tekście albo ``None``."""

    if not isinstance(text, str):
        return None
    match = _DATE_RE.search(text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _period_year(text: Any) -> Optional[int]:
    """Rok obrotowy z „OD 01.01.2025 DO 31.12.2025” — rok daty końcowej."""

    if not isinstance(text, str):
        return None
    dates = _DATE_RE.findall(text)
    if not dates:
        return None
    return int(dates[-1][2])


def _active(items: Any) -> list[dict[str, Any]]:
    """Pozycje działu bez wykreślenia (``nrWpisuWykr``)."""

    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and "nrWpisuWykr" not in item]


def _last_value(items: Any, key: str) -> Optional[str]:
    active = _active(items)
    if not active:
        return None
    value = active[-1].get(key)
    return str(value) if value is not None else None


def _positions(groups: Any) -> list[dict[str, Any]]:
    """Wzmianki i zmiany statutu: lista grup ``{"pozycja": [...]}`` → płaska lista."""

    out: list[dict[str, Any]] = []
    if not isinstance(groups, list):
        return out
    for group in groups:
        if isinstance(group, dict) and isinstance(group.get("pozycja"), list):
            out.extend(p for p in group["pozycja"] if isinstance(p, dict))
        elif isinstance(group, dict):
            out.append(group)
    return out


def _entry_no(item: dict[str, Any]) -> Optional[int]:
    raw = item.get("nrWpisuWprow")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _member_active(member: Any) -> bool:
    if not isinstance(member, dict):
        return False
    for values in member.values():
        if isinstance(values, list) and values and all(
            isinstance(v, dict) and "nrWpisuWykr" in v for v in values
        ):
            return False
    return True


@dataclass(frozen=True)
class KrsEntry:
    number: int
    day: Optional[date]
    description: str
    court: str


@dataclass(frozen=True)
class KrsFiling:
    year: int
    kind: str  # financial_statement | activity_report | audit_opinion | approval
    filed_on: Optional[date]
    entry_no: Optional[int]


@dataclass(frozen=True)
class StatuteChange:
    entry_no: Optional[int]
    act_date: Optional[date]
    text: str


@dataclass
class KrsSummary:
    krs: str
    name: Optional[str]
    capital: Optional[str]
    shares: Optional[str]
    entries: list[KrsEntry] = field(default_factory=list)
    filings: list[KrsFiling] = field(default_factory=list)
    statute_changes: list[StatuteChange] = field(default_factory=list)
    management_functions: list[str] = field(default_factory=list)
    supervisory_count: int = 0

    @property
    def last_entry(self) -> Optional[KrsEntry]:
        return max(self.entries, key=lambda e: e.number) if self.entries else None


_FILING_KEYS: dict[str, str] = {
    "wzmiankaOZlozeniuRocznegoSprawozdaniaFinansowego": "financial_statement",
    "wzmiankaOZlozeniuSprawozdaniaZDzialalnosci": "activity_report",
    "wzmiankaOZlozeniuOpiniiBieglegoRewidentaSprawozdaniaZBadania": "audit_opinion",
    "wzmiankaOZlozeniuUchwalyPostanowieniaOZatwierdzeniuRocznegoSprawozdaniaFinansowego": "approval",
}


def parse_odpis(payload: dict[str, Any]) -> KrsSummary:
    """Odpis pełny KRS → to, co pokazuje Rada. Brak gałęzi = pusta lista."""

    odpis = payload.get("odpis") if isinstance(payload.get("odpis"), dict) else payload
    header = odpis.get("naglowekP") or {}
    dane = odpis.get("dane") or {}
    d1 = dane.get("dzial1") or {}
    d2 = dane.get("dzial2") or {}
    d3 = dane.get("dzial3") or {}

    entries: list[KrsEntry] = []
    for raw in header.get("wpis") or []:
        if not isinstance(raw, dict):
            continue
        try:
            number = int(raw.get("numerWpisu"))
        except (TypeError, ValueError):
            continue
        entries.append(
            KrsEntry(
                number=number,
                day=parse_pl_date(raw.get("dataWpisu")),
                description=str(raw.get("opis") or ""),
                court=str(raw.get("oznaczenieSaduDokonujacegoWpisu") or ""),
            )
        )
    entry_days = {e.number: e.day for e in entries}

    subject = d1.get("danePodmiotu") or {}
    capital = d1.get("kapital") or {}
    capital_value = None
    capital_rows = _active(capital.get("wysokoscKapitaluZakladowego"))
    if capital_rows:
        row = capital_rows[-1]
        capital_value = f"{row.get('wartosc', '')} {row.get('waluta', '')}".strip() or None

    filings: list[KrsFiling] = []
    wzmianki = d3.get("wzmiankiOZlozonychDokumentach") or {}
    for key, kind in _FILING_KEYS.items():
        for item in _positions(wzmianki.get(key)):
            year = _period_year(item.get("zaOkresOdDo"))
            if year is None:
                continue
            entry_no = _entry_no(item)
            filed_on = parse_pl_date(item.get("dataZlozenia")) or entry_days.get(entry_no or -1)
            filings.append(KrsFiling(year=year, kind=kind, filed_on=filed_on, entry_no=entry_no))

    statute: list[StatuteChange] = []
    umowa = d1.get("umowaStatut") or {}
    for item in _positions(umowa.get("informacjaOZawarciuZmianieUmowyStatutu")):
        text = str(item.get("zawarcieZmianaUmowyStatutu") or "").strip()
        if not text:
            continue
        statute.append(
            StatuteChange(entry_no=_entry_no(item), act_date=parse_pl_date(text), text=text)
        )

    functions: list[str] = []
    for organ in d2.get("reprezentacja") or []:
        for member in (organ or {}).get("sklad") or []:
            if not _member_active(member):
                continue
            functions.append(_last_value(member.get("funkcjaWOrganie"), "funkcjaWOrganie") or "CZŁONEK")
    supervisory = 0
    for organ in d2.get("organNadzoru") or []:
        supervisory += sum(1 for m in (organ or {}).get("sklad") or [] if _member_active(m))

    return KrsSummary(
        krs=company_krs(),
        name=_last_value(subject.get("nazwa"), "nazwa"),
        capital=capital_value,
        shares=_last_value(capital.get("lacznaLiczbaAkcjiUdzialow"), "lacznaLiczbaAkcjiUdzialow"),
        entries=entries,
        filings=filings,
        statute_changes=statute,
        management_functions=functions,
        supervisory_count=supervisory,
    )


# ── wiersze rejestru z wzmianek ─────────────────────────────────────────────

_FILING_TITLES: dict[str, str] = {
    "financial_statement": "Sprawozdanie finansowe za {year}",
    "activity_report": "Sprawozdanie Zarządu z działalności za {year}",
    "audit_opinion": "Sprawozdanie biegłego rewidenta z badania za {year}",
    "approval": "Uchwała WZA — zatwierdzenie sprawozdania finansowego za {year}",
}


@dataclass(frozen=True)
class DocumentSeed:
    krs_key: str
    category: str
    organ: Optional[str]
    title: str
    doc_date: Optional[date]
    entry_no: Optional[int]
    entry_date: Optional[date]


def document_seeds(summary: KrsSummary) -> list[DocumentSeed]:
    """Wiersze, które automat zakłada w rejestrze (idempotentnie po ``krs_key``)."""

    entry_days = {e.number: e.day for e in summary.entries}
    seeds: list[DocumentSeed] = []
    for filing in summary.filings:
        entry_date = entry_days.get(filing.entry_no or -1)
        is_approval = filing.kind == "approval"
        seeds.append(
            DocumentSeed(
                krs_key=f"{filing.kind}:{filing.year}",
                category="resolution_general" if is_approval else "financial_statement",
                organ="general" if is_approval else None,
                title=_FILING_TITLES[filing.kind].format(year=filing.year),
                doc_date=None if is_approval else filing.filed_on,
                entry_no=filing.entry_no,
                entry_date=entry_date,
            )
        )
    for change in summary.statute_changes:
        if change.entry_no is None:
            continue
        seeds.append(
            DocumentSeed(
                krs_key=f"statute:{change.entry_no}",
                category="statute",
                organ="general",
                title=f"Zmiana statutu (wpis {change.entry_no})",
                doc_date=change.act_date,
                entry_no=change.entry_no,
                entry_date=entry_days.get(change.entry_no),
            )
        )
    return seeds


def missing_filings(summary: KrsSummary) -> list[dict[str, Any]]:
    """Lata, w których jest sprawozdanie, a brakuje którejś wzmianki."""

    by_year: dict[int, set[str]] = {}
    for filing in summary.filings:
        by_year.setdefault(filing.year, set()).add(filing.kind)
    out = []
    for year in sorted(by_year, reverse=True):
        kinds = by_year[year]
        if "financial_statement" not in kinds:
            continue
        missing = [k for k in _FILING_TITLES if k not in kinds]
        if missing:
            out.append({"year": year, "missing": missing})
    return out


# ── pobranie i zapis ─────────────────────────────────────────────────────────


async def fetch_full_extract(krs: str) -> dict[str, Any]:
    """Odpis pełny (rejestr P). Ponawia przy przerwie sieci i 5xx; 4xx = błąd."""

    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"Accept": "application/json", "User-Agent": "NEXUS-board-krs"},
    ) as client:
        for _ in range(ATTEMPTS):
            try:
                resp = await client.get(
                    f"{KRS_BASE}/api/krs/OdpisPelny/{krs}",
                    params={"rejestr": "P", "format": "json"},
                )
            except httpx.HTTPError as exc:
                last_error = exc
                continue
            if resp.status_code >= 500:
                last_error = RuntimeError(f"KRS {resp.status_code}")
                continue
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("KRS: odpowiedź nie jest obiektem")
            return data
    raise RuntimeError("KRS niedostępny") from last_error


def payload_sha(payload: dict[str, Any]) -> str:
    """Skrót treści odpisu bez znacznika czasu wydruku (zmienia się co pobranie)."""

    odpis = payload.get("odpis") if isinstance(payload.get("odpis"), dict) else payload
    stable = {k: v for k, v in odpis.items() if k != "naglowekA"}
    header = odpis.get("naglowekP")
    if isinstance(header, dict):
        stable["naglowekP"] = {
            k: v for k, v in header.items() if k not in {"stanZDnia", "dataCzasOdpisu"}
        }
    blob = json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class SyncResult:
    snapshot_id: int
    changed: bool
    new_entries: list[KrsEntry]
    documents_created: int


async def latest_snapshot(db: AsyncSession, krs: str) -> Optional[BoardKrsSnapshot]:
    return (
        await db.execute(
            select(BoardKrsSnapshot)
            .where(BoardKrsSnapshot.krs == krs)
            .order_by(BoardKrsSnapshot.fetched_at.desc(), BoardKrsSnapshot.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def store_extract(db: AsyncSession, payload: dict[str, Any]) -> SyncResult:
    """Zapis odpisu (nowy wiersz tylko przy zmianie) i wiersze rejestru z wzmianek."""

    krs = company_krs()
    summary = parse_odpis(payload)
    sha = payload_sha(payload)
    now = datetime.now(timezone.utc)
    previous = await latest_snapshot(db, krs)
    previous_last = previous.last_entry_no if previous else None

    same = (
        await db.execute(
            select(BoardKrsSnapshot).where(
                BoardKrsSnapshot.krs == krs, BoardKrsSnapshot.sha256 == sha
            )
        )
    ).scalar_one_or_none()
    last = summary.last_entry
    if same is not None:
        same.checked_at = now
        snapshot = same
        changed = False
    else:
        snapshot = BoardKrsSnapshot(
            krs=krs,
            sha256=sha,
            entries_count=len(summary.entries),
            last_entry_no=last.number if last else None,
            last_entry_date=last.day if last else None,
            payload=payload,
            fetched_at=now,
            checked_at=now,
        )
        db.add(snapshot)
        changed = True
    await db.flush()

    existing = set(
        (
            await db.execute(
                select(BoardDocument.krs_key).where(BoardDocument.krs_key.is_not(None))
            )
        ).scalars()
    )
    created = 0
    for seed in document_seeds(summary):
        if seed.krs_key in existing:
            continue
        db.add(
            BoardDocument(
                category=seed.category,
                organ=seed.organ,
                title=seed.title,
                doc_date=seed.doc_date,
                source="krs",
                krs_key=seed.krs_key,
                krs_entry_no=seed.entry_no,
                krs_entry_date=seed.entry_date,
            )
        )
        created += 1
    await db.flush()

    new_entries = (
        [e for e in summary.entries if e.number > previous_last]
        if previous_last is not None
        else []
    )
    return SyncResult(
        snapshot_id=snapshot.id,
        changed=changed,
        new_entries=sorted(new_entries, key=lambda e: e.number),
        documents_created=created,
    )
