"""Jednorazowa naprawa notatek z Traffita (29.09.2026) — tylko z panelu admina.

Zmierzone na produkcji 29.09.2026 (odczyt): notatki z Traffita miały
* **datę importu** zamiast daty z Traffita — aktywność dostawała
  `created_at = NOW()`, a promocja do `notes` kopiowała tę wartość (notatka
  33542: Traffit 19.02.2026, NEXUS 05.05.2026);
* **złego autora** w 7 752 z 44 565 notatek z migracji 0077 (bez
  `source_ref`) — autor ≠ `created_by` aktywności w Traffit;
* **surowe wzmianki** `$$user_NN$$` (23 331 notatek), które render w UI
  rozwiązywał przez `users.external_id` — a ten nadpisuje logowanie SSO;
* **brak rekrutacji** — globalny feed aktywności jej nie niesie.

Decyzje właściciela (29.09.2026): data notatki = data z Traffita; autor
przeliczony z `created_by` aktywności (użytkownik Traffita → NEXUS po e-mailu,
jak `build_user_id_map`); wzmianki zapisane jako `@Imię Nazwisko` z listy
Traffit `/users/` (konto, którego Traffit już nie zna → `@(były użytkownik)`);
rekrutacja z aktywności osoby (`/employees/{id}/activities`).

Dopasowanie notatki do aktywności:
* notatka z syncu — `source_ref = 'traffit:activity:<id>'`;
* notatka z 0077 (`source_ref IS NULL`) — ten sam kandydat, ten sam
  `created_at` i ta sama treść po `note_unwrap_json`; wyłącznie para
  jednoznaczna w OBIE strony (jedna aktywność ↔ jedna notatka). Reszta to
  `ambiguous` i zostaje nietknięta. Dopasowana notatka dostaje `source_ref` —
  od tej chwili promocja rozpoznaje ją po źródle, a nie po znaczniku czasu,
  który naprawa właśnie zmienia (bez tego następny sync założyłby duplikat).

Zasady zapisu:
* nigdy INSERT — naprawa zmienia tylko istniejące notatki, więc notatka
  usunięta w NEXUSIE nie wraca; aktywność z nagrobkiem
  (`deleted_note_sources`) pomijamy w całości;
* `updated_at` zostaje nietknięty (odcisk nocnej analizy notatek przez AI) —
  zapis surowym SQL-em, bez ORM;
* paczki po ~1000 notatek, każda we własnej transakcji z blokadą doradczą;
  ponowny bieg nic nie zmienia (porównanie z wartością docelową);
* przebieg próbny (`dry_run`) niczego nie zapisuje w `notes` — raport
  (liczby + do 20 przykładowych ID z datą/autorem przed i po, bez treści)
  ląduje w `app_settings`, żeby właściciel mógł go zatwierdzić;
* paragon `traffit_notes_repair_2026_09` = liczby i ID; wartości sprzed
  zmiany pod `repair_details_traffit_notes_2026_09` (ani jeden, ani drugi
  klucz nie pasuje do wzorca publicznego `show_migration_receipts`).
  Treści sprzed zamiany wzmianek NIE przechowujemy — oryginał jest
  w `activities.details` aktywności.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.note_mention_render import (
    count_unknown_traffit_mentions,
    rewrite_traffit_mentions,
)
from app.services.traffit.importer import (
    ACTIVITY_AT_SQL,
    TRAFFIT_NOTE_ACTIONS,
    link_note_recruitments,
    safe_db_error,
)

logger = logging.getLogger(__name__)

RECEIPT_KEY = "traffit_notes_repair_2026_09"
DETAILS_KEY = "repair_details_traffit_notes_2026_09"
DRY_RUN_KEY = "traffit_notes_repair_2026_09_dry_run"
RECRUITMENTS_KEY = "traffit_notes_repair_2026_09_recruitments"
LOCK_KEY = "traffit_notes_repair_2026_09"
BATCH_SIZE = 1000
SAMPLE_SIZE = 20
RECRUITMENT_CHUNK = 50
# Zapis bez świeżego przebiegu próbnego = odmowa: właściciel zatwierdza
# liczby z próby, a nie z bazy sprzed tygodnia.
DRY_RUN_MAX_AGE = timedelta(days=7)

CHANGE_TYPES = ("dates", "authors", "mentions", "source_refs")

# Aktywności-notatki z datą i treścią po `note_unwrap_json` (ta sama reguła co
# promocja). Alias `a` — wymaga go `ACTIVITY_AT_SQL`.
_ACTS_CTE = f"""
acts AS (
    SELECT
        a.external_id,
        a.entity_id AS candidate_id,
        a.created_at AS a_created_at,
        a.user_id AS a_user_id,
        a.details ->> 'traffit_created_by_id' AS traffit_created_by_id,
        {ACTIVITY_AT_SQL} AS activity_at,
        LEFT(note_unwrap_json(COALESCE(
            a.details #>> '{{content,content}}',
            a.details ->> 'content',
            ''
        )), 50000) AS content
    FROM activities a
    WHERE a.external_source = 'traffit'
      AND a.entity_type = 'candidate'
      AND a.entity_id IS NOT NULL
      AND a.external_id IS NOT NULL
      AND a.action = ANY(CAST(:actions AS text[]))
)
"""

PLAN_SQL = f"""
WITH {_ACTS_CTE},
matches AS (
    SELECT n.id AS note_id, acts.external_id, false AS legacy,
           1::bigint AS k_note, 1::bigint AS k_act
    FROM notes n
    JOIN acts
      ON n.source_ref = 'traffit:activity:' || acts.external_id
     AND n.candidate_id = acts.candidate_id
    UNION ALL
    SELECT n.id, acts.external_id, true,
           count(*) OVER (PARTITION BY n.id),
           count(*) OVER (PARTITION BY acts.external_id)
    FROM notes n
    JOIN acts
      ON n.source_ref IS NULL
     AND acts.candidate_id = n.candidate_id
     AND acts.a_created_at = n.created_at
     AND n.content = acts.content
)
SELECT
    m.note_id,
    m.legacy,
    m.k_note,
    m.k_act,
    acts.external_id,
    acts.candidate_id,
    acts.activity_at,
    acts.a_user_id,
    acts.traffit_created_by_id,
    n.created_at AS note_created_at,
    n.source_created_at AS note_source_created_at,
    n.author_id AS note_author_id,
    (strpos(n.content, '$$user_') > 0) AS has_token,
    EXISTS (
        SELECT 1 FROM deleted_note_sources t
        WHERE t.source_ref = 'traffit:activity:' || acts.external_id
    ) AS tombstoned
