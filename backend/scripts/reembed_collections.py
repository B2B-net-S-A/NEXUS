"""One-off re-embed: regenerate Qdrant vectors for candidates and jobs.

Used after switching `VOYAGE_MODEL` (e.g. voyage-3 -> voyage-3-large) — old
embeddings live in a different semantic space, so retrieval against the new
query embeddings degrades until we re-embed.

Run:
    # candidates only, dry run (counts what would be processed)
    python -m scripts.reembed_collections --target candidates --dry-run

    # jobs only, with commit
    python -m scripts.reembed_collections --target jobs --commit

    # both, commit, batch size 50, max 200 (testing)
    python -m scripts.reembed_collections --target all --commit --batch 50 --limit 200

    # progress logging every 100 entities
    python -m scripts.reembed_collections --target all --commit --log-every 100

    # close an indexing gap: embed ONLY what Qdrant is missing
    python -m scripts.reembed_collections --target candidates --only-missing --dry-run
    python -m scripts.reembed_collections --target candidates --only-missing --commit --batch 128

    # the other direction: drop vectors of rows that no longer exist
    python -m scripts.reembed_collections --target all --prune-orphans --dry-run
    python -m scripts.reembed_collections --target all --prune-orphans --commit

Note on scope: without ``--only-missing`` this re-embeds EVERY row, which costs
the same Voyage spend as the original import. That is the right thing after a
``VOYAGE_MODEL`` change (old vectors live in a different semantic space) and the
wrong thing when you merely want to fill a gap.

Kolekcja-cień do A/B tekstu embeddingu (26.09.2026, docs/embedding-v3-ab-runbook.md)::

    # budowa v3 obok produkcji — produkcja nietknięta (bez outboxu, bez
    # znacznika embedding_id), wznawialna po restarcie kontenera
    python -m scripts.reembed_collections --target candidates --commit \
        --collection nexus_candidates_v3 --text-schema v3 --ensure-collection \
        --resume --max-batch-chars 120000

    # po przełączeniu env (AI_TEXT_SCHEMA_V3 + QDRANT_COLLECTION): dogonienie
    # zmian z okresu budowy + wpis stanu indeksu do outboxu
    python -m scripts.reembed_collections --target candidates --commit \
        --resume --record-outbox

Zasady, których pilnuje ``_resolve_candidate_plan``:

* ``--collection`` / ``--text-schema`` inne niż aktywne = **budowa cienia**:
  skrypt NIE dotyka ``candidates.embedding_id`` (kolumna mówi „ma wektor
  w AKTYWNEJ kolekcji”) ani outboxu indeksu;
* ``--record-outbox`` wolno WYŁĄCZNIE na aktywnej kolekcji i aktywnym schemacie
  tekstu — zapis ``indexed_hash`` dla cienia powiedziałby reconcilerowi
  produkcji, że v3 jest zaindeksowane, a ten zakolejkowałby ~60 tys.
  przeliczeń v1 (albo, po przełączeniu, uznałby stan za zgodny, choć nie jest).
  Nie ustawiaj ``QDRANT_COLLECTION``/``AI_TEXT_SCHEMA_V3`` w env samego
  polecenia przy budowie cienia — wtedy skrypt nie odróżni cienia od aktywnej
  kolekcji. Do cienia służą ``--collection`` i ``--text-schema``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import String, cast, select, update  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.services.embedding_service import (  # noqa: E402
    VECTOR_SIZE,
    _build_candidate_text,
    _build_job_text,
    _collection,
    _jobs_collection,
    _voyage_embed_batch,
    _voyage_model,
)

logger = logging.getLogger("reembed_collections")

# Sufit znaków na JEDNO wywołanie Voyage. Voyage limituje łączną liczbę tokenów
# w żądaniu (voyage-3: 120 tys.), a nie tylko liczbę tekstów (128). Tekst v3
# niesie do 12 tys. znaków samego CV, więc 128 takich tekstów to ~1,5 mln
# znaków — kilkakrotnie ponad limit, czyli HTTP 400 na całą paczkę. 120 tys.
# znaków to ~40–60 tys. tokenów nawet przy gęstym polskim tekście (2–3 znaki
# na token) — z zapasem pod limitem. Tekst dłuższy niż sufit idzie sam.
DEFAULT_MAX_BATCH_CHARS = 120_000

# --text-schema → stempel schematu (ten sam słownik co `VersionTrace`).
TEXT_SCHEMAS = ("active", "v1", "v2", "v3", "v3-nonotes")


async def _bulk_upsert_qdrant(collection: str, points: list[dict]) -> int:
    """Bulk upsert points into Qdrant. Returns number upserted."""
    if not points:
        return 0
    from qdrant_client import QdrantClient  # noqa: PLC0415
    from qdrant_client.models import PointStruct  # noqa: PLC0415

    def _upsert():
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        client.upsert(
            collection_name=collection,
            points=[PointStruct(**p) for p in points],
        )

    await asyncio.to_thread(_upsert)
    return len(points)


async def _mark_embedded(model: "type[Candidate] | type[Job]", ids: list[int]) -> None:
    """Set `embedding_id` on rows this script just pushed into Qdrant.

    `embed_candidate` / `embed_job` write this column on every single-row embed
    (as `str(id)` — the column is a copy of the identifier, so its only content
    is "NULL or not", i.e. the predicate "has a vector"). This script upserted
    without it, so a bulk re-embed left the column saying "no vector" for rows
    that had one. Measured on prod 2026-08-07: column 45 317, Qdrant 47 921.

    For jobs the gap is not merely cosmetic — `marketplace_service` and
    `question_suggestions` bail out on `if not job.embedding_id`, so a job
    embedded only by this script silently produced no proposals.

    Best-effort: the vector is already in Qdrant, which is the authority. A
    failed marker must not be reported as a failed embed.
    """
    if not ids:
        return
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(model)
                .where(model.id.in_(ids))
                .values(embedding_id=cast(model.id, String))
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[reembed] vectors upserted but embedding_id not marked for %s ids: %s",
            len(ids),
            exc,
        )


async def _delete_qdrant_points(collection: str, ids: list[int]) -> int:
    """Delete points by id. Returns how many ids were submitted."""
    if not ids:
        return 0
    from qdrant_client import QdrantClient  # noqa: PLC0415
    from qdrant_client.models import PointIdsList  # noqa: PLC0415

    def _delete():
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        for start in range(0, len(ids), 1000):
            client.delete(
                collection_name=collection,
                points_selector=PointIdsList(points=ids[start : start + 1000]),
                wait=True,
            )

    await asyncio.to_thread(_delete)
    return len(ids)


async def _prune_orphans(
    *, entity: str, collection: str, id_column, commit: bool
) -> int:
    """Delete points whose entity no longer exists in the database.

    Right-to-erasure does not reach the vector store today. A candidate vector
    is built from text containing the person's name and up to ~3 000 characters
    of their CV, and the point payload carries `name` outright — so a row that
    is gone from Postgres still has its personal data sitting in Qdrant.

    Measured on prod 2026-08-07: 1 932 orphaned candidate points and 23 job
    points. The likely source is `scripts/merge_duplicate_candidates.py`, which
    merged ~1 884 TalentRadar/Traffit duplicates and deleted the losing rows —
    it re-points every child table and even disables immutability triggers to
    avoid "orphaned PII", but has no notion of the vector store at all.

    Deliberately NOT wired into the main re-embed loop: deleting is not the
    same risk as writing, and an operator should be able to see the count
    before anything is removed. Run with `--dry-run` first.
    """
    indexed = await _qdrant_point_ids(collection)
    async with AsyncSessionLocal() as db:
        live = {row for (row,) in (await db.execute(select(id_column))).all()}

    orphans = sorted(indexed - live)
    logger.info(
        "[prune %s] %s points in Qdrant, %s rows in DB → %s orphaned",
        entity,
        len(indexed),
        len(live),
        len(orphans),
    )
    if not orphans:
        return 0
    if not commit:
        logger.info(
            "[prune %s] DRY RUN — would delete %s points (first 10: %s)",
            entity,
            len(orphans),
            orphans[:10],
        )
        return len(orphans)

    await _delete_qdrant_points(collection, orphans)
    logger.info("[prune %s] deleted %s orphaned points", entity, len(orphans))
    return len(orphans)


async def _qdrant_point_ids(collection: str) -> set[int]:
    """Every point id currently stored in ``collection``.

    Scrolls with vectors and payload switched off, so this pulls ids only —
    the whole candidate collection is ~48k integers, a few MB.

    This, not ``candidates.embedding_id``, is the authority on what is indexed.
    ``_mark_embedded`` now keeps that column in step with what this script
    upserts (it did not, hence the ~2.6k-row disagreement measured on prod
    2026-08-07: column 45 317, Qdrant 47 921), but the column still cannot be
    the authority here: a vector can disappear outside every write path this
    codebase owns — a manual ``delete`` in Qdrant, a rebuilt or renamed
    collection, a restore from an older snapshot. Trusting it would re-embed
    thousands of candidates that already have a vector and miss orphaned points
    entirely. The set difference is only meaningful against Qdrant itself.
    """
    from qdrant_client import QdrantClient  # noqa: PLC0415

    def _scroll() -> set[int]:
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        found: set[int] = set()
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=collection,
                limit=10_000,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            found.update(int(p.id) for p in points)
            if offset is None:
                break
        return found

    try:
        return await asyncio.to_thread(_scroll)
    except Exception as exc:  # noqa: BLE001
        # Fail loudly rather than with a raw traceback: without this the two
        # modes that depend on the scroll (--only-missing, --prune-orphans)
        # crash in a way that reads like a bug in the script rather than
        # "Qdrant is not reachable from here".
        raise RuntimeError(
            f"Cannot read Qdrant collection {collection!r} at "
            f"{settings.QDRANT_HOST}:{settings.QDRANT_PORT} — --only-missing "
            f"and --prune-orphans both need it to compute a set difference. "
            f"Original error: {exc}"
        ) from exc


def _schema_stamp(text_schema: str) -> str:
    """``--text-schema`` → stempel ``TEXT_SCHEMA_*`` (``active`` = bieżący env)."""
    from app.services import canonical_text as ct

    return {
        "active": ct.active_text_schema(),
        "v1": ct.TEXT_SCHEMA_V1,
        "v2": ct.TEXT_SCHEMA_V2,
        "v3": ct.TEXT_SCHEMA_V3,
        "v3-nonotes": ct.TEXT_SCHEMA_V3_NO_NOTES,
    }[text_schema]


def _candidate_text_builder(text_schema: str):
    """Funkcja budująca tekst kandydata dla ``--text-schema``.

    ``active`` to dyspozytor aplikacji (czytany przy WYWOŁANIU, więc testy mogą
    go podmienić). Pozostałe są jawne i NIE zależą od flag w env — cień v3
    buduje się w kontenerze produkcji, który ma ``AI_TEXT_SCHEMA_V3=false``.
    """
    from app.services import canonical_text as ct
    from app.services import embedding_service as emb

    if text_schema == "active":
        return lambda c: _build_candidate_text(c)
    if text_schema == "v1":
        return emb._build_candidate_text_v1
    if text_schema == "v2":
        return ct.build_candidate_text_v2
    if text_schema == "v3":
        return lambda c: ct.build_candidate_text_v3(c, include_notes=True)
    if text_schema == "v3-nonotes":
        return lambda c: ct.build_candidate_text_v3(c, include_notes=False)
    raise ValueError(f"unknown text schema {text_schema!r}")


@dataclass(frozen=True)
class CandidatePlan:
    """Dokąd i czym budujemy wektory kandydatów w tym biegu."""

    collection: str
    text_schema: str  # wartość --text-schema
    schema_stamp: str
    shadow: bool  # kolekcja albo schemat inne niż aktywne w aplikacji
    record_outbox: bool


def _resolve_candidate_plan(
    *,
    collection: Optional[str],
    text_schema: str,
    record_outbox: bool,
) -> CandidatePlan:
    """Rozstrzyga cień vs aktywna kolekcja i pilnuje ``--record-outbox``.

    „Aktywne” = to, czego używa aplikacja w tym procesie (``_collection()``
    i ``active_text_schema()``). Zapis stanu indeksu do outboxu dla czegokolwiek
    innego niż aktywna para (kolekcja, schemat) jest odmową — patrz docstring
    modułu.
    """
    from app.services import canonical_text as ct

    active_collection = _collection()
    target = collection or active_collection
    stamp = _schema_stamp(text_schema)
    shadow = target != active_collection or stamp != ct.active_text_schema()
    if record_outbox and shadow:
        raise ValueError(
            "--record-outbox wolno wyłącznie na AKTYWNEJ kolekcji i aktywnym "
            f"schemacie tekstu (aplikacja: {active_collection!r} / "
            f"{ct.active_text_schema()!r}; ten bieg: {target!r} / {stamp!r}). "
            "Zapis indexed_hash dla cienia okłamałby reconciler produkcji."
        )
    return CandidatePlan(
        collection=target,
        text_schema=text_schema,
        schema_stamp=stamp,
        shadow=shadow,
        record_outbox=record_outbox,
    )


def _text_hash(text: str) -> str:
    """Ten sam hasz treści, który ląduje w payloadzie punktu (`content_hash`)."""
    return hashlib.sha256(text.encode()).hexdigest()


def _char_batches(
    texts: list[str], *, max_chars: int, max_items: int
) -> list[list[int]]:
    """Indeksy tekstów pocięte na paczki ≤ ``max_chars`` znaków i ≤ ``max_items``.

    Kolejność zachowana. Tekst dłuższy niż sufit dostaje własną paczkę — Voyage
    przytnie go sam (``truncation: true``), a dokładanie do niego sąsiadów
    przekroczyłoby limit tokenów żądania i zabrało je razem z nim.
    """
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for idx, text in enumerate(texts):
        length = len(text)
        if current and (size + length > max_chars or len(current) >= max_items):
            batches.append(current)
            current, size = [], 0
        current.append(idx)
        size += length
    if current:
        batches.append(current)
    return batches


async def _embed_texts(
    texts: list[str], *, max_chars: int, max_items: int
) -> list[Optional[list[float]]]:
    """Embedding wielu tekstów paczkami po znakach; ``None`` = slot bez wektora."""
    out: list[Optional[list[float]]] = [None] * len(texts)
    for chunk in _char_batches(texts, max_chars=max_chars, max_items=max_items):
        embeddings = await _voyage_embed_batch(
            [texts[i] for i in chunk], input_type="document"
        )
        if embeddings is None:
            logger.warning(
                "[reembed candidates] voyage batch of %s texts (%s chars) failed",
                len(chunk),
                sum(len(texts[i]) for i in chunk),
            )
            continue
        for k, i in enumerate(chunk):
            out[i] = embeddings[k] if k < len(embeddings) else None
    return out


async def _qdrant_point_hashes(collection: str) -> dict[int, tuple[str, str]]:
    """``id → (content_hash, embedding_model)`` z payloadu punktów kolekcji.

    Podstawa ``--resume``: punkt jest „gotowy”, gdy niesie hasz DOKŁADNIE tego
    tekstu, który zbudowałby ten bieg, i ten sam model. Sama obecność id (to
    robi ``--only-missing``) nie wystarcza przy wznawianiu budowy cienia —
    kandydat zmieniony w trakcie wielogodzinnej budowy miałby wektor ze starej
    treści.
    """
    from qdrant_client import QdrantClient  # noqa: PLC0415

    def _scroll() -> dict[int, tuple[str, str]]:
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        found: dict[int, tuple[str, str]] = {}
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=collection,
                limit=10_000,
                offset=offset,
                with_payload=["content_hash", "embedding_model"],
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                found[int(p.id)] = (
                    str(payload.get("content_hash") or ""),
                    str(payload.get("embedding_model") or ""),
                )
            if offset is None:
                break
        return found

    try:
        return await asyncio.to_thread(_scroll)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Cannot read Qdrant collection {collection!r} payloads for --resume "
            f"at {settings.QDRANT_HOST}:{settings.QDRANT_PORT}. "
            f"Original error: {exc}"
        ) from exc


def _ensure_candidate_collection(collection: str) -> None:
    """Załóż kolekcję kandydatów (cosine, ``VECTOR_SIZE``), jeśli jej nie ma."""
    from qdrant_client import QdrantClient  # noqa: PLC0415
    from qdrant_client.models import Distance, VectorParams  # noqa: PLC0415

    client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    existing = {c.name for c in client.get_collections().collections}
    if collection in existing:
        logger.info("[reembed] collection %r already exists", collection)
        return
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    logger.info("[reembed] collection %r created (dim=%s)", collection, VECTOR_SIZE)


async def _record_outbox_done(candidates: list) -> int:
    """Zapisz w outboxie „ten kandydat jest zaindeksowany aktualną treścią”.

    Wiersz ``done`` z ``indexed_hash = desired_hash`` — dokładnie to, co zapisuje
    worker po udanym upsercie (``process_event``). Reconciler dryfu czyta
    najnowszy taki wiersz; bez niego po przełączeniu schematu tekstu każdy
    kandydat z haszem v1 wyglądałby na dryf i poszedłby do ponownego embeddingu
    (~60 tys. wywołań Voyage za coś, co już jest w kolekcji).

    Hasz liczy ``index_outbox_service.desired_state`` — JEDNO źródło, więc
    porównanie reconcilera (``hashes_match``) trafi dokładnie. Wolno wołać
    WYŁĄCZNIE dla aktywnej pary (kolekcja, schemat) — pilnuje tego
    ``_resolve_candidate_plan``.

    Best-effort jak ``_mark_embedded``: wektor już jest w Qdrancie.
    """
    if not candidates:
        return 0
    from app.models.index_outbox import IndexOutboxEvent  # noqa: PLC0415
    from app.services import index_outbox_service as outbox  # noqa: PLC0415

    try:
        async with AsyncSessionLocal() as db:
            for c in candidates:
                st = outbox.desired_state(outbox.CANDIDATE, c)
                db.add(
                    IndexOutboxEvent(
                        entity_type=outbox.CANDIDATE,
                        entity_id=int(c.id),
                        entity_revision=st.revision,
                        desired_hash=st.desired_hash,
                        operation="upsert",
                        status="done",
                        indexed_hash=st.desired_hash,
                        indexed_revision=st.revision,
                    )
                )
            await db.commit()
        return len(candidates)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[reembed] vectors in Qdrant but outbox not recorded for %s ids: %s",
            len(candidates),
            exc,
        )
        return 0


async def _reembed_candidates(
    *,
    commit: bool,
    batch: int,
    limit: Optional[int],
    log_every: int,
    only_missing: bool = False,
    collection: Optional[str] = None,
    text_schema: str = "active",
    max_batch_chars: int = DEFAULT_MAX_BATCH_CHARS,
    resume: bool = False,
    record_outbox: bool = False,
    estimate: bool = False,
) -> tuple[int, int, int]:
    """Returns (processed, succeeded, failed). Batches Voyage calls (up to 128/req).

    ``succeeded`` liczy też kandydatów pominiętych przez ``--resume`` (wektor
    z tą samą treścią już jest) — osobno są raportowani w logu jako ``skipped``.

    ``estimate`` (tylko z ``--dry-run``): buduje teksty i liczy znaki tego, co
    poszłoby do Voyage (po ``--resume``), bez żadnego wywołania API — podstawa
    szacunku kosztu przed budową cienia.
    """
    plan = _resolve_candidate_plan(
        collection=collection, text_schema=text_schema, record_outbox=record_outbox
    )
    build_text = _candidate_text_builder(plan.text_schema)
    processed = succeeded = failed = skipped = recorded = 0

    # Ids first, rows later, one batch at a time. Loading whole ORM objects up
    # front pulled every `raw_cv_text` on the box into memory at once (~56k rows
    # on prod, 0.5-1.5 GB) — enough to OOM the container before the first Voyage
    # call went out.
    async with AsyncSessionLocal() as db:
        stmt = select(Candidate.id).order_by(Candidate.id.asc())
        # With --only-missing the cap is applied AFTER the set difference, so
        # `--limit 1000` means "a thousand candidates that need a vector".
        # Capping the DB query first would take the thousand lowest ids —
        # nearly all already indexed — and report ~0 work to do.
        if limit is not None and not only_missing:
            stmt = stmt.limit(limit)
        all_ids = [cid for (cid,) in (await db.execute(stmt)).all()]

    if only_missing:
        indexed = await _qdrant_point_ids(plan.collection)
        before = len(all_ids)
        all_ids = [cid for cid in all_ids if cid not in indexed]
        if limit is not None:
            all_ids = all_ids[:limit]
        logger.info(
            "[reembed candidates] --only-missing: %s of %s lack a vector "
            "(%s already indexed in Qdrant)",
            len(all_ids),
            before,
            len(indexed),
        )

    point_hashes: dict[int, tuple[str, str]] = {}
    if resume:
        point_hashes = await _qdrant_point_hashes(plan.collection)
        logger.info(
            "[reembed candidates] --resume: %s points in %r carry a content hash",
            len(point_hashes),
            plan.collection,
        )

    total = len(all_ids)
    logger.info(
        "Found %s candidates to re-embed (model=%s, collection=%s, text=%s, "
        "shadow=%s, record_outbox=%s, batch=%s, max_batch_chars=%s, commit=%s)",
        total,
        settings.VOYAGE_MODEL,
        plan.collection,
        plan.schema_stamp,
        plan.shadow,
        plan.record_outbox,
        batch,
        max_batch_chars,
        commit,
    )
    if not commit and not estimate:
        return total, 0, 0

    model_name = _voyage_model()
    est_texts = est_chars = est_max = est_requests = 0
    for i in range(0, total, batch):
        id_chunk = all_ids[i : i + batch]
        async with AsyncSessionLocal() as db:
            chunk = (
                (
                    await db.execute(
                        select(Candidate)
                        .where(Candidate.id.in_(id_chunk))
                        .order_by(Candidate.id.asc())
                    )
                )
                .scalars()
                .all()
            )
        texts = [build_text(c) for c in chunk]
        # Filter out blanks to align with embedding response.
        keep_idx = [j for j, t in enumerate(texts) if t and t.strip()]
        failed += len(chunk) - len(keep_idx)

        # --resume: punkt z haszem DOKŁADNIE tej treści i tym modelem jest gotowy.
        ready: list = []
        if resume:
            todo = []
            for j in keep_idx:
                c = chunk[j]
                if point_hashes.get(int(c.id)) == (_text_hash(texts[j]), model_name):
                    ready.append(c)
                else:
                    todo.append(j)
            keep_idx = todo
            skipped += len(ready)
            succeeded += len(ready)

        if not commit:
            lengths = [len(texts[j]) for j in keep_idx]
            est_texts += len(lengths)
            est_chars += sum(lengths)
            est_max = max([est_max, *lengths])
            est_requests += len(
                _char_batches(
                    [texts[j] for j in keep_idx],
                    max_chars=max_batch_chars,
                    max_items=batch,
                )
            )
            processed += len(chunk)
            continue

        points: list[dict] = []
        if keep_idx:
            keep_texts = [texts[j] for j in keep_idx]
            embeddings = await _embed_texts(
                keep_texts, max_chars=max_batch_chars, max_items=batch
            )
            for k, j in enumerate(keep_idx):
                emb = embeddings[k]
                c = chunk[j]
                if emb is None:
                    failed += 1
                    continue
                points.append(
                    dict(
                        id=int(c.id),
                        vector=emb,
                        # Bez "name" — parytet z embed_candidate (runda 2): nikt
                        # nie czyta go z payloadu, a PII w indeksie to koszt RODO.
                        payload={
                            "candidate_id": int(c.id),
                            "content_hash": _text_hash(texts[j]),
                            "embedding_model": model_name,
                            "competence_category": c.competence_category or "",
                            # Którym schematem tekstu policzono wektor — cień
                            # i aktywna kolekcja są rozróżnialne po samym punkcie.
                            "text_schema": plan.schema_stamp,
                        },
                    )
                )

        # Identyfikatory wyliczone PRZED `try`. W środku ta lista byłaby objęta
        # `except`, który raportuje wyłącznie „qdrant upsert failed” — więc błąd
        # budowania punktów (np. brak klucza "id" po refaktorze) zostałby
        # zaksięgowany jako awaria Qdranta i wysłał diagnozę w las.
        point_ids = [int(p["id"]) for p in points]
        upserted: list = []
        if points:
            try:
                await _bulk_upsert_qdrant(plan.collection, points)
                if not plan.shadow:
                    # Znacznik mówi „ma wektor w AKTYWNEJ kolekcji” — cień go
                    # nie dotyka, bo aktywna kolekcja nic nie zyskała.
                    await _mark_embedded(Candidate, point_ids)
                succeeded += len(points)
                by_id = {int(c.id): c for c in chunk}
                upserted = [by_id[pid] for pid in point_ids]
            except Exception as e:  # noqa: BLE001
                logger.warning("[reembed candidates] qdrant upsert failed: %s", e)
                failed += len(points)

        if plan.record_outbox:
            recorded += await _record_outbox_done(ready + upserted)

        processed += len(chunk)
        if processed // log_every > (processed - len(chunk)) // log_every:
            logger.info(
                "[reembed candidates] %s/%s (ok=%s, skipped=%s, fail=%s, outbox=%s)",
                processed,
                total,
                succeeded,
                skipped,
                failed,
                recorded,
            )

    if not commit:
        # ~3 znaki na token to typowy stosunek dla polsko-angielskich CV;
        # prawdziwe zużycie pokaże `usage.total_tokens` w odpowiedziach Voyage.
        logger.info(
            "[reembed candidates] ESTIMATE: %s texts to embed (%s skipped by "
            "--resume, %s blank), %s chars total, max %s chars/text, ~%s tokens "
            "(chars/3), %s Voyage requests at max_batch_chars=%s",
            est_texts,
            skipped,
            failed,
            est_chars,
            est_max,
            est_chars // 3,
            est_requests,
            max_batch_chars,
        )
        return processed, 0, 0

    logger.info(
        "[reembed candidates] DONE %s/%s (ok=%s, skipped=%s, fail=%s, outbox=%s)",
        processed,
        total,
        succeeded,
        skipped,
        failed,
        recorded,
    )
    return processed, succeeded, failed


async def _reembed_jobs(
    *,
    commit: bool,
    batch: int,
    limit: Optional[int],
    log_every: int,
    only_missing: bool = False,
) -> tuple[int, int, int]:
    """Same batched pattern as candidates."""
    processed = succeeded = failed = 0
    async with AsyncSessionLocal() as db:
        stmt = select(Job.id).order_by(Job.id.asc())
        # See `_reembed_candidates` — with --only-missing the cap applies after
        # the diff, so it means "N that need a vector".
        if limit is not None and not only_missing:
            stmt = stmt.limit(limit)
        all_ids = [jid for (jid,) in (await db.execute(stmt)).all()]

    if only_missing:
        indexed = await _qdrant_point_ids(_jobs_collection())
        before = len(all_ids)
        all_ids = [jid for jid in all_ids if jid not in indexed]
        if limit is not None:
            all_ids = all_ids[:limit]
        logger.info(
            "[reembed jobs] --only-missing: %s of %s lack a vector "
            "(%s already indexed in Qdrant)",
            len(all_ids),
            before,
            len(indexed),
        )

    total = len(all_ids)
    logger.info(
        "Found %s jobs to re-embed (model=%s, batch=%s, commit=%s)",
        total,
        settings.VOYAGE_MODEL,
        batch,
        commit,
    )
    if not commit:
        return total, 0, 0

    for i in range(0, total, batch):
        id_chunk = all_ids[i : i + batch]
        async with AsyncSessionLocal() as db:
            chunk = (
                (
                    await db.execute(
                        select(Job).where(Job.id.in_(id_chunk)).order_by(Job.id.asc())
                    )
                )
                .scalars()
                .all()
            )
        texts = [_build_job_text(j) for j in chunk]
        keep_idx = [k for k, t in enumerate(texts) if t and t.strip()]
        if not keep_idx:
            processed += len(chunk)
            failed += len(chunk)
            continue

        keep_texts = [texts[k] for k in keep_idx]
        embeddings = await _voyage_embed_batch(keep_texts, input_type="document")
        if embeddings is None:
            processed += len(chunk)
            failed += len(chunk)
            logger.warning(
                "[reembed jobs] batch %s-%s failed entirely", i, i + len(chunk)
            )
            continue

        points: list[dict] = []
        for k, j in enumerate(keep_idx):
            emb = embeddings[k] if k < len(embeddings) else None
            job = chunk[j]
            if emb is None:
                failed += 1
                continue
            payload = {
                "job_id": int(job.id),
                "title": job.title or "",
                "client_id": job.client_id,
                "industry": job.industry or "",
            }
            train_name = getattr(job, "train_name", None)
            if train_name:
                payload["train_name"] = train_name
            points.append(dict(id=int(job.id), vector=emb, payload=payload))

        # Identyfikatory wyliczone PRZED `try`. W środku ta lista byłaby objęta
        # `except`, który raportuje wyłącznie „qdrant upsert failed” — więc błąd
        # budowania punktów (np. brak klucza "id" po refaktorze) zostałby
        # zaksięgowany jako awaria Qdranta i wysłał diagnozę w las.
        point_ids = [int(p["id"]) for p in points]
        try:
            await _bulk_upsert_qdrant(_jobs_collection(), points)
            await _mark_embedded(Job, point_ids)
            succeeded += len(points)
        except Exception as e:  # noqa: BLE001
            logger.warning("[reembed jobs] qdrant upsert failed: %s", e)
            failed += len(points)

        processed += len(chunk)
        if processed // log_every > (processed - len(chunk)) // log_every:
            logger.info(
                "[reembed jobs] %s/%s (ok=%s, fail=%s)",
                processed,
                total,
                succeeded,
                failed,
            )

    logger.info(
        "[reembed jobs] DONE %s/%s (ok=%s, fail=%s)",
        processed,
        total,
        succeeded,
        failed,
    )
    return processed, succeeded, failed


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--target", choices=["candidates", "jobs", "all"], default="all")
    p.add_argument(
        "--ensure-collection",
        action="store_true",
        help=(
            "utwórz kolekcje z init_qdrant_collection() przed biegiem — "
            "potrzebne przy budowie kolekcji side-by-side "
            "(QDRANT_COLLECTION wskazuje nową, jeszcze nieistniejącą)"
        ),
    )
    p.add_argument(
        "--commit", action="store_true", help="actually call Voyage + upsert Qdrant"
    )
    p.add_argument("--dry-run", action="store_true", help="count only, no API calls")
    p.add_argument(
        "--batch",
        type=int,
        default=128,
        help="Voyage batch size (max 128, default 128 for ~390 calls / 50K candidates)",
    )
    p.add_argument(
        "--limit", type=int, default=None, help="cap number of entities (testing)"
    )
    p.add_argument(
        "--log-every", type=int, default=100, help="progress log every N entities"
    )
    p.add_argument(
        "--only-missing",
        action="store_true",
        help=(
            "Embed only entities absent from Qdrant (set difference against a "
            "scroll of the collection). Use this to close an indexing gap: a "
            "full re-embed of every row costs the same Voyage spend as the "
            "original import and is only needed after a model change."
        ),
    )
    p.add_argument(
        "--prune-orphans",
        action="store_true",
        help=(
            "Delete points whose row no longer exists in the database. These "
            "hold the person's name and CV text after the record was removed, "
            "so erasure never reached them. Runs instead of embedding; honours "
            "--dry-run. Check the reported count before committing."
        ),
    )
    p.add_argument(
        "--collection",
        default=None,
        help=(
            "kolekcja docelowa KANDYDATÓW (domyślnie aktywna: QDRANT_COLLECTION). "
            "Inna niż aktywna = budowa cienia: bez znacznika embedding_id i bez "
            "outboxu. Tylko z --target candidates."
        ),
    )
    p.add_argument(
        "--text-schema",
        choices=TEXT_SCHEMAS,
        default="active",
        help=(
            "schemat tekstu kandydata; `active` = dyspozytor aplikacji (flagi "
            "AI_TEXT_SCHEMA_*). Jawny v3/v3-nonotes nie zależy od env — tak "
            "buduje się cień w kontenerze produkcji. Tylko z --target candidates."
        ),
    )
    p.add_argument(
        "--max-batch-chars",
        type=int,
        default=DEFAULT_MAX_BATCH_CHARS,
        help=(
            "sufit łącznej liczby znaków w jednym wywołaniu Voyage (limit "
            "tokenów żądania; długie teksty v3 w paczce 128 go przekraczają)"
        ),
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help=(
            "pomiń kandydatów, których punkt w kolekcji docelowej ma już "
            "content_hash tej samej treści i ten sam embedding_model — "
            "wznowienie po restarcie kontenera i dogonienie zmian z okresu budowy"
        ),
    )
    p.add_argument(
        "--record-outbox",
        action="store_true",
        help=(
            "zapisz w outboxie indeksu wiersz `done` z indexed_hash = desired_hash "
            "dla każdego kandydata z aktualnym wektorem (także pominiętego przez "
            "--resume). WYŁĄCZNIE aktywna kolekcja + aktywny schemat — dla cienia "
            "odmowa. Używane raz, po przełączeniu env na nowy schemat."
        ),
    )
    p.add_argument(
        "--estimate",
        action="store_true",
        help=(
            "tylko z --dry-run --target candidates: zbuduj teksty i policz znaki "
            "oraz liczbę żądań Voyage (bez wywołań API) — szacunek kosztu"
        ),
    )
    args = p.parse_args(argv)
    if args.estimate and not (args.dry_run and args.target == "candidates"):
        p.error("--estimate działa tylko z --dry-run --target candidates")
    if not args.commit and not args.dry_run:
        p.error("must pass --commit or --dry-run")
    if args.commit and args.dry_run:
        p.error("--commit and --dry-run are mutually exclusive")
    candidate_only = (
        args.collection is not None
        or args.text_schema != "active"
        or args.resume
        or args.record_outbox
    )
    if candidate_only and args.target != "candidates":
        p.error(
            "--collection/--text-schema/--resume/--record-outbox dotyczą "
            "wyłącznie kandydatów — użyj --target candidates"
        )
    if args.record_outbox and args.prune_orphans:
        p.error("--record-outbox nie łączy się z --prune-orphans")
    if args.max_batch_chars < 1000:
        p.error("--max-batch-chars musi być co najmniej 1000")
    if not 1 <= args.batch <= 128:
        p.error("--batch musi być w zakresie 1-128 (limit Voyage)")
    return args


async def _main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.ensure_collection:
        from app.services.embedding_service import init_qdrant_collection

        if args.collection:
            _ensure_candidate_collection(args.collection)
        else:
            init_qdrant_collection()

    if args.prune_orphans:
        # Runs INSTEAD of embedding: deleting and writing are different risks,
        # and mixing them in one invocation makes the dry-run output ambiguous.
        if args.target in ("candidates", "all"):
            await _prune_orphans(
                entity="candidates",
                collection=args.collection or _collection(),
                id_column=Candidate.id,
                commit=args.commit,
            )
        if args.target in ("jobs", "all"):
            await _prune_orphans(
                entity="jobs",
                collection=_jobs_collection(),
                id_column=Job.id,
                commit=args.commit,
            )
        return 0

    if args.target in ("candidates", "all"):
        await _reembed_candidates(
            commit=args.commit,
            batch=args.batch,
            limit=args.limit,
            log_every=args.log_every,
            only_missing=args.only_missing,
            collection=args.collection,
            text_schema=args.text_schema,
            max_batch_chars=args.max_batch_chars,
            resume=args.resume,
            record_outbox=args.record_outbox,
            estimate=args.estimate,
        )
    if args.target in ("jobs", "all"):
        await _reembed_jobs(
            commit=args.commit,
            batch=args.batch,
            limit=args.limit,
            log_every=args.log_every,
            only_missing=args.only_missing,
        )
    return 0


def main() -> int:
    return asyncio.run(_main(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
