"""Kopie umów w etapach po naprawie głównego CV (30.10.2026).

`app.cli.contract_as_cv_repair` podmienia tylko kopie z SHA u osób z następcą.
Reszta została jako „Oryginał CV” w etapach (pomiar 30.10: 23 kopie, z tego
13 widać w panelu na najnowszym etapie, 3 przy żywych kandydatach).

Uruchomienie (w kontenerze backendu, PO naprawie profili)::

    python -m app.cli.contract_stage_copies_repair
    python -m app.cli.contract_stage_copies_repair --apply --expected 23

Zasady (decyzja Artura 30.10.2026):

* wybór: kopia etapu z umową w nazwie (`looks_like_contract`), także bez SHA;
* osoba ma główne CV bez umowy w nazwie: kopia dostaje to CV;
* osoba nie ma głównego CV: kopia zostaje pusta, panel pokazuje plik z profilu
  albo „brak pliku”. Nieopisanego pliku nie podstawiamy, bo to może być kolejny
  dokument;
* główne CV to wciąż umowa: kopia zostaje, raport ją liczy;
* umowa zostaje w profilu, CV firmowego skrypt nie zmienia;
* ``--apply`` wymaga paragonu naprawy profili (inaczej „bieżącym CV” byłaby
  umowa) i ``--expected`` równego liczbie kopii z próby na sucho. Każda kopia
  w osobnej transakcji, stan sprawdzany pod blokadą;
* paragon ``app_settings['contract_stage_copies_repair_2026_10']`` niesie same
  liczby; ponowne ``--apply`` przy istniejącym paragonie jest odrzucane.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select, text

from app.cli import contract_as_cv_repair as profile_repair

logger = logging.getLogger(__name__)

RECEIPT_KEY = "contract_stage_copies_repair_2026_10"
_SOURCE = "contract_repair"


@dataclass(frozen=True)
class Planned:
    csv_id: int
    candidate_id: int
    # "replace" | "clear" | "skip"
    action: str


async def _main_cv_filename(db, candidate_id: int) -> Optional[str]:
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.services.cv_source import current_cv_filters

    return await db.scalar(
        select(CandidateDocument.filename).where(
            CandidateDocument.candidate_id == candidate_id,
            CandidateDocument.is_primary.is_(True),
            CandidateDocument.document_kind == CandidateDocumentKind.cv,
            *current_cv_filters(),
        )
    )


def _action(main_cv: Optional[str]) -> str:
    if main_cv is None:
        return "clear"
    return "skip" if profile_repair.looks_like_contract(main_cv) else "replace"


async def plan(db, *, candidate_ids: Optional[list[int]] = None) -> list[Planned]:
    """Kopie do naprawy. ``candidate_ids`` zawęża bieg (testy na wspólnej bazie)."""
    from app.models.candidate_stage_cv import CandidateStageCV

    query = select(
        CandidateStageCV.id,
        CandidateStageCV.candidate_id,
        CandidateStageCV.original_cv_filename,
    ).where(
        CandidateStageCV.original_cv_filename.op("~*")(profile_repair._CONTRACT_PATTERN)
    )
    if candidate_ids is not None:
        query = query.where(CandidateStageCV.candidate_id.in_(candidate_ids))
    planned: list[Planned] = []
    for csv_id, candidate_id, filename in (
        await db.execute(query.order_by(CandidateStageCV.id))
    ).all():
        if not profile_repair.looks_like_contract(filename or ""):
            continue
        action = _action(await _main_cv_filename(db, candidate_id))
        planned.append(Planned(csv_id, candidate_id, action))
    return planned


def summarize(items: list[Planned]) -> dict[str, Any]:
    to_replace = sum(1 for item in items if item.action == "replace")
    to_clear = sum(1 for item in items if item.action == "clear")
    return {
        # Kopie, które bieg zmieni; tę liczbę podaje się w --expected.
        "found": to_replace + to_clear,
        "to_replace": to_replace,
        "to_clear": to_clear,
        "left_for_a_person": len(items) - to_replace - to_clear,
        # Same identyfikatory — bez nazw plików i osób (logi bywają publiczne).
        "csv_ids": [item.csv_id for item in items if item.action != "skip"],
    }


async def repair_one(db, item: Planned) -> Optional[str]:
    """Napraw kopię; zwraca wykonaną akcję albo ``None``, gdy pominięto.

    Stan bazy sprawdzamy jeszcze raz pod blokadą: od próby na sucho rekruter mógł
    sam podmienić kopię albo ktoś wskazać główne CV.
    """
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.services.candidate_stage_cv_service import refresh_original_cv_snapshot
    from app.services.cv_source import get_current_cv

    copy = await db.scalar(
        select(CandidateStageCV)
        .where(CandidateStageCV.id == item.csv_id)
        .with_for_update()
    )
    if copy is None or not profile_repair.looks_like_contract(
        copy.original_cv_filename or ""
    ):
        return None
    main_cv = await _main_cv_filename(db, item.candidate_id)
    action = _action(main_cv)
    if action == "skip":
        return None
    if action == "replace":
        candidate = await db.get(Candidate, item.candidate_id)
        current = await get_current_cv(db, candidate)
        # Awaria magazynu schodzi w `get_current_cv` do wskaźnika kandydata:
        # kopia nie może dostać starszego pliku pod nazwą głównego CV.
        if (
            current is None
            or current.filename != main_cv
            or not current.source.startswith("document_")
        ):
            return None
        await refresh_original_cv_snapshot(
            db,
            copy.candidate_stage_id,
            user_id=None,
            source=_SOURCE,
            current=current,
        )
    else:
        old_filename = copy.original_cv_filename
        copy.original_cv_filename = None
        copy.original_cv_content = None
        copy.original_cv_storage_key = None
        copy.original_cv_sha256 = None
        copy.original_cv_language = None
        copy.original_snapshot_at = datetime.now(tz=timezone.utc)
        copy.original_snapshot_source = _SOURCE
        db.add(
            Activity(
                entity_type="candidate_stage_cv",
                entity_id=copy.id,
                action="snapshot_contract_repaired",
                details={
                    "candidate_stage_id": copy.candidate_stage_id,
                    "old_filename": old_filename,
                    "new_filename": None,
                },
            )
        )
    await db.commit()
    return action


async def repair(
    items: list[Planned], *, session_factory: Optional[Callable] = None
) -> dict[str, int]:
    """Naprawa kopii, każda w osobnej transakcji. Zwraca liczniki."""
    if session_factory is None:
        from app.core.database import AsyncSessionLocal as session_factory

    stats = {"replaced": 0, "cleared": 0, "skipped": 0, "failed": 0}
    for item in items:
        try:
            async with session_factory() as db:
                done = await repair_one(db, item)
        except Exception as error:  # noqa: BLE001 — jedna kopia nie zatrzymuje reszty
            logger.warning(
                "contract_stage_copies_repair csv=%s failed: %s",
                item.csv_id,
                type(error).__name__,
            )
            stats["failed"] += 1
            continue
        if done == "replace":
            stats["replaced"] += 1
        elif done == "clear":
            stats["cleared"] += 1
        else:
            stats["skipped"] += 1
    return stats


async def _setting_exists(db, key: str) -> bool:
    return bool(
        await db.scalar(text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": key})
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
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--expected",
        type=int,
        help="liczba kopii z próby na sucho (wymagana z --apply)",
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
        if await _setting_exists(db, RECEIPT_KEY):
            print(f"Paragon {RECEIPT_KEY} już jest — przerywam.", file=sys.stderr)
            return 2
        if not await _setting_exists(db, profile_repair.RECEIPT_KEY):
            print(
                "Najpierw naprawa profili: app.cli.contract_as_cv_repair — przerywam.",
                file=sys.stderr,
            )
            return 2
    if args.expected != report["found"]:
        print(
            f"Stan bazy różni się od próby: {report['found']} kopii, "
            f"oczekiwano {args.expected} — przerywam.",
            file=sys.stderr,
        )
        return 2
    stats = await repair(items)
    receipt = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "found": report["found"],
        "to_replace": report["to_replace"],
        "to_clear": report["to_clear"],
        "left_for_a_person": report["left_for_a_person"],
        **stats,
    }
    async with AsyncSessionLocal() as db:
        await _write_receipt(db, receipt)
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
