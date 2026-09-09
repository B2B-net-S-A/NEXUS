"""
Embedding Service — Voyage AI + Qdrant
Semantic search for Nexus ATS candidates.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.config import settings
from app.services import champion_view

logger = logging.getLogger(__name__)

VECTOR_SIZE = 1024
VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"

# Ponowienia wywołania Voyage'a. Do 2026-08-21 nie było ŻADNEGO na żadnej
# ścieżce providera, a przy zakładaniu kandydata to nie jest chwilowa
# niedogodność: nieudany embedding zostawia rekord poprawny w Postgresie i
# TRWALE nieobecny w matchingu (kolumna `embedding_id` zostaje NULL, a nic jej
# potem nie ogląda). Jedno 429 w oknie kilkudziesięciu sekund kosztowało więc
# kandydata na zawsze. Ponawiamy tylko sygnały PRZEJŚCIOWE i tylko takie, które
# zawodzą szybko — patrz komentarz przy `ConnectError`.
_VOYAGE_RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_VOYAGE_RETRY_BACKOFF_SECONDS = 0.5

JOBS_COLLECTION = "nexus_jobs"

# ── Pamięć podręczna embeddingów ZAPYTAŃ (w procesie, krótkotrwała) ─────────
# Cache postgresowy (`embedding_cache`) obsługuje wyłącznie `input_type=
# "document"`, bo zapytanie rekrutera bywa unikalne i wiersz per literówka nie
# miałby sensu. Ale JEDEN request potrafi poprosić o TO SAMO zapytanie dwa razy:
# `retrieve_candidate_pool` w trybie hybrydowym embeduje je raz w nodze gęstej
# (`search_candidates_semantic`) i drugi raz w dosypce kosinusów
# (`similarity_for_candidate_ids`). To samo robi ścieżka wielo-zapytaniowa.
# Dopóki `HYBRID_POOL_ENABLED` było wyłączone, płaciliśmy za to tylko w teorii;
# po włączeniu to podwójny koszt i podwójna latencja na KAŻDEJ ofercie.
#
# Cache jest w procesie i celowo mały: te dwa wywołania dzieli ułamek sekundy,
# więc TTL liczony w minutach wystarcza z ogromnym zapasem, a proces
# restartowany przy każdym deployu i tak zaczyna od zera. Klucz niesie model
# i wymiar, bo embedding z innego modelu żyje w innej przestrzeni — pomyłka tu
# to ciche zatrucie kosinusów, dokładnie ta klasa co fallback na Ollamę.
_QUERY_EMBED_CACHE_MAX = 256
_QUERY_EMBED_CACHE_TTL_SECONDS = 300.0
_QUERY_EMBED_CACHE: "OrderedDict[str, tuple[float, list[float]]]" = OrderedDict()


def _query_cache_key(text: str, model: str, dim: int) -> str:
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"|query|")
    h.update(str(dim).encode("utf-8"))
    h.update(b"|")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def _query_cache_get(key: str) -> Optional[list[float]]:
    entry = _QUERY_EMBED_CACHE.get(key)
    if entry is None:
        return None
    expires_at, embedding = entry
    if expires_at <= time.monotonic():
        _QUERY_EMBED_CACHE.pop(key, None)
        return None
    _QUERY_EMBED_CACHE.move_to_end(key)
    return list(embedding)


def _query_cache_put(key: str, embedding: list[float]) -> None:
    _QUERY_EMBED_CACHE[key] = (
        time.monotonic() + _QUERY_EMBED_CACHE_TTL_SECONDS,
        list(embedding),
    )
    _QUERY_EMBED_CACHE.move_to_end(key)
    while len(_QUERY_EMBED_CACHE) > _QUERY_EMBED_CACHE_MAX:
        _QUERY_EMBED_CACHE.popitem(last=False)


def reset_query_embedding_cache() -> None:
    """Wyczyść cache zapytań — dla testów, żeby nie przeciekał między nimi."""
    _QUERY_EMBED_CACHE.clear()


class SemanticSearchUnavailable(RuntimeError):
    """The semantic retrieval provider (Voyage embed or Qdrant) FAILED.

    Distinct from an empty-but-healthy result: it signals an *outage* (query
    embedding could not be produced, or the Qdrant call raised), so callers can
    surface a degraded state instead of silently rendering "no candidates".

    Only raised when a caller opts in with ``raise_on_error=True``; the default
    contract of the semantic helpers stays "return ``[]`` on failure" so the
    other call sites (e.g. the ``/semantic`` ILIKE fallback) are unaffected.
    """


def _voyage_model() -> str:
    """Read Voyage embedding model from settings (default voyage-3-large)."""
    return getattr(settings, "VOYAGE_MODEL", None) or "voyage-3-large"


def _collection() -> str:
    """Return configured Qdrant collection name (default: nexus_candidates)."""
    name = getattr(settings, "QDRANT_COLLECTION", "nexus_candidates")
    return name or "nexus_candidates"


def _jobs_collection() -> str:
    """Separate Qdrant collection for job embeddings (Phase 2)."""
    return getattr(settings, "QDRANT_JOBS_COLLECTION", None) or JOBS_COLLECTION


# Publiczne aliasy — moduły spoza embeddingu (np. raport pokrycia indeksu)
# potrzebują NAZW kolekcji, nie wnętrzności tego serwisu. Bez nich każdy taki
# konsument importował `_collection` i wiązał się z prywatnym API.
def candidates_collection_name() -> str:
    return _collection()


def jobs_collection_name() -> str:
    return _jobs_collection()


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _get_qdrant_client():
    """Return a synchronous Qdrant client (used in background tasks)."""
    try:
        from qdrant_client import QdrantClient

        return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    except Exception as e:
        logger.error(f"[Qdrant] Failed to create client: {e}")
        return None


async def _run_qdrant(fn):
    """Run a blocking Qdrant call off-thread and report it to provider health.

    Qdrant previously reported only into the *global* matching window shared
    with Voyage, so ``/api/health`` could not say which of the two was down —
    and the indexing-side calls reported nothing at all. Routing the read paths
    through here gives the healthcheck a Qdrant-specific signal without
    instrumenting every call site.

    WSZYSTKIE ścieżki ODCZYTU muszą iść tędy, a nie przez gołe
    ``asyncio.to_thread``. Trzy z nich wołały wątek wprost
    (``similarity_for_candidate_ids``, ``search_jobs_semantic``,
    ``search_similar_jobs_by_job_id``), więc ich awarie nie wchodziły do okna
    zdrowia Qdranta. Pierwsza z tych trzech obsługuje kanban i scoring
    pipeline'u — czyli ruch, który przy padniętym Qdrancie milczy najgłośniej,
    a `/api/health` nadal raportował `qdrant: healthy`, bo widział wyłącznie
    ruch z wyszukiwarki. Dokładając kolejny odczyt: użyj tej funkcji.
    """
    from app.services.ai_health import record_provider_call

    started = time.monotonic()
    failed = True
    try:
        result = await asyncio.to_thread(fn)
        failed = False
        return result
    finally:
        record_provider_call("qdrant", int((time.monotonic() - started) * 1000), failed)


def init_qdrant_collection() -> None:
    """
    Create Qdrant collections if missing:
      - nexus_candidates (Phase 1)
      - nexus_jobs       (Phase 2)

    Called at application startup (synchronous, runs in thread via asyncio.to_thread).
    """
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        existing = {c.name for c in client.get_collections().collections}

        for coll in (_collection(), _jobs_collection()):
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
            f"[Qdrant] init_qdrant_collection failed: {e} — semantic search will be unavailable."
        )


# ---------------------------------------------------------------------------
# Voyage AI — embedding generation
# ---------------------------------------------------------------------------


OLLAMA_EMBED_MODEL = "mxbai-embed-large"  # 1024-dim, compatible with Qdrant collection


async def _voyage_embed(
    text: str, *, input_type: str = "document"
) -> Optional[list[float]]:
    """Generate embedding via Voyage AI (model from EMBEDDING_MODEL env, default voyage-3-large)."""
    out = await _voyage_embed_batch([text], input_type=input_type)
    if not out:
        return None
    return out[0]


async def _voyage_embed_batch(
    texts: list[str], *, input_type: str = "document"
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
    # Report to the per-provider health window from the ONE place every Voyage
    # embedding call funnels through. Instrumenting callers instead would leave
    # the indexing path (embed_candidate / embed_job) unobserved, which is
    # exactly where a silent Voyage outage stops producing vectors while every
    # read path still looks fine because it is serving what was already indexed.
    from app.services.ai_health import record_provider_call
    from app.services.search_telemetry import record_embedding_attempt

    started = time.monotonic()
    failed = True
    attempts = max(1, int(getattr(settings, "VOYAGE_MAX_ATTEMPTS", 3)))
    try:
        for attempt in range(1, attempts + 1):
            attempt_started = time.monotonic()
            attempt_failed = True
            usage_tokens = None
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        VOYAGE_API_URL,
                        headers={
                            "Authorization": f"Bearer {settings.VOYAGE_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": _voyage_model(),
                            "input": payload_texts,
                            "input_type": input_type,
                            "output_dimension": VECTOR_SIZE,
                            "truncation": True,
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    usage_tokens = (body.get("usage") or {}).get("total_tokens")
                    data = body.get("data") or []
                    # Voyage returns items with `index` field; reorder to input order.
                    by_idx = {
                        int(item["index"]): item["embedding"]
                        for item in data
                        if "embedding" in item
                    }
                    failed = False
                    attempt_failed = False
                    return [by_idx.get(i) for i in range(len(texts))]
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                logger.warning("[Voyage] HTTP %s — %s", status, e.response.text[:200])
                if status not in _VOYAGE_RETRY_STATUSES or attempt == attempts:
                    return None
            except httpx.ConnectError as e:
                # Świadomie WYŁĄCZNIE błąd nawiązania połączenia. Read-timeout
                # też bywa przejściowy, ale kosztuje pełne 60 s na próbę — trzy
                # takie to 180 s na request, czyli fronton (axios 30 s) i tak
                # zdąży się poddać, a my zapłacimy trzykrotnie.
                logger.warning("[Voyage] connect error: %s", e)
                if attempt == attempts:
                    return None
            except Exception as e:
                logger.warning("[Voyage] error: %s", e)
                return None
            finally:
                record_embedding_attempt(
                    model=_voyage_model(),
                    tokens=usage_tokens,
                    failed=attempt_failed,
                    elapsed_ms=(time.monotonic() - attempt_started) * 1000,
                )
            await asyncio.sleep(_VOYAGE_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        return None
    finally:
        record_provider_call("voyage", int((time.monotonic() - started) * 1000), failed)


async def _ollama_embed(text: str) -> Optional[list[float]]:
    """
    Local fallback using Ollama's `mxbai-embed-large` (1024-dim, same as Voyage).
    Lets the stack run fully offline without any external API key.
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
        logger.warning("[Ollama embed] error: %s", e)
        return None


