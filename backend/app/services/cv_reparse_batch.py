"""Ponowny odczyt CV starej bazy pełnym promptem przez Message Batches API.

Decyzja Artura z 07.11.2026: oś technologii (`skill_timeline`) i pola v9 dla
osób czytanych dotąd tanim szablonem masowym (08.2026) albo wcale, model
`cv_backfill` (Haiku 5.5), Batch API (−50%). Pomiar na 50 CV: 0,0017 USD za
CV na żywo, oś u 47 z 50 osób.

Zasady:

* **To samo żądanie co ścieżka rekrutera** (`claude_cv_request_params`) i ta
  sama obróbka odpowiedzi (`parsed_from_claude_message`,
  `finalize_claude_cv_output`): filtr technologii bez śladu w CV, ratowanie
  uciętego JSON-a, regex kontaktu, normalizacja.
* **Zapis przez `finish_cv_ingest` z FILL_EMPTY** bez zgłaszania do
  auto-dopasowania: stare CV nie mogą wyglądać jak fala nowych.
* **Bramka tożsamości** jak w `cv_field_backfill`: sprzeczna nazwa = nic nie
  zapisujemy, profil zostaje do przeglądu.
* **Wznowienie bez stanu poza bazą**: odczytany tekst dostaje znacznik
  `_cv_reparse` (skrót tekstu, wynik, próby), a zakres pomija osoby ze
  znacznikiem tego samego tekstu. Nieudana odpowiedź (niepoprawny JSON,
  błąd paczki) wraca do zakresu raz. Nowe CV (inny tekst) wraca samo.
* **Paczka czeka na wynik, zanim pójdzie następna**: przerwany proces traci
  najwyżej jedną paczkę, a jej id jest w logu (`collect`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.services.ai_models import model_for
from app.services.ai_quota import ai_feature
from app.services.cv_enrichment import CvWritePolicy
from app.services.cv_parser import (
    claude_cv_request_params,
    finalize_claude_cv_output,
    parsed_from_claude_message,
)
from app.services.llm_prompts import CV_ENRICHMENT

logger = logging.getLogger(__name__)

REPARSE_KEY = "_cv_reparse"
MAX_ATTEMPTS = 2
MIN_CV_CHARS = 200
CUSTOM_ID_PREFIX = "cvr"
TRIGGER = "cv_reparse"
# Koszt na CV z pomiaru 07.11.2026 (Haiku 5.5, prompt v9, na żywo) i zniżka
# Batch API — tylko do szacunku w `count`, rachunek liczy `ai_metering`.
EST_USD_PER_CV = 0.00177 * 0.5

CURRENT_SOURCE = f"claude:{CV_ENRICHMENT.name}:v{CV_ENRICHMENT.version}"

_SCOPE_SQL = f"""
    length(c.raw_cv_text) >= {MIN_CV_CHARS}
    AND EXISTS (
        SELECT 1 FROM candidate_documents d
        WHERE d.candidate_id = c.id AND d.document_kind = 'cv'
          AND d.source_deleted_at IS NULL
    )
    AND coalesce(c.cv_extracted_data->>'_source', '') <> :current_source
    AND NOT (
        coalesce(c.cv_extracted_data->'{REPARSE_KEY}'->>'md5', '') = md5(c.raw_cv_text)
        AND (
            coalesce(c.cv_extracted_data->'{REPARSE_KEY}'->>'outcome', '') <> 'failed'
            OR coalesce((c.cv_extracted_data->'{REPARSE_KEY}'->>'attempts')::int, 0)
               >= {MAX_ATTEMPTS}
        )
    )
"""
# Domyślny zakres = osoby bez osi technologii (decyzja „wszyscy” z 07.11).
_NO_AXIS_SQL = """
    AND coalesce(jsonb_array_length(CASE
        WHEN jsonb_typeof(c.cv_extracted_data->'skill_timeline') = 'array'
        THEN c.cv_extracted_data->'skill_timeline' END), 0) = 0
