"""Pomiar wag „Dop.” na historii i podgląd na żywo (panel „Ranking kandydatów”).

Ten sam pomiar co ``scripts/eval_manual_search_order --rerank-top 200``
(kolejność produkcji od 19.10.2026: wektor kolumny „Dop.”, 200 pierwszych
ułożonych pełnym „Dop.”), zawężony do zamkniętych rekrutacji. Dla każdej
rekrutacji: dwa pierwsze „musi mieć” jako wiersze wymagań, baza cofnięta do
dnia otwarcia, właściwe osoby = zweryfikowane albo wysłane do klienta.

Składniki oceny (``Components``) liczymy RAZ, profilem sondy z niezerową wagą
każdej warstwy, a potem przeliczamy „Dop.” dla dowolnych wag bez modelu
językowego — tak samo jak ``scoring_service.score_candidate_job`` składa wynik
z warstw. Zgodność z silnikiem pilnuje ``tests/test_ranking_lab.py``.

Tylko odczyt: każda rekrutacja w osobnej sesji ``SET TRANSACTION READ ONLY``,
wektor zapytania prosto z Voyage (bez ``embedding_cache``), zweryfikowane
wymagania zamaskowane, a notatki-dowody i wcześniejsze rozmowy tylko sprzed
dnia otwarcia (powstają w trakcie procesu — to etykieta, nie dane z dnia
otwarcia).
"""

from __future__ import annotations

import asyncio
import logging
import re
import statistics
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from sqlalchemy import select, text

from app.services.ranking_weights import BASE_LAYERS, PanelWeights, engine_weights
from app.services.scoring_service import WeightProfile

logger = logging.getLogger(__name__)

PAGE = 50
HEAD = 200
MEASURE_JOBS = 120
SCAN_LIMIT = 600
MIN_POOL = 100
MIN_POSITIVES = 2
# Każda warstwa z niezerową wagą — inaczej udział warstwy z wagą 0 w wagach
# opublikowanych byłby nieznany i suwak nie miałby czego przeliczyć.
PROBE = WeightProfile(
    id=0,
    name="probe",
    semantic=20.0,
    skills=20.0,
    salary=20.0,
    location=20.0,
    availability=20.0,
    champion_fit=0.0,
)

# Kandydaci do pomiaru i podglądu: zamknięte, ≥ 2 „musi mieć”, ostatnie
# 24 miesiące, ≥ 2 właściwe osoby, które były w bazie przed otwarciem.
_ELIGIBLE_JOBS = """
    select j.id, coalesce(j.opened_at, j.created_at) t0, j.must_skills, j.title,
           j.location,
           (select count(distinct m.candidate_id) from analytics_first_milestones m
            join candidates c on c.id = m.candidate_id
            where m.job_id = j.id and m.stage in ('verified','cv_sent')
              and c.created_at < coalesce(j.opened_at, j.created_at)) positives
    from jobs j
    where (case when jsonb_typeof(j.must_skills)='array'
                then jsonb_array_length(j.must_skills) else 0 end) >= 2
      and coalesce(j.opened_at, j.created_at) > now() - interval '24 months'
      {closed}
      and (select count(*) from analytics_first_milestones m
           join candidates c on c.id = m.candidate_id
           where m.job_id = j.id and m.stage in ('verified','cv_sent')
             and c.created_at < coalesce(j.opened_at, j.created_at)) >= 2
    {only}
    order by j.id desc limit :limit
"""


# ── Składniki oceny i przeliczenie ───────────────────────────────────────────


@dataclass(frozen=True)
class Components:
    """Wszystko, czego trzeba, by złożyć „Dop.” dla innych wag.

    ``layers[name] = (ułamek punktów warstwy, maks. warstwy / waga warstwy,
    czy oceniona)``; ``extra`` = warstwa wcześniejszych rozmów (punkty, maks.),
    która nie zależy od wag; ``factor`` = kary mnożnikowe (staż, konflikt
    dostępności)."""

    candidate_id: int
    layers: dict[str, tuple[float, float, bool]]
    extra: Optional[tuple[float, float]]
    factor: float
    matched_must: int
    must_total: int

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "layers": {
                name: [round(f, 6), round(m, 6), scored]
                for name, (f, m, scored) in self.layers.items()
            },
            "extra": [round(v, 6) for v in self.extra] if self.extra else None,
            "factor": round(self.factor, 6),
            "matched_must": self.matched_must,
            "must_total": self.must_total,
        }


def normalized(weights: dict) -> dict[str, float]:
    """Wagi pięciu warstw przeliczone do 100 — jak ``base_fit_profile``."""
    total = sum(float(weights.get(name, 0.0)) for name in BASE_LAYERS)
    if total <= 0:
        raise ValueError("co najmniej jedna waga musi być większa od zera")
    return {name: float(weights.get(name, 0.0)) * 100.0 / total for name in BASE_LAYERS}


