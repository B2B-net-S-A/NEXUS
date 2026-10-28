"""Odejście rekrutera: jego kandydatów domyka Delivery Lead rekrutacji.

Prośba Artura z 28.10.2026. Na kopii produkcji z 22.10 608 żywych par
w otwartych rekrutacjach (19%) prowadziły wyłączone konta, a nikt nie
wiedział, że to jego sprawa: „Dezaktywuj” w Ustawieniach niczego nie
przekazywał. Decyzje Artura 28.10.2026 (makiety:
https://claude.ai/artifact/XgaQS3c9PTRoNahBb2FuPx):

* każde wyłączenie konta (Ustawienia, sprawa odejścia, synchronizacja
  z Compassem, SSO) dzieli żywe pary osoby po rekrutacjach: DL rekrutacji,
  bez niego główny DL klienta, bez niego Head of Recruitment;
* DL domyka sam (bez przekazywania dalej) w ramach obowiązków — bez Ligi,
  KPI i premii. Dlatego „Prowadzi” pary zostaje przy osobie, która odeszła:
  przypinamy ją w ``candidate_job_owners``, więc ``credited_nexus``
  i ``placement_bonuses.load_verifiers`` nie przeniosą zasługi na DL-a,
  nawet gdy to on da „Zweryfikowany”. DL dostaje opiekę: kafel na pulpicie,
  znacznik i filtr na Tablicy, follow-upy i domyślne rozmowy;
* mail i dzwonek od razu, przypomnienie po 5 dniach roboczych, po 10 licznik
  per DL dla Head of Recruitment;
* tylko nowe odejścia — pary osób wyłączonych przed wdrożeniem zostają.

Opieka jest otwarta, dopóki para żyje (ostatni etap nie jest zamknięciem ani
zatrudnieniem), rekrutacja jest otwarta, konto dalej wyłączone, a „Prowadzi”
wskazuje osobę, która odeszła. Wiersz zostaje jako ślad.

Reguła: ``docs/claude/rekrutacja-tablica/odejscie-rekrutera-opieka-delivery-leada.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import is_business_day
from app.models.activity import Activity
from app.models.candidate_job_owner import CandidateJobOwner, CandidateJobOwnerEvent
from app.models.client import Client
from app.models.notification import NotificationType
from app.models.pair_departure_care import PairDepartureCare
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.autofill_decisions import business_days_since
from app.services.board_stage_badges import board_column_for

logger = logging.getLogger(__name__)

#: Przypomnienie DL-owi po tylu dniach roboczych od przejęcia.
REMIND_AFTER_DAYS = 5
#: Po tylu dniach roboczych Head of Recruitment widzi licznik per DL.
ESCALATE_AFTER_DAYS = 10
#: Ślad wyłączenia konta, od którego pętla nadrabia drogi bez wywołania
#: wprost (Compass, SSO). Starsze odejścia zostają — decyzja Artura 28.10.
SWEEP_SINCE = datetime(2026, 10, 28, 22, 0, tzinfo=timezone.utc)
DEACTIVATION_TRACES: tuple[str, ...] = (
    "user_deactivated",
    "hr_lifecycle_deactivated",
    "compass_lifecycle_deactivated",
    "sso_aad_role_denied",
    "admin_aad_role_denied",
    "m365_account_gone_deactivated",
    "active_changed",
)
#: Ślad przekazania na koncie osoby — pętla nie liczy jej drugi raz.
HANDED_OVER_ACTION = "departure_care_assigned"
LINK = "/departed-care"

#: Kolumny Tablicy żywej pary, od najbliższej klienta (kolejność listy).
LIVE_COLUMNS: tuple[str, ...] = (
    "contract",
    "client_interview",
    "cv_sent",
    "cv_qc",
    "verified",
    "screening",
    "new",
)
COLUMN_LABELS: dict[str, str] = {
    "contract": "umowa",
    "client_interview": "rozmowa u klienta",
    "cv_sent": "CV wysłane",
    "cv_qc": "QC CV",
    "verified": "zweryfikowani",
    "screening": "screening",
    "new": "nowi",
}
VIA_LABELS: dict[str, str] = {
    "job_dl": "Delivery Lead rekrutacji",
    "client_dl": "główny Delivery Lead klienta",
    "hor": "Head of Recruitment",
}

# Żywe pary jednej osoby w otwartych rekrutacjach — „Prowadzi” liczone jak
# w „Moich ludziach”: przypisanie, potem pierwszy weryfikujący, potem osoba,
# która dodała. Zakres zaczyna od JEJ wierszy (indeks po ``moved_by``).
_OWNED_LIVE_SQL = text(
    """
    WITH scope AS (
        SELECT DISTINCT candidate_id, job_id
        FROM candidate_stages
        WHERE moved_by = :uid
        UNION
        SELECT candidate_id, job_id
        FROM candidate_job_owners
        WHERE owner_user_id = :uid
    ),
    cur AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.candidate_id, cs.job_id, cs.stage::text AS stage, cs.moved_at,
               d.name AS stage_name, d.category::text AS stage_category,
               d.terminal_type::text AS stage_terminal_type
        FROM candidate_stages cs
        JOIN scope p ON p.candidate_id = cs.candidate_id AND p.job_id = cs.job_id
        LEFT JOIN pipeline_stage_defs d ON d.id = cs.stage_def_id
        ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
    ),
    first_row AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.candidate_id, cs.job_id, cs.moved_by
        FROM candidate_stages cs
        JOIN scope p ON p.candidate_id = cs.candidate_id AND p.job_id = cs.job_id
        ORDER BY cs.candidate_id, cs.job_id, cs.moved_at, cs.id
    ),
    first_verified AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.candidate_id, cs.job_id, cs.moved_by
        FROM candidate_stages cs
        JOIN scope p ON p.candidate_id = cs.candidate_id AND p.job_id = cs.job_id
        WHERE cs.stage = 'verified' AND cs.verification_status = 'active'
        ORDER BY cs.candidate_id, cs.job_id, cs.moved_at, cs.id
    )
    SELECT c.candidate_id, c.job_id, c.stage, c.moved_at, c.stage_name,
           c.stage_category, c.stage_terminal_type,
           j.delivery_lead_id, j.client_id
    FROM cur c
    JOIN jobs j ON j.id = c.job_id AND j.status <> 'closed'
    LEFT JOIN candidate_job_owners o
      ON o.candidate_id = c.candidate_id AND o.job_id = c.job_id
    LEFT JOIN first_verified v
      ON v.candidate_id = c.candidate_id AND v.job_id = c.job_id
    LEFT JOIN first_row f
      ON f.candidate_id = c.candidate_id AND f.job_id = c.job_id
    WHERE COALESCE(o.owner_user_id, v.moved_by, f.moved_by) = :uid
      AND c.stage NOT IN ('rejected', 'withdrawn', 'hired', 'onboarding')
    """
)

# Otwarta opieka: para żyje, rekrutacja otwarta, konto wyłączone, „Prowadzi”
# dalej przy osobie, która odeszła. ``{where}`` zawęża do opiekuna/osoby/par.
_OPEN_CARE_SQL = """
    SELECT d.candidate_id, d.job_id, d.departed_user_id, d.caretaker_user_id,
           d.via, d.created_at, d.reminded_at,
           cur.stage, cur.moved_at, cur.stage_name, cur.stage_category,
           cur.stage_terminal_type,
           j.title AS job_title, j.working_title AS job_working_title,
           j.client_id, COALESCE(cl.display_name, cl.name) AS client_name,
           TRIM(CONCAT_WS(' ', ca.name, ca.lastname)) AS candidate_name,
           du.name AS departed_name, cu.name AS caretaker_name
    FROM pair_departure_care d
    JOIN users du ON du.id = d.departed_user_id AND du.is_active IS NOT TRUE
    JOIN users cu ON cu.id = d.caretaker_user_id
    JOIN candidate_job_owners o
      ON o.candidate_id = d.candidate_id AND o.job_id = d.job_id
     AND o.owner_user_id = d.departed_user_id
    JOIN jobs j ON j.id = d.job_id AND j.status <> 'closed'
    LEFT JOIN clients cl ON cl.id = j.client_id
    JOIN candidates ca ON ca.id = d.candidate_id
    JOIN LATERAL (
        SELECT cs.stage::text AS stage, cs.moved_at, sd.name AS stage_name,
               sd.category::text AS stage_category,
               sd.terminal_type::text AS stage_terminal_type
        FROM candidate_stages cs
        LEFT JOIN pipeline_stage_defs sd ON sd.id = cs.stage_def_id
        WHERE cs.candidate_id = d.candidate_id AND cs.job_id = d.job_id
        ORDER BY cs.moved_at DESC, cs.id DESC
        LIMIT 1
    ) cur ON cur.stage NOT IN ('rejected', 'withdrawn', 'hired', 'onboarding')
    WHERE {where}
    ORDER BY d.created_at, d.job_id, d.candidate_id
