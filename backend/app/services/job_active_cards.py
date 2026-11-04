"""Osoby w toku w rekrutacji — ostrzeżenie przed jej zamknięciem (13.10.2026).

``POST /api/jobs/{id}/close`` zmienia status rekrutacji i nie rusza kart.
12.10.2026 Delivery Lead zamknął duplikat requestu z pięcioma kartami, na
których rekruterka pracowała kwadrans wcześniej: karty zostały w zamkniętej
rekrutacji, a okno zamykania nic o nich nie mówiło.

„W toku” = bieżąca karta osoby stoi w jednej z kolumn Tablicy poza
„Zamkniętymi” i „Zatrudnionymi” — ta sama reguła kolumny co Tablica
(``board_stage_badges.board_column_for``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.services.board_stage_badges import BOARD_COLUMN_ORDER, board_column_for
from app.services.pipeline_latest import latest_stage_ids

WARNING_CODE = "active_cards_warning"
_DONE_COLUMNS = frozenset({"closed", "hired"})


def _people(total: int) -> str:
    """„jest 1 osoba”, „są 3 osoby”, „jest 5 osób”."""
    if total == 1:
        return "jest 1 osoba"
    if total % 10 in (2, 3, 4) and total % 100 not in (12, 13, 14):
        return f"są {total} osoby"
    return f"jest {total} osób"


@dataclass(frozen=True)
class ActiveCards:
    total: int
    #: Kolumna Tablicy → liczba osób, w kolejności kolumn.
    columns: dict[str, int]
    last_moved_at: Optional[datetime]

    def message(self) -> str:
        last = ""
        if self.last_moved_at is not None:
            day = self.last_moved_at.astimezone(ZoneInfo(DEFAULT_TZ))
            last = f" (ostatni ruch karty {day.strftime('%d.%m.%Y')})"
        return (
            f"W tej rekrutacji {_people(self.total)} w toku{last}. "
            "Zamknięcie nie zamyka kart — zostaną w zamkniętej rekrutacji."
        )

    def warning_detail(self) -> dict[str, Any]:
        return {
            "code": WARNING_CODE,
            "message": self.message(),
            "active_cards": self.total,
            "columns": self.columns,
            "last_moved_at": (
                self.last_moved_at.isoformat() if self.last_moved_at else None
            ),
        }


def summarize(rows: list[tuple[str, datetime]]) -> ActiveCards:
    """``(kolumna, moved_at)`` bieżących kart → podsumowanie osób w toku."""
    counts: dict[str, int] = {}
    last: Optional[datetime] = None
    for column, moved_at in rows:
        if column in _DONE_COLUMNS:
            continue
        counts[column] = counts.get(column, 0) + 1
        if last is None or moved_at > last:
            last = moved_at
    ordered = {c: counts[c] for c in BOARD_COLUMN_ORDER if c in counts}
    return ActiveCards(total=sum(ordered.values()), columns=ordered, last_moved_at=last)


async def load_active_cards(db: AsyncSession, job_id: int) -> ActiveCards:
    latest = latest_stage_ids(job_ids=[job_id])
    rows = (
        await db.execute(
            select(
                CandidateStage.stage,
                CandidateStage.moved_at,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(CandidateStage.id.in_(select(latest.c.latest_id)))
        )
    ).all()
    return summarize(
        [
            (
                board_column_for(
                    name,
                    getattr(stage, "value", stage),
                    category=getattr(category, "value", category),
                    terminal_type=getattr(terminal_type, "value", terminal_type),
                ),
                moved_at,
            )
            for stage, moved_at, name, category, terminal_type in rows
        ]
    )
