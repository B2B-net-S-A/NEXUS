"""Wypełnij kolekcję pasaży CV — Fala 2, krok 2.

    # POMIAR — nie liczy embeddingów, nie pisze do Qdranta, nie kosztuje nic
    python -m scripts.backfill_cv_passages --dry-run

    # zapis, wznawialny; kursor idzie po candidate_id
    python -m scripts.backfill_cv_passages --commit --batch 128
    python -m scripts.backfill_cv_passages --commit --after-id 20000

DLACZEGO DRY-RUN JEST DOMYŚLNY I DLACZEGO LICZY NA PRAWDZIWEJ BAZIE.
Rozmiar tej kolekcji jest ograniczony twardo: kontener Qdranta ma 2 GB RAM,
z czego ~260 MB zajmuje już kolekcja kandydatów. Szacunek zrobiony wcześniej na
SYMULOWANYM rozkładzie długości CV dał ~254 tys. punktów i 991 MB w f32 — ale
symulacja rozkładu to nie pomiar korpusu. Ten tryb czyta realne `raw_cv_text`,
tnie je tym samym chunkerem, którego użyje zapis, i podaje liczby, na których
wolno oprzeć decyzję.

Zapis jest wznawialny, bo Coolify restartuje kontener przy KAŻDYM pushu na main,
a pełny przebieg to ćwierć miliona embeddingów. Bieg bez kursora zaczynałby od
zera po każdym wdrożeniu i przy odpowiednio częstych deployach mógłby nigdy nie
dojść do końca — ta sama pułapka, która latami trzymała lukę w plikach Traffita.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.services.cv_passages import split_cv_into_passages  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_cv_passages")

# Minimalna długość tekstu, żeby CV w ogóle weszło do indeksu. Poniżej tego
# `raw_cv_text` bywa artefaktem ekstrakcji (sama stopka, jedno słowo), a nie
# dokumentem — pasaż z tego byłby szumem dopasowującym się do wszystkiego.
MIN_CV_CHARS = 200

VECTOR_DIM = 1024
QDRANT_LIMIT_MB = 2048
CANDIDATES_COLLECTION_MB = 260

# Twardy limit Voyage: jedno wywołanie przyjmuje najwyżej 128 tekstów, a
# `_voyage_embed_batch` NIE tnie wewnętrznie — nadmiar to odrzucona paczka.
# Bufor skryptu przekracza próg przy każdym flushu (ostatni kandydat dokłada
# swoje pasaże PO przekroczeniu progu), a pomiar na produkcji znalazł CV z 261
# pasażami, które samo jedno rozsadza dowolny rozmiar bufora. Stąd cięcie tutaj.
VOYAGE_MAX_BATCH = 128


async def embed_in_slices(texts: list[str], embed_fn) -> list | None:
    """Zaembeduj listę dowolnej długości plastrami po `VOYAGE_MAX_BATCH`.

    Zwraca listę wektorów wyrównaną z wejściem albo None, gdy KTÓRYKOLWIEK
    plaster padł — częściowy wynik przesunąłby przypisanie wektorów do pasaży
    o długość brakującego plastra i pasaże jednego kandydata dostałyby wektory
    innego. Wyrównanie jest tu ważniejsze niż ratowanie części paczki; wołający
    pomija paczkę i idzie dalej, a wznowienie po `--after-id` ją dobierze.
    """

    vectors: list = []
    for offset in range(0, len(texts), VOYAGE_MAX_BATCH):
        piece = texts[offset : offset + VOYAGE_MAX_BATCH]
        try:
            got = await embed_fn(piece, input_type="document")
        except Exception as exc:  # noqa: BLE001
            # Kontrakt `None-znaczy-pomiń` nie może zależeć od tego, czy AKURAT
            # to embed_fn łapie własne wyjątki (`_voyage_embed_batch` dziś łapie
            # i zwraca None — ale to wiedza o cudzym wnętrzu, nie gwarancja).
            # Przelotny błąd sieci w wielogodzinnym biegu ma kosztować jedną
            # paczkę, nie cały proces.
            logger.warning("embed_fn rzucił zamiast zwrócić None: %s", exc)
            return None
        if not got or len(got) != len(piece):
            return None
        vectors.extend(got)
    return vectors


async def _iter_candidates(db, *, after_id: int, limit: int | None, page: int = 500):
    """Keyset pagination po `id` — NIE `.all()` na całym zakresie.

    Pełny scope to ~50 tys. wierszy z pełnym tekstem CV; wczytanie ich naraz to
    gigabajty w pamięci jednego procesu, który dzieli event loop z ruchem
    rekruterów.
    """

    seen = 0
    cursor = after_id
    while True:
        rows = (
            await db.execute(
                select(Candidate.id, Candidate.raw_cv_text)
                .where(
                    Candidate.id > cursor,
                    Candidate.raw_cv_text.isnot(None),
                    func.length(Candidate.raw_cv_text) >= MIN_CV_CHARS,
                )
                .order_by(Candidate.id)
                .limit(page)
            )
        ).all()
        if not rows:
            return
        for candidate_id, cv_text in rows:
            yield candidate_id, cv_text
            seen += 1
            if limit and seen >= limit:
                return
        cursor = rows[-1][0]


async def measure(after_id: int, limit: int | None) -> None:
    """Policz, ile to będzie punktów i megabajtów — bez zapisu i bez kosztu."""

    counts: list[int] = []
    candidates = 0
    chars = 0

    async with AsyncSessionLocal() as db:
        async for candidate_id, cv_text in _iter_candidates(
            db, after_id=after_id, limit=limit
        ):
            candidates += 1
            chars += len(cv_text or "")
            counts.append(len(split_cv_into_passages(cv_text)))
            if candidates % 5000 == 0:
                logger.info("  … przetworzono %s kandydatów", f"{candidates:,}")

    if not counts:
        logger.warning("Brak kandydatów z tekstem CV — nie ma czego mierzyć.")
        return

    total_points = sum(counts)
    ordered = sorted(counts)
    p90 = ordered[int(0.9 * len(ordered)) - 1] if len(ordered) > 1 else ordered[0]

    f32_mb = total_points * VECTOR_DIM * 4 / 1024 / 1024
    int8_mb = total_points * VECTOR_DIM / 1024 / 1024
    # Voyage liczy tokeny; ~4 znaki na token dla tekstu mieszanego PL/EN.
    tokens = chars / 4

    logger.info("")
    logger.info("=== POMIAR (nic nie zapisano) ===")
    logger.info(
        "kandydatów z tekstem CV >= %s zn. : %s", MIN_CV_CHARS, f"{candidates:,}"
    )
    logger.info(
        "pasaży na CV                     : średnio %.1f, p90 %s, max %s",
        total_points / candidates,
        p90,
        max(counts),
    )
    logger.info("PUNKTÓW W INDEKSIE               : %s", f"{total_points:,}")
    logger.info("")
    logger.info("wektory f32                      : %s MB", f"{f32_mb:,.0f}")
    logger.info("wektory int8 (tak zbudujemy)     : %s MB", f"{int8_mb:,.0f}")
    logger.info("kolekcja kandydatów (istnieje)   : ~%s MB", CANDIDATES_COLLECTION_MB)
    logger.info(
        "RAZEM int8                       : %s MB / limit %s MB",
        f"{int8_mb + CANDIDATES_COLLECTION_MB:,.0f}",
        QDRANT_LIMIT_MB,
    )
    logger.info("")
    logger.info("tokenów do zaembedowania         : ~%s", f"{tokens:,.0f}")
    logger.info("")

    total_int8 = int8_mb + CANDIDATES_COLLECTION_MB
    if total_int8 > QDRANT_LIMIT_MB * 0.7:
        logger.warning(
            "UWAGA: %s MB to ponad 70%% limitu kontenera — zapas na graf HNSW, "
            "payload i skoki jest zbyt mały. NIE uruchamiaj zapisu bez decyzji "
            "o podniesieniu limitu Qdranta.",
            f"{total_int8:,.0f}",
        )
    else:
        logger.info(
            "Mieści się z zapasem (%.0f%% limitu). f32 zająłby %.0f%% — dlatego "
            "kwantyzacja jest warunkiem, nie optymalizacją.",
            100 * total_int8 / QDRANT_LIMIT_MB,
            100 * (f32_mb + CANDIDATES_COLLECTION_MB) / QDRANT_LIMIT_MB,
        )


async def backfill(after_id: int, limit: int | None, batch: int) -> None:
    """Policz embeddingi i zapisz pasaże. Wznawialne po `--after-id`."""

    from qdrant_client import QdrantClient, models as qmodels

    from app.core.config import settings
    from app.services.embedding_service import _voyage_embed_batch
    from app.services.passage_index import (
        PAYLOAD_CANDIDATE_ID,
        ensure_passages_collection,
        point_id_for,
        replace_candidate_passages,
    )

    client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    if not ensure_passages_collection(client):
        logger.error("Nie udało się przygotować kolekcji pasaży — przerywam.")
        return

    written = 0
    skipped = 0
    last_id = after_id

    async with AsyncSessionLocal() as db:
        pending: list[tuple[int, list]] = []

        async def flush() -> None:
            nonlocal written, skipped
            if not pending:
                return
            texts = [p.text for _, passages in pending for p in passages]
            vectors = await embed_in_slices(texts, _voyage_embed_batch)
            if vectors is None:
                logger.warning(
                    "Voyage nie zwrócił kompletu dla %s tekstów — pomijam paczkę "
                    "(wznowienie po --after-id ją dobierze).",
                    len(texts),
                )
                skipped += len(pending)
                pending.clear()
                return

            offset = 0
            for candidate_id, passages in pending:
                points = [
                    qmodels.PointStruct(
                        id=point_id_for(candidate_id, passage.index),
                        vector=vectors[offset + i],
                        payload={
                            PAYLOAD_CANDIDATE_ID: candidate_id,
                            "passage_index": passage.index,
                            "text": passage.text,
                        },
                    )
                    for i, passage in enumerate(passages)
                ]
                offset += len(passages)
                if replace_candidate_passages(client, candidate_id, points):
                    written += 1
                else:
                    skipped += 1
            pending.clear()

        async for candidate_id, cv_text in _iter_candidates(
            db, after_id=after_id, limit=limit
        ):
            last_id = candidate_id
            passages = split_cv_into_passages(cv_text)
            if not passages:
                skipped += 1
                continue
            pending.append((candidate_id, passages))
            if sum(len(p) for _, p in pending) >= batch:
                await flush()
                logger.info(
                    "  zapisano %s kandydatów (ostatni id=%s)", f"{written:,}", last_id
                )

        await flush()

    logger.info("")
    logger.info("=== ZAPIS ZAKOŃCZONY ===")
    logger.info("zapisanych kandydatów : %s", f"{written:,}")
    logger.info("pominiętych           : %s", f"{skipped:,}")
    logger.info("ostatni id            : %s  (wznów: --after-id %s)", last_id, last_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Domyślne. Policz punkty i pamięć na prawdziwych CV; nic nie zapisuj.",
    )
    mode.add_argument(
        "--commit", action="store_true", help="Policz embeddingi i zapisz do Qdranta."
    )
    parser.add_argument("--after-id", type=int, default=0, help="Wznów od tego id.")
    parser.add_argument("--limit", type=int, default=None, help="Ogranicz liczbę CV.")
    parser.add_argument(
        "--batch", type=int, default=128, help="Pasaży na jedno wywołanie Voyage."
    )
    args = parser.parse_args()

    if args.commit:
        asyncio.run(backfill(args.after_id, args.limit, args.batch))
    else:
        asyncio.run(measure(args.after_id, args.limit))


if __name__ == "__main__":
    main()
