"""Jednorazowe przeniesienie kart z portali do „Do przejrzenia” (30.09.2026).

Scraper JJIT/RocketJobs dodawał dopasowania wprost na Tablicę (etap
„Ogłoszenia”, ``entry_source='auto_match'``). Zmierzone 30.09.2026: 1 819 kart,
każda osoba średnio w ~3,9 rekrutacjach, dalej przeszły 2. Od tej daty
``POST /api/jobs/{id}/proposals/bulk`` z ``auto_match`` od tokenu integracji
zakłada propozycję ``job_board`` (``proposals_bulk.propose_candidates_for_job``).
Ta naprawa przenosi NIETKNIĘTE stare karty tą samą drogą, co ręczne „Usuń
z rekrutacji”, i zakłada w ich miejsce propozycję z oryginalnym wynikiem.

Karta kwalifikuje się wyłącznie, gdy spełnia WSZYSTKO:

* rekrutacja opublikowana i założona w NEXUSIE (``external_source`` różne
  od ``traffit`` — rekrutacje z Traffita są archiwum);
* para ma dokładnie jeden proces, ``entry_source='auto_match'``, otwarty,
  z plakietką auto-matcha od integracji (``entry_meta.kind='auto_match'``,
  ``source`` różne od ``nexus`` — wewnętrzny auto-match w trybie ``add`` to
  decyzja administratora, nie scraper; wejścia integracji BEZ wyniku, np.
  zgłoszenia z pracuj.pl, zostają);
* dokładnie jeden wiersz etapu pary, na etapie ``posting``, bez odpowiedzi
  screeningu i scorecardu;
* żadnej notatki z tą rekrutacją, żadnego ``application_screenings``, żadnej
  notatki screeningu (``screening_notes``) tej pary;
* CV etapu wyłącznie jako automatyczna migawka z dodania (nikt nie zaczął CV
  firmowego) i nic, co na tę migawkę wskazuje;
* ZERO wierszy w jakiejkolwiek tabeli z FK do tego wiersza etapu albo tego
  procesu — lista FK czytana z ``pg_constraint`` w chwili biegu (poza
  wskaźnikiem ``recruitment_processes.legacy_current_candidate_stage_id``
  i migawką CV z punktu wyżej), więc tabela dopisana później też blokuje.

Wykonanie na parę, w savepoincie: blokada kandydata, ponowne sprawdzenie
wszystkich warunków, archiwum etapów (``candidate_stage_removals``),
``void_process`` → ``delete_voided_stage_history`` → zamknięcie okazji
kontaktu (jak ``DELETE /api/candidates/{id}/recruitments/{job_id}``), potem
propozycja ``job_board`` z wynikiem z ``entry_meta``. Wiersze skrzynki tej pary
w statusie ``added`` (postawione przy dodaniu karty) wracają do ``proposed`` —
karty już nie ma, więc „dodana” przestała być prawdą, a bez tego osoba nie
pokazałaby się w „Do przejrzenia”.

Zasady jak przy innych naprawach z panelu: przebieg próbny niczego nie zapisuje
poza raportem (liczby per rekrutacja, powody odrzucenia, do 20 przykładów —
same identyfikatory); zapis wymaga próby z ostatnich 7 dni; paragon w stanie =
liczby i ID; dane do odwrócenia (id archiwum, proces, etap, cofnięte wiersze
skrzynki, oryginalny ``entry_meta``) pod ``repair_details_…``. Ponowny bieg nic
nie zmienia: przeniesiona para ma proces ``voided`` i żadnego etapu.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

STATE_KEY = "job_board_cards_to_proposals_2026_09"
DRY_RUN_KEY = "job_board_cards_to_proposals_2026_09_dry_run"
DETAILS_KEY = "repair_details_job_board_cards_to_proposals_2026_09"
LOCK_KEY = "job_board_cards_to_proposals_2026_09"
CHUNK = 50
SAMPLE_SIZE = 20
FAILED_SAMPLE = 50
DRY_RUN_MAX_AGE = timedelta(days=7)
REMOVAL_REASON = "job_board_to_proposals"

# FK pomijane w ogólnym sprawdzeniu: wskaźnik migracyjny procesu na jego własny
# ostatni etap i migawka CV z dodania (ta ma własny warunek „nietknięta”).
_SKIPPED_FKS = frozenset(
    {
        ("recruitment_processes", "legacy_current_candidate_stage_id"),
        ("candidate_stage_cvs", "candidate_stage_id"),
    }
)

_FK_SQL = """
SELECT cl.relname AS tbl,
       quote_ident(n.nspname) || '.' || quote_ident(cl.relname) AS qualified,
       a.attname AS col,
       tcl.relname AS target
