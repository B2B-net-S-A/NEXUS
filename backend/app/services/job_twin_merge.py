"""Scalenie rekrutacji-duplikatów po migracji z Traffita (12.10.2026).

Migracja całego zespołu otworzyła kopie z Traffita także tam, gdzie ten sam
request był już założony w NEXUSIE. Request stał na liście dwa razy: w kopii
byli kandydaci z Traffita, w rekrutacji NEXUSA zespół, Profil Championa
i propozycje. Scalenie zostawia rekrutację NEXUSA, przepina do niej pary
z kopii razem z historią i zamyka kopię.

Pary (kopia → rekrutacja NEXUSA) pochodzą z paragonu przeniesienia: ostatni
wpis ``traffit_transfer`` kopii z ``twin_exact`` (ten sam tytuł i numer
requestu). Podobny tytuł nie wystarcza — to może być inny request.

Dwa biegi tej samej reguły, jak przy przeniesieniu:

* **próba** (``dry_run=true``) — raport per para: ile osób przejdzie, kto jest
  w obu rekrutacjach, ile notatek, kart rekomendacji, CV i propozycji pójdzie
  za osobami, w której kolumnie staną. Niczego nie zmienia;
* **wykonanie** (``dry_run=false``, po próbie tego samego zakresu z ostatnich
  24 godzin) — każda para we własnej transakcji; paragon niesie id
  przeniesionych kandydatów, więc parę da się cofnąć tym samym przepięciem
  w drugą stronę.

Czego scalenie świadomie NIE robi:

* nie zmienia zespołu rekrutacji NEXUSA (decyzja Artura 12.10.2026:
  przypisane osoby mają się nie zmieniać) — kopia dostała ten zespół przy
  przeniesieniu;
* nie skleja dwóch historii jednej osoby: kto ma kartę w obu rekrutacjach,
  zostaje przy karcie z NEXUSA, a jego historia z Traffita przy zamkniętej
  kopii (raport wymienia te osoby);
* nie przenosi rzeczy liczonych per rekrutacja (dopasowania, migawki
  propozycji, „Moi ludzie”) — NEXUS policzy je dla rekrutacji, która zostaje;
* nie przenosi osoby, której przepięcie odebrałoby kredyt KPI (``kpi_hold``,
  patrz ``_PEOPLE_SQL``) — reguł KPI dla jednego biegu nie zmieniamy;
* nie zdejmuje z kopii flagi „Prowadzona w NEXUSIE”: bez niej import odtworzyłby
  w kopii pary, które właśnie przeszły.

Raport i paragon leżą w ``app_settings`` (liczby i ID, bez nazwisk).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.board_stage_badges import board_column_for

logger = logging.getLogger(__name__)

DRY_RUN_KEY = "traffit_twins_merge_dry_run"
LOG_KEY = "traffit_twins_merge_log"
MERGE_ACTION = "traffit_twin_merged"
DRY_RUN_MAX_AGE = timedelta(hours=24)

SKIP_MERGED = "already_merged"
SKIP_SOURCE = "copy_not_managed_in_nexus"
SKIP_TARGET = "target_not_nexus_job"
SKIP_SHARED = "target_has_two_copies"
SKIP_CLIENT = "different_client"
SKIP_TARGET_CLOSED = "target_not_open"
SKIP_CHANGED = "changed"
SKIP_NOT_REVIEWED = "not_in_dry_run"


@dataclass(frozen=True)
class Scope:
    """Zakres: wszystkie pewne pary albo wskazane kopie (id NEXUSA)."""

    job_ids: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"job_ids": sorted(self.job_ids)}

    def key(self) -> str:
        raw = json.dumps(self.as_dict(), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Pair(NamedTuple):
    """Kopia z Traffita (``source_id``) i rekrutacja NEXUSA, która zostaje."""

    source_id: int
    target_id: int


class JobFacts(NamedTuple):
    job_id: int
    external_source: Optional[str]
    managed_in_nexus: bool
    status: str
    client_id: Optional[int]


def skip_reason(
    source: Optional[JobFacts],
    target: Optional[JobFacts],
    *,
    shared: bool,
    merged: bool,
) -> Optional[str]:
    """Powód pominięcia pary albo ``None``, gdy parę wolno scalić.

    Kopia może być już zamknięta przez człowieka — jej osoby i tak przechodzą.
    Rekrutacja NEXUSA musi być otwarta: przepięcie ludzi do zamkniętej
    schowałoby ich z Tablicy, a o jej otwarciu decyduje Delivery Lead.
    """
    if merged:
        return SKIP_MERGED
    if (
        source is None
        or source.external_source != "traffit"
        or not source.managed_in_nexus
    ):
        return SKIP_SOURCE
    if target is None or target.external_source == "traffit":
        return SKIP_TARGET
    if shared:
        return SKIP_SHARED
    if source.client_id != target.client_id:
        return SKIP_CLIENT
    if target.status != "published":
        return SKIP_TARGET_CLOSED
    return None


def parse_pairs(rows: list[tuple[Any, Any, Any]]) -> list[Pair]:
    """Wiersze ``(kopia, bliźniak, pewny)`` z historii → pewne pary.

    ``details`` wpisu to JSON pisany przez przeniesienie; czytamy go
    ostrożnie, bo starsze wpisy nie mają pola ``twin_exact``.
    """
    pairs: list[Pair] = []
    for source_id, target, exact in rows:
        if str(exact).lower() != "true" or not str(target or "").isdigit():
            continue
        if int(target) != int(source_id):
            pairs.append(Pair(int(source_id), int(target)))
    return pairs


_PAIRS_SQL = """
SELECT DISTINCT ON (a.entity_id)
       a.entity_id,
       a.details->>'twin_job_id' AS twin_job_id,
       a.details->>'twin_exact' AS twin_exact