FROM matches m
JOIN acts ON acts.external_id = m.external_id
JOIN notes n ON n.id = m.note_id
ORDER BY m.note_id
"""

# Notatki 0077 (bez `source_ref`) z aktywnością o tym samym znaczniku czasu —
# mianownik dla licznika „niedopasowane” (treść się nie zgodziła).
LEGACY_CANDIDATES_SQL = f"""
WITH {_ACTS_CTE}
SELECT count(DISTINCT n.id)
FROM notes n
JOIN acts
  ON n.source_ref IS NULL
 AND acts.candidate_id = n.candidate_id
 AND acts.a_created_at = n.created_at
"""

NOTES_WITHOUT_JOB_SQL = """
SELECT count(*) AS notes, count(DISTINCT n.candidate_id) AS candidates
FROM notes n
JOIN candidates c ON c.id = n.candidate_id
WHERE n.source_ref LIKE 'traffit:activity:%'
  AND n.job_id IS NULL
  AND c.external_source = 'traffit'
  AND c.external_id IS NOT NULL
"""

_UPDATE_FIELDS_SQL = """
UPDATE notes
SET created_at = :created_at,
    source_created_at = :source_created_at,
    author_id = :author_id,
    source_ref = :source_ref
WHERE id = :id
  AND (source_ref IS NULL OR source_ref = :source_ref)
