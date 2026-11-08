"""Zamknięcie rekrutacji daje znać rekruterom osób, które czekają (28.10.2026).

Zgłoszenie Delivery Leada z 28.10.2026: rekruterka nie wiedziała, że
rekrutacja jej wysłanych do klienta osób została zamknięta, więc nie dała im
znać. Zamknięcie nie wysyłało nikomu nic (``park_team(notify=False)``). Na
kopii produkcji z 22.10: z 61 rekrutacji zamkniętych 12–22.10 w 43 zostało
216 osób od „CV wysłane” w górę u 29 rekruterów.

Decyzje Artura 28.10.2026:

* odbiorca = osoba, która prowadzi kandydata (``prowadzi-przypisanie-osoby.md``):
  przypisana „Prowadzi”, bez przypisania pierwszy weryfikujący pary
  (``stage_verifier.first_verifier``), a bez weryfikacji ten, kto dodał osobę
  do rekrutacji; bez osoby, która zamyka, i bez kont nieaktywnych;
* tylko osoby, których bieżąca karta stoi w „CV wysłane”, „Rozmowie
  u klienta” albo „Umowie” (``NOTIFY_COLUMNS``) — te, które wiedzą o tej
  rekrutacji od klienta;
* dzwonek w temacie „Rekrutacje” z dymkiem i mail obowiązkowy;
* tylko zamknięcie przez człowieka (okno z powodem i „Edytuj rekrutację”),
  nie ``close_job_core`` — automaty nie mają kogo pytać i zamykają hurtem;
* kandydatom NEXUS nie pisze sam: rekruter odrzuca osobę oknem odrzucenia
  z mailem z własnej skrzynki.

Okno zamykania pokazuje tę samą listę przed zamknięciem (``recipients``
w odpowiedzi 409 ``active_cards_warning``).

Reguła: ``docs/claude/rekrutacja-tablica/zamkniecie-rekrutacji-osoby-w-toku.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services.board_stage_badges import board_column_for
from app.services.job_opening import in_opening
from app.services.stage_verifier import first_verifier

logger = logging.getLogger(__name__)

# Kolumny Tablicy od „CV wysłane” w górę, bez „Zatrudnionych” i „Zamkniętych”.
NOTIFY_COLUMNS: tuple[str, ...] = ("cv_sent", "client_interview", "contract")
COLUMN_LABELS: dict[str, str] = {
    "cv_sent": "CV wysłane",
    "client_interview": "Rozmowa u klienta",
    "contract": "Umowa",
}
# Lustro `JOB_CLOSE_REASONS` we froncie (`types/client-profile.ts`).
CLOSE_REASON_LABELS: dict[str, str] = {
    "filled_by_us": "Obsadzone przez nas",
    "competitor": "Klient wybrał kandydata innej firmy",
    "duplicate": "Duplikat albo założona przez pomyłkę",
    "internal_hire": "Klient zatrudnił kogoś wewnętrznie",
    "budget": "Klient anulował projekt / brak budżetu",
    "paused": "Wstrzymana przez klienta",
    "client_ghosted": "Klient przestał odpowiadać",
    "no_match": "Nie znaleźliśmy kandydata",
    "no_activity": "28 dni bez ruchu — zamknął NEXUS",
    "other": "Inny",
}
# Tyle nazwisk w treści dzwonka i maila; reszta jako „i N innych”.
NAMES_MAX = 8


@dataclass(frozen=True)
class WaitingCard:
    candidate_id: int
    user_id: int
    column: str


@dataclass(frozen=True)
class WaitingPerson:
    candidate_id: int
    name: str
    column: str


@dataclass(frozen=True)
class Recipient:
    user_id: int
    name: str
    people: tuple[WaitingPerson, ...]


def waiting_cards(
    stages: Iterable[Any],
    owners: Optional[dict[int, int]] = None,
    *,
    columns: Optional[Sequence[str]] = NOTIFY_COLUMNS,
    since: Optional[datetime] = None,
) -> list[WaitingCard]:
    """Karty od „CV wysłane” w górę z osobą karty — bez bazy.

    ``stages`` = wiersze etapów JEDNEJ rekrutacji z polami ``candidate_id``,
    ``stage``, ``moved_by``, ``moved_at``, ``approved_at``, ``id``,
    ``stage_name``, ``stage_category``, ``stage_terminal_type``, w dowolnej
    kolejności. ``owners`` = przypisania „Prowadzi” (kandydat → osoba).
    Bieżąca karta = najnowszy wiersz pary (jak Tablica), osoba karty =
    przypisana, potem pierwszy weryfikujący, potem autor najstarszego wiersza.
    ``columns=None`` = każda karta w toku (bez „Zamkniętych” i „Zatrudnionych”).
    ``since`` = początek bieżącego otwarcia (``job_opening``): karta, której
    najnowszy ruch był przed nim, została w poprzednim otwarciu.
    """
    owners = owners or {}
    by_candidate: dict[int, list[Any]] = {}
    for row in stages:
        by_candidate.setdefault(row.candidate_id, []).append(row)
    cards: list[WaitingCard] = []
    for candidate_id, rows in by_candidate.items():
        rows.sort(key=lambda r: (r.moved_at, r.id))
        latest = rows[-1]
        if not in_opening(latest.moved_at, since):
            continue
        column = board_column_for(
            latest.stage_name,
            getattr(latest.stage, "value", latest.stage),
            category=getattr(latest.stage_category, "value", latest.stage_category),
            terminal_type=getattr(
                latest.stage_terminal_type, "value", latest.stage_terminal_type
            ),
        )
        if columns is None:
            if column in ("closed", "hired"):
                continue
        elif column not in columns:
            continue
        verifier = None
        for row in rows:
            if row.stage == PipelineStage.verified:
                verifier = first_verifier(verifier, row)
        owner = owners.get(candidate_id) or (
            verifier.moved_by if verifier is not None else rows[0].moved_by
        )
        if owner is None:
            continue
        cards.append(WaitingCard(candidate_id, owner, column))
    return cards


def group_recipients(
    cards: Sequence[WaitingCard],
    *,
    user_names: dict[int, str],
    candidate_names: dict[int, str],
    exclude_user_id: Optional[int],
) -> list[Recipient]:
    """Karty → odbiorcy z listą osób. ``user_names`` = tylko aktywne konta."""
    people: dict[int, list[WaitingPerson]] = {}
    for card in cards:
        if card.user_id == exclude_user_id or card.user_id not in user_names:
            continue
        people.setdefault(card.user_id, []).append(
            WaitingPerson(
                card.candidate_id,
                candidate_names.get(card.candidate_id)
                or f"Kandydat #{card.candidate_id}",
                card.column,
            )
        )
    order = {column: i for i, column in enumerate(NOTIFY_COLUMNS)}
    last = len(order)
    recipients = [
        Recipient(
            user_id,
            user_names[user_id],
            tuple(sorted(rows, key=lambda p: (order.get(p.column, last), p.name))),
        )
        for user_id, rows in people.items()
    ]
    return sorted(recipients, key=lambda r: (-len(r.people), r.name))


async def load_recipients(
    db: AsyncSession,
    job_id: int,
    *,
    exclude_user_id: Optional[int],
    columns: Optional[Sequence[str]] = NOTIFY_COLUMNS,
) -> list[Recipient]:
    rows = (
        await db.execute(
            select(
                CandidateStage.id,
                CandidateStage.candidate_id,
                CandidateStage.stage,
                CandidateStage.moved_by,
                CandidateStage.moved_at,
                CandidateStage.approved_at,
                PipelineStageDef.name.label("stage_name"),
                PipelineStageDef.category.label("stage_category"),
                PipelineStageDef.terminal_type.label("stage_terminal_type"),
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(CandidateStage.job_id == job_id)
        )
    ).all()
    from app.services.pair_owner import owners_for_job  # noqa: PLC0415

    opening_started_at = await db.scalar(
        select(Job.cycle_started_at).where(Job.id == job_id)
    )

    assigned = await owners_for_job(db, job_id)
    cards = waiting_cards(
        rows,
        {cid: owner.owner_user_id for cid, owner in assigned.items()},
        columns=columns,
        since=opening_started_at,
    )
    if not cards:
        return []
    user_ids = {card.user_id for card in cards}
    user_names = dict(
        (
            await db.execute(
                select(User.id, User.name).where(
                    User.id.in_(user_ids), User.is_active.is_(True)
                )
            )
        ).all()
    )
    candidate_names = {
        cid: " ".join(" ".join(part for part in (name, lastname) if part).split())
        for cid, name, lastname in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_({card.candidate_id for card in cards})
                )
            )
        ).all()
    }
    return group_recipients(
        cards,
        user_names={uid: name or f"Konto #{uid}" for uid, name in user_names.items()},
        candidate_names=candidate_names,
        exclude_user_id=exclude_user_id,
    )


def recipients_payload(recipients: Sequence[Recipient]) -> list[dict[str, Any]]:
    """Lista odbiorców do okna zamykania (bez nazwisk kandydatów)."""
    payload = []
    for recipient in recipients:
        columns: dict[str, int] = {}
        for person in recipient.people:
            columns[person.column] = columns.get(person.column, 0) + 1
        payload.append(
            {
                "user_id": recipient.user_id,
                "name": recipient.name,
                "people": len(recipient.people),
                "columns": {c: columns[c] for c in NOTIFY_COLUMNS if c in columns},
            }
        )
    return payload


async def active_cards_warning(
    db: AsyncSession,
    job_id: int,
    *,
    actor_id: Optional[int],
    close_reason: Any = None,
    job: Optional[Job] = None,
) -> Optional[dict[str, Any]]:
    """Treść 409 ``active_cards_warning`` z listą odbiorców albo ``None``.

    Przy powodzie, który kończy pary u klienta, dochodzi ``client_end``
    (``job_close_client_cards``): okno pyta, czy je zakończyć.
    """
    from app.services.job_active_cards import load_active_cards  # noqa: PLC0415
    from app.services.job_close_client_cards import (  # noqa: PLC0415
        client_side_cards,
        preview_payload,
    )

    active = await load_active_cards(db, job_id)
    if not active.total:
        return None
    detail = active.warning_detail()
    detail["recipients"] = recipients_payload(
        await load_recipients(db, job_id, exclude_user_id=actor_id)
    )
    if job is not None and close_reason is not None:
        detail["client_end"] = preview_payload(
            await client_side_cards(db, job), close_reason
        )
        if detail["client_end"] is not None:
            detail["message"] = active.message(cards_may_end=True)
    return detail


def _people_dative(count: int) -> str:
    """„1 osobie”, „2 osobom”."""
    return "1 osobie" if count == 1 else f"{count} osobom"


def notice_text(
    recipient: Recipient,
    *,
    job_title: str,
    client_name: Optional[str],
    actor_name: Optional[str],
    reason: Optional[str],
    ended_ids: frozenset[int] = frozenset(),
) -> tuple[str, str]:
    """Tytuł i treść dzwonka (a więc i maila) dla jednego rekrutera.

    ``ended_ids`` = pary, które zamknięcie kończy „przez klienta” (08.11.2026).
    """
    title = f"Rekrutacja zamknięta — daj znać {_people_dative(len(recipient.people))}"
    head = f"{job_title} · {client_name}" if client_name else job_title
    closed = "Zamknięcie"
    if actor_name:
        closed += f": {actor_name}"
    if reason:
        closed += f", powód: {CLOSE_REASON_LABELS.get(reason, reason)}"
    shown = recipient.people[:NAMES_MAX]
    names = ", ".join(f"{p.name} ({COLUMN_LABELS[p.column]})" for p in shown)
    rest = len(recipient.people) - len(shown)
    if rest:
        names += f" i {rest} innych"
    ended = sum(1 for p in recipient.people if p.candidate_id in ended_ids)
    if ended == len(recipient.people):
        tail = (
            f"Twoje osoby: {names}. Ich procesy NEXUS zakończył jako „przez klienta”, "
            "bez maila do kandydatów. Daj im znać."
        )
    elif ended:
        tail = (
            f"Twoje osoby: {names}. Część procesów ({ended}) NEXUS zakończył jako "
            "„przez klienta”, bez maila. Reszta jest dalej w toku. Daj im znać: okno "
            "„Odrzuć” na Tablicy może wysłać mail z Twojej skrzynki."
        )
    else:
        tail = (
            f"Twoje osoby nadal są w procesie: {names}. Daj im znać — okno „Odrzuć” "
            "na Tablicy może wysłać im mail z Twojej skrzynki."
        )
    message = f"{head}. {closed}. {tail}"
    return title, message


async def notify_closed(
    db: AsyncSession,
    job: Job,
    *,
    actor_id: Optional[int],
    ended_ids: frozenset[int] = frozenset(),
) -> list[int]:
    """Dzwonek (i mail obowiązkowy z kolejki) do rekruterów osób w toku.

    Woła trasa po zmianie statusu, przed commitem. Savepoint na osobę:
    nieudane powiadomienie nie cofa zamknięcia.
    """
    from app.services.job_working_title import display_title  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    recipients = await load_recipients(db, job.id, exclude_user_id=actor_id)
    if not recipients:
        return []
    client_name = await db.scalar(
        select(func.coalesce(Client.display_name, Client.name)).where(
            Client.id == job.client_id
        )
    )
    actor_name = (
        await db.scalar(select(User.name).where(User.id == actor_id))
        if actor_id is not None
        else None
    )
    reason = getattr(job.close_reason, "value", job.close_reason)
    sent: list[int] = []
    for recipient in recipients:
        title, message = notice_text(
            recipient,
            job_title=display_title(job),
            client_name=client_name,
            actor_name=actor_name,
            reason=reason,
            ended_ids=ended_ids,
        )
        try:
            async with db.begin_nested():
                row = await emit(
                    db,
                    user_id=recipient.user_id,
                    title=title,
                    message=message,
                    ntype=NotificationType.job_closed_people_waiting,
                    related_entity_type="job",
                    related_entity_id=job.id,
                    link=f"/jobs/{job.id}",
                )
            if row is not None:
                sent.append(recipient.user_id)
        except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć zamknięcia
            logger.exception(
                "job_closed_notices: dzwonek dla user_id=%s job_id=%s nie powstał",
                recipient.user_id,
                job.id,
            )
    return sent


def cpro_notice_text(
    recipient: Recipient,
    *,
    job_title: str,
    client_name: Optional[str],
    request: Optional[str],
    cpro_reason: Optional[str],
) -> tuple[str, str]:
    """Tytuł i treść, gdy rekrutację zamknął mail CPro (02.11.2026)."""
    at_client = [p for p in recipient.people if p.column in NOTIFY_COLUMNS]
    earlier = len(recipient.people) - len(at_client)
    if at_client:
        title = f"CPro zamknęło rekrutację: daj znać {_people_dative(len(at_client))}"
    else:
        title = "CPro zamknęło rekrutację: nie dzwoń już w tej sprawie"
    head = f"{job_title} · {client_name}" if client_name else job_title
    number = f"request {request}" if request else "request"
    parts = [f"{head}. Nordea zamknęła {number} w CPro."]
    if cpro_reason:
        parts.append(f"Powód w CPro: {cpro_reason}.")
    if at_client:
        shown = at_client[:NAMES_MAX]
        names = ", ".join(f"{p.name} ({COLUMN_LABELS[p.column]})" for p in shown)
        rest = len(at_client) - len(shown)
        if rest:
            names += f" i {rest} innych"
        parts.append(f"Twoje osoby, które były u klienta: {names}. Daj im znać.")
    if earlier:
        parts.append(
            f"Pozostałe Twoje osoby w tej rekrutacji: {earlier}. Nie dzwoń już do nich w tej sprawie."
        )
    return title, " ".join(parts)


async def notify_closed_from_cpro(
    db: AsyncSession,
    job: Job,
    *,
    request: Optional[str],
    cpro_reason: Optional[str],
) -> list[int]:
    """Dzwonek i mail do każdego rekrutera z kartą w toku (decyzja Artura 02.11).

    Wyjątek od reguły „automaty nie piszą do rekruterów”: klient zamknął request
    i rekruterzy mają wiedzieć od razu, także ci z osobami w „Nowych”.
    """
    from app.services.job_working_title import display_title  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    recipients = await load_recipients(db, job.id, exclude_user_id=None, columns=None)
    client_name = await db.scalar(
        select(func.coalesce(Client.display_name, Client.name)).where(
            Client.id == job.client_id
        )
    )
    sent: list[int] = []
    for recipient in recipients:
        title, message = cpro_notice_text(
            recipient,
            job_title=display_title(job),
            client_name=client_name,
            request=request,
            cpro_reason=cpro_reason,
        )
        try:
            async with db.begin_nested():
                row = await emit(
                    db,
                    user_id=recipient.user_id,
                    title=title,
                    message=message,
                    ntype=NotificationType.job_closed_people_waiting,
                    related_entity_type="job",
                    related_entity_id=job.id,
                    link=f"/jobs/{job.id}",
                )
            if row is not None:
                sent.append(recipient.user_id)
        except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć zamknięcia
            logger.exception(
                "job_closed_notices: dzwonek CPro dla user_id=%s job_id=%s nie powstał",
                recipient.user_id,
                job.id,
            )
    return sent
