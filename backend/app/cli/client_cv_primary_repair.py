"""Główne CV z pliku CV do klienta — naprawa profili (15.10.2026, D3).

Od 13.10.2026 kafelek „Wgraj nowe CV” w panelu osoby robił z gotowego CV do
klienta („B2B_…docx”) główne CV profilu: AI czytało profil z wersji firmowej,
a plik stawał się „Oryginałem CV” rekrutacji. Od 15.10.2026 kafelek zapisuje
taki plik jako CV do klienta (`app.services.client_cv_upload`). Ten skrypt
naprawia profile z okresu przejściowego (pomiar 15.10: 27 plików).

Uruchomienie (w kontenerze backendu)::

    python -m app.cli.client_cv_primary_repair --until 2026-10-15T21:00:00+02:00
    python -m app.cli.client_cv_primary_repair --until … --apply --expected 25

Zasady:

* wybór: główne CV osoby nazwane jak CV do klienta (Word „…B2B…”, ta sama
  reguła co kafelek — PDF zostaje CV kandydata), niewykasowane, wgrane od
  13.10.2026 00:00 czasu firmy, a z ``--until`` — przed wdrożeniem kafelka
  rozpoznającego CV do klienta (później „B2B” jako główne ktoś wskazał sam);
* następca: plik PDF/DOC/DOCX osoby, który może być bieżącym CV
  (`cv_source.current_cv_filters`) i nie jest CV do klienta, w kolejności
  `get_current_cv`: najpierw rodzaj „cv”, potem najnowszy (bez daty na końcu).
  Osoba bez następcy zostaje bez zmian — raport ją liczy;
* ``--apply`` wymaga ``--expected`` równego liczbie osób z następcą z próby na
  sucho. Inny stan bazy niż w próbie przerywa bieg przed pierwszym zapisem;
* każda osoba w osobnej transakcji: plik CV do klienta traci „główne”,
  następca je dostaje, kopie CV etapu z bajtami pliku do klienta dostają CV
  osoby (``client_cv_repair``), a po commicie AI czyta profil z następcy.
  Plik do klienta zostaje w profilu jako „CV dla klientów”;
* paragon ``app_settings['client_cv_primary_repair_2026_10']`` niesie same
  liczby; ponowne ``--apply`` przy istniejącym paragonie jest odrzucane.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update

logger = logging.getLogger(__name__)

RECEIPT_KEY = "client_cv_primary_repair_2026_10"
# Kafelek „Wgraj nowe CV” wszedł 13.10.2026 — wcześniejsze pliki „B2B” jako
# główne CV to głównie import Traffita, osobny temat.
CUTOFF = datetime(2026, 10, 13, tzinfo=ZoneInfo("Europe/Warsaw"))
_CV_EXT = (".pdf", ".doc", ".docx")


@dataclass(frozen=True)
class Planned:
    candidate_id: int
    client_cv_id: int
    client_cv_sha256: Optional[str]
    successor_id: Optional[int]
    stage_copies: int
    # Rodzaj i rozszerzenie następcy — do raportu na sucho (bez nazw plików).
    successor_kind: Optional[str] = None
    successor_ext: Optional[str] = None


async def plan(
    db,
    *,
    candidate_ids: Optional[list[int]] = None,
    until: Optional[datetime] = None,
) -> list[Planned]:
    """Osoby do naprawy. ``candidate_ids`` zawęża bieg (testy na wspólnej bazie)."""
    from sqlalchemy import case

    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.services.client_cv_upload import CLIENT_CV_NAME, looks_like_client_cv
    from app.services.cv_source import current_cv_filters

    query = select(
        CandidateDocument.id,
        CandidateDocument.candidate_id,
        CandidateDocument.filename,
        CandidateDocument.content_sha256,
    ).where(
        CandidateDocument.is_primary.is_(True),
        CandidateDocument.document_kind == CandidateDocumentKind.cv,
        CandidateDocument.source_deleted_at.is_(None),
        CandidateDocument.uploaded_at >= CUTOFF,
    )
    if candidate_ids is not None:
        query = query.where(CandidateDocument.candidate_id.in_(candidate_ids))
    if until is not None:
        query = query.where(CandidateDocument.uploaded_at < until)
    planned: list[Planned] = []
    for doc_id, candidate_id, filename, sha256 in (
        await db.execute(query.order_by(CandidateDocument.candidate_id))
    ).all():
        if not looks_like_client_cv(filename or ""):
            continue
        others = (
            await db.execute(
                select(
                    CandidateDocument.id,
                    CandidateDocument.filename,
                    CandidateDocument.document_kind,
                )
                .where(
                    CandidateDocument.candidate_id == candidate_id,
                    CandidateDocument.id != doc_id,
                    *current_cv_filters(),
                )
                # Kolejność `cv_source.current_cv_ordering` bez „głównego”
                # (główny jest naprawiany plik). Bez daty na końcu — Postgres
                # stawia NULL pierwszy przy DESC.
                .order_by(
                    case(
                        (
                            CandidateDocument.document_kind == CandidateDocumentKind.cv,
                            0,
                        ),
                        else_=1,
                    ),
                    CandidateDocument.uploaded_at.desc().nulls_last(),
                    CandidateDocument.id.desc(),
                )
            )
        ).all()
        successor, successor_kind, successor_ext = next(
            (
                (other_id, getattr(kind, "value", str(kind)), ext)
                for other_id, name, kind in others
                if (ext := os.path.splitext((name or "").lower())[1]) in _CV_EXT
                and not CLIENT_CV_NAME.search(name or "")
            ),
            (None, None, None),
        )
        copies = 0
        if sha256:
            copies = await db.scalar(
                select(func.count())
                .select_from(CandidateStageCV)
                .where(
                    CandidateStageCV.candidate_id == candidate_id,
                    CandidateStageCV.original_cv_sha256 == sha256,
                )
            )
        planned.append(
            Planned(
                candidate_id=candidate_id,
                client_cv_id=doc_id,
                client_cv_sha256=sha256,
                successor_id=successor,
                stage_copies=int(copies or 0),
                successor_kind=successor_kind,
                successor_ext=successor_ext,
            )
        )
    return planned


def summarize(items: list[Planned]) -> dict[str, Any]:
    ready = [item for item in items if item.successor_id is not None]
    return {
        "found": len(items),
        "with_successor": len(ready),
        "without_successor": len(items) - len(ready),
        "stage_copies": sum(item.stage_copies for item in ready),
        # Czym jest następca: rodzaj „other” to zwykle nieopisany plik z importu.
        "successor_kinds": dict(
            Counter(f"{item.successor_kind}{item.successor_ext}" for item in ready)
        ),
        # Same identyfikatory — bez nazw plików i osób (logi bywają publiczne).
        "candidate_ids": [item.candidate_id for item in ready],
        "skipped_candidate_ids": [
            item.candidate_id for item in items if item.successor_id is None
        ],
    }


async def repair_one(db, item: Planned):
    """Następca zostaje głównym CV; zwraca stan sprzed zmiany albo ``None``.

    Stan bazy sprawdzamy jeszcze raz pod blokadą: od próby na sucho ktoś mógł
    sam wskazać inne główne CV.
    """
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.services.candidate_identity_quarantine import ReplacedPrimaryCv
    from app.services.candidate_stage_cv_service import (
        restore_stage_copies_after_quarantine,
    )

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"{RECEIPT_KEY}:{item.candidate_id}"},
    )
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == item.candidate_id).with_for_update()
    )
    client_cv = await db.get(CandidateDocument, item.client_cv_id)
    successor = await db.get(CandidateDocument, item.successor_id)
    if (
        candidate is None
        or client_cv is None
        or successor is None
        or not client_cv.is_primary
        or successor.source_deleted_at is not None
    ):
        return None
    replaced = ReplacedPrimaryCv(
        document_id=client_cv.id, cv_filename=candidate.cv_filename
    )
    # Częściowy UNIQUE na aktywne główne CV: najpierw zdjęcie flagi w bazie.
    await db.execute(
        update(CandidateDocument)
        .where(
            CandidateDocument.candidate_id == candidate.id,
            CandidateDocument.document_kind == CandidateDocumentKind.cv,
            CandidateDocument.is_primary.is_(True),
        )
        .values(is_primary=False)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(client_cv)
    successor.document_kind = CandidateDocumentKind.cv
    successor.is_primary = True
    candidate.cv_filename = successor.filename
    await db.flush()
    copies = await restore_stage_copies_after_quarantine(
        db,
        candidate=candidate,
        quarantined_sha256=item.client_cv_sha256,
        source="client_cv_repair",
        action="snapshot_client_cv_repaired",
    )
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="primary_cv_repaired_from_client_cv",
            details={
                "client_cv_document_id": client_cv.id,
                "successor_document_id": successor.id,
                "stage_copies": copies,
            },
        )
    )
    await db.commit()
    return replaced


async def repair(
    items: list[Planned],
    *,
    session_factory: Optional[Callable] = None,
    reread: bool = True,
) -> dict[str, int]:
    """Naprawa osób z następcą, każda w osobnej transakcji. Zwraca liczniki."""
    from app.models.candidate import Candidate

    if session_factory is None:
        from app.core.database import AsyncSessionLocal as session_factory
    from app.api.candidates import _enrich_candidate_from_document_task

    stats = {"repaired": 0, "skipped": 0, "profile_reread": 0, "failed": 0}
    for item in items:
        if item.successor_id is None:
            continue
        try:
            async with session_factory() as db:
                before = await db.scalar(
                    select(Candidate.cv_parsed_at).where(
                        Candidate.id == item.candidate_id
                    )
                )
                replaced = await repair_one(db, item)
        except Exception as error:  # noqa: BLE001 — jedna osoba nie zatrzymuje reszty
            logger.warning(
                "client_cv_repair candidate=%s failed: %s",
                item.candidate_id,
                type(error).__name__,
            )
            stats["failed"] += 1
            continue
        if replaced is None:
            stats["skipped"] += 1
            continue
        stats["repaired"] += 1
        if not reread:
            continue
        await _enrich_candidate_from_document_task(
            item.candidate_id,
            item.successor_id,
            trigger="cv_repair",
            replaced_primary=replaced,
        )
        async with session_factory() as db:
            after = await db.scalar(
                select(Candidate.cv_parsed_at).where(Candidate.id == item.candidate_id)
            )
        if after is not None and after != before:
            stats["profile_reread"] += 1
    return stats


async def _receipt_exists(db) -> bool:
    return bool(
        await db.scalar(
            text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": RECEIPT_KEY}
        )
    )


async def _write_receipt(db, payload: dict[str, Any]) -> None:
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, CAST(:v AS jsonb), NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,
                                            updated_at = NOW()
            """
        ),
        {"k": RECEIPT_KEY, "v": json.dumps(payload)},
    )
    await db.commit()


