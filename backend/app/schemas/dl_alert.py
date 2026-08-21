"""DTO powiadomień Delivery Leada."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DlAlertRead(BaseModel):
    id: int
    alert_type: str
    alert_type_label: str
    status: str
    status_label: str

    client_id: int
    client_name: str
    order_group_id: Optional[int] = None
    order_id: Optional[int] = None

    title: str
    message: str
    link: Optional[str] = None

    recipient_user_id: int
    recipient_name: str

    created_at: datetime
    handled_at: Optional[datetime] = None
    handled_by_user_id: Optional[int] = None
    handled_by_name: Optional[str] = None
    reaction_seconds: Optional[int] = None
    reaction_label: str = "—"
    """Czas reakcji liczony serwerowo. Front go NIE wylicza: ta sama liczba
    trafia do eksportu XLSX, a dwa niezależne wyliczenia tej samej wartości
    rozjeżdżają się przy pierwszej zmianie strefy czasowej."""


class DlAlertListResponse(BaseModel):
    alerts: list[DlAlertRead] = Field(default_factory=list)
    total_new: int = 0
    total_handled: int = 0
    """Liczniki obu zakładek naraz — inaczej przełączenie na „Historia"
    musiałoby najpierw pobrać dane, żeby dowiedzieć się, czy coś tam jest."""


class DlAlertScopeResponse(BaseModel):
    """Co ten użytkownik może zobaczyć i wyeksportować."""

    can_export_all: bool = False