FROM pg_constraint c
JOIN pg_class cl ON cl.oid = c.conrelid
JOIN pg_namespace n ON n.oid = cl.relnamespace
JOIN pg_class tcl ON tcl.oid = c.confrelid
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
WHERE c.contype = 'f'
  AND array_length(c.conkey, 1) = 1
  AND c.confrelid IN (
      to_regclass('candidate_stages'),
      to_regclass('recruitment_processes'),
      to_regclass('candidate_stage_cvs')
  )
ORDER BY cl.relname, a.attname
"""

# Baza: otwarte procesy z plakietką auto-matcha od integracji. ``stage_id`` =
# najnowszy wiersz etapu pary (warunki niżej wymagają, żeby był jedyny).
_BASE_SQL = """
SELECT rp.id AS process_id, rp.candidate_id, rp.job_id, rp.entry_meta,
       (SELECT max(c.id) FROM candidate_stages c
        WHERE c.candidate_id = rp.candidate_id AND c.job_id = rp.job_id) AS stage_id
FROM recruitment_processes rp
WHERE rp.entry_source = 'auto_match'
  AND rp.status = 'open'
  AND rp.entry_meta ->> 'kind' = 'auto_match'
  AND (rp.entry_meta ->> 'source') IS DISTINCT FROM 'nexus'
