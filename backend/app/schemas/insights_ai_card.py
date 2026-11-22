"""Kafelek „CV do klienta z karty AI” w Insights → Zespół (22.11.2026)."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AiCardCvWeek(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: date
    week_end: date
    cv_sent: int
    from_ai_card: int
    share_pct: Optional[float] = None
    in_progress: bool = False


class AiCardCvShare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_from: date
    window_to: date
    target_pct: int
    # Od najstarszego do bieżącego (ostatni ma `in_progress`).
    weeks: list[AiCardCvWeek]
