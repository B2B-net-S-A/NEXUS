"""Bramka tożsamości dla plików CV z importu Traffita (09.11.2026).

Pomiar z kopii produkcji: bramka widziała 157 z 84 576 plików CV z Traffita, więc
cudze CV stało jako bieżące i kopiowało się na etapy. Bieg czyta tylko pliki,
przy których jest powód do wątpliwości:

* tekst CV w profilu nie ma ani imienia, ani nazwiska osoby,
* wskaźnik CV ma już ocenę „inna osoba, bez wyroku”,
* profil jest na liście `--candidate-ids-file` (np. identyczny plik pod inną osobą).

Uruchomienie (w kontenerze backendu, po wdrożeniu, jeden proces)::

    python -m app.cli.traffit_cv_identity_review
    python -m app.cli.traffit_cv_identity_review --apply [--limit N]

Bez `--apply` to próba: liczy pliki i nie woła modelu. Bieg nie wpisuje faktów
do profilu i niczego nie wrzuca do kwarantanny (`hold_mismatch_for_review`), bo
po samej nazwie nie da się odróżnić własnego CV od cudzego. Plik z oceną „inna
osoba” dostaje ostrzeżenie w podglądzie, a decyzję podejmuje człowiek. Wynik to
liczby i id, bez nazwisk. Plik z oceną nie wraca do kolejnego biegu, więc
przerwany bieg wystarczy uruchomić ponownie.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer
from starlette.concurrency import run_in_threadpool

from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.candidate_source_identity_review import (
    CandidateSourceIdentityReview,
)
from app.services import object_storage
from app.services.ai_models import model_for
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.candidate_identity_quarantine import (
    record_detected_identity,
    review_names_another_person,
)
from app.services.cv_backfill import _extract_text_from_bytes
from app.services.cv_field_backfill import MIN_CV_CHARS, SLEEP_BETWEEN_CALLS_S
from app.services.cv_parser import normalize_cv_output, parse_cv_with_claude
from app.services.cv_source import current_cv_filters
from app.services.llm_prompts import CV_ENRICHMENT

logger = logging.getLogger(__name__)

PROVENANCE = "cv_parser:traffit_file_review"
_MIN_NAME_CHARS = 3
_MIN_TEXT_CHARS = 400


@dataclass(frozen=True)
class Target:
    document_id: int
    candidate_id: int


def _folded(column: Any) -> Any:
    return func.translate(func.lower(column), "ąćęłńóśźż", "acelnoszz")


def _cv_text_without_the_name() -> Any:
    text = _folded(Candidate.raw_cv_text)
    return and_(
        func.length(Candidate.raw_cv_text) > _MIN_TEXT_CHARS,
        func.length(Candidate.name) >= _MIN_NAME_CHARS,
        func.length(Candidate.lastname) >= _MIN_NAME_CHARS,
        func.strpos(text, _folded(Candidate.name)) == 0,
        func.strpos(text, _folded(Candidate.lastname)) == 0,
    )


async def _pointer_doubt_candidate_ids(db: AsyncSession) -> set[int]:
    rows = await db.execute(
        select(
            CandidateSourceIdentityReview.candidate_id,
            CandidateSourceIdentityReview.decision,
            CandidateSourceIdentityReview.evidence,
        ).where(
            CandidateSourceIdentityReview.source_kind == "legacy_cv",
            CandidateSourceIdentityReview.decision == "inconclusive",
            CandidateSourceIdentityReview.override_at.is_(None),
        )
    )
    return {
        row.candidate_id
        for row in rows
        if review_names_another_person(row.decision, row.evidence or {})
    }


async def select_targets(
    db: AsyncSession, *, candidate_ids: Sequence[int] = ()
) -> list[Target]:
    """Pliki CV z Traffita bez oceny bramki, przy których jest powód do wątpliwości."""

    listed = set(candidate_ids) | await _pointer_doubt_candidate_ids(db)
    reviewed = exists().where(
        CandidateSourceIdentityReview.candidate_id == CandidateDocument.candidate_id,
        CandidateSourceIdentityReview.source_kind == "document",
        CandidateSourceIdentityReview.source_id == CandidateDocument.id,
    )
    rows = await db.execute(
        select(CandidateDocument.id, CandidateDocument.candidate_id)
        .join(Candidate, Candidate.id == CandidateDocument.candidate_id)
        .where(
            CandidateDocument.external_source == "traffit",
            func.lower(CandidateDocument.filename).regexp_match(r"\.(pdf|docx?)$"),
            *current_cv_filters(),
            ~reviewed,
            or_(Candidate.id.in_(listed), _cv_text_without_the_name()),
        )
        .order_by(CandidateDocument.id)
    )
    return [Target(row.id, row.candidate_id) for row in rows]


async def _document_text(db: AsyncSession, document_id: int) -> str:
    document = await db.scalar(
        select(CandidateDocument)
        .options(undefer(CandidateDocument.file_content))
        .where(CandidateDocument.id == document_id)
    )
    if document is None:
        return ""
    content = (
        await run_in_threadpool(object_storage.download_cv, document.storage_key)
        if document.storage_key
        else document.file_content
    )
    if not content:
        return ""
    return await _extract_text_from_bytes(bytes(content), document.filename) or ""


async def _review_target(
    db: AsyncSession, target: Target, model: str, stats: dict[str, Any]
) -> None:
    text = await _document_text(db, target.document_id)
    if len(text.strip()) < MIN_CV_CHARS:
        stats["no_text"] += 1
        return
    async with ai_feature(db, AIFeatureKey.cv_backfill):
        parsed = await parse_cv_with_claude(text, model=model, template=CV_ENRICHMENT)
    stats["model_calls"] += 1
    if parsed is None:
        stats["no_result"] += 1
        return
    parsed = normalize_cv_output(parsed)
    if not (parsed.get("first_name") or parsed.get("last_name")):
        stats["no_name_read"] += 1
        return
    candidate = await db.get(Candidate, target.candidate_id)
    if candidate is None:
        return
    review = await record_detected_identity(
        db,
        candidate=candidate,
        source_kind="document",
        source_id=target.document_id,
        observed_first_name=parsed.get("first_name"),
        observed_last_name=parsed.get("last_name"),
        observed_phone=parsed.get("phone"),
        provenance=PROVENANCE,
        observed_name_from_header=bool(parsed.get("_name_from_header")),
        hold_mismatch_for_review=True,
    )
    await db.commit()
    stats["decisions"][review.decision] = stats["decisions"].get(review.decision, 0) + 1
    if review_names_another_person(review.decision, review.evidence or {}):
        stats["doubt"] += 1
        stats["doubt_candidate_ids"].append(target.candidate_id)


async def run(
    *,
    apply: bool,
    candidate_ids: Sequence[int] = (),
    limit: int | None = None,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "apply": apply,
        "targets": 0,
        "model_calls": 0,
        "no_text": 0,
        "no_result": 0,
        "no_name_read": 0,
        "errors": 0,
        "error_document_ids": [],
        "decisions": {},
        "doubt": 0,
        "doubt_candidate_ids": [],
        "stopped_reason": None,
    }
    async with AsyncSessionLocal() as db:
        targets = await select_targets(db, candidate_ids=candidate_ids)
    stats["targets"] = len(targets)
    if not apply:
        return stats
    model = model_for(AIFeatureKey.cv_backfill)
    for target in targets[:limit]:
        async with AsyncSessionLocal() as db:
            try:
                await _review_target(db, target, model, stats)
            except AIQuotaExceeded as exc:
                stats["stopped_reason"] = f"quota: {exc}"
                break
            except Exception as exc:  # noqa: BLE001 — wiersz, nie bieg
                await db.rollback()
                stats["errors"] += 1
                stats["error_document_ids"].append(target.document_id)
                logger.warning(
                    "traffit_cv_identity_review: document=%s failed: %s",
                    target.document_id,
                    type(exc).__name__,
                )
        await asyncio.sleep(SLEEP_BETWEEN_CALLS_S)
    return stats


def _read_ids(path: str | None) -> tuple[int, ...]:
    if not path:
        return ()
    return tuple(
        int(item)
        for item in Path(path).read_text(encoding="utf-8").replace(",", " ").split()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--candidate-ids-file", default=None)
    args = parser.parse_args()
    stats = asyncio.run(
        run(
            apply=args.apply,
            candidate_ids=_read_ids(args.candidate_ids_file),
            limit=args.limit,
        )
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