"""


def text_digest(cv_text: str) -> str:
    return hashlib.md5(cv_text.encode("utf-8")).hexdigest()  # noqa: S324 — skrót tożsamości tekstu


def custom_id(candidate_id: int, digest: str) -> str:
    return f"{CUSTOM_ID_PREFIX}-{candidate_id}-{digest[:16]}"


def parse_custom_id(value: str) -> Optional[tuple[int, str]]:
    parts = value.split("-")
    if len(parts) != 3 or parts[0] != CUSTOM_ID_PREFIX or not parts[1].isdigit():
        return None
    return int(parts[1]), parts[2]


def _scope(include_with_axis: bool) -> str:
    return _SCOPE_SQL + ("" if include_with_axis else _NO_AXIS_SQL)


async def count_scope(db: AsyncSession, *, include_with_axis: bool = False) -> int:
    sql = f"SELECT count(*) FROM candidates c WHERE {_scope(include_with_axis)}"
    return int(await db.scalar(text(sql), {"current_source": CURRENT_SOURCE}) or 0)


async def pick_chunk(
    db: AsyncSession,
    *,
    after_id: int,
    until_id: Optional[int],
    size: int,
    include_with_axis: bool = False,
) -> list[tuple[int, str]]:
    """Następna paczka (id, tekst CV) po kursorze — keyset po `id`."""
    upper = "AND c.id <= :until_id" if until_id is not None else ""
    sql = (
        "SELECT c.id, c.raw_cv_text FROM candidates c "
        f"WHERE c.id > :after_id {upper} AND {_scope(include_with_axis)} "
        "ORDER BY c.id LIMIT :size"
    )
    params: dict[str, Any] = {
        "after_id": after_id,
        "size": size,
        "current_source": CURRENT_SOURCE,
    }
    if until_id is not None:
        params["until_id"] = until_id
    rows = (await db.execute(text(sql), params)).all()
    return [(int(r[0]), r[1]) for r in rows]


def build_requests(rows: Iterable[tuple[int, str]], *, model: str) -> list[dict]:
    return [
        {
            "custom_id": custom_id(cid, text_digest(cv_text)),
            "params": claude_cv_request_params(cv_text, model=model),
        }
        for cid, cv_text in rows
    ]


@dataclass
class ReparseStats:
    submitted: int = 0
    applied: int = 0
    with_axis: int = 0
    identity_held: int = 0
    failed: int = 0
    stale: int = 0
    missing: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    batch_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _mark(candidate: Candidate, digest: str, outcome: str) -> None:
    extracted = candidate.cv_extracted_data
    extracted = dict(extracted) if isinstance(extracted, dict) else {}
    previous = extracted.get(REPARSE_KEY)
    attempts = 1
    if isinstance(previous, dict) and previous.get("md5") == digest:
        attempts = int(previous.get("attempts") or 0) + 1
    extracted[REPARSE_KEY] = {"md5": digest, "outcome": outcome, "attempts": attempts}
    # Nowy obiekt, nie mutacja — JSONB bez `MutableDict` nie widzi zmian w miejscu.
    candidate.cv_extracted_data = extracted


async def apply_result(
    db: AsyncSession,
    *,
    candidate_id: int,
    digest: str,
    result: Any,
    model: str,
    stats: ReparseStats,
) -> None:
    """Zapisz jeden wynik paczki. Błąd wiersza nie zatrzymuje biegu."""
    from app.services.claude_client import record_batch_message_usage
    from app.services.cv_field_backfill import _read_names_another_person
    from app.services.cv_ingest_service import finish_cv_ingest

    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        stats.missing += 1
        return
    cv_text = candidate.raw_cv_text or ""
    full_digest = text_digest(cv_text)
    # `custom_id` niesie początek skrótu (limit 64 znaków), znacznik — pełny.
    if not digest or not full_digest.startswith(digest):
        # CV zmieniło się po wysłaniu — odczyt opisuje stary plik.
        stats.stale += 1
        return
    digest = full_digest
    if getattr(result, "type", None) != "succeeded":
        stats.failed += 1
        _mark(candidate, digest, "failed")
        await db.flush()
        return

    message = result.message
    async with ai_feature(db, AIFeatureKey.cv_backfill):
        record_batch_message_usage(message, model=model)
    usage = getattr(message, "usage", None)
    stats.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
    stats.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)

    try:
        parsed = parsed_from_claude_message(message, cv_text, model=model)
    except json.JSONDecodeError:
        parsed = None
    if parsed is None:
        stats.failed += 1
        _mark(candidate, digest, "failed")
        await db.flush()
        return
    parsed = finalize_claude_cv_output(parsed, cv_text)

    async with db.begin_nested():
        if await _read_names_another_person(db, candidate, parsed):
            stats.identity_held += 1
            _mark(candidate, digest, "identity_held")
            await db.flush()
            return
        await finish_cv_ingest(
            db,
            candidate=candidate,
            parsed=parsed,
            source_document_id=None,
            source_hash=None,
            policy=CvWritePolicy.FILL_EMPTY,
            trigger=TRIGGER,
            enqueue_auto_match=False,
        )
        _mark(candidate, digest, "ok")
        await db.flush()
    stats.applied += 1
    extracted = candidate.cv_extracted_data
    if not isinstance(extracted, dict):
        return
    if any(
        isinstance(e, dict) and e.get("months")
        for e in extracted.get("skill_timeline") or []
    ):
        stats.with_axis += 1


async def apply_batch_results(
    db: AsyncSession,
    results: Iterable[Any],
    *,
    model: str,
    stats: ReparseStats,
    commit_every: int = 25,
) -> None:
    """Wyniki paczki (`client.messages.batches.results`) → profile.

    Commit w `finally`: wyjątek spoza wiersza (np. zerwany strumień wyników)
    nie może zgubić zapisanych już wierszy, bo za ich odczyt zapłacono.
    """
    since_commit = 0
    try:
        for entry in results:
            parsed_id = parse_custom_id(getattr(entry, "custom_id", "") or "")
            if parsed_id is None:
                continue
            candidate_id, digest = parsed_id
            try:
                # SAVEPOINT per wiersz: błąd cofa tylko ten wiersz, a nie
                # niezacommitowane udane wiersze z tej samej porcji.
                async with db.begin_nested():
                    await apply_result(
                        db,
                        candidate_id=candidate_id,
                        digest=digest,
                        result=entry.result,
                        model=model,
                        stats=stats,
                    )
            except Exception as exc:  # noqa: BLE001 — wiersz, nie bieg
                stats.errors += 1
                logger.warning(
                    "[cv-reparse] zapis padł dla id=%s: %s",
                    candidate_id,
                    type(exc).__name__,
                )
                await _mark_write_failure(db, candidate_id, digest)
                continue
            since_commit += 1
            if since_commit >= commit_every:
                await db.commit()
                since_commit = 0
    finally:
        await db.commit()


async def _mark_write_failure(db: AsyncSession, candidate_id: int, digest: str) -> None:
    """Znacznik `failed` po błędzie zapisu, osobnym savepointem.

    Odpowiedź jest już zapłacona, a savepoint wiersza cofnął też znacznik —
    bez tego deterministyczny błąd zapisu płaciłby przy każdym biegu, bo limit
    prób liczy tylko znaczniki.
    """
    try:
        async with db.begin_nested():
            candidate = await db.get(Candidate, candidate_id)
            if candidate is None:
                return
            full_digest = text_digest(candidate.raw_cv_text or "")
            if full_digest.startswith(digest):
                _mark(candidate, full_digest, "failed")
                await db.flush()
    except Exception as exc:  # noqa: BLE001 — znacznik to ratunek, nie warunek
        logger.warning(
            "[cv-reparse] znacznik po błędzie padł dla id=%s: %s",
            candidate_id,
            type(exc).__name__,
        )


def bulk_model() -> str:
    return model_for(AIFeatureKey.cv_backfill)


async def wait_for_batch(client: Any, batch_id: str, *, poll_s: float) -> Any:
    """Czekaj na koniec paczki (`processing_status == "ended"`)."""
    while True:
        batch = await asyncio.to_thread(client.messages.batches.retrieve, batch_id)
        if batch.processing_status == "ended":
            return batch
        logger.info(
            "[cv-reparse] paczka %s: %s, %s",
            batch_id,
            batch.processing_status,
            getattr(batch, "request_counts", None),
        )
        await asyncio.sleep(poll_s)