"""

_UPDATE_CONTENT_SQL = "UPDATE notes SET content = :content WHERE id = :id"

# Sieroty w grupie (kandydat, stary znacznik czasu) notatek z 0077.
#
# Import z maja dał WSZYSTKIM aktywnościom jednej transakcji ten sam
# `created_at`. Aktywność, której notatkę ktoś usunął w NEXUSIE przed
# nagrobkami (0391), nie wracała przy promocji WYŁĄCZNIE dlatego, że gałąź
# „notatka bez `source_ref` z tym samym znacznikiem” pasowała do notatki
# innej aktywności z tej grupy. Naprawa nadaje tej notatce `source_ref`
# i nową datę — bez nagrobka następny sync przestawiłby datę sieroty
# i założył usuniętą notatkę od nowa. Sierota = aktywność-notatka z grupy
# z treścią, bez notatki po źródle, bez nagrobka, a w grupie nie zostaje
# już żadna notatka bez `source_ref` (ta dalej by ją chroniła).
# `:stamped_ids`/`:stamped_refs` = notatki, które naprawa właśnie oznacza
# (przebieg próbny symuluje zapis; w zapisie są już w bazie — puste tablice).
_ORPHANS_SQL = """
SELECT DISTINCT 'traffit:activity:' || a.external_id AS ref
FROM activities a
JOIN unnest(CAST(:cids AS integer[]), CAST(:ts AS timestamptz[])) AS g(cid, ts)
  ON a.entity_id = g.cid AND a.created_at = g.ts
WHERE a.external_source = 'traffit'
  AND a.entity_type = 'candidate'
  AND a.external_id IS NOT NULL
  AND a.action = ANY(CAST(:actions AS text[]))
  AND note_unwrap_json(COALESCE(
      a.details #>> '{content,content}',
      a.details ->> 'content',
      ''
  )) <> ''
  AND NOT (('traffit:activity:' || a.external_id) = ANY(CAST(:stamped_refs AS text[])))
  AND NOT EXISTS (
      SELECT 1 FROM notes n
      WHERE n.candidate_id = a.entity_id
        AND n.source_ref = 'traffit:activity:' || a.external_id
  )
  AND NOT EXISTS (
      SELECT 1 FROM deleted_note_sources t
      WHERE t.source_ref = 'traffit:activity:' || a.external_id
  )
  AND NOT EXISTS (
      SELECT 1 FROM notes n
      WHERE n.candidate_id = a.entity_id
        AND n.source_ref IS NULL
        AND n.created_at = a.created_at
        AND NOT (n.id = ANY(CAST(:stamped_ids AS integer[])))
  )