"""

# (powód, predykat PRAWDZIWY, gdy para NIE kwalifikuje się). Alias bazy: ``b``.
_STATIC_DISQUALIFIERS: tuple[tuple[str, str], ...] = (
    (
        "job_not_eligible",
        """NOT EXISTS (SELECT 1 FROM jobs j WHERE j.id = b.job_id
                  AND j.status = 'published'
                  AND j.external_source IS DISTINCT FROM 'traffit')""",
    ),
    (
        "multiple_processes",
        """(SELECT count(*) FROM recruitment_processes p2
            WHERE p2.candidate_id = b.candidate_id AND p2.job_id = b.job_id) <> 1""",
    ),
    (
        "stage_not_single_posting",
        """((SELECT count(*) FROM candidate_stages c2
             WHERE c2.candidate_id = b.candidate_id AND c2.job_id = b.job_id) <> 1
            OR NOT EXISTS (SELECT 1 FROM candidate_stages c3
                           WHERE c3.id = b.stage_id AND c3.stage = 'posting'))""",
    ),
    (
        "stage_answers",
        """EXISTS (SELECT 1 FROM candidate_stages c4 WHERE c4.id = b.stage_id AND (
                (c4.screening_answers IS NOT NULL
                 AND jsonb_typeof(c4.screening_answers) <> 'null')
             OR (c4.scorecard_answers IS NOT NULL
                 AND jsonb_typeof(c4.scorecard_answers) <> 'null')))""",
    ),
    (
        "notes",
        """EXISTS (SELECT 1 FROM notes nt
                  WHERE nt.candidate_id = b.candidate_id AND nt.job_id = b.job_id)""",
    ),
    (
        "application_screening",
        """EXISTS (SELECT 1 FROM application_screenings aps
                  WHERE aps.candidate_id = b.candidate_id AND aps.job_id = b.job_id)""",
    ),
    (
        "screening_notes",
        """EXISTS (SELECT 1 FROM screening_notes sn
                  WHERE sn.candidate_id = b.candidate_id AND sn.job_id = b.job_id)""",
    ),
    (
        "stage_cv_touched",
        """EXISTS (SELECT 1 FROM candidate_stage_cvs sc
                  WHERE sc.candidate_stage_id = b.stage_id
                    AND NOT (sc.branded_status = 'none'
                             AND sc.generated_document_id IS NULL
                             AND sc.branded_draft_html IS NULL
                             AND sc.branded_updated_at IS NULL
                             AND sc.branded_finalized_at IS NULL))""",
    ),
)


def fk_disqualifiers(fks: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Predykaty „coś wskazuje na ten etap / proces / migawkę CV” z katalogu.

    Nazwy tabel i kolumn pochodzą z ``pg_constraint`` i są cytowane
    (``quote_ident``) — nic z żądania nie trafia do SQL-a.
    """
    out: list[tuple[str, str]] = []
    for fk in fks:
        tbl, col, target = fk["tbl"], fk["col"], fk["target"]
        if (tbl, col) in _SKIPPED_FKS:
            continue
        qualified = fk["qualified"]
        quoted_col = '"' + col.replace('"', '""') + '"'
        if target == "candidate_stages":
            predicate = f"EXISTS (SELECT 1 FROM {qualified} x WHERE x.{quoted_col} = b.stage_id)"
        elif target == "recruitment_processes":
            predicate = (
                f"EXISTS (SELECT 1 FROM {qualified} x "
                f"WHERE x.{quoted_col} = b.process_id)"
            )
        elif target == "candidate_stage_cvs":
            predicate = (
                f"EXISTS (SELECT 1 FROM {qualified} x "
                f"JOIN candidate_stage_cvs scv ON scv.id = x.{quoted_col} "
                "WHERE scv.candidate_stage_id = b.stage_id)"
            )
        else:  # pragma: no cover — zapytanie o FK zwraca tylko te trzy cele
            continue
        out.append((f"fk:{tbl}.{col}", predicate))
    return out


def qualifying_sql(disqualifiers: list[tuple[str, str]], *, one_pair: bool) -> str:
    """Zapytanie o kwalifikujące się pary (albo jedną — ponowne sprawdzenie)."""
    where = " AND ".join(f"NOT ({pred})" for _, pred in disqualifiers) or "TRUE"
    pair = "WHERE base.process_id = :process_id" if one_pair else ""
    return (
        f"SELECT b.process_id, b.candidate_id, b.job_id, b.entry_meta, b.stage_id "
        f"FROM (SELECT * FROM ({_BASE_SQL}) base {pair}) b "
        f"WHERE {where} ORDER BY b.job_id, b.candidate_id"
    )


def blocked_counts_sql(disqualifiers: list[tuple[str, str]]) -> str:
    """Ile par z bazy odpada z KAŻDEGO powodu (powody się nakładają)."""
    columns = ", ".join(
        f"count(*) FILTER (WHERE {pred}) AS c{i}"
        for i, (_, pred) in enumerate(disqualifiers)
    )
    return f"SELECT count(*) AS base{', ' + columns if columns else ''} FROM ({_BASE_SQL}) b"


async def _read_setting(db: AsyncSession, key: str) -> Optional[dict[str, Any]]:
    row = await db.execute(
        text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}
    )
    value = row.scalar_one_or_none()
    return value if isinstance(value, dict) else None


async def _write_setting(db: AsyncSession, key: str, value: dict[str, Any]) -> None:
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, CAST(:v AS jsonb), now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """
        ),
        {"k": key, "v": json.dumps(value, default=str)},
    )


async def _append_details(db: AsyncSession, entries: list[dict[str, Any]]) -> None:
    """Dopisz dane do odwrócenia przeniesienia (same identyfikatory i wynik)."""
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:key, jsonb_build_object('moved', CAST(:value AS jsonb)), now())
            ON CONFLICT (key) DO UPDATE SET
                value = jsonb_build_object(
                    'moved',
                    COALESCE(app_settings.value -> 'moved', '[]'::jsonb)
                    || CAST(:value AS jsonb)
                ),
                updated_at = now()
            """
        ),
        {"key": DETAILS_KEY, "value": json.dumps(entries, default=str)},
    )


