"""Masowe uzupełnianie pól kandydata z tekstu CV — Fala 3.

Populacja: kandydaci z tekstem CV (≥200 znaków), którym brakuje któregokolwiek
z pól celu: `skills` (NULL **lub** `'[]'` — 33 625 wierszy trzyma pustą tablicę,
realną listę ma ~600 osób, więc `[]` MUSI liczyć się jako puste), `city` albo
`years_it_experience`.

Zasady, które nie są kosmetyką:

* **Polityka zapisu = FILL_EMPTY** (`cv_enrichment._apply_cv_enrichment`).
  Tylko puste pola, nigdy nadpisanie człowieka; flagi `_manual_override_*` są
  honorowane generycznie. Ta polityka jest już wdrożona i przetestowana — ten
  moduł jej NIE reimplementuje, tylko ją woła.
* **Kwota per wywołanie** (`ai_feature(db, cv_backfill)`), osobny kubełek od
  `cv_parser` — bieg masowy nie może wyczerpać limitu rekruterów. Wyczerpana
  kwota ZATRZYMUJE bieg (to hamulec organizacyjny, nie sygnał per wiersz).
* **Keyset pagination, wznawialny kursor** — Coolify restartuje kontener przy
  każdym pushu, a pełny bieg to godziny. `after_id` w statusie mówi, od czego
  wznowić.
* **Sam krok Claude** (`_parse_with_claude`, model+prompt masowe), bez Ollamy:
  fallback na lokalny model dawałby niespójną jakość w obrębie jednego biegu,
  a regex nie wypełnia pól celu. Wiersz bez wyniku = pominięty, nie blokujący.
* **`message.usage` jest zbierane** — bieg kalibracyjny ma zmierzyć realny
  koszt jednostkowy zamiast szacunku; sumy tokenów są w statusie.
* **Zaktualizowani trafiają do outboxu reindeksu** — tekst embeddingu kandydata
  zawiera skills/kategorię, więc wypełnienie pól BEZ oznaczenia do re-embeddingu
  zostawiłoby wektory stare i praca Claude'a nigdy nie dotarłaby do Voyage.
  Dokładnie ta luka zjadła Falę 1 (naprawa w #1096); tu oznaczamy w rytmie
  commitów, żeby przerwany bieg nie gubił oznaczeń.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.cv_enrichment import CvWritePolicy, _apply_cv_enrichment
from app.services.cv_parser import parse_cv_with_claude
from app.services.llm_prompts import CV_ENRICHMENT_BULK

logger = logging.getLogger(__name__)

MIN_CV_CHARS = 200
COMMIT_EVERY = 25
# Krótka pauza między wywołaniami LLM: bieg dzieli backend z ruchem rekruterów
# i nie może zmonopolizować ani limitów dostawcy, ani pętli zdarzeń.
SLEEP_BETWEEN_CALLS_S = 0.15

# Pola, których brak kwalifikuje kandydata do biegu i których wypełnienie
# liczymy jako efekt. Semantyka "puste" jest per pole — patrz _missing_*.
TARGET_FIELDS = ("skills", "city", "years_it_experience")

# `[]` liczy się jako puste — patrz docstring modułu. Ten sam predykat co w
# candidate_column_coverage (tam jako string SQL, tu jako wyrażenie).
_SKILLS_EMPTY = or_(
    Candidate.skills.is_(None),
    text(
        "NOT (jsonb_typeof(candidates.skills) = 'array' "
        "AND candidates.skills <> '[]'::jsonb)"
    ),
)
_CITY_EMPTY = or_(Candidate.city.is_(None), func.trim(Candidate.city) == "")
_YEARS_EMPTY = Candidate.years_it_experience.is_(None)


def _scope_filter():
    return (
        Candidate.raw_cv_text.isnot(None),
        func.length(Candidate.raw_cv_text) >= MIN_CV_CHARS,
        or_(_SKILLS_EMPTY, _CITY_EMPTY, _YEARS_EMPTY),
    )


def _empty_now(candidate: Candidate) -> set[str]:
    """Które pola celu są puste TERAZ — mierzone tą samą semantyką co scope."""

    empty: set[str] = set()
    skills = candidate.skills
    if not isinstance(skills, list) or len(skills) == 0:
        empty.add("skills")
    if not (candidate.city or "").strip():
        empty.add("city")
    if candidate.years_it_experience is None:
        empty.add("years_it_experience")
    return empty


async def count_scope(db: AsyncSession, *, after_id: int = 0) -> dict[str, int]:
    """Ile wierszy kwalifikuje się do biegu — i czego im brakuje.

    Darmowe (bez LLM); to jest liczba do decyzji i do szacunku kosztu.
    """

    base = [Candidate.id > after_id, *_scope_filter()]
    total = await db.scalar(select(func.count()).where(*base))
    missing_skills = await db.scalar(select(func.count()).where(*base, _SKILLS_EMPTY))
    missing_city = await db.scalar(select(func.count()).where(*base, _CITY_EMPTY))
    missing_years = await db.scalar(select(func.count()).where(*base, _YEARS_EMPTY))
    return {
        "in_scope": int(total or 0),
        "missing_skills": int(missing_skills or 0),
        "missing_city": int(missing_city or 0),
        "missing_years": int(missing_years or 0),
    }


async def backfill_cv_fields(
    db: AsyncSession,
    *,
    limit: Optional[int] = None,
    after_id: int = 0,
    progress: Optional[dict[str, Any]] = None,
    calibration_log_path: Optional[str] = None,
) -> dict[str, Any]:
    """Przetwórz scope sekwencyjnie; zwróć (i aktualizuj) statystyki.

    `calibration_log_path` włącza tryb kalibracji: każdy wiersz dopisuje do
    JSONL surowy wynik parsowania + usage, żeby dało się ręcznie ocenić jakość
    Haiku na próbce PRZED autoryzacją pełnego biegu.
    """

    stats: dict[str, Any] = progress if progress is not None else {}
    stats.setdefault("processed", 0)
    stats.setdefault("updated", 0)
    stats.setdefault("skipped_no_result", 0)
    stats.setdefault("errors", 0)
    stats.setdefault("fields_filled", {f: 0 for f in TARGET_FIELDS})
    stats.setdefault("usage", {"input_tokens": 0, "output_tokens": 0, "calls": 0})
    stats.setdefault("reindex_enqueued", 0)
    stats["last_id"] = after_id
    stats["stopped_reason"] = None

    max_calls = int(getattr(settings, "CV_BACKFILL_MAX_CALLS", 45_000) or 45_000)
    bulk_model = settings.CLAUDE_MODEL_CV_BULK

    calibration_handle = None
    if calibration_log_path:
        from pathlib import Path

        # Strażnik na UJŚCIU, nie w endpoincie: parametr przychodzi od admina
        # przez query string i trafia do `open(..., "a")`. Bez ograniczenia to
        # zapis w dowolne miejsce zapisywalne dla procesu — dopisanie fragmentu
        # do `entrypoint.sh` czy plików crona wykonuje się przy najbliższym
        # restarcie, a Coolify restartuje kontener przy KAŻDYM pushu. `resolve()`
        # przed sprawdzeniem, żeby `/tmp/../etc/x` nie przeszło po literach.
        resolved = Path(calibration_log_path).resolve()
        if not resolved.is_relative_to(Path("/tmp")):
            raise ValueError(
                "calibration_log_path musi wskazywać pod /tmp — "
                f"otrzymano {calibration_log_path!r}"
            )
        calibration_handle = open(resolved, "a", encoding="utf-8")  # noqa: SIM115

    from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex

    pending_reindex: list[int] = []

    async def _flush_reindex() -> None:
        if not pending_reindex:
            return
        enqueued = await record_bulk_reindex(db, CANDIDATE, pending_reindex)
        stats["reindex_enqueued"] += int(enqueued or 0)
        pending_reindex.clear()

    try:
        since_commit = 0
        cursor = after_id
        while True:
            rows = (
                (
                    await db.execute(
                        select(Candidate)
                        .where(Candidate.id > cursor, *_scope_filter())
                        .order_by(Candidate.id)
                        .limit(200)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                break

            for candidate in rows:
                cursor = candidate.id
                stats["last_id"] = candidate.id

                if limit and stats["processed"] >= limit:
                    stats["stopped_reason"] = "limit"
                    return stats
                if stats["usage"]["calls"] >= max_calls:
                    # Bezpiecznik biegu, nie kwota: `ai_quota` sam dokumentuje
                    # się jako advisory i wyścigowy, więc bieg ma własny sufit.
                    stats["stopped_reason"] = "max_calls"
                    return stats

                stats["processed"] += 1
                empty_before = _empty_now(candidate)
                if not empty_before:
                    # Wiersz mógł zostać uzupełniony między stronami — nie płać.
                    continue

                try:
                    async with ai_feature(db, AIFeatureKey.cv_backfill):
                        parsed = await parse_cv_with_claude(
                            candidate.raw_cv_text,
                            model=bulk_model,
                            template=CV_ENRICHMENT_BULK,
                        )
                except AIQuotaExceeded as quota_exc:
                    # Hamulec organizacyjny — zatrzymuje BIEG, nie wiersz.
                    stats["stopped_reason"] = f"quota: {quota_exc}"
                    logger.warning("[cv-backfill] stop przez kwotę: %s", quota_exc)
                    return stats

                stats["usage"]["calls"] += 1
                if parsed is None:
                    stats["skipped_no_result"] += 1
                    continue

                usage = parsed.get("_usage") or {}
                stats["usage"]["input_tokens"] += int(usage.get("input_tokens") or 0)
                stats["usage"]["output_tokens"] += int(usage.get("output_tokens") or 0)

                if calibration_handle is not None:
                    calibration_handle.write(
                        json.dumps(
                            {"candidate_id": candidate.id, "parsed": parsed},
                            ensure_ascii=False,
                            default=str,
                        )
                        + "\n"
                    )

                try:
                    _apply_cv_enrichment(
                        candidate, parsed, policy=CvWritePolicy.FILL_EMPTY
                    )
                except Exception as exc:  # noqa: BLE001 — wiersz, nie bieg
                    stats["errors"] += 1
                    logger.warning(
                        "[cv-backfill] apply padł dla id=%s: %r", candidate.id, exc
                    )
                    continue

                filled = empty_before - _empty_now(candidate)
                if filled:
                    stats["updated"] += 1
                    for field in filled:
                        stats["fields_filled"][field] += 1
                    pending_reindex.append(candidate.id)

                since_commit += 1
                if since_commit >= COMMIT_EVERY:
                    # Oznaczenia reindeksu jadą w TEJ SAMEJ transakcji co pola —
                    # commit zapisuje oba naraz albo żadnego, więc restart nie
                    # zostawia wierszy z nowymi polami i starym wektorem.
                    await _flush_reindex()
                    await db.commit()
                    since_commit = 0
                    logger.info(
                        "[cv-backfill] processed=%s updated=%s last_id=%s "
                        "tokens(in/out)=%s/%s",
                        stats["processed"],
                        stats["updated"],
                        stats["last_id"],
                        stats["usage"]["input_tokens"],
                        stats["usage"]["output_tokens"],
                    )

                await asyncio.sleep(SLEEP_BETWEEN_CALLS_S)

        stats["stopped_reason"] = stats["stopped_reason"] or "done"
        return stats
    finally:
        await _flush_reindex()
        await db.commit()
        if calibration_handle is not None:
            calibration_handle.close()
