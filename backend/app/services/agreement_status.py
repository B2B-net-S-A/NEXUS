"""Stan umowy B2B z Generatora dla kart na Tablicy (04.10.2026).

Rejestr Generatora jest jedynym źródłem stanu umowy; karta tylko go pokazuje
— w KAŻDEJ kolumnie, bo co trzecia umowa powstaje jeszcze w „Rozmowie
u klienta”. Jedno zapytanie na tablicę. Wiersze z Excela działu pomijamy
(nie mają pary kandydat × rekrutacja z NEXUSA). Na parę bierzemy żywą umowę
(„W trakcie”, „Aktywna”) przed anulowaną albo zakończoną, potem najnowszą.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import case, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.services.board_stage_badges import board_column_for

LIVE_STATUSES = ("in_progress", "active")


def _iso(value: Any) -> Any:
    return value.isoformat() if value is not None else None


def agreement_badge(row: Any) -> dict[str, Any]:
    """Kształt pola ``agreement`` karty (też dla pulpitu)."""
    return {
        "id": row.id,
        "number": row.contract_number,
        "contract_status": row.contract_status,
        "signature_status": row.signature_status,
        "created_at": _iso(row.created_at),
        "signed_at": _iso(row.signed_at),
        "signature_requested_at": _iso(row.signature_requested_at),
        "contract_id": row.contract_id,
    }


async def agreement_status_for_pairs(
    db: AsyncSession, *, job_id: int, candidate_ids: Iterable[int]
) -> dict[int, dict[str, Any]]:
    """``{candidate_id: agreement}`` dla jednej rekrutacji."""
    ids = sorted({int(c) for c in candidate_ids})
    if not ids:
        return {}
    live_first = case(
        (B2BGeneratedContract.contract_status.in_(LIVE_STATUSES), 0), else_=1
    )
    rows = await db.execute(
        select(
            B2BGeneratedContract.id,
            B2BGeneratedContract.candidate_id,
            B2BGeneratedContract.contract_number,
            B2BGeneratedContract.contract_status,
            B2BGeneratedContract.signature_status,
            B2BGeneratedContract.created_at,
            B2BGeneratedContract.signed_at,
            B2BGeneratedContract.signature_requested_at,
            B2BGeneratedContract.contract_id,
        )
        .where(
            B2BGeneratedContract.job_id == job_id,
            B2BGeneratedContract.candidate_id.in_(ids),
            B2BGeneratedContract.source != "excel",
        )
        .order_by(
            B2BGeneratedContract.candidate_id,
            live_first,
            B2BGeneratedContract.created_at.desc(),
            B2BGeneratedContract.id.desc(),
        )
    )
    out: dict[int, dict[str, Any]] = {}
    for row in rows.all():
        out.setdefault(row.candidate_id, agreement_badge(row))
    return out


async def pair_columns(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], tuple[str, Optional[datetime]]]:
    """``{(kandydat, rekrutacja): (kolumna Tablicy, od kiedy)}`` — jedno zapytanie.

    Najnowszy wiersz etapu pary przez ``board_column_for`` (nazwa, kod,
    kategoria i typ zamknięcia etapu). Rejestr Generatora i grupa „Umowy” na
    pulpicie pokazują, gdzie jest osoba, której dotyczy umowa.
    """
    wanted = sorted({(int(c), int(j)) for c, j in pairs})
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.stage,
            CandidateStage.moved_at,
            PipelineStageDef.name,
            PipelineStageDef.category,
            PipelineStageDef.terminal_type,
        )
        .outerjoin(PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id)
        .where(tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(wanted))
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
    )
    out: dict[tuple[int, int], tuple[str, Optional[datetime]]] = {}
    for cand, job_id, stage, moved_at, name, category, terminal in rows.all():
        column = board_column_for(
            name,
            getattr(stage, "value", stage),
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal, "value", terminal),
        )
        out[(cand, job_id)] = (column, moved_at)
    return out