def _composite(
    layers: dict[str, tuple[float, float, bool]],
    extra: Optional[tuple[float, float]],
    weights: dict[str, float],
    *,
    renormalize: bool,
) -> float:
    earned = available = plain = 0.0
    for name in BASE_LAYERS:
        fraction, share, scored = layers[name]
        max_points = share * weights[name]
        points = fraction * max_points
        plain += points
        if scored:
            earned += points
            available += max_points
    if renormalize:
        if extra is not None:
            earned += extra[0]
            available += extra[1]
        return earned / available * 100.0 if available > 0 else 0.0
    if extra is not None:
        return (plain + extra[0]) * 100.0 / (100.0 + extra[1])
    return plain


def components_of(breakdown, *, renormalize: bool) -> Components:
    """Składniki z ``ScoreBreakdown`` policzonego profilem ``PROBE``."""
    probe = normalized({name: getattr(PROBE, name) for name in BASE_LAYERS})
    layers: dict[str, tuple[float, float, bool]] = {}
    for name in BASE_LAYERS:
        layer = getattr(breakdown, name)
        max_points = float(layer.max_points or 0.0)
        fraction = float(layer.points) / max_points if max_points > 0 else 0.0
        share = max_points / probe[name] if probe[name] > 0 else 0.0
        layers[name] = (fraction, share, bool(layer.scored))
    prior = getattr(breakdown, "prior_screening", None)
    extra = (
        (float(prior.points), float(prior.max_points))
        if prior is not None and prior.scored and prior.max_points > 0
        else None
    )
    composite = _composite(layers, extra, probe, renormalize=renormalize)
    factor = float(breakdown.total) / composite if composite > 0 else 1.0
    must_total = len(breakdown.matching_must or []) + len(breakdown.gap_must or [])
    return Components(
        candidate_id=int(breakdown.candidate_id),
        layers=layers,
        extra=extra,
        factor=factor,
        matched_must=len(breakdown.matching_must or []),
        must_total=must_total,
    )


def score(c: Components, weights: dict, *, renormalize: bool) -> float:
    total = _composite(c.layers, c.extra, normalized(weights), renormalize=renormalize)
    return total * c.factor if total > 0 else total


def proposal_eligible(c: Components, value: float, threshold: float) -> bool:
    """Lustro ``auto_match_rules.is_good_match``: próg + ≥ 1 trafione must."""
    return value >= threshold and (c.must_total == 0 or c.matched_must > 0)


# ── Przypadki z historii ─────────────────────────────────────────────────────


@dataclass
class Case:
    job_id: int
    title: str
    location: Optional[str]
    order: list[int]
    positives: frozenset[int]
    head: dict[int, Components]
    renormalize: bool
    people: dict[int, dict] = field(default_factory=dict)

    def ranked(self, weights: dict) -> list[int]:
        head_ids = self.order[:HEAD]
        position = {cid: i for i, cid in enumerate(head_ids)}
        values = {
            cid: score(self.head[cid], weights, renormalize=self.renormalize)
            if cid in self.head
            else -1.0
            for cid in head_ids
        }
        reranked = sorted(head_ids, key=lambda cid: (-values[cid], position[cid]))
        return reranked + self.order[HEAD:]

    def proposals(self, weights: dict, threshold: float) -> int:
        return sum(
            1
            for c in self.head.values()
            if proposal_eligible(
                c, score(c, weights, renormalize=self.renormalize), threshold
            )
        )


def _fts(word: str):
    from app.services import keyword_terms as kt

    term = kt.parse_keyword(word)
    if term is None or term.open_start:
        return None
    query = kt.tsquery_text(term)
    return None if query is None else (query, kt.tsquery_path_variants(term))


def must_words(must) -> list:
    """Dwa pierwsze „musi mieć” jak w ``eval_manual_search_order``."""
    words = []
    for item in must or []:
        name = (
            ((item.get("name") if isinstance(item, dict) else str(item)) or "")
            .strip()
            .lower()
        )
        if not re.fullmatch(r"[a-z0-9ąćęłńóśźż#+.]{2,20}", name):
            continue
        parsed = _fts(name)
        if parsed:
            words.append(parsed)
        if len(words) == 2:
            break
    return words


def _exact_order(client, vector, ids: list[int]) -> list[int]:
    from qdrant_client.models import (
        Filter,
        HasIdCondition,
        QuantizationSearchParams,
        SearchParams,
    )

    from app.services import embedding_service as emb

    hits = client.search(
        collection_name=emb._collection(),
        query_vector=vector,
        query_filter=Filter(must=[HasIdCondition(has_id=ids)]),
        search_params=SearchParams(
            exact=True, quantization=QuantizationSearchParams(ignore=True)
        ),
        limit=len(ids),
        with_payload=False,
        with_vectors=False,
    )
    ordered = [int(h.id) for h in hits]
    seen = set(ordered)
    return ordered + [i for i in ids if i not in seen]