async def load_disqualifiers(db: AsyncSession) -> list[tuple[str, str]]:
    rows = (await db.execute(text(_FK_SQL))).mappings().all()
    fks = [dict(r) for r in rows]
    return list(_STATIC_DISQUALIFIERS) + fk_disqualifiers(fks)


async def plan(db: AsyncSession) -> dict[str, Any]:
    """Przebieg próbny: liczby per rekrutacja, powody odrzucenia, przykłady."""
    disqualifiers = await load_disqualifiers(db)
    rows = (
        (await db.execute(text(qualifying_sql(disqualifiers, one_pair=False))))
        .mappings()
        .all()
    )
    blocked_row = (
        (await db.execute(text(blocked_counts_sql(disqualifiers)))).mappings().one()
    )
    per_job: Counter[int] = Counter(int(r["job_id"]) for r in rows)
    return {
        "dry_run": True,
        "base_pairs": int(blocked_row["base"] or 0),
        "qualifying_pairs": len(rows),
        "jobs": len(per_job),
        "per_job": [
            {"job_id": job_id, "pairs": count}
            for job_id, count in sorted(per_job.items())
        ],
        "blocked_by": {
            reason: int(blocked_row[f"c{i}"] or 0)
            for i, (reason, _) in enumerate(disqualifiers)
        },
        "fk_checks": [
            reason for reason, _ in disqualifiers if reason.startswith("fk:")
        ],
        "samples": [
            {
                "candidate_id": int(r["candidate_id"]),
                "job_id": int(r["job_id"]),
                "process_id": int(r["process_id"]),
                "stage_id": int(r["stage_id"]),
            }
            for r in rows[:SAMPLE_SIZE]
        ],
    }


