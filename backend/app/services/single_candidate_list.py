"""Jedna lista kandydatów rekrutacji (``SINGLE_CANDIDATE_LIST_ENABLED``, 08.11.2026).

Reguły i decyzje: ``docs/claude/rekrutacja-tablica/jedna-lista-kandydatow.md``.

Wyniki par leżą w ``job_proposals`` i ``job_autofill_pool``. Ten moduł scala je
przy odczycie w jeden wiersz na osobę i rekrutację, bez migracji i bez kopiowania
puli do ``job_proposals``: 34 tys. wierszy puli wymieniałoby się co noc, a każdy
czytelnik skrzynki (dzwonek, liczniki, wygaszanie) musiałby się ich wystrzegać.

* :func:`merged_rows` to jedyna definicja wierszy. Czytają ją lista i silnik kart.
* Wiersz puli zachowuje się jak ``full_base``, więc próg i status pary liczą się
  tak samo jak w skrzynce. Pula dopuszcza tylko osoby, które silnik mógłby dodać.
* ``job_board`` zostaje w ``NON_CANONICAL_SCORE_SOURCES``: stare wiersze niosą
  wynik scrapera w ``score``. Wynik „Dop.” przy nowym wierszu oznacza
  ``evidence.dop_scale``, a liczba scrapera zostaje w ``evidence.auto_match``.
* Kolejność to :mod:`review_batch_order`, ta sama co na Tablicy i w porcji.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import exists, func, literal, or_, select, text, true, union_all
from sqlalchemy.sql.expression import false

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_proposal import JobProposal
from app.services import job_proposals as proposals
from app.services.job_proposals import (
    DOP_SCALE_KEY,
    EXPIRED,
    NEW_PROPOSAL_WINDOW,
    NON_CANONICAL_SCORE_SOURCES,
    POSTING_RECENT_DAYS,
    POSTING_SOURCES,
    PREVIOUSLY_DISMISSED_KEY,
    ProposalRow,
)

logger = logging.getLogger(__name__)

FILTER_ALL = "all"
APPLIED = "applied"
NEW_IN_BASE = "new_in_base"
PORTAL = "portal"
KNOWN = "known"
SIMILAR = "similar"
LABELS = (APPLIED, NEW_IN_BASE, PORTAL, KNOWN, SIMILAR)
LIST_FILTERS = (FILTER_ALL, *LABELS)

_SIMILAR_SOURCES = frozenset({"reassign", "similar_projects"})
# Pełna kolejność tylko dla tylu najlepszych: fakty i reguły czytają osobę po
# osobie, a dalej nikt nie przewija. Reszta stoi za nimi wg wyniku.
ORDER_WINDOW = 500


def enabled() -> bool:
    return bool(getattr(settings, "SINGLE_CANDIDATE_LIST_ENABLED", False))


def merged_rows(job_id: int):
    """Żywe wiersze propozycji i puli rekrutacji w jednym kształcie."""
    from app.services.new_column_autofill import system_exclusions

    on_dop_scale = or_(
        JobProposal.source.notin_(NON_CANONICAL_SCORE_SOURCES),
        func.coalesce(JobProposal.evidence[DOP_SCALE_KEY].as_boolean(), false()),
    )
    from_proposals = select(
        JobProposal.candidate_id.label("candidate_id"),
        JobProposal.source.label("source"),
        JobProposal.status.label("status"),
        JobProposal.score.label("score"),
        on_dop_scale.label("canonical"),
        JobProposal.run_id.label("run_id"),
        JobProposal.evidence.label("evidence"),
        JobProposal.first_seen_at.label("first_seen_at"),
        JobProposal.last_seen_at.label("last_seen_at"),
        false().label("from_pool"),
    ).where(JobProposal.job_id == job_id, JobProposal.status != EXPIRED)
    from_pool = select(
        JobAutofillPool.candidate_id.label("candidate_id"),
        literal("full_base").label("source"),
        literal("proposed").label("status"),
        JobAutofillPool.score.label("score"),
        true().label("canonical"),
        JobAutofillPool.run_id.label("run_id"),
        JobAutofillPool.evidence.label("evidence"),
        JobAutofillPool.created_at.label("first_seen_at"),
        JobAutofillPool.created_at.label("last_seen_at"),
        true().label("from_pool"),
    ).where(
        JobAutofillPool.job_id == job_id,
        *[
            JobAutofillPool.candidate_id.not_in(refused)
            for refused in system_exclusions(job_id)
        ],
    )
    return union_all(from_proposals, from_pool).subquery("merged_rows")


def engine_rows(job_id: int, sources: Iterable[str]):
    """Wiersze, z których silnik „Nowych” może dobrać kartę (``ranked_picks``)."""
    rows = merged_rows(job_id)
    return select(
        rows.c.candidate_id.label("candidate_id"),
        rows.c.score.label("score"),
        rows.c.run_id.label("run_id"),
        rows.c.evidence.label("evidence"),
    ).where(
        rows.c.status == "proposed",
        rows.c.source.in_(list(sources)),
        rows.c.score.is_not(None),
    )


@dataclass(frozen=True)
class Pair:
    candidate_id: int
    sources: tuple[str, ...]
    rank_score: Optional[float]
    score: Optional[float]
    board_score: Optional[float]
    first_seen_at: datetime
    newest_seen_at: Optional[datetime]
    last_seen_at: datetime
    posting_seen_at: Optional[datetime]
    below_threshold: bool


@dataclass(frozen=True)
class ListPage:
    rows: list[ProposalRow]
    total: int
    # Liczby na plakietkach: tylko osoby od progu, jak kafle i dzwonek.
    counts: dict[str, int]


async def _pairs(db, job_id: int, threshold: float) -> list[Pair]:
    rows = merged_rows(job_id)
    portal_points = rows.c.evidence["auto_match"]["score"].as_float()
    result = await db.execute(
        select(
            rows.c.candidate_id,
            func.array_agg(func.distinct(rows.c.source)).label("sources"),
            func.max(rows.c.score).label("rank_score"),
            func.max(rows.c.score).filter(rows.c.canonical).label("score"),
            func.coalesce(
                func.max(portal_points).filter(rows.c.source == "job_board"),
                func.max(rows.c.score).filter(~rows.c.canonical),
            ).label("board_score"),
            func.min(rows.c.first_seen_at).label("first_seen_at"),
            func.max(rows.c.first_seen_at)
            .filter(~rows.c.from_pool)
            .label("newest_seen_at"),
            func.max(rows.c.last_seen_at).label("last_seen_at"),
            func.max(rows.c.first_seen_at)
            .filter(rows.c.source.in_(POSTING_SOURCES))
            .label("posting_seen_at"),
            (
                ~proposals.meets_threshold(
                    threshold, source=rows.c.source, score=rows.c.score
                )
            ).label("below_threshold"),
        )
        .where(
            ~proposals._in_pipeline(literal(job_id), rows.c.candidate_id),
            ~proposals._globally_blacklisted(rows.c.candidate_id),
        )
        .group_by(rows.c.candidate_id)
        .having(proposals._pair_status(rows.c.status) == "proposed")
        .order_by(
            func.max(rows.c.score).desc().nullslast(),
            func.max(rows.c.first_seen_at).desc(),
            rows.c.candidate_id,
        )
    )
    return [
        Pair(
            candidate_id=int(row.candidate_id),
            sources=tuple(sorted(row.sources or ())),
            rank_score=_number(row.rank_score),
            score=_number(row.score),
            board_score=_number(row.board_score),
            first_seen_at=row.first_seen_at,
            newest_seen_at=row.newest_seen_at,
            last_seen_at=row.last_seen_at,
            posting_seen_at=row.posting_seen_at,
            below_threshold=bool(row.below_threshold),
        )
        for row in result.all()
    ]


def _number(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


async def _evidence_of(
    db, job_id: int, candidate_ids: list[int]
) -> tuple[dict[int, Optional[dict]], dict[int, str]]:
    """Dowody z wiersza propozycji (puli, gdy osoba ma tylko pulę): propozycja
    niesie wymagania ze statusami, pula same nazwy."""
    if not candidate_ids:
        return {}, {}
    rows = merged_rows(job_id)
    result = await db.execute(
        select(rows.c.candidate_id, rows.c.evidence, rows.c.run_id)
        .where(rows.c.candidate_id.in_(candidate_ids))
        .order_by(
            rows.c.candidate_id, rows.c.from_pool, rows.c.score.desc().nullslast()
        )
    )
    evidence: dict[int, Optional[dict]] = {}
    runs: dict[int, str] = {}
    flagged: set[int] = set()
    for candidate_id, row_evidence, run_id in result.all():
        evidence.setdefault(candidate_id, row_evidence)
        if run_id and candidate_id not in runs:
            runs[candidate_id] = run_id
        if isinstance(row_evidence, dict) and row_evidence.get(
            PREVIOUSLY_DISMISSED_KEY
        ):
            flagged.add(candidate_id)
    for candidate_id in flagged:
        evidence[candidate_id] = {
            **(evidence.get(candidate_id) or {}),
            PREVIOUSLY_DISMISSED_KEY: True,
        }
    return evidence, runs


def _missing_critical(job: Job, evidence: Optional[dict]) -> tuple[str, ...]:
    """Brakujące krytyczne. ``missing_must`` niesie też zwykłe „musi mieć”,
    a o miejscu na końcu listy decyduje wyłącznie brak krytycznej."""
    from app.services.critical_skills import effective_critical

    missing = (evidence or {}).get("missing_must") or []
    if not missing:
        return ()
    critical = {label.casefold() for label in effective_critical(job).labels}
    return tuple(str(name) for name in missing if str(name).casefold() in critical)


async def _cards(
    db, job: Job, pairs: list[Pair], evidence: dict[int, Optional[dict]]
) -> list:
    """Karty do :mod:`review_batch_order`. Osoba bez wyniku stoi na końcu grupy."""
    from app.services.candidate_rate_from import (
        effective_currency_sql,
        effective_rate_sql,
    )
    from app.services.new_column_autofill import Pick, _by_rules
    from app.services.review_batch import PendingCard

    def score_of(pair: Pair) -> float:
        return pair.rank_score if pair.rank_score is not None else -1.0

    ruled = await _by_rules(
        db,
        job,
        [
            Pick(
                candidate_id=pair.candidate_id,
                score=score_of(pair),
                run_id=None,
                matched_must=(),
                missing_must=(),
            )
            for pair in pairs
        ],
        keep_all=True,
    )
    cautions = {pick.candidate_id: pick.cautions for pick in ruled}
    people = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    Candidate.id,
                    Candidate.availability_status,
                    effective_rate_sql(Candidate).label("rate"),
                    effective_currency_sql(Candidate).label("currency"),
                ).where(Candidate.id.in_([pair.candidate_id for pair in pairs]))
            )
        ).all()
    }
    return [
        PendingCard(
            process_id=0,
            job_id=job.id,
            candidate_id=pair.candidate_id,
            owner_id=None,
            score=score_of(pair),
            opened_at=None,
            cautions=cautions.get(pair.candidate_id, ()),
            missing_must=_missing_critical(job, evidence.get(pair.candidate_id)),
            availability_status=getattr(
                people.get(pair.candidate_id), "availability_status", None
            ),
            rate_from_hourly=getattr(people.get(pair.candidate_id), "rate", None),
            rate_currency=getattr(people.get(pair.candidate_id), "currency", None),
        )
        for pair in pairs
    ]


async def _ordered(
    db,
    job: Job,
    pairs: list[Pair],
    *,
    first_ids: frozenset[int],
    evidence: dict[int, Optional[dict]],
    now: datetime,
) -> tuple[list[Pair], set[int]]:
    """Kolejność listy i osoby „znamy”. Przepięcia i przekazania od praktykantów
    są decyzją człowieka, więc stoją przed kolejką, a osoby spod progu za nią."""
    from app.services import review_batch_order

    window = pairs[:ORDER_WINDOW]
    if not window:
        return [], set()
    by_id = {pair.candidate_id: pair for pair in window}
    cards = [
        replace(
            card,
            facts=replace(card.facts, fresh_first=card.candidate_id in first_ids),
        )
        for card in await review_batch_order.with_order_facts(
            db, job, await _cards(db, job, window, evidence), now=now
        )
    ]
    known = {
        card.candidate_id
        for card in cards
        if card.facts.known is not None and card.facts.known.points > 0
    }

    def group(card) -> int:
        pair = by_id[card.candidate_id]
        if "reassign" in pair.sources:
            return 0
        if "trainee" in pair.sources:
            return 1
        return 3 if pair.below_threshold else 2

    ranked: list = []
    for position in range(4):
        ranked += review_batch_order.order_cards(
            [card for card in cards if group(card) == position]
        )
    return [by_id[card.candidate_id] for card in ranked] + pairs[ORDER_WINDOW:], known


async def _applied_ids(db, job_id: int, candidate_ids: list[int]) -> set[int]:
    from app.services.integration_intake import candidates_with_application_evidence

    return await candidates_with_application_evidence(
        db, job_id=job_id, candidate_ids=candidate_ids
    )


def _labels(
    pair: Pair,
    *,
    posting_since: datetime,
    applied: set[int],
    first_ids: frozenset[int],
    known: set[int],
) -> tuple[str, ...]:
    flags = {
        APPLIED: pair.candidate_id in applied,
        NEW_IN_BASE: pair.candidate_id in first_ids,
        PORTAL: pair.posting_seen_at is not None
        and pair.posting_seen_at >= posting_since,
        KNOWN: pair.candidate_id in known,
        SIMILAR: bool(_SIMILAR_SOURCES.intersection(pair.sources)),
    }
    return tuple(label for label in LABELS if flags[label])


async def page(
    db,
    *,
    job: Job,
    threshold: float,
    first_ids: Iterable[int],
    limit: int,
    offset: int,
    list_filter: str,
    now: datetime,
) -> ListPage:
    """Strona listy po filtrze. Liczby plakietek nie zależą od wybranego filtra."""
    if list_filter not in LIST_FILTERS:
        raise ValueError(f"Unknown list filter: {list_filter!r}")
    fresh = frozenset(int(c) for c in first_ids)
    pairs = await _pairs(db, job.id, threshold)
    evidence, runs = await _evidence_of(
        db, job.id, [pair.candidate_id for pair in pairs[:ORDER_WINDOW]]
    )
    ordered, known = await _ordered(
        db, job, pairs, first_ids=fresh, evidence=evidence, now=now
    )
    posting_since = now - timedelta(days=POSTING_RECENT_DAYS)
    applied = await _applied_ids(db, job.id, [pair.candidate_id for pair in pairs])
    labels = {
        pair.candidate_id: _labels(
            pair,
            posting_since=posting_since,
            applied=applied,
            first_ids=fresh,
            known=known,
        )
        for pair in ordered
    }
    counted = [pair for pair in ordered if not pair.below_threshold]
    counts = {
        FILTER_ALL: len(counted),
        **{
            label: sum(1 for pair in counted if label in labels[pair.candidate_id])
            for label in LABELS
        },
    }
    matching = (
        ordered
        if list_filter == FILTER_ALL
        else [pair for pair in ordered if list_filter in labels[pair.candidate_id]]
    )
    chosen = matching[offset : offset + limit]
    unread = [p.candidate_id for p in chosen if p.candidate_id not in evidence]
    if unread:
        more_evidence, more_runs = await _evidence_of(db, job.id, unread)
        evidence = {**evidence, **more_evidence}
        runs = {**runs, **more_runs}
    new_since = now - NEW_PROPOSAL_WINDOW
    rows = [
        ProposalRow(
            candidate_id=pair.candidate_id,
            sources=list(pair.sources),
            score=pair.score,
            evidence=evidence.get(pair.candidate_id),
            first_seen_at=pair.first_seen_at,
            last_seen_at=pair.last_seen_at,
            is_new=pair.newest_seen_at is not None and pair.newest_seen_at >= new_since,
            status="proposed",
            run_id=runs.get(pair.candidate_id),
            posting_seen_at=pair.posting_seen_at,
            board_score=pair.board_score,
            below_threshold=pair.below_threshold,
            labels=labels[pair.candidate_id],
        )
        for pair in chosen
    ]
    return ListPage(rows=rows, total=len(matching), counts=counts)


async def split_counts(
    db, *, job_id: int, since: datetime, min_score: float
) -> dict[str, int]:
    """Lustro ``open_split_counts`` na scalonej liście — te same kafle i pary."""
    pairs = await _pairs(db, job_id, min_score)
    recent = [
        pair
        for pair in pairs
        if pair.posting_seen_at is not None and pair.posting_seen_at >= since
    ]
    below = sum(1 for pair in pairs if pair.below_threshold)
    postings = sum(1 for pair in recent if not pair.below_threshold)
    return {
        "postings_recent": postings,
        "base": len(pairs) - below - postings,
        "below_threshold": below,
    }


async def _in_pool(db, job_id: int, candidate_id: int) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    JobAutofillPool.job_id == job_id,
                    JobAutofillPool.candidate_id == candidate_id,
                )
            )
        )
    )


async def dismiss_pool_only(
    db,
    *,
    job_id: int,
    candidate_id: int,
    user_id: Optional[int],
    cv_revision: Optional[str],
    reason: Optional[str],
    note: Optional[str],
) -> int:
    """„Pomiń zaznaczone” przy osobie, którą lista ma tylko z puli."""
    if not enabled() or not await _in_pool(db, job_id, candidate_id):
        return 0
    return await proposals.dismiss_unlisted(
        db,
        job_id=job_id,
        candidate_id=candidate_id,
        user_id=user_id,
        cv_revision=cv_revision,
        reason=reason,
        note=note,
    )


async def reopen_pool_only(db, *, job_id: int, candidate_id: int) -> int:
    """„Cofnij” dodania osoby z puli: usunięcie z rekrutacji odcina wiersz puli,
    więc zaraz po dodaniu wraca ona na listę jako propozycja ``full_base``."""
    if not enabled():
        return 0
    has_proposal = await db.scalar(
        select(
            exists().where(
                JobProposal.job_id == job_id,
                JobProposal.candidate_id == candidate_id,
            )
        )
    )
    if has_proposal:
        return 0
    row = await db.get(JobAutofillPool, (job_id, candidate_id))
    if row is None:
        return 0
    return await proposals.upsert_proposals(
        db,
        job_id,
        [
            {
                "candidate_id": candidate_id,
                "score": row.score,
                "evidence": row.evidence,
                "cv_revision": row.cv_revision,
            }
        ],
        source="full_base",
        run_id=row.run_id,
    )


# ── Portale na skali „Dop.” ─────────────────────────────────────────────────


async def dop_scores(db, job: Job, candidates: list[Candidate]) -> dict[int, float]:
    """Wynik „Dop.” osób z aktualnym wektorem. Awaria nie psuje zapisu: wiersz
    zostaje bez liczby, tak jak przy nieaktualnym wektorze."""
    if not enabled() or not candidates:
        return {}
    from app.services.auto_match_service import _fit_context
    from app.services.canonical_fit import score_candidates

    try:
        async with db.begin_nested():
            context = await _fit_context(db, job)
            fits = await score_candidates(db, context, list(candidates))
    except Exception as exc:  # noqa: BLE001 — wynik to dodatek do zapisu
        logger.warning(
            "[single_list] portal score failed job=%s: %s", job.id, type(exc).__name__
        )
        return {}
    return {
        int(fit.breakdown.candidate_id): round(float(fit.fit_score), 2)
        for fit in fits
        if fit.fit_score is not None
    }


def portal_score(
    candidate_id: int,
    scraper_score: Any,
    evidence: Optional[dict],
    dop: dict[int, float],
) -> tuple[Any, Optional[dict]]:
    """Wynik i dowody wiersza ``job_board``. Liczba scrapera zostaje w dowodach
    (``auto_match.score``) i nigdy nie trafia do ``score`` nowego wiersza."""
    if not enabled():
        return scraper_score, evidence
    score = dop.get(candidate_id)
    if score is None:
        return None, evidence
    return score, {**(evidence or {}), DOP_SCALE_KEY: True}


async def fill_portal_scores(db, scored: Iterable[Any]) -> int:
    """Kolejka CV dopisuje „Dop.” wierszom portalu, które czekały bez liczby."""
    pairs = list(scored)
    if not enabled() or not pairs:
        return 0
    try:
        async with db.begin_nested():
            result = await db.execute(
                text(
                    """
                    UPDATE job_proposals AS p
                    SET score = round(v.score::numeric, 2),
                        evidence = (CASE WHEN jsonb_typeof(p.evidence) = 'object'
                                         THEN p.evidence ELSE '{}'::jsonb END)
                                   || jsonb_build_object('dop_scale', true)
                    FROM unnest(CAST(:jobs AS int[]), CAST(:people AS int[]),
                                CAST(:scores AS double precision[]))
                         AS v(job_id, candidate_id, score)
                    WHERE p.job_id = v.job_id
                      AND p.candidate_id = v.candidate_id
                      AND p.source = 'job_board'
                      AND p.status = 'proposed'
                      AND p.score IS NULL
                    """
                ),
                {
                    "jobs": [row.job_id for row in pairs],
                    "people": [row.candidate_id for row in pairs],
                    "scores": [row.score for row in pairs],
                },
            )
    except Exception as exc:  # noqa: BLE001 — dodatek do oceny CV
        logger.warning("[single_list] portal fill failed: %s", type(exc).__name__)
        return 0
    return int(result.rowcount or 0)
