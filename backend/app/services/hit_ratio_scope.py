"""Która zamknięta rekrutacja wchodzi do hit ratio (21.10.2026).

Jedno miejsce dla każdego wzoru hit ratio: Liga i cel DL
(`competitions.dl_portfolio_counts`), Insights → Firma i jej rok do roku,
raport i ranking klientów, portfele DL. Do 21.10.2026 każdy z nich liczył
w mianowniku każdą zamkniętą rekrutację, więc zamknięcie duplikatu albo
projektu anulowanego przez klienta obniżało wynik jak przegrana.

Grupy powodów: `metric_definitions.HIT_RATIO_*_CLOSE_REASONS`.
"""

from __future__ import annotations

from typing import Literal, Optional

from sqlalchemy import ColumnElement, or_

from app.models.job import Job, JobCloseReason
from app.services.metric_definitions import (
    HIT_RATIO_LOST_CLOSE_REASONS,
    HIT_RATIO_NEUTRAL_CLOSE_REASONS,
    HIT_RATIO_WON_CLOSE_REASONS,
)

CloseReasonGroup = Literal["won", "lost", "neutral", "unreviewed"]

NEUTRAL_CLOSE_REASONS: frozenset[JobCloseReason] = frozenset(
    JobCloseReason(v) for v in HIT_RATIO_NEUTRAL_CLOSE_REASONS
)


def counts_in_hit_ratio() -> ColumnElement[bool]:
    """Warunek na `Job`: rekrutacja liczy się do mianownika hit ratio."""
    return or_(
        Job.close_reason.is_(None),
        Job.close_reason.notin_(sorted(NEUTRAL_CLOSE_REASONS, key=lambda r: r.value)),
    )


def counts_in_hit_ratio_sql(alias: str = "j") -> str:
    """Ten sam warunek dla surowego SQL (`alias` = alias tabeli `jobs`).

    Wartości to stałe z kodu, nie dane użytkownika — wklejenie ich w tekst
    zapytania jest bezpieczne, a zapytania z parametrami tablicowymi nie
    trzeba przerabiać w każdym miejscu.
    """
    values = ", ".join(f"'{v}'" for v in sorted(HIT_RATIO_NEUTRAL_CLOSE_REASONS))
    return (
        f"({alias}.close_reason IS NULL "
        f"OR {alias}.close_reason::text NOT IN ({values}))"
    )


def close_reason_group(reason: Optional[JobCloseReason | str]) -> CloseReasonGroup:
    """Grupa powodu zamknięcia; `unreviewed` = `other` albo brak powodu.

    `unreviewed` liczy się w mianowniku jak przegrana, dopóki ktoś nie
    przypisze powodu.
    """
    if reason is None:
        return "unreviewed"
    value = reason.value if isinstance(reason, JobCloseReason) else str(reason)
    if value in HIT_RATIO_WON_CLOSE_REASONS:
        return "won"
    if value in HIT_RATIO_LOST_CLOSE_REASONS:
        return "lost"
    if value in HIT_RATIO_NEUTRAL_CLOSE_REASONS:
        return "neutral"
    return "unreviewed"
