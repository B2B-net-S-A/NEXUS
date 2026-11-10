"""Lista osób z researchu → mapy decyzyjne lejka Fabryki IT (B1, 10.11.2026).

Listę z researchu (osoby w firmach) wgrywa człowiek; NEXUS niczego nie pobiera
i nie wysyła osób do bota. ``plan`` mówi, co stanie się z każdym wierszem, zanim
cokolwiek powstanie: dopasowuje firmę do kart z kartoteki sprzedaży, pokazuje
konto w lejku z licznikami mapy i odsiewa klienta NEXUSA. ``accept`` dodaje
zaakceptowane osoby do map ze statusem „bez kontaktu”, źródłem i datą.

Dopasowanie firmy: karty tej samej marki (``company_aliases.brand_of``), bo jedna
firma ma w kartotece po kilka kart („Volvo”, „Volvo Group”, „Volvo Polska”).
Cel wybiera się sam tylko przy jednej karcie o dokładnie tej nazwie i gdy żadna
inna karta marki nie ma konta w lejku; w pozostałych przypadkach kartę wskazuje
człowiek. Scalanie kart to osobny krok (B6).

Firma, która jest klientem NEXUSA, nie dostaje osoby ani konta: temat prowadzi
Delivery Lead (``client_gate``, decyzja z 22.10.2026).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import String, any_, bindparam, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesCompany,
    SalesContact,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.services.company_names import normalize_company_name
from app.services.sales import client_gate, company_aliases, factories, history
from app.services.sales.decision_map import (
    IT_FACTORIES_PIPELINE_KEY,
    DecisionPersonCreate,
    decision_entries,
    describe_person,
    fill_contact,
    with_entries,
)
from app.services.sales.lifecycle import apply_stage
from app.services.sales.research_file import ResearchRow, person_key
from app.services.sales_schema import OpportunityEventKind

logger = logging.getLogger(__name__)

#: Źródło wpisu na mapie i nowej karty; ekran pokazuje przy nim ``source_label``.
SOURCE = "research"
#: Tyle kart jednej marki pokazuje wybór; reszta wymaga scalenia kart (B6).
MAX_CARDS_PER_COMPANY = 25
#: Nowe konto ma już osoby na mapie, więc zaczyna od tego etapu, nie od „Ciszy”.
NEW_ACCOUNT_STAGE_KEY = "itf-decision-map-wip"
COMPANY_DO_NOT_CONTACT = factories.COMPANY_DO_NOT_CONTACT

# Stan firmy z pliku w NEXUSIE.
ACCOUNT = "account"
CARD = "card"
CHOOSE = "choose"
NO_CARD = "no_card"
CLIENT = "client"
BLOCKED = "blocked"
OWN_COMPANY = "own_company"

# Osoba z pliku wobec map.
NEW = "new"
ON_MAP = "on_map"
REPEATED = "repeated"

# Wynik akceptacji jednego wiersza.
ADDED = "added"
CHOOSE_CARD = "choose_card"
CARD_MISSING = "card_missing"
ERROR = "error"

NO_PIPELINE_DETAIL = "W Sprzedaży nie ma lejka Fabryki IT."
CARD_MISSING_DETAIL = (
    "Nie ma takiej karty firmy albo jest w archiwum. Wczytaj listę ponownie."
)
CHOOSE_CARD_DETAIL = "Ta firma ma kilka kart. Wybierz kartę i dodaj osobę ponownie."
BLOCKED_DETAIL = "Firma ma oznaczenie „Nie kontaktować”."
ON_MAP_DETAIL = "Ta osoba jest już na mapie tej firmy."
ERROR_DETAIL = "Nie udało się zapisać tego wiersza. Spróbuj ponownie."


class NoPipelineError(RuntimeError):
    """Baza bez lejka Fabryki IT: nie ma gdzie założyć konta."""


@dataclass(frozen=True)
class AccountInfo:
    opportunity_id: int
    title: str
    stage_name: str
    status: str
    counts: factories.MapCounts


@dataclass(frozen=True)
class Card:
    """Karta firmy z kartoteki sprzedaży, która może być celem dla osoby z pliku."""

    id: int
    name: str
    #: Nazwa kanoniczna karty jest dokładnie nazwą z pliku.
    exact: bool
    contacts: int
    account: Optional[AccountInfo]
    #: Konto w lejku jest tylko w archiwum: akceptacja założy nowe.
    archived_account: bool
    client: Optional[client_gate.ClientMatch]
    blocked: bool


@dataclass(frozen=True)
class CompanyPlan:
    key: str
    #: Pisownia z pliku (pierwszy wiersz tej firmy).
    name: str
    state: str
    #: Karta wybrana samoczynnie; ``None`` przy wyborze, braku karty i odmowie.
    company_id: Optional[int]
    cards: tuple[Card, ...]
    client: Optional[client_gate.ClientMatch]


@dataclass(frozen=True)
class RowPlan:
    row: ResearchRow
    company_key: str
    person: str
    on_map_opportunity_id: Optional[int] = None


@dataclass(frozen=True)
class Plan:
    companies: list[CompanyPlan]
    rows: list[RowPlan]


@dataclass(frozen=True)
class Person:
    """Zaakceptowany wiersz: osoba, firma z pliku i karta wskazana na ekranie."""

    line: int
    company: str
    name: str
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    source_url: Optional[str] = None
    domain: Optional[str] = None
    confidence: str = "to_verify"
    decision_level: Optional[int] = None
    note: Optional[str] = None
    #: ``None``: jedyna karta o tej nazwie albo nowa karta, gdy żadnej nie ma.
    company_id: Optional[int] = None


@dataclass(frozen=True)
class Outcome:
    line: int
    result: str
    detail: Optional[str] = None
    company_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    created_company: bool = False
    created_account: bool = False
    client: Optional[client_gate.ClientMatch] = None


@dataclass(frozen=True)
class _Target:
    """Karta firmy jako zwykłe wartości: obiekt ORM wygasa po cofnięciu wiersza."""

    id: int
    name: str
    blocked: bool


# ── Wspólne ───────────────────────────────────────────────────────────────


def company_key(name: str) -> str:
    """Nazwa kanoniczna firmy z pliku; sama interpunkcja zostaje małymi literami."""

    return normalize_company_name(name) or name.strip().lower()


def _same_person(
    entry: dict[str, Any], *, name_key: Optional[str], email: Optional[str]
) -> bool:
    """Ten sam e-mail albo to samo imię i nazwisko (kolejność wyrazów bez znaczenia)."""

    entry_email = entry.get("email")
    if email and isinstance(entry_email, str) and entry_email.strip().lower() == email:
        return True
    return name_key is not None and person_key(entry.get("name")) == name_key


def on_map(
    entries: Sequence[dict[str, Any]], *, name: str, email: Optional[str]
) -> bool:
    name_key = person_key(name)
    email = (email or "").strip().lower() or None
    return any(_same_person(e, name_key=name_key, email=email) for e in entries)


def _client_identities(
    keys: Sequence[str], cards: Sequence[Any]
) -> list[client_gate.CompanyIdentity]:
    """Karty i same nazwy z pliku (id ujemne) do jednej bramki klienta."""

    return [
        client_gate.CompanyIdentity(
            company_id=card.id,
            client_id=card.client_id,
            normalized_name=card.normalized_name,
        )
        for card in cards
        if card.normalized_name != client_gate.OWN_COMPANY_KEY
    ] + [
        client_gate.CompanyIdentity(
            company_id=-(index + 1), client_id=None, normalized_name=key
        )
        for index, key in enumerate(keys)
    ]


def _funnel_opportunities(company_ids: Sequence[int]):
    return (
        select(
            SalesOpportunity.id,
            SalesOpportunity.title,
            SalesOpportunity.company_id,
            SalesOpportunity.status,
            SalesOpportunity.archived_at,
            SalesOpportunity.custom_fields,
            SalesPipelineStage.name.label("stage_name"),
        )
        .join(SalesPipeline, SalesPipeline.id == SalesOpportunity.pipeline_id)
        .join(SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id)
        .where(
            SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
            SalesOpportunity.company_id.in_(company_ids),
        )
        # Otwarte konto przed zamkniętym, potem najstarsze: pierwsze wygrywa.
        .order_by(SalesOpportunity.status != "open", SalesOpportunity.id)
    )


# ── Przegląd ──────────────────────────────────────────────────────────────


async def _cards_by_key(db: AsyncSession, keys: Sequence[str]) -> dict[str, list[Any]]:
    """Karty tej samej marki dla każdej nazwy z pliku, jednym zapytaniem."""

    brands = {key: company_aliases.brand_of(key) for key in keys}
    exact_names = sorted({*keys, *brands.values()})
    # Nazwa kanoniczna to litery, cyfry i spacje, więc wzorzec nie wymaga ucieczek.
    # Dwuliterowa nazwa („IT”) pasowałaby jako początek do przypadkowych firm.
    prefixes = sorted(
        {
            f"{brand} %"
            for brand in brands.values()
            if len(brand) >= company_aliases.MIN_NAME_LEN
        }
    )
    rows = (
        await db.execute(
            select(
                SalesCompany.id,
                SalesCompany.name,
                SalesCompany.normalized_name,
                SalesCompany.client_id,
                SalesCompany.status,
            )
            .where(
                SalesCompany.archived_at.is_(None),
                or_(
                    SalesCompany.normalized_name.in_(exact_names),
                    SalesCompany.normalized_name.like(
                        any_(bindparam("prefixes", prefixes, type_=ARRAY(String)))
                    ),
                ),
            )
            .order_by(SalesCompany.id)
        )
    ).all()
    found: dict[str, list[Any]] = {key: [] for key in keys}
    for key, brand in brands.items():
        prefix = f"{brand} " if len(brand) >= company_aliases.MIN_NAME_LEN else None
        found[key] = [
            row
            for row in rows
            if row.normalized_name in (key, brand)
            or (prefix is not None and row.normalized_name.startswith(prefix))
        ]
    return found


def _state(
    key: str,
    cards: Sequence[Card],
    name_client: Optional[client_gate.ClientMatch],
) -> tuple[str, Optional[int], Optional[client_gate.ClientMatch]]:
    if company_aliases.is_own_company(key):
        return OWN_COMPANY, None, None
    exact = [card for card in cards if card.exact]
    client = name_client or next((c.client for c in exact if c.client), None)
    if client is not None:
        return CLIENT, None, client
    if not cards:
        return NO_CARD, None, None
    with_account = [card for card in cards if card.account is not None]
    if len(exact) == 1 and all(card.id == exact[0].id for card in with_account):
        target = exact[0]
        if target.blocked:
            return BLOCKED, None, None
        return (ACCOUNT if target.account else CARD), target.id, None
    return CHOOSE, None, None


async def plan(db: AsyncSession, rows: Sequence[ResearchRow]) -> Plan:
    """Los każdego wiersza listy; niczego nie zapisuje."""

    names: dict[str, str] = {}
    for row in rows:
        names.setdefault(company_key(row.company), row.company)
    keys = list(names)
    if not keys:
        return Plan(companies=[], rows=[])
    raw_cards = await _cards_by_key(db, keys)
    by_id = {card.id: card for cards in raw_cards.values() for card in cards}
    card_ids = sorted(by_id)

    contacts: dict[int, int] = {}
    accounts: dict[int, Any] = {}
    archived: set[int] = set()
    if card_ids:
        contacts = dict(
            (
                await db.execute(
                    select(SalesContact.company_id, func.count())
                    .where(
                        SalesContact.company_id.in_(card_ids),
                        SalesContact.archived_at.is_(None),
                    )
                    .group_by(SalesContact.company_id)
                )
            ).all()
        )
        for opp in (await db.execute(_funnel_opportunities(card_ids))).all():
            if opp.archived_at is not None:
                archived.add(opp.company_id)
            else:
                accounts.setdefault(opp.company_id, opp)
    clients = await client_gate.match_companies(
        db, _client_identities(keys, list(by_id.values()))
    )

    def card_of(raw: Any, key: str) -> Card:
        opp = accounts.get(raw.id)
        return Card(
            id=raw.id,
            name=raw.name,
            exact=raw.normalized_name == key,
            contacts=int(contacts.get(raw.id, 0)),
            account=AccountInfo(
                opportunity_id=opp.id,
                title=opp.title,
                stage_name=opp.stage_name,
                status=opp.status,
                # Te same definicje co lista kont: kto jest „po kontakcie”.
                counts=factories.map_counts(decision_entries(opp.custom_fields)),
            )
            if opp is not None
            else None,
            archived_account=opp is None and raw.id in archived,
            client=clients.get(raw.id),
            blocked=raw.status == COMPANY_DO_NOT_CONTACT,
        )

    companies: dict[str, CompanyPlan] = {}
    for index, key in enumerate(keys):
        cards = sorted(
            (card_of(raw, key) for raw in raw_cards[key]),
            key=lambda c: (
                not c.exact,
                c.account is None,
                -c.contacts,
                c.name.casefold(),
            ),
        )[:MAX_CARDS_PER_COMPANY]
        state, company_id, client = _state(key, cards, clients.get(-(index + 1)))
        companies[key] = CompanyPlan(
            key=key,
            name=names[key],
            state=state,
            company_id=company_id,
            cards=tuple(cards),
            client=client,
        )

    entries_by_company = {
        company_id: (opp.id, decision_entries(opp.custom_fields))
        for company_id, opp in accounts.items()
    }
    seen: set[tuple[str, str]] = set()
    planned = []
    for row in rows:
        key = company_key(row.company)
        marks = {
            (key, mark)
            for mark in (person_key(row.name), row.email)
            if mark is not None
        }
        found = next(
            (
                entries_by_company[card.id][0]
                for card in companies[key].cards
                if card.id in entries_by_company
                and on_map(
                    entries_by_company[card.id][1], name=row.name, email=row.email
                )
            ),
            None,
        )
        if found is not None:
            person = ON_MAP
        elif marks & seen:
            person = REPEATED
        else:
            person = NEW
        seen |= marks
        planned.append(
            RowPlan(
                row=row, company_key=key, person=person, on_map_opportunity_id=found
            )
        )
    return Plan(companies=list(companies.values()), rows=planned)


# ── Akceptacja ────────────────────────────────────────────────────────────


async def _pipeline(db: AsyncSession) -> tuple[int, list[SalesPipelineStage]]:
    pipeline_id = await db.scalar(
        select(SalesPipeline.id).where(
            SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
            SalesPipeline.archived_at.is_(None),
        )
    )
    stages = list(
        (
            await db.execute(
                select(SalesPipelineStage)
                .where(SalesPipelineStage.pipeline_id == pipeline_id)
                .order_by(SalesPipelineStage.position)
            )
        ).scalars()
    )
    if pipeline_id is None or not any(stage.outcome == "open" for stage in stages):
        raise NoPipelineError(NO_PIPELINE_DETAIL)
    return pipeline_id, stages


def _entry(person: Person, *, source_label: str, today: date) -> dict[str, Any]:
    """Wpis mapy z polami formularza i pochodzeniem; okno osoby zachowuje te klucze."""

    entry = DecisionPersonCreate(
        name=person.name,
        role_in_company=person.title,
        decision_level=person.decision_level,
        linkedin_url=person.linkedin_url,
        phone=person.phone,
        email=person.email,
        notes=person.note,
    ).model_dump(mode="json")
    entry.update(
        source=SOURCE,
        source_label=source_label,
        source_added_at=today.isoformat(),
        source_confidence=person.confidence,
    )
    if person.source_url:
        entry["source_url"] = person.source_url
    return entry


@dataclass
class _Batch:
    """Stan jednej akceptacji: karty, konta i klienci wczytani raz dla całej listy."""

    db: AsyncSession
    user_id: int
    owner_user_id: int
    source_label: str
    today: date
    now: datetime
    pipeline_id: int
    stages: list[SalesPipelineStage]
    targets: dict[int, _Target]
    exact: dict[str, list[int]]
    accounts: dict[int, int]
    clients: dict[int, client_gate.ClientMatch]
    key_index: dict[str, int]

    def refusal(self, person: Person) -> tuple[Optional[Outcome], Optional[_Target]]:
        """Odmowa bez zapisu albo karta, na której mapę trafi osoba."""

        key = company_key(person.company)
        line = person.line
        if company_aliases.is_own_company(key):
            return (
                Outcome(line, OWN_COMPANY, detail=client_gate.OWN_COMPANY_REFUSAL),
                None,
            )
        client = self.clients.get(-(self.key_index[key] + 1))
        if client is not None:
            return Outcome(line, CLIENT, detail=client.refusal, client=client), None
        target: Optional[_Target] = None
        if person.company_id is not None:
            target = self.targets.get(person.company_id)
            if target is None:
                return Outcome(line, CARD_MISSING, detail=CARD_MISSING_DETAIL), None
        else:
            same_name = self.exact.get(key, [])
            if len(same_name) > 1:
                return Outcome(line, CHOOSE_CARD, detail=CHOOSE_CARD_DETAIL), None
            target = self.targets[same_name[0]] if same_name else None
        if target is not None:
            client = self.clients.get(target.id)
            if client is not None:
                return (
                    Outcome(
                        line,
                        CLIENT,
                        detail=client.refusal,
                        company_id=target.id,
                        client=client,
                    ),
                    None,
                )
            if target.blocked:
                return (
                    Outcome(line, BLOCKED, detail=BLOCKED_DETAIL, company_id=target.id),
                    None,
                )
        return None, target

    async def add(self, person: Person, target: Optional[_Target]) -> Outcome:
        """Zapis jednego wiersza: karta i konto, gdy ich brak, potem osoba na mapie."""

        db = self.db
        created_company = target is None
        if target is None:
            name = person.company[:500]
            company = SalesCompany(
                name=name,
                normalized_name=company_key(name)[:500],
                domain=person.domain,
                website_url=f"https://{person.domain}" if person.domain else None,
                source=SOURCE,
                owner_user_id=self.owner_user_id,
                created_by_user_id=self.user_id,
            )
            db.add(company)
            await db.flush()
            target = _Target(id=company.id, name=name, blocked=False)

        opportunity_id = self.accounts.get(target.id)
        created_account = opportunity_id is None
        if opportunity_id is None:
            stage = next(
                (s for s in self.stages if s.key == NEW_ACCOUNT_STAGE_KEY),
                next(s for s in self.stages if s.outcome == "open"),
            )
            opp = SalesOpportunity(
                company_id=target.id,
                pipeline_id=self.pipeline_id,
                stage_id=stage.id,
                title=target.name[:255],
                source=SOURCE,
                owner_user_id=self.owner_user_id,
                created_by_user_id=self.user_id,
            )
            apply_stage(opp, stage, self.stages, now=self.now)
            db.add(opp)
            await db.flush()
            history.record_created(db, opp, user_id=self.user_id)
        else:
            # Blokada wiersza, jak przy „Dodaj osobę”: zapis to odczyt listy z JSON-a,
            # zmiana i nadpisanie, a świeży odczyt zastępuje stan sprzed cofnięcia.
            opp = (
                await db.execute(
                    select(SalesOpportunity)
                    .where(SalesOpportunity.id == opportunity_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()

        entries = decision_entries(opp.custom_fields)
        if on_map(entries, name=person.name, email=person.email):
            return Outcome(
                person.line,
                ON_MAP,
                detail=ON_MAP_DETAIL,
                company_id=target.id,
                opportunity_id=opp.id,
            )
        entry = _entry(person, source_label=self.source_label, today=self.today)
        opp.custom_fields = with_entries(
            opp.custom_fields, [*entries, entry], user_id=self.user_id, now=self.now
        )
        history.record(
            db,
            opportunity_id=opp.id,
            user_id=self.user_id,
            kind=OpportunityEventKind.updated,
            field="decision_map",
            new_value=describe_person(entry),
        )
        filled = await fill_contact(db, target.id, entry, list(entry))
        if filled:
            history.record(
                db,
                opportunity_id=opp.id,
                user_id=self.user_id,
                kind=OpportunityEventKind.updated,
                field="decision_map_contact",
                new_value=f"{entry['name']}: {', '.join(filled)}",
            )
        await db.flush()
        return Outcome(
            person.line,
            ADDED,
            company_id=target.id,
            opportunity_id=opp.id,
            created_company=created_company,
            created_account=created_account,
        )

    def remember(self, person: Person, outcome: Outcome) -> None:
        """Kolejna osoba tej samej firmy trafia na tę samą nową kartę i konto."""

        if outcome.company_id is None or outcome.opportunity_id is None:
            return
        if outcome.created_company:
            self.targets[outcome.company_id] = _Target(
                id=outcome.company_id, name=person.company[:500], blocked=False
            )
            self.exact.setdefault(company_key(person.company), []).append(
                outcome.company_id
            )
        self.accounts.setdefault(outcome.company_id, outcome.opportunity_id)


async def accept(
    db: AsyncSession,
    people: Sequence[Person],
    *,
    user_id: int,
    owner_user_id: int,
    source_label: str,
    today: date,
    now: datetime,
) -> list[Outcome]:
    """Dodaje osoby do map; wynik per wiersz. Commit robi wywołujący.

    Każdy wiersz ma własny punkt zapisu: błąd jednego nie cofa pozostałych.
    Osoba już obecna na mapie (ten sam e-mail albo nazwisko) nie dubluje się,
    więc ponowna akceptacja tej samej listy niczego nie dopisuje.
    """

    pipeline_id, stages = await _pipeline(db)
    keys = list(dict.fromkeys(company_key(person.company) for person in people))
    given = sorted({p.company_id for p in people if p.company_id is not None})
    free_keys = sorted({company_key(p.company) for p in people if p.company_id is None})
    cards = (
        await db.execute(
            select(
                SalesCompany.id,
                SalesCompany.name,
                SalesCompany.normalized_name,
                SalesCompany.client_id,
                SalesCompany.status,
            )
            .where(
                SalesCompany.archived_at.is_(None),
                or_(
                    SalesCompany.id.in_(given),
                    SalesCompany.normalized_name.in_(free_keys),
                ),
            )
            .order_by(SalesCompany.id)
        )
    ).all()
    exact: dict[str, list[int]] = {}
    for card in cards:
        if card.normalized_name in free_keys:
            exact.setdefault(card.normalized_name, []).append(card.id)
    card_ids = [card.id for card in cards]
    accounts: dict[int, int] = {}
    if card_ids:
        for opp in (await db.execute(_funnel_opportunities(card_ids))).all():
            if opp.archived_at is None:
                accounts.setdefault(opp.company_id, opp.id)

    batch = _Batch(
        db=db,
        user_id=user_id,
        owner_user_id=owner_user_id,
        source_label=source_label,
        today=today,
        now=now,
        pipeline_id=pipeline_id,
        stages=stages,
        targets={
            card.id: _Target(
                id=card.id,
                name=card.name,
                blocked=card.status == COMPANY_DO_NOT_CONTACT,
            )
            for card in cards
        },
        exact=exact,
        accounts=accounts,
        clients=await client_gate.match_companies(db, _client_identities(keys, cards)),
        key_index={key: index for index, key in enumerate(keys)},
    )

    outcomes = []
    for person in people:
        refused, target = batch.refusal(person)
        if refused is not None:
            outcomes.append(refused)
            continue
        try:
            async with db.begin_nested():
                outcome = await batch.add(person, target)
        except Exception as exc:  # noqa: BLE001 — błąd wiersza nie wywraca listy
            # Log jest publiczny: numer wiersza i typ błędu, bez nazw i treści.
            logger.warning(
                "[sales-research-import] wiersz %s: %s",
                person.line,
                type(exc).__name__,
            )
            outcomes.append(Outcome(person.line, ERROR, detail=ERROR_DETAIL))
            continue
        batch.remember(person, outcome)
        outcomes.append(outcome)
    return outcomes