"""

_TOMBSTONE_SQL = """
INSERT INTO deleted_note_sources (source_ref)
SELECT unnest(CAST(:refs AS text[]))
ON CONFLICT (source_ref) DO NOTHING
"""


@dataclass
class NoteChange:
    note_id: int
    candidate_id: int
    legacy: bool
    source_ref: str
    old_created_at: datetime
    new_created_at: datetime
    old_source_created_at: Optional[datetime]
    new_source_created_at: Optional[datetime]
    old_author_id: Optional[int]
    new_author_id: Optional[int]
    has_token: bool

    @property
    def date_changed(self) -> bool:
        return self.new_created_at != self.old_created_at

    @property
    def source_date_changed(self) -> bool:
        return self.new_source_created_at != self.old_source_created_at

    @property
    def author_changed(self) -> bool:
        return self.new_author_id != self.old_author_id

    @property
    def fields_changed(self) -> bool:
        return (
            self.legacy
            or self.date_changed
            or self.source_date_changed
            or self.author_changed
        )


@dataclass
class RepairPlan:
    changes: list[NoteChange] = field(default_factory=list)
    matched_sync: int = 0
    matched_legacy: int = 0
    ambiguous: int = 0
    tombstoned: int = 0
    legacy_candidates: int = 0
    no_activity_date: int = 0
    author_unresolved: int = 0


def resolve_author(
    traffit_created_by_id: Optional[str],
    activity_user_id: Optional[int],
    user_map: dict[str, int],
) -> Optional[int]:
    """Autor = użytkownik NEXUSA dopasowany teraz po e-mailu do `created_by`
    aktywności; bez dopasowania — `activities.user_id` (dopasowany przy
    imporcie). `None` = nie wiemy — autor notatki zostaje bez zmian."""
    if traffit_created_by_id:
        mapped = user_map.get(str(traffit_created_by_id))
        if mapped is not None:
            return mapped
    return activity_user_id


async def build_plan(db: AsyncSession, user_map: dict[str, int]) -> RepairPlan:
    """Policz zmiany (wyłącznie odczyt)."""
    plan = RepairPlan()
    params = {"actions": list(TRAFFIT_NOTE_ACTIONS)}
    rows = (await db.execute(text(PLAN_SQL), params)).mappings().all()
    ambiguous_ids: set[int] = set()
    seen: set[int] = set()
    for row in rows:
        note_id = int(row["note_id"])
        legacy = bool(row["legacy"])
        if legacy and (row["k_note"] > 1 or row["k_act"] > 1):
            ambiguous_ids.add(note_id)
            continue
        if note_id in seen:
            continue
        seen.add(note_id)
        if row["tombstoned"]:
            plan.tombstoned += 1
            continue
        if legacy:
            plan.matched_legacy += 1
        else:
            plan.matched_sync += 1
        activity_at = row["activity_at"]
        if activity_at is None:
            plan.no_activity_date += 1
        new_created = activity_at or row["note_created_at"]
        new_source_created = activity_at or row["note_source_created_at"]
        author = resolve_author(
            row["traffit_created_by_id"], row["a_user_id"], user_map
        )
        if author is None:
            plan.author_unresolved += 1
            author = row["note_author_id"]
        plan.changes.append(
            NoteChange(
                note_id=note_id,
                candidate_id=int(row["candidate_id"]),
                legacy=legacy,
                source_ref=f"traffit:activity:{row['external_id']}",
                old_created_at=row["note_created_at"],
                new_created_at=new_created,
                old_source_created_at=row["note_source_created_at"],
                new_source_created_at=new_source_created,
                old_author_id=row["note_author_id"],
                new_author_id=author,
                has_token=bool(row["has_token"]),
            )
        )
    # Notatka niejednoznaczna nie może być też „dopasowana” inną ścieżką.
    plan.changes = [c for c in plan.changes if c.note_id not in ambiguous_ids]
    plan.ambiguous = len(ambiguous_ids)
    plan.legacy_candidates = int(
        (await db.execute(text(LEGACY_CANDIDATES_SQL), params)).scalar_one() or 0
    )
    return plan


async def _mention_rewrites(
    db: AsyncSession, changes: list[NoteChange], labels: dict[str, str]
) -> tuple[dict[int, str], int]:
    """Nowa treść notatek z tokenami (tylko te, które naprawdę się zmieniają)
    oraz liczba tokenów, które staną się `@(były użytkownik)`."""
    ids = [c.note_id for c in changes if c.has_token]
    if not ids or not labels:
        return {}, 0
    rows = await db.execute(
        text("SELECT id, content FROM notes WHERE id = ANY(CAST(:ids AS integer[]))"),
        {"ids": ids},
    )
    out: dict[int, str] = {}
    former = 0
    for note_id, content in rows.all():
        rewritten = rewrite_traffit_mentions(content, labels)
        if rewritten is not None and rewritten != content:
            out[int(note_id)] = rewritten
            former += count_unknown_traffit_mentions(content, labels)
    return out, former


async def _orphan_refs(
    db: AsyncSession,
    legacy: list[NoteChange],
    *,
    stamped_ids: list[int],
    stamped_refs: list[str],
) -> list[str]:
    """Źródła aktywności-sierot z grup (kandydat, stary znacznik) ``legacy``."""
    groups = sorted({(c.candidate_id, c.old_created_at) for c in legacy})
    refs: set[str] = set()
    for i in range(0, len(groups), 5000):
        chunk = groups[i : i + 5000]
        rows = await db.execute(
            text(_ORPHANS_SQL),
            {
                "cids": [g[0] for g in chunk],
                "ts": [g[1] for g in chunk],
                "actions": list(TRAFFIT_NOTE_ACTIONS),
                "stamped_ids": stamped_ids,
                "stamped_refs": stamped_refs,
            },
        )
        refs.update(str(r[0]) for r in rows.all())
    return sorted(refs)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _batches(items: list[NoteChange]) -> list[list[NoteChange]]:
    return [items[i : i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]


def _base_report(plan: RepairPlan) -> dict[str, Any]:
    return {
        "matched_sync": plan.matched_sync,
        "matched_legacy": plan.matched_legacy,
        "ambiguous": plan.ambiguous,
        "tombstoned": plan.tombstoned,
        "legacy_unmatched": max(
            0, plan.legacy_candidates - plan.matched_legacy - plan.ambiguous
        ),
        "no_activity_date": plan.no_activity_date,
        "author_unresolved": plan.author_unresolved,
    }


async def dry_run(
    db: AsyncSession, user_map: dict[str, int], labels: dict[str, str]
) -> dict[str, Any]:
    """Przebieg próbny: liczby i przykłady, ZERO zapisów w `notes`."""
    plan = await build_plan(db, user_map)
    counts = dict.fromkeys(CHANGE_TYPES, 0)
    samples: dict[str, list[dict[str, Any]]] = {k: [] for k in CHANGE_TYPES}
    mentions_former_user = 0
    for batch in _batches(plan.changes):
        rewrites, former = await _mention_rewrites(db, batch, labels)
        mentions_former_user += former
        for change in batch:
            if change.date_changed:
                counts["dates"] += 1
                if len(samples["dates"]) < SAMPLE_SIZE:
                    samples["dates"].append(
                        {
                            "note_id": change.note_id,
                            "before": _iso(change.old_created_at),
                            "after": _iso(change.new_created_at),
                        }
                    )
            if change.author_changed:
                counts["authors"] += 1
                if len(samples["authors"]) < SAMPLE_SIZE:
                    samples["authors"].append(
                        {
                            "note_id": change.note_id,
                            "before": change.old_author_id,
                            "after": change.new_author_id,
                        }
                    )
            if change.note_id in rewrites:
                counts["mentions"] += 1
                if len(samples["mentions"]) < SAMPLE_SIZE:
                    samples["mentions"].append({"note_id": change.note_id})
            if change.legacy:
                counts["source_refs"] += 1
                if len(samples["source_refs"]) < SAMPLE_SIZE:
                    samples["source_refs"].append({"note_id": change.note_id})
    legacy = [c for c in plan.changes if c.legacy]
    orphans = await _orphan_refs(
        db,
        legacy,
        stamped_ids=[c.note_id for c in legacy],
        stamped_refs=[c.source_ref for c in legacy],
    )
    jobs = (await db.execute(text(NOTES_WITHOUT_JOB_SQL))).mappings().one()
    # Zamknij transakcję odczytu — przebieg próbny nie zostawia otwartej sesji.
    await db.rollback()
    return {
        **_base_report(plan),
        "changes": counts,
        "samples": samples,
        # Tokeny, których konta Traffit już nie zna — staną się
        # `@(były użytkownik)`.
        "mentions_former_user": mentions_former_user,
        # Aktywności, których notatki usunięto w NEXUSIE przed nagrobkami
        # (0391) — dostaną nagrobek razem z nadaniem `source_ref`.
        "orphans_tombstoned": len(orphans),
        "mention_labels_available": bool(labels),
        # Rekrutacja: liczy ją osobny przebieg (zapytanie per osoba do
        # Traffita) — tu tylko ile notatek z syncu i ilu kandydatów czeka.
        "job_id": {
            "notes_without_job": int(jobs["notes"] or 0),
            "candidates_to_query": int(jobs["candidates"] or 0),
        },
    }


async def _append_details(db: AsyncSession, details: dict[str, list[Any]]) -> None:
    """Dopisz wartości sprzed zmiany (listy per rodzaj) do klucza szczegółów."""
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:key, CAST(:value AS jsonb), now())
            ON CONFLICT (key) DO UPDATE SET
                value = jsonb_build_object(
                    'dates', COALESCE(app_settings.value -> 'dates', '[]'::jsonb)
                             || (EXCLUDED.value -> 'dates'),
                    'authors', COALESCE(app_settings.value -> 'authors', '[]'::jsonb)
                               || (EXCLUDED.value -> 'authors'),
                    'source_refs', COALESCE(app_settings.value -> 'source_refs', '[]'::jsonb)
                                   || (EXCLUDED.value -> 'source_refs'),
                    'mentions', COALESCE(app_settings.value -> 'mentions', '[]'::jsonb)
                                || (EXCLUDED.value -> 'mentions'),
                    'orphans', COALESCE(app_settings.value -> 'orphans', '[]'::jsonb)
                               || (EXCLUDED.value -> 'orphans')
                ),
                updated_at = now()
            """
        ),
        {"key": DETAILS_KEY, "value": json.dumps(details)},
    )


