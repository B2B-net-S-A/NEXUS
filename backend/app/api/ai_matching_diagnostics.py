"""GET /api/admin/ai-matching/diagnostics — read-only ops view (plan support).

Surfaces the state of every flag-gated subsystem from the AI-matching plan
(telemetry, indexing outbox, versioned score cache, text schema, unified
retrieval) in one call, so the rollout can be operated by *observation* — flip a
flag, watch queue depth / lag / coverage / cache version distribution, decide
promote-or-stop. Strictly read-only; each section is guarded so a not-yet-created
table degrades to an error note instead of a 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, UserRole

router = APIRouter()


# Dźwignie RETRIEVALU — czyli tego, KOGO w ogóle oglądamy.
#
# Do 09.2026 ta lista miała wyłącznie flagi planu AI-matching, a `HYBRID_POOL_ENABLED`
# w niej NIE BYŁO. To jest dziura dokładnie w obietnicy z docstringu modułu
# („flip a flag, watch …, decide promote-or-stop"): flaga hybrydy przełącza pulę
# dla CAŁEGO ruchu AI (rekomendacje, Talent Radar, propozycje, harness), a jedynym
# sposobem sprawdzenia, czy na produkcji faktycznie działa, było zajrzenie do
# zmiennych środowiskowych w Coolify — czyli w miejsce, którego ten endpoint ma
# oszczędzać. Flaga, którą da się przestawić, ale nie da się zaobserwować, nie jest
# dźwignią; jest zgadywanką.
#
# Dwa progi (`HYBRID_BM25_POOL_LIMIT`, `SEARCH_HYBRID_POOL_SIZE`) są tu z tego samego
# powodu, choć nie są bool-ami: ustawione w Coolify na wartość inną niż domyślna
# zmieniają liczbę wyników widoczną dla rekrutera i liczbę dokumentów wysyłanych do
# rerankera, a rozjazd „co miało być ustawione" vs „co obowiązuje" jest z zewnątrz
# niewidoczny.
_RETRIEVAL_FLAGS = [
    "HYBRID_POOL_ENABLED",
    "HYBRID_BM25_POOL_LIMIT",
    "SEARCH_HYBRID_POOL_SIZE",
    "MULTI_QUERY_RETRIEVAL_ENABLED",
    "CV_PASSAGES_ENABLED",
    "RERANKER_ENABLED",
    # 0278: pula SQL-first po must-have — sprawdzana PRZED hybrydą/wektorem
    # w tej samej fasadzie (`retrieval_pool.py`), więc obowiązuje ta sama
    # obietnica: dźwignia, której nie da się zaobserwować, przestawia się
    # na ślepo.
    "STRUCTURED_POOL_ENABLED",
    "STRUCTURED_POOL_LIMIT",
    "STRUCTURED_POOL_MIN_MEMBERS",
    # Wspólny silnik pod `/ai-matches` — ta sama obietnica: dźwignia, której
    # nie da się zaobserwować, przestawia się na ślepo.
    "AI_MATCHES_SHARED_ENGINE",
    "AI_MATCHES_RERANK_TOP_N",
]

_PLAN_FLAGS = [
    "AI_MATCH_TELEMETRY_ENABLED",
    "AI_SCORING_CONTRACT_V2",
    "AI_INDEX_OUTBOX_ENABLED",
    "AI_INDEX_WORKER_ENABLED",
    "AI_TEXT_SCHEMA_V2",
    "AI_UNIFIED_RETRIEVAL_ENABLED",
    "AI_UNIFIED_RETRIEVAL_SURFACES",
]


def _flags() -> dict:
    return {k: getattr(settings, k, None) for k in (_PLAN_FLAGS + _RETRIEVAL_FLAGS)}


async def _outbox(db: AsyncSession) -> dict:
    try:
        from app.services import index_outbox_service as outbox

        return await outbox.diagnostics(db)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


async def _telemetry(db: AsyncSession) -> dict:
    try:
        impressions = await db.scalar(text("SELECT count(*) FROM match_impressions"))
        runs = await db.scalar(
            text("SELECT count(DISTINCT run_id) FROM match_impressions")
        )
        outcomes = await db.scalar(text("SELECT count(*) FROM match_outcomes"))
        return {
            "impressions": int(impressions or 0),
            "distinct_runs": int(runs or 0),
            "outcomes": int(outcomes or 0),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


async def _score_cache(db: AsyncSession) -> dict:
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT scoring_algorithm_version, count(*) "
                    "FROM candidate_job_match_scores GROUP BY scoring_algorithm_version"
                )
            )
        ).all()
        stale = await db.scalar(
            text("SELECT count(*) FROM candidate_job_match_scores WHERE stale = true")
        )
        return {
            "by_version": {str(v): int(c) for v, c in rows},
            "stale": int(stale or 0),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


@router.get("/ai-matching/diagnostics")
async def ai_matching_diagnostics(
    current_user: User = Depends(require_roles(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-call snapshot of the AI-matching plan subsystems (admin, read-only)."""
    from app.services.matching_contracts import current_version_trace

    return {
        "flags": _flags(),
        "version_trace": current_version_trace().as_dict(),
        "indexing_outbox": await _outbox(db),
        "telemetry": await _telemetry(db),
        "score_cache": await _score_cache(db),
    }


