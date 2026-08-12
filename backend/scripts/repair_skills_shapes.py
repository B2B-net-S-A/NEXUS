"""Naprawa kształtu `candidates.skills` — jednorazowy bieg po istniejących wierszach.

Skąd się wzięło: granica zapisu enrichmentu nigdy nie walidowała typu, więc
JSONB przyjmował wszystko, co oddał model. Pomiar na prodzie (2026-08-12):
192 historyczne stringi z zakodowaną tablicą + 20 obiektów
`{"level", "technologies"}` + 5 JSON-nulli ze ścieżki interaktywnej, plus
113/150 stringów z biegu kalibracyjnego Fali 3 (Haiku). Do tego część tablic
trzyma gołe stringi zamiast kanonu `[{"name", "level", ...}]`.

Co robi: przepuszcza każdy niepusty `skills` przez `normalize_llm_skills`
(ten sam normalizator, który od teraz pilnuje granicy zapisu) i zapisuje
wynik, gdy różni się od stanu w bazie. Zero LLM — czysta transformacja.

Czego NIE robi:
  * nie dotyka wierszy z lockiem `_manual_override_skills` — człowiek wygrywa
    z każdą naprawą;
  * nie CZYŚCI kolumny, gdy normalizacja nie ocali nic (np. string
    niedekodowalny) — zostawia wiersz nietknięty i raportuje go w
    `unsalvageable`; kasowanie danych to inna decyzja niż naprawa kształtu;
  * nie zeruje JSON-nulli (`jsonb_typeof = 'null'`) — scope backfillu i tak
    traktuje je jako puste, a zamiana `'null'::jsonb` na SQL NULL nie zmienia
    żadnej decyzji w aplikacji.

Naprawieni kandydaci trafiają do outboxu reindeksu w rytmie commitów — tekst
embeddingu zawiera skills, więc naprawa kształtu bez re-embeddingu zostawiłaby
wektory policzone na starym śmieciu (ta sama lekcja co #1096).

Użycie (w kontenerze backendu):
    python -m scripts.repair_skills_shapes --dry-run   # domyślne: tylko raport
    python -m scripts.repair_skills_shapes --commit
    python -m scripts.repair_skills_shapes --commit --after-id 12345
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.services.cv_enrichment import normalize_llm_skills

logger = logging.getLogger(__name__)

PAGE_SIZE = 500
COMMIT_EVERY = 200


def _needs_repair(current: object, normalized: list[dict] | None) -> bool:
    """Czy zapis zmienia stan? Kanon idempotentnie normalizuje się do siebie."""

    return normalized is not None and normalized != current


async def repair(*, commit: bool, after_id: int = 0, limit: int | None = None) -> dict:
    stats = {
        "scanned": 0,
        "repaired": 0,
        "already_canonical": 0,
        "unsalvageable": 0,
        "locked": 0,
        "last_id": after_id,
        "reindex_enqueued": 0,
    }
    from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex

    async with AsyncSessionLocal() as db:
        pending_reindex: list[int] = []

        async def _flush() -> None:
            if not pending_reindex:
                return
            enqueued = await record_bulk_reindex(db, CANDIDATE, pending_reindex)
            stats["reindex_enqueued"] += int(enqueued or 0)
            pending_reindex.clear()

        since_commit = 0
        cursor = after_id
        while True:
            rows = (
                (
                    await db.execute(
                        select(Candidate)
                        .where(
                            Candidate.id > cursor,
                            Candidate.skills.isnot(None),
                        )
                        .order_by(Candidate.id)
                        .limit(PAGE_SIZE)
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
                if limit and stats["scanned"] >= limit:
                    await _flush()
                    if commit:
                        await db.commit()
                    return stats
                stats["scanned"] += 1

                extracted = candidate.cv_extracted_data
                if isinstance(extracted, dict) and extracted.get(
                    "_manual_override_skills"
                ):
                    stats["locked"] += 1
                    continue

                current = candidate.skills
                if isinstance(current, list) and not current:
                    # `[]` to poprawny (pusty) kanon — nie ma czego naprawiać.
                    stats["already_canonical"] += 1
                    continue

                normalized = normalize_llm_skills(current)
                if normalized is None:
                    stats["unsalvageable"] += 1
                    logger.info(
                        "[repair-skills] id=%s: nieratowalne (typ %s) — nietknięte",
                        candidate.id,
                        type(current).__name__,
                    )
                    continue
                if not _needs_repair(current, normalized):
                    stats["already_canonical"] += 1
                    continue

                if commit:
                    candidate.skills = normalized
                    pending_reindex.append(candidate.id)
                stats["repaired"] += 1

                since_commit += 1
                if commit and since_commit >= COMMIT_EVERY:
                    await _flush()
                    await db.commit()
                    since_commit = 0
                    logger.info(
                        "[repair-skills] scanned=%s repaired=%s last_id=%s",
                        stats["scanned"],
                        stats["repaired"],
                        stats["last_id"],
                    )

        await _flush()
        if commit:
            await db.commit()
    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--commit", action="store_true", help="faktycznie zapisz naprawy")
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stats = await repair(
        commit=bool(args.commit), after_id=args.after_id, limit=args.limit
    )
    header = "NAPRAWIONO" if args.commit else "DO NAPRAWY (dry-run, nic nie zapisano)"
    print(f"=== {header} ===")
    for key, value in stats.items():
        print(f"{key:20}: {value:,}" if isinstance(value, int) else f"{key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
