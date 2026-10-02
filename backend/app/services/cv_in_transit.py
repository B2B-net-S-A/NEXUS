"""„Twoje CV w drodze” — co dzieje się z CV po przekazaniu karty (02.10.2026).

Dzwonek o przekazaniu (`stage_handoff_recipients`) znika po kliknięciu, a
rekruter nie miał na pulpicie nic: panel „Czeka na Ciebie” pokazywał przegląd
tylko Delivery Leadowi i kolejkę tylko osobie od Cpro. Ta lista jest drugą
stroną tych samych przekazań, liczoną przy odczycie z NAJNOWSZEGO wiersza pary
(kandydat, opublikowana rekrutacja) — bez własnej tabeli:

* **wróciło** — Delivery Lead odrzucił kandydata, ktoś cofnął kartę z „QC CV”
  do wcześniejszej kolumny albo (Nordea) osoba od Cpro zwróciła ją z kolejki;
  znika po kolejnym ruchu karty albo po ``RETURNED_WINDOW_DAYS``;
* **w przeglądzie** — karta stoi w „QC CV” u Delivery Leada (poza Nordeą) albo
  w kolejce Cpro (Nordea);
* **wysłane** — „CV wysłane” z ostatnich ``SENT_WINDOW_DAYS`` dni.

„Moje” CV = para, w której jestem rekruterem kandydata
(`interview_slots.default_recruiter_ids`) albo osobą, która przekazała kartę
dalej (autor wiersza sprzed ruchu) — ta sama reguła odbiorcy co w dzwonkach.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_template import PipelineTemplate
from app.models.user import User, UserRole
from app.models.user_dashboard import UserDashboard
from app.services import cpro_sender
from app.services.board_stage_badges import (
    BOARD_COLUMN_ORDER,
    CV_QC_COLUMN,
    board_column_for,
    cpro_enabled_for_client,
    stage_badge_kind,
)
from app.services.board_tasks import _catalog, _Catalog
from app.services.dashboard_tiles import PANEL_CV_IN_TRANSIT, hidden_panels
from app.services.interview_slots import default_recruiter_ids
from app.services.rejection_reason_labels import rejection_reason_label

logger = logging.getLogger(__name__)

RETURNED_WINDOW_DAYS = 14
REVIEW_WINDOW_DAYS = 30
SENT_WINDOW_DAYS = 7
# Lista stoi nad pulpitem — dłuższa niż to przestaje być czytana.
MAX_ROWS = 30

KIND_REJECTED_BY_DL = "rejected_by_dl"
KIND_SENT_BACK = "sent_back"
KIND_CPRO_RETURNED = "cpro_returned"
KIND_IN_REVIEW = "in_review"
KIND_CPRO_QUEUE = "cpro_queue"
KIND_SENT = "sent"

CV_SENT_COLUMN = "cv_sent"
_QC_INDEX = BOARD_COLUMN_ORDER.index(CV_QC_COLUMN)
# Kolumny, z których karta idzie dalej z rąk do rąk (lustro
# `stage_handoff_recipients._BEFORE_SEND_COLUMNS`).
_BEFORE_SEND_COLUMNS = frozenset(BOARD_COLUMN_ORDER[: _QC_INDEX + 1])
_REASON_MAX = 160
# Wolny tekst powodu ruch zapisuje w notatce: „Powód (rejected): …”.
_NOTE_REASON_RE = re.compile(r"^Powód \([a-z_]+\):\s*(.+)$")


@dataclass(frozen=True)
class TransitRow:
    kind: str
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    job_working_title: Optional[str]
    client_name: Optional[str]
    since: datetime
    # Kto odrzucił, cofnął albo wysłał (wróciło, wysłane).
    actor_name: Optional[str] = None
    # U kogo karta czeka (w przeglądzie).
    holder_name: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class CvInTransit:
    returned: list[TransitRow] = field(default_factory=list)
    in_review: list[TransitRow] = field(default_factory=list)
    sent: list[TransitRow] = field(default_factory=list)
    returned_total: int = 0
    in_review_total: int = 0
    sent_total: int = 0


# Najnowszy wiersz pary + wiersz tuż przed nim. Warunek na końcu to NADZBIÓR
# „moich” par (autor któregoś z dwóch wierszy, prowadzący rekrutację,
# właściciel procesu, weryfikator) — dokładną regułę rekrutera kandydata liczy
# potem `default_recruiter_ids` na tej małej liście.
_SQL = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.id, cs.candidate_id, cs.job_id, cs.stage, cs.stage_def_id,
               cs.moved_at, cs.moved_by, cs.ended_by, cs.rejection_reason_id,
               cs.notes
          FROM candidate_stages cs
          JOIN jobs j ON j.id = cs.job_id
         WHERE j.status = 'published'
           AND cs.moved_at >= :since
         ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
    )
    SELECT l.id, l.candidate_id, l.job_id, l.stage, l.stage_def_id, l.moved_at,
           l.moved_by, l.ended_by, l.notes,
           p.stage AS prev_stage, p.stage_def_id AS prev_stage_def_id,
           p.moved_by AS prev_moved_by,
           COALESCE(j.pipeline_template_id, :default_template_id) AS template_id,
           j.title, j.working_title, j.client_id,
           CASE WHEN dl.is_active THEN j.delivery_lead_id END AS delivery_lead_id,
           CASE WHEN js.is_active THEN j.cpro_sender_id END AS cpro_sender_id,
           cl.name AS client_name,
           c.name AS cname, c.lastname AS clastname,
           rr.name AS rejection_reason_name
      FROM latest l
      JOIN jobs j ON j.id = l.job_id
      JOIN candidates c ON c.id = l.candidate_id
      LEFT JOIN clients cl ON cl.id = j.client_id
      LEFT JOIN users dl ON dl.id = j.delivery_lead_id
      LEFT JOIN users js ON js.id = j.cpro_sender_id
      LEFT JOIN rejection_reasons rr ON rr.id = l.rejection_reason_id
      LEFT JOIN LATERAL (
            SELECT p.stage, p.stage_def_id, p.moved_by
              FROM candidate_stages p
             WHERE p.candidate_id = l.candidate_id
               AND p.job_id = l.job_id
               AND (p.moved_at, p.id) < (l.moved_at, l.id)
             ORDER BY p.moved_at DESC, p.id DESC
             LIMIT 1
      ) p ON TRUE
     WHERE l.moved_by = :user_id
        OR p.moved_by = :user_id
        OR j.recruiter_id = :user_id
        OR EXISTS (
            SELECT 1 FROM recruitment_processes rp
             WHERE rp.candidate_id = l.candidate_id
               AND rp.job_id = l.job_id
               AND rp.owner_user_id = :user_id
        )
        OR EXISTS (
            SELECT 1 FROM candidate_stages v
             WHERE v.candidate_id = l.candidate_id
               AND v.job_id = l.job_id
               AND v.stage = 'verified'
               AND v.moved_by = :user_id
        )
    """
)


