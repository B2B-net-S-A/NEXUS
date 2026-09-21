"""Skrzynka „Propozycje" rekrutacji — zapis, znacznik „widziane", licznik nowych.

Reguły, które łatwo cofnąć „przy okazji":

* ``status`` jest zapadką. ``upsert_proposals`` NIGDY go nie dotyka przy
  konflikcie: odrzucona propozycja nie wraca przy następnym przeglądzie,
  a ``added`` się nie cofa.
* Status liczy się PER PARA (kandydat, rekrutacja), nie per wiersz źródła:
  ``added`` > ``dismissed`` > ``proposed``. Inaczej osoba odrzucona ze źródła
  „pełna baza" wracałaby nazajutrz jako nowa ze źródła „nowe CV".
* Osoba, która ma już JAKIKOLWIEK wiersz w pipeline'ie tej rekrutacji, nie jest
  propozycją — ani na liście, ani w liczniku.
* ``evidence`` przechodzi przez :func:`sanitize_evidence` — wyłącznie
  nazwy/identyfikatory wymagań i liczby, nigdy wolny tekst z CV.
* Żadna funkcja tutaj nie commituje — transakcja należy do wołającego.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import and_, case, exists, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_proposal import (
    JOB_PROPOSAL_SOURCES,
    JOB_PROPOSAL_STATUSES,
    JobProposal,
    JobProposalSeen,
)
from app.models.recruitment_pipeline import CandidateStage

_UPSERT_CHUNK = 500
_MAX_NAME_LEN = 120
_MAX_REQUIREMENTS = 60
_REQUIREMENT_KEYS = ("id", "key", "level", "status")
_NAME_LIST_KEYS = ("matched_must", "matched_nice", "missing_must", "missing_nice")


def _short(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:_MAX_NAME_LEN] if text else None


def _names(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    out = [_short(v) for v in values[:_MAX_REQUIREMENTS]]
    return [v for v in out if v]


def sanitize_evidence(raw: Any) -> Optional[dict]:
    """Allowlista: nazwy/identyfikatory wymagań + liczby. Reszta przepada.

    Wiersz żyje do usunięcia kandydata, więc nie może nieść cytatów z CV,
    notatek ani kontekstu użycia technologii (``candidate_evidence``,
    ``usage_context`` z pełnego przeglądu są tu świadomie odrzucane).
    """
    if not isinstance(raw, Mapping):
        return None
    out: dict[str, Any] = {}
    requirements = []
    for item in (raw.get("requirements") or [])[:_MAX_REQUIREMENTS]:
        if not isinstance(item, Mapping):
            continue
        clean: dict[str, Any] = {}
        for key in _REQUIREMENT_KEYS:
            value = item.get(key)
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, int):
                clean[key] = value
            elif (short := _short(value)) is not None:
                clean[key] = short
        if (name := _short(item.get("name"))) is not None:
            clean["name"] = name
        if any_of := _names(item.get("any_of")):
            clean["any_of"] = any_of
        if clean:
            requirements.append(clean)
    if requirements:
        out["requirements"] = requirements
    for key in _NAME_LIST_KEYS:
        if names := _names(raw.get(key)):
            out[key] = names
    counts = raw.get("counts")
    if isinstance(counts, Mapping):
        numbers = {
            str(k)[:40]: v
            for k, v in counts.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        if numbers:
            out["counts"] = numbers
    return out or None


def _score(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return min(max(number, Decimal("0")), Decimal("999.99"))


def _validate_source(source: str) -> None:
    if source not in JOB_PROPOSAL_SOURCES:
        raise ValueError(f"Unknown job proposal source: {source!r}")


async def upsert_proposals(
    db: AsyncSession,
    job_id: int,
    rows: Iterable[Mapping[str, Any]],
    source: str,
    run_id: Optional[str] = None,
) -> int:
    """Zapisz propozycje jednego źródła. Zwraca liczbę przetworzonych par.

    ``rows``: ``{"candidate_id": int, "score": number|None, "evidence": dict|None}``.
    Konflikt ``(job_id, candidate_id, source)`` odświeża ``last_seen_at``,
    ``score``, ``evidence`` (i ``run_id``, gdy podany). ``status``
    i ``first_seen_at`` zostają — patrz docstring modułu.
    """
    _validate_source(source)
    by_candidate: dict[int, dict] = {}
    for row in rows:
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, int) or isinstance(candidate_id, bool):
            continue
        # Ostatni wiersz tej samej osoby wygrywa: dwa wiersze jednej pary
        # w jednym INSERT … ON CONFLICT to błąd Postgresa (cardinality violation).
        by_candidate[candidate_id] = {
            "job_id": job_id,
            "candidate_id": candidate_id,
            "source": source,
            "score": _score(row.get("score")),
            "evidence": sanitize_evidence(row.get("evidence")),
            "run_id": run_id,
        }
    # Rosnąco po kandydacie — stała kolejność blokad wierszy między
    # równoległymi zapisami tego samego źródła.
    values = [by_candidate[cid] for cid in sorted(by_candidate)]
    for start in range(0, len(values), _UPSERT_CHUNK):
        chunk = values[start : start + _UPSERT_CHUNK]
        stmt = pg_insert(JobProposal).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_job_proposals_pair_source",
            set_={
                "last_seen_at": func.now(),
                "score": stmt.excluded.score,
                "evidence": stmt.excluded.evidence,
                "run_id": func.coalesce(stmt.excluded.run_id, JobProposal.run_id),
            },
        )
        await db.execute(stmt)
    return len(values)


async def mark_seen(
    db: AsyncSession, *, user_id: int, job_id: int, at: Optional[datetime] = None
) -> datetime:
    """Przesuń znacznik „widziane do" (nigdy wstecz). Zwraca zapisaną chwilę."""
    moment = at or datetime.now(timezone.utc)
    stmt = pg_insert(JobProposalSeen).values(
        user_id=user_id, job_id=job_id, seen_at=moment
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "job_id"],
        set_={"seen_at": func.greatest(JobProposalSeen.seen_at, stmt.excluded.seen_at)},
    ).returning(JobProposalSeen.seen_at)
    return (await db.execute(stmt)).scalar_one()


