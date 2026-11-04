"""Migawka etapów pary przed korekcyjnym usunięciem z rekrutacji.

Jedno miejsce kształtu ``candidate_stage_removals.stages_snapshot`` — czytają
go ręczne „Usuń z rekrutacji” (``DELETE /api/candidates/{id}/recruitments/
{job_id}``) i jednorazowe przeniesienie kart z portali do „Do przejrzenia”
(``services/job_board_cards_to_proposals.py``). Dwie kopie rozjechałyby się
przy pierwszej nowej kolumnie etapu, a archiwum jest jedynym dowodem przebiegu.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.models.recruitment_pipeline import CandidateStage


def ordered_stage_rows(stage_rows: Iterable[CandidateStage]) -> list[CandidateStage]:
    """Etapy pary w kolejności przebiegu (chwila ruchu, potem id)."""
    return sorted(stage_rows, key=lambda s: (s.moved_at or s.created_at, s.id))


def stage_removal_snapshot(ordered: Iterable[CandidateStage]) -> list[dict[str, Any]]:
    """Pełne wiersze ``candidate_stages`` w chwili usunięcia (lista obiektów)."""
    return [
        {
            "id": s.id,
            "stage": s.stage.value,
            "stage_def_id": s.stage_def_id,
            "moved_at": s.moved_at.isoformat() if s.moved_at else None,
            "moved_by": s.moved_by,
            "notes": s.notes,
            "rejection_reason_id": s.rejection_reason_id,
            "client_rate_value": (
                float(s.client_rate_value) if s.client_rate_value is not None else None
            ),
            "expected_rate_value": (
                float(s.expected_rate_value)
                if s.expected_rate_value is not None
                else None
            ),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in ordered
    ]