"""


@dataclass(frozen=True)
class LivePair:
    candidate_id: int
    job_id: int
    column: str
    moved_at: Optional[datetime]
    delivery_lead_id: Optional[int]
    client_id: Optional[int]


@dataclass(frozen=True)
class Caretaker:
    user_id: int
    via: str


@dataclass
class CareGroup:
    """Część jednej osoby, która odeszła, u jednego opiekuna."""

    caretaker_id: int
    caretaker_name: str
    via: set[str] = field(default_factory=set)
    pairs: int = 0
    job_ids: set[int] = field(default_factory=set)
    clients: list[str] = field(default_factory=list)
    columns: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CareRow:
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_name: Optional[str]
    column: str
    moved_at: Optional[datetime]
    departed_user_id: int
    departed_name: str
    caretaker_user_id: int
    caretaker_name: str
    via: str
    since: datetime
    reminded_at: Optional[datetime]


def _column(row: Any) -> str:
    return board_column_for(
        row.stage_name,
        row.stage,
        category=row.stage_category,
        terminal_type=row.stage_terminal_type,
    )


def short_name(name: Optional[str]) -> str:
    from app.services.job_ad.reminders import short_name as _short  # noqa: PLC0415

    return _short(name)


def people_phrase(count: int) -> str:
    """„1 osoba”, „3 osoby”, „12 osób”."""
    if count == 1:
        return "1 osoba"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} osoby"
    return f"{count} osób"


def jobs_phrase(count: int) -> str:
    """„1 rekrutacji”, „7 rekrutacjach” (miejscownik po „w”)."""
    return "1 rekrutacji" if count == 1 else f"{count} rekrutacjach"


def columns_text(columns: dict[str, int]) -> str:
    """„3 rozmowa u klienta, 18 CV wysłane, 41 nowi” — od najbliższej klienta."""
    return ", ".join(
        f"{columns[c]} {COLUMN_LABELS[c]}" for c in LIVE_COLUMNS if columns.get(c)
    )


# ── Kto przejmuje ────────────────────────────────────────────────────────────


async def live_pairs_of(db: AsyncSession, user_id: int) -> list[LivePair]:
    rows = (await db.execute(_OWNED_LIVE_SQL, {"uid": user_id})).all()
    pairs = []
    for row in rows:
        column = _column(row)
        if column not in LIVE_COLUMNS:
            continue
        pairs.append(
            LivePair(
                candidate_id=row.candidate_id,
                job_id=row.job_id,
                column=column,
                moved_at=row.moved_at,
                delivery_lead_id=row.delivery_lead_id,
                client_id=row.client_id,
            )
        )
    return pairs


async def _hor_id(db: AsyncSession, exclude: int) -> Optional[int]:
    return await db.scalar(
        select(User.id)
        .where(
            User.is_active.is_(True),
            User.id != exclude,
            or_(
                User.role == UserRole.head_of_recruitment,
                User.roles.contains([UserRole.head_of_recruitment.value]),
            ),
        )
        .order_by(User.id)
        .limit(1)
    )


async def resolve_caretakers(
    db: AsyncSession, pairs: Iterable[LivePair], *, departed_id: int
) -> dict[int, Caretaker]:
    """Rekrutacja → opiekun: DL rekrutacji, główny DL klienta, Head of Recruitment.

    Opiekun to aktywne konto inne niż osoba, która odeszła. Brak wszystkich
    trzech = rekrutacja bez opiekuna (nie powinno się zdarzyć; log).
    """
    jobs: dict[int, tuple[Optional[int], Optional[int]]] = {
        p.job_id: (p.delivery_lead_id, p.client_id) for p in pairs
    }
    if not jobs:
        return {}
    dl_ids = {dl for dl, _ in jobs.values() if dl is not None}
    active = set(
        (
            await db.scalars(
                select(User.id).where(
                    User.id.in_(dl_ids or {0}),
                    User.is_active.is_(True),
                    User.id != departed_id,
                )
            )
        ).all()
    )
    client_ids = {cid for _, cid in jobs.values() if cid is not None}
    heads: dict[int, int] = {}
    if client_ids:
        for client_id, user_id in (
            await db.execute(
                select(
                    DeliveryLeadClientAssignment.client_id,
                    DeliveryLeadClientAssignment.delivery_lead_user_id,
                )
                .join(
                    User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id
                )
                .where(
                    DeliveryLeadClientAssignment.client_id.in_(client_ids),
                    User.is_active.is_(True),
                    User.id != departed_id,
                )
                .order_by(
                    DeliveryLeadClientAssignment.is_head.desc(),
                    DeliveryLeadClientAssignment.id,
                )
            )
        ).all():
            heads.setdefault(client_id, user_id)
    hor: Optional[int] = None
    hor_loaded = False
    out: dict[int, Caretaker] = {}
    for job_id, (dl_id, client_id) in jobs.items():
        if dl_id in active:
            out[job_id] = Caretaker(dl_id, "job_dl")
        elif client_id in heads:
            out[job_id] = Caretaker(heads[client_id], "client_dl")
        else:
            if not hor_loaded:
                hor, hor_loaded = await _hor_id(db, departed_id), True
            if hor is not None:
                out[job_id] = Caretaker(hor, "hor")
            else:
                logger.warning(
                    "departure_care: rekrutacja %s bez DL-a, DL-a klienta i HoR", job_id
                )
    return out


async def _group(
    db: AsyncSession, pairs: list[LivePair], caretakers: dict[int, Caretaker]
) -> list[CareGroup]:
    groups: dict[int, CareGroup] = {}
    client_by_job: dict[int, Optional[int]] = {}
    for pair in pairs:
        caretaker = caretakers.get(pair.job_id)
        if caretaker is None:
            continue
        group = groups.setdefault(caretaker.user_id, CareGroup(caretaker.user_id, ""))
        group.via.add(caretaker.via)
        group.pairs += 1
        group.job_ids.add(pair.job_id)
        group.columns[pair.column] = group.columns.get(pair.column, 0) + 1
        client_by_job[pair.job_id] = pair.client_id
    if not groups:
        return []
    names = dict(
        (await db.execute(select(User.id, User.name).where(User.id.in_(groups)))).all()
    )
    wanted_clients = {c for c in client_by_job.values() if c}
    client_names = {
        cid: display or name
        for cid, display, name in (
            await db.execute(
                select(Client.id, Client.display_name, Client.name).where(
                    Client.id.in_(wanted_clients or {0})
                )
            )
        ).all()
    }
    for group in groups.values():
        group.caretaker_name = (
            names.get(group.caretaker_id) or f"Konto #{group.caretaker_id}"
        )
        seen = dict.fromkeys(
            client_names[client_by_job[j]]
            for j in sorted(group.job_ids)
            if client_by_job.get(j) in client_names
        )
        group.clients = list(seen)
    return sorted(groups.values(), key=lambda g: (-g.pairs, g.caretaker_name))


def group_payload(group: CareGroup) -> dict[str, Any]:
    return {
        "user_id": group.caretaker_id,
        "name": group.caretaker_name,
        "via": sorted(group.via),
        "pairs": group.pairs,
        "jobs": len(group.job_ids),
        "clients": group.clients,
        "columns": {c: group.columns[c] for c in LIVE_COLUMNS if c in group.columns},
    }


async def preview(db: AsyncSession, user: User) -> dict[str, Any]:
    """Co zostaje po koncie i kto to przejmie — okno „Wyłącz konto”."""
    pairs = await live_pairs_of(db, user.id)
    caretakers = await resolve_caretakers(db, pairs, departed_id=user.id)
    groups = await _group(db, pairs, caretakers)
    return {
        "user_id": user.id,
        "pairs": len(pairs),
        "jobs": len({p.job_id for p in pairs}),
        "unassigned": sum(1 for p in pairs if p.job_id not in caretakers),
        "caretakers": [group_payload(g) for g in groups],
    }


# ── Przekazanie ──────────────────────────────────────────────────────────────


def notice_text(departed_name: Optional[str], group: CareGroup) -> tuple[str, str]:
    """Tytuł i treść dzwonka (a więc i maila) dla jednego opiekuna."""
    who = short_name(departed_name)
    title = f"Odejście z firmy: {who} — {people_phrase(group.pairs)} do domknięcia"
    where = f" ({', '.join(group.clients)})" if group.clients else ""
    message = (
        f"Konto {who} jest wyłączone. Kandydatów, których ta osoba prowadziła "
        f"w {jobs_phrase(len(group.job_ids))}{where}, domykasz Ty: "
        f"{columns_text(group.columns)}. Zacznij od najbliższych klienta. "
        "„Prowadzi” zostaje bez zmian — to nie liczy się do Ligi, KPI ani premii."
    )
    return title, message


def reminder_text(departed_name: Optional[str], count: int) -> tuple[str, str]:
    who = short_name(departed_name)
    title = f"Przypomnienie: {people_phrase(count)} do domknięcia — odejście: {who}"
    message = (
        f"Minęło {REMIND_AFTER_DAYS} dni roboczych, odkąd przejmujesz kandydatów "
        f"osoby, która odeszła z firmy ({who}). Doprowadź ich do końca albo odrzuć "
        f"z powodem. Po {ESCALATE_AFTER_DAYS} dniach roboczych Head of Recruitment "
        "widzi licznik."
    )
    return title, message


async def _emit(
    db: AsyncSession, *, user_id: int, departed_id: int, title: str, message: str
) -> bool:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    try:
        async with db.begin_nested():
            row = await emit(
                db,
                user_id=user_id,
                title=title,
                message=message,
                ntype=NotificationType.departed_pairs_care,
                related_entity_type="user",
                related_entity_id=departed_id,
                link=f"{LINK}?from={departed_id}",
            )
        return row is not None
    except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć przekazania
        logger.exception(
            "departure_care: dzwonek dla user_id=%s (odejście %s) nie powstał",
            user_id,
            departed_id,
        )
        return False


async def hand_over(
    db: AsyncSession,
    user: User,
    *,
    actor_id: Optional[int],
    now: Optional[datetime] = None,
) -> list[CareGroup]:
    """Dzieli żywe pary wyłączonego konta między opiekunów. Idempotentne.

    Woła każda droga wyłączenia (``deactivate_account``, PATCH admina) przed
    commitem, a pętla nadrabia pozostałe. Nie commituje. Zapisuje ślad na
    koncie (``departure_care_assigned``) także przy zerze par.
    """
    if user.is_active:
        return []
    now = now or datetime.now(timezone.utc)
    pairs = await live_pairs_of(db, user.id)
    if pairs:
        taken = set(
            (
                await db.execute(
                    select(
                        PairDepartureCare.candidate_id, PairDepartureCare.job_id
                    ).where(
                        tuple_(
                            PairDepartureCare.candidate_id, PairDepartureCare.job_id
                        ).in_([(p.candidate_id, p.job_id) for p in pairs])
                    )
                )
            ).all()
        )
        pairs = [p for p in pairs if (p.candidate_id, p.job_id) not in taken]
    caretakers = await resolve_caretakers(db, pairs, departed_id=user.id)
    pairs = [p for p in pairs if p.job_id in caretakers]
    groups = await _group(db, pairs, caretakers)
    if pairs:
        names = {g.caretaker_id: g.caretaker_name for g in groups}
        await db.execute(
            pg_insert(PairDepartureCare)
            .values(
                [
                    {
                        "candidate_id": p.candidate_id,
                        "job_id": p.job_id,
                        "departed_user_id": user.id,
                        "caretaker_user_id": caretakers[p.job_id].user_id,
                        "via": caretakers[p.job_id].via,
                        "created_at": now,
                        "updated_at": now,
                    }
                    for p in pairs
                ]
            )
            .on_conflict_do_nothing()
        )
        # „Prowadzi” zostaje przy osobie, która odeszła — zasługa i premia
        # nie przechodzą na DL-a, który domyka (decyzja Artura 28.10).
        pinned = (
            await db.execute(
                pg_insert(CandidateJobOwner)
                .values(
                    [
                        {
                            "candidate_id": p.candidate_id,
                            "job_id": p.job_id,
                            "owner_user_id": user.id,
                            "previous_owner_id": user.id,
                            "assigned_by": actor_id,
                            "reason": _pin_reason(
                                names.get(caretakers[p.job_id].user_id)
                            ),
                            "created_at": now,
                            "updated_at": now,
                        }
                        for p in pairs
                    ]
                )
                .on_conflict_do_nothing()
                .returning(CandidateJobOwner.candidate_id, CandidateJobOwner.job_id)
            )
        ).all()
        pinned_set = set(pinned)
        for p in pairs:
            if (p.candidate_id, p.job_id) in pinned_set:
                db.add(
                    CandidateJobOwnerEvent(
                        candidate_id=p.candidate_id,
                        job_id=p.job_id,
                        owner_user_id=user.id,
                        previous_owner_id=user.id,
                        assigned_by=actor_id,
                        reason=_pin_reason(names.get(caretakers[p.job_id].user_id)),
                        created_at=now,
                    )
                )
    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action=HANDED_OVER_ACTION,
            user_id=actor_id,
            details={
                "pairs": len(pairs),
                "caretakers": {str(g.caretaker_id): g.pairs for g in groups},
            },
        )
    )
    await db.flush()
    for group in groups:
        title, message = notice_text(user.name, group)
        await _emit(
            db,
            user_id=group.caretaker_id,
            departed_id=user.id,
            title=title,
            message=message,
        )
    return groups


def _pin_reason(caretaker_name: Optional[str]) -> str:
    who = short_name(caretaker_name) if caretaker_name else "Delivery Lead"
    return f"Odejście z firmy — domyka {who}; „Prowadzi” bez zmian"


async def hand_over_safely(
    db: AsyncSession, user: User, *, actor_id: Optional[int]
) -> list[CareGroup]:
    """Jak ``hand_over``, ale awaria nie zatrzymuje wyłączenia konta — pętla
    (``run``) nadrobi przekazanie przy następnym ticku."""
    try:
        async with db.begin_nested():
            return await hand_over(db, user, actor_id=actor_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "departure_care: przekazanie po user_id=%s nie wyszło", user.id
        )
        return []


# ── Odczyt opieki ────────────────────────────────────────────────────────────


async def open_care(
    db: AsyncSession,
    *,
    caretaker_id: Optional[int] = None,
    departed_id: Optional[int] = None,
    pairs: Optional[list[tuple[int, int]]] = None,
    job_id: Optional[int] = None,
) -> list[CareRow]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if caretaker_id is not None:
        clauses.append("d.caretaker_user_id = :caretaker")
        params["caretaker"] = caretaker_id
    if departed_id is not None:
        clauses.append("d.departed_user_id = :departed")
        params["departed"] = departed_id
    if job_id is not None:
        clauses.append("d.job_id = :job")
        params["job"] = job_id
    if pairs is not None:
        if not pairs:
            return []
        clauses.append(
            "(d.candidate_id, d.job_id) IN (SELECT * FROM unnest("
            "CAST(:cids AS int[]), CAST(:jids AS int[])))"
        )
        params["cids"] = [c for c, _ in pairs]
        params["jids"] = [j for _, j in pairs]
    sql = text(_OPEN_CARE_SQL.format(where=" AND ".join(clauses) or "TRUE"))
    rows = (await db.execute(sql, params)).all()
    out = []
    for row in rows:
        column = _column(row)
        if column not in LIVE_COLUMNS:
            continue
        out.append(
            CareRow(
                candidate_id=row.candidate_id,
                candidate_name=row.candidate_name or f"Kandydat #{row.candidate_id}",
                job_id=row.job_id,
                job_title=row.job_working_title or row.job_title,
                client_name=row.client_name,
                column=column,
                moved_at=row.moved_at,
                departed_user_id=row.departed_user_id,
                departed_name=row.departed_name or f"Konto #{row.departed_user_id}",
                caretaker_user_id=row.caretaker_user_id,
                caretaker_name=row.caretaker_name or f"Konto #{row.caretaker_user_id}",
                via=row.via,
                since=row.created_at,
                reminded_at=row.reminded_at,
            )
        )
    return out


async def caretaker_ids(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], int]:
    """Opiekun otwartej opieki dla par — follow-upy i domyślne rozmowy."""
    wanted = list(dict.fromkeys(pairs))
    if not wanted:
        return {}
    rows = await open_care(db, pairs=wanted)
    return {(r.candidate_id, r.job_id): r.caretaker_user_id for r in rows}


def _column_rank(column: str) -> int:
    return LIVE_COLUMNS.index(column)


def rows_payload(rows: list[CareRow]) -> list[dict[str, Any]]:
    """Grupy per osoba, która odeszła — lista „Po osobach, które odeszły”."""
    by_departed: dict[int, list[CareRow]] = {}
    for row in rows:
        by_departed.setdefault(row.departed_user_id, []).append(row)
    groups = []
    for departed_id, items in by_departed.items():
        items.sort(key=lambda r: (_column_rank(r.column), r.job_id, r.candidate_name))
        columns: dict[str, int] = {}
        for r in items:
            columns[r.column] = columns.get(r.column, 0) + 1
        clients = list(dict.fromkeys(r.client_name for r in items if r.client_name))
        groups.append(
            {
                "departed_user_id": departed_id,
                "departed_name": items[0].departed_name,
                "since": min(r.since for r in items),
                "pairs": len(items),
                "jobs": len({r.job_id for r in items}),
                "clients": clients,
                "columns": {c: columns[c] for c in LIVE_COLUMNS if c in columns},
                "rows": [
                    {
                        "candidate_id": r.candidate_id,
                        "candidate_name": r.candidate_name,
                        "job_id": r.job_id,
                        "job_title": r.job_title,
                        "client_name": r.client_name,
                        "column": r.column,
                        "moved_at": r.moved_at,
                        "caretaker_user_id": r.caretaker_user_id,
                        "caretaker_name": r.caretaker_name,
                    }
                    for r in items
                ],
            }
        )
    groups.sort(key=lambda g: (-g["pairs"], g["departed_name"]))
    return groups


async def overdue_by_caretaker(
    db: AsyncSession, now: Optional[datetime] = None
) -> list[dict[str, Any]]:
    """Niedomknięte pary po ``ESCALATE_AFTER_DAYS`` dniach roboczych — per opiekun."""
    now = now or datetime.now(timezone.utc)
    counts: dict[int, dict[str, Any]] = {}
    for row in await open_care(db):
        if business_days_since(row.since, now) < ESCALATE_AFTER_DAYS:
            continue
        entry = counts.setdefault(
            row.caretaker_user_id,
            {
                "user_id": row.caretaker_user_id,
                "name": row.caretaker_name,
                "pairs": 0,
                "departed": [],
                "since": row.since,
            },
        )
        entry["pairs"] += 1
        entry["since"] = min(entry["since"], row.since)
        if row.departed_name not in entry["departed"]:
            entry["departed"].append(row.departed_name)
    return sorted(counts.values(), key=lambda e: (-e["pairs"], e["name"]))


# ── Pętla: nadrabianie i przypomnienia ───────────────────────────────────────


async def sweep(db: AsyncSession) -> int:
    """Konta wyłączone po ``SWEEP_SINCE`` bez śladu przekazania (Compass, SSO)."""
    handed = select(Activity.entity_id).where(
        Activity.entity_type == "user", Activity.action == HANDED_OVER_ACTION
    )
    users = (
        await db.scalars(
            select(User)
            .where(
                User.is_active.is_not(True),
                User.id.in_(
                    select(Activity.entity_id).where(
                        Activity.entity_type == "user",
                        Activity.action.in_(DEACTIVATION_TRACES),
                        Activity.created_at >= SWEEP_SINCE,
                    )
                ),
                User.id.not_in(handed),
            )
            .order_by(User.id)
        )
    ).all()
    done = 0
    for user in users:
        groups = await hand_over_safely(db, user, actor_id=None)
        done += sum(g.pairs for g in groups)
    return done


async def send_reminders(db: AsyncSession, now: datetime) -> int:
    """Jedno przypomnienie per opiekun i odejście, w dzień roboczy 8–17."""
    local = now.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    if not (8 <= local.hour < 17) or not is_business_day(local):
        return 0
    due: dict[tuple[int, int], list[CareRow]] = {}
    for row in await open_care(db):
        if row.reminded_at is not None:
            continue
        if business_days_since(row.since, now) < REMIND_AFTER_DAYS:
            continue
        due.setdefault((row.caretaker_user_id, row.departed_user_id), []).append(row)
    sent = 0
    for (caretaker_id, departed_id), rows in due.items():
        title, message = reminder_text(rows[0].departed_name, len(rows))
        if await _emit(
            db,
            user_id=caretaker_id,
            departed_id=departed_id,
            title=title,
            message=message,
        ):
            sent += 1
        await db.execute(
            PairDepartureCare.__table__.update()
            .where(
                tuple_(PairDepartureCare.candidate_id, PairDepartureCare.job_id).in_(
                    [(r.candidate_id, r.job_id) for r in rows]
                )
            )
            .values(reminded_at=now, updated_at=now)
        )
    return sent


async def run(db: AsyncSession, now: datetime) -> int:
    """Tick pętli triggerów. Nie commituje."""
    try:
        async with db.begin_nested():
            handed = await sweep(db)
        async with db.begin_nested():
            reminded = await send_reminders(db, now)
    except Exception:  # noqa: BLE001 — opieka nigdy nie psuje ticku
        logger.exception("departure_care: tick nie wyszedł")
        return 0
    return handed + reminded
