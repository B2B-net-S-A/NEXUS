"""Umowa jako główne CV — naprawa profili z importu Traffita (30.10.2026).

Import z Traffita oznaczał jako główne CV pierwszy PDF osoby, bez patrzenia na
nazwę, więc u części osób główne CV to podpisana umowa. Traffit jest wyłączony
od 14.10.2026, nowe takie pliki z importu nie przybędą; zostają dane
(pomiar 30.10: 137 osób, 59 z plikiem z CV w nazwie).

Uruchomienie (w kontenerze backendu)::

    python -m app.cli.contract_as_cv_repair
    python -m app.cli.contract_as_cv_repair --apply --expected 137

Zasady (decyzja Artura 30.10.2026):

* wybór: aktywne główne CV z umową w nazwie (`looks_like_contract`), bez CV
  w nazwie i bez „Contract Manager”;
* umowa zostaje w profilu (CV nie kasujemy nigdy), ale dostaje rodzaj „other”
  i „nieaktualne”, bo tylko to odcina ją od „bieżącego CV”
  (`cv_source.current_cv_filters`) i od „Ustaw jako główne CV”;
* następca to wyłącznie plik PDF/DOC/DOCX z CV w nazwie, który może być
  bieżącym CV, nie jest umową ani CV do klienta. Po nim AI czyta profil od nowa;
* bez następcy profil zostaje bez głównego CV, a główne CV wskazuje człowiek.
  Danych odczytanych wcześniej z pliku skrypt nie czyści;
* wskaźnik CV na kandydacie odpina ta sama reguła co „Usuń z profilu”;
* ``--apply`` wymaga ``--expected`` równego liczbie osób z próby na sucho.
  Każda osoba w osobnej transakcji, stan sprawdzany pod blokadą;
* paragon ``app_settings['contract_as_cv_repair_2026_10']`` niesie same liczby;
  ponowne ``--apply`` przy istniejącym paragonie jest odrzucane.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import case, func, or_, select, text

logger = logging.getLogger(__name__)

RECEIPT_KEY = "contract_as_cv_repair_2026_10"
_CV_EXT = (".pdf", ".doc", ".docx")
_CONTRACT_PATTERN = "umow|umów|contract|agreement"
_CONTRACT_NAME = re.compile(_CONTRACT_PATTERN, re.IGNORECASE)
_CV_NAME = re.compile(r"(^|[^a-z])(cv|resume|curriculum)([^a-z]|$)", re.IGNORECASE)
_JOB_TITLE = re.compile(r"contract.?manager", re.IGNORECASE)


def looks_like_contract(filename: str) -> bool:
    """Umowa w nazwie, bez CV w nazwie; „Contract Manager” to stanowisko."""
    return bool(
        _CONTRACT_NAME.search(filename)
        and not _CV_NAME.search(filename)
        and not _JOB_TITLE.search(filename)
    )


@dataclass(frozen=True)
class Planned:
    candidate_id: int
    contract_id: int
    successor_id: Optional[int]
    stage_copies: int


async def plan(db, *, candidate_ids: Optional[list[int]] = None) -> list[Planned]:
    """Osoby do naprawy. ``candidate_ids`` zawęża bieg (testy na wspólnej bazie)."""
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.services.client_cv_upload import CLIENT_CV_NAME
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
        CandidateDocument.filename.op("~*")(_CONTRACT_PATTERN),
    )
    if candidate_ids is not None:
        query = query.where(CandidateDocument.candidate_id.in_(candidate_ids))
    planned: list[Planned] = []
    for doc_id, candidate_id, filename, sha256 in (
        await db.execute(query.order_by(CandidateDocument.candidate_id))
    ).all():
        if not looks_like_contract(filename or ""):
            continue
        others = (
            await db.execute(
                select(CandidateDocument.id, CandidateDocument.filename)
                .where(
                    CandidateDocument.candidate_id == candidate_id,
                    CandidateDocument.id != doc_id,
                    *current_cv_filters(),
                )
                # Kolejność jak w `client_cv_primary_repair`.
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
        successor = next(
            (
                other_id
                for other_id, name in others
                if os.path.splitext((name or "").lower())[1] in _CV_EXT
                and _CV_NAME.search(name or "")
                and not _CONTRACT_NAME.search(name or "")
                and not CLIENT_CV_NAME.search(name or "")
            ),
            None,
        )
        # Tylko do raportu: kopii etapu skrypt nie zmienia.
        same_file = CandidateStageCV.original_cv_filename.op("~*")(_CONTRACT_PATTERN)
        if sha256:
            same_file = or_(same_file, CandidateStageCV.original_cv_sha256 == sha256)
        copies = await db.scalar(
            select(func.count())
            .select_from(CandidateStageCV)
            .where(CandidateStageCV.candidate_id == candidate_id, same_file)
        )
        planned.append(
            Planned(
                candidate_id=candidate_id,
                contract_id=doc_id,
                successor_id=successor,
                stage_copies=int(copies or 0),
            )
        )
    return planned


def summarize(items: list[Planned]) -> dict[str, Any]:
    with_successor = sum(1 for item in items if item.successor_id is not None)
    return {
        "found": len(items),
        "with_successor": with_successor,
        "without_successor": len(items) - with_successor,
        "stage_copies": sum(item.stage_copies for item in items),
        # Same identyfikatory — bez nazw plików i osób (logi bywają publiczne).
        "candidate_ids": [item.candidate_id for item in items],
        "without_successor_ids": [
            item.candidate_id for item in items if item.successor_id is None
        ],
    }


async def repair_one(db, item: Planned):
    """Zdejmij umowę z głównego CV; zwraca stan sprzed zmiany albo ``None``.

    Stan bazy sprawdzamy jeszcze raz pod blokadą: od próby na sucho ktoś mógł
    sam wskazać inne główne CV.
    """
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.services.candidate_document_removal import _detach_candidate_cv_pointer
    from app.services.candidate_identity_quarantine import ReplacedPrimaryCv

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"{RECEIPT_KEY}:{item.candidate_id}"},
    )
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == item.candidate_id).with_for_update()
    )
    contract = await db.get(CandidateDocument, item.contract_id)
    if (
        candidate is None
        or contract is None
        or not contract.is_primary
        or contract.document_kind != CandidateDocumentKind.cv
        or contract.source_deleted_at is not None
    ):
        return None
    successor = None
    if item.successor_id is not None:
        successor = await db.get(CandidateDocument, item.successor_id)
        if (
            successor is None
            or successor.source_deleted_at is not None
            or successor.outdated_at is not None
        ):
            return None
    replaced = ReplacedPrimaryCv(
        document_id=contract.id, cv_filename=candidate.cv_filename
    )
    now = datetime.now(timezone.utc)
    contract.is_primary = False
    contract.document_kind = CandidateDocumentKind.other
    contract.outdated_at = now
    # Częściowy UNIQUE na aktywne główne CV: najpierw zdjęcie flagi w bazie.
    await db.flush()
    if successor is not None:
        successor.document_kind = CandidateDocumentKind.cv
        successor.is_primary = True
        await db.flush()
    await _detach_candidate_cv_pointer(
        db, candidate=candidate, document=contract, removed_at=now, actor_id=None
    )
    if successor is not None:
        candidate.cv_filename = successor.filename
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="primary_cv_repaired_from_contract",
            details={
                "contract_document_id": contract.id,
                "successor_document_id": item.successor_id,
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
    """Naprawa osób, każda w osobnej transakcji. Zwraca liczniki."""
    from app.models.candidate import Candidate

    if session_factory is None:
        from app.core.database import AsyncSessionLocal as session_factory
    from app.api.candidates import _enrich_candidate_from_document_task

    stats = {"repaired": 0, "skipped": 0, "profile_reread": 0, "failed": 0}
    for item in items:
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
                "contract_as_cv_repair candidate=%s failed: %s",
                item.candidate_id,
                type(error).__name__,
            )
            stats["failed"] += 1
            continue
        if replaced is None:
            stats["skipped"] += 1
            continue
        stats["repaired"] += 1
        if not reread or item.successor_id is None:
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
        "--expected",
        type=int,
        help="liczba osób z próby na sucho (wymagana z --apply)",
    )
    args = parser.parse_args(argv)

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        items = await plan(db, candidate_ids=candidate_ids)
        report = summarize(items)
        print(json.dumps({"plan": report}, ensure_ascii=False))
        if not args.apply:
            print(
                f"Na sucho — nic nie zmieniono. Dodaj --apply --expected {report['found']}."
            )
            return 0
        if await _receipt_exists(db):
            print(f"Paragon {RECEIPT_KEY} już jest — przerywam.", file=sys.stderr)
            return 2
    if args.expected != report["found"]:
        print(
            f"Stan bazy różni się od próby: {report['found']} osób, "
            f"oczekiwano {args.expected} — przerywam.",
            file=sys.stderr,
        )
        return 2
    stats = await repair(items, reread=reread)
    receipt = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "found": report["found"],
        "with_successor": report["with_successor"],
        "without_successor": report["without_successor"],
        "stage_copies": report["stage_copies"],
        **stats,
    }
    async with AsyncSessionLocal() as db:
        await _write_receipt(db, receipt)
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
