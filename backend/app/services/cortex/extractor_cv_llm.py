"""Cortex — ekstraktor faktów z CV przez LLM (``source='cv_llm'``, Etap 2).

Reużywa istniejący stos: ``parse_cv`` (Claude→Ollama→regex) na ``raw_cv_text``
kandydata → lista skilli → normalizacja przez tę samą taksonomię co Traffit →
upsert faktów ``source='cv_llm'`` (confidence wyższe niż Traffit, bo skille
wyciągnięte z kontekstu CV, nie z ręcznego pola).

**Bezpieczeństwo / koszt:**
- Kosztowny (LLM per kandydat) — NIGDY nie odpala się automatycznie (brak fazy w
  daily sync). Tylko ręczny admin endpoint, gated ``CORTEX_CV_LLM_ENABLED``.
- ``only_active=True`` domyślnie — najpierw aktywni konsultanci (plan Etap 2).
- Pełnego backfillu całej bazy NIE uruchamiać przed walidacją Etapu 0 i
  ekstraktora na ograniczonej populacji (``limit``).
- Idempotentny + reconcile per (candidate, cv_llm) — jak Traffit.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.services.cortex import runs
from app.services.cortex.fact_store import (
    RawSkillToken,
    load_taxonomy,
    normalize_and_upsert,
)
from app.services.cv_parser import parse_cv

logger = logging.getLogger(__name__)

SOURCE = "cv_llm"
# Wyższe niż Traffit (0.8) — skill z kontekstu CV jest silniejszym sygnałem niż
# ręcznie wpisany token, ale wciąż < screening (weryfikacja człowieka).
CV_LLM_CONFIDENCE = 0.85
EXTRACTOR_VERSION = "cv_llm-1"

_COMMIT_EVERY = 20  # LLM-bound, więc mniejsze batche + częstszy heartbeat
_LOG_EVERY = 20


def _content_hash(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def _extract_skill_names(parsed: dict[str, Any]) -> list[str]:
    """Wyciągnij nazwy skilli z wyniku ``parse_cv`` (str albo {name})."""
    out: list[str] = []
    for s in parsed.get("skills") or []:
        if isinstance(s, str) and s.strip():
            out.append(s)
        elif isinstance(s, dict):
            name = s.get("name") or s.get("skill")
            if name:
                out.append(str(name))
    return out


async def run_cv_llm_extraction(
    db: AsyncSession,
    *,
    limit: Optional[int] = None,
    only_active: bool = True,
    run_id: Optional[int] = None,
    progress: Optional[dict] = None,
) -> dict:
    """Ekstrahuj fakty cv_llm z ``raw_cv_text`` kandydatów. Zwraca staty."""
    taxonomy = await load_taxonomy(db)

    q = select(Candidate.id, Candidate.raw_cv_text).where(
        func.coalesce(Candidate.raw_cv_text, "") != ""
    )
    if only_active:
        from app.api.candidates import _at_client_predicate

        q = q.where(_at_client_predicate())
    q = q.order_by(Candidate.id)
    if limit:
        q = q.limit(int(limit))
    rows = (await db.execute(q)).all()

    stats = {
        "total": len(rows),
        "processed": 0,
        "facts_upserted": 0,
        "unmatched_tokens": 0,
        "errors": 0,
    }
    if progress is not None:
        progress.update(stats)

    for candidate_id, raw in rows:
        try:
            # parse_cv woła zewnętrzny LLM — poza savepointem (żeby nie trzymać
            # otwartej transakcji przez czas API call).
            parsed = await parse_cv(raw)
            tokens = [
                RawSkillToken(
                    name=name, confidence=CV_LLM_CONFIDENCE, evidence=name[:300]
                )
                for name in _extract_skill_names(parsed)
            ]
            async with db.begin_nested():
                fact_stats = await normalize_and_upsert(
                    db,
                    candidate_id=candidate_id,
                    tokens=tokens,
                    source=SOURCE,
                    taxonomy=taxonomy,
                    reconcile=True,
                    run_id=run_id,
                    extractor_version=EXTRACTOR_VERSION,
                    content_hash=_content_hash(raw or ""),
                )
            stats["facts_upserted"] += fact_stats.matched
            stats["unmatched_tokens"] += fact_stats.unmatched
        except Exception:  # noqa: BLE001 — pojedynczy kandydat nie ubija runu
            stats["errors"] += 1
            logger.exception("cortex cv_llm extraction failed for id=%s", candidate_id)

        stats["processed"] += 1
        if stats["processed"] % _COMMIT_EVERY == 0:
            await db.commit()
            if run_id is not None:
                await runs.heartbeat_run(
                    db, run_id, cursor_candidate_id=candidate_id, stats=dict(stats)
                )
        if stats["processed"] % _LOG_EVERY == 0:
            logger.info(
                "cortex cv_llm: %s/%s (facts=%s)",
                stats["processed"],
                stats["total"],
                stats["facts_upserted"],
            )
        if progress is not None:
            progress.update(stats)

    await db.commit()
    if progress is not None:
        progress.update(stats)
    logger.info("cortex cv_llm extraction done: %s", stats)
    return stats


async def execute_cv_llm_run(
    db: AsyncSession,
    run_id: int,
    *,
    limit: Optional[int] = None,
    only_active: bool = True,
    progress: Optional[dict] = None,
) -> dict:
    """Wykonaj zarezerwowany run cv_llm i sfinalizuj jego status."""
    try:
        stats = await run_cv_llm_extraction(
            db, limit=limit, only_active=only_active, run_id=run_id, progress=progress
        )
        status = "errors" if stats.get("errors") else "ok"
        await runs.finish_run(db, run_id, status=status, stats=stats)
        return stats
    except Exception as exc:  # noqa: BLE001
        logger.exception("cortex cv_llm run failed (run_id=%s)", run_id)
        await db.rollback()
        await runs.finish_run(db, run_id, status="failed", last_error=str(exc))
        raise