# ── PR0 audit — read-only prod schema/state inventory ────────────────────────
#
# Prod has no SSH/DB path, but the backend itself CAN read its own Postgres and
# Qdrant. This endpoint runs the plan's PR0 read-only inventory from inside the
# app so the baseline can be captured over the authed API. STRICTLY read-only —
# no DDL, no DML.


async def _alembic_state(db: AsyncSession) -> dict:
    try:
        rows = (await db.execute(text("SELECT version_num FROM alembic_version"))).all()
        return {"bookmarks": [r[0] for r in rows]}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


async def _schema_inventory(db: AsyncSession) -> dict:
    """Tables/triggers in prod vs tables the current ORM knows about.

    ``unknown_tables`` are the prime suspects for orphaned 0162–0170 remnants
    from the reverted Codex package — the plan's reuse/migrate/ignore list.
    """
    try:
        from app.core.database import Base

        db_tables = {
            r[0]
            for r in (
                await db.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                )
            ).all()
        }
        orm_tables = set(Base.metadata.tables.keys()) | {"alembic_version"}
        triggers = (
            await db.execute(
                text(
                    "SELECT DISTINCT event_object_table, trigger_name "
                    "FROM information_schema.triggers "
                    "WHERE trigger_schema='public' ORDER BY 1, 2"
                )
            )
        ).all()
        return {
            "table_count": len(db_tables),
            "unknown_tables": sorted(db_tables - orm_tables),
            "missing_tables": sorted(orm_tables - db_tables),
            "triggers": [f"{t}.{n}" for t, n in triggers],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


async def _profile_budgets(db: AsyncSession) -> dict:
    """Every stored weight profile with its EFFECTIVE budget (110-bug detector)."""
    try:
        from app.services.scoring_service import WeightProfile

        rows = (
            await db.execute(
                text("SELECT id, name, weights, active FROM scoring_weight_profiles")
            )
        ).all()
        out = []
        for pid, name, weights, active in rows:
            rec = type("R", (), {"id": pid, "name": name, "weights": weights})()
            p = WeightProfile.from_record(rec)
            budget = (
                p.semantic + p.skills + p.salary + p.location + p.availability
            ) + p.champion_fit
            out.append({"id": pid, "name": name, "active": active, "budget": budget})
        return {"profiles": out, "over_budget": [p for p in out if p["budget"] > 100]}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


async def _coverage(db: AsyncSession) -> dict:
    """Eligible DB records vs Qdrant point counts — the plan's first measurement."""
    import asyncio

    result: dict = {}
    try:
        result["db_candidates"] = int(
            await db.scalar(text("SELECT count(*) FROM candidates")) or 0
        )
        result["db_jobs"] = int(await db.scalar(text("SELECT count(*) FROM jobs")) or 0)
    except Exception as exc:  # noqa: BLE001
        result["db_error"] = str(exc)[:200]

    def _qdrant_counts() -> dict:
        from app.services.embedding_service import (
            _collection,
            _get_qdrant_client,
            _jobs_collection,
        )

        client = _get_qdrant_client()
        if client is None:
            return {"qdrant_error": "client unavailable"}
        out: dict = {}
        for label, coll in (
            ("qdrant_candidates", _collection()),
            ("qdrant_jobs", _jobs_collection()),
        ):
            try:
                out[label] = int(client.count(coll, exact=True).count)
            except Exception as exc:  # noqa: BLE001
                out[f"{label}_error"] = str(exc)[:200]
        return out

    try:
        result.update(await asyncio.to_thread(_qdrant_counts))
    except Exception as exc:  # noqa: BLE001
        result["qdrant_error"] = str(exc)[:200]
    return result


@router.get("/ai-matching/audit")
async def ai_matching_audit(
    current_user: User = Depends(require_roles(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Plan PR0: read-only prod inventory (alembic bookmark, schema remnants,
    profile budgets, DB↔Qdrant coverage). Run once, save as the frozen baseline."""
    return {
        "alembic": await _alembic_state(db),
        "schema": await _schema_inventory(db),
        "profile_budgets": await _profile_budgets(db),
        "coverage": await _coverage(db),
    }
