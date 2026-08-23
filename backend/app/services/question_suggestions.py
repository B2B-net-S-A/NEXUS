"""Question suggestion waterfall dla prep-kitów.

Reżyser dla feature'u "Prepy". Zwraca listę pytań dla konkretnego joba,
przechodząc przez hierarchię źródeł:

  1. Pinned — `JobQuestion WHERE job_id = self.id AND is_pinned = true`
  2. Legacy — `Job.champion_profile.screening_questions`
  3. Tier 1 — jobs z tym samym primary CC, cosine >= 0.70
  4. Tier 2 — jobs z overlapping secondary CC, cosine >= 0.55
  5. Tier 3 — `ClientKnowledge` kategorii `interview_questions` (per klient)
  6. Tier 4 — auto-generate z `job.must_skills` + `requirements`

Kluczowe zasady:

- **Tenant isolation**: pytania z `client_id != NULL` nigdy nie lądują w
  prep-kitach innych klientów. Filtr w `_questions_for_jobs`.
- **Graceful degradation**: brak Qdrant / brak embeddingu / brak CC = skip,
  leć dalej. Funkcja ZAWSZE zwraca ≥ 1 pytanie (auto-gen fallback).
- **Faza 1 — ratings są audit-only**: sortowanie w fallbackach jest
  deterministyczne (embedding score). Rating-aware scoring zostawiamy na
  fazę 2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cc_feedback import JobSecondaryCc
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.interview_question import (
    InterviewQuestion,
    JobQuestion,
)
from app.models.job import Job
from app.services.embedding_service import search_similar_jobs_by_job_id

logger = logging.getLogger(__name__)


DEFAULT_TARGET_QUESTIONS = 10
TIER_1_MIN_COSINE = 0.70
TIER_2_MIN_COSINE = 0.55
SIMILAR_JOBS_SEARCH_TOP_K = 20


@dataclass(frozen=True)
class SuggestedQuestion:
    """Zserializowany kawałek pytania zwrócony do prep-kita."""

    text: str
    source_tier: str  # "pinned" | "legacy_champion" | "tier_1_same_cc" |
    # "tier_2_secondary_cc" | "tier_3_client_knowledge" | "tier_4_auto_generated"
    question_id: Optional[int] = None
    source_job_id: Optional[int] = None
    ideal_answer: Optional[str] = None
    deal_breaker: bool = False
    seniority: Optional[str] = None
    question_type: Optional[str] = None
    skill_tags: Optional[list[str]] = None
    cosine_score: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "source_tier": self.source_tier,
            "question_id": self.question_id,
            "source_job_id": self.source_job_id,
            "ideal_answer": self.ideal_answer,
            "deal_breaker": self.deal_breaker,
            "seniority": self.seniority,
            "question_type": self.question_type,
            "skill_tags": self.skill_tags or [],
            "cosine_score": self.cosine_score,
        }


def _q_from_iq(
    iq: InterviewQuestion,
    source_tier: str,
    source_job_id: Optional[int] = None,
    cosine_score: Optional[float] = None,
) -> SuggestedQuestion:
    return SuggestedQuestion(
        text=iq.text,
        source_tier=source_tier,
        question_id=iq.id,
        source_job_id=source_job_id,
        ideal_answer=iq.ideal_answer,
        deal_breaker=iq.deal_breaker,
        seniority=iq.seniority.value if iq.seniority else None,
        question_type=iq.question_type.value if iq.question_type else None,
        skill_tags=list(iq.skill_tags or []),
        cosine_score=cosine_score,
    )


async def _tier_pinned(db: AsyncSession, job: Job) -> list[SuggestedQuestion]:
    """Pytania przypięte do joba, sortowane po `order_index`."""
    result = await db.execute(
        select(JobQuestion)
        .where(JobQuestion.job_id == job.id, JobQuestion.is_pinned.is_(True))
        .options(selectinload(JobQuestion.question))
        .order_by(JobQuestion.order_index.asc())
    )
    links = result.scalars().all()
    return [
        _q_from_iq(link.question, "pinned")
        for link in links
        if link.question is not None
    ]


def _tier_legacy_champion(job: Job) -> list[SuggestedQuestion]:
    """`champion_profile.screening_questions` — read-only (nie piszemy tu więcej)."""
    profile = job.champion_profile or {}
    if not isinstance(profile, dict):
        return []
    raw = profile.get("screening_questions") or []
    if not isinstance(raw, list):
        return []
    out: list[SuggestedQuestion] = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        text = (q.get("question") or "").strip()
        if not text:
            continue
        ideal = (q.get("ideal_answer") or "").strip() or None
        deal_raw = (q.get("deal_breaker") or "").strip()
        out.append(
            SuggestedQuestion(
                text=text,
                source_tier="legacy_champion",
                ideal_answer=ideal,
                deal_breaker=bool(deal_raw),
            )
        )
    return out


def _tenant_filter(
    other_job_client_id: Optional[int], self_client_id: Optional[int]
) -> bool:
    """Czy pytania innego joba mogą być pożyczone do prep-kita 'self'.

    Hard rule: pytania `client_id != NULL` → tylko dla tego samego klienta.
    Zwracamy True jeśli przejście jest dozwolone — filtracja per-pytanie
    robi się potem w _questions_for_jobs.
    """
    # Per-job poziom (czy w ogóle ruszać ten job): allow jeśli bez klienta
    # albo ten sam klient. Jobs innego klienta można ruszać tylko po
    # *globalne* pytania (filtrowane per-question).
    return True  # filtracja finalna per-question


async def _questions_for_jobs(
    db: AsyncSession,
    job_ids: list[int],
    self_client_id: Optional[int],
    score_by_job: dict[int, float],
    source_tier: str,
) -> list[SuggestedQuestion]:
    """Zciąg pytań przypiętych do *job_ids* + tenant-safe filter.

    Tenant isolation:
      - pytanie.client_id IS NULL → zawsze dozwolone
      - pytanie.client_id == self_client_id → dozwolone
      - inaczej → drop
    """
    if not job_ids:
        return []

    conds = [InterviewQuestion.client_id.is_(None)]
    if self_client_id is not None:
        conds.append(InterviewQuestion.client_id == self_client_id)

    result = await db.execute(
        select(JobQuestion, InterviewQuestion)
        .join(InterviewQuestion, JobQuestion.question_id == InterviewQuestion.id)
        .where(
            JobQuestion.job_id.in_(job_ids),
            JobQuestion.is_pinned.is_(True),
            or_(*conds),
        )
    )
    rows = result.all()

    # dedupe po question_id, zachowaj najwyższy cosine_score z jobów
    best: dict[int, tuple[InterviewQuestion, int, float]] = {}
    for link, iq in rows:
        score = score_by_job.get(link.job_id, 0.0)
        if iq.id not in best or best[iq.id][2] < score:
            best[iq.id] = (iq, link.job_id, score)

    # sortuj po cosine desc, potem po question_id asc (deterministic)
    sorted_items = sorted(best.values(), key=lambda x: (-x[2], x[0].id))
    return [
        _q_from_iq(iq, source_tier, source_job_id=source_job_id, cosine_score=score)
        for iq, source_job_id, score in sorted_items
    ]


async def _tier_same_cc_similar(
    db: AsyncSession,
    job: Job,
) -> tuple[list[SuggestedQuestion], bool]:
    """Tier 1: jobs z tym samym primary CC, cosine >= TIER_1_MIN_COSINE.

    Zwraca ``(pytania, degraded)``. ``degraded=True`` znaczy „nie wiem" —
    Qdrant nie odpowiedział, więc pusta lista NIE znaczy, że podobnych ofert
    nie ma. Bez tej flagi tier 4 dolewał pytania z auto-generatora i rekruter
    dostawał wiarygodny wynik, nie mając jak zauważyć, że dwa najlepsze źródła
    milczały (#408).
    """
    # Bramka WYŁĄCZNIE na CC: filtr niżej to `Job.competence_category_id ==
    # job.competence_category_id`, co przy None degeneruje do IS NULL i
    # dopasowałoby oferty bez CC. Brak wektora rozstrzyga `search_similar_jobs_
    # by_job_id` (retrieve po PK oferty) — bramka na `embedding_id` była drugim,
    # słabszym predykatem przed lepszym. Patrz #403.
    if not job.competence_category_id:
        logger.debug("[prep-suggest] skip tier 1 (job %s): no CC", job.id)
        return [], False

    hits = await search_similar_jobs_by_job_id(
        job.id, top_k=SIMILAR_JOBS_SEARCH_TOP_K, exclude_self=True
    )
    # `is None` PRZED `not hits`: samo `if not hits` sklejałoby z powrotem
    # „nie wiem" z „wiem, że nie ma" — czyli defekt, który ta zmiana usuwa.
    if hits is None:
        logger.warning(
            "[prep-suggest] tier 1 (job %s): Qdrant nie odpowiedział — wynik "
            "jest NIEPEŁNY, nie pusty",
            job.id,
        )
        return [], True
    if not hits:
        return [], False

    candidate_ids = [h["job_id"] for h in hits]
    scores = {h["job_id"]: h["score"] for h in hits}

    # Filtr: ten sam primary CC + cosine >= 0.70
    result = await db.execute(
        select(Job.id).where(
            Job.id.in_(candidate_ids),
            Job.competence_category_id == job.competence_category_id,
        )
    )
    same_cc_ids = {row[0] for row in result.all()}
    filtered_ids = [
        jid
        for jid in candidate_ids
        if jid in same_cc_ids and scores.get(jid, 0.0) >= TIER_1_MIN_COSINE
    ]
    filtered_scores = {jid: scores[jid] for jid in filtered_ids}

    return (
        await _questions_for_jobs(
            db, filtered_ids, job.client_id, filtered_scores, "tier_1_same_cc"
        ),
        False,
    )


async def _tier_secondary_cc(
    db: AsyncSession,
    job: Job,
) -> tuple[list[SuggestedQuestion], bool]:
    """Tier 2: jobs overlapping po secondary CC, cosine >= TIER_2_MIN_COSINE.

    Zwraca ``(pytania, degraded)`` — patrz ``_tier_same_cc_similar``.
    """
    # Bez bramki na `embedding_id` — patrz komentarz w `_tier_same_cc_similar`.
    # Zbierz secondary CCs siebie
    self_secondary = await db.execute(
        select(JobSecondaryCc.competence_category_id).where(
            JobSecondaryCc.job_id == job.id
        )
    )
    self_secondary_ids = [row[0] for row in self_secondary.all()]

    # Jeśli self nie ma ani primary ani secondary CC, nic tu nie zrobimy
    cc_pool = set(self_secondary_ids)
    if job.competence_category_id:
        cc_pool.add(job.competence_category_id)
    if not cc_pool:
        return [], False

    hits = await search_similar_jobs_by_job_id(
        job.id, top_k=SIMILAR_JOBS_SEARCH_TOP_K, exclude_self=True
    )
    if hits is None:
        logger.warning(
            "[prep-suggest] tier 2 (job %s): Qdrant nie odpowiedział — wynik "
            "jest NIEPEŁNY, nie pusty",
            job.id,
        )
        return [], True
    if not hits:
        return [], False

    candidate_ids = [h["job_id"] for h in hits]
    scores = {h["job_id"]: h["score"] for h in hits}

    # Kandydaci: jobs gdzie
    #   (a) other.primary ∈ self_secondary_ids  OR
    #   (b) EXISTS JobSecondaryCc(other_job_id) WHERE cc ∈ cc_pool
    subq_secondary = select(JobSecondaryCc.job_id).where(
        JobSecondaryCc.competence_category_id.in_(list(cc_pool))
    )
    result = await db.execute(
        select(Job.id).where(
            Job.id.in_(candidate_ids),
            or_(
                Job.competence_category_id.in_(list(cc_pool)) if cc_pool else False,
                Job.id.in_(subq_secondary),
            ),
        )
    )
    allowed_ids = {row[0] for row in result.all()}
    filtered_ids = [
        jid
        for jid in candidate_ids
        if jid in allowed_ids and scores.get(jid, 0.0) >= TIER_2_MIN_COSINE
    ]
    filtered_scores = {jid: scores[jid] for jid in filtered_ids}

    return (
        await _questions_for_jobs(
            db, filtered_ids, job.client_id, filtered_scores, "tier_2_secondary_cc"
        ),
        False,
    )


def _parse_bullet_list(content: str) -> list[str]:
    """Parse ClientKnowledge content jako listę pytań (bullet points)."""
    items: list[str] = []
    for line in (content or "").splitlines():
        line = line.strip()
        if not line:
            continue
        line = line.lstrip("•-–*·").strip()
        if line:
            items.append(line)
    if items:
        return items
    text = (content or "").strip()
    return [text] if text else []


async def _tier_client_knowledge(db: AsyncSession, job: Job) -> list[SuggestedQuestion]:
    """Tier 3: legacy `ClientKnowledge` kategorii `interview_questions`."""
    if not job.client_id:
        return []
    result = await db.execute(
        select(ClientKnowledge).where(
            ClientKnowledge.client_id == job.client_id,
            ClientKnowledge.category == KnowledgeCategory.interview_questions,
        )
    )
    entries = result.scalars().all()
    out: list[SuggestedQuestion] = []
    for e in entries:
        for text in _parse_bullet_list(e.content):
            out.append(
                SuggestedQuestion(text=text, source_tier="tier_3_client_knowledge")
            )
    return out


def _tier_auto_generate(job: Job) -> list[SuggestedQuestion]:
    """Tier 4: wygeneruj pytania z must_skills/requirements (ostatnia deska)."""
    out: list[SuggestedQuestion] = []

    # Must-have skills
    for item in job.must_skills or []:
        if isinstance(item, dict):
            name = (item.get("name") or "").strip()
        elif isinstance(item, str):
            name = item.strip()
        else:
            name = ""
        if name:
            out.append(
                SuggestedQuestion(
                    text=f"Jakie masz doświadczenie z {name}?",
                    source_tier="tier_4_auto_generated",
                    question_type="technical",
                    skill_tags=[name.lower()],
                )
            )

    # Requirements bullet points
    if job.requirements:
        for line in job.requirements.splitlines():
            line = line.strip().lstrip("•-–*").strip()
            if len(line) > 10:
                out.append(
                    SuggestedQuestion(
                        text=f"Opisz swoje doświadczenie z: {line}",
                        source_tier="tier_4_auto_generated",
                        question_type="experience",
                    )
                )

    if not out:
        out = [
            SuggestedQuestion(
                text="Opisz swoje ostatnie doświadczenie projektowe.",
                source_tier="tier_4_auto_generated",
                question_type="experience",
            ),
            SuggestedQuestion(
                text="Jakie są Twoje oczekiwania względem nowego miejsca pracy?",
                source_tier="tier_4_auto_generated",
                question_type="motivation",
            ),
            SuggestedQuestion(
                text="Jak radzisz sobie z pracą w zespole?",
                source_tier="tier_4_auto_generated",
                question_type="behavioral",
            ),
        ]

    return out


def _normalize_dedup_key(text: str) -> str:
    """Dedup key — lowercase + collapse whitespace."""
    import re

    return re.sub(r"\s+", " ", text.strip().lower())


@dataclass
class PrepSuggestions:
    """Pytania + informacja, czy wynik jest KOMPLETNY.

    Kształt wzorowany na ``RadarResult`` z Talent Radaru, gdzie ta sama zasada
    jest już utrwalona: wynik zdegradowany NIE MOŻE renderować się jak
    normalny. Tutaj jest gorzej niż przy pustej liście — tier 4 (auto-gen)
    uruchamia się jako bezpiecznik, więc rekruter dostaje pytania WYGLĄDAJĄCE
    normalnie i nie ma jak zauważyć, że dwa najlepsze źródła milczały (#408).
    """

    questions: list[SuggestedQuestion]
    degraded: bool = False
    reason: Optional[str] = None

    def as_meta(self) -> dict:
        return {
            "returned": len(self.questions),
            "degraded": self.degraded,
            "reason": self.reason,
        }


async def suggest_questions_for_prep(
    db: AsyncSession,
    job: Job,
    target_count: int = DEFAULT_TARGET_QUESTIONS,
) -> PrepSuggestions:
    """Główne wejście: pytania dla prep-kita joba + flaga kompletności.

    Waterfall: dolewamy źródła aż osiągniemy `target_count` unikalnych pytań.
    Dedupe po `_normalize_dedup_key(text)`. Tier 4 (auto-gen) uruchamia się
    zawsze jako *bezpiecznik* — prep-kit musi mieć ≥ 1 pytanie.

    Ten bezpiecznik jest właśnie powodem, dla którego flaga ``degraded`` musi
    dojechać do wołającego: bez niej awaria Qdranta wygląda dokładnie jak
    oferta, dla której po prostu nie ma podobnych.
    """
    buckets: list[list[SuggestedQuestion]] = []

    # Always-on
    buckets.append(await _tier_pinned(db, job))
    buckets.append(_tier_legacy_champion(job))

    # Dolewamy fallbacki tylko jeśli brak
    current_unique: set[str] = set()
    for bucket in buckets:
        for q in bucket:
            current_unique.add(_normalize_dedup_key(q.text))

    degraded = False

    if len(current_unique) < target_count:
        tier1, tier1_degraded = await _tier_same_cc_similar(db, job)
        degraded = degraded or tier1_degraded
        buckets.append(tier1)
        for q in tier1:
            current_unique.add(_normalize_dedup_key(q.text))

    if len(current_unique) < target_count:
        tier2, tier2_degraded = await _tier_secondary_cc(db, job)
        degraded = degraded or tier2_degraded
        buckets.append(tier2)
        for q in tier2:
            current_unique.add(_normalize_dedup_key(q.text))

    if len(current_unique) < target_count:
        tier3 = await _tier_client_knowledge(db, job)
        buckets.append(tier3)
        for q in tier3:
            current_unique.add(_normalize_dedup_key(q.text))

    if len(current_unique) < target_count:
        buckets.append(_tier_auto_generate(job))

    # Final merge + dedup (zachowuje priority order wg bucket)
    seen: set[str] = set()
    merged: list[SuggestedQuestion] = []
    for bucket in buckets:
        for q in bucket:
            key = _normalize_dedup_key(q.text)
            if key in seen:
                continue
            seen.add(key)
            merged.append(q)

    if degraded:
        # WARNING, nie DEBUG: to jest jedyny ślad po tym, że rekruter patrzy na
        # niepełny wynik. Sam log nie wystarcza (nikt go nie czyta bez alertu),
        # dlatego flaga jedzie też w odpowiedzi API.
        logger.warning(
            "[prep-suggest] job %s: wynik NIEPEŁNY — Qdrant nie odpowiedział, "
            "a tier 4 dolał pytania z auto-generatora",
            job.id,
        )

    return PrepSuggestions(
        questions=merged,
        degraded=degraded,
        reason=(
            "Wyszukiwanie podobnych rekrutacji nie odpowiedziało — lista może "
            "być niepełna."
            if degraded
            else None
        ),
    )