async def _convert_pair(
    db: AsyncSession,
    *,
    process_id: int,
    candidate_id: int,
    job_id: int,
    actor: Any,
    disqualifiers: list[tuple[str, str]],
) -> Optional[dict[str, Any]]:
    """Przenieś jedną parę. ``None`` = para przestała się kwalifikować."""
    from app.api.proposals_bulk import job_board_evidence
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.candidate_stage_removal import CandidateStageRemoval
    from app.models.recruitment_pipeline import CandidateStage
    from app.services.auto_match_outbox import candidate_revision
    from app.services.candidate_contact_hooks import (
        has_active_contact_trigger,
        maybe_close_contact_opportunity,
    )
    from app.services.candidate_stage_removal_snapshot import (
        ordered_stage_rows,
        stage_removal_snapshot,
    )
    from app.services.job_proposals import upsert_proposals
    from app.services.recruitment_process_commands import (
        delete_voided_stage_history,
        void_process,
    )

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        return None
    # Ponowne sprawdzenie pod blokadą kandydata: między próbą a zapisem ktoś
    # mógł przesunąć kartę, dopisać notatkę albo zacząć CV.
    fresh = (
        (
            await db.execute(
                text(qualifying_sql(disqualifiers, one_pair=True)),
                {"process_id": process_id},
            )
        )
        .mappings()
        .first()
    )
    if fresh is None:
        return None
    entry_meta = fresh["entry_meta"] if isinstance(fresh["entry_meta"], dict) else {}
    stage_rows = (
        (
            await db.execute(
                select(CandidateStage)
                .where(
                    CandidateStage.candidate_id == candidate_id,
                    CandidateStage.job_id == job_id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if len(stage_rows) != 1:
        return None
    ordered = ordered_stage_rows(stage_rows)
    removal = CandidateStageRemoval(
        candidate_id=candidate_id,
        job_id=job_id,
        removed_by=actor.id,
        reason=REMOVAL_REASON,
        last_stage=ordered[-1].stage.value,
        stage_count=len(stage_rows),
        stages_snapshot=stage_removal_snapshot(ordered),
    )
    db.add(removal)
    await db.flush()
    stage_id = ordered[-1].id
    stage_def_id = ordered[-1].stage_def_id

    await void_process(db, candidate_id=candidate_id, job_id=job_id, actor_user=actor)
    await delete_voided_stage_history(db, candidate_id=candidate_id, job_id=job_id)
    if not await has_active_contact_trigger(
        db, candidate_id=candidate_id, job_id=job_id
    ):
        await maybe_close_contact_opportunity(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            actor_user_id=actor.id,
            reason="removed_from_recruitment",
        )

    # Karta zniknęła, więc „dodana” w skrzynce przestała być prawdą — inaczej
    # status pary (added > dismissed > proposed) chowałby nową propozycję.
    reverted = (
        (
            await db.execute(
                text(
                    """
                UPDATE job_proposals SET status = 'proposed'
                WHERE job_id = :job_id AND candidate_id = :candidate_id
                  AND status = 'added'
                RETURNING id
                """
                ),
                {"job_id": job_id, "candidate_id": candidate_id},
            )
        )
        .scalars()
        .all()
    )
    await upsert_proposals(
        db,
        job_id,
        [
            {
                "candidate_id": candidate_id,
                "score": entry_meta.get("score"),
                "evidence": job_board_evidence(entry_meta),
                "cv_revision": candidate_revision(candidate),
            }
        ],
        source="job_board",
    )
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="moved_to_proposals",
            user_id=actor.id,
            details={
                "job_id": job_id,
                "process_id": process_id,
                "removal_id": removal.id,
                "source": "job_board",
            },
        )
    )
    await db.flush()
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "process_id": process_id,
        "removal_id": removal.id,
        "stage_id": stage_id,
        "stage_def_id": stage_def_id,
        "reverted_proposal_ids": [int(i) for i in reverted],
        "entry_meta": entry_meta,
    }


async def apply(
    db: AsyncSession,
    *,
    actor: Any,
    only_process_ids: Optional[set[int]] = None,
) -> dict[str, Any]:
    """Zapis: para po parze w savepointach, paczki po ``CHUNK`` z commitem.

    ``only_process_ids`` zawęża bieg (testy na wspólnej bazie); endpoint go
    nie przekazuje.
    """
    from app.models.user import User

    actor_id = int(actor.id)
    disqualifiers = await load_disqualifiers(db)
    targets = [
        (int(r["process_id"]), int(r["candidate_id"]), int(r["job_id"]))
        for r in (await db.execute(text(qualifying_sql(disqualifiers, one_pair=False))))
        .mappings()
        .all()
        if only_process_ids is None or int(r["process_id"]) in only_process_ids
    ]
    await db.rollback()
    # Wycofanie wygasza obiekty sesji — także ``actor``; odczyt ``actor.id``
    # w pętli doczytywałby leniwie (MissingGreenlet w async).
    actor = await db.get(User, actor_id)

    counts: Counter[str] = Counter({"moved": 0, "changed_meanwhile": 0, "failed": 0})
    per_job: Counter[int] = Counter()
    samples: list[dict[str, Any]] = []
    failed_process_ids: list[int] = []
    stopped = False
    for start in range(0, len(targets), CHUNK):
        chunk = targets[start : start + CHUNK]
        moved: list[dict[str, Any]] = []
        chunk_counts: Counter[str] = Counter()
        chunk_failed: list[int] = []
        try:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": LOCK_KEY}
            )
            for process_id, candidate_id, job_id in chunk:
                try:
                    async with db.begin_nested():
                        entry = await _convert_pair(
                            db,
                            process_id=process_id,
                            candidate_id=candidate_id,
                            job_id=job_id,
                            actor=actor,
                            disqualifiers=disqualifiers,
                        )
                except Exception as exc:  # noqa: BLE001 — para, nie cały bieg
                    logger.warning(
                        "job_board cards: process %s failed: %s",
                        process_id,
                        type(exc).__name__,
                    )
                    chunk_counts["failed"] += 1
                    chunk_failed.append(process_id)
                    continue
                if entry is None:
                    chunk_counts["changed_meanwhile"] += 1
                    continue
                chunk_counts["moved"] += 1
                moved.append(entry)
            if moved:
                await _append_details(db, moved)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.error("job_board cards: chunk failed: %s", type(exc).__name__)
            stopped = True
            break
        counts.update(chunk_counts)
        failed_process_ids.extend(
            chunk_failed[: max(0, FAILED_SAMPLE - len(failed_process_ids))]
        )
        for entry in moved:
            per_job[entry["job_id"]] += 1
            if len(samples) < SAMPLE_SIZE:
                samples.append(
                    {
                        "candidate_id": entry["candidate_id"],
                        "job_id": entry["job_id"],
                        "process_id": entry["process_id"],
                        "removal_id": entry["removal_id"],
                    }
                )
    return {
        "dry_run": False,
        "targets": len(targets),
        "stopped_on_error": stopped,
        "counts": dict(counts),
        "per_job": [
            {"job_id": job_id, "pairs": count}
            for job_id, count in sorted(per_job.items())
        ],
        "failed_process_ids": failed_process_ids,
        "samples": samples,
    }