FROM activities a
WHERE a.entity_type = 'job' AND a.action = 'traffit_transfer'
ORDER BY a.entity_id, a.id DESC
"""

# `kpi_hold`: `VERIFIER_ANCHORED_CTE` (`services/kpi_panel.py`) kredytuje
# historię sprzed pierwszego sklasyfikowanego procesu pary tylko do chwili jego
# otwarcia — a liczy też procesy unieważnione. Unieważniony proces rekrutacji
# NEXUSA, otwarty wcześniej niż pierwszy sklasyfikowany proces kopii, zabrałby
# po przepięciu kredyt kamieniom milowym z tej przerwy. Takiej osoby nie
# przenosimy; raport ją wymienia.
_FIRST_CLASSIFIED = """
    SELECT MIN(p.opened_at) AS opened_at
    FROM recruitment_processes p
    WHERE p.job_id = {job} AND p.candidate_id = people.candidate_id
      AND p.opened_at IS NOT NULL AND p.origin_kind IS NOT NULL
      AND CAST(p.origin_kind AS text) <> 'legacy'
"""

_PEOPLE_SQL = f"""
SELECT people.candidate_id,
       (EXISTS (
           SELECT 1 FROM candidate_stages x
           WHERE x.job_id = :target AND x.candidate_id = people.candidate_id
       ) OR EXISTS (
           SELECT 1 FROM recruitment_processes p
           WHERE p.job_id = :target AND p.candidate_id = people.candidate_id
             AND p.status <> 'voided'
       )) AS in_target,
       EXISTS (
           SELECT 1 FROM analytics_first_milestones afm
           WHERE afm.job_id = :source AND afm.candidate_id = people.candidate_id
             AND afm.first_reached_at >= in_nexus.opened_at
             AND (in_copy.opened_at IS NULL
                  OR afm.first_reached_at < in_copy.opened_at)
       ) AS kpi_hold
FROM (
    SELECT DISTINCT candidate_id FROM candidate_stages WHERE job_id = :source
) people
LEFT JOIN LATERAL ({_FIRST_CLASSIFIED.format(job=":target")}) in_nexus ON true
LEFT JOIN LATERAL ({_FIRST_CLASSIFIED.format(job=":source")}) in_copy ON true
ORDER BY people.candidate_id
"""

_CURRENT_SQL = """
SELECT DISTINCT ON (cs.candidate_id)
       cs.candidate_id, CAST(cs.stage AS text) AS stage,
       sd.name, sd.category, sd.terminal_type
