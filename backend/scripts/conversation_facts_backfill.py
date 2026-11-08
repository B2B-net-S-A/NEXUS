"""Historia rozmów do rejestru faktów (08.11.2026, wariant A).

Dwa źródła, bez wołania modelu: arkusze screeningu (najnowszy arkusz pary)
i zapisane ``_notes_insights`` (``skills_evidenced``, ``certifications``).
Reguły: ``docs/claude/screening-notatki/rozmowy-i-profil-rejestr-faktow.md``.

Przebieg (kontener backendu; ``--apply`` wymaga ``CONVERSATION_FACTS_ENABLED``)::

    python -m scripts.conversation_facts_backfill                     # podgląd
    python -m scripts.conversation_facts_backfill --apply             # zapis, paragon
    python -m scripts.conversation_facts_backfill --recalc --batch ID # przeliczenie pasami
    python -m scripts.conversation_facts_backfill --revert ID         # podgląd cofnięcia
    python -m scripts.conversation_facts_backfill --revert ID --apply

Paragon: ``app_settings['conversation_facts_backfill_<id>']``, same liczby. Przeliczenie
trzyma w paragonie id ostatniej osoby, więc da się je przerwać i wznowić kolejnej
nocy. Zdarzeń jest w kolejce najwyżej ``--open-limit``, żeby nie zatykać nowych CV.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select, text, update  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.models.candidate_conversation_fact import (  # noqa: E402
    CandidateConversationFact as Fact,
)
from app.services import conversation_facts as facts  # noqa: E402

RECEIPT_PREFIX = "conversation_facts_backfill_"
_COMMIT_EVERY = 50

SHEETS_SQL = """
    SELECT DISTINCT ON (candidate_id, job_id)
           id, candidate_id, job_id, screening_answers, moved_at
    FROM candidate_stages
    WHERE jsonb_typeof(screening_answers) = 'object'
      AND jsonb_array_length(
            CASE WHEN jsonb_typeof(screening_answers->'experience_checks') = 'array'
                 THEN screening_answers->'experience_checks' ELSE '[]'::jsonb END
          ) > 0
    ORDER BY candidate_id, job_id, moved_at DESC NULLS LAST, id DESC
"""
INSIGHTS_SQL = """
    SELECT id, cv_extracted_data->'_notes_insights'
    FROM candidates
    WHERE jsonb_typeof(cv_extracted_data->'_notes_insights') = 'object'
      AND (cv_extracted_data->'_notes_insights' ? 'skills_evidenced'
           OR cv_extracted_data->'_notes_insights' ? 'certifications')