async def eligible_jobs(
    db, *, limit: int = SCAN_LIMIT, job_id: Optional[int] = None, closed: bool = True
) -> list:
    sql = _ELIGIBLE_JOBS.format(
        closed="and j.status = 'closed'" if closed else "",
        only="and j.id = :job_id" if job_id is not None else "",
    )
    params: dict = {"limit": limit}
    if job_id is not None:
        params["job_id"] = job_id
    return list((await db.execute(text(sql), params)).all())


async def build_case(db, row, client, *, with_people: bool = False) -> Optional[Case]:
    """Jedna rekrutacja z historii albo ``None``, gdy nie da się jej odtworzyć."""
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services.canonical_fit import score_candidates
    from app.services.full_search_measurement import request_vector
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import _renormalizing

    job_id, t0, must = row.id, row.t0, row.must_skills
    words = must_words(must)
    if len(words) < 2:
        return None
    parts, params = [], {"t0": t0, "jid": job_id}
    for i, (query, variants) in enumerate(words):
        params[f"q{i}"] = query
        part = f"to_tsquery('simple', :q{i})"
        if variants:
            params[f"v{i}"] = variants
            part = f"({part} || cast(:v{i} as tsquery))"
        parts.append(part)
    ids = list(
        (
            await db.execute(
                text(
                    "select id from candidates c where c.created_at < :t0 "
                    f"and c.keyword_fts @@ ({' && '.join(parts)}) "
                    "order by c.created_at desc, c.id desc"
                ),
                params,
            )
        ).scalars()
    )
    if len(ids) < MIN_POOL:
        return None
    positives = frozenset(
        (
            await db.execute(
                text(
                    "select distinct m.candidate_id from analytics_first_milestones m "
                    "join candidates c on c.id = m.candidate_id "
                    "where m.job_id = :jid and m.stage in ('verified','cv_sent') "
                    "and c.created_at < :t0"
                ),
                params,
            )
        ).scalars()
    )
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
    context = build_request_context(job, PROBE)
    vector = await request_vector(context.query_text)
    if vector is None:
        return None
    order = await asyncio.to_thread(_exact_order, client, vector, ids)
    head_ids = order[:HEAD]
    candidates = list(
        (await db.execute(select(Candidate).where(Candidate.id.in_(head_ids))))
        .scalars()
        .all()
    )
    renormalize = _renormalizing()
    # Ocena z dnia otwarcia: bez zweryfikowanych wymagań i bez notatek
    # powstałych w trakcie tej rekrutacji (screening = etykieta).
    fits = await score_candidates(
        db, context, candidates, reviewed_evidence=False, evidence_before=t0
    )
    head = {
        int(f.breakdown.candidate_id): components_of(
            f.breakdown, renormalize=renormalize
        )
        for f in fits
        if f.fit_score is not None
    }
    people = {}
    if with_people:
        people = {
            c.id: {
                "name": f"{c.name or ''} {c.lastname or ''}".strip(),
                "city": c.city or c.location,
            }
            for c in candidates
        }
    return Case(
        job_id=job_id,
        title=row.title,
        location=row.location,
        order=order,
        positives=positives,
        head=head,
        renormalize=renormalize,
        people=people,
    )


# ── Miary ────────────────────────────────────────────────────────────────────


def _ranks(case: Case, weights: dict) -> list[int]:
    return [
        i + 1 for i, cid in enumerate(case.ranked(weights)) if cid in case.positives
    ]


def metrics(cases: list[Case], weights: dict, threshold: float) -> dict:
    per_job = [_ranks(case, weights) for case in cases]
    ranks = [r for rs in per_job for r in rs]
    firsts = [min(rs) for rs in per_job if rs]
    return {
        "page1_hit": round(
            100.0
            * sum(1 for rs in per_job if any(r <= PAGE for r in rs))
            / max(len(per_job), 1),
            1,
        ),
        "median_first": statistics.median(firsts) if firsts else None,
        "top50_share": round(
            100.0 * sum(1 for r in ranks if r <= PAGE) / max(len(ranks), 1), 1
        ),
        "mrr": round(
            statistics.mean([max((1 / r for r in rs), default=0) for rs in per_job])
            if per_job
            else 0.0,
            3,
        ),
        "proposals": sum(case.proposals(weights, threshold) for case in cases),
    }


# Miary w punktach procentowych, które blokują publikację bez powodu.
GUARDED = ("page1_hit", "top50_share")
MAX_DROP_PT = 2.0


