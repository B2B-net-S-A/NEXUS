"""
Embedding Service — Voyage AI + Qdrant
Semantic search for Nexus ATS candidates.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings

logger = logging.getLogger(__name__)

VECTOR_SIZE = 1024
VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"

LEGACY_CANDIDATE_COLLECTION = "nexus_candidates"
LEGACY_JOBS_COLLECTION = "nexus_jobs"


def _voyage_model() -> str:
    """Read Voyage embedding model from settings (default voyage-3-large)."""
    return getattr(settings, "VOYAGE_MODEL", None) or "voyage-3-large"


def _safe_collection_name(entity: str) -> str:
    """Build a physical collection name bound to the active vector space."""
    model_slug = re.sub(r"[^a-z0-9]+", "_", _voyage_model().lower()).strip("_")
    return f"nexus_{entity}_{model_slug}_{VECTOR_SIZE}_clean_v1"


def _belongs_to_active_vector_space(name: str, entity: str) -> bool:
    """Accept schema versions only when provider/model/dimension still match."""
    active_prefix = _safe_collection_name(entity).removesuffix("clean_v1")
    return name.startswith(active_prefix)


def _collection() -> str:
    """Return the populated candidate index; reject mismatched versioned names."""
    from app.services.qdrant_factory import CANDIDATES_ALIAS

    name = getattr(settings, "QDRANT_COLLECTION", None) or LEGACY_CANDIDATE_COLLECTION
    if name not in (
        LEGACY_CANDIDATE_COLLECTION,
        CANDIDATES_ALIAS,
    ) and not _belongs_to_active_vector_space(name, "candidates"):
        raise RuntimeError("candidate Qdrant collection does not match active model")
    return name


def _jobs_collection() -> str:
    """Return the populated job index; reject mismatched versioned names."""
    from app.services.qdrant_factory import JOBS_ALIAS

    name = getattr(settings, "QDRANT_JOBS_COLLECTION", None) or LEGACY_JOBS_COLLECTION
    if name not in (LEGACY_JOBS_COLLECTION, JOBS_ALIAS) and not (
        _belongs_to_active_vector_space(name, "jobs")
    ):
        raise RuntimeError("job Qdrant collection does not match active model")
    return name


def candidate_collection_name() -> str:
    """Public resolver used by every candidate-vector consumer."""
    return _collection()


def job_collection_name() -> str:
    """Public resolver used by every job-vector consumer."""
    return _jobs_collection()


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _get_qdrant_client():
    """Return a synchronous Qdrant client (used in background tasks)."""
    try:
        from app.services.qdrant_factory import get_qdrant_client

        return get_qdrant_client()
    except Exception as e:
        logger.error("[Qdrant] client creation failed error_type=%s", type(e).__name__)
        return None


def init_qdrant_collection() -> None:
    """
    Create the configured, versioned Voyage-only Qdrant collections if missing.

    Called at application startup (synchronous, runs in thread via asyncio.to_thread).
    """
    try:
        from qdrant_client.models import Distance, VectorParams
        from app.services.qdrant_factory import get_qdrant_client

        client = get_qdrant_client()
        existing = {c.name for c in client.get_collections().collections}
        aliases = {
            item.alias_name: item.collection_name
            for item in client.get_aliases().aliases
        }

        for coll in (_collection(), _jobs_collection()):
            if coll in aliases:
                info = client.get_collection(aliases[coll])
                vectors = info.config.params.vectors
                if getattr(vectors, "size", None) != VECTOR_SIZE:
                    raise RuntimeError(f"Qdrant alias {coll} has wrong dimension")
                logger.info("[Qdrant] alias '%s' -> '%s' ready.", coll, aliases[coll])
                continue
            if coll not in existing:
                client.create_collection(
                    collection_name=coll,
                    vectors_config=VectorParams(
                        size=VECTOR_SIZE, distance=Distance.COSINE
                    ),
                )
                logger.info(
                    f"[Qdrant] Collection '{coll}' created (dim={VECTOR_SIZE}, cosine)."
                )
            else:
                logger.info(f"[Qdrant] Collection '{coll}' already exists.")
    except Exception as e:
        logger.warning(
            "[Qdrant] collection init failed error_type=%s; "
            "semantic search will be unavailable",
            type(e).__name__,
        )


# ---------------------------------------------------------------------------
# Voyage AI — embedding generation
# ---------------------------------------------------------------------------


OLLAMA_EMBED_MODEL = "mxbai-embed-large"


ACTIVE_TEXT_SCHEMA = "clean_v1"


def _active_text_schema() -> str:
    return getattr(settings, "EMBEDDING_TEXT_SCHEMA", None) or ACTIVE_TEXT_SCHEMA


async def _voyage_embed(
    text: str,
    *,
    input_type: str = "document",
    model: Optional[str] = None,
    dimension: int = VECTOR_SIZE,
) -> Optional[list[float]]:
    """Generate embedding via Voyage AI (model from EMBEDDING_MODEL env, default voyage-3-large)."""
    out = await _voyage_embed_batch(
        [text], input_type=input_type, model=model, dimension=dimension
    )
    if not out:
        return None
    return out[0]


async def _voyage_embed_batch(
    texts: list[str],
    *,
    input_type: str = "document",
    model: Optional[str] = None,
    dimension: int = VECTOR_SIZE,
) -> Optional[list[Optional[list[float]]]]:
    """Batch-embed up to 128 texts in one Voyage call.

    Returns a list aligned with input order; entries are None if the slot was
    blank. Returns None if the API call failed entirely.
    """
    if not settings.VOYAGE_API_KEY:
        return None
    if not texts:
        return []
    # Voyage accepts blank strings poorly; replace blanks with single space.
    payload_texts = [t if (t and t.strip()) else " " for t in texts]
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                VOYAGE_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.VOYAGE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model or _voyage_model(),
                    "input": payload_texts,
                    "input_type": input_type,
                    "output_dimension": dimension,
                    "truncation": True,
                },
            )
            response.raise_for_status()
            data = response.json().get("data") or []
            # Voyage returns items with `index` field; reorder to input order.
            by_idx = {
                int(item["index"]): item["embedding"]
                for item in data
                if "embedding" in item
            }
            return [by_idx.get(i) for i in range(len(texts))]
    except httpx.HTTPStatusError as e:
        logger.warning(
            "[Voyage] HTTP status=%s response_bytes=%s",
            e.response.status_code,
            len(e.response.content),
        )
        return None
    except Exception as e:
        logger.warning("[Voyage] request failed error_type=%s", type(e).__name__)
        return None


async def _ollama_embed(text: str) -> Optional[list[float]]:
    """
    Generate a local development embedding with Ollama.

    This vector is *not* compatible with Voyage merely because both have 1024
    dimensions.  It may only be requested explicitly in DEBUG mode and must
    never be written to the Voyage cache.
    """
    host = getattr(settings, "OLLAMA_BASE_URL", None) or getattr(
        settings, "OLLAMA_HOST", None
    )
    if not host:
        return None
    model = getattr(settings, "OLLAMA_EMBED_MODEL", OLLAMA_EMBED_MODEL)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{host.rstrip('/')}/api/embeddings",
                json={"model": model, "prompt": text},
            )
            response.raise_for_status()
            emb = response.json().get("embedding")
            if not isinstance(emb, list) or len(emb) != VECTOR_SIZE:
                logger.warning(
                    "[Ollama] unexpected embedding shape: dim=%s (expected %s)",
                    (len(emb) if isinstance(emb, list) else None),
                    VECTOR_SIZE,
                )
                return None
            return emb
    except Exception as e:
        logger.warning("[Ollama embed] request failed error_type=%s", type(e).__name__)
        return None


async def generate_embedding(
    text: str,
    *,
    input_type: str = "document",
    use_cache: bool = True,
    allow_local_fallback: bool = False,
    text_schema: Optional[str] = None,
) -> Optional[list[float]]:
    """
    Generate a 1024-dim Voyage embedding for *text*.

    Production calls fail closed when Voyage is unavailable.  A local Ollama
    fallback is available only when the caller explicitly opts in *and* the
    application runs with ``DEBUG=true``.  Local vectors are never cached under
    a Voyage key.  Equal dimensions do not imply compatible vector spaces.

    `input_type` should be "document" when indexing entities (candidates, jobs)
    and "query" when embedding a search query — Voyage 3-large applies different
    instruction prompts for each, improving retrieval quality.

    Cache: "document" embeddings hit a Postgres SHA-256 cache (Item 4) so
    duplicate uploads skip Voyage. Queries skip the cache (unique per call).
    Set `use_cache=False` for batch reembed paths that intentionally rewrite.
    """
    if not text or not text.strip():
        return None
    resolved_text_schema = text_schema or _active_text_schema()

    # Document cache lookup (queries are usually unique — skip).
    cache_eligible = use_cache and input_type == "document"
    if cache_eligible:
        try:
            from app.services.embedding_cache import get as _cache_get

            cached = await _cache_get(
                text,
                provider="voyage",
                model=_voyage_model(),
                input_type=input_type,
                dimension=VECTOR_SIZE,
                text_schema=resolved_text_schema,
            )
            if cached is not None:
                return cached
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[embedding] cache lookup failed error_type=%s", type(e).__name__
            )

    emb = await _voyage_embed(text, input_type=input_type)
    is_voyage_embedding = emb is not None
    if emb is None and allow_local_fallback and settings.DEBUG:
        emb = await _ollama_embed(text)
        if emb is not None:
            logger.warning(
                "[embedding] using explicit DEBUG-only Ollama embedding; "
                "do not mix this vector with Voyage collections"
            )

    if emb is None:
        logger.warning("[embedding] Voyage embedding unavailable")
        return None

    # Best-effort cache write.  The explicit DEBUG-only local path is never
    # cached because it belongs to a different vector space.
    if cache_eligible and is_voyage_embedding:
        try:
            from app.services.embedding_cache import store as _cache_store

            await _cache_store(
                text,
                emb,
                provider="voyage",
                model=_voyage_model(),
                input_type=input_type,
                text_schema=resolved_text_schema,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[embedding] cache store failed error_type=%s", type(e).__name__
            )

    return emb


# ---------------------------------------------------------------------------
# Candidate embedding — store in Qdrant
# ---------------------------------------------------------------------------


def _build_candidate_text_v1(candidate) -> str:
    """Build a rich text blob from candidate fields for embedding."""
    parts: list[str] = []

    if candidate.name:
        parts.append(candidate.name)
    if candidate.lastname:
        parts.append(candidate.lastname)
    if candidate.competence_category:
        parts.append(candidate.competence_category)

    # Seniority hint from structured years_it_experience
    years = getattr(candidate, "years_it_experience", None)
    if years is not None:
        if years >= 7:
            parts.append("senior experienced engineer")
        elif years >= 3:
            parts.append("mid-level developer")
        else:
            parts.append("junior entry-level developer")

    # Skills
    if candidate.skills:
        skills = candidate.skills
        if isinstance(skills, list):
            for s in skills:
                if isinstance(s, dict):
                    parts.append(s.get("name", ""))
                elif isinstance(s, str):
                    parts.append(s)
        elif isinstance(skills, str):
            parts.append(skills)

    # Verified tech (Phase 1 — structured list of confirmed technologies)
    verified_tech = getattr(candidate, "verified_tech", None)
    if verified_tech:
        if isinstance(verified_tech, list):
            for t in verified_tech:
                if isinstance(t, dict):
                    parts.append(t.get("name", ""))
                elif isinstance(t, str):
                    parts.append(t)

    # Experience
    if candidate.experience:
        exp = candidate.experience
        if isinstance(exp, list):
            for e in exp:
                if isinstance(e, dict):
                    parts.append(e.get("role", ""))
                    parts.append(e.get("company", ""))
                    parts.append(e.get("desc", ""))
        elif isinstance(exp, str):
            parts.append(exp)

    # Tags
    if candidate.tags:
        tags = candidate.tags
        if isinstance(tags, list):
            parts.extend([str(t) for t in tags])
        elif isinstance(tags, str):
            parts.append(tags)

    # Preferences — industries help matching engine
    prefs = getattr(candidate, "preferences", None)
    if prefs and isinstance(prefs, dict):
        industries = prefs.get("industries") or []
        if isinstance(industries, list):
            parts.extend([str(i) for i in industries if i])

    # AI summary
    if candidate.ai_summary:
        parts.append(candidate.ai_summary)

    # Raw CV (truncated to avoid token blowup)
    if candidate.raw_cv_text:
        parts.append(candidate.raw_cv_text[:3000])

    return " ".join(p for p in parts if p and p.strip())


_EMBED_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_EMBED_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]*){8,14}(?!\d)")
_EMBED_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)


def _clean_embedding_fragment(value: object, *, forbidden: tuple[str, ...] = ()) -> str:
    """Remove direct identifiers from a structured embedding fragment."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = _EMBED_EMAIL_RE.sub(" ", text)
    text = _EMBED_PHONE_RE.sub(" ", text)
    text = _EMBED_URL_RE.sub(" ", text)
    for token in forbidden:
        if token and len(token.strip()) >= 2:
            text = re.sub(re.escape(token.strip()), " ", text, flags=re.I)
    return " ".join(text.split())[:1200]