async def dismiss(
    db: AsyncSession, *, job_id: int, candidate_id: int, user_id: Optional[int]
) -> int:
    """Odrzuć propozycję tej osoby ze WSZYSTKICH źródeł. Zwraca liczbę wierszy.

    ``added`` zostaje nietknięte; powtórne odrzucenie nic nie zmienia (0).
    """
    result = await db.execute(
        update(JobProposal)
        .where(
            JobProposal.job_id == job_id,
            JobProposal.candidate_id == candidate_id,
            JobProposal.status == "proposed",
        )
        .values(status="dismissed", dismissed_by=user_id)
    )
    return int(result.rowcount or 0)


async def mark_added(
    db: AsyncSession, *, job_id: int, candidate_ids: Sequence[int]
) -> int:
    """Osoby faktycznie dodane do pipeline'u → ``added`` (także z ``dismissed``)."""
    ids = sorted({int(c) for c in candidate_ids})
    if not ids:
        return 0
    result = await db.execute(
        update(JobProposal)
        .where(
            JobProposal.job_id == job_id,
            JobProposal.candidate_id.in_(ids),
            JobProposal.status != "added",
        )
        .values(status="added")
    )
    return int(result.rowcount or 0)


async def mark_added_fail_soft(
    db: AsyncSession, *, job_id: int, candidate_ids: Sequence[int]
) -> None:
    """``mark_added`` w savepoincie — awaria nie cofa dodania do rekrutacji."""
    import logging

    if not candidate_ids:
        return
    try:
        async with db.begin_nested():
            await mark_added(db, job_id=job_id, candidate_ids=candidate_ids)
    except Exception as exc:  # noqa: BLE001 — propozycje nigdy nie psują dodania
        logging.getLogger(__name__).warning(
            "[job_proposals] mark_added skipped job=%s: %s",
            job_id,
            type(exc).__name__,
        )


def _in_pipeline(job_col, candidate_col):
    return exists(
        select(literal(1)).where(
            CandidateStage.job_id == job_col,
            CandidateStage.candidate_id == candidate_col,
        )
    )


def _pair_status():
    """Status pary z wierszy źródeł: added > dismissed > proposed."""
    return case(
        (func.bool_or(JobProposal.status == "added"), "added"),
        (func.bool_or(JobProposal.status == "dismissed"), "dismissed"),
        else_="proposed",
    )


