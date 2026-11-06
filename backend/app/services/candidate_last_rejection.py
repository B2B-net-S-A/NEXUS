"""„Ostatnie odrzucenie” osoby na liście kandydatów (06.11.2026).

Kolumna, filtr i pasek „Ostatnie odrzucenie w tym wyniku” czytają jedną
definicję: najnowszy wiersz końcowy (odrzucenie albo rezygnacja), który jest
nadal stanem swojej pary (osoba, rekrutacja). Karta przywrócona później do
procesu w tej samej rekrutacji nie liczy się jako odrzucona. Osoba może mieć po
nim nowszy proces w innej rekrutacji — decyzja Artura: pokazujemy i filtrujemy
ostatnie odrzucenie, a front dopisuje „potem: w toku”.

Odrzucenie ma klucz, po którym filtruje lista:

* ``r:<etykieta>`` — powód ze słownika NEXUSA (etykieta z
  :func:`rejection_reason_label`, więc oba „Inne (…)” to jedno „Inne”);
* ``t:<kategoria>`` — import z Traffita bez powodu: Traffit zapisywał kategorię
  („Po CV”, „Odrzucenie oferty przez Kandydata”…) w ``rejection_note``;
* ``none`` — ani powodu, ani kategorii.

„Kto zakończył” to reguła Insights (`insights_stage_breakdown._closed_by`):
``ended_by``, a bez niego rezygnacja albo kategoria „… przez Kandydata” =
kandydat, „… przez Klienta” = klient, reszta = my. Rekruter i DL to jedno „my”.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.pipeline_template import RejectionReason
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services.client_identity import client_display_name_expression
from app.services.insights_stage_breakdown import (
    CANDIDATE_DECISION_PATTERN,
    CLIENT_DECISION_PATTERN,
)
from app.services.rejection_reason_labels import rejection_reason_label

REJECTION_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.rejected,
    PipelineStage.withdrawn,
)
WHO_KEYS: tuple[str, ...] = ("client", "us", "candidate")
WITHIN_MONTHS: tuple[int, ...] = (3, 12)
NO_REASON_KEY = "none"
REASON_PREFIX = "r:"
TRAFFIT_PREFIX = "t:"
NO_REASON_LABEL = "Bez powodu"
# Zaślepka importu Traffita w `rejection_reasons.name` — to brak powodu.
_NO_REASON_CODES = frozenset({"legacy_unknown"})
_NOTE_MAX_CHARS = 160


def latest_rejection_subquery(candidate_ids: Optional[Sequence[int]] = None):
    """Najnowsze odrzucenie osoby, które jest nadal stanem swojej pary."""
    later = aliased(CandidateStage)
    newer_in_pair = (
        select(1)
        .where(
            later.candidate_id == CandidateStage.candidate_id,
            later.job_id == CandidateStage.job_id,
            tuple_(later.moved_at, later.id)
            > tuple_(CandidateStage.moved_at, CandidateStage.id),
        )
        .exists()
    )
    stmt = (
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.stage,
            CandidateStage.ended_by,
            CandidateStage.rejection_note,
            CandidateStage.notes,
            CandidateStage.moved_at,
            CandidateStage.moved_by,
            RejectionReason.name.label("reason_name"),
        )
        .outerjoin(
            RejectionReason, RejectionReason.id == CandidateStage.rejection_reason_id
        )
        .where(
            CandidateStage.candidate_id.is_not(None),
            CandidateStage.stage.in_(REJECTION_STAGES),
            ~newer_in_pair,
        )
        .distinct(CandidateStage.candidate_id)
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
    )
    if candidate_ids is not None:
        stmt = stmt.where(CandidateStage.candidate_id.in_(list(candidate_ids)))
    return stmt.subquery("last_rejection")


def _real_reason(sq):
    """Nazwa powodu albo NULL, gdy powodu nie ma (także zaślepka Traffita)."""
    return case(
        (sq.c.reason_name.in_(tuple(_NO_REASON_CODES)), None),
        else_=func.nullif(func.btrim(sq.c.reason_name), ""),
    )


def _traffit_category(sq):
    return func.nullif(func.btrim(sq.c.rejection_note), "")


def who_expression(sq):
    """SQL lustro :func:`who_of` — przypięte testem parytetu."""
    decision_text = func.concat_ws(" ", sq.c.reason_name, sq.c.rejection_note)
    return case(
        (sq.c.ended_by.in_(("recruiter", "delivery_lead")), "us"),
        (sq.c.ended_by == "client", "client"),
        (sq.c.ended_by == "candidate", "candidate"),
        (sq.c.stage == PipelineStage.withdrawn, "candidate"),
        (decision_text.op("~*")(CANDIDATE_DECISION_PATTERN), "candidate"),
        (decision_text.op("~*")(CLIENT_DECISION_PATTERN), "client"),
        else_="us",
    )


def who_of(
    *,
    ended_by: Optional[str],
    stage: Any,
    reason_name: Optional[str],
    rejection_note: Optional[str],
) -> str:
    """Kto zakończył: ``client`` / ``us`` / ``candidate`` (reguła Insights)."""
    if ended_by in ("recruiter", "delivery_lead"):
        return "us"
    if ended_by in ("client", "candidate"):
        return ended_by
    stage_value = getattr(stage, "value", stage)
    if stage_value == PipelineStage.withdrawn.value:
        return "candidate"
    decision_text = " ".join(x for x in (reason_name, rejection_note) if x)
    if re.search(CANDIDATE_DECISION_PATTERN, decision_text, re.IGNORECASE):
        return "candidate"
    if re.search(CLIENT_DECISION_PATTERN, decision_text, re.IGNORECASE):
        return "client"
    return "us"


def key_of(reason_name: Optional[str], rejection_note: Optional[str]) -> str:
    """Klucz filtra dla jednego odrzucenia (``r:…`` / ``t:…`` / ``none``)."""
    name = (reason_name or "").strip()
    if name and name not in _NO_REASON_CODES:
        return REASON_PREFIX + (rejection_reason_label(name) or name)
    category = (rejection_note or "").strip()
    if category:
        return TRAFFIT_PREFIX + category
    return NO_REASON_KEY


def label_of(key: str) -> str:
    if key.startswith(REASON_PREFIX):
        return key[len(REASON_PREFIX) :]
    if key.startswith(TRAFFIT_PREFIX):
        return "Traffit · " + key[len(TRAFFIT_PREFIX) :]
    return NO_REASON_LABEL


@dataclass(frozen=True)
class RejectionFilter:
    keys: tuple[str, ...] = ()
    who: tuple[str, ...] = ()
    within_months: Optional[int] = None
    exclude: bool = False

    @property
    def active(self) -> bool:
        return bool(self.keys or self.who or self.within_months)


async def _reason_names_for_labels(
    db: AsyncSession, labels: Sequence[str]
) -> list[str]:
    """Nazwy z `rejection_reasons`, których etykieta jest jedną z wybranych."""
    wanted = set(labels)
    names = (await db.execute(select(RejectionReason.name).distinct())).scalars()
    return [
        name
        for name in names
        if name
        and name.strip() not in _NO_REASON_CODES
        and (rejection_reason_label(name.strip()) or name.strip()) in wanted
    ]


async def filter_clause(
    db: AsyncSession, spec: RejectionFilter, *, now: Optional[datetime] = None
) -> Optional[Any]:
    """Warunek na `Candidate.id`; ``None`` = filtr nieustawiony.

    „Pokaż tylko” = osoba ma ostatnie odrzucenie spełniające WSZYSTKIE części
    (powód LUB powód…, kto LUB kto…, okres). „Ukryj” = zaprzeczenie — osoby bez
    żadnego odrzucenia zostają.
    """
    if not spec.active:
        return None
    sq = latest_rejection_subquery()
    conditions: list[Any] = []
    if spec.keys:
        reason = _real_reason(sq)
        category = _traffit_category(sq)
        labels = [
            k[len(REASON_PREFIX) :] for k in spec.keys if k.startswith(REASON_PREFIX)
        ]
        categories = [
            k[len(TRAFFIT_PREFIX) :] for k in spec.keys if k.startswith(TRAFFIT_PREFIX)
        ]
        parts: list[Any] = []
        if labels:
            names = await _reason_names_for_labels(db, labels)
            if names:
                parts.append(reason.in_(names))
        if categories:
            parts.append(and_(reason.is_(None), category.in_(categories)))
        if NO_REASON_KEY in spec.keys:
            parts.append(and_(reason.is_(None), category.is_(None)))
        # Nieznany klucz (np. powód usunięty ze słownika) nic nie łapie —
        # „Pokaż tylko” daje wtedy pusty wynik, „Ukryj” nikogo nie ukrywa.
        conditions.append(or_(*parts) if parts else False)
    if spec.who:
        conditions.append(who_expression(sq).in_(list(spec.who)))
    if spec.within_months:
        moment = (now or datetime.now(timezone.utc)) - timedelta(
            days=_days_for_months(spec.within_months)
        )
        conditions.append(sq.c.moved_at >= moment)
    matching = select(sq.c.candidate_id).where(and_(*conditions))
    if spec.exclude:
        return Candidate.id.notin_(matching)
    return Candidate.id.in_(matching)


def _days_for_months(months: int) -> int:
    return 365 if months >= 12 else 30 * months + months // 2


async def facets(db: AsyncSession, ids_query) -> dict[str, Any]:
    """Rozkład ostatnich odrzuceń w wyniku: powody, „kto zakończył”, bez odrzucenia.

    ``ids_query`` to zapytanie o identyfikatory wyniku (już bez filtra
    odrzucenia — inaczej pasek pokazywałby tylko wybrane powody).
    """
    ids_sub = ids_query.order_by(None).subquery("result_ids")
    total = int(await db.scalar(select(func.count()).select_from(ids_sub)) or 0)
    sq = latest_rejection_subquery()
    category = func.btrim(sq.c.rejection_note)
    who = who_expression(sq)
    rows = (
        await db.execute(
            select(sq.c.reason_name, category, who, func.count())
            .where(sq.c.candidate_id.in_(select(ids_sub.c[0])))
            .group_by(sq.c.reason_name, category, who)
        )
    ).all()
    by_key: dict[str, int] = {}
    by_who: dict[str, int] = {}
    with_rejection = 0
    for reason_name, category, who, count in rows:
        key = key_of(reason_name, category)
        by_key[key] = by_key.get(key, 0) + int(count)
        by_who[who] = by_who.get(who, 0) + int(count)
        with_rejection += int(count)
    items = sorted(by_key.items(), key=lambda kv: (-kv[1], label_of(kv[0])))
    return {
        "total": total,
        "without_rejection": max(total - with_rejection, 0),
        "items": [
            {"key": key, "label": label_of(key), "count": count} for key, count in items
        ],
        "who": [{"key": key, "count": by_who.get(key, 0)} for key in WHO_KEYS],
    }


async def page_rows(
    db: AsyncSession, candidate_ids: Sequence[int]
) -> dict[int, dict[str, Any]]:
    """Dane kolumny „Ostatnie odrzucenie” dla osób ze strony."""
    if not candidate_ids:
        return {}
    sq = latest_rejection_subquery(candidate_ids)
    mover = aliased(User)
    stmt = (
        select(
            sq.c.candidate_id,
            sq.c.stage,
            sq.c.ended_by,
            sq.c.reason_name,
            sq.c.rejection_note,
            sq.c.notes,
            sq.c.moved_at,
            sq.c.job_id,
            func.coalesce(Job.working_title, Job.title).label("job_title"),
            client_display_name_expression().label("client_name"),
            mover.name.label("moved_by_name"),
        )
        .select_from(sq)
        .join(Job, Job.id == sq.c.job_id)
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(mover, mover.id == sq.c.moved_by)
    )
    out: dict[int, dict[str, Any]] = {}
    for row in (await db.execute(stmt)).all():
        key = key_of(row.reason_name, row.rejection_note)
        note = " ".join((row.notes or "").split())
        if len(note) > _NOTE_MAX_CHARS:
            note = note[: _NOTE_MAX_CHARS - 1].rstrip() + "…"
        out[row.candidate_id] = {
            "key": key,
            "label": label_of(key),
            "who": who_of(
                ended_by=row.ended_by,
                stage=row.stage,
                reason_name=row.reason_name,
                rejection_note=row.rejection_note,
            ),
            "ended_by": row.ended_by,
            "note": note or None,
            "at": row.moved_at,
            "job_id": row.job_id,
            "job_title": row.job_title,
            "client_name": row.client_name,
            "moved_by_name": row.moved_by_name,
        }
    return out