def _skill_fragments(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    values: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = _clean_embedding_fragment(item.get("name"))
            level = _clean_embedding_fragment(item.get("level"))
            if name:
                values.append(f"{name} {level}".strip())
        elif isinstance(item, str):
            clean = _clean_embedding_fragment(item)
            if clean:
                values.append(clean)
    return values


def _build_candidate_text_v2(candidate) -> str:
    """Privacy-minimised candidate text for Voyage 4 ``text_v2``.

    Names, contacts, locations, rates, availability and raw CV content are
    intentionally excluded. Location/rate/availability remain structured
    filters in the scoring pipeline.
    """
    parts: list[str] = []
    forbidden = tuple(
        value
        for value in (
            getattr(candidate, "name", None),
            getattr(candidate, "lastname", None),
            getattr(candidate, "location", None),
            getattr(candidate, "city", None),
        )
        if isinstance(value, str)
    )
    cc = _clean_embedding_fragment(getattr(candidate, "competence_category", None))
    if cc:
        parts.append(f"kategoria kompetencji: {cc}")

    years = getattr(candidate, "years_it_experience", None)
    if isinstance(years, (int, float)):
        seniority = "senior" if years >= 7 else "mid" if years >= 3 else "junior"
        parts.append(f"seniority: {seniority}; doświadczenie IT: {years:g} lat")

    skills = [
        *_skill_fragments(getattr(candidate, "skills", None)),
        *_skill_fragments(getattr(candidate, "verified_tech", None)),
    ]
    if skills:
        parts.append("umiejętności i technologie: " + ", ".join(dict.fromkeys(skills)))

    current_role = _clean_embedding_fragment(
        getattr(candidate, "linkedin_current_title", None), forbidden=forbidden
    )
    if current_role:
        parts.append(f"aktualna rola: {current_role}")

    experience = getattr(candidate, "experience", None)
    if isinstance(experience, list):
        for item in experience[:20]:
            if not isinstance(item, dict):
                continue
            role = _clean_embedding_fragment(item.get("role"), forbidden=forbidden)
            responsibility = _clean_embedding_fragment(
                item.get("desc") or item.get("description"), forbidden=forbidden
            )
            if role:
                parts.append(f"rola: {role}")
            if responsibility:
                parts.append(f"obowiązki: {responsibility}")

    preferences = getattr(candidate, "preferences", None)
    if isinstance(preferences, dict):
        industries = preferences.get("industries")
        if isinstance(industries, list):
            clean = [_clean_embedding_fragment(item) for item in industries]
            clean = [item for item in clean if item]
            if clean:
                parts.append("branże: " + ", ".join(clean))

    languages = getattr(candidate, "languages", None)
    if isinstance(languages, list):
        clean_languages: list[str] = []
        for item in languages:
            if isinstance(item, dict):
                lang = _clean_embedding_fragment(item.get("lang") or item.get("name"))
                level = _clean_embedding_fragment(item.get("level"))
                if lang:
                    clean_languages.append(f"{lang} {level}".strip())
            elif isinstance(item, str):
                clean_languages.append(_clean_embedding_fragment(item))
        clean_languages = [item for item in clean_languages if item]
        if clean_languages:
            parts.append("języki: " + ", ".join(clean_languages))

    return "\n".join(parts)


def _build_candidate_text(candidate) -> str:
    """Build candidate text using the runtime-selected, versioned schema."""
    if _active_text_schema() == "text_v2":
        return _build_candidate_text_v2(candidate)
    return _build_candidate_text_v1(candidate)


async def embed_candidate(candidate_id: int, db: AsyncSession) -> bool:
    """
    Generate an embedding for a candidate and upsert it into Qdrant.
    Returns True on success, False on failure.
    """
    from app.models.candidate import Candidate

    try:
        result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
        candidate = result.scalar_one_or_none()
        if not candidate:
            logger.warning(f"[Embed] Candidate {candidate_id} not found.")
            return False

        text = _build_candidate_text(candidate)
        if not text.strip():
            logger.warning(f"[Embed] Candidate {candidate_id} has no text to embed.")
            return False

        embedding = await generate_embedding(text, input_type="document")
        if embedding is None:
            return False

        # Upsert into Qdrant
        def _upsert():
            from app.services.qdrant_factory import get_qdrant_client
            from qdrant_client.models import PointStruct

            client = get_qdrant_client()
            client.upsert(
                collection_name=_collection(),
                points=[
                    PointStruct(
                        id=candidate_id,
                        vector=embedding,
                        payload={
                            "candidate_id": candidate_id,
                            "name": f"{candidate.name} {candidate.lastname}",
                            "competence_category": candidate.competence_category or "",
                        },
                    )
                ],
            )

        await asyncio.to_thread(_upsert)

        # Update embedding_id on the candidate record
        candidate.embedding_id = str(candidate_id)
        await db.commit()

        logger.info(f"[Embed] Candidate {candidate_id} embedded and stored in Qdrant.")
        return True

    except Exception as e:
        logger.error(
            "[Embed] Candidate %s failed error_type=%s",
            candidate_id,
            type(e).__name__,
        )
        return False


async def delete_candidate_embedding(candidate_id: int) -> bool:
    """Best-effort removal of a candidate's vector from Qdrant.

    The point id is the integer candidate_id (see ``embed_candidate``). Failures
    are logged and swallowed — a hard candidate delete must not be blocked by an
    unreachable Qdrant.
    """

    def _delete():
        from app.services.qdrant_factory import get_qdrant_client

        client = get_qdrant_client()
        client.delete(collection_name=_collection(), points_selector=[candidate_id])

    try:
        await asyncio.to_thread(_delete)
        logger.info(f"[Embed] Deleted candidate {candidate_id} vector from Qdrant.")
        return True
    except Exception as e:  # pragma: no cover - network/Qdrant failure path
        logger.warning(
            "[Embed] Candidate %s vector delete failed error_type=%s",
            candidate_id,
            type(e).__name__,
        )
        return False


async def delete_job_embedding(job_id: int) -> bool:
    """Best-effort removal of a job vector from the active job collection."""

    def _delete():
        from app.services.qdrant_factory import get_qdrant_client

        client = get_qdrant_client()
        client.delete(collection_name=_jobs_collection(), points_selector=[job_id])

    try:
        await asyncio.to_thread(_delete)
        logger.info("[Embed] Deleted job %s vector from Qdrant.", job_id)
        return True
    except Exception as e:  # pragma: no cover - network/Qdrant failure path
        logger.warning(
            "[Embed] Job %s vector delete failed error_type=%s",
            job_id,
            type(e).__name__,
        )
        return False


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------


async def search_candidates_semantic(
    query: str,
    top_k: int = 20,
) -> list[dict]:
    """
    Embed *query* and search the Qdrant collection for the closest candidates.
    Returns a list of dicts: [{candidate_id, score}].

    Each call (including its embedding step) is recorded in the AI health
    tracker so ``meta.ai_status`` on candidate-search responses can flip the
    "manual search" banner when Voyage/Qdrant is degraded or down.
    """
    from app.services.ai_health import AiCallTimer

    with AiCallTimer() as timer:
        embedding = await generate_embedding(query, input_type="query")
        if embedding is None:
            timer.failed = True
            logger.warning(
                "[Search] Could not generate query embedding — returning empty results."
            )
            return []

        def _search():
            from app.services.qdrant_factory import get_qdrant_client

            client = get_qdrant_client()
            hits = client.search(
                collection_name=_collection(),
                query_vector=embedding,
                limit=top_k,
                with_payload=True,
            )
            return [
                {
                    "candidate_id": int(hit.id),
                    "score": round(float(hit.score), 4),
                    "payload": hit.payload or {},
                }
                for hit in hits
            ]

        try:
            return await asyncio.to_thread(_search)
        except Exception as e:
            timer.failed = True
            logger.error(
                "[Search] Qdrant candidate search failed error_type=%s",
                type(e).__name__,
            )
            return []


async def similarity_for_candidate_ids(
    query: str,
    candidate_ids: list[int],
) -> dict[int, float]:
    """Cosine similarity of each *specific* candidate (by id) to ``query``.

    Unlike :func:`search_candidates_semantic` (top-K nearest globally), this
    returns a score for EVERY embedded candidate in ``candidate_ids`` regardless
    of global rank — used to score in-pipeline candidates that may sit outside
    the top-K pool. Candidates with no stored vector are simply absent from the
    result. Deliberately does NOT record into the AI-health window (it's a
    targeted lookup, not the user-facing semantic search).
    """
    ids = [int(c) for c in candidate_ids]
    if not ids:
        return {}

    embedding = await generate_embedding(query, input_type="query")
    if embedding is None:
        logger.warning(
            "[Search] similarity_for_candidate_ids: no query embedding — empty."
        )
        return {}

    def _search():
        from app.services.qdrant_factory import get_qdrant_client
        from qdrant_client.models import Filter, HasIdCondition

        client = get_qdrant_client()
        hits = client.search(
            collection_name=_collection(),
            query_vector=embedding,
            query_filter=Filter(must=[HasIdCondition(has_id=ids)]),
            limit=len(ids),
            with_payload=False,
        )
        return {int(hit.id): round(float(hit.score), 4) for hit in hits}

    try:
        return await asyncio.to_thread(_search)
    except Exception as e:
        logger.error(
            "[Search] candidate similarity failed error_type=%s",
            type(e).__name__,
        )
        return {}


# ---------------------------------------------------------------------------
# Phase 2: Job embedding (reverse matching)
# ---------------------------------------------------------------------------


def _build_job_text_v1(job) -> str:
    """Build a rich text blob from job fields for embedding.

    When `job.champion_profile` exists, its narrative content (project context,
    screening question ideal answers, sourcing keywords/target companies) is
    included — Champion Profile is a curated description of the perfect
    candidate, which dramatically improves recall on roles where the recruiter
    invested in defining it (Phase 15 / Traffit-style championship workflow).
    """
    parts: list[str] = []

    if job.title:
        parts.append(job.title)
    if job.description:
        parts.append(job.description[:1200])
    if job.requirements:
        parts.append(job.requirements[:1200])

    # Structured fields (Phase 1)
    if getattr(job, "seniority", None):
        parts.append(f"{job.seniority.value} level")
    if getattr(job, "subcategory", None):
        parts.append(job.subcategory)
    if getattr(job, "industry", None):
        parts.append(f"branża {job.industry}")
    # Phase 15: train/programme tag — strong same-client similarity signal
    # captured in the embedding so cross-client searches also benefit.
    train_name = getattr(job, "train_name", None)
    if train_name:
        parts.append(f"train {train_name}")

    # Champion Profile narrative (Item 9 — Champion-driven matching).
    # Stored as JSONB in jobs.champion_profile, follows ChampionProfile schema
    # (backend/app/schemas/champion.py).
    champion = getattr(job, "champion_profile", None)
    if isinstance(champion, dict) and champion:
        ctx = champion.get("project_context") or {}
        if isinstance(ctx, dict):
            for key in ("about", "responsibilities", "selling_points"):
                v = ctx.get(key)
                if isinstance(v, str) and v.strip():
                    parts.append(v[:1000])

        # Screening questions encode the recruiter's mental model of the
        # ideal candidate — ideal_answer is exactly what we want to match.
        questions = champion.get("screening_questions") or []
        if isinstance(questions, list):
            for q in questions[:10]:
                if not isinstance(q, dict):
                    continue
                ideal = q.get("ideal_answer")
                if isinstance(ideal, str) and ideal.strip():
                    parts.append(ideal[:400])
                qtext = q.get("question")
                if isinstance(qtext, str) and qtext.strip():
                    parts.append(qtext[:200])

        # Free-text recruiter notes — strongest semantic signal for niche roles
        for key in (
            "historical_client_questions",
            "internal_consultant_insight",
        ):
            v = champion.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v[:600])

        sourcing = champion.get("sourcing") or {}
        if isinstance(sourcing, dict):
            kw = sourcing.get("keywords")
            if isinstance(kw, str) and kw.strip():
                parts.append(kw[:500])
            tc = sourcing.get("target_companies")
            if isinstance(tc, str) and tc.strip():
                parts.append(tc[:500])
            notes = sourcing.get("notes")
            if isinstance(notes, str) and notes.strip():
                parts.append(notes[:500])

        basics = champion.get("basics") or {}
        if isinstance(basics, dict):
            lang = basics.get("language")
            if isinstance(lang, str) and lang.strip():
                parts.append(f"język: {lang}")
            loc = basics.get("candidate_location_pref")
            if isinstance(loc, str) and loc.strip():
                parts.append(f"lokalizacja: {loc}")

    # Must / nice skills names
    for bucket_name, bucket in (("must", job.must_skills), ("nice", job.nice_skills)):
        if bucket and isinstance(bucket, list):
            for item in bucket:
                if isinstance(item, dict) and item.get("name"):
                    parts.append(item["name"])
                elif isinstance(item, str):
                    parts.append(item)

    return " ".join(p for p in parts if p and p.strip())