async def generate_embedding(
    text: str, *, input_type: str = "document", use_cache: bool = True
) -> Optional[list[float]]:
    """
    Generate a 1024-dim embedding for *text*. Tries Voyage first (if key present),
    falls back to local Ollama (mxbai-embed-large). Returns None only if both fail.

    `input_type` should be "document" when indexing entities (candidates, jobs)
    and "query" when embedding a search query — Voyage 3-large applies different
    instruction prompts for each, improving retrieval quality.

    Cache: "document" embeddings hit a Postgres SHA-256 cache (Item 4) so
    duplicate uploads skip Voyage. Queries skip the cache (unique per call).
    Set `use_cache=False` for batch reembed paths that intentionally rewrite.
    """
    if not text or not text.strip():
        return None

    # Document cache lookup (queries are usually unique — skip).
    cache_eligible = use_cache and input_type == "document"
    if cache_eligible:
        try:
            from app.services.embedding_cache import get as _cache_get

            cached = await _cache_get(
                text, model=_voyage_model(), input_type=input_type, dim=VECTOR_SIZE
            )
            if cached is not None:
                return cached
        except Exception as e:  # noqa: BLE001
            logger.debug("[embedding] cache miss path error: %s", e)

    # Zapytania: cache W PROCESIE, nie w Postgresie — patrz komentarz przy
    # `_QUERY_EMBED_CACHE`. Chodzi o jeden request, który pyta o to samo dwa
    # razy, a nie o trwałe składowanie unikalnych fraz.
    query_cache_key: Optional[str] = None
    if use_cache and input_type == "query":
        query_cache_key = _query_cache_key(text, _voyage_model(), VECTOR_SIZE)
        cached_query = _query_cache_get(query_cache_key)
        if cached_query is not None:
            return cached_query

    emb = await _voyage_embed(text, input_type=input_type)
    from_voyage = emb is not None
    if emb is None:
        # Ollama fallback ONLY when Voyage is not configured at all (offline/dev
        # mode — both queries and documents live in a consistent Ollama space).
        # When Voyage IS configured but transiently failing, mixing an Ollama
        # vector into the Voyage-embedded index/queries yields random cosine
        # similarities despite the matching dimension (M3-VEC-01) — degrade to
        # None instead, so callers hit their lexical/DB fallbacks and the
        # entity gets re-embedded once Voyage recovers.
        if settings.VOYAGE_API_KEY:
            logger.warning(
                "[embedding] Voyage configured but unavailable — degraded "
                "(no Ollama fallback: mixed vector spaces poison the index)"
            )
            return None
        emb = await _ollama_embed(text)
        if emb is not None:
            logger.info("[embedding] using Ollama fallback (Voyage not configured)")

    if emb is None:
        logger.warning("[embedding] both Voyage and Ollama unavailable")
        return None

    # Best-effort cache write — ONLY for genuine Voyage results. An Ollama
    # fallback vector has the same 1024 dims but lives in a DIFFERENT semantic
    # space; caching it under the Voyage model key would silently poison every
    # later cosine comparison against Voyage-embedded documents (AI-P0-03).
    if cache_eligible and from_voyage:
        try:
            from app.services.embedding_cache import store as _cache_store

            await _cache_store(text, emb, model=_voyage_model(), input_type=input_type)
        except Exception as e:  # noqa: BLE001
            logger.debug("[embedding] cache store error: %s", e)

    # Ten sam warunek `from_voyage` co wyżej i z DOKŁADNIE tego samego powodu:
    # wektor z Ollamy ma te same 1024 wymiary, ale żyje w innej przestrzeni.
    # Zapisany pod kluczem modelu Voyage'a zatruwałby kosinusy tak samo cicho —
    # tyle że w pamięci procesu, więc jeszcze trudniej byłoby to zauważyć.
    if query_cache_key is not None and from_voyage:
        _query_cache_put(query_cache_key, emb)

    return emb