async def finish_run(
    db: AsyncSession, report: dict[str, Any], *, started: datetime
) -> None:
    """Próba → ``DRY_RUN_KEY``; zapis → stan z sumami (paragon: liczby i ID)."""
    report = {
        **report,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    if report["dry_run"]:
        await _write_setting(db, DRY_RUN_KEY, report)
        await db.commit()
        return
    state = await _read_setting(db, STATE_KEY) or {}
    totals = dict(state.get("totals") or {})
    for key, value in report["counts"].items():
        totals[key] = int(totals.get(key) or 0) + int(value)
    await _write_setting(
        db,
        STATE_KEY,
        {
            "runs": int(state.get("runs") or 0) + 1,
            "totals": totals,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_run": report,
        },
    )
    await db.commit()


# ── Przebieg w tle ───────────────────────────────────────────────────────────

_running: dict[str, bool] = {"convert": False}


def is_running() -> bool:
    return _running["convert"]


async def fresh_dry_run_exists(db: AsyncSession) -> bool:
    report = await _read_setting(db, DRY_RUN_KEY)
    if not report or not report.get("finished_at"):
        return False
    try:
        finished = datetime.fromisoformat(str(report["finished_at"]))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - finished <= DRY_RUN_MAX_AGE


async def run_apply(*, actor_user_id: int) -> None:
    """Zapis w tle (spawn z endpointu) — ~2 tys. par to kilka minut."""
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    if _running["convert"]:
        return
    _running["convert"] = True
    started = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as db:
            actor = await db.get(User, actor_user_id)
            if actor is None:
                logger.error("job_board cards: actor %s missing", actor_user_id)
                return
            report = await apply(db, actor=actor)
            await finish_run(db, report, started=started)
            logger.info("job_board cards done: %s", json.dumps(report["counts"]))
    finally:
        _running["convert"] = False


async def read_status(db: AsyncSession) -> dict[str, Any]:
    return {
        "running": is_running(),
        "dry_run": await _read_setting(db, DRY_RUN_KEY),
        "state": await _read_setting(db, STATE_KEY),
    }


__all__ = [
    "DETAILS_KEY",
    "DRY_RUN_KEY",
    "STATE_KEY",
    "apply",
    "blocked_counts_sql",
    "fk_disqualifiers",
    "finish_run",
    "fresh_dry_run_exists",
    "plan",
    "qualifying_sql",
    "read_status",
    "run_apply",
]