def _build_job_text_v2(job) -> str:
    """Job text for Voyage 4; salary and location remain structured filters."""
    parts: list[str] = []
    forbidden = tuple(
        str(value)
        for value in (
            getattr(job, "location", None),
            getattr(job, "salary_min", None),
            getattr(job, "salary_max", None),
        )
        if value not in (None, "")
    )
    for label, value in (
        ("tytuł", getattr(job, "title", None)),
        ("kategoria", getattr(job, "subcategory", None)),
        ("domena", getattr(job, "industry", None)),
    ):
        clean = _clean_embedding_fragment(value, forbidden=forbidden)
        if clean:
            parts.append(f"{label}: {clean}")

    seniority = getattr(job, "seniority", None)
    if seniority:
        parts.append(
            f"seniority: {_clean_embedding_fragment(getattr(seniority, 'value', seniority))}"
        )
    work_mode = getattr(job, "work_mode", None)
    if work_mode:
        parts.append(
            f"tryb pracy: {_clean_embedding_fragment(getattr(work_mode, 'value', work_mode))}"
        )

    for label, bucket in (
        ("must have", getattr(job, "must_skills", None)),
        ("nice to have", getattr(job, "nice_skills", None)),
    ):
        values = _skill_fragments(bucket)
        if values:
            parts.append(f"{label}: " + ", ".join(values))

    for label, value in (
        ("obowiązki i kontekst", getattr(job, "description", None)),
        ("wymagania", getattr(job, "requirements", None)),
    ):
        clean = _clean_embedding_fragment(value, forbidden=forbidden)
        if clean:
            parts.append(f"{label}: {clean}")

    champion = getattr(job, "champion_profile", None)
    if isinstance(champion, dict):
        context = champion.get("project_context")
        if isinstance(context, dict):
            for key in ("about", "responsibilities", "selling_points"):
                clean = _clean_embedding_fragment(context.get(key), forbidden=forbidden)
                if clean:
                    parts.append(f"champion {key}: {clean}")
        basics = champion.get("basics")
        if isinstance(basics, dict):
            language = _clean_embedding_fragment(
                basics.get("language"), forbidden=forbidden
            )
            if language:
                parts.append(f"język: {language}")
        sourcing = champion.get("sourcing")
        if isinstance(sourcing, dict):
            keywords = _clean_embedding_fragment(
                sourcing.get("keywords"), forbidden=forbidden
            )
            if keywords:
                parts.append(f"zatwierdzone słowa kluczowe: {keywords}")

    return "\n".join(parts)


