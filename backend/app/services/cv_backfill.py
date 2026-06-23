"""Backfill name/contact data for candidates imported without a name.

The Traffit importer stores ``name="?"`` / ``lastname="?"`` when the source
record has neither a name nor a usable email, and downloads the CV to object
storage **without parsing it**. This module recovers the missing data from the
stored CV using the same ``parse_cv`` → ``_apply_cv_enrichment`` path as the
manual upload flow, with a conservative CV-filename fallback for the name.

Two entry points share one core (``enrich_candidate_from_cv_bytes``):
  * ``backfill_missing_names`` — bulk pass over existing ``"?"`` rows (admin
    trigger + a phase appended to every Traffit sync so it never recurs).
  * ``backfill_candidate_from_stored_cv`` — single candidate, downloads the CV.

Idempotent and safe: only blank/placeholder fields are filled (see
``app.services.cv_enrichment``); a real value is never overwritten, so the job
can be re-run freely and stops touching a row once its name is resolved.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.services.cv_enrichment import _CV_PLACEHOLDER_NAMES, _apply_cv_enrichment

logger = logging.getLogger(__name__)

# Tokens that appear in CV filenames but are not part of a person's name.
_FILENAME_NOISE = frozenset(
    {
        "cv",
        "resume",
        "resmue",
        "życiorys",
        "zyciorys",
        "en",
        "eng",
        "pl",
        "pol",
        "de",
        "ger",
        "fin",
        "final",
        "finalna",
        "ostateczne",
        "updated",
        "update",
        "new",
        "nowy",
        "copy",
        "kopia",
        "version",
        "ver",
        "doc",
        "docx",
        "pdf",
        "profil",
        "profile",
    }
)

# A name token: letters (incl. Polish/diacritics) plus internal hyphen/apostrophe.
_NAME_TOKEN_RE = re.compile(r"^[^\W\d_]{2,}(?:[-'][^\W\d_]+)*$", re.UNICODE)
# Split a camelCase blob ("VugarSuleymanov") into ["Vugar", "Suleymanov"].
_CAMEL_RE = re.compile(r"[A-ZŁŚŻŹĆĄĘÓŃ][^\sA-ZŁŚŻŹĆĄĘÓŃ]+")


def _titlecase_token(token: str) -> str:
    """Title-case an all-lower / all-upper token; leave mixed case as-is."""
    if token.islower() or token.isupper():
        return token[:1].upper() + token[1:].lower()
    return token


def name_from_filename(filename: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Best-effort (first, last) from a CV filename.

    Conservative by design — only returns a name when exactly two clean tokens
    survive noise filtering, or a single camelCase blob splits cleanly into two.
    Returns ``(None, None)`` for ambiguous filenames (e.g. "CV_fin.pdf") rather
    than guessing garbage. Used only as a fallback when CV parsing finds no name.
    """
    if not filename:
        return None, None
    stem = os.path.splitext(filename)[0]
    # Drop parenthetical chunks like "(1)" / "(final)" then normalise separators.
    stem = re.sub(r"\([^)]*\)", " ", stem)
    stem = re.sub(r"[_.\-]+", " ", stem)

    clean = [
        tok
        for tok in stem.split()
        if tok and tok.lower() not in _FILENAME_NOISE and _NAME_TOKEN_RE.match(tok)
    ]

    # A single surviving token may be a camelCase blob ("VugarSuleymanov") —
    # split it into two name parts when that yields exactly two clean halves.
    if len(clean) == 1:
        parts = _CAMEL_RE.findall(clean[0])
        if len(parts) == 2 and all(p.lower() not in _FILENAME_NOISE for p in parts):
            clean = parts

    if len(clean) >= 2:
        return _titlecase_token(clean[0]), _titlecase_token(clean[1])
    return None, None


def _name_resolved(candidate: Candidate) -> bool:
    """True when the candidate now has at least a real first name."""
    name = (candidate.name or "").strip()
    return bool(name) and name not in _CV_PLACEHOLDER_NAMES


