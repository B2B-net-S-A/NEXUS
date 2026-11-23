"""Baza wiedzy oceny potencjału: co wiemy o sobie (oferta, gwarancje) i referencje.

Decyzja Artura z 23.11.2026: baza nie siedzi w prompcie ani w kodzie, tylko
w NEXUSIE, a edytuje ją każdy z „Sprzedaż: edycja” (prowadzi ją Sprzedaż).
Leży w ``app_settings`` pod kluczem ``sales_potential_knowledge``, bez migracji,
jak pauza botów. Repo i logi Actions są publiczne, więc w kodzie nie ma treści
bazy, nazw klientów ani podpisów listów; wkleja je człowiek na ekranie
Sprzedaż → Leady → Boty → Baza wiedzy.

Model oceny dostaje referencje z numerami i odsyła tylko numery: tekst zakresu
pokazuje ekran prosto z bazy, więc model nie dopisze referencji zakresu, którego
w bazie nie ma. Podpis listu (osoba) nie idzie do modelu.

Reguły: ``docs/claude/sprzedaz/ocena-potencjalu.md``.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.contract import Contract, ContractStatus
from app.services.client_duplicates import load_client_name_index
from app.services.company_names import normalize_company_name

KEY = "sales_potential_knowledge"
MAX_OFFER = 30_000
MAX_REFERENCES = 150
MAX_HISTORY = 30
#: List bez daty ważności liczy się jako świeży przez rok od daty listu.
LETTER_FRESH = timedelta(days=365)

ReferenceKind = Literal["list", "realizacja", "logo"]
KIND_LABELS = {"list": "list", "realizacja": "realizacja", "logo": "logo"}


def _line(value: Any) -> str:
    """Jedna linia bez znaków sterujących i nadmiarowych spacji."""

    return " ".join(str(value or "").replace("\x00", "").split())


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Numer referencji; nadaje go NEXUS, model odsyła tylko ten numer.
    id: str = Field(default="", max_length=16)
    client: str = Field(min_length=1, max_length=120)
    kind: ReferenceKind = "logo"
    sectors: list[str] = Field(default_factory=list, max_length=6)
    services: list[str] = Field(default_factory=list, max_length=8)
    scope: str = Field(default="", max_length=600)
    since: str = Field(default="", max_length=60)
    letter_date: Optional[date] = None
    valid_until: Optional[date] = None
    #: Kto podpisał list (stanowisko, osoba). Zostaje w NEXUSIE, do modelu nie idzie.
    signed_by: str = Field(default="", max_length=160)
    quote: str = Field(default="", max_length=400)
    #: Referencję wolno wskazać w przetargu publicznym.
    public_tender: bool = False
    note: str = Field(default="", max_length=300)

    @field_validator(
        "client", "scope", "since", "signed_by", "quote", "note", mode="before"
    )
    @classmethod
    def _clean(cls, value: Any) -> str:
        return _line(value)

    @field_validator("sectors", "services", mode="before")
    @classmethod
    def _tags(cls, value: Any) -> list[str]:
        items = value.split(",") if isinstance(value, str) else (value or [])
        out: list[str] = []
        for item in items:
            text = _line(item)[:60]
            if text and text.casefold() not in {o.casefold() for o in out}:
                out.append(text)
        return out


class KnowledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer: str = Field(default="", max_length=MAX_OFFER)
    references: list[Reference] = Field(default_factory=list, max_length=MAX_REFERENCES)

    @field_validator("offer", mode="before")
    @classmethod
    def _offer(cls, value: Any) -> str:
        return str(value or "").replace("\x00", "").strip()


@dataclass(frozen=True)
class Knowledge:
    offer: str
    references: list[Reference]
    history: list[dict[str, Any]]
    updated_at: Optional[datetime]
    updated_by: Optional[int]

    @property
    def empty(self) -> bool:
        return not self.offer and not self.references


def _parse(value: Any) -> tuple[KnowledgeIn, list[dict[str, Any]]]:
    data = value if isinstance(value, dict) else {}
    refs = []
    for raw in data.get("references") or []:
        try:
            refs.append(Reference.model_validate(raw))
        except ValueError:
            continue  # zepsuty wiersz nie może zablokować całej bazy
    base = KnowledgeIn(offer=str(data.get("offer") or "")[:MAX_OFFER], references=refs)
    history = [h for h in data.get("history") or [] if isinstance(h, dict)]
    return base, history[:MAX_HISTORY]


async def load(db: AsyncSession) -> Knowledge:
    row = await db.get(AppSetting, KEY)
    base, history = _parse(row.value if row is not None else None)
    return Knowledge(
        offer=base.offer,
        references=base.references,
        history=history,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
    )


def _with_ids(references: list[Reference]) -> list[Reference]:
    """Numer zostaje przy referencji przez edycje; nowa i zdublowana dostaje nowy."""

    seen: set[str] = set()
    out: list[Reference] = []
    for ref in references:
        ref_id = ref.id if re.fullmatch(r"[a-z0-9]{4,16}", ref.id or "") else ""
        while not ref_id or ref_id in seen:
            ref_id = secrets.token_hex(4)
        seen.add(ref_id)
        out.append(ref.model_copy(update={"id": ref_id}))
    return out


def change_summary(before: KnowledgeIn, after: KnowledgeIn) -> str:
    """Krótki opis zmiany do historii: bez treści, same liczby i nazwy pól."""

    parts: list[str] = []
    if before.offer != after.offer:
        parts.append("opis oferty")
    old = {r.id: r for r in before.references}
    new = {r.id: r for r in after.references}
    added = len(new.keys() - old.keys())
    removed = len(old.keys() - new.keys())
    changed = sum(1 for key in new.keys() & old.keys() if new[key] != old[key])
    if added:
        parts.append(f"dodane referencje: {added}")
    if removed:
        parts.append(f"usunięte referencje: {removed}")
    if changed:
        parts.append(f"zmienione referencje: {changed}")
    return ", ".join(parts) or "bez zmian"


async def save(
    db: AsyncSession,
    payload: KnowledgeIn,
    *,
    user_id: int,
    user_name: str,
    now: Optional[datetime] = None,
) -> Knowledge:
    """Zapisz całą bazę (ekran wysyła całość); commit robi wywołujący."""

    moment = now or datetime.now(timezone.utc)
    row = await db.get(AppSetting, KEY, with_for_update=True)
    before, history = _parse(row.value if row is not None else None)
    after = KnowledgeIn(offer=payload.offer, references=_with_ids(payload.references))
    summary = change_summary(before, after)
    if summary != "bez zmian":
        history = [
            {
                "at": moment.isoformat(),
                "by": user_id,
                "by_name": user_name,
                "summary": summary,
            },
            *history,
        ][:MAX_HISTORY]
    value = {
        "offer": after.offer,
        "references": [r.model_dump(mode="json") for r in after.references],
        "history": history,
    }
    if row is None:
        db.add(AppSetting(key=KEY, value=value, updated_by=user_id))
    else:
        row.value = value
        row.updated_by = user_id
    return Knowledge(
        offer=after.offer,
        references=after.references,
        history=history,
        updated_at=moment,
        updated_by=user_id,
    )


def is_fresh(ref: Reference, today: date) -> Optional[bool]:
    """Czy list referencyjny jest aktualny; ``None`` dla realizacji i logo."""

    if ref.kind != "list" or ref.letter_date is None:
        return None
    if ref.valid_until is not None:
        return ref.valid_until >= today
    return ref.letter_date >= today - LETTER_FRESH


def for_model(knowledge: Knowledge, today: date) -> dict[str, Any]:
    """Co z bazy dostaje model oceny: bez podpisów, notatek i dat ważności wprost."""

    return {
        "o_nas": knowledge.offer,
        "referencje": [
            {
                "nr": ref.id,
                "klient": ref.client,
                "typ": ref.kind,
                "branze": ref.sectors,
                "uslugi": ref.services,
                "zakres": ref.scope,
                "od": ref.since,
                "list_aktualny": is_fresh(ref, today),
                "cytat": ref.quote,
                "do_przetargow": ref.public_tender,
            }
            for ref in knowledge.references
        ],
    }


def name_variants(client: str) -> list[str]:
    """„Telko Alfa (Plus)” → też „Telko Alfa”; „Biuro Beta / Gamma Info” → obie nazwy."""

    base = re.sub(r"\s*\(.*?\)\s*", " ", client).strip()
    parts = [part.strip() for part in re.split(r"\s+/\s+", base) if part.strip()]
    return list(dict.fromkeys([client, base, *parts]))


async def active_contracts_by_reference(
    db: AsyncSession, references: list[Reference]
) -> dict[str, Optional[int]]:
    """Aktywne kontrakty klienta referencji w NEXUSIE; ``None`` = brak takiego klienta.

    Dopasowanie po nazwie jak bramka klienta (nazwa, nazwa wyświetlana, prawna
    i aliasy). Liczba ma pokazać rozjazd bazy z NEXUSEM, nie rozliczać klienta.
    """

    if not references:
        return {}
    index = await load_client_name_index(db)
    ids_by_ref = {
        ref.id: {
            cid
            for name in name_variants(ref.client)
            for cid in index.ids_by_key.get(normalize_company_name(name), ())
        }
        for ref in references
    }
    all_ids = sorted({cid for ids in ids_by_ref.values() for cid in ids})
    counts: dict[int, int] = {}
    if all_ids:
        rows = await db.execute(
            select(Contract.client_id, func.count(Contract.id))
            .where(
                Contract.client_id.in_(all_ids),
                Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
            )
            .group_by(Contract.client_id)
        )
        counts = {int(cid): int(n) for cid, n in rows.all()}
    return {
        ref_id: (sum(counts.get(cid, 0) for cid in ids) if ids else None)
        for ref_id, ids in ids_by_ref.items()
    }


# ── Import tabeli z dokumentu (np. „Pisemne listy referencyjne”) ───────────────

_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_COLUMNS: dict[str, tuple[str, ...]] = {
    "client": ("klient",),
    "sectors": ("sektor", "branża", "branza"),
    "scope": ("zakres",),
    "since": ("współpraca od", "wspolpraca od", "od kiedy"),
    "signed_by": ("podpisał", "podpisal", "podpis"),
    "letter_date": ("data listu", "data"),
    "kind": ("typ",),
}
_KIND_WORDS = {"list": "list", "realizacja": "realizacja", "logo": "logo"}


def _date(text: str) -> Optional[date]:
    match = _DATE.search(text or "")
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _months_valid(text: str) -> Optional[int]:
    match = re.search(r"ważn\w*\s+(\d{1,2})\s*mies", text or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    for last in (31, 30, 29, 28):
        try:
            return date(year, month, min(day.day, last))
        except ValueError:
            continue
    return day


def parse_table(text: str, *, default_kind: ReferenceKind = "list") -> list[Reference]:
    """Wiersze tabeli Markdown (``| Klient | Sektor | … |``) jako referencje.

    Kolumny rozpoznaje po nagłówku; kolejność i brakujące kolumny nie szkodzą.
    „(ważny 12 mies.)” przy dacie listu daje datę ważności. Wiersz bez klienta
    odpada. Zwraca referencje bez numerów: numer nadaje ``save``.
    """

    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in (text or "").splitlines()
        if line.strip().startswith("|")
    ]
    if not rows:
        return []
    header = [cell.casefold() for cell in rows[0]]
    position: dict[str, int] = {}
    for field, names in _COLUMNS.items():
        for index, cell in enumerate(header):
            if field not in position and any(cell.startswith(name) for name in names):
                position[field] = index
    if "client" not in position:
        return []
    out: list[Reference] = []
    for cells in rows[1:]:
        if all(set(cell) <= set("-: ") for cell in cells):
            continue  # linia oddzielająca nagłówek

        def cell(field: str) -> str:
            index = position.get(field)
            return cells[index] if index is not None and index < len(cells) else ""

        client = _line(cell("client"))
        if not client or client in {"–", "-"}:
            continue
        raw_date = cell("letter_date")
        letter = _date(raw_date)
        months = _months_valid(raw_date)
        kind_text = cell("kind").casefold()
        kind = next(
            (value for word, value in _KIND_WORDS.items() if word in kind_text),
            default_kind,
        )
        try:
            out.append(
                Reference(
                    client=client[:120],
                    kind=kind,  # type: ignore[arg-type]
                    sectors=[
                        s for s in re.split(r"[/,]", cell("sectors")) if s.strip()
                    ],
                    scope=cell("scope")[:600],
                    since=_line(cell("since")).strip("–- ")[:60],
                    signed_by=cell("signed_by")[:160],
                    letter_date=letter if kind == "list" else None,
                    valid_until=_add_months(letter, months)
                    if letter and months
                    else None,
                )
            )
        except ValueError:
            continue
        if len(out) >= MAX_REFERENCES:
            break
    return out
