"""Backfill DAT w ``candidates.experience`` z tekstu CV.

Po co? ~44k kandydatów z Traffita dostało ``experience`` z gołej listy
pracodawców (``traffit_previous_employers`` → ``scripts/backfill_candidate_experience.py``):
każdy wpis bez ``start`` i bez ``end``. ``end IS NULL`` jest kanonicznym
znacznikiem bieżącej pracy, więc KAŻDA firma z takiego CV liczyła się jako
obecny pracodawca — w filtrze „Obecna firma" i w panelu ATLAS-a „pracują tam
teraz". Masowy bieg Fali 3 (``cv_field_backfill``) tego nie naprawia: jego
prompt celowo nie prosi o ``experience``, a polityka FILL_EMPTY nie dotyka
niepustej listy.

Ten bieg prosi model WYŁĄCZNIE o historię zatrudnienia (``CV_EXPERIENCE_DATES``)
i zapisuje ją tylko wtedy, gdy odczyt niesie choć jedną datę. Zasady, które
nie są kosmetyką:

* **Scope = wiersze bez żadnej daty w ``experience``** (pusta lista też), z
  tekstem CV ≥ 200 znaków, bez ręcznej blokady ``_manual_override_experience``
  i bez znacznika „model nic nie znalazł" — wiersz, za który już zapłacono bez
  efektu, nie wraca do kolejki przy każdym wznowieniu.
* **Zapis = odczyt z datami + stare firmy, których model nie wymienił**, dopisane
  bez dat. Lista Traffita bywa dłuższa niż CV (stanowiska sprzed wielu lat), a
  ich wyrzucenie zmieniłoby „mają firmę w CV" w „nigdy tam nie pracowali".
* **Ta sama kwota co Fala 3** (``AIFeatureKey.cv_backfill``) i ten sam model
  masowy — bieg nie może wyczerpać limitu rekruterów; wyczerpana kwota
  ZATRZYMUJE bieg.
* **Keyset pagination, wznawialny kursor** (``after_id``) — Coolify restartuje
  kontener przy każdym pushu, a bieg trwa godziny.
* **Zaktualizowani trafiają do outboxu reindeksu** — tekst embeddingu
  (``canonical_text``) zawiera role z ``experience``, więc bez oznaczenia wektory
  zostałyby stare (ta sama luka, która zjadła Falę 1).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.services.ai_models import model_for
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.cv_parser import normalize_experience_entries, parse_cv_with_claude
from app.services.experience_end import is_current_end, sql_current_end_literals
from app.services.llm_prompts import CV_EXPERIENCE_DATES

logger = logging.getLogger(__name__)

MIN_CV_CHARS = 200
COMMIT_EVERY = 25
SLEEP_BETWEEN_CALLS_S = 0.15
# Ile starych, niedatowanych firm dopisujemy za odczytem modelu. Lista Traffita
# ma do 15 pozycji; bez sufitu zepsuty wiersz z setką „firm" rozdąłby JSONB.
MAX_KEPT_UNDATED = 15
# Znaczniki w `cv_extracted_data` — ta sama torba, w której żyją flagi
# `_manual_override_*`, więc czyszczenie kwarantanny tożsamości ich nie zgubi.
BACKFILLED_AT_KEY = "_experience_dates_backfilled_at"
NO_RESULT_KEY = "_experience_dates_no_result_at"
MANUAL_OVERRIDE_KEY = "_manual_override_experience"

# Wpis „z datą" = ma początek ALBO koniec będący DATĄ (nie słowem „obecnie").
# Jedna definicja w SQL (scope) i w Pythonie (`entry_is_dated`) — rozjazd
# oznaczałby wiersze, które scope wybiera, a bieg pomija (albo odwrotnie),
# czyli płacenie za nic albo wieczną pętlę.
_CURRENT_WORDS_SQL = sql_current_end_literals(include_empty=False)
# Negacje wpisane w SQL, nie przez `~text(...)`: SQLAlchemy nie umie odwrócić
# surowego `TextClause` (asercja w `_negate`), a `not_()` idzie tą samą ścieżką.
_NO_DATED_ENTRY_SQL = text(
    "NOT EXISTS ("
    "SELECT 1 FROM jsonb_array_elements("
    "CASE WHEN jsonb_typeof(candidates.experience) = 'array' "
    "THEN candidates.experience ELSE '[]'::jsonb END"
    ") AS e(elem) "
    "WHERE btrim(coalesce(elem->>'start', '')) <> '' "
    "OR (btrim(coalesce(elem->>'end', '')) <> '' "
    f"AND lower(btrim(elem->>'end')) NOT IN ({_CURRENT_WORDS_SQL}))"
    ")"
)
_NOT_MANUALLY_LOCKED_SQL = text(
    "coalesce(candidates.cv_extracted_data->>'_manual_override_experience', '') <> 'true'"
)
# `jsonb_exists(...)` zamiast operatora `?` — znak zapytania w surowym SQL
# koliduje z paramstyle sterownika.
_NOT_MARKED_NO_RESULT_SQL = text(
    "NOT (jsonb_typeof(candidates.cv_extracted_data) = 'object' "
    f"AND jsonb_exists(candidates.cv_extracted_data, '{NO_RESULT_KEY}'))"
)


def _scope_filter():
    return (
        Candidate.raw_cv_text.isnot(None),
        func.length(Candidate.raw_cv_text) >= MIN_CV_CHARS,
        _NO_DATED_ENTRY_SQL,
        _NOT_MANUALLY_LOCKED_SQL,
        _NOT_MARKED_NO_RESULT_SQL,
    )


def entry_is_dated(entry: Any) -> bool:
    """Lustro warunku z `_NO_DATED_ENTRY_SQL` dla jednego wpisu."""
    if not isinstance(entry, dict):
        return False
    start = entry.get("start")
    if isinstance(start, str) and start.strip():
        return True
    end = entry.get("end")
    if not isinstance(end, str) or not end.strip():
        return False
    return not is_current_end(end)


def needs_dates(candidate: Candidate) -> bool:
    """Czy wiersz NADAL kwalifikuje się do biegu — mierzone tą samą semantyką co scope."""
    entries = candidate.experience if isinstance(candidate.experience, list) else []
    if any(entry_is_dated(e) for e in entries):
        return False
    extracted = candidate.cv_extracted_data
    if isinstance(extracted, dict):
        if (
            extracted.get(MANUAL_OVERRIDE_KEY) is True
            or extracted.get(MANUAL_OVERRIDE_KEY) == "true"
        ):
            return False
        if NO_RESULT_KEY in extracted:
            return False
    return True


def _company_key(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return " ".join(name.casefold().split())


def merge_experience(
    existing: Any, parsed_entries: list[dict[str, Optional[str]]]
) -> Optional[list[dict[str, Optional[str]]]]:
    """Nowa lista `experience` albo ``None``, gdy odczyt nie niesie żadnej daty.

    Odczyt modelu idzie w całości (stanowiska + daty, najnowsze pierwsze), a za
    nim — bez dat — te stare firmy, których model nie wymienił. Stara firma
    obecna w odczycie NIE jest dublowana: podwójny wpis (datowany + pusty)
    dawałby w ATLAS-ie tę samą osobę raz jako „wcześniej", raz jako „okres
    nieznany".
    """
    if not any(entry_is_dated(e) for e in parsed_entries):
        return None
    merged: list[dict[str, Optional[str]]] = [
        {
            "company": e.get("company") or None,
            "role": e.get("role") or None,
            "start": e.get("start") or None,
            "end": e.get("end") or None,
            "desc": None,
        }
        for e in parsed_entries
        if e.get("company") or e.get("role")
    ]
    seen = {_company_key(e["company"]) for e in merged if e["company"]}
    kept = 0
    for old in existing if isinstance(existing, list) else []:
        if not isinstance(old, dict):
            continue
        key = _company_key(old.get("company"))
        if not key or key in seen:
            continue
        if kept >= MAX_KEPT_UNDATED:
            break
        seen.add(key)
        kept += 1
        merged.append(
            {
                "company": old.get("company"),
                "role": old.get("role") or None,
                "start": None,
                "end": None,
                "desc": old.get("desc") or None,
            }
        )
    return merged


async def count_scope(db: AsyncSession, *, after_id: int = 0) -> dict[str, int]:
    """Ile wierszy kwalifikuje się do biegu — darmowe, bez LLM."""
    base = [Candidate.id > after_id, *_scope_filter()]
    total = await db.scalar(select(func.count()).where(*base))
    empty = await db.scalar(
        select(func.count()).where(
            *base,
            text(
                "NOT (jsonb_typeof(candidates.experience) = 'array' "
                "AND jsonb_array_length(candidates.experience) > 0)"
            ),
        )
    )
    return {
        "in_scope": int(total or 0),
        "with_empty_experience": int(empty or 0),
        "with_undated_experience": int(total or 0) - int(empty or 0),
    }


def _stamp(candidate: Candidate, key: str, value: Any) -> None:
    raw = candidate.cv_extracted_data
    extracted = dict(raw) if isinstance(raw, dict) else {}
    extracted[key] = value
    # Nowy obiekt, nie mutacja — JSONB bez `MutableDict` nie widzi zmian w miejscu.
    candidate.cv_extracted_data = extracted


async def backfill_experience_dates(
    db: AsyncSession,
    *,
    limit: Optional[int] = None,
    after_id: int = 0,
    progress: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Przetwórz scope sekwencyjnie; zwróć (i aktualizuj) statystyki."""
    stats: dict[str, Any] = progress if progress is not None else {}
    stats.setdefault("processed", 0)
    stats.setdefault("updated", 0)
    stats.setdefault("skipped_no_dates", 0)
    stats.setdefault("skipped_no_result", 0)
    stats.setdefault("errors", 0)
    stats.setdefault("usage", {"input_tokens": 0, "output_tokens": 0, "calls": 0})
    stats.setdefault("reindex_enqueued", 0)
    stats["last_id"] = after_id
    stats["stopped_reason"] = None

    max_calls = int(getattr(settings, "CV_BACKFILL_MAX_CALLS", 45_000) or 45_000)
    bulk_model = model_for(AIFeatureKey.cv_backfill)

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
                    stats["stopped_reason"] = "max_calls"
                    return stats

                stats["processed"] += 1
                if not needs_dates(candidate):
                    # Wiersz mógł dostać daty między stronami — nie płać.
                    continue

                try:
                    async with ai_feature(db, AIFeatureKey.cv_backfill):
                        parsed = await parse_cv_with_claude(
                            candidate.raw_cv_text,
                            model=bulk_model,
                            template=CV_EXPERIENCE_DATES,
                        )
                except AIQuotaExceeded as quota_exc:
                    stats["stopped_reason"] = f"quota: {quota_exc}"
                    logger.warning("[experience-dates] stop przez kwotę: %s", quota_exc)
                    return stats

                stats["usage"]["calls"] += 1
                if parsed is None:
                    # Awaria wywołania (timeout, zły JSON) — NIE znakujemy
                    # wiersza: przy wznowieniu ma dostać drugą szansę.
                    stats["skipped_no_result"] += 1
                    continue

                usage = parsed.get("_usage") or {}
                stats["usage"]["input_tokens"] += int(usage.get("input_tokens") or 0)
                stats["usage"]["output_tokens"] += int(usage.get("output_tokens") or 0)

                now = datetime.now(timezone.utc).isoformat()
                merged = merge_experience(
                    candidate.experience,
                    normalize_experience_entries(parsed.get("experience")),
                )
                try:
                    async with db.begin_nested():
                        if merged is None:
                            # Model odczytał CV, ale bez ani jednej daty — to
                            # jest wynik, nie awaria. Znacznik wyklucza wiersz
                            # ze scope'u, żeby nie płacić za niego ponownie.
                            _stamp(candidate, NO_RESULT_KEY, now)
                            stats["skipped_no_dates"] += 1
                        else:
                            candidate.experience = merged
                            _stamp(candidate, BACKFILLED_AT_KEY, now)
                            stats["updated"] += 1
                            pending_reindex.append(candidate.id)
                        await db.flush()
                except Exception as exc:  # noqa: BLE001 — wiersz, nie bieg
                    stats["errors"] += 1
                    logger.warning(
                        "[experience-dates] zapis padł dla id=%s: %r — wiersz "
                        "pominięty, bieg trwa",
                        candidate.id,
                        exc,
                    )
                    continue

                since_commit += 1
                if since_commit >= COMMIT_EVERY:
                    await _flush_reindex()
                    await db.commit()
                    since_commit = 0
                    logger.info(
                        "[experience-dates] processed=%s updated=%s no_dates=%s "
                        "last_id=%s tokens(in/out)=%s/%s",
                        stats["processed"],
                        stats["updated"],
                        stats["skipped_no_dates"],
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
