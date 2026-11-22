"""Odczyt CV z integracji wsadem (Message Batches API, −50%).

Decyzja Artura z 22.11.2026. Pomiar 22.11 (``docs/claude/generator-cv/
odczyty-parsera-cv-konto-scraperow.md``): konto scraperów pracuj.pl i JJIT
robi 86% odczytów parsera CV i nikt nie czeka na ich wynik. Wsad obejmuje
tylko wgrania do istniejących profili (``POST /api/candidates/{id}/cv``);
``/from-cv`` zostaje na żywo, bo duplikat po e-mailu z CV oraz telefonie
z imieniem i nazwiskiem trzeba sprawdzić przed założeniem profilu.

Przebieg:

* wgranie z integracji robi te same sprawdzenia co dotąd (plik już odczytany,
  kopia z kwarantanny, wyciągnięcie tekstu) i zamiast modelu wstawia wiersz
  ``cv_parse_batch_items`` (``enqueue``),
* pętla ``cv_parse_batch`` (worker) wysyła zebrane CV jedną paczką, odbiera
  wynik zakończonej paczki i zapisuje go tą samą ścieżką co odczyt na żywo
  (``api.candidates._apply_batch_document_read``),
* awaria nie gubi odczytu: błąd utworzenia paczki, wynik inny niż
  ``succeeded``, niepoprawny JSON, błąd zapisu i brak wyniku po
  ``CV_PARSER_BATCH_FALLBACK_HOURS`` dają odczyt na żywo (status ``fallback``,
  potem ``live``),
* model z rejestru (``cv_parser``), operacja w ``ai_feature`` z wyceną −50%
  (``record_batch_message_usage``). Do czasu wyniku profil ma dane
  z poprzedniego CV, a ekran pokazuje „czytamy CV” (``queued_since``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.models.cv_parse_batch import CvParseBatchItem
from app.services import cv_parse_batch_schema as schema
from app.services.ai_models import model_for

logger = logging.getLogger(__name__)

CUSTOM_ID_PREFIX = "cvp"
#: Najwięcej CV w jednej paczce (limit API: 100 000 żądań i 256 MB).
MAX_ITEMS_PER_BATCH = 500
#: Najwięcej odczytów na żywo w jednym ticku pętli (każdy ok. 20 s).
LIVE_READS_PER_TICK = 20
#: Zamknięte wiersze (bez tekstu CV) zostają do pomiaru udziału wsadu.
RETENTION_DAYS = 60


def batch_model() -> str:
    return model_for(AIFeatureKey.cv_parser)


def enabled() -> bool:
    """Czy CV z integracji może iść do kolejki zamiast odczytu na żywo."""
    from app.services.llm_providers import ANTHROPIC, api_key_configured, provider_of

    if not (settings.CV_PARSER_BATCH_ENABLED and settings.CV_ENRICHMENT_ENABLED):
        return False
    model = batch_model()
    # Paczki ma tylko Anthropic; model parsera przestawiony na innego dostawcę
    # (`CV_PARSER_MODEL`) czyta na żywo.
    return provider_of(model) == ANTHROPIC and api_key_configured(model)


def custom_id(item_id: int) -> str:
    return f"{CUSTOM_ID_PREFIX}-{item_id}"


def parse_custom_id(value: str) -> Optional[int]:
    prefix, _, rest = (value or "").partition("-")
    if prefix != CUSTOM_ID_PREFIX or not rest.isdigit():
        return None
    return int(rest)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _replaced_to_json(replaced: Any) -> Optional[dict[str, Any]]:
    if replaced is None:
        return None
    return {
        "document_id": getattr(replaced, "document_id", None),
        "cv_filename": getattr(replaced, "cv_filename", None),
    }


def _replaced_from_json(value: Optional[dict[str, Any]]) -> Any:
    from app.services.candidate_identity_quarantine import ReplacedPrimaryCv

    if not isinstance(value, dict):
        return None
    return ReplacedPrimaryCv(
        document_id=value.get("document_id"), cv_filename=value.get("cv_filename")
    )


async def supersede_open(db: AsyncSession, candidate_id: int) -> int:
    """Zamknij CV kandydata czekające w kolejce (nowsze CV, odczyt na żywo)."""
    result = await db.execute(
        update(CvParseBatchItem)
        .where(
            CvParseBatchItem.candidate_id == candidate_id,
            CvParseBatchItem.status.in_(schema.OPEN_STATUSES),
        )
        .values(status="superseded", finished_at=func.now(), raw_text=None)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def enqueue(
    db: AsyncSession,
    *,
    candidate_id: int,
    document_id: int,
    content_sha256: Optional[str],
    raw_text: str,
    trigger: str,
    actor_user_id: Optional[int],
    replaced_primary: Any,
) -> bool:
    """Wstaw CV do kolejki wsadu. `False` = kolejka wyłączona, czytaj na żywo.

    Nie commituje. Starsze CV tego kandydata w kolejce przestają być potrzebne:
    zapis i tak przyjmuje tylko bieżące główne CV.
    """
    if not enabled():
        return False
    await supersede_open(db, candidate_id)
    db.add(
        CvParseBatchItem(
            candidate_id=candidate_id,
            document_id=document_id,
            content_sha256=content_sha256,
            raw_text=raw_text,
            trigger=trigger,
            actor_user_id=actor_user_id,
            replaced_primary=_replaced_to_json(replaced_primary),
            status="queued",
        )
    )
    await db.flush()
    logger.info(
        "[cv_parse_batch] CV w kolejce wsadu candidate=%s document=%s",
        candidate_id,
        document_id,
    )
    return True


async def queued_since(db: AsyncSession, candidate_id: int) -> Optional[datetime]:
    """Od kiedy CV kandydata czeka na odczyt wsadem (stan „czytamy CV”)."""
    return await db.scalar(
        select(func.min(CvParseBatchItem.queued_at)).where(
            CvParseBatchItem.candidate_id == candidate_id,
            CvParseBatchItem.status.in_(schema.OPEN_STATUSES),
        )
    )


@dataclass
class TickStats:
    submitted: int = 0
    batches: int = 0
    applied: int = 0
    not_applied: int = 0
    fallback: int = 0
    live: int = 0
    timed_out: int = 0
    errors: list[str] = field(default_factory=list)

    def any(self) -> bool:
        return bool(
            self.submitted
            or self.applied
            or self.not_applied
            or self.fallback
            or self.live
            or self.timed_out
        )


async def _to_fallback(db: AsyncSession, ids: list[int], reason: str) -> None:
    if not ids:
        return
    await db.execute(
        update(CvParseBatchItem)
        .where(
            CvParseBatchItem.id.in_(ids),
            CvParseBatchItem.status.in_(("queued", "submitted")),
        )
        .values(status="fallback", error=reason[:255])
        .execution_options(synchronize_session=False)
    )


async def _close(
    db: AsyncSession, item_id: int, status: str, error: Optional[str]
) -> None:
    await db.execute(
        update(CvParseBatchItem)
        .where(CvParseBatchItem.id == item_id)
        .values(
            status=status,
            error=(error or None) and error[:255],
            finished_at=func.now(),
            raw_text=None,
        )
        .execution_options(synchronize_session=False)
    )


async def submit_queued(client: Any, stats: TickStats) -> None:
    """Wyślij CV z kolejki jedną paczką."""
    from app.core.database import AsyncSessionLocal
    from app.services.claude_client import batch_request_params
    from app.services.cv_parser import claude_cv_request_params

    async with AsyncSessionLocal() as db:
        items = list(
            (
                await db.scalars(
                    select(CvParseBatchItem)
                    .where(CvParseBatchItem.status == "queued")
                    .order_by(CvParseBatchItem.id)
                    .limit(MAX_ITEMS_PER_BATCH)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        if not items:
            return
        model = batch_model()
        requests = [
            {
                "custom_id": custom_id(item.id),
                "params": batch_request_params(
                    claude_cv_request_params(item.raw_text or "", model=model)
                ),
            }
            for item in items
        ]
        try:
            batch = await asyncio.to_thread(
                client.messages.batches.create, requests=requests
            )
        except Exception as exc:  # noqa: BLE001 — paczka nie poszła, czytamy na żywo
            reason = f"batch_create_failed:{type(exc).__name__}"
            logger.warning("[cv_parse_batch] %s (%d CV)", reason, len(items))
            await _to_fallback(db, [item.id for item in items], reason)
            await db.commit()
            stats.fallback += len(items)
            stats.errors.append(reason)
            return
        now = _utcnow()
        for item in items:
            item.status = "submitted"
            item.batch_id = batch.id
            item.model = model
            item.submitted_at = now
        await db.commit()
        stats.submitted += len(items)
        stats.batches += 1
        logger.info("[cv_parse_batch] paczka %s: %d CV", batch.id, len(items))


async def _meter(message: Any, *, model: str, user_id: Optional[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.ai_quota import ai_feature
    from app.services.claude_client import record_batch_message_usage

    async with AsyncSessionLocal() as db:
        async with ai_feature(db, AIFeatureKey.cv_parser, user_id=user_id):
            record_batch_message_usage(message, model=model)


async def _apply_result(
    item: CvParseBatchItem, entry: Any
) -> tuple[str, Optional[str]]:
    """Jeden wynik paczki → (status wiersza, powód)."""
    from app.api.candidates import _apply_batch_document_read
    from app.services.cv_parser import (
        finalize_claude_cv_output,
        parsed_from_claude_message,
    )

    result = getattr(entry, "result", None) if entry is not None else None
    result_type = getattr(result, "type", None)
    if result_type != "succeeded":
        return "fallback", f"result_{result_type or 'missing'}"

    message = result.message
    model = item.model or batch_model()
    try:
        await _meter(message, model=model, user_id=item.actor_user_id)
    except Exception as exc:  # noqa: BLE001 — telemetria nie blokuje zapisu
        logger.warning("[cv_parse_batch] licznik AI padł: %s", type(exc).__name__)

    raw_text = item.raw_text or ""
    try:
        parsed = parsed_from_claude_message(message, raw_text, model=model)
    except json.JSONDecodeError:
        parsed = None
    if parsed is None:
        return "fallback", "invalid_json"
    parsed = finalize_claude_cv_output(parsed, raw_text)

    try:
        applied = await _apply_batch_document_read(
            candidate_id=item.candidate_id,
            document_id=item.document_id,
            expected_hash=item.content_sha256,
            raw_text=raw_text,
            parsed=parsed,
            trigger=item.trigger,
            replaced_primary=_replaced_from_json(item.replaced_primary),
        )
    except Exception as exc:  # noqa: BLE001 — wiersz, nie pętla
        return "fallback", f"apply_failed:{type(exc).__name__}"
    return ("done", None) if applied else ("done", "not_applied")


async def collect_ended(client: Any, stats: TickStats) -> None:
    """Odbierz wyniki zakończonych paczek."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        batch_ids = list(
            (
                await db.scalars(
                    select(CvParseBatchItem.batch_id)
                    .where(
                        CvParseBatchItem.status == "submitted",
                        CvParseBatchItem.batch_id.is_not(None),
                    )
                    .distinct()
                )
            ).all()
        )
    for batch_id in batch_ids:
        try:
            batch = await asyncio.to_thread(client.messages.batches.retrieve, batch_id)
        except Exception as exc:  # noqa: BLE001 — następny tick spyta znowu
            stats.errors.append(f"retrieve_failed:{type(exc).__name__}")
            continue
        if getattr(batch, "processing_status", None) != "ended":
            continue
        try:
            # Całość w wątku: `results()` to leniwy strumień JSONL.
            results = await asyncio.to_thread(
                lambda: list(client.messages.batches.results(batch_id))
            )
        except Exception as exc:  # noqa: BLE001 — następny tick spyta znowu
            stats.errors.append(f"results_failed:{type(exc).__name__}")
            continue
        by_item: dict[int, Any] = {}
        for entry in results:
            item_id = parse_custom_id(getattr(entry, "custom_id", "") or "")
            if item_id is not None:
                by_item[item_id] = entry
        async with AsyncSessionLocal() as db:
            items = list(
                (
                    await db.scalars(
                        select(CvParseBatchItem).where(
                            CvParseBatchItem.batch_id == batch_id,
                            CvParseBatchItem.status == "submitted",
                        )
                    )
                ).all()
            )
            db.expunge_all()
        for item in items:
            status, reason = await _apply_result(item, by_item.get(item.id))
            async with AsyncSessionLocal() as db:
                if status == "fallback":
                    await _to_fallback(db, [item.id], reason or "fallback")
                    stats.fallback += 1
                else:
                    await _close(db, item.id, status, reason)
                    if reason == "not_applied":
                        stats.not_applied += 1
                    else:
                        stats.applied += 1
                await db.commit()


