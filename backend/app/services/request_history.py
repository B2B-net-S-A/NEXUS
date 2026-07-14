"""Request history retrieval — siostrzane requesty dla widoku 'Historia' (Phase 16+).

Mirror dataclass-based service inspired by `historical_jobs_retrieval.py` (Phase 15)
but with three deliberate differences from that contract:

1. Includes BOTH `closed` and open/in-progress jobs (caller decides via
   `include_open`).
2. Does NOT require `champion_profile` to be populated — most operational rows
   never had one filled.
3. Semantic ranking by default: Voyage + Qdrant cosine similarity drives the
   order so the tab surfaces requests similar in ROLE, not merely the most
   recent ones from the same client. The same-client SQL recency pool is a
   degraded fallback, used only when semantic retrieval is unavailable (Qdrant
   down, missing embedding, or empty query text).

Returns rich aggregated metadata (champion, TTH, fee, owners, candidates count)
in a single batched aggregator to avoid N+1.

Fall-back: any infrastructure failure logs WARNING and returns []. Retrieval
must never block the caller path.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services.embedding_service import VECTOR_SIZE, generate_embedding
from app.services.historical_jobs_retrieval import (
    QDRANT_OVERSAMPLE_FACTOR,
    _qdrant_search,
)

logger = logging.getLogger(__name__)


# ── Tunables ─────────────────────────────────────────────────────────────────

SQL_FAST_PATH_LIMIT: int = 50
SAME_TRAIN_BOOST: float = 0.05


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RequestHistoryEntry:
    """One historical/in-progress sibling request with rich operational metadata."""

    job_id: int
    title: str
    train_name: Optional[str]
    same_train: bool
    seniority: Optional[str]
    status: str  # JobStatus.value
    is_in_progress: bool
    outcome: Optional[Literal["filled", "cancelled"]]
    close_reason: Optional[str]  # JobCloseReason.value or None
    similarity: float
    similarity_source: Literal["sql_same_client", "voyage"]
    closed_at: Optional[datetime]
    created_at: datetime
    tth_days: Optional[int]
    client_id: Optional[int]
    client_name: Optional[str]
    champion_name: Optional[str]
    champion_candidate_id: Optional[int]
    champions_count: int
    candidates_count: int
    fee_rate: Optional[int]  # monthly_margin (PLN-equivalent), nullable
    fee_currency: Optional[str]
    rate_unit: Optional[str]
    tac_name: Optional[str]
    delivery_lead_name: Optional[str]


@dataclass(frozen=True)
class _Meta:
    """Aggregated per-job metadata used internally by `_aggregate_request_metadata`."""

    champion_candidate_id: Optional[int] = None
    champion_name: Optional[str] = None
    champions_count: int = 0
    candidates_count: int = 0
    fee_rate: Optional[int] = None
    fee_currency: Optional[str] = None
    rate_unit: Optional[str] = None


# ── Public API ───────────────────────────────────────────────────────────────


async def find_similar_requests(
    db: AsyncSession,
    *,
    client_id: Optional[int],
    title: str,
    raw_description: Optional[str] = None,
    train_name: Optional[str] = None,
    top_k: int = 10,
    cross_client: bool = False,
    exclude_job_id: Optional[int] = None,
    include_open: bool = True,
) -> list[RequestHistoryEntry]:
    """Find sibling requests (closed + optionally in-progress) for the 'Historia' tab.

    Retrieval order:
        1. Voyage + Qdrant semantic search (scoped to `client_id` unless
           `cross_client`) is the primary ranker — results are ordered by role
           similarity.
        2. SQL same-client recency pool only as a degraded fallback when the
           semantic step returns nothing (Qdrant down / unembedded / no query).
        3. Single SQL round-trip loads the chosen pool and post-filters status.
        4. Single aggregator query batch enriches with champion / TTH / fee /
           owners.

    Args:
        db: Async DB session.
        client_id: Same-client filter when set + `cross_client=False`.
        title: Role title — primary embedding signal.
        raw_description: JD text (optional, concatenated for embedding).
        train_name: Programme tag of CURRENT role; used to mark `same_train`
            and to bias same-client SQL ordering.
        top_k: Max results to return per call.
        cross_client: Drop client filter, return matches from any client.
        exclude_job_id: Self-exclude (e.g. when called for a saved job).
        include_open: Keep `published`/`draft`(non-self) status rows. False ⇒
            only `closed`.

    Returns:
        List of RequestHistoryEntry sorted by (same_train boost + similarity)
        desc, recency desc. Length 0..top_k.
    """
    target_train = (train_name or "").strip().lower() or None

    # ── 1. Semantic search — PRIMARY ranker ─────────────────────────────────
    # Scoped to the client unless cross_client. Job embedding coverage is
    # effectively complete, so this returns real cosine similarity for ~all
    # same-client requests and orders them by ROLE similarity rather than
    # recency. (Previously the same-client SQL fast-path returned every recent
    # request at a flat 1.0, surfacing unrelated roles — the bug this fixes.)
    voyage_hits: dict[int, float] = await _voyage_candidates(
        client_id=None if cross_client else client_id,
        title=title,
        raw_description=raw_description,
        top_k=top_k,
        exclude_job_id=exclude_job_id,
    )

    # ── 2. SQL same-client fallback (degraded mode) ─────────────────────────
    # Only when semantic retrieval yields nothing (Qdrant down / unembedded /
    # empty query) AND we have a concrete same-client scope. Recency-ordered,
    # flat similarity — never competes with semantic hits because it runs only
    # when there are none.
    sql_hits: dict[int, float] = {}
    if not voyage_hits and not cross_client and client_id is not None:
        sql_hits = await _sql_same_client_candidates(
            db,
            client_id=client_id,
            target_train=target_train,
            include_open=include_open,
            exclude_job_id=exclude_job_id,
            limit=SQL_FAST_PATH_LIMIT,
        )

    # ── 3. Union ────────────────────────────────────────────────────────────
    if not sql_hits and not voyage_hits:
        return []

    candidate_ids = list({*sql_hits.keys(), *voyage_hits.keys()})

    # ── 4. Post-filter SQL: load Job rows + status filter ──────────────────
    job_rows = await _load_jobs_with_clients(
        db, candidate_ids, include_open=include_open, exclude_job_id=exclude_job_id
    )
    if not job_rows:
        return []

    # ── 5. Aggregator: champion + counts + fee + owners (batched) ──────────
    job_ids = [j.id for j, _client_name in job_rows]
    meta_by_id = await _aggregate_request_metadata(db, job_ids)
    owner_names = await _load_owner_names(db, job_rows)

    entries: list[RequestHistoryEntry] = []
    for job, client_name in job_rows:
        sim_voyage = voyage_hits.get(job.id)
        sim_sql = sql_hits.get(job.id)
        if sim_voyage is not None:
            similarity = sim_voyage
            similarity_source: Literal["sql_same_client", "voyage"] = "voyage"
        elif sim_sql is not None:
            similarity = sim_sql
            similarity_source = "sql_same_client"
        else:
            continue  # Should not happen — id list came from these dicts.

        job_train = getattr(job, "train_name", None)
        same_train = bool(
            target_train and job_train and job_train.strip().lower() == target_train
        )

        is_in_progress = job.status != JobStatus.closed
        meta = meta_by_id.get(job.id, _Meta())
        outcome: Optional[Literal["filled", "cancelled"]]
        if is_in_progress:
            outcome = None
        elif meta.champion_candidate_id is not None:
            outcome = "filled"
        else:
            outcome = "cancelled"

        tth_days: Optional[int] = None
        if job.closed_at and job.created_at:
            tth_days = max((job.closed_at - job.created_at).days, 0)

        entries.append(
            RequestHistoryEntry(
                job_id=job.id,
                title=job.title or f"Job {job.id}",
                train_name=job_train,
                same_train=same_train,
                seniority=(job.seniority.value if job.seniority else None),
                status=job.status.value
                if hasattr(job.status, "value")
                else str(job.status),
                is_in_progress=is_in_progress,
                outcome=outcome,
                close_reason=(
                    job.close_reason.value
                    if isinstance(job.close_reason, JobCloseReason)
                    else None
                ),
                similarity=round(float(similarity), 4),
                similarity_source=similarity_source,
                closed_at=job.closed_at,
                created_at=job.created_at,
                tth_days=tth_days,
                client_id=job.client_id,
                client_name=client_name,
                champion_name=meta.champion_name,
                champion_candidate_id=meta.champion_candidate_id,
                champions_count=meta.champions_count,
                candidates_count=meta.candidates_count,
                fee_rate=meta.fee_rate,
                fee_currency=meta.fee_currency,
                rate_unit=meta.rate_unit,
                tac_name=owner_names.get(("tac", job.id)),
                delivery_lead_name=owner_names.get(("dl", job.id)),
            )
        )

    # ── 6. Sort + trim ──────────────────────────────────────────────────────
    entries.sort(
        key=lambda e: (
            e.similarity + (SAME_TRAIN_BOOST if e.same_train else 0.0),
            e.closed_at or e.created_at,
        ),
        reverse=True,
    )
    return entries[:top_k]


def aggregate_meta_counts(entries: list[RequestHistoryEntry]) -> dict[str, int]:
    """Counters for the API meta payload: how many came from SQL vs Voyage."""
    sql_count = sum(1 for e in entries if e.similarity_source == "sql_same_client")
    voyage_count = len(entries) - sql_count
    return {
        "sql_count": sql_count,
        "voyage_count": voyage_count,
        "total": len(entries),
    }


# ── Internals ────────────────────────────────────────────────────────────────


async def _sql_same_client_candidates(
    db: AsyncSession,
    *,
    client_id: int,
    target_train: Optional[str],
    include_open: bool,
    exclude_job_id: Optional[int],
    limit: int,
) -> dict[int, float]:
    """Cheap same-client lookup. Returns {job_id: 1.0}. Sorted: same-train first,
    then closed_at desc, then created_at desc.
    """
    stmt = select(Job.id).where(
        Job.client_id == client_id, Job.status != JobStatus.draft
    )
    if exclude_job_id is not None:
        stmt = stmt.where(Job.id != exclude_job_id)
    if not include_open:
        stmt = stmt.where(Job.status == JobStatus.closed)

    # Same-train hits first when target_train is provided. Postgres NULLS LAST
    # via the explicit boolean expression keeps the ordering stable.
    if target_train:
        stmt = stmt.order_by(
            (func.lower(func.coalesce(Job.train_name, "")) == target_train).desc(),
            Job.closed_at.desc().nullslast(),
            Job.created_at.desc(),
        )
    else:
        stmt = stmt.order_by(
            Job.closed_at.desc().nullslast(),
            Job.created_at.desc(),
        )
    stmt = stmt.limit(limit)

    rows = (await db.execute(stmt)).all()
    return {row[0]: 1.0 for row in rows}


async def _voyage_candidates(
    *,
    client_id: Optional[int],
    title: str,
    raw_description: Optional[str],
    top_k: int,
    exclude_job_id: Optional[int],
) -> dict[int, float]:
    """Embed + Qdrant search. Returns {job_id: cosine_similarity}.

    Always returns {} on infra failure (logged at WARNING) — caller still has
    the SQL fast-path pool to render.
    """
    query_text = _build_query_text(title=title, raw_description=raw_description)
    if not query_text:
        return {}

    embedding = await generate_embedding(query_text, input_type="query")
    if embedding is None or len(embedding) != VECTOR_SIZE:
        logger.warning(
            "[request_history] embedding unavailable (text_len=%d)", len(query_text)
        )
        return {}

    qdrant_limit = max(top_k * QDRANT_OVERSAMPLE_FACTOR, top_k)
    hits = await asyncio.to_thread(_qdrant_search, embedding, client_id, qdrant_limit)
    if not hits:
        return {}

    out: dict[int, float] = {}
    for h in hits:
        jid = h["job_id"]
        if exclude_job_id is not None and jid == exclude_job_id:
            continue
        out[jid] = float(h["score"])
    return out


def _build_query_text(*, title: str, raw_description: Optional[str]) -> str:
    """Same shape as `historical_jobs_retrieval._build_query_text` so retrieval
    is consistent with what was indexed.
    """
    parts: list[str] = []
    if title:
        parts.append(title.strip())
    if raw_description:
        parts.append(raw_description.strip()[:1200])
    return " ".join(p for p in parts if p).strip()


async def _load_jobs_with_clients(
    db: AsyncSession,
    job_ids: list[int],
    *,
    include_open: bool,
    exclude_job_id: Optional[int],
) -> list[tuple[Job, Optional[str]]]:
    """Single SELECT on `jobs LEFT JOIN clients` filtered by allowed status."""
    if not job_ids:
        return []
    stmt = (
        select(Job, Client.name)
        .join(Client, Job.client_id == Client.id, isouter=True)
        .where(Job.id.in_(job_ids), Job.status != JobStatus.draft)
    )
    if exclude_job_id is not None:
        stmt = stmt.where(Job.id != exclude_job_id)
    if not include_open:
        stmt = stmt.where(Job.status == JobStatus.closed)
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def _aggregate_request_metadata(
    db: AsyncSession, job_ids: list[int]
) -> dict[int, _Meta]:
    """Batched aggregator for outcome / champion / counts / fee. 3 small queries.

    Uses Postgres `DISTINCT ON` (job_id) to grab the most recent hire / contract
    per job without a Cartesian explosion. Indexes:
    - candidate_stages(job_id, stage, moved_at DESC) — already exists
    - contracts(job_id) — already exists
    """
    if not job_ids:
        return {}

    # Q1: most-recent hired CandidateStage per job + Candidate name
    hired_rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                CandidateStage.candidate_id,
                Candidate.name,
                Candidate.lastname,
                CandidateStage.moved_at,
            )
            .join(Candidate, CandidateStage.candidate_id == Candidate.id)
            .where(
                CandidateStage.job_id.in_(job_ids),
                CandidateStage.stage == PipelineStage.hired,
            )
            .order_by(
                CandidateStage.job_id,
                CandidateStage.moved_at.desc(),
            )
            .distinct(CandidateStage.job_id)
        )
    ).all()

    # Q2: champions count per job (distinct candidate_ids on `hired`)
    champions_count_rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                func.count(func.distinct(CandidateStage.candidate_id)),
            )
            .where(
                CandidateStage.job_id.in_(job_ids),
                CandidateStage.stage == PipelineStage.hired,
            )
            .group_by(CandidateStage.job_id)
        )
    ).all()
    champions_count_by_id: dict[int, int] = {
        row[0]: int(row[1] or 0) for row in champions_count_rows
    }

    # Q3: total distinct candidates per job (any stage)
    cand_count_rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                func.count(func.distinct(CandidateStage.candidate_id)),
            )
            .where(CandidateStage.job_id.in_(job_ids))
            .group_by(CandidateStage.job_id)
        )
    ).all()
    cand_count_by_id: dict[int, int] = {
        row[0]: int(row[1] or 0) for row in cand_count_rows
    }

    # Q4: latest contract per job (for fee) — DISTINCT ON job_id
    contract_rows = (
        (
            await db.execute(
                select(Contract)
                .where(Contract.job_id.in_(job_ids))
                .order_by(Contract.job_id, Contract.created_at.desc())
                .distinct(Contract.job_id)
            )
        )
        .scalars()
        .all()
    )
    contract_by_id: dict[int, Contract] = {
        c.job_id: c for c in contract_rows if c.job_id
    }

    out: dict[int, _Meta] = {}
    for jid in job_ids:
        champion_name: Optional[str] = None
        champion_candidate_id: Optional[int] = None
        for row in hired_rows:
            row_jid, cand_id, name, lastname, _moved_at = row
            if row_jid == jid:
                champion_candidate_id = int(cand_id)
                first = (name or "").strip()
                last = (lastname or "").strip()
                champion_name = " ".join(p for p in (first, last) if p) or None
                break

        contract = contract_by_id.get(jid)
        fee_rate: Optional[int] = None
        fee_currency: Optional[str] = None
        rate_unit: Optional[str] = None
        if contract is not None:
            fee_rate = contract.monthly_margin
            fee_currency = contract.currency
            rate_unit = (
                contract.rate_unit.value
                if hasattr(contract.rate_unit, "value")
                else str(contract.rate_unit)
                if contract.rate_unit
                else None
            )

        out[jid] = _Meta(
            champion_candidate_id=champion_candidate_id,
            champion_name=champion_name,
            champions_count=champions_count_by_id.get(jid, 0),
            candidates_count=cand_count_by_id.get(jid, 0),
            fee_rate=fee_rate,
            fee_currency=fee_currency,
            rate_unit=rate_unit,
        )
    return out


async def _load_owner_names(
    db: AsyncSession, job_rows: Iterable[tuple[Job, Any]]
) -> dict[tuple[str, int], str]:
    """Resolve TAC + DL display names from User table in one round-trip."""
    user_ids: set[int] = set()
    for job, _ in job_rows:
        if job.tac_id is not None:
            user_ids.add(job.tac_id)
        if job.delivery_lead_id is not None:
            user_ids.add(job.delivery_lead_id)
    if not user_ids:
        return {}

    rows = (
        await db.execute(
            select(User.id, User.name, User.email).where(User.id.in_(user_ids))
        )
    ).all()
    name_by_id: dict[int, str] = {}
    for uid, name, email in rows:
        name_by_id[int(uid)] = (
            (name or "").strip() or (email or "").strip() or f"User {uid}"
        )

    out: dict[tuple[str, int], str] = {}
    for job, _ in job_rows:
        if job.tac_id is not None and job.tac_id in name_by_id:
            out[("tac", job.id)] = name_by_id[job.tac_id]
        if job.delivery_lead_id is not None and job.delivery_lead_id in name_by_id:
            out[("dl", job.id)] = name_by_id[job.delivery_lead_id]
    return out