# ---------------------------------------------------------------------------
# Candidate embedding — store in Qdrant
# ---------------------------------------------------------------------------


def _build_candidate_text(candidate) -> str:
    """Dispatch candidate embedding text by schema version (plan PR7).

    ``AI_TEXT_SCHEMA_V2`` on ⇒ the PII-free canonical builder; off ⇒ legacy.
    Selected here so every call site (embed + outbox desired-hash) is consistent.
    """
    if getattr(settings, "AI_TEXT_SCHEMA_V3", False):
        from app.services.canonical_text import build_candidate_text_v3

        return build_candidate_text_v3(candidate)
    if getattr(settings, "AI_TEXT_SCHEMA_V2", False):
        from app.services.canonical_text import build_candidate_text_v2

        return build_candidate_text_v2(candidate)
    return _build_candidate_text_v1(candidate)


def _build_candidate_text_v1(candidate) -> str:
    """Build a rich text blob from candidate fields for embedding (legacy)."""
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


async def _record_failed_embed_intent(candidate_id: int, db: AsyncSession) -> None:
    """Zostaw po nieudanym embedowaniu ślad, na którym system może zadziałać.

    Zwracany `bool` nie jest naprawą: WSZYSTKIE ścieżki zapisu kandydata
    odrzucają go i łapią wyłącznie wyjątek, więc jedno przejściowe 429 z
    Voyage'a kończyło się rekordem poprawnym w Postgresie i trwale nieobecnym
    w matchingu — bez wpisu, który ktokolwiek mógłby później zdrenować
    (`enqueue()` jest no-opem przy wyłączonej fladze outboxu, a reconciler
    dryfu z założenia pomija rekordy NIGDY nieindeksowane). `record_bulk_reindex`
    świadomie ignoruje flagę outboxu — jego kontrakt to „wiersz albo nic",
    a nic jest właśnie tym błędem.

    Piszemy w sesji WOŁAJĄCEGO (bez commita): intencja ma się utrwalić dokładnie
    wtedy, gdy utrwali się kandydat, którego dotyczy.

    `worker_enabled()` jest warunkiem KONIECZNYM, nie ostrożnością: przy
    włączonym workerze to ON woła `embed_candidate` (`_default_reindex`) i sam
    prowadzi księgowość prób (`attempts` → `failed`/`dead`). Dopisanie stamtąd
    nowego zdarzenia zamieniłoby każdą nieudaną próbę drenażu w kolejny wiersz
    kolejki — podczas awarii providera kolejka rosłaby wykładniczo, a licznik
    prób przestałby cokolwiek znaczyć.
    """
    from app.services.index_outbox_service import (
        CANDIDATE,
        record_bulk_reindex,
        worker_enabled,
    )

    if worker_enabled():
        return
    try:
        await record_bulk_reindex(db, CANDIDATE, [candidate_id])
    except Exception as exc:  # noqa: BLE001 — zapis intencji jest best-effort
        logger.warning(
            "[Embed] nie udało się zapisać intencji reindeksu dla kandydata %s: %s",
            candidate_id,
            exc,
        )


