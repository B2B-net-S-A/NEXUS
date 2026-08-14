"""Recover ``candidates.raw_cv_text`` from CV files already in object storage.

Measured on prod 2026-08-10: 14 509 candidates hold a CV file whose text was
never extracted. That text is the input to everything downstream — the embedding
blob, the structured field parse, the passage index — so recovering it is the
cheapest data win available and it costs nothing but CPU.

Lives in ``app/services`` rather than ``scripts/`` so an API layer can call it
without the ``sys.path`` hack; ``scripts/backfill_cv_text.py`` is a thin CLI over
this module.

Scope note, measured rather than assumed: every recoverable candidate reaches
their file through ``candidates.cv_storage_key``. Zero rows need the
``candidate_documents`` / legacy-bytea fallbacks, so this module deliberately
does not implement them — see ``docs/`` for the query. Add them the day the
measurement says otherwise, not before.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import func, or_, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.services.cv_text_extractor import UnsupportedCvFormat, extract_text
from app.services.object_storage import download_cv, is_available

logger = logging.getLogger("cv_text_backfill")

# Anything at or below this is "no usable text". The original scope was
# `IS NULL OR = ''`; widening it to a length threshold adds 30 rows on prod
# (candidates whose extraction produced a few useless characters). Small, but
# those rows were invisible to every previous run and would stay invisible.
MIN_USEFUL_TEXT_CHARS = 200

# Extensions we can actually read. `.doc` is deliberately absent: the image ships
# neither libreoffice nor antiword, so python-docx raises on binary OLE2 every
# time. Skipping by extension avoids thousands of pointless S3 GETs and OCR runs.
_READABLE_EXTENSIONS = (".pdf", ".docx", ".txt")
_KNOWN_EXTENSIONS = _READABLE_EXTENSIONS + (".doc",)

_EXTRACTION_MARKER_KEY = "_cv_text_extraction"
# Outcomes that will not change on a retry. Rows carrying one of these are
# skipped, so a rerun spends its time on the unknowns instead of re-burning OCR
# on the same corrupt PDFs. `error` and `download_failed` are NOT terminal —
# those are worth another attempt.
_TERMINAL_OUTCOMES = frozenset(
    {"legacy_doc", "unsupported_format", "junk", "empty", "no_improvement"}
)


@dataclass
class BackfillStats:
    """Outcome taxonomy, not a single success rate.

    The historical run reported "77,5% extracted" and nothing else, which cannot
    answer the one question that decides the next step: is the remainder corrupt
    PDFs (nothing to do) or legacy `.doc` (fixable by adding libreoffice)?
    """

    scanned: int = 0
    extracted: int = 0
    improved: int = 0
    empty: int = 0
    # Distinct from `empty`: the file DID yield text, we simply already hold
    # something longer. Folding the two together would hide whether a bucket
    # means "nothing readable in the file" or "nothing better than we have" —
    # the exact conflation this taxonomy exists to prevent.
    no_improvement: int = 0
    junk: int = 0
    legacy_doc: int = 0
    unsupported_format: int = 0
    no_file: int = 0
    download_failed: int = 0
    error: int = 0
    skipped_terminal: int = 0
    reindex_enqueued: int = 0
    # False when object storage is unconfigured. Without it the caller cannot
    # tell "nothing to do" from "could not even look" — both leave scanned=0.
    storage_available: bool = True
    candidate_ids_written: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items() if k != "candidate_ids_written"}
        data["written"] = len(self.candidate_ids_written)
        return data


def _extension_of(filename: str | None, storage_key: str) -> str:
    for src in (filename or "", storage_key or ""):
        _, ext = os.path.splitext(src)
        if ext.lower() in _KNOWN_EXTENSIONS:
            return ext.lower()
    return ".pdf"  # most stored files are PDFs and the extractor sniffs anyway


def looks_like_junk(text: str) -> bool:
    """pdfplumber's CID-glyph fallback: '(cid:42)(cid:7)...'.

    Emitted when a PDF uses a font without a Unicode CMap. The result is
    unreadable and would only pollute embeddings, so it counts as no text at all.
    """
    if not text or len(text) < 100:
        return False
    cid_chars = text.count("(cid:")
    return (cid_chars * 8) / len(text) > 0.3


def sanitize(text: str) -> str:
    """Drop NUL and control characters that Postgres TEXT rejects."""
    if not text:
        return ""
    return "".join(c for c in text if c in "\t\n\r" or c >= " ")


@dataclass(frozen=True)
class ExtractionResult:
    outcome: str
    text: str = ""


def extract_one(storage_key: str, filename: str | None) -> ExtractionResult:
    """Download and extract one CV. Blocking — call via ``asyncio.to_thread``.

    Returns a classified outcome rather than a bare string so the caller can
    distinguish "this file will never yield text" from "try again later".
    """
    ext = _extension_of(filename, storage_key)
    if ext == ".doc":
        return ExtractionResult("legacy_doc")

    try:
        blob = download_cv(storage_key)
    except Exception as exc:  # noqa: BLE001 — network/storage errors are retryable
        logger.warning("[download] %s: %s", storage_key, exc)
        return ExtractionResult("download_failed")
    if not blob:
        return ExtractionResult("no_file")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        text = extract_text(path, filename or os.path.basename(storage_key))
    except UnsupportedCvFormat:
        return ExtractionResult("unsupported_format")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[extract] %s: %s", storage_key, exc)
        return ExtractionResult("error")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if looks_like_junk(text):
        return ExtractionResult("junk")
    cleaned = sanitize(text).strip()
    if not cleaned:
        return ExtractionResult("empty")
    return ExtractionResult("extracted", cleaned)


def _pending_candidates_stmt(
    limit: Optional[int],
    *,
    random_sample: bool = False,
    retry_outcomes: frozenset[str] = frozenset(),
):
    """Rows whose CV text is missing or too short to be useful.

    ``retry_outcomes`` wpuszcza z powrotem wiersze z WYBRANYMI terminalnymi
    znacznikami. Powstało z pomiaru 2026-08-14: losowy pilotaż 40 wierszy
    `empty` odzyskał 15 CV (37,5%) — klasa przestała być terminalna po bumpach
    zależności ekstraktorów, ale znaczniki z 10.08 trwale wykluczały ponowną
    próbę. Czoło listy po id kłamie w drugą stronę (najstarsze importy to
    hasła/korupcje) — stąd pomiar na losowej próbie, nie od początku.

    Ordered by id by default so a full run is deterministic and resumable — a row
    that gains text drops out of the predicate, and hopeless ones carry a marker.

    ``random_sample`` exists because ordering by id makes ``--limit`` lie about
    the population. Measured 2026-08-10: the first 30 rows returned 50% legacy
    ``.doc`` (oldest Traffit imports cluster at low ids), while the real backlog
    is 72% ``.pdf`` / 27% ``.docx`` and only 0.9% ``.doc``. Sizing the work off
    the id-ordered sample would have argued for adding LibreOffice to the image
    to rescue 133 people. Use it for any estimate; never for the real run.
    """
    # Terminal rows are excluded in SQL, not in the loop. Skipping them in Python
    # was not enough: a row that can never yield text keeps matching the
    # predicate, so `ORDER BY id LIMIT N` kept re-selecting the same failures and
    # each successive tranche spent more of its budget re-reading them. Measured
    # on the first production run: 2 494 of 2 500 rows scanned were already-marked
    # skips, i.e. the tranche did ~0.2% useful work.
    marker_outcome = Candidate.cv_extracted_data[_EXTRACTION_MARKER_KEY][
        "outcome"
    ].astext
    stmt = select(Candidate.id, Candidate.cv_storage_key, Candidate.cv_filename).where(
        Candidate.cv_storage_key.is_not(None),
        Candidate.cv_storage_key != "",
        or_(
            Candidate.raw_cv_text.is_(None),
            func.char_length(func.btrim(Candidate.raw_cv_text))
            <= MIN_USEFUL_TEXT_CHARS,
        ),
        or_(
            marker_outcome.is_(None),
            marker_outcome.notin_(sorted(_TERMINAL_OUTCOMES - retry_outcomes)),
        ),
    )
    stmt = stmt.order_by(func.random() if random_sample else Candidate.id.asc())
    return stmt.limit(limit) if limit is not None else stmt


def _terminal_marker(candidate: Candidate) -> Optional[str]:
    extracted = candidate.cv_extracted_data
    if not isinstance(extracted, dict):
        return None
    marker = extracted.get(_EXTRACTION_MARKER_KEY)
    if not isinstance(marker, dict):
        return None
    outcome = marker.get("outcome")
    return outcome if outcome in _TERMINAL_OUTCOMES else None


def _record_marker(candidate: Candidate, outcome: str, chars: int) -> None:
    # Same column, same trap as `_manual_lock`: a non-empty list is truthy, so
    # `or {}` does not catch it and `dict(<list>)` raises. `_terminal_marker`
    # above already reads this column with an `isinstance` guard; writing it
    # needs the same. A non-dict value carries no marker to preserve, so it is
    # replaced rather than merged.
    existing = candidate.cv_extracted_data
    extracted = dict(existing) if isinstance(existing, dict) else {}
    extracted[_EXTRACTION_MARKER_KEY] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "outcome": outcome,
        "chars": chars,
    }
    candidate.cv_extracted_data = extracted


async def run_backfill(
    *,
    commit: bool,
    limit: Optional[int] = None,
    batch_size: int = 8,
    log_every: int = 200,
    enqueue_reindex: bool = True,
    random_sample: bool = False,
    retry_outcomes: frozenset[str] = frozenset(),
    progress: Optional[Callable[[BackfillStats], None]] = None,
) -> BackfillStats:
    """Extract text for every candidate whose stored CV was never read.

    ``enqueue_reindex`` closes a loop that was open until now: the previous
    implementation wrote ``raw_cv_text`` and told nobody, so 7 893 historically
    recovered CVs sat in Postgres while their Qdrant vectors were still built
    from an empty blob. Recovering text without reindexing produces data the
    search cannot see, which is most of the point.
    """
    stats = BackfillStats()
    if not is_available():
        logger.error("Object storage not configured — nothing to download from")
        stats.storage_available = False
        return stats

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                _pending_candidates_stmt(
                    limit, random_sample=random_sample, retry_outcomes=retry_outcomes
                )
            )
        ).all()

    total = len(rows)
    stats.scanned = total
    logger.info(
        "candidates with a stored CV but no usable text: %s (commit=%s)", total, commit
    )
    if total == 0:
        return stats

    for start in range(0, total, batch_size):
        chunk = rows[start : start + batch_size]
        results = await asyncio.gather(
            *[asyncio.to_thread(extract_one, key, name) for _, key, name in chunk],
            return_exceptions=True,
        )

        async with AsyncSessionLocal() as db:
            for (cid, _key, _name), result in zip(chunk, results, strict=True):
                if isinstance(result, BaseException):
                    stats.error += 1
                    continue

                candidate = await db.scalar(
                    select(Candidate).where(Candidate.id == cid)
                )
                if candidate is None:
                    continue
                if _terminal_marker(candidate):
                    stats.skipped_terminal += 1
                    continue

                if result.outcome != "extracted":
                    setattr(
                        stats, result.outcome, getattr(stats, result.outcome, 0) + 1
                    )
                    if commit:
                        _record_marker(candidate, result.outcome, 0)
                    continue

                previous = (candidate.raw_cv_text or "").strip()
                # Monotonic write. Widening the scope to "short text" means we
                # now revisit rows that already hold something; without this a
                # worse extraction could replace a better one and the run would
                # stop being safe to repeat.
                if len(result.text) <= len(previous):
                    stats.no_improvement += 1
                    if commit:
                        _record_marker(candidate, "no_improvement", len(previous))
                    continue

                if previous:
                    stats.improved += 1
                else:
                    stats.extracted += 1
                stats.candidate_ids_written.append(cid)
                if commit:
                    candidate.raw_cv_text = result.text
                    _record_marker(candidate, "extracted", len(result.text))

            if commit:
                await db.commit()

        done = start + len(chunk)
        if done % log_every < batch_size or done >= total:
            logger.info("[%s/%s] %s", done, total, stats.as_dict())
            if progress is not None:
                progress(stats)

    if commit and enqueue_reindex and stats.candidate_ids_written:
        stats.reindex_enqueued = await _enqueue_reindex(stats.candidate_ids_written)

    logger.info("DONE %s", stats.as_dict())
    return stats


async def _enqueue_reindex(candidate_ids: list[int]) -> int:
    """Mark recovered candidates for re-embedding.

    Bulk-enqueued at the end rather than per row on purpose: with
    ``AI_INDEX_OUTBOX_ENABLED`` off — the default — ``schedule_or_embed_candidate``
    embeds inline, which would turn this into 14 509 blocking Voyage calls
    interleaved with OCR. ``record_bulk_reindex`` writes outbox rows and lets the
    worker (or the drift reconciler) drain them at its own pace.
    """
    from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex

    try:
        async with AsyncSessionLocal() as db:
            enqueued = await record_bulk_reindex(db, CANDIDATE, candidate_ids)
            await db.commit()
        logger.info("enqueued %s candidates for re-embedding", enqueued)
        return enqueued
    except Exception as exc:  # noqa: BLE001 — never lose recovered text over this
        logger.warning(
            "reindex enqueue failed for %s candidates: %s — text is saved, run "
            "`reembed_collections --only-missing` or wait for the drift reconciler",
            len(candidate_ids),
            exc,
        )
        return 0
