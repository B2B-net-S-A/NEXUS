"""Read-only Traffit status shared by the authorized API and Admin Ops.

Od 14.10.2026 Traffit jest wyłączony na stałe (``traffit_retired.py``): status
pokazuje historię ostatnich biegów z bazy i mówi wprost, od kiedy import stoi.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.traffit_retired import TRAFFIT_RETIRED_MESSAGE, TRAFFIT_RETIRED_ON

# Świeżość wiersza `traffit_sync_state` — próg po typie fazy, nie po nazwie
# (INT-09). Importer usunięty 08.11.2026, a tabela jest też dziennikiem biegów
# `notes_insights` i `weekly_eval`, więc werdykt zostaje przy odczycie statusu:
# - fazy budżetowane i stronicowane (z kursorem wznawiania) — 72 h;
# - znacznik `__full__` i `weekly_eval` (rytm tygodniowy) — 8 dni;
# - fazy DORADCZE nie blokowały watermarku, więc werdykt `advisory`, nie
#   `stale`, i nie liczą się do `phases_stale`.
FULL_MARKER = "__full__"
WEEKLY_EVAL_STATE_PHASE = "weekly_eval"
ADVISORY_PHASES = frozenset({"candidates_enrich_names", "candidates_cv_fields"})

_DAILY_PHASE_STALE_HOURS = 36
_CURSORED_PHASE_STALE_HOURS = 72
_FULL_CADENCE_STALE_HOURS = 8 * 24

_CURSORED_PHASES = frozenset(
    {
        "candidate_files",
        "candidates_cv",
        "candidates_enrich_names",
        "candidates",
        "candidate_activities",
        "pipelines",
    }
)
_FULL_CADENCE_PHASES = frozenset({FULL_MARKER, WEEKLY_EVAL_STATE_PHASE})

FRESHNESS_FRESH = "fresh"
FRESHNESS_STALE = "stale"
FRESHNESS_NEVER = "never"
FRESHNESS_ADVISORY = "advisory"


def phase_stale_after(phase: str) -> timedelta:
    """Próg świeżości dla fazy (albo znacznika) — po typie, nie po nazwie."""
    if phase in _FULL_CADENCE_PHASES:
        return timedelta(hours=_FULL_CADENCE_STALE_HOURS)
    if phase in _CURSORED_PHASES:
        return timedelta(hours=_CURSORED_PHASE_STALE_HOURS)
    return timedelta(hours=_DAILY_PHASE_STALE_HOURS)


def phase_freshness(
    phase: str, *, finished_at: Optional[datetime], now: datetime
) -> str:
    """``fresh`` | ``stale`` | ``never`` | ``advisory`` dla jednego wiersza stanu.

    Czysta funkcja — o świeżości, nie o wyniku: `last_status` jedzie obok
    w tej samej odpowiedzi i mówi o błędach, ten werdykt mówi o CZASIE.
    `never` = wiersz bez końca biegu (faza nigdy nie doszła do końca).
    """
    if finished_at is None:
        return FRESHNESS_NEVER
    overdue = (now - finished_at) > phase_stale_after(phase)
    if phase in ADVISORY_PHASES:
        return FRESHNESS_ADVISORY if overdue else FRESHNESS_FRESH
    return FRESHNESS_STALE if overdue else FRESHNESS_FRESH


def annotate_freshness(states: list[dict[str, Any]], now: datetime) -> list[str]:
    """Dopisz `freshness` i `stale_after_hours` do wierszy `/sync/status`;
    zwróć posortowane nazwy faz z werdyktem `stale` (zbiorcze `phases_stale`).

    Wiersze bez końca biegu (`never`) NIE trafiają do `phases_stale`: faza,
    która nigdy nie pobiegła, to stan świeżo włączonej instalacji, nie regres —
    a lista ma być tym, na co operator reaguje.
    """
    stale: list[str] = []
    for state in states:
        phase = str(state.get("phase") or "")
        raw = state.get("last_run_finished_at")
        finished_at = datetime.fromisoformat(raw) if isinstance(raw, str) else raw
        if finished_at is not None and finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=timezone.utc)
        verdict = phase_freshness(phase, finished_at=finished_at, now=now)
        state["freshness"] = verdict
        state["stale_after_hours"] = int(
            phase_stale_after(phase).total_seconds() // 3600
        )
        if verdict == FRESHNESS_STALE:
            stale.append(phase)
    return sorted(stale)


async def read_traffit_status(db: AsyncSession) -> dict[str, Any]:
    """Current watermark + last-run stats for every phase + scheduler markers."""
    rows = await db.execute(
        text(
            "SELECT phase, last_synced_at, last_run_started_at, "
            "last_run_finished_at, last_status, stats, cursor_at, cursor_payload "
            "FROM traffit_sync_state ORDER BY phase"
        )
    )
    states = [
        {
            "phase": r.phase,
            "last_synced_at": r.last_synced_at.isoformat()
            if r.last_synced_at
            else None,
            "last_run_started_at": r.last_run_started_at.isoformat()
            if r.last_run_started_at
            else None,
            "last_run_finished_at": r.last_run_finished_at.isoformat()
            if r.last_run_finished_at
            else None,
            "last_status": r.last_status,
            "stats": r.stats,
            # Resume cursor (Stage 3) — non-null while a phase (e.g.
            # candidate_activities) is mid-catch-up; watch cursor.page advance
            # across runs to see resumable pagination working, NULL after a
            # full pass.
            "cursor_at": r.cursor_at.isoformat() if r.cursor_at else None,
            "cursor": r.cursor_payload,
        }
        for r in rows
    ]
    # Roll the parked rows up to the top level. Quarantine only works if
    # somebody sees it: a row that stops blocking the watermark but stays buried
    # three levels deep in a per-phase stats blob has simply been forgotten with
    # extra steps. This is the list an operator has to act on.
    quarantined: list[dict[str, Any]] = []
    for state in states:
        stats = state["stats"] or {}
        if not isinstance(stats, dict):
            continue
        attempts = stats.get("quarantine") or {}
        for ref in stats.get("quarantined") or []:
            quarantined.append(
                {
                    "phase": state["phase"],
                    "ref": ref,
                    "attempts": attempts.get(ref),
                    "last_seen": state["last_run_finished_at"],
                }
            )

    # Kolizje e-maila (05.10.2026): doradcze — nie wstrzymują `__daily__`
    # i nie psują `checks.traffit`, więc jedynym miejscem, gdzie operator je
    # widzi, jest ta lista. Same identyfikatory (numer Traffita → kandydat
    # NEXUSA), nigdy mail: status czyta konto serwisowe i workflow z publicznym
    # logiem. Rozstrzyga człowiek: „Scal z…” w NEXUSIE albo poprawka w Traffit.
    email_collisions: list[dict[str, Any]] = []
    email_collision_count = 0
    for state in states:
        stats = state["stats"] or {}
        if not isinstance(stats, dict):
            continue
        try:
            email_collision_count += int(stats.get("email_collision_count") or 0)
        except (TypeError, ValueError):
            pass
        for pair in stats.get("email_collisions") or []:
            if isinstance(pair, dict):
                email_collisions.append(
                    {
                        "phase": state["phase"],
                        "ext_id": pair.get("ext_id"),
                        "candidate_id": pair.get("candidate_id"),
                        "last_seen": state["last_run_finished_at"],
                    }
                )

    # Werdykt świeżości PER FAZA (INT-09). `checks.traffit` w `/api/health`
    # czyta wyłącznie `__daily__` — mówi, że nocna delta się kończy, nie że
    # każda faza doszła do ogona. `phases_stale` to lista, na którą operator
    # reaguje; fazy doradcze i `never` (świeżo włączona instalacja) są w
    # `freshness` wiersza, ale nie na tej liście.
    phases_stale = annotate_freshness(states, datetime.now(timezone.utc))

    # Adopcja przełącznika (0325): ile ofert import etapów omija. Liczba, nie lista.
    managed_in_nexus_jobs = int(
        await db.scalar(text("SELECT count(*) FROM jobs WHERE managed_in_nexus")) or 0
    )

    return {
        # Wyłączony na stałe — nie czytamy flagi, która mogłaby powiedzieć „tak”.
        "enabled": False,
        "retired_on": TRAFFIT_RETIRED_ON.isoformat(),
        "retired_message": TRAFFIT_RETIRED_MESSAGE,
        # Importera nie ma w kodzie od 08.11.2026; pole zostaje dla kafelka.
        "running": False,
        "max_row_attempts": settings.TRAFFIT_MAX_ROW_ATTEMPTS,
        "managed_in_nexus_jobs": managed_in_nexus_jobs,
        "quarantined": quarantined,
        "email_collision_count": email_collision_count,
        "email_collisions": email_collisions,
        "phases_stale": phases_stale,
        "states": states,
    }
