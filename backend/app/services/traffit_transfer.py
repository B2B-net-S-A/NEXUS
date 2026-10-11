"""Przeniesienie otwartych rekrutacji z Traffita do NEXUSA — falami (11.10.2026).

Decyzje Artura 11.10.2026: zespół przechodzi z Traffita falami (klient po
kliencie), a „otwarta” rekrutacja to taka bez daty zamknięcia w Traffit
i z ruchem z Traffita w ostatnich 30 dniach. Pomiar tego dnia: 99,2% osób stoi
już w NEXUSIE na właściwym stanie — rekrutacje są po prostu zamknięte jako
archiwum (0377), więc nikt ich nie widzi jako swojej pracy.

Fala to dwa biegi tej samej reguły:

* **próba** (``dry_run=true``) — dla każdej rekrutacji fali pobiera z Traffita
  listę osób per stan, porównuje z wierszami NEXUSA (:mod:`traffit_transfer_plan`)
  i zapisuje raport: ile osób zgodnych, co zostanie poprawione, kto zejdzie
  z Tablicy, czego nie da się przenieść. Niczego nie zmienia;
* **wykonanie** (``dry_run=false``, wymaga próby z ostatnich 24 h dla tej samej
  fali) — każda rekrutacja we własnej transakcji: poprawki stanów, zdjęcie
  kart osób usuniętych w Traffit, „Prowadzona w NEXUSIE” i ponowne otwarcie.
  Od tej chwili import jej ruchów nie rusza (``skipped_managed``).

Czego ta wersja świadomie NIE robi:

* nie przenosi rekrutacji, która ma bliźniaka założonego w NEXUSIE (ten sam
  klient, niemal ten sam tytuł) — która z dwóch zostaje, to osobna decyzja;
  raport takie rekrutacje wskazuje i pomija;
* nie zakłada kandydatów — osoba z Traffita, której NEXUS nie zna, trafia do
  raportu z numerem osoby;
* nie rusza kart dodanych w NEXUSIE ani par, których ostatni ruch zrobiono
  w NEXUSIE.

Raport i paragon leżą w ``app_settings`` (liczby i ID, bez nazwisk; klucze nie
pasują do publicznego wzorca ``^\\d{4}_``).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.board_stage_badges import board_column_for
from app.services.traffit_transfer_plan import (
    JobPlan,
    StageRow,
    plan_job,
    roster_is_trustworthy,
)

logger = logging.getLogger(__name__)

DRY_RUN_KEY = "traffit_transfer_dry_run"
LOG_KEY = "traffit_transfer_log"
LOCK_KEY = "traffit_transfer"
ACTIVE_DAYS_DEFAULT = 30
#: Rekrutacja-worek (np. „projekty wewnętrzne”, 14,6 tys. zgłoszeń) nie jest
#: rekrutacją do przeniesienia.
MAX_PEOPLE = 3000
#: Bliźniak = rekrutacja założona w NEXUSIE u tego samego klienta o niemal tym
#: samym tytule.
TWIN_MIN_RATIO = 0.8
#: Od tego dnia rekrutacje zakłada się w NEXUSIE (decyzja z 24.09.2026).
NEXUS_START = date(2026, 9, 25)
DRY_RUN_MAX_AGE = timedelta(hours=24)
SAMPLE_IDS = 50

SKIP_LARGE = "too_many_people"
SKIP_TWIN = "twin_in_nexus"
SKIP_ROSTER = "roster_incomplete"
SKIP_TRAFFIT = "traffit_unavailable"

COUNT_KEYS = (
    "people",
    "matched",
    "promote",
    "insert",
    "remove",
    "nexus_on_top",
    "nexus_only",
    "unverified",
    "already_closed",
    "unknown_people",
)


@dataclass(frozen=True)
class Scope:
    """Fala: klient albo wskazane rekrutacje (id NEXUSA)."""

    client_id: Optional[int] = None
    job_ids: tuple[int, ...] = ()
    active_days: int = ACTIVE_DAYS_DEFAULT

    def as_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "job_ids": sorted(self.job_ids),
            "active_days": self.active_days,
        }

    def key(self) -> str:
        raw = json.dumps(self.as_dict(), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class WaveJob:
    job_id: int
    traffit_id: str
    client_id: Optional[int]
    title: str
    recruiter_id: Optional[int]
    delivery_lead_id: Optional[int]
    people: int


@dataclass(frozen=True)
class StageDef:
    stage_def_id: int
    name: Optional[str]
    legacy: str
    category: Optional[str]
    terminal_type: Optional[str]


class RosterUnavailable(RuntimeError):
    """Traffit nie oddał listy stanów rekrutacji."""


def _jobs_sql(scope: Scope) -> str:
    clauses = [
        "j.external_source = 'traffit'",
        "j.external_id IS NOT NULL",
        "j.closed_at IS NULL",
        "NOT j.managed_in_nexus",
        """EXISTS (
            SELECT 1 FROM candidate_stages cs
            WHERE cs.job_id = j.id AND cs.external_source = 'traffit'
              AND cs.moved_at >= now() - make_interval(days => :days)
        )""",
    ]
    if scope.client_id is not None:
        clauses.append("j.client_id = :client_id")
    if scope.job_ids:
        clauses.append("j.id = ANY(CAST(:job_ids AS integer[]))")
    return f"""
        SELECT j.id, j.external_id, j.client_id, j.title, j.recruiter_id,
               j.delivery_lead_id,
               (SELECT count(DISTINCT cs.candidate_id) FROM candidate_stages cs
                WHERE cs.job_id = j.id) AS people
        FROM jobs j
        WHERE {" AND ".join(clauses)}
        ORDER BY j.id
    """


_ROWS_SQL = """
SELECT cs.id, cs.candidate_id,
       CASE WHEN c.external_source = 'traffit' THEN c.external_id END AS emp,
       cs.external_source AS source,
       sd.external_id AS state_ext,
       cs.moved_at,
       CAST(cs.stage AS text) AS stage