async def apply(
    db: AsyncSession, user_map: dict[str, int], labels: dict[str, str]
) -> dict[str, Any]:
    """Zapisz naprawę paczkami; każda paczka we własnej transakcji."""
    plan = await build_plan(db, user_map)
    await db.rollback()
    counts = dict.fromkeys(CHANGE_TYPES, 0)
    orphans_tombstoned = 0
    mentions_former_user = 0
    skipped_concurrent = 0
    failed_batches = 0
    for batch in _batches(plan.changes):
        try:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": LOCK_KEY}
            )
            rewrites, former = await _mention_rewrites(db, batch, labels)
            field_rows: list[dict[str, Any]] = []
            details: dict[str, list[Any]] = {
                "dates": [],
                "authors": [],
                "source_refs": [],
                "mentions": [],
                "orphans": [],
            }
            for change in batch:
                if not change.fields_changed:
                    continue
                field_rows.append(
                    {
                        "id": change.note_id,
                        "created_at": change.new_created_at,
                        "source_created_at": change.new_source_created_at,
                        "author_id": change.new_author_id,
                        "source_ref": change.source_ref,
                    }
                )
            written: set[int] = set()
            for row in field_rows:
                result = await db.execute(text(_UPDATE_FIELDS_SQL), row)
                if result.rowcount:
                    written.add(row["id"])
                else:
                    skipped_concurrent += 1
            for change in batch:
                if change.note_id not in written:
                    continue
                if change.date_changed:
                    counts["dates"] += 1
                    details["dates"].append(
                        [change.note_id, _iso(change.old_created_at)]
                    )
                if change.author_changed:
                    counts["authors"] += 1
                    details["authors"].append([change.note_id, change.old_author_id])
                if change.legacy:
                    counts["source_refs"] += 1
                    details["source_refs"].append(change.note_id)
            # Nagrobki sierot w TEJ SAMEJ transakcji co nadanie `source_ref`
            # — między nimi nie może wejść sync, który założyłby usuniętą
            # notatkę od nowa.
            stamped = [c for c in batch if c.legacy and c.note_id in written]
            if stamped:
                orphans = await _orphan_refs(
                    db, stamped, stamped_ids=[], stamped_refs=[]
                )
                if orphans:
                    await db.execute(text(_TOMBSTONE_SQL), {"refs": orphans})
                    details["orphans"].extend(orphans)
            content_rows = [
                {"id": note_id, "content": content}
                for note_id, content in rewrites.items()
            ]
            if content_rows:
                await db.execute(text(_UPDATE_CONTENT_SQL), content_rows)
                counts["mentions"] += len(content_rows)
                details["mentions"].extend(sorted(rewrites))
            if any(details.values()):
                await _append_details(db, details)
            await db.commit()
            orphans_tombstoned += len(details["orphans"])
            mentions_former_user += former
        except Exception as exc:  # noqa: BLE001
            failed_batches += 1
            logger.error("Traffit notes repair: batch failed: %s", safe_db_error(exc))
            await db.rollback()
    return {
        **_base_report(plan),
        "changes": counts,
        "orphans_tombstoned": orphans_tombstoned,
        "mentions_former_user": mentions_former_user,
        "skipped_concurrent": skipped_concurrent,
        "failed_batches": failed_batches,
    }