async def fallback_timed_out(client: Any, stats: TickStats, *, now: datetime) -> None:
    """CV bez wyniku po `CV_PARSER_BATCH_FALLBACK_HOURS` → odczyt na żywo.

    Paczka, w której nic już nie czeka, jest anulowana (odczyt na żywo idzie
    i tak, a anulowane żądania bez wyniku nie są płatne).
    """
    from app.core.database import AsyncSessionLocal

    cutoff = now - timedelta(hours=settings.CV_PARSER_BATCH_FALLBACK_HOURS)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(CvParseBatchItem.id, CvParseBatchItem.batch_id).where(
                    CvParseBatchItem.status.in_(("queued", "submitted")),
                    CvParseBatchItem.queued_at < cutoff,
                )
            )
        ).all()
        if not rows:
            return
        await _to_fallback(db, [row.id for row in rows], "timeout")
        await db.commit()
        stats.timed_out += len(rows)
        batch_ids = {row.batch_id for row in rows if row.batch_id}
        still_waiting = set(
            (
                await db.scalars(
                    select(CvParseBatchItem.batch_id)
                    .where(
                        CvParseBatchItem.batch_id.in_(batch_ids),
                        CvParseBatchItem.status == "submitted",
                    )
                    .distinct()
                )
            ).all()
        )
    for batch_id in batch_ids - still_waiting:
        try:
            await asyncio.to_thread(client.messages.batches.cancel, batch_id)
        except Exception as exc:  # noqa: BLE001 — paczka mogła się już skończyć
            logger.info(
                "[cv_parse_batch] anulowanie %s: %s", batch_id, type(exc).__name__
            )