async def embed_candidate(candidate_id: int, db: AsyncSession) -> bool:
    """
    Generate an embedding for a candidate and upsert it into Qdrant.
    Returns True on success, False on failure.

    Porażka providera zostawia dodatkowo trwałą intencję reindeksu
    (:func:`_record_failed_embed_intent`) — bez niej „nie udało się" znikało
    razem z requestem.
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

        embedding = await generate_embedding(text)
        if embedding is None:
            await _record_failed_embed_intent(candidate_id, db)
            return False

        # Upsert into Qdrant
        def _upsert():
            from qdrant_client import QdrantClient
            from qdrant_client.models import PointStruct

            client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
            client.upsert(
                collection_name=_collection(),
                points=[
                    PointStruct(
                        id=candidate_id,
                        vector=embedding,
                        # Bez "name" w payloadzie (od rundy 2): żaden konsument
                        # go nie czyta (zweryfikowane grepem 2026-08-18), a PII
                        # w indeksie to czysty koszt przy RODO-erasure.
                        payload={
                            "candidate_id": candidate_id,
                            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                            "embedding_model": _voyage_model()
                            if settings.VOYAGE_API_KEY
                            else "unverified-provider",
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
        logger.error(f"[Embed] Failed to embed candidate {candidate_id}: {e}")
        await _record_failed_embed_intent(candidate_id, db)
        return False


async def delete_candidate_embedding(candidate_id: int) -> bool:
    """Best-effort removal of a candidate's vector from Qdrant.

    The point id is the integer candidate_id (see ``embed_candidate``). Failures
    are logged and swallowed — a hard candidate delete must not be blocked by an
    unreachable Qdrant.
    """

    def _delete():
        from qdrant_client import QdrantClient

        from app.services.passage_index import delete_candidate_passages

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

        # KAŻDA kolekcja kandydacka, nie tylko aktywna. W oknie side-by-side
        # (stara kolekcja + kolekcja z nowym schematem tekstu obok siebie,
        # przełączane `QDRANT_COLLECTION`) kasowanie wyłącznie z aktywnej
        # zostawiałoby wektor osoby w tej drugiej — cichy przeciek dokładnie
        # tej klasy, którą pasaże domknęły niżej. Prefiks łapie też przyszłe
        # kolekcje eksperymentalne bez pamiętania o tej funkcji.
        try:
            names = [c.name for c in client.get_collections().collections]
        except Exception:
            names = []
        active = _collection()
        targets = {active} | {n for n in names if n.startswith("nexus_candidates")}
        for coll in targets:
            if coll == active:
                # Awaria na kolekcji AKTYWNEJ musi WYJŚĆ z _delete(): zewnętrzny
                # handler zwraca wtedy False, a kwarantanna (`if not deleted:`)
                # stage'uje trwały retry. Połknięcie jej tutaj zwracałoby True
                # przy nieusuniętym wektorze — cicha luka w RODO-erasure.
                client.delete(collection_name=coll, points_selector=[candidate_id])
                continue
            try:
                client.delete(collection_name=coll, points_selector=[candidate_id])
            except Exception:
                # Kolekcja poboczna (np. właśnie dropnięta) nie może zablokować
                # kasowania z aktywnej ani przewrócić całej operacji.
                logger.warning(
                    "[Embed] Delete candidate %s from collection %s failed",
                    candidate_id,
                    coll,
                )

        # Pasaże CV kasujemy TU, a nie osobną ścieżką, bo to jedyne miejsce
        # wołane przy usuwaniu kandydata (`candidate_identity_quarantine`
        # i outbox). Osobna funkcja, o której trzeba pamiętać, prędzej czy
        # później zostałaby pominięta — a wtedy w indeksie zostawałoby
        # nazwisko i fragmenty CV osoby skasowanej.
        #
        # Bezwarunkowo, NIE za flagą `CV_PASSAGES_ENABLED`: flaga rządzi tym,
        # czy z pasaży CZYTAMY, a nie tym, czy dane po kimś zostają. Kolekcja
        # wypełniona przy wyłączonej fladze to najbardziej prawdopodobny stan
        # w trakcie wdrożenia i właśnie wtedy przeciek byłby najcichszy.
        #
        # Kontrakt: NIC poniżej `client.delete` nie może rzucić — zewnętrzny
        # handler logowałby wtedy „Failed to delete candidate vector", choć
        # wektor został już usunięty, i licznik sukcesu kłamałby w dół.
        # `delete_candidate_passages` łapie wszystko wewnętrznie i zwraca bool.
        delete_candidate_passages(client, candidate_id)

    try:
        await asyncio.to_thread(_delete)
        logger.info(f"[Embed] Deleted candidate {candidate_id} vector from Qdrant.")
        return True
    except Exception as e:  # pragma: no cover - network/Qdrant failure path
        logger.warning(f"[Embed] Failed to delete candidate {candidate_id} vector: {e}")
        return False


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------


async def search_candidates_semantic(
    query: str,
    top_k: int = 20,
    *,
    raise_on_error: bool = False,
) -> list[dict]:
    """
    Embed *query* and search the Qdrant collection for the closest candidates.
    Returns a list of dicts: [{candidate_id, score}].

    Each call (including its embedding step) is recorded in the AI health
    tracker so ``meta.ai_status`` on candidate-search responses can flip the
    "manual search" banner when Voyage/Qdrant is degraded or down.

    When ``raise_on_error`` is True, a provider *failure* (no query embedding or
    a raised Qdrant call) raises :class:`SemanticSearchUnavailable` instead of
    returning ``[]`` — letting callers distinguish an outage from a genuinely
    empty result. A healthy search that simply matches nothing still returns
    ``[]``. The default (False) keeps the swallow-to-``[]`` contract.
    """
    from app.services.ai_health import AiCallTimer

    with AiCallTimer() as timer:
        embedding = await generate_embedding(query, input_type="query")
        if embedding is None:
            timer.failed = True
            logger.warning(
                "[Search] Could not generate query embedding — returning empty results."
            )
            if raise_on_error:
                raise SemanticSearchUnavailable("query embedding unavailable")
            return []

        def _search():
            from qdrant_client import QdrantClient

            from app.services.passage_index import (
                aggregate_hits_to_candidates,
                merge_candidate_hits,
                passages_enabled,
                search_passage_hits,
            )

            client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
            hits = client.search(
                collection_name=_collection(),
                query_vector=embedding,
                limit=top_k,
                with_payload=True,
            )
            base = [
                {
                    "candidate_id": int(hit.id),
                    "score": round(float(hit.score), 4),
                    "payload": hit.payload or {},
                }
                for hit in hits
            ]
            # Fala 2: unia z najlepszym pasażem CV, za flagą. Bramka jest TUTAJ,
            # w jedynym wspólnym wejściu retrievalu — dziewięciu konsumentów
            # przełącza się jedną flagą NARAZ. Przełączanie ich pojedynczo
            # zostawiałoby okres, w którym część powierzchni liczy na starej
            # skali semantycznej, część na nowej, a cache score'ów (klucz bez
            # pola powierzchni) mieszałby obie w jednym wierszu.
            if passages_enabled():
                try:
                    passage_rows = aggregate_hits_to_candidates(
                        # Zapas ×4: jeden kandydat potrafi obsadzić kilka
                        # czołowych miejsc swoimi pasażami; po agregacji do
                        # kandydatów lista się skraca.
                        search_passage_hits(client, embedding, limit=top_k * 4),
                        top_k=top_k,
                    )
                except Exception as passage_exc:  # noqa: BLE001
                    # Degradacja do samego wektora kandydata, nie awaria
                    # całości — pasaże są DODATKIEM do sygnału, nie podmianą.
                    logger.warning(
                        "[Search] pasaże niedostępne, zwracam sam wektor kandydata: %s",
                        passage_exc,
                    )
                    return base
                return merge_candidate_hits(base, passage_rows, top_k=top_k)
            return base

        try:
            return await _run_qdrant(_search)
        except Exception as e:
            timer.failed = True
            logger.error(f"[Search] Qdrant search error: {e}")
            if raise_on_error:
                raise SemanticSearchUnavailable("qdrant search failed") from e
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
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, HasIdCondition

        from app.services.passage_index import (
            best_passage_scores_for_ids,
            passages_enabled,
        )

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        hits = client.search(
            collection_name=_collection(),
            query_vector=embedding,
            query_filter=Filter(must=[HasIdCondition(has_id=ids)]),
            limit=len(ids),
            with_payload=False,
        )
        scores = {int(hit.id): round(float(hit.score), 4) for hit in hits}
        # Fala 2: ta ścieżka zasila TEN SAM cache score'ów co pula z
        # `search_candidates_semantic` (klucz: kandydat×oferta×profil, bez pola
        # powierzchni). Musi więc przełączyć się TĄ SAMĄ flagą — zostawiona na
        # starej kolekcji mieszałaby dwie skale semantyczne w jednym wierszu.
        if passages_enabled():
            try:
                for candidate_id, best in best_passage_scores_for_ids(
                    client, embedding, ids
                ).items():
                    if best > scores.get(candidate_id, -1.0):
                        scores[candidate_id] = best
            except Exception as passage_exc:  # noqa: BLE001
                logger.warning(
                    "[Search] pasaże niedostępne w similarity_for_candidate_ids: %s",
                    passage_exc,
                )
        return scores

    try:
        return await _run_qdrant(_search)
    except Exception as e:
        logger.error(f"[Search] similarity_for_candidate_ids error: {e}")
        return {}


async def indexed_candidate_ids(candidate_ids: list[int]) -> Optional[set[int]]:
    """Subset of ``candidate_ids`` that actually has a vector in Qdrant.

    A candidate without a vector is not "ranked badly" — it can never be
    returned by any semantic path at all, while still looking perfectly normal
    in the candidate list. Retrieval-quality measurements are meaningless
    without this: a job whose ground truth is 40% unindexed has a hard recall
    ceiling that no ranking change can lift, and reading that as "the engine
    missed them" sends you tuning weights to fix a data-pipeline hole.

    Returns ``None`` — not an empty set — when Qdrant cannot answer, so that an
    outage cannot masquerade as "none of them are indexed". An empty set is a
    real answer meaning "none of these ids are in the collection"; conflating
    the two would turn a five-minute Qdrant blip into a report claiming the
    whole index is gone.
    """
    ids = [int(c) for c in candidate_ids]
    if not ids:
        return set()

    def _retrieve() -> set[int]:
        client = _get_qdrant_client()
        if client is None:
            raise RuntimeError("Qdrant client unavailable")
        found: set[int] = set()
        # Chunked: a job's ground truth can reach ~200 ids on this dataset, and
        # retrieve() puts them all in one request payload.
        for start in range(0, len(ids), 256):
            chunk = ids[start : start + 256]
            points = client.retrieve(
                collection_name=_collection(),
                ids=chunk,
                with_payload=False,
                with_vectors=False,
            )
            found.update(int(p.id) for p in points)
        return found

    try:
        return await _run_qdrant(_retrieve)
    except Exception as e:
        logger.error(f"[Search] indexed_candidate_ids error: {e}")
        return None


_JOB_VECTOR_CHECK_TIMEOUT_SECONDS = 2.0


async def indexed_job_ids(job_ids: list[int]) -> Optional[set[int]]:
    """Bliźniak ``indexed_candidate_ids`` na kolekcji OFERT.

    Zwraca ``None`` — nie pusty zbiór — gdy Qdrant nie umie odpowiedzieć, żeby
    awaria nie udawała „żadna z tych ofert nie jest zaindeksowana".
    """
    ids = [int(j) for j in job_ids]
    if not ids:
        return set()

    def _retrieve() -> set[int]:
        client = _get_qdrant_client()
        if client is None:
            raise RuntimeError("Qdrant client unavailable")
        found: set[int] = set()
        for start in range(0, len(ids), 256):
            chunk = ids[start : start + 256]
            points = client.retrieve(
                collection_name=_jobs_collection(),
                ids=chunk,
                with_payload=False,
                with_vectors=False,
            )
            found.update(int(p.id) for p in points)
        return found

    try:
        return await _run_qdrant(_retrieve)
    except Exception as e:
        logger.error(f"[Search] indexed_job_ids error: {e}")
        return None


async def _heal_job_embedding_id(job_id: int) -> None:
    """Dopisz znacznik ofercie, która MA wektor, a kolumnę ma pustą.

    WŁASNA sesja, świadomie: wołający (sweeper marketplace, podpowiedzi pytań)
    ma w ręku transakcję, której ta naprawa nie ma prawa zatwierdzić ani cofnąć.

    ``WHERE embedding_id IS NULL`` — nigdy nie nadpisujemy istniejącej wartości.
    Best-effort: autorytetem jest Qdrant, a nieudany stempel to tylko droższe
    następne wywołanie, nie błędna odpowiedź.
    """
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.job import Job

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Job)
                .where(Job.id == job_id, Job.embedding_id.is_(None))
                .values(embedding_id=str(job_id))
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[Embed] job %s ma wektor, ale nie udało się dopisać embedding_id: %s",
            job_id,
            exc,
        )


async def job_has_vector(job_id: int, embedding_id: Optional[str]) -> Optional[bool]:
    """Czy oferta ma wektor w ``nexus_jobs``. ``None`` = „nie wiem".

    JEDYNY dozwolony czytelnik ``jobs.embedding_id`` w warstwie ORM (pilnuje
    tego ``tests/test_job_embedding_id_marker.py``).

    UCZCIWIE o zasięgu: trzy bramki, które tę kolumnę czytały
    (``marketplace_service``, oba tiery ``question_suggestions``), zostały
    ZDJĘTE, a nie przepisane na to wywołanie — żadna z nich nie używa wektora
    oferty, więc najlepszą odpowiedzią na „nie wiem" jest tam NIE ZADAWAĆ
    pytania. Dziś konsument jest więc dokładnie jeden: ``compute_proposals``,
    które musi wiedzieć, czy płacić Voyage'owi za embedding. Ta funkcja istnieje
    po to, żeby czwarty czytelnik kolumny miał dokąd pójść zamiast kopiować
    predykat po raz czwarty — a nie dlatego, że ma dziś trzech.

    Kolumna zostaje TANIM ZAWĘŻENIEM: gdy jest niepusta, odpowiadamy bez ruchu
    sieciowego. Kłamstwo „na TAK" (kolumna pełna, wektora brak) jest tu
    nieszkodliwe — żaden z trzech wołających nie liczy niczego z wektora
    oferty, a ``search_similar_jobs_by_job_id`` sam zwróci pustkę. Qdrant
    rozstrzyga wyłącznie ścieżkę negatywną, bo tylko tam kolumna kłamie
    kosztownie: ``embed_job`` upsertuje wektor PRZED commitem stempla, więc
    padnięty commit zostawia wektor i pustą kolumnę — i oferta cicho przestaje
    generować propozycje oraz podpowiedzi pytań, na zawsze.

    Sufit czasu jest tu, nie w ``indexed_job_ids``: bramki lecą SEKWENCYJNIE po
    ofertach, a domyślny timeout ``qdrant-client`` to ~5 s, więc wiszący Qdrant
    zatrzymałby sweepera zamiast go zdegradować.
    """
    if embedding_id:
        return True

    try:
        found = await asyncio.wait_for(
            indexed_job_ids([job_id]),
            timeout=_JOB_VECTOR_CHECK_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("[Embed] nie udało się sprawdzić wektora oferty %s", job_id)
        return None

    if found is None:
        return None
    if job_id not in found:
        return False

    await _heal_job_embedding_id(job_id)
    return True


# ---------------------------------------------------------------------------
# Phase 2: Job embedding (reverse matching)
# ---------------------------------------------------------------------------


def _build_job_text(job, *, max_field_chars: int | None = 1200) -> str:
    """Dispatch job embedding text by schema version (plan PR7).

    ``AI_TEXT_SCHEMA_V2`` on ⇒ the PII-free canonical builder; off ⇒ legacy.

    ``max_field_chars`` — sufit na POJEDYNCZE pole tekstowe. ``None`` znaczy
    „nie tnij" i używa tego wyłącznie Talent Radar: jego oferta jest efemeryczna,
    a wklejony przez rekrutera request bywa mailem, w którym wymagania stoją na
    końcu, po akapicie grzeczności. Domyślne 1200 znaków obcinało go tak, że
    silnik rankował po wstępie — zmierzone: `must 1/2` i podobieństwo 0,65
    zamiast 0,73 dla tego samego zapytania bez wstępu.

    Domyślna wartość zostaje 1200 i to jest istotne: ``index_outbox_service``
    liczy SHA-256 z tego tekstu, żeby zdecydować o reindeksie, a
    ``compute_proposals`` używa go jako odcisku świeżości snapshotów. Globalne
    podniesienie limitu przestawiłoby 949 ofert na „do przeliczenia" i
    unieważniło snapshoty propozycji — bez żadnej korzyści, bo indeksowana
    oferta i tak niesie te pola w kolumnach.

    Parametr przechodzi przez OBA buildery świadomie: gdyby trafił tylko do v1,
    zmiana przestałaby działać w dniu, w którym ktoś włączy ``AI_TEXT_SCHEMA_V2``
    — i to po cichu, bo krótszy tekst nadal daje poprawny wynik, tylko gorszy.
    """
    if getattr(settings, "AI_TEXT_SCHEMA_V2", False):
        from app.services.canonical_text import build_job_text_v2

        return build_job_text_v2(job, max_field_chars=max_field_chars)
    return _build_job_text_v1(job, max_field_chars=max_field_chars)


def _build_job_text_v1(job, *, max_field_chars: int | None = 1200) -> str:
    """Build a rich text blob from job fields for embedding (legacy).

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
        parts.append(job.description[:max_field_chars])
    if job.requirements:
        parts.append(job.requirements[:max_field_chars])

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
    #
    # Czytane przez `champion_view`, więc niezależnie od tego, czy profil ma
    # kształt sprzed czy po przebudowie szablonu (09.2026). KOLEJNOŚĆ i LIMITY
    # znaków są celowo nietknięte: to jest tekst idący do wektora, a jego zmiana
    # unieważniłaby indeks 949 ofert i wmieszała zmianę retrievalu w przebudowę
    # formularza. Dla starego profilu wynik jest bajt w bajt taki jak dotąd.
    #
    # Stack (sekcja 3) świadomie NIE dochodzi tutaj osobno — `PUT` synchronizuje
    # go do `Job.must_skills`/`nice_skills`, które i tak dopisują się niżej.
    # Dodanie go tu dałoby te same nazwy dwa razy.
    champion = getattr(job, "champion_profile", None)
    if isinstance(champion, dict) and champion:
        proj = champion_view.project(champion)
        cli = champion_view.client(champion)
        for value in (
            proj.get("about"),
            proj.get("responsibilities"),
            cli.get("selling_points"),
        ):
            if isinstance(value, str) and value.strip():
                parts.append(value[:1000])

        # Screening questions encode the recruiter's mental model of the
        # ideal candidate — ideal_answer is exactly what we want to match.
        for q in champion_view.screening_questions(champion)[:10]:
            if not isinstance(q, dict):
                continue
            ideal = q.get("ideal_answer")
            if isinstance(ideal, str) and ideal.strip():
                parts.append(ideal[:400])
            qtext = q.get("question")
            if isinstance(qtext, str) and qtext.strip():
                parts.append(qtext[:200])

        # Free-text recruiter notes — strongest semantic signal for niche roles
        for value in (
            cli.get("historical_questions"),
            cli.get("consultant_insight"),
        ):
            if isinstance(value, str) and value.strip():
                parts.append(value[:600])

        srch = champion_view.search(champion)
        for key in ("keywords", "target_companies", "notes"):
            value = srch.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value[:500])

        basics = champion_view.basics(champion)
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

        embedding = await generate_embedding(text)
        if embedding is None:
            return False

        def _upsert():
            from qdrant_client import QdrantClient
            from qdrant_client.models import PointStruct

            client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
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

        # Od tego momentu wektor JEST w Qdrancie. Zapis do Postgresa nie jest
        # z nim atomowy, więc padnięty commit zostawiał ofertę z wektorem
        # i pustą kolumną — bez śladu, bez ponowienia. Własny `try` WOKÓŁ SAMEGO
        # commita, bo zewnętrzny `except` łapie też przypadki SPRZED upsertu,
        # a ostemplowanie oferty BEZ wektora wypycha ją na zawsze z jedynego
        # zapytania naprawczego (`phase3.py`: WHERE embedding_id IS NULL).
        job.embedding_id = str(job_id)
        try:
            await db.commit()
        except Exception as commit_exc:  # noqa: BLE001
            logger.warning(
                "[Embed] job %s: wektor w Qdrancie, commit stempla padł (%s) — "
                "stempluję z osobnej sesji",
                job_id,
                commit_exc,
            )
            # Sesja wołającego po padniętym commicie jest nieużywalna, więc
            # naprawa musi mieć własną. `WHERE embedding_id IS NULL` — nigdy
            # nie nadpisujemy cudzej wartości.
            #
            # `rollback()` PRZED naprawą i przed powrotem: bez niego sesja
            # wołającego zostaje w stanie PendingRollbackError i pada NIE TYLKO
            # ten krok, ale wszystko poniżej. W `compute_proposal_for_job`
            # intencją `except` jest „leć dalej bez warstwy semantycznej" —
            # a niecofnięta transakcja zabija także kolejne zapytania (odczyt
            # profilu wag), więc całe liczenie propozycji przewraca się przez
            # nieudany embedding. Po rollbacku SQLAlchemy wygasza wartość
            # `job.embedding_id` w pamięci (nigdy nie została zatwierdzona),
            # ale naprawa zapisała ją już WŁASNĄ sesją — więc `session.refresh`
            # u wołającego wczyta wartość naprawioną.
            try:
                await db.rollback()
            except Exception as rb_exc:  # noqa: BLE001
                logger.warning(
                    "[Embed] job %s: rollback po padniętym commicie też padł: %s",
                    job_id,
                    rb_exc,
                )
            await _heal_job_embedding_id(job_id)
            return False

        logger.info(f"[Embed] Job {job_id} embedded and stored in Qdrant.")
        return True

    except Exception as e:
        logger.error(f"[Embed] Failed to embed job {job_id}: {e}")
        return False