FROM candidate_stages cs
LEFT JOIN pipeline_stage_defs sd ON sd.id = cs.stage_def_id
WHERE cs.job_id = :source
ORDER BY cs.candidate_id, cs.moved_at DESC, cs.id DESC
"""

_OPEN_PROPOSAL_PEOPLE_SQL = """
SELECT jp.candidate_id FROM job_proposals jp
WHERE jp.job_id = :source AND jp.status = 'proposed'
  AND NOT EXISTS (
      SELECT 1 FROM job_proposals x
      WHERE x.job_id = :target AND x.candidate_id = jp.candidate_id
        AND x.source = jp.source
  )
  AND NOT EXISTS (
      SELECT 1 FROM candidate_stages x
      WHERE x.job_id = :target AND x.candidate_id = jp.candidate_id
  )
"""


class Follow(NamedTuple):
    """Tabela z danymi pary, które idą za przeniesioną osobą albo propozycją."""

    key: str
    table: str
    where: str
    column: str = "job_id"

    def count_sql(self) -> str:
        return f"SELECT count(*) FROM {self.table} WHERE {self.where}"

    def update_sql(self) -> str:
        return f"UPDATE {self.table} SET {self.column} = :target WHERE {self.where}"


_PAIR_ROWS = "job_id = :source AND candidate_id = ANY(CAST(:ids AS integer[]))"


def _unless_target_has(table: str) -> str:
    # Para w rekrutacji docelowej jest unikalna: istniejący wiersz zostaje.
    return (
        f"{_PAIR_ROWS} AND NOT EXISTS (SELECT 1 FROM {table} x "
        f"WHERE x.job_id = :target AND x.candidate_id = {table}.candidate_id)"
    )


#: Wszystko, co opisuje pracę z osobą W TEJ rekrutacji. Wiersze etapów
#: i procesy przepina `recruitment_process_commands.move_pairs_to_job`.
FOLLOW: tuple[Follow, ...] = (
    Follow("notes", "notes", _PAIR_ROWS),
    Follow("stage_cvs", "candidate_stage_cvs", _PAIR_ROWS),
    Follow("generated_cvs", "cv_generated_documents", _PAIR_ROWS),
    Follow("cv_qc_runs", "cv_qc_runs", _PAIR_ROWS),
    Follow("rate_changes", "candidate_rate_changes", _PAIR_ROWS),
    Follow("contracts", "b2b_generated_contracts", _PAIR_ROWS),
    # Terminy, prepy i feedback czytają parę po (kandydat, rekrutacja):
    # bramka debriefu, checklista ruchu, odznaka rozmowy na karcie.
    Follow("calendar_events", "calendar_events", _PAIR_ROWS),
    Follow("interview_feedback", "interview_feedback", _PAIR_ROWS),
    Follow("prep_meetings", "prep_meetings", _PAIR_ROWS),
    Follow("prep_transcripts", "prep_transcripts", _PAIR_ROWS),
    Follow("prep_reviews", "prep_reviews", _PAIR_ROWS),
    Follow("question_ratings", "interview_question_ratings", _PAIR_ROWS),
    # Wysyłka sprawdza bieżący etap pary — bez tego anulowałaby maila.
    Follow("rejection_emails", "scheduled_rejection_emails", _PAIR_ROWS),
    # Ślad zgłoszenia osoby, której propozycja przechodzi.
    Follow("application_screenings", "application_screenings", _PAIR_ROWS),
    Follow("source_events", "candidate_source_events", _PAIR_ROWS),
    Follow(
        "application_submissions",
        "application_submissions",
        "job_id = :source AND matched_candidate_id = ANY(CAST(:ids AS integer[]))",
    ),
    Follow(
        "slot_requests",
        "client_interview_slot_requests",
        _unless_target_has("client_interview_slot_requests"),
    ),
    Follow(
        "placement_exclusions",
        "placement_exclusions",
        _unless_target_has("placement_exclusions"),
    ),
    Follow(
        "recommendation_cards",
        "recommendation_cards",
        _unless_target_has("recommendation_cards"),
    ),
    Follow(
        "screening_forms",
        "screening_form_versions",
        _unless_target_has("screening_form_versions"),
    ),
    # 0450: champion idzie za osobą; flaga „nie szukamy” rekrutacji docelowej
    # przelicza się przy najbliższym zapisie listy albo ruchu championa.
    Follow(
        "champions",
        "job_champions",
        _unless_target_has("job_champions"),
    ),
    Follow(
        "rate_from",
        "candidates",
        "rate_from_job_id = :source AND id = ANY(CAST(:ids AS integer[]))",
        column="rate_from_job_id",
    ),
)


def _params(sql: str, pair: Pair, ids: list[int]) -> dict[str, Any]:
    params: dict[str, Any] = {"source": pair.source_id, "ids": ids}
    if ":target" in sql:
        params["target"] = pair.target_id
    return params


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


# ── Odczyty ──────────────────────────────────────────────────────────────────


async def load_pairs(db: AsyncSession) -> list[Pair]:
    """Wszystkie pewne pary z paragonów przeniesienia (bez zawężenia)."""
    rows = (await db.execute(text(_PAIRS_SQL))).all()
    return parse_pairs([(r.entity_id, r.twin_job_id, r.twin_exact) for r in rows])


async def load_facts(db: AsyncSession, job_ids: list[int]) -> dict[int, JobFacts]:
    if not job_ids:
        return {}
    rows = await db.execute(
        text(
            "SELECT id, external_source, managed_in_nexus, "
            "CAST(status AS text) AS status, client_id "
            "FROM jobs WHERE id = ANY(CAST(:ids AS integer[]))"
        ),
        {"ids": job_ids},
    )
    return {
        int(r.id): JobFacts(
            int(r.id),
            r.external_source,
            bool(r.managed_in_nexus),
            r.status,
            r.client_id,
        )
        for r in rows.all()
    }


async def load_merged(db: AsyncSession, job_ids: list[int]) -> set[int]:
    if not job_ids:
        return set()
    rows = await db.execute(
        text(
            "SELECT DISTINCT entity_id FROM activities "
            "WHERE entity_type = 'job' AND action = :action "
            "AND entity_id = ANY(CAST(:ids AS integer[]))"
        ),
        {"action": MERGE_ACTION, "ids": job_ids},
    )
    return {int(r.entity_id) for r in rows.all()}


class People(NamedTuple):
    """Osoby z kartą w kopii."""

    movable: list[int]
    in_both: list[int]
    kpi_hold: list[int]

    def everyone(self) -> set[int]:
        return {*self.movable, *self.in_both, *self.kpi_hold}


async def _people(db: AsyncSession, pair: Pair) -> People:
    """Kto przejdzie, kto jest w obu rekrutacjach, kogo wstrzymuje kredyt KPI."""
    rows = await db.execute(
        text(_PEOPLE_SQL), {"source": pair.source_id, "target": pair.target_id}
    )
    people = People([], [], [])
    for row in rows.all():
        if row.in_target:
            people.in_both.append(int(row.candidate_id))
        elif row.kpi_hold:
            people.kpi_hold.append(int(row.candidate_id))
        else:
            people.movable.append(int(row.candidate_id))
    return people


async def _columns(db: AsyncSession, pair: Pair, ids: list[int]) -> dict[str, int]:
    """W której kolumnie Tablicy staną przeniesione osoby."""
    wanted = set(ids)
    counts: Counter[str] = Counter()
    rows = await db.execute(text(_CURRENT_SQL), {"source": pair.source_id})
    for row in rows.all():
        if int(row.candidate_id) in wanted:
            counts[
                board_column_for(
                    row.name,
                    row.stage,
                    category=row.category,
                    terminal_type=row.terminal_type,
                )
            ] += 1
    return dict(counts)


async def _follow_counts(
    db: AsyncSession, pair: Pair, movable: list[int]
) -> dict[str, int]:
    """Próba: ile wierszy pójdzie za osobami z kartą i za propozycjami."""
    with_card = set(movable)
    rows = await db.execute(
        text(_OPEN_PROPOSAL_PEOPLE_SQL),
        {"source": pair.source_id, "target": pair.target_id},
    )
    # Kto przechodzi z kartą, po przepięciu stoi w pipeline — jego propozycja
    # zostaje przy kopii (lustro `job_proposals.move_open_to_job`).
    proposed = [int(r.candidate_id) for r in rows.all()]
    proposed = [
        candidate_id for candidate_id in proposed if candidate_id not in with_card
    ]
    ids = sorted(with_card | set(proposed))
    counts: dict[str, int] = {}
    for follow in FOLLOW:
        sql = follow.count_sql()
        counts[follow.key] = int(
            (await db.execute(text(sql), _params(sql, pair, ids))).scalar_one()
        )
    counts["proposals"] = len(proposed)
    return counts


async def _follow(db: AsyncSession, pair: Pair, moved: list[int]) -> dict[str, int]:
    """Wykonanie — wołane PO przepięciu kart (propozycje patrzą na pipeline)."""
    from app.services import job_proposals

    proposed = await job_proposals.move_open_to_job(
        db, source_job_id=pair.source_id, target_job_id=pair.target_id
    )
    ids = sorted({*moved, *proposed})
    counts: dict[str, int] = {follow.key: 0 for follow in FOLLOW}
    if ids:
        for follow in FOLLOW:
            sql = follow.update_sql()
            result = await db.execute(text(sql), _params(sql, pair, ids))
            counts[follow.key] = int(result.rowcount or 0)
    counts["proposals"] = len(proposed)
    # Osoba, która przeszła z kartą, nie jest już propozycją tej rekrutacji.
    counts["proposals_added"] = await job_proposals.mark_added(
        db, job_id=pair.target_id, candidate_ids=moved
    )
    return counts


# ── Jedna para ───────────────────────────────────────────────────────────────


def _report(pair: Pair, *, status: str, **extra: Any) -> dict[str, Any]:
    return {
        "job_id": pair.source_id,
        "target_job_id": pair.target_id,
        "status": status,
        **extra,
    }


def _facts(job: Any) -> Optional[JobFacts]:
    if job is None:
        return None
    return JobFacts(
        int(job.id),
        job.external_source,
        bool(job.managed_in_nexus),
        getattr(job.status, "value", job.status),
        job.client_id,
    )


async def _close_copy(
    db: AsyncSession,
    source: Any,
    target: Any,
    *,
    actor_id: int,
    effects: Any,
    now: datetime,
) -> bool:
    """Zamknij kopię jak archiwum z Traffita — bez daty i powodu zamknięcia.

    Duplikat nie jest zamkniętym requestem: ``closed_at`` i ``close_reason``
    policzyłyby go w raportach zamknięć i w Lidze DL. Kopię zamkniętą już
    przez człowieka zostawiamy z jego powodem. Zwraca, czy coś zamknięto.
    """
    from sqlalchemy import case, exists, literal, select, update
    from sqlalchemy.orm import aliased

    from app.core.cache import cache_invalidate
    from app.models.job import JobStatus
    from app.models.job_work_assignment import JobWorkAssignment
    from app.services import job_lifecycle
    from app.services.candidate_contact_hooks import (
        maybe_close_job_contact_opportunities,
    )
    from app.services.job_portals.service import close_live_postings
    from app.services.job_proposals import expire_open_for_job
    from app.services.request_work_state import set_work_state

    # Osoba, która ma ten sam request w rekrutacji NEXUSA, niczego nie traci:
    # „reassigned” nie trafia do porannego „Zwolnione: …” (`is_silent_release`).
    twin = aliased(JobWorkAssignment)
    still_has_request = exists(
        select(literal(1)).where(
            twin.job_id == target.id,
            twin.user_id == JobWorkAssignment.user_id,
            twin.state != "released",
        )
    )
    await db.execute(
        update(JobWorkAssignment)
        .where(
            JobWorkAssignment.job_id == source.id,
            JobWorkAssignment.state != "released",
        )
        .values(
            state="released",
            released_at=now,
            release_reason=case((still_has_request, "reassigned"), else_="finished"),
        )
        .execution_options(synchronize_session=False)
    )
    if source.status == JobStatus.closed:
        return False
    api = job_lifecycle._api()  # noqa: SLF001 — to samo wejście co zamknięcie
    # Lustro `close_job_core`: zespół duplikatu do „Poprzedni rekruter”.
    from app.services.job_previous_recruiters import park_team  # noqa: PLC0415

    await park_team(
        db,
        source,
        reason="closed",
        actor_id=actor_id,
        notify=False,
        release_assignments=False,
    )
    source.status = JobStatus.closed
    source.is_open = False
    source.close_notes = f"Duplikat z Traffita — scalona z rekrutacją #{target.id}."
    await set_work_state(
        db, source, "finished", actor_id=actor_id, reason="twin_merged"
    )
    await close_live_postings(db, source.id)
    await expire_open_for_job(db, job_id=source.id)
    await maybe_close_job_contact_opportunities(
        db,
        job_id=source.id,
        actor_user_id=actor_id,
        reason="job_closed",
        occurred_at=now,
    )
    effects.add("reports_cache", lambda: cache_invalidate("reports:clients"))
    effects.add("status_payload", lambda: api._sync_job_status_payload(source))
    return True


async def merge_pair(
    db: AsyncSession,
    pair: Pair,
    *,
    shared: bool,
    merged: bool,
    actor_user_id: Optional[int],
    dry_run: bool,
) -> dict[str, Any]:
    """Próba albo scalenie jednej pary — własna transakcja."""
    from sqlalchemy import select

    from app.models.activity import Activity
    from app.models.job import Job
    from app.models.user import User
    from app.services import job_lifecycle
    from app.services.recruitment_allocation import allocation_lock
    from app.services.recruitment_process_commands import move_pairs_to_job
    from app.services.traffit.importer import safe_db_error

    effects = job_lifecycle.PostCommit()
    try:
        facts = await load_facts(db, [pair.source_id, pair.target_id])
        reason = skip_reason(
            facts.get(pair.source_id),
            facts.get(pair.target_id),
            shared=shared,
            merged=merged,
        )
        if reason:
            await db.rollback()
            return _report(pair, status="skipped", skip_reason=reason)
        if not dry_run:
            await allocation_lock(db)
        people = await _people(db, pair)
        movable, in_both, held = people
        if dry_run:
            plan = {
                "people": len(people.everyone()),
                "moved": len(movable),
                "in_both": len(in_both),
                "in_both_ids": in_both,
                "kpi_hold": len(held),
                "kpi_hold_ids": held,
                "columns": await _columns(db, pair, movable),
                "copy_already_closed": facts[pair.source_id].status == "closed",
                **await _follow_counts(db, pair, movable),
            }
            await db.rollback()
            return _report(pair, status="ready", **plan)

        actor = await db.get(User, actor_user_id) if actor_user_id else None
        if actor is None:
            await db.rollback()
            return _report(pair, status="failed", error="brak wykonawcy")
        now = datetime.now(timezone.utc)
        columns = await _columns(db, pair, movable)
        # Kandydaci PRZED rekrutacjami — ta sama kolejność blokad co ruch karty.
        moved = await move_pairs_to_job(
            db,
            source_job_id=pair.source_id,
            target_job_id=pair.target_id,
            candidate_ids=[*movable, *in_both],
        )
        jobs = {
            job.id: job
            for job in (
                await db.scalars(
                    select(Job)
                    .where(Job.id.in_([pair.source_id, pair.target_id]))
                    .order_by(Job.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        }
        source, target = jobs.get(pair.source_id), jobs.get(pair.target_id)
        changed = skip_reason(
            _facts(source), _facts(target), shared=shared, merged=False
        )
        # Karta dodana do kopii po odczycie listy osób zostałaby w zamkniętej
        # rekrutacji — wtedy parę zostawiamy następnemu biegowi.
        arrived = (await _people(db, pair)).everyone() - people.everyone()
        if changed or arrived:
            await db.rollback()
            return _report(pair, status="skipped", skip_reason=SKIP_CHANGED)
        followed = await _follow(db, pair, moved)
        closed = await _close_copy(
            db, source, target, actor_id=actor.id, effects=effects, now=now
        )
        stayed = sorted({*movable, *in_both} - set(moved))
        receipt = {
            "people": len(people.everyone()),
            "moved": len(moved),
            "in_both": len(stayed),
            "in_both_ids": stayed,
            "kpi_hold": len(held),
            "kpi_hold_ids": held,
            "moved_candidate_ids": moved,
            "columns": columns,
            "copy_closed": closed,
            **followed,
        }
        summary = {k: v for k, v in receipt.items() if not k.endswith("_ids")}
        # Pełny paragon przy kopii, w tej samej transakcji co przepięcie:
        # raport biegu powstaje dopiero na końcu, a deploy w trakcie biegu
        # zostawiłby scaloną parę bez listy przeniesionych osób.
        db.add(
            Activity(
                entity_type="job",
                entity_id=pair.source_id,
                action=MERGE_ACTION,
                user_id=actor.id,
                details={"merged_into": pair.target_id, **receipt},
            )
        )
        db.add(
            Activity(
                entity_type="job",
                entity_id=pair.target_id,
                action=MERGE_ACTION,
                user_id=actor.id,
                details={"merged_from": pair.source_id, **summary},
            )
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — jedna para nie zatrzymuje reszty
        await db.rollback()
        logger.error(
            "Twin merge: pair %s -> %s failed: %s",
            pair.source_id,
            pair.target_id,
            safe_db_error(exc),
        )
        return _report(pair, status="failed", error=type(exc).__name__)

    await job_lifecycle.run_post_commit(effects)
    return _report(pair, status="merged", **receipt)


# ── Bieg ─────────────────────────────────────────────────────────────────────

COUNT_KEYS = (
    "people",
    "moved",
    "in_both",
    "kpi_hold",
    "proposals",
    "proposals_added",
    *(follow.key for follow in FOLLOW),
)


def _totals(reports: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    columns: Counter[str] = Counter()
    for report in reports:
        statuses[report["status"]] += 1
        for key in COUNT_KEYS:
            counts[key] += int(report.get(key) or 0)
        for column, value in (report.get("columns") or {}).items():
            columns[column] += int(value)
    return {
        "pairs": len(reports),
        "by_status": dict(statuses),
        **{key: int(counts[key]) for key in COUNT_KEYS},
        "columns": dict(columns),
    }


async def process(
    db: AsyncSession,
    scope: Scope,
    *,
    dry_run: bool,
    actor_user_id: Optional[int],
    actor_label: str,
    reviewed: Optional[frozenset[int]] = None,
) -> dict[str, Any]:
    """Jeden bieg. Zwraca raport (zapis raportu: :func:`finish_run`).

    ``reviewed`` — kopie, które próba pokazała jako gotowe. Wykonanie z trasy
    scala tylko je: para, która doszła po próbie, nie przechodzi bez raportu.
    """
    known = await load_pairs(db)
    # Liczone po WSZYSTKICH parach: zawężenie biegu do jednej kopii nie może
    # ukryć drugiej kopii tej samej rekrutacji.
    targets = Counter(pair.target_id for pair in known)
    wanted = set(scope.job_ids)
    pairs = [pair for pair in known if not wanted or pair.source_id in wanted]
    merged = await load_merged(db, [pair.source_id for pair in pairs])
    await db.rollback()

    reports: list[dict[str, Any]] = []
    for pair in pairs:
        if reviewed is not None and pair.source_id not in reviewed:
            reports.append(
                _report(pair, status="skipped", skip_reason=SKIP_NOT_REVIEWED)
            )
            continue
        reports.append(
            await merge_pair(
                db,
                pair,
                shared=targets[pair.target_id] > 1,
                merged=pair.source_id in merged,
                actor_user_id=actor_user_id,
                dry_run=dry_run,
            )
        )
    return {
        "dry_run": dry_run,
        "scope": scope.as_dict(),
        "scope_key": scope.key(),
        "actor": actor_label,
        "totals": _totals(reports),
        "pairs": reports,
    }


async def finish_run(
    db: AsyncSession, report: dict[str, Any], *, started: datetime
) -> None:
    """Próba → ``DRY_RUN_KEY`` (ostatnia); wykonanie → dopisek do ``LOG_KEY``."""
    report = {
        **report,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    if report["dry_run"]:
        await _write_setting(db, DRY_RUN_KEY, report)
    else:
        log = await _read_setting(db, LOG_KEY) or {}
        runs = list(log.get("runs") or [])
        runs.append(report)
        await _write_setting(db, LOG_KEY, {"runs": runs})
    await db.commit()


_running: dict[str, bool] = {"merge": False}


def is_running() -> bool:
    return _running["merge"]


async def fresh_dry_run_exists(db: AsyncSession, scope: Scope) -> bool:
    """Czy jest próba TEGO zakresu z ostatnich 24 godzin."""
    report = await _read_setting(db, DRY_RUN_KEY)
    if not report or report.get("scope_key") != scope.key():
        return False
    try:
        finished = datetime.fromisoformat(str(report.get("finished_at")))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - finished <= DRY_RUN_MAX_AGE


async def run_merge(
    *,
    scope: Scope,
    dry_run_mode: bool,
    actor_user_id: Optional[int],
    actor_label: str,
) -> None:
    """Bieg w tle (spawn z endpointu) pod blokadą syncu Traffita.

    Import nie rusza kopii „Prowadzonych w NEXUSIE”, ale przepięcie zmienia
    rekrutację wierszom, które import zna po ``external_id`` — nie mieszamy
    tych dwóch biegów.
    """
    from app.core.database import AsyncSessionLocal
    from app.tasks.traffit_sync import traffit_exclusive_lock

    if _running["merge"]:
        return
    _running["merge"] = True
    started = datetime.now(timezone.utc)
    try:
        lock = traffit_exclusive_lock()
        if lock.locked():
            logger.warning("Twin merge skipped: Traffit sync or transfer running")
            return
        async with lock:
            async with AsyncSessionLocal() as db:
                reviewed: Optional[frozenset[int]] = None
                if not dry_run_mode:
                    rehearsal = await _read_setting(db, DRY_RUN_KEY) or {}
                    reviewed = frozenset(
                        int(pair["job_id"])
                        for pair in rehearsal.get("pairs") or []
                        if pair.get("status") == "ready"
                    )
                report = await process(
                    db,
                    scope,
                    dry_run=dry_run_mode,
                    actor_user_id=actor_user_id,
                    actor_label=actor_label,
                    reviewed=reviewed,
                )
                await finish_run(db, report, started=started)
                logger.info(
                    "Twin merge done (dry_run=%s): %s",
                    dry_run_mode,
                    json.dumps(report["totals"]),
                )
    finally:
        _running["merge"] = False


async def read_status(db: AsyncSession) -> dict[str, Any]:
    log = await _read_setting(db, LOG_KEY) or {}
    runs = list(log.get("runs") or [])
    return {
        "running": is_running(),
        "dry_run": await _read_setting(db, DRY_RUN_KEY),
        "runs": len(runs),
        "last_run": runs[-1] if runs else None,
    }


def spawn_running_guard() -> Optional[str]:
    """Powód odmowy startu (409) albo ``None``."""
    from app.services import traffit_transfer

    reason = traffit_transfer.spawn_running_guard()
    if reason:
        return reason
    if is_running():
        return "Scalanie rekrutacji-duplikatów już trwa."
    return None


__all__ = [
    "DRY_RUN_KEY",
    "FOLLOW",
    "LOG_KEY",
    "MERGE_ACTION",
    "JobFacts",
    "Pair",
    "Scope",
    "finish_run",
    "fresh_dry_run_exists",
    "is_running",
    "load_pairs",
    "merge_pair",
    "parse_pairs",
    "process",
    "read_status",
    "run_merge",
    "skip_reason",
    "spawn_running_guard",
]