async def main(
    argv: Optional[list[str]] = None,
    *,
    candidate_ids: Optional[list[int]] = None,
    reread: bool = True,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--until",
        type=datetime.fromisoformat,
        help="tylko pliki wgrane przed tą chwilą (ISO ze strefą, np. chwila wdrożenia)",
    )
    parser.add_argument(
        "--expected",
        type=int,
        help="liczba osób z następcą z próby na sucho (wymagana z --apply)",
    )
    args = parser.parse_args(argv)

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        items = await plan(db, candidate_ids=candidate_ids, until=args.until)
        report = summarize(items)
        print(json.dumps({"plan": report}, ensure_ascii=False))
        if not args.apply:
            print(
                "Na sucho — nic nie zmieniono. Dodaj --apply --expected "
                f"{report['with_successor']}."
            )
            return 0
        if await _receipt_exists(db):
            print(f"Paragon {RECEIPT_KEY} już jest — przerywam.", file=sys.stderr)
            return 2
    if args.expected != report["with_successor"]:
        print(
            f"Stan bazy różni się od próby: {report['with_successor']} osób, "
            f"oczekiwano {args.expected} — przerywam.",
            file=sys.stderr,
        )
        return 2
    stats = await repair(items, reread=reread)
    receipt = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "found": report["found"],
        "without_successor": report["without_successor"],
        "stage_copies_planned": report["stage_copies"],
        **stats,
    }
    async with AsyncSessionLocal() as db:
        await _write_receipt(db, receipt)
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