async def new_count_for_jobs(
    db: AsyncSession, user_id: int, job_ids: Sequence[int]
) -> dict[int, int]:
    """Ile NOWYCH (od ostatniego spojrzenia tej osoby) propozycji ma rekrutacja.

    Jedno zapytanie dla całej strony listy. Rekrutacje bez nowych propozycji
    nie trafiają do słownika (wołający czyta ``.get(job_id, 0)``).
    """
    ids = sorted({int(j) for j in job_ids})
    if not ids:
        return {}
    pairs = (
        select(
            JobProposal.job_id.label("job_id"),
            JobProposal.candidate_id.label("candidate_id"),
        )
        .outerjoin(
            JobProposalSeen,
            and_(
                JobProposalSeen.job_id == JobProposal.job_id,
                JobProposalSeen.user_id == user_id,
            ),
        )
        .where(
            JobProposal.job_id.in_(ids),
            ~_in_pipeline(JobProposal.job_id, JobProposal.candidate_id),
        )
        .group_by(JobProposal.job_id, JobProposal.candidate_id)
        .having(
            _pair_status() == "proposed",
            # `seen_at` jest stałe w grupie (jedna para osoba–rekrutacja);
            # brak znacznika = wszystko jest nowe.
            func.bool_or(
                (JobProposalSeen.seen_at.is_(None))
                | (JobProposal.first_seen_at > JobProposalSeen.seen_at)
            ),
        )
        .subquery()
    )
    rows = await db.execute(
        select(pairs.c.job_id, func.count()).group_by(pairs.c.job_id)
    )
    return {int(job_id): int(n) for job_id, n in rows.all()}


@dataclass(frozen=True)
class ProposalRow:
    candidate_id: int
    sources: list[str]
    score: Optional[float]
    evidence: Optional[dict]
    first_seen_at: datetime
    last_seen_at: datetime
    is_new: bool
    status: str


async def list_for_job(
    db: AsyncSession,
    *,
    job_id: int,
    user_id: int,
    status: str = "proposed",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ProposalRow], int]:
    """Strona propozycji — jedna pozycja na OSOBĘ, ze złożonymi źródłami.

    Kolejność: wynik malejąco (brak wyniku na końcu), potem najnowsze, potem id
    — stabilna między stronami.
    """
    if status not in JOB_PROPOSAL_STATUSES:
        raise ValueError(f"Unknown job proposal status: {status!r}")
    seen_at = await db.scalar(
        select(JobProposalSeen.seen_at).where(
            JobProposalSeen.job_id == job_id, JobProposalSeen.user_id == user_id
        )
    )
    grouped = (
        select(
            JobProposal.candidate_id.label("candidate_id"),
            func.array_agg(func.distinct(JobProposal.source)).label("sources"),
            func.max(JobProposal.score).label("score"),
            func.min(JobProposal.first_seen_at).label("first_seen_at"),
            func.max(JobProposal.first_seen_at).label("newest_seen_at"),
            func.max(JobProposal.last_seen_at).label("last_seen_at"),
        )
        .where(JobProposal.job_id == job_id)
        .group_by(JobProposal.candidate_id)
        .having(_pair_status() == status)
    )
    if status == "proposed":
        grouped = grouped.where(
            ~_in_pipeline(JobProposal.job_id, JobProposal.candidate_id)
        )
    sub = grouped.subquery()
    total = int(await db.scalar(select(func.count()).select_from(sub)) or 0)
    page = (
        await db.execute(
            select(sub)
            .order_by(
                sub.c.score.desc().nullslast(),
                sub.c.newest_seen_at.desc(),
                sub.c.candidate_id,
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    candidate_ids = [row.candidate_id for row in page]
    evidence_by_candidate: dict[int, Optional[dict]] = {}
    if candidate_ids:
        # Dowody z wiersza o najwyższym wyniku (jedno zapytanie na stronę).
        evidence_rows = await db.execute(
            select(JobProposal.candidate_id, JobProposal.evidence)
            .where(
                JobProposal.job_id == job_id,
                JobProposal.candidate_id.in_(candidate_ids),
            )
            .order_by(
                JobProposal.candidate_id,
                JobProposal.score.desc().nullslast(),
                JobProposal.id,
            )
            .distinct(JobProposal.candidate_id)
        )
        evidence_by_candidate = {cid: ev for cid, ev in evidence_rows.all()}
    out = [
        ProposalRow(
            candidate_id=row.candidate_id,
            sources=sorted(row.sources or []),
            score=float(row.score) if row.score is not None else None,
            evidence=evidence_by_candidate.get(row.candidate_id),
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            is_new=seen_at is None or row.newest_seen_at > seen_at,
            status=status,
        )
        for row in page
    ]
    return out, total