async def search_jobs_semantic(
    query: str, top_k: int = 20, *, raise_on_error: bool = False
) -> list[dict]:
    """Embed *query* and return top-k closest job ids from nexus_jobs.

    The *query* text (candidate profile, CV extract or free-text search) is the
    search input against a corpus of job *documents*, so it MUST be embedded
    with ``input_type="query"``. Voyage 3-large applies an asymmetric
    instruction prompt for queries vs documents; embedding the query as a
    document (the old default) degraded reverse-match retrieval quality on
    every candidate/CV → jobs surface (recommendations, marketplace, CV
    preview, hybrid search).

    ``raise_on_error`` mirrors :func:`search_candidates_semantic`: a provider
    failure raises :class:`SemanticSearchUnavailable` instead of returning
    ``[]``, so hybrid retrieval can flag an outage rather than "no jobs".
    """
    embedding = await generate_embedding(query, input_type="query")
    if embedding is None:
        if raise_on_error:
            raise SemanticSearchUnavailable("query embedding unavailable")
        return []

    def _search():
        from qdrant_client import QdrantClient

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
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
        return await _run_qdrant(_search)
    except Exception as e:
        logger.error(f"[Search] Qdrant jobs search error: {e}")
        if raise_on_error:
            raise SemanticSearchUnavailable("qdrant jobs search failed") from e
        return []