def _value(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def _place(
    catalog: _Catalog, template_id: int, stage_def_id: Optional[int], stage: object
) -> tuple[Optional[str], Optional[str]]:
    """(kolumna Tablicy, znacznik etapu) — ta sama reguła co tablica."""

    if stage_def_id is None:
        return board_column_for(None, _value(stage)), None
    effective = catalog.effective_def_id(template_id, stage_def_id)
    stage_def = catalog.defs.get(effective) if effective is not None else None
    if stage_def is None:
        # Etap bez odpowiednika w szablonie — „poza szablonem”.
        return None, None
    category = _value(stage_def.category)
    column = board_column_for(
        stage_def.name,
        stage_def.legacy_enum_value,
        category=category,
        terminal_type=_value(getattr(stage_def, "terminal_type", None)),
    )
    badge = stage_badge_kind(stage_def.name) if category != "terminal" else None
    return column, badge


def _short(value: Optional[str]) -> Optional[str]:
    """Pierwsza linia notatki, przycięta do rozmiaru wiersza listy."""

    lines = (value or "").strip().splitlines()
    line = lines[0].strip() if lines else ""
    if not line:
        return None
    return line if len(line) <= _REASON_MAX else line[: _REASON_MAX - 1].rstrip() + "…"


def rejection_reason_text(
    reason_name: Optional[str], notes: Optional[str]
) -> Optional[str]:
    """Powód odrzucenia do pokazania: ze słownika albo wolny tekst z notatki."""

    label = rejection_reason_label(reason_name)
    if label:
        return label
    first = _short(notes)
    match = _NOTE_REASON_RE.match(first) if first else None
    return match.group(1).strip() if match else None


def classify(
    *,
    column: Optional[str],
    badge: Optional[str],
    prev_column: Optional[str],
    prev_badge: Optional[str],
    nordea: bool,
    ended_by: Optional[str],
) -> Optional[str]:
    """Rodzaj wpisu dla najnowszego wiersza pary (albo ``None``)."""

    if column == CV_SENT_COLUMN:
        return KIND_SENT
    if column == CV_QC_COLUMN:
        if badge == "cpro":
            return KIND_CPRO_QUEUE if nordea else None
        if nordea:
            # U Nordei „QC CV” to praca rekrutera; wpisem jest tylko zwrot
            # z kolejki Cpro.
            return KIND_CPRO_RETURNED if prev_badge == "cpro" else None
        return KIND_IN_REVIEW
    if column == "closed":
        return KIND_REJECTED_BY_DL if ended_by == "delivery_lead" else None
    if (
        prev_column == CV_QC_COLUMN
        and column in BOARD_COLUMN_ORDER
        and BOARD_COLUMN_ORDER.index(column) < _QC_INDEX
    ):
        return KIND_SENT_BACK
    return None


async def is_hidden(db: AsyncSession, user_id: int) -> bool:
    """Czy osoba usunęła listę z pulpitu („Usuń z pulpitu”)."""

    row = await db.get(UserDashboard, user_id)
    return row is not None and PANEL_CV_IN_TRANSIT in hidden_panels(row.layout)


async def load_for_user(
    db: AsyncSession,
    user: User,
    *,
    portfolio: frozenset[int],
    now: Optional[datetime] = None,
) -> CvInTransit:
    now = now or datetime.now(timezone.utc)
    catalog = await _catalog(db)
    default_template_id = await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )
    rows = (
        await db.execute(
            _SQL,
            {
                "user_id": user.id,
                "default_template_id": default_template_id,
                "since": now - timedelta(days=REVIEW_WINDOW_DAYS),
            },
        )
    ).all()

    returned_since = now - timedelta(days=RETURNED_WINDOW_DAYS)
    sent_since = now - timedelta(days=SENT_WINDOW_DAYS)
    reviews_as_dl = user.has_role(UserRole.delivery_lead)
    candidates: list[tuple[Any, str, bool]] = []
    for r in rows:
        column, badge = _place(catalog, r.template_id, r.stage_def_id, r.stage)
        prev_column, prev_badge = (
            _place(catalog, r.template_id, r.prev_stage_def_id, r.prev_stage)
            if r.prev_stage is not None
            else (None, None)
        )
        kind = classify(
            column=column,
            badge=badge,
            prev_column=prev_column,
            prev_badge=prev_badge,
            nordea=cpro_enabled_for_client(r.client_id),
            ended_by=r.ended_by,
        )
        if kind is None:
            continue
        if kind == KIND_SENT:
            if r.moved_at < sent_since:
                continue
            handed_over = (
                r.prev_moved_by if prev_column in _BEFORE_SEND_COLUMNS else None
            )
        elif kind in (KIND_IN_REVIEW, KIND_CPRO_QUEUE):
            if kind == KIND_IN_REVIEW and reviews_as_dl:
                # Ten wiersz mam już w „Czeka na Twój przegląd”.
                mine_to_review = (
                    r.delivery_lead_id == user.id
                    if r.delivery_lead_id is not None
                    else r.client_id in portfolio
                )
                if mine_to_review:
                    continue
            handed_over = r.moved_by
        else:
            # Wróciło: własny ruch nie jest wiadomością.
            if r.moved_at < returned_since or r.moved_by == user.id:
                continue
            handed_over = (
                r.prev_moved_by if prev_column in _BEFORE_SEND_COLUMNS else None
            )
        candidates.append((r, kind, handed_over == user.id))

    recruiters = await default_recruiter_ids(
        db, [(r.candidate_id, r.job_id) for r, _kind, mine in candidates if not mine]
    )
    kept = [
        (r, kind)
        for r, kind, mine in candidates
        if mine or recruiters.get((r.candidate_id, r.job_id)) == user.id
    ]
    if not kept:
        return CvInTransit()

    firm_sender_id = (await cpro_sender.effective_sender(db, now)).user_id
    user_ids = {r.moved_by for r, _ in kept if r.moved_by is not None}
    user_ids |= {r.delivery_lead_id for r, _ in kept if r.delivery_lead_id is not None}
    user_ids |= {r.cpro_sender_id for r, _ in kept if r.cpro_sender_id is not None}
    if firm_sender_id is not None:
        user_ids.add(firm_sender_id)
    names: dict[int, str] = {}
    if user_ids:
        for uid, uname, email in (
            await db.execute(
                select(User.id, User.name, User.email).where(User.id.in_(user_ids))
            )
        ).all():
            names[uid] = uname or email

    out = CvInTransit()
    for r, kind in kept:
        actor = names.get(r.moved_by) if r.moved_by is not None else None
        holder: Optional[str] = None
        reason: Optional[str] = None
        if kind == KIND_IN_REVIEW:
            holder, actor = names.get(r.delivery_lead_id), None
        elif kind == KIND_CPRO_QUEUE:
            holder, actor = names.get(firm_sender_id or r.cpro_sender_id), None
        elif kind == KIND_REJECTED_BY_DL:
            reason = rejection_reason_text(r.rejection_reason_name, r.notes)
        elif kind == KIND_CPRO_RETURNED:
            reason = _short(r.notes)
        row = TransitRow(
            kind=kind,
            stage_id=r.id,
            candidate_id=r.candidate_id,
            candidate_name=" ".join(p for p in (r.cname, r.clastname) if p)
            or "Kandydat",
            job_id=r.job_id,
            job_title=r.title,
            job_working_title=r.working_title,
            client_name=r.client_name,
            since=r.moved_at,
            actor_name=actor,
            holder_name=holder,
            reason=reason,
        )
        if kind in (KIND_IN_REVIEW, KIND_CPRO_QUEUE):
            out.in_review.append(row)
        elif kind == KIND_SENT:
            out.sent.append(row)
        else:
            out.returned.append(row)

    # Wróciło i wysłane: najnowsze na górze; w przeglądzie: najdłużej czekające.
    out.returned.sort(key=lambda t: t.since, reverse=True)
    out.sent.sort(key=lambda t: t.since, reverse=True)
    out.in_review.sort(key=lambda t: t.since)
    out.returned_total = len(out.returned)
    out.in_review_total = len(out.in_review)
    out.sent_total = len(out.sent)
    out.returned = out.returned[:MAX_ROWS]
    out.in_review = out.in_review[:MAX_ROWS]
    out.sent = out.sent[:MAX_ROWS]
    return out


async def load_safely(
    db: AsyncSession,
    user: User,
    *,
    portfolio: frozenset[int],
    now: Optional[datetime] = None,
) -> Optional[CvInTransit]:
    """Lista dla pulpitu: usunięta przez osobę albo awaria = ``None``.

    Lista jest dodatkiem do panelu „Czeka na Ciebie” — padnięte zapytanie nie
    może dać 500 całego pulpitu. Savepoint, bo sesja żądania jedzie dalej.
    """

    try:
        async with db.begin_nested():
            if await is_hidden(db, user.id):
                return None
            return await load_for_user(db, user, portfolio=portfolio, now=now)
    except Exception:  # noqa: BLE001
        logger.exception("cv_in_transit: nie udało się policzyć listy")
        return None


__all__ = [
    "CvInTransit",
    "TransitRow",
    "classify",
    "is_hidden",
    "load_for_user",
    "load_safely",
    "rejection_reason_text",
]