async def _extract_text_from_bytes(cv_bytes: bytes, filename: Optional[str]) -> str:
    """Write bytes to a temp file and run the blocking extractor off-loop."""
    from app.services import cv_text_extractor

    safe_name = filename or "cv.pdf"
    ext = os.path.splitext(safe_name)[1] or ".pdf"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        tmp.write(cv_bytes)
        tmp.flush()
        tmp.close()
        return await asyncio.to_thread(
            cv_text_extractor.extract_text, tmp.name, safe_name
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


async def enrich_candidate_from_cv_bytes(
    db: AsyncSession,
    candidate: Candidate,
    cv_bytes: Optional[bytes],
    filename: Optional[str],
    *,
    prefer_llm: bool = True,
) -> dict[str, Any]:
    """Core: text-extract + parse a CV blob and fold it into ``candidate``.

    Does NOT commit — the caller owns the transaction. Never raises on
    extraction/parse failure: those degrade to the filename fallback so a
    nameless row can still be partially resolved.
    """
    from app.services.cv_parser import parse_cv

    result: dict[str, Any] = {
        "text_extracted": False,
        "parsed": False,
        "name_source": None,
        "resolved": False,
    }

    raw_text: Optional[str] = None
    if cv_bytes:
        try:
            raw_text = await _extract_text_from_bytes(cv_bytes, filename)
        except Exception as e:  # noqa: BLE001 — extraction is best-effort
            logger.info(
                "[cv_backfill] text extraction failed cand=%s file=%s: %s",
                candidate.id,
                filename,
                e,
            )

    parsed: dict[str, Any] = {}
    if raw_text and raw_text.strip():
        candidate.raw_cv_text = raw_text
        result["text_extracted"] = True
        try:
            parsed = await parse_cv(raw_text, prefer_llm=prefer_llm) or {}
            result["parsed"] = True
            if parsed.get("first_name"):
                result["name_source"] = "cv"
        except Exception as e:  # noqa: BLE001 — parse is best-effort
            logger.warning("[cv_backfill] parse_cv failed cand=%s: %s", candidate.id, e)

    # Fallback: derive the name from the filename when the CV gave us nothing.
    if not (parsed.get("first_name") and parsed.get("last_name")):
        f_first, f_last = name_from_filename(filename)
        if f_first and not parsed.get("first_name"):
            parsed["first_name"] = f_first
            result["name_source"] = result["name_source"] or "filename"
        if f_last and not parsed.get("last_name"):
            parsed["last_name"] = f_last
            result["name_source"] = result["name_source"] or "filename"

    _apply_cv_enrichment(candidate, parsed)
    result["resolved"] = _name_resolved(candidate)
    return result


async def backfill_candidate_from_stored_cv(
    db: AsyncSession,
    candidate: Candidate,
    *,
    prefer_llm: bool = True,
) -> dict[str, Any]:
    """Download a candidate's stored CV (object storage / legacy bytea) and enrich."""
    from app.services import object_storage

    cv_bytes: Optional[bytes] = None
    if candidate.cv_storage_key:
        try:
            cv_bytes = await asyncio.to_thread(
                object_storage.download_cv, candidate.cv_storage_key
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[cv_backfill] download failed cand=%s key=%s: %s",
                candidate.id,
                candidate.cv_storage_key,
                e,
            )
    elif candidate.cv_file_content:
        cv_bytes = candidate.cv_file_content

    return await enrich_candidate_from_cv_bytes(
        db, candidate, cv_bytes, candidate.cv_filename, prefer_llm=prefer_llm
    )


async def backfill_missing_names(
    db: AsyncSession,
    *,
    limit: Optional[int] = None,
    since: Optional[datetime] = None,
    dry_run: bool = False,
    prefer_llm: bool = True,
    progress: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Bulk-enrich Traffit candidates whose name/lastname is still ``"?"``.

    Commits per candidate so a long run is resumable and partial progress
    survives a container restart. ``since`` scopes to recently-touched rows
    (used by the sync prevention phase); omit it for a full backfill.
    """
    since_clause = "AND updated_at >= :since" if since is not None else ""
    limit_clause = "LIMIT :limit" if limit is not None else ""
    params: dict[str, Any] = {}
    if since is not None:
        params["since"] = since
    if limit is not None:
        params["limit"] = limit

    rows = await db.execute(
        text(
            f"""
            SELECT id FROM candidates
            WHERE external_source = 'traffit'
              AND (name = '?' OR lastname = '?')
              {since_clause}
            ORDER BY id
            {limit_clause}
            """
        ),
        params,
    )
    ids = [r.id for r in rows]

    stats: dict[str, Any] = {
        "total": len(ids),
        "processed": 0,
        "resolved": 0,
        "unresolved": 0,
        "errors": 0,
    }
    if progress is not None:
        progress.update(stats)

    if dry_run or not ids:
        return stats

    for cand_id in ids:
        candidate = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        if candidate is None:
            continue
        try:
            await backfill_candidate_from_stored_cv(
                db, candidate, prefer_llm=prefer_llm
            )
            await db.commit()
            if _name_resolved(candidate):
                stats["resolved"] += 1
            else:
                stats["unresolved"] += 1
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            stats["errors"] += 1
            logger.warning("[cv_backfill] candidate %s failed: %s", cand_id, e)
        stats["processed"] += 1
        if progress is not None:
            progress.update(stats)
        if stats["processed"] % 25 == 0:
            logger.info(
                "[cv_backfill] progress %d/%d resolved=%d errors=%d",
                stats["processed"],
                stats["total"],
                stats["resolved"],
                stats["errors"],
            )

    logger.info("[cv_backfill] done: %s", stats)
    return stats
