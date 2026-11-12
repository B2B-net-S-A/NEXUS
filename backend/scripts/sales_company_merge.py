#!/usr/bin/env python3
"""Jednorazowe scalenie zdublowanych kart firm Sprzedaży i uzupełnienie domen (B6).

Zakres: firmy z szansą w lejku „Fabryki IT” (także w archiwum), firmy z listy
researchu centrów IT (``--names-file``, jedna nazwa w wierszu; plik nie trafia do
repo) i karty wskazane po id (``--company-ids``, na produkcji zamiast pliku z nazwami).

Domyślnie NA SUCHO: transakcja ``READ ONLY``, raport, wycofanie. ``--apply`` zapisuje
w jednej transakcji i tylko z licznikami zaakceptowanymi przez Artura
(``--expect-merge``, ``--expect-domains``), więc dane, które zmieniły się od
akceptacji, kończą bieg bez zapisu. Drugi bieg nie ma już czego scalić.

Co robi:

1. dla każdej firmy z zakresu składa grupę kart o tej samej nazwie kanonicznej albo
   NIP-ie i wybiera kartę docelową: powiązana z klientem NEXUSA, potem z kontem
   w lejku, potem z największą liczbą kontaktów, potem z największą historią,
   na końcu najstarsza;
2. grupę jednoznaczną scala przez ``services/sales/merge.py`` (wpis w historii szans,
   źródło idzie do archiwum, nic nie jest kasowane). Grupa z różnymi NIP-ami, dwoma
   klientami, relacją matka–córka, różnymi domenami poczty albo wspólnym NIP-em przy
   różnych nazwach jest tylko wypisana jako „do decyzji”: dwie spółki o tej samej
   nazwie istnieją naprawdę;
3. karty tej samej marki o innej nazwie („… Bank Polska”, „… Leasing”) wypisuje obok
   grupy jako podobne i nigdy nie scala ich sam. Decyzję Artura wykonuje
   ``--decide DOCELOWA:ŹRÓDŁO[,ŹRÓDŁO]`` (same id);
4. liczy nazwy wchłoniętych kart, które scalenie dopisze do „Innych nazw z CV”
   jako dołączone (``merge.py``: „Kogo znamy” dopasowuje osoby dokładnie po nazwie),
   i po zapisie sprawdza, że są przy karcie docelowej;
5. proponuje domenę karty docelowej: najczęstsza firmowa domena z adresów kontaktów
   (bez darmowych skrzynek), w drugiej kolejności pole strony www. Domena już wpisana
   zostaje. Propozycja słaba albo wspólna z inną firmą nie jest zapisywana bez
   ``--accept-domain ID[,ID]``.

Grupa nie jest scalana, gdy scalenie przesunęłoby dotyk otwartej szansy (``touch.py``:
aktywność firmy jest dotykiem jej szans), zgubiłoby nazwę dołączoną na karcie albo
połączyło karty dwóch różnych klientów. Po zapisie dotyk jest sprawdzany jeszcze raz;
różnica wycofuje całą transakcję (kod 3).

Uruchomienie (z ``backend/``, baza z ``DATABASE_URL``)::

    python -m scripts.sales_company_merge --names-file ~/lista.txt --list-out ~/lista.json
    python -m scripts.sales_company_merge --apply --actor-id 82 \
        --expect-merge 12 --expect-domains 30

Raport na standardowym wyjściu to same liczby: repo i logi Actions są publiczne. Nazwy
kart, liczniki i propozycje domen idą do pliku ``--list-out`` poza repozytorium.

``--lock /tmp/nexus-sales-company-merge-<liczba>`` jest dla zadania Coolify, które
odpala komendę co minutę: pierwsze odpalenie zakłada katalog i pracuje, każde kolejne
kończy się kodem 4 bez biegu. Ślad błędu zostaje w ``<lock>/error.log`` w kontenerze.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyAlias,
    SalesContact,
    SalesFile,
    SalesOpportunity,
    SalesPipeline,
)
from app.models.user import User, UserRole
from app.services.company_names import normalize_company_name
from app.services.m365.matcher import PUBLIC_EMAIL_DOMAINS
from app.services.sales.company_aliases import JOINED, brand_of
from app.services.sales.decision_map import IT_FACTORIES_PIPELINE_KEY
from app.services.sales.merge import merge_companies, names_to_join, outlook_copy
from app.services.sales.task_scope import live_opportunity
from app.services.sales.touch import last_touch_at, touched_at

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2
EXIT_RESULT_DIFFERS = 3
EXIT_ALREADY_RAN = 4

#: Marka krótsza niż to nie wyznacza rodziny kart („PGE” tak, „P4” nie).
MIN_BRAND_LEN = 3
#: Domena z adresów kontaktów jest pewna od tylu adresów i od połowy firmowych.
STRONG_DOMAIN_SUPPORT = 2
STRONG_DOMAIN_SHARE = 0.5

SEED_PIPELINE = "lejek"
SEED_NAMES = "lista"
SEED_IDS = "id"

#: Domena z pola, które bywa adresem strony; to samo co ``COMPANY_DOMAIN_SQL``.
_HOST = re.compile(r"^([a-z]+://)?(www\.)?([^/:?#]+).*$")


class Refused(Exception):
    """Warunek biegu niespełniony; nic nie zostało zapisane."""


class ResultDiffers(Exception):
    """Po zapisie dotyk szansy albo liczniki wyszły inne niż w planie; wycofane."""


@dataclass(frozen=True)
class Options:
    names_file: Optional[str] = None
    company_ids: tuple[int, ...] = ()
    decide: tuple[tuple[int, tuple[int, ...]], ...] = ()
    accept_domain: tuple[int, ...] = ()
    list_out: Optional[str] = None
    apply: bool = False
    expect_merge: Optional[int] = None
    expect_domains: Optional[int] = None
    actor_id: Optional[int] = None


@dataclass(frozen=True)
class Card:
    id: int
    name: str
    legal_name: Optional[str]
    key: str
    nip: Optional[str]
    client_id: Optional[int]
    parent_id: Optional[int]
    domain: Optional[str]
    website: Optional[str]


@dataclass
class Stats:
    contacts: int = 0
    opportunities: int = 0
    open_opportunities: int = 0
    factory_opportunities: int = 0
    activities: int = 0
    files: int = 0
    #: Firmowe domeny z adresów kontaktów karty.
    mail_domains: Counter[str] = field(default_factory=Counter)


@dataclass
class Group:
    """Karty o tej samej nazwie kanonicznej albo NIP-ie wokół firmy z zakresu."""

    cards: list[Card]
    seeds: set[str]
    reasons: list[str] = field(default_factory=list)
    #: Karty tej samej marki o innej nazwie: (karta, „wariant” | „inna_spolka”).
    similar: list[tuple[Card, str]] = field(default_factory=list)
    target: Optional[Card] = None
    status: str = "pojedyncza"


@dataclass
class Merge:
    target: Card
    sources: list[Card]
    origin: str
    blocked: list[str] = field(default_factory=list)
    #: Nazwy wchłanianych kart do dopisania jako dołączone: (zapis, kanoniczna).
    join: list[tuple[str, str]] = field(default_factory=list)
    moved_touches: int = 0


@dataclass
class DomainPlan:
    card: Card
    current: Optional[str] = None
    proposed: Optional[str] = None
    source: Optional[str] = None
    support: int = 0
    of: int = 0
    status: str = "brak"
    shared_with: list[int] = field(default_factory=list)


@dataclass
class Report:
    mode: str = "dry-run"
    seeds_pipeline: int = 0
    seeds_names: int = 0
    seeds_ids: int = 0
    names_without_card: int = 0
    groups: dict[str, int] = field(default_factory=dict)
    to_decide_reasons: dict[str, int] = field(default_factory=dict)
    blocked_reasons: dict[str, int] = field(default_factory=dict)
    similar_cards: int = 0
    similar_name_variants: int = 0
    to_merge: int = 0
    to_merge_by_origin: dict[str, int] = field(default_factory=dict)
    moving: dict[str, int] = field(default_factory=dict)
    names_to_join: int = 0
    #: Kopie maili i spotkań z Outlooka, które scalenie dołączy do wiersza docelowej.
    outlook_duplicates: int = 0
    domains: dict[str, int] = field(default_factory=dict)
    domains_to_set: int = 0
    merged: int = 0
    names_joined: int = 0
    domains_set: int = 0


@dataclass
class Plan:
    report: Report
    groups: list[Group]
    merges: list[Merge]
    domains: list[DomainPlan]
    stats: dict[int, Stats]
    missing: list[tuple[str, list[tuple[Card, str]]]]


def host_of(value: Optional[str]) -> Optional[str]:
    match = _HOST.match((value or "").strip().lower())
    host = match.group(3) if match else ""
    return host if "." in host else None


def _nip(value: Optional[str]) -> Optional[str]:
    return re.sub(r"\D", "", value or "") or None


def _brand(key: str) -> str:
    """Marka karty; ``normalize_company_name`` nie zdejmuje „S. A” pisanego osobno."""

    return brand_of(re.sub(r" s a$", "", key))


def _cards_query() -> Select[Any]:
    """Karty, na których pracuje skrypt; scalona karta jest w archiwum."""

    return select(
        SalesCompany.id,
        SalesCompany.name,
        SalesCompany.legal_name,
        SalesCompany.normalized_name,
        SalesCompany.nip,
        SalesCompany.client_id,
        SalesCompany.parent_company_id,
        SalesCompany.domain,
        SalesCompany.website_url,
    ).where(SalesCompany.archived_at.is_(None))


async def _load_cards(db: AsyncSession) -> dict[int, Card]:
    return {
        row.id: Card(
            id=row.id,
            name=row.name,
            legal_name=row.legal_name,
            key=row.normalized_name,
            nip=_nip(row.nip),
            client_id=row.client_id,
            parent_id=row.parent_company_id,
            domain=host_of(row.domain),
            website=host_of(row.website_url),
        )
        for row in (await db.execute(_cards_query())).all()
    }


async def _factory_pipeline_id(db: AsyncSession) -> Optional[int]:
    return await db.scalar(
        select(SalesPipeline.id).where(SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY)
    )


async def _load_stats(
    db: AsyncSession, ids: Sequence[int], pipeline_id: Optional[int]
) -> dict[int, Stats]:
    stats = {company_id: Stats() for company_id in ids}
    if not ids:
        return stats
    for name, model in (
        ("contacts", SalesContact),
        ("activities", SalesActivity),
        ("files", SalesFile),
    ):
        rows = await db.execute(
            select(model.company_id, func.count())
            .where(model.company_id.in_(ids))
            .group_by(model.company_id)
        )
        for company_id, count in rows.all():
            setattr(stats[company_id], name, int(count))
    rows = await db.execute(
        select(
            SalesOpportunity.company_id,
            func.count(),
            func.count().filter(live_opportunity()),
            func.count().filter(SalesOpportunity.pipeline_id == pipeline_id),
        )
        .where(SalesOpportunity.company_id.in_(ids))
        .group_by(SalesOpportunity.company_id)
    )
    for company_id, total, live, factory in rows.all():
        stats[company_id].opportunities = int(total)
        stats[company_id].open_opportunities = int(live)
        stats[company_id].factory_opportunities = int(factory)
    mail_domain = func.lower(func.split_part(func.btrim(SalesContact.email), "@", 2))
    rows = await db.execute(
        select(SalesContact.company_id, mail_domain, func.count())
        .where(
            SalesContact.company_id.in_(ids),
            SalesContact.email.like("%@%"),
            SalesContact.archived_at.is_(None),
        )
        .group_by(SalesContact.company_id, mail_domain)
    )
    for company_id, domain, count in rows.all():
        if "." in domain and domain not in PUBLIC_EMAIL_DOMAINS:
            stats[company_id].mail_domains[domain] = int(count)
    return stats


def _read_names(path: Optional[str]) -> list[str]:
    if path is None:
        return []
    try:
        lines = Path(path).expanduser().read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise Refused("--names-file: nie da się odczytać pliku") from exc
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _list_path(value: Optional[str]) -> Optional[Path]:
    """Plik listy z nazwami firm; w repozytorium trafiłby do publicznej historii."""

    if value is None:
        return None
    path = Path(value).expanduser().resolve()
    if any((parent / ".git").exists() for parent in path.parents):
        raise Refused("--list-out: wskaż plik poza repozytorium")
    if not path.parent.is_dir():
        raise Refused("--list-out: katalog nie istnieje")
    return path


def _exact_group(
    seed: int,
    cards: dict[int, Card],
    by_key: dict[str, list[int]],
    by_nip: dict[str, list[int]],
) -> frozenset[int]:
    seen = {seed}
    queue = [seed]
    while queue:
        card = cards[queue.pop()]
        linked = [*by_key.get(card.key, ())]
        if card.nip:
            linked += by_nip.get(card.nip, ())
        for other in linked:
            if other not in seen:
                seen.add(other)
                queue.append(other)
    return frozenset(seen)


def _top_mail_domain(stats: Stats) -> Optional[str]:
    ranked = stats.mail_domains.most_common(1)
    return ranked[0][0] if ranked else None


def _reasons(group: Sequence[Card], stats: dict[int, Stats]) -> list[str]:
    """Dlaczego grupy nie wolno scalić bez decyzji człowieka."""

    reasons = []
    ids = {card.id for card in group}
    if len({card.nip for card in group if card.nip}) > 1:
        reasons.append("rozne_nipy")
    if len({card.client_id for card in group if card.client_id is not None}) > 1:
        reasons.append("dwoch_klientow")
    if any(card.parent_id in ids for card in group):
        reasons.append("matka_i_corka")
    if len({_brand(card.key) for card in group}) > 1:
        # Wspólny NIP przy niepowiązanych nazwach bywa błędem wpisu.
        reasons.append("wspolny_nip_rozne_nazwy")
    mail = {_top_mail_domain(stats[card.id]) for card in group} - {None}
    if len(mail) > 1:
        reasons.append("rozne_domeny_poczty")
    return reasons


def _pick_target(group: Sequence[Card], stats: dict[int, Stats]) -> Card:
    def rank(card: Card) -> tuple[bool, bool, int, int, int]:
        own = stats[card.id]
        return (
            card.client_id is not None,
            own.factory_opportunities > 0,
            own.contacts,
            own.opportunities + own.activities + own.files,
            -card.id,
        )

    return max(group, key=rank)


def _similar(
    brands: set[str], skip: set[int], cards: Iterable[Card]
) -> list[tuple[Card, str]]:
    """Karty tej samej marki o innej nazwie: wariant nazwy albo inna spółka grupy."""

    prefixes = [brand for brand in brands if len(brand) >= MIN_BRAND_LEN]
    found = []
    for card in cards:
        if card.id in skip:
            continue
        if any(card.key == p or card.key.startswith(f"{p} ") for p in prefixes):
            kind = "wariant" if _brand(card.key) in brands else "inna_spolka"
            found.append((card, kind))
    return sorted(found, key=lambda item: (item[0].key, item[0].id))


def _names_to_join(
    merge: Merge, aliases: dict[int, list[tuple[str, str]]]
) -> tuple[list[tuple[str, str]], bool]:
    """Nazwy, które scalenie dopisze, i czy zgubiłoby nazwę dołączoną.

    Odtwarza ``merge.py`` źródło po źródle: decyzje źródła idą za firmą, potem
    jego nazwy (``names_to_join``), a przy tej samej nazwie wygrywa decyzja,
    która już jest przy docelowej (``ON CONFLICT DO NOTHING``).
    """

    state = dict(aliases.get(merge.target.id, ()))
    lost = False
    own = {merge.target.key, normalize_company_name(merge.target.name)}
    legal_name = merge.target.legal_name
    join = []
    for source in merge.sources:
        for canonical, status in aliases.get(source.id, ()):
            kept = state.setdefault(canonical, status)
            lost = lost or (status == JOINED and kept != JOINED)
        legal_name = legal_name or source.legal_name
        covered = {*own, normalize_company_name(legal_name or "")}
        for alias, canonical in names_to_join(
            covered, (source.name, source.legal_name)
        ):
            if canonical in state:
                # „Nie ta firma” przy nazwie karty, którą właśnie mamy wchłonąć.
                lost = lost or state[canonical] != JOINED
                continue
            state[canonical] = JOINED
            join.append((alias, canonical))
    return join, lost


async def _aliases(
    db: AsyncSession, ids: Sequence[int]
) -> dict[int, list[tuple[str, str]]]:
    found: dict[int, list[tuple[str, str]]] = defaultdict(list)
    if not ids:
        return found
    rows = await db.execute(
        select(
            SalesCompanyAlias.company_id,
            SalesCompanyAlias.normalized_alias,
            SalesCompanyAlias.status,
        )
        .where(SalesCompanyAlias.company_id.in_(ids))
        .order_by(SalesCompanyAlias.id)
    )
    for company_id, canonical, status in rows.all():
        found[company_id].append((canonical, status))
    return found


async def _live_touches(
    db: AsyncSession, ids: Sequence[int], now: datetime
) -> dict[int, tuple[int, datetime]]:
    """Otwarta szansa → (firma, ostatni dotyk)."""

    if not ids:
        return {}
    rows = await db.execute(
        select(
            SalesOpportunity.id, SalesOpportunity.company_id, last_touch_at(now)
        ).where(SalesOpportunity.company_id.in_(ids), live_opportunity())
    )
    return {row[0]: (row[1], row[2]) for row in rows.all()}


async def _company_touches(
    db: AsyncSession, ids: Sequence[int], now: datetime
) -> dict[int, datetime]:
    if not ids:
        return {}
    touched = touched_at()
    rows = await db.execute(
        select(SalesActivity.company_id, func.max(touched))
        .where(SalesActivity.company_id.in_(ids), touched < now)
        .group_by(SalesActivity.company_id)
    )
    return {row[0]: row[1] for row in rows.all() if row[1] is not None}


async def _outlook_duplicates(db: AsyncSession, merges: Sequence[Merge]) -> int:
    """Ile kopii tego samego maila lub spotkania z Outlooka zniknie przy scaleniu.

    Synchronizacja zapisuje je przy każdej dopasowanej firmie, a na jednej karcie
    zostaje jeden wiersz (``ux_sales_activities_outlook``).
    """

    total = 0
    for merge in merges:
        ids = [merge.target.id, *(source.id for source in merge.sources)]
        rows = await db.execute(
            select(func.count() - 1)
            .where(SalesActivity.company_id.in_(ids), outlook_copy())
            .group_by(SalesActivity.external_source, SalesActivity.external_id)
        )
        total += sum(int(extra) for extra in rows.scalars())
    return total


def _moved_touches(
    merge: Merge,
    live: dict[int, tuple[int, datetime]],
    company_touch: dict[int, datetime],
) -> int:
    """Ile otwartych szans dostałoby późniejszy dotyk z aktywności drugiej karty."""

    ids = {merge.target.id, *(source.id for source in merge.sources)}
    touches = [company_touch[i] for i in ids if i in company_touch]
    if not touches:
        return 0
    latest = max(touches)
    return sum(
        1 for company_id, touch in live.values() if company_id in ids and latest > touch
    )


def _parse_decisions(
    options: Options, cards: dict[int, Card]
) -> list[tuple[Card, list[Card]]]:
    decided = []
    used: set[int] = set()
    for target_id, source_ids in options.decide:
        ids = (target_id, *source_ids)
        if not source_ids or len(set(ids)) != len(ids):
            raise Refused("--decide: podaj DOCELOWA:ŹRÓDŁO[,ŹRÓDŁO], każdą kartę raz")
        if any(company_id not in cards for company_id in ids):
            raise Refused("--decide: karta nie istnieje albo jest w archiwum")
        if used & set(ids):
            raise Refused("--decide: karta występuje w dwóch decyzjach")
        used |= set(ids)
        decided.append((cards[target_id], [cards[i] for i in sorted(source_ids)]))
    return decided


def _name_in_domain(domain: str, cards: Sequence[Card]) -> bool:
    """Czy domena wygląda na domenę tej firmy: wyraz z nazwy siedzi w adresie."""

    host = domain.rsplit(".", 1)[0].replace("-", "").replace(".", "")
    words = {
        word
        for card in cards
        for word in card.key.split()
        if len(word) >= MIN_BRAND_LEN
    }
    return any(word in host for word in words)


def _propose_domain(
    card: Card, absorbed: Sequence[Card], stats: dict[int, Stats]
) -> DomainPlan:
    members = [card, *absorbed]
    plan = DomainPlan(card=card)
    # ``merge.py`` uzupełnia pustą domenę docelowej domeną pierwszego źródła.
    plan.current = next((m.domain for m in members if m.domain), None)
    if plan.current:
        plan.status = "jest"
        return plan
    mail: Counter[str] = Counter()
    for member in members:
        mail.update(stats[member.id].mail_domains)
    ranked = mail.most_common(2)
    website = next((m.website for m in members if m.website), None)
    if ranked:
        domain, support = ranked[0]
        total = sum(mail.values())
        tied = len(ranked) > 1 and ranked[1][1] == support
        strong = not tied and (
            (
                support >= STRONG_DOMAIN_SUPPORT
                and support / total >= STRONG_DOMAIN_SHARE
            )
            or (support == total and _name_in_domain(domain, members))
        )
        if strong or website is None:
            plan.proposed, plan.source = domain, "poczta"
            plan.support, plan.of = support, total
            plan.status = "do_zapisu" if strong else "slaba"
            return plan
    if website:
        plan.proposed, plan.source, plan.status = website, "www", "do_zapisu"
    return plan


def _mark_shared_domains(
    domains: list[DomainPlan], cards: dict[int, Card], absorbed: set[int]
) -> None:
    """Ta sama domena na dwóch firmach to konflikt, nie cichy zapis."""

    holders: dict[str, set[int]] = defaultdict(set)
    for card in cards.values():
        if card.domain and card.id not in absorbed:
            holders[card.domain].add(card.id)
    for plan in domains:
        # ``current`` bywa domeną wchłanianej karty, której ``holders`` jeszcze nie zna.
        if plan.current or plan.proposed:
            holders[plan.current or plan.proposed].add(plan.card.id)
    for plan in domains:
        if not plan.proposed:
            continue
        plan.shared_with = sorted(holders[plan.proposed] - {plan.card.id})
        if plan.shared_with:
            plan.status = "konflikt"


async def _build_plan(
    db: AsyncSession, options: Options, names: Sequence[str], now: datetime
) -> Plan:
    cards = await _load_cards(db)
    pipeline_id = await _factory_pipeline_id(db)
    by_key: dict[str, list[int]] = defaultdict(list)
    by_nip: dict[str, list[int]] = defaultdict(list)
    for card in cards.values():
        if card.key:
            by_key[card.key].append(card.id)
        if card.nip:
            by_nip[card.nip].append(card.id)

    seeds: dict[int, set[str]] = defaultdict(set)
    report = Report(mode="apply" if options.apply else "dry-run")
    if pipeline_id is not None:
        rows = await db.execute(
            select(SalesOpportunity.company_id)
            .where(SalesOpportunity.pipeline_id == pipeline_id)
            .distinct()
        )
        for company_id in rows.scalars():
            if company_id in cards:
                seeds[company_id].add(SEED_PIPELINE)
                report.seeds_pipeline += 1
    missing_names = []
    for name in dict.fromkeys(names):
        matched = by_key.get(normalize_company_name(name), ())
        for company_id in matched:
            seeds[company_id].add(SEED_NAMES)
        if matched:
            report.seeds_names += 1
        else:
            missing_names.append(name)
    report.names_without_card = len(missing_names)
    for company_id in options.company_ids:
        if company_id not in cards:
            raise Refused("--company-ids: karta nie istnieje albo jest w archiwum")
        seeds[company_id].add(SEED_IDS)
        report.seeds_ids += 1

    decided = _parse_decisions(options, cards)
    decided_ids = {c.id for target, sources in decided for c in (target, *sources)}
    grouped: dict[frozenset[int], set[str]] = defaultdict(set)
    for company_id in sorted(seeds):
        grouped[_exact_group(company_id, cards, by_key, by_nip)] |= seeds[company_id]
    groups = [
        Group(cards=[cards[i] for i in sorted(ids)], seeds=origin)
        for ids, origin in grouped.items()
    ]
    for group in groups:
        own = {card.id for card in group.cards}
        brands = {_brand(card.key) for card in group.cards}
        group.similar = _similar(brands, own, cards.values())
    missing = [
        (
            name,
            _similar({_brand(normalize_company_name(name))}, set(), cards.values()),
        )
        for name in missing_names
    ]

    scope = {card.id for group in groups for card in group.cards}
    scope |= {card.id for group in groups for card, _ in group.similar}
    scope |= {card.id for _, similar in missing for card, _ in similar} | decided_ids
    stats = await _load_stats(db, sorted(scope), pipeline_id)

    merges = [Merge(target, sources, "decyzja") for target, sources in decided]
    for group in groups:
        group.target = _pick_target(group.cards, stats)
        if {card.id for card in group.cards} & decided_ids:
            group.status = "decyzja"
        elif len(group.cards) > 1:
            group.reasons = _reasons(group.cards, stats)
            group.status = "do_decyzji" if group.reasons else "pewna"
        if group.status == "pewna":
            sources = [card for card in group.cards if card.id != group.target.id]
            merges.append(Merge(group.target, sources, "pewna"))

    merge_ids = sorted({c.id for m in merges for c in (m.target, *m.sources)})
    aliases = await _aliases(db, merge_ids)
    live = await _live_touches(db, merge_ids, now)
    company_touch = await _company_touches(db, merge_ids, now)
    for merge in merges:
        members = [merge.target, *merge.sources]
        if len({m.client_id for m in members if m.client_id is not None}) > 1:
            merge.blocked.append("dwoch_klientow")
        merge.moved_touches = _moved_touches(merge, live, company_touch)
        if merge.moved_touches:
            merge.blocked.append("dotyk")
        merge.join, lost = _names_to_join(merge, aliases)
        if lost:
            merge.blocked.append("dolaczona_nazwa")
    blocked_targets = {merge.target.id for merge in merges if merge.blocked}
    for group in groups:
        if group.status == "pewna" and group.target.id in blocked_targets:
            group.status = "zablokowana"

    going = [merge for merge in merges if not merge.blocked]
    absorbed_by = {merge.target.id: merge.sources for merge in going}
    absorbed = {source.id for merge in going for source in merge.sources}
    final = {company_id for company_id in seeds if company_id not in absorbed}
    final |= set(absorbed_by)
    domains = [
        _propose_domain(cards[i], absorbed_by.get(i, ()), stats) for i in sorted(final)
    ]
    _mark_shared_domains(domains, cards, absorbed)
    for plan in domains:
        if plan.card.id in options.accept_domain and plan.proposed:
            plan.status = "do_zapisu"

    report.groups = dict(Counter(group.status for group in groups))
    report.to_decide_reasons = dict(
        Counter(reason for group in groups for reason in group.reasons)
    )
    report.blocked_reasons = dict(
        Counter(reason for merge in merges for reason in merge.blocked)
    )
    similar = {card.id: kind for group in groups for card, kind in group.similar}
    report.similar_cards = len(similar)
    report.similar_name_variants = sum(1 for k in similar.values() if k == "wariant")
    report.to_merge = len(absorbed)
    report.to_merge_by_origin = dict(
        Counter(merge.origin for merge in going for _ in merge.sources)
    )
    report.moving = {
        name: sum(getattr(stats[company_id], name) for company_id in absorbed)
        for name in ("contacts", "opportunities", "activities", "files")
    }
    report.names_to_join = sum(len(merge.join) for merge in going)
    report.outlook_duplicates = await _outlook_duplicates(db, going)
    report.domains = dict(Counter(plan.status for plan in domains))
    report.domains_to_set = report.domains.get("do_zapisu", 0)
    return Plan(report, groups, merges, domains, stats, missing)


def _card_row(card: Card, stats: dict[int, Stats], role: str) -> dict[str, Any]:
    own = stats[card.id]
    return {
        "id": card.id,
        "name": card.name,
        "role": role,
        "nip": card.nip,
        "client_id": card.client_id,
        "domain": card.domain,
        "mail_domains": dict(own.mail_domains.most_common(3)),
        "contacts": own.contacts,
        "opportunities": own.opportunities,
        "open_opportunities": own.open_opportunities,
        "factory_opportunities": own.factory_opportunities,
        "activities": own.activities,
        "files": own.files,
    }


def _listing(plan: Plan, now: datetime) -> dict[str, Any]:
    """Lista do przejrzenia: z nazwami firm, więc tylko do pliku poza repo."""

    domains = {item.card.id: item for item in plan.domains}
    merges = {merge.target.id: merge for merge in plan.merges}

    def domain_row(company_id: int) -> Optional[dict[str, Any]]:
        item = domains.get(company_id)
        if item is None:
            return None
        return {
            "status": item.status,
            "current": item.current,
            "proposed": item.proposed,
            "source": item.source,
            "support": item.support,
            "of": item.of,
            "shared_with": item.shared_with,
        }

    def merge_row(merge: Merge) -> dict[str, Any]:
        return {
            "origin": merge.origin,
            "target": _card_row(merge.target, plan.stats, "docelowa"),
            "sources": [_card_row(c, plan.stats, "wchlaniana") for c in merge.sources],
            "blocked": merge.blocked,
            "moved_touches": merge.moved_touches,
            "names_to_join": [alias for alias, _ in merge.join],
            "domain": domain_row(merge.target.id),
        }

    groups = []
    for group in sorted(plan.groups, key=lambda g: (g.target.key, g.target.id)):
        merge = merges.get(group.target.id)
        variants = [card.id for card, kind in group.similar if kind == "wariant"]
        sources = [card.id for card in group.cards if card.id != group.target.id]
        groups.append(
            {
                "status": group.status,
                "seeds": sorted(group.seeds),
                "reasons": group.reasons,
                "blocked": merge.blocked if merge else [],
                "target_id": group.target.id,
                "cards": [
                    _card_row(
                        card,
                        plan.stats,
                        "docelowa" if card.id == group.target.id else "ta_sama_nazwa",
                    )
                    for card in group.cards
                ],
                "similar": [
                    _card_row(card, plan.stats, kind) for card, kind in group.similar
                ],
                "names_to_join": [alias for alias, _ in merge.join] if merge else [],
                "domain": domain_row(group.target.id),
                "other_domains": {
                    card.id: domain_row(card.id)
                    for card in group.cards
                    if card.id != group.target.id and card.id in domains
                },
                # Gotowa decyzja „scal karty o tej samej nazwie i warianty nazwy”.
                "decide_variants": (
                    f"{group.target.id}:{','.join(map(str, sorted(sources + variants)))}"
                    if variants and group.status in ("pojedyncza", "pewna")
                    else None
                ),
            }
        )
    return {
        "generated_at": now.isoformat(),
        "report": asdict(plan.report),
        "groups": groups,
        "decisions": [merge_row(m) for m in plan.merges if m.origin == "decyzja"],
        "names_without_card": [
            {
                "name": name,
                "similar": [
                    _card_row(card, plan.stats, kind) for card, kind in similar
                ],
            }
            for name, similar in plan.missing
        ],
    }


def _check_counters(options: Options, report: Report) -> None:
    if options.expect_merge is None or options.expect_domains is None:
        raise Refused(
            "--apply wymaga --expect-merge i --expect-domains z biegu na sucho"
        )
    if options.expect_merge != report.to_merge:
        raise Refused(
            f"--expect-merge {options.expect_merge}, a jest {report.to_merge}"
        )
    if options.expect_domains != report.domains_to_set:
        raise Refused(
            f"--expect-domains {options.expect_domains}, a jest {report.domains_to_set}"
        )


async def _check_actor(db: AsyncSession, options: Options) -> None:
    actor = await db.get(User, options.actor_id) if options.actor_id else None
    if actor is None or not actor.is_active or not actor.has_role(UserRole.admin):
        raise Refused("--actor-id: potrzebne aktywne konto administratora")


async def _apply(db: AsyncSession, plan: Plan, options: Options, now: datetime) -> None:
    going = [merge for merge in plan.merges if not merge.blocked]
    writing = [item for item in plan.domains if item.status == "do_zapisu"]
    ids = {c.id for merge in going for c in (merge.target, *merge.sources)}
    ids |= {item.card.id for item in writing}
    companies = {
        company.id: company
        for company in (
            await db.execute(
                select(SalesCompany)
                .where(SalesCompany.id.in_(ids))
                .order_by(SalesCompany.id)
                .with_for_update()
            )
        ).scalars()
    }
    if len(companies) != len(ids) or any(c.archived_at for c in companies.values()):
        raise Refused("karta z planu zniknęła albo trafiła do archiwum")

    merge_ids = sorted({c.id for m in going for c in (m.target, *m.sources)})
    before = await _live_touches(db, merge_ids, now)
    for merge in going:
        target = companies[merge.target.id]
        for source in merge.sources:
            await merge_companies(
                db,
                target=target,
                source=companies[source.id],
                now=now,
                user_id=options.actor_id,
            )
            plan.report.merged += 1
        if merge.join:
            # Nazwy dopisuje ``merge.py``; tu tylko sprawdzenie, że są przy karcie.
            present = await db.scalar(
                select(func.count())
                .select_from(SalesCompanyAlias)
                .where(
                    SalesCompanyAlias.company_id == target.id,
                    SalesCompanyAlias.status == JOINED,
                    SalesCompanyAlias.normalized_alias.in_(
                        [canonical for _, canonical in merge.join]
                    ),
                )
            )
            plan.report.names_joined += int(present or 0)
    for item in writing:
        company = companies[item.card.id]
        if not company.domain:
            company.domain = item.proposed
            plan.report.domains_set += 1
    await db.flush()

    after = await _live_touches(db, [merge.target.id for merge in going], now)
    moved = [
        opportunity_id
        for opportunity_id, (_, touch) in before.items()
        if opportunity_id not in after or after[opportunity_id][1] != touch
    ]
    if (
        moved
        or plan.report.names_joined != plan.report.names_to_join
        or plan.report.domains_set != plan.report.domains_to_set
    ):
        raise ResultDiffers()


async def run(options: Options, now: Optional[datetime] = None) -> Report:
    moment = now or datetime.now(timezone.utc)
    names = _read_names(options.names_file)
    list_path = _list_path(options.list_out)
    async with AsyncSessionLocal() as db:
        if not options.apply:
            await db.execute(text("SET TRANSACTION READ ONLY"))
        plan = await _build_plan(db, options, names, moment)
        if list_path is not None:
            list_path.write_text(
                json.dumps(_listing(plan, moment), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if not options.apply:
            await db.rollback()
            return plan.report
        _check_counters(options, plan.report)
        await _check_actor(db, options)
        await _apply(db, plan, options, moment)
        await db.commit()
        return plan.report


def _ids(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split(",") if part.strip())


def _decision(value: str) -> tuple[int, tuple[int, ...]]:
    target, _, sources = value.partition(":")
    return int(target), _ids(sources)


def _lock_path(value: str) -> Path:
    if not re.fullmatch(r"/tmp/nexus-sales-company-merge-\d+", value):
        raise argparse.ArgumentTypeError(
            "lock musi mieć postać /tmp/nexus-sales-company-merge-<liczba>"
        )
    return Path(value)


def _parse(argv: Sequence[str]) -> tuple[Options, Optional[Path]]:
    parser = argparse.ArgumentParser(
        description="Scalenie zdublowanych kart firm Sprzedaży i domeny"
    )
    parser.add_argument("--names-file")
    parser.add_argument("--company-ids", type=_ids, default=())
    parser.add_argument("--decide", type=_decision, action="append", default=[])
    parser.add_argument("--accept-domain", type=_ids, default=())
    parser.add_argument("--list-out")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-merge", type=int)
    parser.add_argument("--expect-domains", type=int)
    parser.add_argument("--actor-id", type=int)
    parser.add_argument("--lock", type=_lock_path)
    args = vars(parser.parse_args(argv))
    args["decide"] = tuple(args["decide"])
    lock = args.pop("lock")
    return Options(**args), lock


def main(argv: Optional[Sequence[str]] = None) -> int:
    options, lock = _parse(sys.argv[1:] if argv is None else argv)
    if lock is not None:
        try:
            lock.mkdir(parents=False)
        except FileExistsError:
            print(f"lock {lock} exists — already ran", file=sys.stderr)
            return EXIT_ALREADY_RAN
    try:
        report = asyncio.run(run(options))
    except Refused as exc:
        print(f"Odmowa, nic nie zapisano: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ResultDiffers:
        print(
            "Odmowa, transakcja wycofana: wynik zapisu różni się od planu",
            file=sys.stderr,
        )
        return EXIT_RESULT_DIFFERS
    except Exception as exc:  # log może być publiczny, więc bez treści wyjątku
        if lock is not None:
            (lock / "error.log").write_text(traceback.format_exc())
        print(f"Błąd: {type(exc).__name__}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