# ── Stan i przebiegi w tle ───────────────────────────────────────────────────

_running: dict[str, bool] = {"notes": False, "recruitments": False}


def is_running() -> bool:
    return any(_running.values())


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


async def fresh_dry_run_exists(db: AsyncSession) -> bool:
    report = await _read_setting(db, DRY_RUN_KEY)
    if not report or not report.get("finished_at"):
        return False
    try:
        finished = datetime.fromisoformat(str(report["finished_at"]))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - finished <= DRY_RUN_MAX_AGE


async def run_notes_repair(*, dry_run_mode: bool) -> None:
    """Bieg w tle (spawn z endpointu): Traffit `/users/` → plan → raport/zapis."""
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.client import TraffitClient, TraffitConfig
    from app.services.traffit.importer import TraffitImporter
    from app.tasks.traffit_sync import traffit_exclusive_lock

    if _running["notes"]:
        return
    _running["notes"] = True
    started = datetime.now(timezone.utc)
    try:
        lock = traffit_exclusive_lock()
        if lock.locked():
            logger.warning("Traffit notes repair skipped: sync running")
            return
        async with lock:
            config = TraffitConfig.from_env()
            async with TraffitClient(config) as traffit:
                async with AsyncSessionLocal() as db:
                    importer = TraffitImporter(traffit, db)
                    user_map = await importer.build_user_id_map()
                    labels = importer.traffit_user_labels()
                    await db.rollback()
                    if dry_run_mode:
                        report = await dry_run(db, user_map, labels)
                        key = DRY_RUN_KEY
                    else:
                        report = await apply(db, user_map, labels)
                        key = RECEIPT_KEY
                    report.update(
                        {
                            "dry_run": dry_run_mode,
                            "started_at": started.isoformat(),
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "traffit_users_mapped": len(user_map),
                        }
                    )
                    await _write_setting(db, key, report)
                    await db.commit()
                    logger.info(
                        "Traffit notes repair done (dry_run=%s): %s",
                        dry_run_mode,
                        json.dumps(report.get("changes")),
                    )
    finally:
        _running["notes"] = False