def _build_job_text(job) -> str:
    """Build job text using the runtime-selected, versioned schema."""
    if _active_text_schema() == "text_v2":
        return _build_job_text_v2(job)
    return _build_job_text_v1(job)


async def embed_job(job_id: int, db: AsyncSession) -> bool:
    """
    Generate a vector embedding for *job_id* and upsert it into the nexus_jobs
    collection. Sets jobs.embedding_id = str(job_id).
    Non-blocking: returns False on any failure, logs at WARNING.
    """
    from app.models.job import Job

    try:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            logger.warning(f"[Embed] Job {job_id} not found.")
            return False

        text = _build_job_text(job)
        if not text.strip():
            logger.warning(f"[Embed] Job {job_id} has no text to embed.")
            return False

        embedding = await generate_embedding(text, input_type="document")
        if embedding is None:
            return False

        def _upsert():
            from app.services.qdrant_factory import get_qdrant_client
            from qdrant_client.models import PointStruct

            client = get_qdrant_client()
            client.upsert(
                collection_name=_jobs_collection(),
                points=[
                    PointStruct(
                        id=job_id,
                        vector=embedding,
                        payload={
                            "job_id": job_id,
                            "title": job.title or "",
                            "client_id": job.client_id,
                            "industry": job.industry or "",
                        },
                    )
                ],
            )

        await asyncio.to_thread(_upsert)

        job.embedding_id = str(job_id)
        await db.commit()

        logger.info(f"[Embed] Job {job_id} embedded and stored in Qdrant.")
        return True

    except Exception as e:
        logger.error("[Embed] Job %s failed error_type=%s", job_id, type(e).__name__)
        return False