async def read_fallbacks_live(
    stats: TickStats, *, limit: int = LIVE_READS_PER_TICK
) -> None:
    """Odczyt na żywo dla CV, których paczka nie przeczytała.

    Ta sama funkcja co wgranie przez człowieka (bez `defer_to_batch`), więc
    sprawdza wszystko od nowa: plik nadal główny, ten sam skrót, kwarantanna.
    Status `live` dopiero po odczycie: proces zabity w trakcie zostawia
    wiersz w `fallback` i następny tick czyta go jeszcze raz.
    """
    from app.api.candidates import _enrich_candidate_from_document_task
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        items = list(
            (
                await db.scalars(
                    select(CvParseBatchItem)
                    .where(CvParseBatchItem.status == "fallback")
                    .order_by(CvParseBatchItem.id)
                    .limit(limit)
                )
            ).all()
        )
        db.expunge_all()
    for item in items:
        await _enrich_candidate_from_document_task(
            item.candidate_id,
            item.document_id,
            item.content_sha256,
            trigger=item.trigger,
            actor_user_id=item.actor_user_id,
            replaced_primary=_replaced_from_json(item.replaced_primary),
        )
        async with AsyncSessionLocal() as db:
            # Odczyt na żywo zamknął wiersz jako `superseded` (zapis do profilu)
            # albo nie dotknął go (plik już nie główny, odczyt bez zmian) —
            # w obu razach to odczyt zamiast paczki.
            await _close(db, item.id, "live", item.error)
            await db.commit()
        stats.live += 1


