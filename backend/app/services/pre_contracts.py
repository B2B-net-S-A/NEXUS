"""Umowa przedwstępna przy osobie w rekrutacji — jedna reguła stanów i dzwonków.

Decyzje Artura 21.10.2026 (makiety https://claude.ai/artifact/VWyCFF3aU7CLCNSXGCSx2R):

* prośba dotyczy JEDNEJ osoby w JEDNEJ rekrutacji; prosi Delivery Lead, Head
  of Recruitment albo sam rekruter; wystawia domyślnie rekruter prowadzący,
* każdy, kto poprosił albo obserwuje, widzi stan i dostaje dzwonek przy każdej
  zmianie (bez autora zmiany),
* każda forma podpisu kandydata (profil zaufany, podpis osobisty,
  kwalifikowany, odręczny skan) — NEXUS zapisuje formę,
* brak podpisanej umowy NIE blokuje ruchu karty (ostrzeżenie w oknie ruchu).

Stan liczy :func:`state_of` z dat w wierszu; plakietkę Tablicy, wiersz listy
i panel osoby składa :func:`badge` — front tylko ją pokazuje.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_today, is_business_day
from app.models.notification import NotificationType
from app.models.pre_contract import (
    PreContractEvent,
    PreContractRequest,
    PreContractWatcher,
)
from app.services.board_stage_badges import BOARD_COLUMN_ORDER

_TZ = ZoneInfo(DEFAULT_TZ)

# ── Słowniki (napisy w UI) ───────────────────────────────────────────────────

NEEDED_BEFORE_LABEL: dict[str, str] = {
    "cv_sent": "przed wysłaniem CV",
    "client_interview": "przed rozmową u klienta",
    "b2b_contract": "przed umową B2B",
    "date": "do daty",
}

#: Kolumna Tablicy, PRZED którą umowa ma być podpisana.
NEEDED_COLUMN: dict[str, Optional[str]] = {
    "cv_sent": "cv_sent",
    "client_interview": "client_interview",
    "b2b_contract": "contract",
    "date": None,
}

SIGNATURE_FORM_LABEL: dict[str, str] = {
    "trusted_profile": "profil zaufany",
    "personal_signature": "podpis osobisty (e-dowód)",
    "qualified": "podpis kwalifikowany",
    "handwritten_scan": "odręcznie, skan",
    "other": "inna forma",
}

WITHDRAWAL_LABEL: dict[str, str] = {
    "no_show": "nie przyszedł na rozmowę albo test",
    "refused": "odmówił udziału",
    "resigned": "zrezygnował w trakcie",
    "bypassed": "poszedł do klienta inną drogą",
}

CLOSE_LABEL: dict[str, str] = {
    "fulfilled": "Zrealizowana",
    "expired": "Wygasła",
    "cancelled": "Anulowana",
    "withdrawn": "Prośba wycofana",
    "candidate_refused": "Kandydat odmówił podpisu",
    "candidate_withdrew": "Kandydat zrezygnował",
}

STATE_LABEL: dict[str, str] = {
    "requested": "Prośba — nie wystawiona",
    "issued": "Wystawiona, nie wysłana",
    "sent": "Wysłana kandydatowi",
    "candidate_signed": "Kandydat podpisał — czeka podpis firmy",
    "signed": "Podpisana",
}

#: Ile dni przed końcem ważności plakietka robi się czerwona i idzie dzwonek.
EXPIRING_DAYS = 7
REMIND_EXPIRING_DAYS = 3

# ── Stan ─────────────────────────────────────────────────────────────────────


def state_of(req: PreContractRequest) -> str:
    """Krok umowy: requested → issued → sent → candidate_signed → signed.

    Zamknięta prośba zwraca powód zamknięcia (``expired``, ``cancelled``…)."""
    if req.closed_at is not None and req.close_reason:
        return req.close_reason
    if req.company_signed_at is not None:
        return "signed"
    if req.candidate_signed_at is not None:
        return "candidate_signed"
    if req.sent_at is not None:
        return "sent"
    if req.document_id is not None or req.issued_at is not None:
        return "issued"
    return "requested"


def is_open(req: PreContractRequest) -> bool:
    return req.closed_at is None


def is_signed(req: PreContractRequest) -> bool:
    return req.company_signed_at is not None and req.candidate_signed_at is not None


def _column_index(column: Optional[str]) -> Optional[int]:
    if column is None or column not in BOARD_COLUMN_ORDER:
        return None
    return BOARD_COLUMN_ORDER.index(column)


def past_needed_point(
    req: PreContractRequest, *, column: Optional[str], today: date
) -> bool:
    """Osoba minęła etap, przed którym umowa miała być podpisana."""
    if req.needed_before == "date":
        return req.needed_by is not None and today > req.needed_by
    needed = _column_index(NEEDED_COLUMN.get(req.needed_before))
    current = _column_index(column)
    return needed is not None and current is not None and current >= needed


def _days(a: date, b: date) -> int:
    return (b - a).days


def _pl_date(value: date) -> str:
    return value.strftime("%d.%m")


def _plural_days(n: int) -> str:
    return "dzień" if n == 1 else "dni"


@dataclass(frozen=True)
class Badge:
    state: str
    label: str
    # missing (pomarańczowa) · late (czerwona) · wait (niebieska) ·
    # signer (szara) · ok (zielona) · closed (szara)
    tone: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "state": self.state,
            "label": self.label,
            "tone": self.tone,
            "detail": self.detail,
        }


def badge(
    req: PreContractRequest,
    *,
    column: Optional[str],
    today: date,
    business_days_left: Optional[int] = None,
) -> Badge:
    """Plakietka „Przedwstępna …” dla karty, wiersza listy i panelu osoby.

    ``business_days_left`` — dni robocze do terminu umowy B2B (liczy wołający,
    bo potrzebuje kalendarza świąt); ``None`` = brak terminu."""
    state = state_of(req)
    needed = NEEDED_BEFORE_LABEL.get(req.needed_before, "")
    if req.needed_before == "date" and req.needed_by is not None:
        needed = f"do {_pl_date(req.needed_by)}"
    if not is_open(req):
        return Badge(
            state,
            f"Przedwstępna: {CLOSE_LABEL.get(state, state).lower()}",
            "closed",
            CLOSE_LABEL.get(state, state),
        )

    if state == "signed":
        if req.b2b_deadline is not None and business_days_left is not None:
            n = max(business_days_left, 0)
            return Badge(
                state,
                f"Umowa B2B: zostało {n} {'dzień roboczy' if n == 1 else 'dni roboczych'}",
                "late",
                f"Termin z przedwstępnej: {req.b2b_deadline:%d.%m.%Y}.",
            )
        if req.valid_until is not None:
            left = _days(today, req.valid_until)
            if left < 0:
                return Badge(
                    state, "Przedwstępna wygasła", "late", "Minęła data ważności."
                )
            if left <= EXPIRING_DAYS:
                return Badge(
                    state,
                    f"Przedwstępna wygasa za {left} {_plural_days(left)}",
                    "late",
                    f"Ważna do {req.valid_until:%d.%m.%Y}.",
                )
            return Badge(
                state,
                f"Przedwstępna do {_pl_date(req.valid_until)}",
                "ok",
                f"Podpisana obustronnie, ważna do {req.valid_until:%d.%m.%Y}.",
            )
        return Badge(state, "Przedwstępna podpisana", "ok", "Podpisana obustronnie.")

    late = past_needed_point(req, column=column, today=today)
    if state == "requested":
        label = f"Przedwstępna {needed} — nie wystawiona"
        tone = "late" if late else "missing"
    elif state == "issued":
        label = f"Przedwstępna {needed} — nie wysłana"
        tone = "late" if late else "missing"
    elif state == "sent":
        waiting = _days(req.sent_at.date(), today) if req.sent_at is not None else 0
        label = (
            f"Przedwstępna wysłana · czeka {waiting} {_plural_days(waiting)}"
            if waiting > 0
            else "Przedwstępna wysłana dziś"
        )
        tone = "late" if late else "wait"
    else:  # candidate_signed
        label = "Przedwstępna: czeka na podpis firmy"
        tone = "late" if late else "signer"
    detail = STATE_LABEL.get(state, state)
    if late:
        detail += f" — miała być podpisana {needed}."
    return Badge(state, label, tone, detail)


# ── Historia i dzwonki ───────────────────────────────────────────────────────

EVENT_TITLE: dict[str, str] = {
    "requested": "Prośba o umowę przedwstępną",
    "watcher_joined": "Dołączono do obserwujących przedwstępną",
    "assignee_changed": "Zmiana osoby wystawiającej przedwstępną",
    "issued": "Przedwstępna wystawiona",
    "sent": "Przedwstępna wysłana kandydatowi",
    "candidate_signed": "Kandydat podpisał przedwstępną",
    "company_signed": "Przedwstępna podpisana przez firmę",
    "moved_without": "Ruch karty bez podpisanej przedwstępnej",
    "expiring": "Przedwstępna wkrótce wygaśnie",
    "expired": "Przedwstępna wygasła",
    "b2b_deadline": "Termin umowy B2B z przedwstępnej",
    "candidate_withdrew": "Kandydat zrezygnował — przedwstępna obowiązywała",
    "candidate_refused": "Kandydat odmówił podpisu przedwstępnej",
    "cancelled": "Przedwstępna anulowana",
    "withdrawn": "Prośba o przedwstępną wycofana",
    "fulfilled": "Przedwstępna zrealizowana",
    "reminder_waiting": "Kandydat nie odesłał przedwstępnej",
    "updated": "Zmiana prośby o przedwstępną",
    "penalty_decision": "Decyzja o karze z przedwstępnej",
}


async def add_event(
    db: AsyncSession,
    req: PreContractRequest,
    kind: str,
    *,
    actor_id: Optional[int],
    payload: Optional[dict[str, Any]] = None,
) -> PreContractEvent:
    event = PreContractEvent(
        request_id=req.id, kind=kind, actor_id=actor_id, payload=payload or None
    )
    db.add(event)
    await db.flush()
    return event


async def add_watchers(
    db: AsyncSession, request_id: int, user_ids: Iterable[Optional[int]]
) -> None:
    ids = sorted({uid for uid in user_ids if uid})
    if not ids:
        return
    await db.execute(
        pg_insert(PreContractWatcher)
        .values([{"request_id": request_id, "user_id": uid} for uid in ids])
        .on_conflict_do_nothing()
    )


async def watcher_ids(db: AsyncSession, request_id: int) -> list[int]:
    rows = await db.scalars(
        select(PreContractWatcher.user_id).where(
            PreContractWatcher.request_id == request_id
        )
    )
    return sorted(set(rows.all()))


def pair_link(req: PreContractRequest) -> str:
    return f"/jobs/{req.job_id}?candidate={req.candidate_id}"


async def notify(
    db: AsyncSession,
    req: PreContractRequest,
    event: PreContractEvent,
    *,
    message: str,
    actor_id: Optional[int],
    extra_user_ids: Iterable[Optional[int]] = (),
    only_user_ids: Optional[Iterable[Optional[int]]] = None,
) -> list[int]:
    """Dzwonek do obserwujących i wystawiającego (bez autora zmiany).

    Encja = zdarzenie, więc dwa kroki jednego dnia dają dwa dzwonki."""
    from app.services.notification_triggers import emit  # noqa: PLC0415

    if only_user_ids is not None:
        recipients = {uid for uid in only_user_ids if uid}
    else:
        recipients = set(await watcher_ids(db, req.id))
        if req.assignee_id:
            recipients.add(req.assignee_id)
        recipients.update(uid for uid in extra_user_ids if uid)
    if actor_id is not None:
        recipients.discard(actor_id)
    sent: list[int] = []
    for uid in sorted(recipients):
        row = await emit(
            db,
            user_id=uid,
            title=EVENT_TITLE.get(event.kind, "Umowa przedwstępna"),
            message=message,
            ntype=NotificationType.pre_contract,
            related_entity_type="pre_contract_event",
            related_entity_id=event.id,
            link=pair_link(req),
        )
        if row is not None:
            sent.append(uid)
    return sent


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return business_today()


# ── Kolumna Tablicy pary (lista „Umowy przedwstępne”) ───────────────────────


async def pair_columns(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], tuple[str, Optional[str]]]:
    """(kandydat, rekrutacja) → (kolumna Tablicy, nazwa etapu) — ta sama reguła
    co Tablica (`board_column_for` na ostatnim wierszu etapu pary)."""
    from app.models.pipeline_template import PipelineStageDef  # noqa: PLC0415
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415
    from app.services.board_stage_badges import board_column_for  # noqa: PLC0415
    from app.services.pipeline_latest import latest_stage_ids  # noqa: PLC0415

    wanted = set(pairs)
    if not wanted:
        return {}
    latest = latest_stage_ids(job_ids=sorted({job for _, job in wanted}))
    rows = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.stage,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(CandidateStage.id.in_(select(latest.c.latest_id)))
            .where(CandidateStage.candidate_id.in_({c for c, _ in wanted}))
        )
    ).all()
    out: dict[tuple[int, int], tuple[str, Optional[str]]] = {}
    for cid, jid, stage, name, category, terminal_type in rows:
        if (cid, jid) not in wanted:
            continue
        out[(cid, jid)] = (
            board_column_for(
                name,
                getattr(stage, "value", stage),
                category=getattr(category, "value", category),
                terminal_type=getattr(terminal_type, "value", terminal_type),
            ),
            name,
        )
    return out


def business_days_until(start: date, end: date) -> int:
    """Dni robocze od jutra do ``end`` włącznie (0, gdy termin dziś lub minął)."""
    n = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if is_business_day(datetime.combine(current, time(12), tzinfo=_TZ)):
            n += 1
    return n


async def kanban_badges(
    db: AsyncSession, job_id: int, candidate_ids: Iterable[int]
) -> dict[int, dict[str, Any]]:
    """Plakietka „Przedwstępna …” dla kart Tablicy jednej rekrutacji.

    Prośba w toku albo zamknięta w ostatnich 14 dniach (żeby „wygasła” /
    „kandydat zrezygnował” nie znikały od razu z karty)."""
    ids = sorted(set(candidate_ids))
    if not ids:
        return {}
    since = now_utc() - timedelta(days=14)
    rows = (
        await db.scalars(
            select(PreContractRequest)
            .where(
                PreContractRequest.job_id == job_id,
                PreContractRequest.candidate_id.in_(ids),
            )
            .where(
                (PreContractRequest.closed_at.is_(None))
                | (PreContractRequest.closed_at >= since)
            )
            .order_by(PreContractRequest.requested_at)
        )
    ).all()
    if not rows:
        return {}
    latest: dict[int, PreContractRequest] = {}
    for req in rows:
        current = latest.get(req.candidate_id)
        # Prośba w toku wygrywa z zamkniętą; wśród równych — nowsza.
        if current is None or (current.closed_at is not None) or req.closed_at is None:
            latest[req.candidate_id] = req
    columns = await pair_columns(db, [(cid, job_id) for cid in latest])
    day = today()
    out: dict[int, dict[str, Any]] = {}
    for cid, req in latest.items():
        column = columns.get((cid, job_id), (None, None))[0]
        left = (
            business_days_until(day, req.b2b_deadline)
            if req.b2b_deadline is not None
            else None
        )
        b = badge(req, column=column, today=day, business_days_left=left)
        out[cid] = {"id": req.id, **b.as_dict()}
    return out


# ── Ruch karty (wołane z `api/pipeline.apply_move`, ta sama transakcja) ─────

#: Dni robocze na umowę B2B po akceptacji klienta, gdy wzór ich nie podaje
#: (wzór CeZ, § 2 ust. 3: 5 dni roboczych od poinformowania kandydata).
_B2B_TERM_FALLBACK = {"preliminary_cez": 5}


def b2b_term_days(document_type: Optional[str]) -> Optional[int]:
    if not document_type:
        return None
    from app.services.b2b_documents.registry import get_type  # noqa: PLC0415

    doc_type = get_type(document_type)
    days = getattr(doc_type, "b2b_term_business_days", None) if doc_type else None
    return days if days is not None else _B2B_TERM_FALLBACK.get(document_type)


async def start_b2b_deadline(
    db: AsyncSession,
    req: PreContractRequest,
    *,
    accepted_on: date,
    actor_id: Optional[int],
) -> None:
    """Termin umowy B2B z przedwstępnej od akceptacji klienta (albo od dziś,
    gdy umowę podpisano już po akceptacji). Nic, gdy wzór terminu nie zna."""
    from app.models.b2b_contract_document import B2BContractDocument  # noqa: PLC0415
    from app.services.candidate_followups import add_business_days  # noqa: PLC0415

    if req.b2b_deadline is not None or not is_signed(req):
        return
    doc_type = (
        await db.scalar(
            select(B2BContractDocument.document_type).where(
                B2BContractDocument.id == req.document_id
            )
        )
        if req.document_id
        else None
    )
    days = b2b_term_days(doc_type)
    if not days:
        return
    start = max(accepted_on, today())
    req.b2b_deadline = add_business_days(
        datetime.combine(start, time(12), tzinfo=_TZ), days
    )
    event = await add_event(
        db,
        req,
        "b2b_deadline",
        actor_id=actor_id,
        payload={"accepted_on": accepted_on.isoformat(), "days": days},
    )
    await notify(
        db,
        req,
        event,
        message=(
            f"Klient zaakceptował osobę. Umowę B2B trzeba zawrzeć do "
            f"{req.b2b_deadline:%d.%m.%Y} ({days} dni roboczych z przedwstępnej) "
            "— po terminie kara dla firmy."
        ),
        actor_id=None,
    )


async def latest_acceptance(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[date]:
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415

    return await db.scalar(
        select(CandidateStage.client_accepted_on)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
            CandidateStage.client_accepted_on.is_not(None),
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )


async def on_move(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    to_column: str,
    to_label: str,
    accepted_on: Optional[date],
    actor_id: Optional[int],
    actor_name: Optional[str],
) -> None:
    """Skutki ruchu karty dla prośby w toku.

    * Akceptacja klienta przy podpisanej umowie, której wzór wiąże firmę
      terminem (CeZ: 5 dni roboczych) → ``b2b_deadline`` i dzwonek.
    * Pierwszy ruch na etap, przed którym umowa miała być podpisana, bez
      podpisu → zdarzenie ``moved_without`` i dzwonek do proszących."""

    req = await db.scalar(
        select(PreContractRequest)
        .where(
            PreContractRequest.candidate_id == candidate_id,
            PreContractRequest.job_id == job_id,
            PreContractRequest.closed_at.is_(None),
        )
        .with_for_update()
    )
    if req is None:
        return
    if accepted_on is not None:
        await start_b2b_deadline(db, req, accepted_on=accepted_on, actor_id=actor_id)
    needed = NEEDED_COLUMN.get(req.needed_before)
    if (
        needed is None
        or is_signed(req)
        or to_column not in BOARD_COLUMN_ORDER
        or BOARD_COLUMN_ORDER.index(to_column) < BOARD_COLUMN_ORDER.index(needed)
    ):
        return
    already = await db.scalar(
        select(PreContractEvent.id).where(
            PreContractEvent.request_id == req.id,
            PreContractEvent.kind == "moved_without",
        )
    )
    if already is not None:
        return
    event = await add_event(
        db, req, "moved_without", actor_id=actor_id, payload={"to_column": to_column}
    )
    await notify(
        db,
        req,
        event,
        message=(
            f"{actor_name or 'Ktoś'} przesunął(a) osobę na „{to_label}” "
            "bez podpisanej umowy przedwstępnej."
        ),
        actor_id=actor_id,
    )
