"""Popyt z rozmów opiekuna → Delivery Lead klienta (decyzja Artura 22.10.2026, nie ATLAS).

* **Sygnał** = rozmowa opiekuna z „klient zatrudnia” z ostatnich 90 dni.
  Dział: z karty technologicznej zapisanej tą rozmową (okno „Rozmowa”,
  ``tech_cards.care_conversation_id``), a bez niej — dział menedżera
  konsultanta u klienta. Role i źródło informacji — z tej karty; bez karty
  (albo gdy karta ich nie ma) — z rozmowy (``client_hiring_roles``,
  ``client_hiring_source``, 0506), a bez nich zostaje notatka „klient zatrudnia”.
* **Karta „Popyt do sprawdzenia”** na tablicy DL: ten sam klient, dział
  i zbiór ról w 30 dniach = jedna karta (najnowszy sygnał, lista źródeł).
  Klucz ``demand:<klient>:<rozmowa>`` (``board_state``) — bez działu, bo
  dział liczy się przy odczycie i po zmianie działu menedżera stan karty
  (rozstrzygnięcie) by się zgubił; dział służy tylko do łączenia kart.
* **Dzwonek** ``care_demand_signal`` do aktywnych DL klienta przy zapisie
  rozmowy, najwyżej jeden na (DL, klient, dział) w 7 dni; link
  ``/care?card=<klucz>&area=<dział albo 0>`` (dział w linku tylko do
  liczenia tego limitu).
* **Rozstrzygnięcie** (okno „Rozmowa z menedżerem”): potwierdzona →
  ``/jobs/new`` z klientem, hiring managerem, technologiami i nazwą
  (``jobs_new_url``), „nie teraz” → wraca za 30 dni, „nieaktualne” → znika.
  Rozstrzyga DL klienta albo admin; zapis obejmuje wszystkie źródła karty.

Odczyt niczego nie zapisuje. Bez stawek.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import quote, urlencode

from sqlalchemy import Integer, String, column, select, table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.contract import Contract
from app.models.contract_care import CONTACTS_ORG, CareConversation, ClientArea
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.care import access as care_access
from app.services.care import board_state
from app.services.care.week import excerpt
from app.services.hr import audit

SIGNAL_WINDOW_DAYS = 90
GROUP_WINDOW_DAYS = 30
NOTIFY_EVERY_DAYS = 7
NOT_NOW_DAYS = 30
ROLE_MAX = 120

#: Karta zapisana rozmową (0506) — dział, role i źródło informacji o popycie.
TECH_CARDS_LINK = table(
    "tech_cards",
    column("id", Integer),
    column("care_conversation_id", Integer),
    column("client_area_id", Integer),
    column("hiring_roles", JSONB),
    column("hiring_source", String),
)
#: Role i źródło „klient zatrudnia” zapisane przy rozmowie (0506).
CONVERSATIONS_HIRING = table(
    "care_conversations",
    column("id", Integer),
    column("client_hiring_roles", JSONB),
    column("client_hiring_source", String),
)
_contacts_org = CONTACTS_ORG.alias("contacts_org")

RESOLVE_DENIED = "Popyt rozstrzyga Delivery Lead klienta albo administrator."
UNKNOWN_SIGNAL = "Nie ma takiego sygnału popytu u tego klienta."


@dataclass(frozen=True)
class Signal:
    conversation_id: int
    contract_id: int
    client_id: int
    client_name: str
    candidate_name: Optional[str]
    on: date
    area_id: Optional[int]
    area_name: Optional[str]
    roles: tuple[str, ...]
    source: Optional[str]
    note: Optional[str]

    @property
    def key(self) -> str:
        return board_state.demand_key(self.client_id, self.conversation_id)

    @property
    def role_set(self) -> frozenset[str]:
        return frozenset(role.casefold() for role in self.roles)


@dataclass
class Group:
    """Jedna karta popytu: najnowszy sygnał i pozostałe źródła."""

    signals: list[Signal] = field(default_factory=list)

    @property
    def head(self) -> Signal:
        return self.signals[0]

    @property
    def keys(self) -> list[str]:
        return [signal.key for signal in self.signals]


def clean_roles(roles: Iterable[object]) -> list[str]:
    """Role popytu: bez pustych, przycięte do ``ROLE_MAX``, bez powtórzeń."""

    out: list[str] = []
    seen: set[str] = set()
    for role in roles or []:
        text = " ".join(str(role).split())[:ROLE_MAX]
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return out


def signal_hiring(
    card_roles: Optional[Sequence[object]],
    card_source: Optional[str],
    conversation_roles: Optional[Sequence[object]],
    conversation_source: Optional[str],
) -> tuple[tuple[str, ...], Optional[str]]:
    """Role i źródło sygnału: z karty rozmowy, a gdy ich nie ma — z rozmowy."""

    roles = clean_roles(card_roles or []) or clean_roles(conversation_roles or [])
    return tuple(roles), card_source or conversation_source


def group_signals(signals: Iterable[Signal]) -> list[Group]:
    """Ten sam klient, dział i zbiór ról w 30 dniach = jedna karta (czysta reguła).

    Grupę otwiera najnowszy sygnał; dołączają starsze, nie starsze niż 30 dni
    od NAJNOWSZEGO sygnału grupy.
    """

    ordered = sorted(signals, key=lambda s: (s.on, s.conversation_id), reverse=True)
    groups: list[Group] = []
    open_by: dict[tuple, Group] = {}
    for signal in ordered:
        bucket = (signal.client_id, signal.area_id or 0, signal.role_set)
        group = open_by.get(bucket)
        if group is not None and (group.head.on - signal.on).days <= GROUP_WINDOW_DAYS:
            group.signals.append(signal)
            continue
        group = Group([signal])
        groups.append(group)
        open_by[bucket] = group
    return groups


def visible(state: Optional[board_state.BoardState], today: date) -> bool:
    """Rozstrzygnięty popyt znika; „nie teraz” wraca w dniu ``retry_on``."""

    if state is None or state.outcome is None:
        return True
    if state.outcome == "not_now":
        return state.retry_on is not None and state.retry_on <= today
    return False


async def signals_for_clients(
    db: AsyncSession, client_ids: Optional[Iterable[int]], *, today: date
) -> list[Signal]:
    """Sygnały z 90 dni (``None`` = wszyscy klienci)."""

    since = today - timedelta(days=SIGNAL_WINDOW_DAYS)
    query = (
        select(
            CareConversation.id,
            CareConversation.contract_id,
            CareConversation.occurred_on,
            CareConversation.client_hiring_note,
            Contract.client_id,
            Client.name,
            Contract.client_pm_contact_id,
            Contract.candidate_id,
        )
        .join(Contract, Contract.id == CareConversation.contract_id)
        .join(Client, Client.id == Contract.client_id)
        .where(
            CareConversation.client_hiring.is_(True),
            CareConversation.occurred_on >= since,
            Contract.voided_at.is_(None),
        )
    )
    if client_ids is not None:
        query = query.where(Contract.client_id.in_(sorted(set(client_ids)) or [-1]))
    rows = (await db.execute(query)).all()
    if not rows:
        return []
    conv_ids = [row[0] for row in rows]
    cards = {
        row.care_conversation_id: row
        for row in (
            await db.execute(
                select(
                    TECH_CARDS_LINK.c.care_conversation_id,
                    TECH_CARDS_LINK.c.client_area_id,
                    TECH_CARDS_LINK.c.hiring_roles,
                    TECH_CARDS_LINK.c.hiring_source,
                ).where(TECH_CARDS_LINK.c.care_conversation_id.in_(conv_ids))
            )
        ).all()
    }
    talk_hiring = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    CONVERSATIONS_HIRING.c.id,
                    CONVERSATIONS_HIRING.c.client_hiring_roles,
                    CONVERSATIONS_HIRING.c.client_hiring_source,
                ).where(CONVERSATIONS_HIRING.c.id.in_(conv_ids))
            )
        ).all()
    }
    managers = sorted({row[6] for row in rows if row[6] is not None})
    manager_area: dict[int, int] = {}
    if managers:
        manager_area = {
            contact_id: area_id
            for contact_id, area_id in (
                await db.execute(
                    select(_contacts_org.c.id, _contacts_org.c.client_area_id).where(
                        _contacts_org.c.id.in_(managers),
                        _contacts_org.c.client_area_id.is_not(None),
                    )
                )
            ).all()
        }
    contracts = await care_access.contracts_by_id(db, [row[1] for row in rows])
    out: list[Signal] = []
    pending_areas: set[int] = set()
    raw: list[tuple] = []
    for conv_id, contract_id, on, note, client_id, client_name, pm_id, _cand in rows:
        card = cards.get(conv_id)
        area_id = (card.client_area_id if card is not None else None) or (
            manager_area.get(pm_id) if pm_id is not None else None
        )
        if area_id is not None:
            pending_areas.add(area_id)
        raw.append(
            (conv_id, contract_id, on, note, client_id, client_name, area_id, card)
        )
    area_rows = (
        await db.execute(
            select(ClientArea.id, ClientArea.client_id, ClientArea.name).where(
                ClientArea.id.in_(sorted(pending_areas) or [-1])
            )
        )
    ).all()
    areas = {area_id: (client_id, name) for area_id, client_id, name in area_rows}
    for conv_id, contract_id, on, note, client_id, client_name, area_id, card in raw:
        # Dział innego klienta (dane sprzed walidacji) nie wskazuje działu.
        if area_id is not None and areas.get(area_id, (None,))[0] != client_id:
            area_id = None
        contract = contracts.get(contract_id)
        talk = talk_hiring.get(conv_id)
        roles, source = signal_hiring(
            card.hiring_roles if card is not None else None,
            card.hiring_source if card is not None else None,
            talk.client_hiring_roles if talk is not None else None,
            talk.client_hiring_source if talk is not None else None,
        )
        out.append(
            Signal(
                conversation_id=conv_id,
                contract_id=contract_id,
                client_id=client_id,
                client_name=client_name,
                candidate_name=contract.candidate_name if contract else None,
                on=on,
                area_id=area_id,
                area_name=areas[area_id][1] if area_id is not None else None,
                roles=roles,
                source=source,
                note=excerpt(note),
            )
        )
    return out


async def open_groups(
    db: AsyncSession, client_ids: Optional[Iterable[int]], *, today: date
) -> list[tuple[Group, Optional[board_state.BoardState]]]:
    """Karty popytu do pokazania: grupy nierozstrzygniętych sygnałów i ich stan."""

    signals = await signals_for_clients(db, client_ids, today=today)
    states = await board_state.states_for(db, (s.key for s in signals))
    alive = [s for s in signals if visible(states.get(s.key), today)]
    return [(group, states.get(group.head.key)) for group in group_signals(alive)]


def card_title(roles: Sequence[str]) -> str:
    if not roles:
        return "Popyt do sprawdzenia"
    return "Popyt do sprawdzenia: " + ", ".join(roles[:3])


# ── Kto rozstrzyga ──────────────────────────────────────────────────────────


async def demand_clients(db: AsyncSession, user: User) -> Optional[frozenset[int]]:
    """Klienci, których popyt widzi i rozstrzyga ``user``.

    ``None`` = wszyscy (admin); pusty zbiór = nikt (nie DL i nie admin).
    """

    if user.has_role(UserRole.admin):
        return None
    if not user.has_role(UserRole.delivery_lead):
        return frozenset()
    scope = await care_access.allowed_client_ids(user, db)
    return scope


async def can_resolve(db: AsyncSession, user: User, client_id: int) -> bool:
    scope = await demand_clients(db, user)
    return scope is None or client_id in scope


# ── Dzwonek przy zapisie rozmowy ────────────────────────────────────────────


def card_link(key: str) -> str:
    return f"/care?card={key}"


def notify_link(key: str, area_id: Optional[int]) -> str:
    """Link dzwonka: karta popytu + dział (do limitu raz na 7 dni per dział)."""

    return f"{card_link(key)}&area={area_id or 0}"


def notify_message(
    client_name: str,
    area_name: Optional[str],
    roles: Sequence[str],
    candidate_name: Optional[str],
) -> str:
    where = client_name + (f" · {area_name}" if area_name else "")
    what = ", ".join(roles[:3]) if roles else "nowe osoby"
    who = f" (z rozmowy z {candidate_name})" if candidate_name else ""
    return f"{where} zatrudnia: {what}{who}. Sprawdź u menedżera."


async def _recent_recipients(
    db: AsyncSession, *, client_id: int, area_id: Optional[int], now: datetime
) -> set[int]:
    prefix = card_link(f"demand:{client_id}:")
    rows = await db.scalars(
        select(Notification.user_id).where(
            Notification.notification_type == NotificationType.care_demand_signal,
            Notification.related_entity_type == "client",
            Notification.related_entity_id == client_id,
            Notification.link.startswith(prefix, autoescape=True),
            Notification.link.endswith(f"&area={area_id or 0}", autoescape=True),
            Notification.created_at >= now - timedelta(days=NOTIFY_EVERY_DAYS),
        )
    )
    return {int(user_id) for user_id in rows.all()}


async def notify_leads(
    db: AsyncSession,
    *,
    conversation: CareConversation,
    contract: care_access.CareContract,
    area: Optional[tuple[int, str]],
    roles: Sequence[str],
    actor_id: Optional[int],
    now: datetime,
) -> int:
    """Dzwonek ``care_demand_signal`` do DL klienta (bez autora, raz na 7 dni)."""

    from app.services.care.structure_proposals import client_leads  # noqa: PLC0415
    from app.services.hr.notify import notify_each  # noqa: PLC0415

    area_id = area[0] if area else None
    leads = (await client_leads(db, [contract.client_id])).get(contract.client_id, [])
    if not leads:
        return 0
    recent = await _recent_recipients(
        db, client_id=contract.client_id, area_id=area_id, now=now
    )
    key = board_state.demand_key(contract.client_id, conversation.id)
    return await notify_each(
        db,
        [lead for lead in leads if lead not in recent],
        exclude=[actor_id],
        title="Popyt do sprawdzenia",
        message=notify_message(
            contract.client_name,
            area[1] if area else None,
            roles,
            contract.candidate_name,
        ),
        ntype=NotificationType.care_demand_signal,
        related_entity_type="client",
        related_entity_id=contract.client_id,
        link=notify_link(key, area_id),
        log_tag="care",
    )


# ── Rozstrzygnięcie ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Resolution:
    key: str
    outcome: str  # confirmed | not_now | stale
    role: Optional[str] = None
    headcount: Optional[int] = None
    start_month: Optional[str] = None
    skill_ids: tuple[int, ...] = ()


def jobs_new_url(
    *,
    client_id: int,
    hm_contact_id: Optional[int],
    skill_ids: Sequence[int],
    title: Optional[str],
) -> str:
    """``/jobs/new`` z klientem, hiring managerem, technologiami i nazwą.

    ``/jobs/new`` wypełnia tylko puste pola (``?from=`` ma pierwszeństwo).
    """

    params: list[tuple[str, str]] = [("client", str(client_id))]
    if hm_contact_id is not None:
        params.append(("hm", str(hm_contact_id)))
    ids = list(dict.fromkeys(int(sid) for sid in skill_ids))
    if ids:
        params.append(("skills", ",".join(str(sid) for sid in ids)))
    cleaned = " ".join((title or "").split())
    if cleaned:
        params.append(("title", cleaned[:ROLE_MAX]))
    return "/jobs/new?" + urlencode(params, quote_via=quote, safe=",")


async def resolve(
    db: AsyncSession,
    *,
    client_id: int,
    resolution: Resolution,
    actor_id: int,
    today: date,
    now: datetime,
) -> list[str]:
    """Zapisuje rozstrzygnięcie dla wszystkich źródeł karty; zwraca ich klucze."""

    from fastapi import HTTPException, status  # noqa: PLC0415

    parsed = board_state.parse_key(resolution.key)
    if parsed is None or parsed.kind != "demand" or parsed.ids[0] != client_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, UNKNOWN_SIGNAL)
    signals = await signals_for_clients(db, [client_id], today=today)
    states = await board_state.states_for(db, (s.key for s in signals))
    alive = [s for s in signals if visible(states.get(s.key), today)]
    # Karta na tablicy to grupa nierozstrzygniętych sygnałów (jak ``open_groups``);
    # już rozstrzygnięty sygnał (zmiana zdania) zmienia tylko siebie.
    group = next(
        (g for g in group_signals(alive) if resolution.key in g.keys), None
    ) or next((Group([s]) for s in signals if s.key == resolution.key), None)
    if group is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, UNKNOWN_SIGNAL)
    if resolution.outcome == "not_now":
        column_value, retry_on = "waiting", today + timedelta(days=NOT_NOW_DAYS)
    else:
        column_value, retry_on = "done", None
    for key in group.keys:
        await board_state.save(
            db,
            key=key,
            kind="demand",
            column_value=column_value,
            retry_on=retry_on,
            outcome=resolution.outcome,
            actor_id=actor_id,
            now=now,
        )
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="client",
        entity_id=client_id,
        action="care.demand_resolved",
        details={
            "keys": group.keys,
            "outcome": resolution.outcome,
            "skills": len(resolution.skill_ids),
        },
    )
    return group.keys