FROM candidate_stages cs
JOIN candidates c ON c.id = cs.candidate_id
LEFT JOIN pipeline_stage_defs sd
       ON sd.id = cs.stage_def_id AND sd.external_source = 'traffit'
WHERE cs.job_id = :job_id
"""

_STAGE_DEFS_SQL = """
SELECT id, external_id, name, legacy_enum_value, category, terminal_type
FROM pipeline_stage_defs
WHERE external_source = 'traffit' AND external_id IS NOT NULL
ORDER BY id
"""

_TWINS_SQL = """
SELECT id, client_id, title
FROM jobs
WHERE external_source IS DISTINCT FROM 'traffit'
  AND status <> 'closed'
  AND created_at >= :since
  AND client_id = ANY(CAST(:client_ids AS integer[]))
"""


async def load_wave(db: AsyncSession, scope: Scope) -> list[WaveJob]:
    params: dict[str, Any] = {"days": int(scope.active_days)}
    if scope.client_id is not None:
        params["client_id"] = scope.client_id
    if scope.job_ids:
        params["job_ids"] = list(scope.job_ids)
    rows = await db.execute(text(_jobs_sql(scope)), params)
    return [
        WaveJob(
            int(r.id),
            str(r.external_id),
            r.client_id,
            r.title or "",
            r.recruiter_id,
            r.delivery_lead_id,
            int(r.people or 0),
        )
        for r in rows.all()
    ]


async def load_stage_defs(db: AsyncSession) -> dict[str, StageDef]:
    """Numer stanu Traffita → etap szablonu. Pierwszy wygrywa, jak w imporcie."""
    rows = await db.execute(text(_STAGE_DEFS_SQL))
    out: dict[str, StageDef] = {}
    for r in rows.all():
        out.setdefault(
            str(r.external_id),
            StageDef(
                int(r.id),
                r.name,
                r.legacy_enum_value or "screening",
                r.category,
                r.terminal_type,
            ),
        )
    return out


async def load_rows(db: AsyncSession, job_id: int) -> list[StageRow]:
    rows = await db.execute(text(_ROWS_SQL), {"job_id": job_id})
    return [
        StageRow(
            int(r.id),
            int(r.candidate_id),
            r.emp,
            r.source,
            r.state_ext,
            r.moved_at,
            r.stage,
        )
        for r in rows.all()
    ]


async def load_candidates_by_emp(db: AsyncSession, emps: list[str]) -> dict[str, int]:
    if not emps:
        return {}
    rows = await db.execute(
        text(
            "SELECT id, external_id FROM candidates "
            "WHERE external_source = 'traffit' "
            "AND external_id = ANY(CAST(:emps AS text[]))"
        ),
        {"emps": emps},
    )
    return {str(r.external_id): int(r.id) for r in rows.all()}


def _title_key(title: str) -> str:
    return " ".join(title.lower().split())


def find_twin(title: str, candidates: list[tuple[int, str]]) -> Optional[int]:
    """Rekrutacja NEXUSA o niemal tym samym tytule (ten sam klient) albo ``None``."""
    key = _title_key(title)
    best: tuple[float, int] = (0.0, 0)
    for job_id, other in candidates:
        ratio = SequenceMatcher(None, key, _title_key(other)).ratio()
        if ratio > best[0]:
            best = (ratio, job_id)
    return best[1] if best[0] >= TWIN_MIN_RATIO else None


async def load_twins(db: AsyncSession, jobs: list[WaveJob]) -> dict[int, int]:
    """``job_id`` rekrutacji z Traffita → ``job_id`` bliźniaka w NEXUSIE."""
    client_ids = sorted({j.client_id for j in jobs if j.client_id is not None})
    if not client_ids:
        return {}
    rows = await db.execute(
        text(_TWINS_SQL),
        {
            "since": datetime(
                NEXUS_START.year,
                NEXUS_START.month,
                NEXUS_START.day,
                tzinfo=timezone.utc,
            ),
            "client_ids": client_ids,
        },
    )
    by_client: dict[int, list[tuple[int, str]]] = {}
    for r in rows.all():
        by_client.setdefault(int(r.client_id), []).append((int(r.id), r.title or ""))
    out: dict[int, int] = {}
    for job in jobs:
        if job.client_id is None:
            continue
        twin = find_twin(job.title, by_client.get(int(job.client_id), []))
        if twin is not None:
            out[job.job_id] = twin
    return out


async def fetch_roster(
    traffit: Any, traffit_id: str
) -> tuple[dict[str, str], Optional[int]]:
    """``(osoba → stan, liczba osób w rekrutacji)`` prosto z Traffita.

    Historii ruchów nie da się zawęzić do rekrutacji (filtr jest ignorowany),
    ale lista osób NA STANIE jest dostępna wprost i to ona jest źródłem prawdy.
    """
    resp = await traffit._get_raw(  # noqa: SLF001
        f"/recruitments/{traffit_id}/states", page=1, page_size=100
    )
    if resp.status_code != 200:
        raise RosterUnavailable(f"states HTTP {resp.status_code}")
    states = resp.json()
    if not isinstance(states, list):
        raise RosterUnavailable("states: nie lista")
    people: dict[str, str] = {}
    for state in states:
        state_id = state.get("id") if isinstance(state, dict) else None
        if state_id is None:
            continue
        async for _page, items in traffit.get_pages(
            f"/recruitments/{traffit_id}/states/{state_id}/employees", page_size=100
        ):
            for item in items:
                emp = item.get("id") if isinstance(item, dict) else None
                if emp is not None:
                    people[str(emp)] = str(state_id)
    try:
        total: Optional[int] = await traffit.total_count(
            f"/recruitments/{traffit_id}/employees"
        )
    except RuntimeError:
        total = None
    return people, total


def columns_after(people: dict[str, str], defs: dict[str, StageDef]) -> dict[str, int]:
    """Ile osób stanie w której kolumnie Tablicy (``unknown`` = stan spoza szablonu)."""
    counts: Counter[str] = Counter()
    for state in people.values():
        stage_def = defs.get(state)
        if stage_def is None:
            counts["unknown"] += 1
            continue
        counts[
            board_column_for(
                stage_def.name,
                stage_def.legacy,
                category=stage_def.category,
                terminal_type=stage_def.terminal_type,
            )
        ] += 1
    return dict(counts)


def plan_counts(plan: JobPlan) -> dict[str, int]:
    return {
        "people": plan.people_in_traffit,
        "matched": plan.matched,
        "promote": len(plan.promotes),
        "insert": len(plan.inserts),
        "remove": len(plan.removes),
        "nexus_on_top": plan.nexus_on_top,
        "nexus_only": plan.nexus_only,
        "unverified": plan.unverified,
        "already_closed": plan.already_closed,
        "unknown_people": len(plan.unknown_people),
    }


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


# ── Jedna rekrutacja ─────────────────────────────────────────────────────────

#: Notatka przy karcie osoby zdjętej z rekrutacji w Traffit.
REMOVED_NOTE = "Zdjęty z rekrutacji w Traffit — przeniesienie do NEXUSA."
TRANSFER_REASON = "traffit_transfer"


def _ext_id(kind: str, traffit_id: str, emp: str) -> str:
    """Klucz idempotencji wiersza dopisanego przy przeniesieniu.

    Wiersze z importu niosą numer wpisu historii Traffita; te nie mają
    odpowiednika w historii (stan odczytany z listy osób), więc dostają własny
    prefiks. Ponowny bieg trafia w ten sam wiersz zamiast dokładać kolejny.
    """
    return f"transfer:{kind}:{traffit_id}:{emp}"


def _blocker_codes(job: Any) -> list[str]:
    """Braki z bramki „Otwórz ponownie” — do raportu, przeniesienie ich nie wymusza."""
    from app.services.job_readiness import job_handoff_blocker_items

    try:
        return [
            item["code"] for item in job_handoff_blocker_items(job, include_open=True)
        ]
    except Exception:  # noqa: BLE001 — raport braków nie może wywrócić przeniesienia
        logger.warning("Traffit transfer: readiness check failed for job %s", job.id)
        return ["readiness_unknown"]


async def _apply_plan(
    db: AsyncSession,
    importer: Any,
    job: WaveJob,
    plan: JobPlan,
    defs: dict[str, StageDef],
    fallback: Any,
    now: datetime,
) -> dict[str, Any]:
    """Zapisz poprawki jednej rekrutacji. Bez commitu. Zwraca ID do paragonu."""
    from app.services.recruitment_process_commands import (
        note_external_stage_row,
        promote_external_stage_row,
        sync_external_observed_processes,
    )

    receipt: dict[str, Any] = {"promoted": [], "inserted": [], "withdrawn": []}
    pairs: list[tuple[int, int]] = []

    for promote in plan.promotes:
        if await promote_external_stage_row(
            db, stage_id=promote.row_id, job_id=job.job_id, moved_at=promote.moved_at
        ):
            receipt["promoted"].append(promote.row_id)
            pairs.append((promote.candidate_id, job.job_id))

    for insert in plan.inserts:
        stage_def = defs.get(insert.state_ext)
        if stage_def is None:
            # Stan spoza szablonów NEXUSA — nie zgadujemy etapu.
            continue
        payload = {
            "external_id": _ext_id("state", job.traffit_id, insert.emp),
            "candidate_id": insert.candidate_id,
            "job_id": job.job_id,
            "stage_def_id": stage_def.stage_def_id,
            "stage_legacy_enum": stage_def.legacy,
            "moved_at": now,
            "moved_by": None,
            "contact_source_created_at": None,
        }
        reason_id = fallback.resolve(
            stage_def.legacy, job.job_id, stage_def.stage_def_id
        )
        if stage_def.legacy == "withdrawn" and reason_id is None:
            continue
        await importer._upsert_stage_row(payload, reason_id)  # noqa: SLF001
        receipt["inserted"].append(insert.candidate_id)
        pairs.append((insert.candidate_id, job.job_id))

    for remove in plan.removes:
        reason_id = fallback.resolve("withdrawn", job.job_id, None)
        if reason_id is None:
            # Bez powodu wiersz padłby na ograniczeniu 0068 — karta zostaje.
            continue
        ext_id = _ext_id("removed", job.traffit_id, f"c{remove.candidate_id}")
        payload = {
            "external_id": ext_id,
            "candidate_id": remove.candidate_id,
            "job_id": job.job_id,
            # Etap bez wskazania szablonu: Tablica dobiera „Wycofany” rekrutacji
            # po kodzie etapu, jak dla każdego wiersza bez etapu szablonu.
            "stage_def_id": None,
            "stage_legacy_enum": "withdrawn",
            "moved_at": now,
            "moved_by": None,
            "contact_source_created_at": None,
        }
        await importer._upsert_stage_row(payload, reason_id)  # noqa: SLF001
        await note_external_stage_row(
            db, external_id=ext_id, rejection_note=REMOVED_NOTE
        )
        receipt["withdrawn"].append(remove.candidate_id)
        pairs.append((remove.candidate_id, job.job_id))

    if pairs:
        await sync_external_observed_processes(db, pairs=pairs)
    return receipt


def _job_report(
    job: WaveJob, plan: Optional[JobPlan], *, status: str, **extra: Any
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "job_id": job.job_id,
        "traffit_id": job.traffit_id,
        "client_id": job.client_id,
        "status": status,
        "missing_delivery_lead": job.delivery_lead_id is None,
        "missing_recruiter": job.recruiter_id is None,
    }
    if plan is not None:
        report.update(plan_counts(plan))
        report["unknown_people_ids"] = plan.unknown_people[:SAMPLE_IDS]
    report.update(extra)
    return report


async def process_job(
    db: AsyncSession,
    traffit: Any,
    importer: Any,
    job: WaveJob,
    *,
    defs: dict[str, StageDef],
    twin_job_id: Optional[int],
    fallback: Any,
    actor_user_id: Optional[int],
    dry_run: bool,
) -> dict[str, Any]:
    """Próba albo przeniesienie jednej rekrutacji — własna transakcja."""
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.models.activity import Activity
    from app.models.job import Job, JobStatus
    from app.models.user import User
    from app.services import job_lifecycle
    from app.services.recruitment_allocation import allocation_lock
    from app.services.traffit.importer import safe_db_error

    if job.people > MAX_PEOPLE:
        return _job_report(job, None, status="skipped", skip_reason=SKIP_LARGE)
    if twin_job_id is not None:
        return _job_report(
            job, None, status="skipped", skip_reason=SKIP_TWIN, twin_job_id=twin_job_id
        )

    # Połączenie wraca do puli na czas zapytań do Traffita.
    await db.rollback()
    try:
        people, total = await fetch_roster(traffit, job.traffit_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Traffit transfer: roster for recruitment %s failed: %s",
            job.traffit_id,
            type(exc).__name__,
        )
        return _job_report(job, None, status="skipped", skip_reason=SKIP_TRAFFIT)
    if not roster_is_trustworthy(people, total):
        return _job_report(
            job,
            None,
            status="skipped",
            skip_reason=SKIP_ROSTER,
            roster_people=len(people),
            roster_total=total,
        )

    try:
        if not dry_run:
            await allocation_lock(db)
        rows = await load_rows(db, job.job_id)
        with_card = {r.emp for r in rows if r.emp}
        emp_map = await load_candidates_by_emp(
            db, sorted(emp for emp in people if emp not in with_card)
        )
        plan = plan_job(people, rows, emp_map)
        columns = columns_after(people, defs)
        job_row = (
            await db.execute(select(Job).where(Job.id == job.job_id))
        ).scalar_one()
        blockers = _blocker_codes(job_row)
        if dry_run:
            await db.rollback()
            return _job_report(
                job, plan, status="ready", columns=columns, blockers=blockers
            )

        actor = await db.get(User, actor_user_id) if actor_user_id else None
        if actor is None:
            await db.rollback()
            return _job_report(job, plan, status="failed", error="brak wykonawcy")
        now = datetime.now(timezone.utc)
        # Poprawki etapów PRZED blokadą rekrutacji: synchronizacja procesów
        # blokuje kandydatów, potem rekrutację — ta sama kolejność co ruch
        # karty, więc równoległy ruch nie zakleszczy się z przeniesieniem.
        receipt = await _apply_plan(db, importer, job, plan, defs, fallback, now)
        job_row = (
            await db.execute(
                select(Job)
                .where(Job.id == job.job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if (
            job_row.external_source != "traffit"
            or job_row.managed_in_nexus
            or job_row.status != JobStatus.closed
        ):
            # Ktoś przełączył albo otworzył ją w międzyczasie — poprawki cofamy.
            await db.rollback()
            return _job_report(job, plan, status="skipped", skip_reason="changed")
        effects = job_lifecycle.PostCommit()
        # Te same funkcje co „Otwórz ponownie”: flaga „Prowadzona w NEXUSIE”,
        # status, „Szukamy”, przypisanie prowadzącego. Bramki braków NIE
        # sprawdzamy — rekrutacja jest już w pracy, braki niesie raport.
        await job_lifecycle.publish_core(
            db, job_row, actor, effects, reason=TRANSFER_REASON
        )
        await job_lifecycle.reopen_keep_team_core(db, job_row, actor, effects)
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.job_id,
                action="traffit_transfer",
                user_id=actor.id,
                details={**plan_counts(plan), "traffit_id": job.traffit_id},
            )
        )
        await db.commit()
    except HTTPException as exc:
        await db.rollback()
        detail = exc.detail
        if isinstance(detail, dict):
            detail = detail.get("code") or detail.get("message") or "odmowa"
        return _job_report(job, None, status="failed", error=str(detail)[:200])
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error(
            "Traffit transfer: job %s failed: %s", job.job_id, safe_db_error(exc)
        )
        return _job_report(job, None, status="failed", error=type(exc).__name__)

    await job_lifecycle.run_post_commit(effects)
    return _job_report(
        job, plan, status="transferred", columns=columns, blockers=blockers, **receipt
    )


# ── Bieg fali ────────────────────────────────────────────────────────────────


def _totals(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    columns: Counter[str] = Counter()
    for job in jobs:
        statuses[job["status"]] += 1
        for key in COUNT_KEYS:
            counts[key] += int(job.get(key) or 0)
        for column, value in (job.get("columns") or {}).items():
            columns[column] += int(value)
    return {
        "jobs": len(jobs),
        "by_status": dict(statuses),
        **{key: int(counts[key]) for key in COUNT_KEYS},
        "columns": dict(columns),
    }


async def process(
    db: AsyncSession,
    traffit: Any,
    scope: Scope,
    *,
    dry_run: bool,
    actor_user_id: Optional[int],
    actor_label: str,
) -> dict[str, Any]:
    """Jeden bieg fali. Zwraca raport (zapis raportu: :func:`finish_run`)."""
    from app.services.traffit.importer import TraffitImporter

    jobs = await load_wave(db, scope)
    defs = await load_stage_defs(db)
    twins = await load_twins(db, jobs)
    importer = TraffitImporter(traffit, db, dry_run=dry_run)
    # Próba nie dosiewa powodu `legacy_unknown` (importer w dry_run nie pisze).
    fallback = await importer._build_withdrawn_fallback_reason_map()  # noqa: SLF001
    await db.commit()

    reports: list[dict[str, Any]] = []
    for job in jobs:
        reports.append(
            await process_job(
                db,
                traffit,
                importer,
                job,
                defs=defs,
                twin_job_id=twins.get(job.job_id),
                fallback=fallback,
                actor_user_id=actor_user_id,
                dry_run=dry_run,
            )
        )

    if not dry_run:
        from app.services.job_delivery_lead_fill import fill_missing_job_delivery_leads

        client_ids = {j.client_id for j in jobs if j.client_id is not None}
        try:
            await fill_missing_job_delivery_leads(db, client_ids)
            await db.commit()
        except Exception:  # noqa: BLE001 — DL-a dopełni też start aplikacji
            await db.rollback()
            logger.warning("Traffit transfer: delivery lead fill failed")

    return {
        "dry_run": dry_run,
        "scope": scope.as_dict(),
        "scope_key": scope.key(),
        "actor": actor_label,
        "totals": _totals(reports),
        "jobs": reports,
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


# ── Przebieg w tle ───────────────────────────────────────────────────────────

_running: dict[str, bool] = {"transfer": False}


def is_running() -> bool:
    return _running["transfer"]


async def fresh_dry_run_exists(db: AsyncSession, scope: Scope) -> bool:
    """Czy jest próba TEJ fali z ostatnich 24 godzin."""
    report = await _read_setting(db, DRY_RUN_KEY)
    if not report or report.get("scope_key") != scope.key():
        return False
    try:
        finished = datetime.fromisoformat(str(report.get("finished_at")))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - finished <= DRY_RUN_MAX_AGE


async def run_transfer(
    *,
    scope: Scope,
    dry_run_mode: bool,
    actor_user_id: Optional[int],
    actor_label: str,
) -> None:
    """Bieg w tle (spawn z endpointu) pod blokadą syncu Traffita."""
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.client import TraffitClient, TraffitConfig
    from app.tasks.traffit_sync import traffit_exclusive_lock

    if _running["transfer"]:
        return
    _running["transfer"] = True
    started = datetime.now(timezone.utc)
    try:
        lock = traffit_exclusive_lock()
        if lock.locked():
            logger.warning("Traffit transfer skipped: sync running")
            return
        async with lock:
            config = TraffitConfig.from_env()
            async with TraffitClient(config) as traffit:
                async with AsyncSessionLocal() as db:
                    report = await process(
                        db,
                        traffit,
                        scope,
                        dry_run=dry_run_mode,
                        actor_user_id=actor_user_id,
                        actor_label=actor_label,
                    )
                    await finish_run(db, report, started=started)
                    logger.info(
                        "Traffit transfer done (dry_run=%s): %s",
                        dry_run_mode,
                        json.dumps(report["totals"]),
                    )
    finally:
        _running["transfer"] = False


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
    from app.services import traffit_file_dates_repair, traffit_notes_repair
    from app.tasks.traffit_sync import sync_is_running

    if sync_is_running():
        return "Trwa synchronizacja z Traffitem — spróbuj po jej zakończeniu."
    if traffit_notes_repair.is_running() or traffit_file_dates_repair.is_running():
        return "Trwa naprawa danych z Traffita — spróbuj po jej zakończeniu."
    if is_running():
        return "Przeniesienie rekrutacji z Traffita już trwa."
    return None


__all__ = [
    "ACTIVE_DAYS_DEFAULT",
    "DRY_RUN_KEY",
    "LOG_KEY",
    "Scope",
    "WaveJob",
    "find_twin",
    "finish_run",
    "fresh_dry_run_exists",
    "process",
    "process_job",
    "read_status",
    "run_transfer",
    "spawn_running_guard",
]