def compare(
    cases: list[Case],
    before_w: dict,
    before_threshold: float,
    after_w: dict,
    after_threshold: float,
) -> dict:
    """Te same rekrutacje i składniki, dwa zestawy wag (opublikowane i szkic)."""
    before = metrics(cases, before_w, before_threshold)
    after = metrics(cases, after_w, after_threshold)
    drops = {
        key: round(before[key] - after[key], 1)
        for key in GUARDED
        if before[key] - after[key] > 0
    }
    changes = []
    for case in cases:
        first_before = min(_ranks(case, before_w), default=None)
        first_after = min(_ranks(case, after_w), default=None)
        if first_before is None or first_after is None:
            continue
        changes.append(
            {
                "job_id": case.job_id,
                "title": case.title,
                "before": first_before,
                "after": first_after,
            }
        )
    changes.sort(key=lambda c: (-abs(c["before"] - c["after"]), c["job_id"]))
    return {
        "jobs": len(cases),
        "before": before,
        "after": after,
        "max_drop_pt": max(drops.values(), default=0.0),
        "needs_reason": any(v > MAX_DROP_PT for v in drops.values()),
        "biggest_changes": changes[:3],
    }


Progress = Callable[[int, int], Awaitable[None]]


async def collect_cases(
    *, target: int = MEASURE_JOBS, progress: Optional[Progress] = None
) -> list[Case]:
    """Rekrutacje do pomiaru, każda w osobnej sesji tylko do odczytu."""
    from app.core.database import AsyncSessionLocal
    from app.services import embedding_service as emb

    client = emb._get_qdrant_client()
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        rows = await eligible_jobs(db)
    cases: list[Case] = []
    for row in rows:
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(text("SET TRANSACTION READ ONLY"))
                await db.execute(text("SET LOCAL statement_timeout = '120s'"))
                case = await build_case(db, row, client)
        except Exception:  # noqa: BLE001 — jedna rekrutacja nie psuje pomiaru
            logger.warning("ranking_lab: job %s skipped", row.id, exc_info=True)
            case = None
        if case is not None:
            cases.append(case)
            if progress is not None:
                await progress(len(cases), target)
        if len(cases) >= target:
            break
    return cases


async def measure(
    before_w: dict,
    before_threshold: float,
    draft: PanelWeights,
    *,
    target: int = MEASURE_JOBS,
    progress: Optional[Progress] = None,
) -> dict:
    started = time.monotonic()
    cases = await collect_cases(target=target, progress=progress)
    result = compare(
        cases, before_w, before_threshold, engine_weights(draft), draft.threshold
    )
    result["duration_s"] = round(time.monotonic() - started)
    return result


# ── Podgląd na żywo ──────────────────────────────────────────────────────────

_PREVIEW_TTL = 15 * 60
_PREVIEW_MAX = 8
_preview_cache: "OrderedDict[tuple, tuple[float, dict]]" = OrderedDict()
_JOBS_TTL = 10 * 60
_jobs_cache: dict[str, tuple[float, list[dict]]] = {}


async def preview_jobs(db) -> list[dict]:
    cached = _jobs_cache.get("jobs")
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]
    rows = await eligible_jobs(db, limit=30)
    jobs = [
        {
            "job_id": row.id,
            "title": row.title,
            "location": row.location,
            "positives": int(row.positives or 0),
        }
        for row in rows
    ]
    _jobs_cache["jobs"] = (time.monotonic() + _JOBS_TTL, jobs)
    return jobs


async def preview(db, job_id: int) -> Optional[dict]:
    """Składniki 200 pierwszych osób zamkniętej rekrutacji — front przelicza
    kolejność sam, bez kolejnych zapytań."""
    from app.services import embedding_service as emb
    from app.services.scoring_service import scoring_algorithm_version

    key = (job_id, scoring_algorithm_version())
    cached = _preview_cache.get(key)
    if cached is not None and cached[0] > time.monotonic():
        _preview_cache.move_to_end(key)
        return cached[1]
    rows = await eligible_jobs(db, limit=1, job_id=job_id)
    if not rows:
        return None
    case = await build_case(db, rows[0], emb._get_qdrant_client(), with_people=True)
    if case is None:
        return None
    people = []
    for rank, cid in enumerate(case.order[:HEAD], start=1):
        components = case.head.get(cid)
        if components is None:
            continue
        person = case.people.get(cid, {})
        people.append(
            {
                **components.as_dict(),
                "vector_rank": rank,
                "name": person.get("name") or f"Kandydat {cid}",
                "city": person.get("city"),
                "positive": cid in case.positives,
            }
        )
    payload = {
        "job_id": case.job_id,
        "title": case.title,
        "location": case.location,
        "positives": len(case.positives),
        "renormalize": case.renormalize,
        "people": people,
    }
    _preview_cache[key] = (time.monotonic() + _PREVIEW_TTL, payload)
    while len(_preview_cache) > _PREVIEW_MAX:
        _preview_cache.popitem(last=False)
    return payload
