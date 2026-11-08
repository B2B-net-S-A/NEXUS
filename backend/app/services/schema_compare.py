"""Porównanie ORM z żywą bazą przez alembicowe ``compare_metadata``.

Etap 1 pozycji B3 z audytu 07.11.2026: lustro DDL w ``entrypoint.sh`` można zamrozić
dopiero, gdy wiadomo, czym schemat produkcji różni się od modeli. Wynik jest
informacją w ``/api/health/deep`` i nie zmienia jej statusu.

Pełne odbicie schematu trwa kilkanaście sekund, a sonda jest bez logowania, więc:
osobny wątek i własne połączenie (pętla zdarzeń obsługuje w tym czasie żądania),
najwyżej jeden bieg naraz, wynik trzymany ``_TTL_SECONDS``. Pierwsze pytanie po
starcie dostaje ``pending``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import Base
from app.core.tasks import spawn

logger = logging.getLogger(__name__)

_TTL_SECONDS = 3600
_FAILED_TTL_SECONDS = 300
_SAMPLE_LIMIT = 50
# Tabele bez modelu, które zostają w bazie (decyzja z 08.11.2026 po przeglądzie
# 70 tabel: stare kopie, `dr_*`, `ai_*`, `signature_links`). Bez nich raport nie
# tonie w `remove_table`. Skasowanie którejś = usunięcie jej stąd.
_ABANDONED_TABLES = frozenset(
    {
        "_alembic_backup_pre_heal",
        "ai_budget_reservations",
        "ai_call_ledger",
        "ai_eval_cases",
        "ai_eval_labels",
        "ai_eval_outputs",
        "ai_eval_runs",
        "ai_eval_sets",
        "ai_provider_compliance",
        "ai_rollout_events",
        "ai_rollout_observations",
        "ai_rollout_reports",
        "ai_rollout_state",
        "ai_routing_activation_log",
        "ai_routing_state",
        "client_norm_bak_calendar",
        "client_norm_bak_clients",
        "client_norm_bak_contacts",
        "client_norm_bak_drdl",
        "client_norm_bak_drpd",
        "client_norm_bak_jobs",
        "client_norm_bak_knowledge",
        "dr_about_calendar",
        "dr_about_career_paths",
        "dr_about_clients_partners",
        "dr_about_contacts",
        "dr_about_faq",
        "dr_about_feedback",
        "dr_about_glossary",
        "dr_about_links",
        "dr_about_org_chart",
        "dr_about_positions",
        "dr_about_procedures",
        "dr_about_templates",
        "dr_about_training",
        "dr_about_values",
        "dr_alerts",
        "dr_api_key_audit_log",
        "dr_api_keys",
        "dr_applied_migrations",
        "dr_competence_categories",
        "dr_consultant_group_assignments",
        "dr_consultant_rate_history",
        "dr_consultants",
        "dr_data_audit_log",
        "dr_delivery_lead_client_assignments",
        "dr_group_monthly_costs",
        "dr_monthly_mrr_data",
        "dr_mrr_import_history",
        "dr_project_cost_groups",
        "dr_project_monthly_costs",
        "dr_project_other_cost_items",
        "dr_przetargi_mrr",
        "dr_przetargi_mrr_backup",
        "dr_system_config",
        "dr_tac_linkedin_farming",
        "nordea_merge_bak_calendar",
        "nordea_merge_bak_clients",
        "nordea_merge_bak_contacts",
        "nordea_merge_bak_dl",
        "nordea_merge_bak_drdl",
        "nordea_merge_bak_drplace",
        "nordea_merge_bak_jobs",
        "nordea_merge_bak_knowledge",
        "nordea_merge_bak_notif",
        "nordea_merge_bak_reqdocs",
        "nordea_merge_bak_tac",
        "signature_links",
        "users_backup_2026_05_18",
        "users_cleanup_backup_2026_05_18",
    }
)
# Tabele spoza modeli z założenia: bookmark alembica i porzucone wyżej.
_IGNORED_TABLES = frozenset({"alembic_version"}) | _ABANDONED_TABLES
# Brak po stronie bazy psuje zapytania ORM; reszta to dług do przeglądu.
BREAKING_KINDS = frozenset({"add_table", "add_column"})

_result: dict[str, Any] | None = None
_expires_at = 0.0
_running: asyncio.Task[None] | None = None


def _include_object(_obj: Any, name: str | None, type_: str, *_rest: Any) -> bool:
    return not (type_ == "table" and name in _IGNORED_TABLES)


def _describe(diff: Any) -> dict[str, str]:
    """Jeden wiersz raportu: same identyfikatory schematu, bez danych."""
    if isinstance(diff, list):  # modify_* przychodzi jako lista krotek
        diff = diff[0]
    kind = str(diff[0])
    if kind in {"add_table", "remove_table"}:
        return {"kind": kind, "object": diff[1].name}
    if kind in {"add_column", "remove_column"}:
        return {"kind": kind, "object": f"{diff[2]}.{diff[3].name}"}
    if kind.startswith("modify_"):
        return {"kind": kind, "object": f"{diff[2]}.{diff[3]}"}
    if kind in {"add_index", "remove_index"}:
        return {"kind": kind, "object": f"{diff[1].table.name}.{diff[1].name}"}
    if kind in {"add_constraint", "remove_constraint", "add_fk", "remove_fk"}:
        constraint = diff[1]
        # Klucz obcy i unikat z modelu bywają bez nazwy: wtedy po kolumnach.
        name = constraint.name or ",".join(c.name for c in constraint.columns)
        return {"kind": kind, "object": f"{constraint.table.name}.{name}"}
    return {"kind": kind, "object": ""}


def summarize(diffs: list[Any]) -> dict[str, Any]:
    rows = sorted(
        (_describe(diff) for diff in diffs), key=lambda r: (r["kind"], r["object"])
    )
    counts = Counter(row["kind"] for row in rows)
    breaking = [row for row in rows if row["kind"] in BREAKING_KINDS]
    return {
        "status": "breaking" if breaking else ("drift" if rows else "clean"),
        "total": len(rows),
        "counts": dict(sorted(counts.items())),
        # Najpierw to, co psuje zapytania: lista bywa dłuższa niż próbka.
        "sample": (breaking + [r for r in rows if r not in breaking])[:_SAMPLE_LIMIT],
    }


def _compare_sync() -> dict[str, Any]:
    started = time.monotonic()
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "compare_type": True,
                    "include_object": _include_object,
                },
            )
            report = summarize(compare_metadata(context, Base.metadata))
    finally:
        engine.dispose()
    report["seconds"] = round(time.monotonic() - started, 1)
    return report


async def _refresh() -> None:
    global _result, _expires_at
    try:
        _result = await asyncio.to_thread(_compare_sync)
        _expires_at = time.monotonic() + _TTL_SECONDS
    except Exception as exc:  # noqa: BLE001 — sonda nie może wywrócić health/deep
        logger.warning("schema_compare: %r", exc)
        _result = {"status": "unavailable", "error": type(exc).__name__}
        _expires_at = time.monotonic() + _FAILED_TTL_SECONDS


def schema_compare_report() -> dict[str, Any]:
    """Ostatni wynik; przeterminowany odświeża się w tle, ``pending`` przed pierwszym."""
    global _running
    if time.monotonic() >= _expires_at and (_running is None or _running.done()):
        _running = spawn(_refresh(), "schema_compare")
    return _result if _result is not None else {"status": "pending"}