async def run_recruitment_backfill(*, dry_run_mode: bool, limit: int) -> None:
    """Rekrutacje notatek z `/employees/{id}/activities` — kursor po kandydacie.

    Kandydaci z notatkami z Traffita (z `source_ref`) bez `job_id`, rosnąco po
    id, najwyżej ``limit`` w biegu. Kursor (`after_candidate_id`) zapisywany co
    paczkę, więc przerwany bieg (deploy) wznawia się od miejsca, w którym
    stanął. Przebieg próbny nie przesuwa kursora i nie pisze do `notes`.
    """
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.client import TraffitClient, TraffitConfig
    from app.tasks.traffit_sync import traffit_exclusive_lock

    if _running["recruitments"]:
        return
    _running["recruitments"] = True
    try:
        lock = traffit_exclusive_lock()
        if lock.locked():
            logger.warning("Traffit note recruitments skipped: sync running")
            return
        async with lock:
            config = TraffitConfig.from_env()
            async with TraffitClient(config) as traffit:
                async with AsyncSessionLocal() as db:
                    state = await _read_setting(db, RECRUITMENTS_KEY) or {}
                    after = int(state.get("after_candidate_id") or 0)
                    totals = {
                        k: int(state.get(k) or 0)
                        for k in ("candidates", "linked", "found", "failed", "no_job")
                    }
                    run_stats = dict.fromkeys(totals, 0)
                    rows = await db.execute(
                        text(
                            """
                            SELECT c.id, c.external_id
                            FROM candidates c
                            WHERE c.external_source = 'traffit'
                              AND c.external_id IS NOT NULL
                              AND c.id > :after
                              AND EXISTS (
                                  SELECT 1 FROM notes n
                                  WHERE n.candidate_id = c.id
                                    AND n.source_ref LIKE 'traffit:activity:%'
                                    AND n.job_id IS NULL
                              )
                            ORDER BY c.id
                            LIMIT :limit
                            """
                        ),
                        {"after": after, "limit": max(1, int(limit))},
                    )
                    targets = [(int(r[0]), str(r[1])) for r in rows.all()]
                    await db.rollback()
                    job_rows = await db.execute(
                        text(
                            "SELECT id, external_id FROM jobs "
                            "WHERE external_source='traffit' AND external_id IS NOT NULL"
                        )
                    )
                    job_map = {str(r.external_id): int(r.id) for r in job_rows}
                    await db.rollback()
                    for i in range(0, len(targets), RECRUITMENT_CHUNK):
                        chunk = targets[i : i + RECRUITMENT_CHUNK]
                        stats = await link_note_recruitments(
                            traffit, db, chunk, job_map=job_map, dry_run=dry_run_mode
                        )
                        for k in run_stats:
                            run_stats[k] += stats.get(k, 0)
                        if not dry_run_mode:
                            after = chunk[-1][0]
                            await _write_setting(
                                db,
                                RECRUITMENTS_KEY,
                                {
                                    "after_candidate_id": after,
                                    **{k: totals[k] + run_stats[k] for k in totals},
                                    "finished": False,
                                    "updated_at": datetime.now(
                                        timezone.utc
                                    ).isoformat(),
                                },
                            )
                            await db.commit()
                    summary = {
                        "last_run": {
                            **run_stats,
                            "dry_run": dry_run_mode,
                            "limit": int(limit),
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                        }
                    }
                    if dry_run_mode:
                        state.update(summary)
                    else:
                        state = {
                            "after_candidate_id": after,
                            **{k: totals[k] + run_stats[k] for k in totals},
                            # Mniej celów niż limit = przeszliśmy do końca listy.
                            "finished": len(targets) < max(1, int(limit)),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                            **summary,
                        }
                    await _write_setting(db, RECRUITMENTS_KEY, state)
                    await db.commit()
    finally:
        _running["recruitments"] = False


async def read_status(db: AsyncSession) -> dict[str, Any]:
    receipt = await _read_setting(db, RECEIPT_KEY)
    return {
        "running": dict(_running),
        "dry_run": await _read_setting(db, DRY_RUN_KEY),
        "applied": receipt,
        "recruitments": await _read_setting(db, RECRUITMENTS_KEY),
    }


def spawn_running_guard() -> Optional[str]:
    """Powód odmowy startu (409) albo ``None``."""
    from app.tasks.traffit_sync import sync_is_running

    if sync_is_running():
        return "Trwa synchronizacja z Traffitem — spróbuj po jej zakończeniu."
    if is_running():
        return "Naprawa notatek z Traffita już trwa."
    return None


__all__ = [
    "DETAILS_KEY",
    "DRY_RUN_KEY",
    "RECEIPT_KEY",
    "RECRUITMENTS_KEY",
    "apply",
    "build_plan",
    "dry_run",
    "fresh_dry_run_exists",
    "read_status",
    "resolve_author",
    "run_notes_repair",
    "run_recruitment_backfill",
    "spawn_running_guard",
]