async def purge_closed(*, now: datetime) -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(CvParseBatchItem).where(
                CvParseBatchItem.status.not_in(schema.OPEN_STATUSES),
                CvParseBatchItem.finished_at < now - timedelta(days=RETENTION_DAYS),
            )
        )
        await db.commit()
        return int(result.rowcount or 0)


def make_client() -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=3)


async def run_tick(client: Any, *, now: Optional[datetime] = None) -> TickStats:
    """Jeden obrót pętli. Kolejność: limit czasu, wyniki, wysyłka, odczyt na żywo.

    Odczyt na żywo idzie także przy wyłączonej kolejce: CV już w niej będące
    nie mogą czekać na ponowne włączenie.
    """
    now = now or _utcnow()
    stats = TickStats()
    await fallback_timed_out(client, stats, now=now)
    await collect_ended(client, stats)
    if enabled():
        await submit_queued(client, stats)
    else:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            ids = list(
                (
                    await db.scalars(
                        select(CvParseBatchItem.id).where(
                            CvParseBatchItem.status == "queued"
                        )
                    )
                ).all()
            )
            await _to_fallback(db, ids, "batch_disabled")
            await db.commit()
            stats.fallback += len(ids)
    await read_fallbacks_live(stats)
    await purge_closed(now=now)
    return stats