"""


def parse_when(raw: Any, fallback: Optional[datetime]) -> datetime:
    """Dzień rozmowy z arkusza albo odczytu; zepsuty zapis = data wiersza."""
    if isinstance(raw, str):
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            value = None
        if value is not None:
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if fallback is not None:
        return fallback if fallback.tzinfo else fallback.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def summarize_sheet(raw_checks: Any, counts: Counter) -> None:
    """Dolicz pozycje jednego arkusza do podglądu (bez zapisu)."""
    for check in facts.sheet_checks(raw_checks):
        counts[f"arkusz.{check.kind}.{check.status}"] += 1
        counts["arkusz.pozycje"] += 1
        mapped = facts._fact_terms(check)
        counts["arkusz.w_slowniku" if mapped else "arkusz.tylko_ta_rekrutacja"] += 1


def summarize_insights(insights: Any, counts: Counter) -> None:
    for kind, name, _quote in facts._note_items(insights):
        counts[f"notatki.{kind}"] += 1
        terms = (
            facts.map_requirement(name, facts.STATUS_CONFIRMED)
            if kind == facts.KIND_SKILL
            else [t for t in [facts._exact_term(name)] if t]
        )
        counts["notatki.w_slowniku" if terms else "notatki.poza_slownikiem"] += 1


async def _hydrate_dictionary() -> None:
    from app.services.skill_normalize import ALIAS_TO_CANONICAL
    from app.services.skill_taxonomy_loader import refresh_alias_map

    await refresh_alias_map()
    if not ALIAS_TO_CANONICAL:
        raise SystemExit("Słownik umiejętności jest pusty: mapowanie nie ma sensu.")


async def _rows(db, sql: str) -> list[Any]:
    return list((await db.execute(text(sql))).all())


async def _save_receipt(db, batch: str, receipt: dict[str, Any]) -> None:
    await db.execute(
        text(
            "INSERT INTO app_settings (key, value) VALUES (:key, CAST(:value AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {
            "key": RECEIPT_PREFIX + batch,
            "value": json.dumps(receipt, ensure_ascii=False),
        },
    )


async def _load_receipt(db, batch: str) -> dict[str, Any]:
    value = await db.scalar(
        text("SELECT value FROM app_settings WHERE key = :key"),
        {"key": RECEIPT_PREFIX + batch},
    )
    if not isinstance(value, dict):
        raise SystemExit(f"Nie ma paragonu dla biegu {batch}.")
    return value


async def _candidate(db, candidate_id: int) -> Optional[Candidate]:
    return await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def preview() -> Counter:
    counts: Counter = Counter()
    await _hydrate_dictionary()
    async with AsyncSessionLocal() as db:
        people: set[int] = set()
        for _sid, cid, _jid, sheet, _at in await _rows(db, SHEETS_SQL):
            before = counts["arkusz.pozycje"]
            summarize_sheet(sheet.get("experience_checks"), counts)
            if counts["arkusz.pozycje"] > before:
                people.add(cid)
        counts["arkusz.osoby"] = len(people)
        insights = await _rows(db, INSIGHTS_SQL)
        for _cid, value in insights:
            summarize_insights(value, counts)
        counts["notatki.osoby"] = len(insights)
    return counts


async def apply() -> str:
    from app.services.match_score_cache import mark_stale_for_candidate

    if not facts.enabled():
        raise SystemExit("Włącz CONVERSATION_FACTS_ENABLED przed zapisem historii.")
    batch = uuid4().hex[:12]
    touched: set[int] = set()
    await _hydrate_dictionary()
    async with AsyncSessionLocal() as db:
        sheets = await _rows(db, SHEETS_SQL)
        insights = await _rows(db, INSIGHTS_SQL)
        await db.commit()
    now = datetime.now(timezone.utc)
    receipt: dict[str, Any] = {
        "applied_at": now.isoformat(),
        "finished": False,
        "sheets": len(sheets),
        "insights": len(insights),
        "candidates": [],
        "recalc_after_id": 0,
    }

    async def checkpoint(db) -> None:
        # Paragon przy każdym commicie: przerwany bieg da się przeliczyć i cofnąć.
        receipt["candidates"] = sorted(touched)
        await _save_receipt(db, batch, receipt)
        await db.commit()

    async with AsyncSessionLocal() as db:
        await checkpoint(db)
        print(f"bieg: {batch}", flush=True)
        for index, (sid, cid, jid, sheet, moved_at) in enumerate(sheets, start=1):
            checks = facts.sheet_checks(sheet.get("experience_checks"))
            candidate = await _candidate(db, cid) if checks else None
            if candidate is not None and await facts.sync_sheet(
                db,
                candidate=candidate,
                job_id=jid,
                stage_id=sid,
                checks=checks,
                user_id=sheet.get("answered_by"),
                now=parse_when(sheet.get("answered_at"), moved_at),
                batch=batch,
            ):
                touched.add(cid)
                await mark_stale_for_candidate(db, cid)
            if index % _COMMIT_EVERY == 0:
                await checkpoint(db)
        await checkpoint(db)
        for index, (cid, value) in enumerate(insights, start=1):
            candidate = await _candidate(db, cid)
            if candidate is None:
                continue
            added = await facts.record_note_facts(
                db,
                candidate=candidate,
                parsed=value,
                note_id=None,
                noted_at=parse_when(value.get("_v2_extracted_at"), None),
                batch=batch,
            )
            if added:
                await mark_stale_for_candidate(db, cid)
            touched.add(cid)
            if index % _COMMIT_EVERY == 0:
                await checkpoint(db)
        receipt["finished"] = True
        await checkpoint(db)
    return batch


async def _open_events(db) -> int:
    return int(
        await db.scalar(
            text(
                "SELECT count(*) FROM candidate_match_outbox "
                "WHERE status IN ('pending', 'processing', 'failed')"
            )
        )
        or 0
    )


async def recalc(batch: str, *, open_limit: int, max_people: int, pause: float) -> int:
    """Zdarzenia ``conversation`` pasami: najwyżej ``open_limit`` otwartych naraz."""
    sent = 0
    async with AsyncSessionLocal() as db:
        receipt = await _load_receipt(db, batch)
        people = [c for c in receipt["candidates"] if c > receipt["recalc_after_id"]]
        await db.commit()
    for cid in people[:max_people]:
        while True:
            async with AsyncSessionLocal() as db:
                busy = await _open_events(db) >= open_limit
            if not busy:
                break
            await asyncio.sleep(pause)
        async with AsyncSessionLocal() as db:
            candidate = await db.get(Candidate, cid)
            if candidate is not None:
                await facts.enqueue_recalculation(db, candidate)
                sent += 1
            receipt = await _load_receipt(db, batch)
            receipt["recalc_after_id"] = cid
            await _save_receipt(db, batch, receipt)
            await db.commit()
    return sent


async def revert(batch: str, *, do_apply: bool) -> int:
    """Gasi fakty z biegu i zdejmuje z listy umiejętności to, co dopisał."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await _load_receipt(db, batch)
        ids = sorted(
            set(
                (
                    await db.scalars(
                        # Także już zgaszone: przerwane cofnięcie da się dokończyć.
                        select(Fact.candidate_id).where(Fact.batch == batch)
                    )
                ).all()
            )
        )
        if not do_apply:
            return len(ids)
        await db.execute(
            update(Fact)
            .where(Fact.batch == batch, Fact.retired_at.is_(None))
            .values(retired_at=now)
        )
        await db.commit()
        for index, cid in enumerate(ids, start=1):
            candidate = await _candidate(db, cid)
            if candidate is not None:
                await facts.refresh_projection(db, candidate)
                await facts.enqueue_recalculation(db, candidate)
            if index % _COMMIT_EVERY == 0:
                await db.commit()
        receipt = await _load_receipt(db, batch)
        receipt["reverted_at"] = now.isoformat()
        await _save_receipt(db, batch, receipt)
        await db.commit()
    return len(ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--recalc", action="store_true")
    parser.add_argument("--batch")
    parser.add_argument("--revert", metavar="BATCH")
    parser.add_argument("--open-limit", type=int, default=20)
    parser.add_argument("--max-people", type=int, default=700)
    parser.add_argument("--pause", type=float, default=30.0)
    args = parser.parse_args()
    if args.revert:
        count = asyncio.run(revert(args.revert, do_apply=args.apply))
        verb = "cofnięto" if args.apply else "do cofnięcia (podgląd)"
        print(f"osoby {verb}: {count}")
    elif args.recalc:
        if not args.batch:
            parser.error("--recalc wymaga --batch")
        sent = asyncio.run(
            recalc(
                args.batch,
                open_limit=args.open_limit,
                max_people=args.max_people,
                pause=args.pause,
            )
        )
        print(f"zdarzenia przeliczenia: {sent}")
    elif args.apply:
        asyncio.run(apply())
    else:
        for key, value in sorted(asyncio.run(preview()).items()):
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