async def search_jobs_semantic(query: str, top_k: int = 20) -> list[dict]:
    """Embed *query* and return top-k closest job ids from the active index."""
    embedding = await generate_embedding(query, input_type="query")
    if embedding is None:
        return []

    def _search():
        from app.services.qdrant_factory import get_qdrant_client

        client = get_qdrant_client()
        hits = client.search(
            collection_name=_jobs_collection(),
            query_vector=embedding,
            limit=top_k,
            with_payload=True,
        )
        return [
            {
                "job_id": int(hit.id),
                "score": round(float(hit.score), 4),
                "payload": hit.payload or {},
            }
            for hit in hits
        ]

    try:
        return await asyncio.to_thread(_search)
    except Exception as e:
        logger.error(
            "[Search] Qdrant job search failed error_type=%s", type(e).__name__
        )
        return []


async def search_similar_jobs_by_job_id(
    job_id: int, top_k: int = 20, exclude_self: bool = True
) -> list[dict]:
    """Find jobs semantically similar to *job_id* using its stored vector.

    Flow:
      1. Retrieve the job vector from the active versioned collection.
      2. Run vector search limit=top_k+1 (to drop self).
      3. Optionally exclude *job_id* itself from results.

    Returns: `[{"job_id": int, "score": float, "payload": dict}]` sorted desc.
    Empty list on any failure (Qdrant offline, job not embedded, collection
    missing). Callers must handle empty gracefully.
    """

    def _run() -> list[dict]:
        from app.services.qdrant_factory import get_qdrant_client

        client = get_qdrant_client()

        try:
            points = client.retrieve(
                collection_name=_jobs_collection(),
                ids=[job_id],
                with_vectors=True,
            )
        except Exception as e:
            logger.debug(
                "[Search] Job %s vector retrieval failed error_type=%s",
                job_id,
                type(e).__name__,
            )
            return []

        if not points:
            logger.debug("[Search] job %s has no vector in nexus_jobs", job_id)
            return []

        vector = getattr(points[0], "vector", None)
        if isinstance(vector, dict):
            vector = next(iter(vector.values()), None)
        if not vector:
            return []

        limit = top_k + 1 if exclude_self else top_k
        try:
            hits = client.search(
                collection_name=_jobs_collection(),
                query_vector=list(vector),
                limit=limit,
                with_payload=True,
            )
        except Exception as e:
            logger.error(
                "[Search] Similar-job search for job %s failed error_type=%s",
                job_id,
                type(e).__name__,
            )
            return []

        results: list[dict] = []
        for hit in hits:
            hit_id = int(hit.id)
            if exclude_self and hit_id == job_id:
                continue
            results.append(
                {
                    "job_id": hit_id,
                    "score": round(float(hit.score), 4),
                    "payload": hit.payload or {},
                }
            )
            if len(results) >= top_k:
                break
        return results

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        logger.error(
            "[Search] Similar-job dispatch failed error_type=%s", type(e).__name__
        )
        return []