async def search_similar_jobs_by_job_id(
    job_id: int, top_k: int = 20, exclude_self: bool = True
) -> Optional[list[dict]]:
    """Find jobs semantically similar to *job_id* using its stored vector.

    Flow:
      1. Retrieve job vector from `nexus_jobs` collection.
      2. Run vector search limit=top_k+1 (to drop self).
      3. Optionally exclude *job_id* itself from results.

    Zwraca `[{"job_id": int, "score": float, "payload": dict}]` malejąco.

    ``None`` znaczy "NIE WIEM" — Qdrant nie odpowiedział. ``[]`` znaczy "WIEM,
    ŻE NIE MA" — Qdrant odpowiedział, a oferta nie ma wektora albo nie ma
    podobnych. Do #408 oba stany zwracały tę samą pustą listę, więc podczas
    awarii Qdranta oba tiery podpowiedzi milkły, tier 4 uruchamiał się jako
    bezpiecznik ("prep-kit musi mieć >= 1 pytanie") i rekruter dostawał
    wiarygodną, NIEPUSTĄ listę pytań bez żadnego sygnału, że dwa najlepsze
    źródła nie odpowiedziały. To ta sama klasa co #403 — system nie wie,
    a zachowuje się tak, jakby wiedział — tylko o warstwę wyżej.

    Wołający MUSI rozróżniać `is None` od pustej listy. Sam `if not hits:`
    skleja oba stany z powrotem.
    """

    def _run() -> Optional[list[dict]]:
        from qdrant_client import QdrantClient

        # Jawny sufit czasu. Bramka `if not job.embedding_id: return []`, którą
        # #403 zdjęło, była PRZYPADKOWĄ tarczą czasową: dla oferty z pustą
        # kolumną kończyła wywołanie natychmiast, więc tu nigdy nie docierało.
        # Bez niej oba tiery podpowiedzi wołają Qdranta dla KAŻDEJ takiej oferty
        # na SYNCHRONICZNEJ ścieżce żądania (`GET /jobs/{id}/suggested-questions`,
        # `generate_prep_kit`), a `qdrant-client` bez `timeout=` spada na
        # domyślny ~5 s httpx — czyli przy brown-oucie Qdranta do ~10 s na
        # żądanie. Degradacja ma być szybka, nie zawieszać użytkownika.
        client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=_JOB_VECTOR_CHECK_TIMEOUT_SECONDS,
        )

        try:
            points = client.retrieve(
                collection_name=_jobs_collection(),
                ids=[job_id],
                with_vectors=True,
            )
        except Exception as e:
            # "Nie wiem" — Qdrant nie odpowiedział. Inna sytuacja niż "nie ma",
            # i to jest DOKŁADNIE ta różnica, którą ta funkcja zwracała jako tę
            # samą pustą listę (#408). `None` niesie ją dalej.
            logger.warning(
                "[Search] retrieve vector for job %s failed (Qdrant unreachable?): %s",
                job_id,
                e,
            )
            return None

        if not points:
            # "Nie ma" — Qdrant odpowiedział i wektora nie ma. To JEDYNE miejsce
            # w kodzie ofert, które wie to na pewno (retrieve po PK oferty).
            # WARNING, nie DEBUG: root logger stoi na INFO, więc DEBUG był na
            # prodzie niewidoczny i degradacja podpowiedzi milkła. Patrz #403.
            logger.warning(
                "[Search] job %s has no vector in %s — similar-jobs search "
                "returns empty",
                job_id,
                _jobs_collection(),
            )
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
            # Też "nie wiem": wektor mamy, ale wyszukiwanie nie odpowiedziało.
            logger.error(
                "[Search] similar-jobs search for job %s failed: %s", job_id, e
            )
            return None

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
        return await _run_qdrant(_run)
    except Exception as e:
        logger.error("[Search] search_similar_jobs_by_job_id error: %s", e)
        return None
