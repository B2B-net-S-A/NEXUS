"""Sprzedaż → „Znamy teraz” i „Kiedyś” dla wielu firm naraz (B3, 10.11.2026).

Lista kont Fabryk IT pokazuje przy każdej firmie liczby z panelu „Kogo znamy”.
Panel liczy jedną firmę jednym skanem kandydatów (ok. 1 s na kopii produkcji),
więc lista 34 kont nie może wołać go per wiersz. Tu jest jeden skan dla
wszystkich firm: prefiltr ``LIKE ANY`` po nazwach wszystkich kart, a relację
osoby z firmą ustala ta sama funkcja co w panelu (``_match_experience``),
osobno dla każdej firmy. Nazwy karty, klient i jego aliasy, umowy „przez nas”
i flagi zatrudnienia składają się tak samo jak w ``lookup_company_people``.

Trzy świadome różnice wobec panelu. Prefiltr patrzy na nazwy firm jednej osoby
naraz (``_scan_filter``), bo przy kilkudziesięciu nazwach rozwijanie każdego
wpisu CV kosztuje dwa razy więcej; łapie co najmniej to samo, a decyzję i tak
podejmuje dopasowanie dokładne. Panel ucina prefiltr do 2000 osób na firmę
i oznacza wynik jako niepełny; tu limit jest wspólny dla całej listy, więc przy
bardzo popularnej nazwie lista może pokazać więcej niż panel. Firma bez nazwy
do dopasowania (za krótka nazwa kanoniczna) ma zera zamiast błędu 422.

Same liczby, bez nazwisk kandydatów, więc to nie jest odczyt do dziennika.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import String, bindparam, func, literal_column, select, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_companies import (
    _MIN_NAME_LEN,
    _STATEMENT_TIMEOUT_MS,
    _active_aliases,
    _client_label_index,
    _client_labels,
    _client_nip_digits,
    _match_experience,
    _normalize_nip,
)
from app.api.sales_company_people import _lookup_names
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.contract import Contract
from app.models.sales import SalesCompany, SalesCompanyAlias
from app.services.company_names import normalize_company_name
from app.services.contract_service import placed_contract_clause
from app.services.polish_ilike import contains_pattern
from app.services.sales import company_aliases

#: Sufit osób z prefiltru dla całej listy. Na kopii z 10.11.2026 34 firmy lejka
#: dają 3913 osób; przekroczenie oznacza wynik jako dolną granicę.
SCAN_ROW_CAP = 20000

# Z wpisu CV wystarczą trzy pola: całe ``experience`` (opisy, technologie) dla
# kilku tysięcy osób to dziesiątki megabajtów na jedno otwarcie listy.
_SLIM_ENTRIES = literal_column(
    "(SELECT jsonb_agg(jsonb_build_object("
    "'company', e.elem->'company', 'start', e.elem->'start', 'end', e.elem->'end')) "
    "FROM jsonb_array_elements("
    "CASE WHEN jsonb_typeof(candidates.experience) = 'array' "
    "THEN candidates.experience ELSE '[]'::jsonb END"
    ") AS e(elem) "
    "WHERE jsonb_typeof(e.elem) = 'object')",
    type_=JSONB,
)


def _scan_filter(names: Iterable[str]):
    """Osoby z którąś z nazw w LinkedInie albo w dowolnym wpisie CV, dla całej listy.

    Jeden ``LIKE ANY`` na osobę: nazwy firm z jej CV idą do porównania jako jeden
    napis (tablica JSON). Na kopii z 10.11.2026 to 1,0 s wobec 1,9 s dla kształtu
    z panelu (``EXISTS`` po wpisach) przy 55 nazwach. Nazwa siedzi w tym napisie
    w zapisie JSON, więc wzorzec dostaje też postać z cudzysłowem po ukośniku.
    Zbiór jest nadzbiorem prefiltru panelu; o relacji decyduje dopasowanie dokładne.
    """

    needles = dict.fromkeys(n.strip().lower() for n in names if n and n.strip())
    patterns = dict.fromkeys(
        contains_pattern(form)
        for needle in needles
        for form in (needle, json.dumps(needle, ensure_ascii=False)[1:-1])
    )
    return text(
        "lower(coalesce(candidates.linkedin_current_company, '') || ' | ' || "
        "coalesce(jsonb_path_query_array("
        "candidates.experience, '$[*].company', '{}', true)::text, '')"
        ") LIKE ANY(:names)"
    ).bindparams(bindparam("names", value=list(patterns), type_=ARRAY(String)))


@dataclass(frozen=True)
class KnownCounts:
    """Kubełki panelu „Kogo znamy”; lista pokazuje ``current`` i ``past``."""

    via_us: int = 0
    current: int = 0
    past: int = 0
    unknown: int = 0


@dataclass(frozen=True)
class KnownPeople:
    counts: dict[int, KnownCounts]
    #: Skan trafił w sufit: liczby są dolną granicą.
    truncated: bool


@dataclass(frozen=True)
class _Card:
    """Nazwy jednej karty firmy, złożone jak w ``_lookup_company_people``."""

    company_id: int
    client_id: Optional[int]
    match_names: frozenset[str]
    prefilter_names: tuple[str, ...]


def _person(candidate_id: int, linkedin_company: Optional[str], entries: Any) -> Any:
    """Kandydat w kształcie, którego oczekuje ``_match_experience``."""

    return SimpleNamespace(
        id=candidate_id,
        linkedin_current_company=linkedin_company,
        linkedin_current_title=None,
        linkedin_current_started_at=None,
        experience=entries if isinstance(entries, list) else [],
    )


async def _cards(db: AsyncSession, companies: Sequence[SalesCompany]) -> list[_Card]:
    linked_ids = {c.client_id for c in companies if c.client_id is not None}
    linked = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    Client.id,
                    Client.name,
                    Client.display_name,
                    Client.merged_into_client_id,
                    Client.deleted_at,
                ).where(Client.id.in_(linked_ids))
            )
        ).all()
    }
    joined: dict[int, list[str]] = defaultdict(list)
    for company_id, alias in (
        await db.execute(
            select(SalesCompanyAlias.company_id, SalesCompanyAlias.alias)
            .where(
                SalesCompanyAlias.company_id.in_([c.id for c in companies]),
                SalesCompanyAlias.status == company_aliases.JOINED,
            )
            .order_by(SalesCompanyAlias.id)
        )
    ).all():
        joined[company_id].append(alias)

    drafts: list[tuple[SalesCompany, dict[str, str], set[str], Optional[int]]] = []
    for company in companies:
        client = linked.get(company.client_id)
        client_name = (client.display_name or client.name) if client else None
        raw_names = [
            name.strip()
            for name in (*_lookup_names(company, client_name), *joined[company.id])
            if name and name.strip()
        ]
        canonical_by_raw = {name: normalize_company_name(name) for name in raw_names}
        canonical_names = {
            name for name in canonical_by_raw.values() if len(name) >= _MIN_NAME_LEN
        }
        if not canonical_names:
            continue
        # Ręczne powiązanie ma pierwszeństwo; scalony albo usunięty klient się nie liczy.
        linked_ok = (
            client is not None
            and client.merged_into_client_id is None
            and client.deleted_at is None
        )
        drafts.append(
            (
                company,
                canonical_by_raw,
                canonical_names,
                client.id if linked_ok else None,
            )
        )

    nips = {
        digits
        for company, _, _, client_id in drafts
        if client_id is None and (digits := _normalize_nip(company.nip))
    }
    by_nip: dict[str, int] = {}
    if nips:
        digits_column = _client_nip_digits()
        for row in (
            await db.execute(
                _client_labels()
                .add_columns(digits_column.label("nip_digits"))
                .where(digits_column.in_(nips))
            )
        ).all():
            by_nip.setdefault(row.nip_digits, row.id)
    by_name = await _client_label_index(db, _client_labels())

    resolved: list[tuple[SalesCompany, dict[str, str], set[str], Optional[int]]] = []
    for company, canonical_by_raw, canonical_names, client_id in drafts:
        if client_id is None:
            client_id = by_nip.get(_normalize_nip(company.nip))
        if client_id is None:
            client_id = next(
                (cid for cid, _, names in by_name if names & canonical_names), None
            )
        resolved.append((company, canonical_by_raw, canonical_names, client_id))

    client_ids = {client_id for *_, client_id in resolved if client_id is not None}
    labels: dict[int, tuple[Optional[str], ...]] = {}
    aliases: dict[int, list[str]] = {}
    if client_ids:
        labels = {
            row.id: (row.name, row.legal_name, row.display_name)
            for row in (
                await db.execute(
                    select(
                        Client.id, Client.name, Client.legal_name, Client.display_name
                    ).where(Client.id.in_(client_ids))
                )
            ).all()
        }
        aliases = await _active_aliases(db)

    cards = []
    for company, canonical_by_raw, canonical_names, client_id in resolved:
        match_names = set(canonical_names)
        raw_by_canonical = dict(canonical_by_raw)
        if client_id is not None:
            # Klient poszerza dopasowanie o swoje nazwy: „BRE Bank” to ten sam mBank.
            for raw in (*labels.get(client_id, ()), *aliases.get(client_id, ())):
                if not raw:
                    continue
                canonical = normalize_company_name(raw)
                if len(canonical) >= _MIN_NAME_LEN:
                    match_names.add(canonical)
                    raw_by_canonical.setdefault(raw, canonical)
        cards.append(
            _Card(
                company_id=company.id,
                client_id=client_id,
                match_names=frozenset(match_names),
                # Surowa pisownia zostaje w prefiltrze: SQL-owe ``lower()`` nie
                # zdejmuje ogonków, więc „Żabka” w CV pasuje tylko do niej.
                prefilter_names=(
                    *sorted(match_names),
                    *(
                        raw
                        for raw, canonical in raw_by_canonical.items()
                        if canonical in match_names
                    ),
                ),
            )
        )
    return cards


async def _placed(db: AsyncSession, client_ids: set[int]) -> dict[int, set[int]]:
    """Osoby umieszczone u klienta przez nas: klient → kandydaci."""

    placed: dict[int, set[int]] = defaultdict(set)
    if not client_ids:
        return placed
    for client_id, candidate_id in (
        await db.execute(
            select(Contract.client_id, Contract.candidate_id)
            .where(
                Contract.client_id.in_(client_ids),
                Contract.candidate_id.is_not(None),
                placed_contract_clause(),
            )
            .distinct()
        )
    ).all():
        placed[client_id].add(candidate_id)
    return placed


async def _flagged(
    db: AsyncSession, client_ids: set[int]
) -> dict[int, dict[int, bool]]:
    """Flagi „zatrudniony u klienta”: klient → kandydat → czy któraś jest aktywna."""

    flagged: dict[int, dict[int, bool]] = defaultdict(dict)
    if not client_ids:
        return flagged
    for client_id, candidate_id, active in (
        await db.execute(
            select(
                CandidateConflict.client_id,
                CandidateConflict.candidate_id,
                CandidateConflict.active,
            ).where(
                CandidateConflict.client_id.in_(client_ids),
                CandidateConflict.type == ConflictType.current_employment,
            )
        )
    ).all():
        people = flagged[client_id]
        people[candidate_id] = people.get(candidate_id, False) or bool(active)
    return flagged


def _by_canonical_name(people: Iterable[Any]) -> dict[str, list[Any]]:
    """Nazwa kanoniczna → osoby, które mają ją w LinkedInie albo we wpisie CV."""

    canonical: dict[str, str] = {}
    index: dict[str, list[Any]] = defaultdict(list)
    for person in people:
        raw_names = [
            person.linkedin_current_company,
            *(entry.get("company") for entry in person.experience),
        ]
        names = set()
        for raw in raw_names:
            # Stare wiersze mają w polu firmy także liczby i obiekty.
            if isinstance(raw, str) and raw:
                if raw not in canonical:
                    canonical[raw] = normalize_company_name(raw)
                names.add(canonical[raw])
        for name in names:
            index[name].append(person)
    return index


def _count(
    card: _Card,
    by_name: dict[str, list[Any]],
    placed: set[int],
    flagged: dict[int, bool],
) -> KnownCounts:
    """Kubełki jednej firmy, w kolejności panelu: przez nas, CV, sama flaga."""

    counts = {"via_us": len(placed), "current": 0, "past": 0, "unknown": 0}
    reported = set(placed)
    people = {
        person.id: person
        for name in card.match_names
        for person in by_name.get(name, ())
    }
    for person in people.values():
        if person.id in reported:
            continue
        relationship, _ = _match_experience(person, card.match_names)
        if relationship is None:
            continue
        if relationship in ("past", "unknown") and flagged.get(person.id):
            # Klient oznaczył osobę jako zatrudnioną teraz: flaga jest świeższa niż CV.
            relationship = "current"
        counts[relationship] += 1
        reported.add(person.id)
    for candidate_id, active in flagged.items():
        if candidate_id not in reported:
            counts["current" if active else "past"] += 1
    return KnownCounts(**counts)


async def count_known_people(
    db: AsyncSession, companies: Sequence[SalesCompany]
) -> KnownPeople:
    """Liczniki „Kogo znamy” dla każdej z firm; firma bez dopasowania ma zera.

    Jeden skan kandydatów na całą listę pod limitem czasu transakcji; wołający
    zamienia przekroczony limit (``DBAPIError``) na 503, jak panel.
    """

    counts = {company.id: KnownCounts() for company in companies}
    await db.execute(
        select(func.set_config("statement_timeout", str(_STATEMENT_TIMEOUT_MS), True))
    )
    cards = await _cards(
        db,
        [c for c in companies if not company_aliases.is_own_company(c.normalized_name)],
    )
    if not cards:
        return KnownPeople(counts=counts, truncated=False)
    client_ids = {card.client_id for card in cards if card.client_id is not None}
    placed = await _placed(db, client_ids)
    flagged = await _flagged(db, client_ids)
    # Bez sortowania: ucięty wynik i tak jest tylko dolną granicą, a plan bez
    # ``ORDER BY`` czyta tabelę raz, od początku do końca.
    rows = (
        await db.execute(
            select(
                Candidate.id,
                Candidate.linkedin_current_company,
                _SLIM_ENTRIES.label("entries"),
            )
            .where(_scan_filter(n for card in cards for n in card.prefilter_names))
            .limit(SCAN_ROW_CAP + 1)
        )
    ).all()
    truncated = len(rows) > SCAN_ROW_CAP
    by_name = _by_canonical_name(
        _person(row.id, row.linkedin_current_company, row.entries)
        for row in rows[:SCAN_ROW_CAP]
    )
    for card in cards:
        counts[card.company_id] = _count(
            card,
            by_name,
            placed.get(card.client_id, set()),
            flagged.get(card.client_id, {}),
        )
    return KnownPeople(counts=counts, truncated=truncated)
