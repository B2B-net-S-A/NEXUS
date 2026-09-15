"""DTO powiadomień Delivery Leada."""

from __future__ import annotations

from datetime import date, datetime
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


class DlAlertCard(BaseModel):
    """Jedna karta panelu „Moi klienci" = jedna SPRAWA (``event_key``).

    Kilka wierszy powtórek jednej sprawy (T-30, T-23, T-14…) składa się w jedną
    kartę: treść i link z najnowszego wiersza, priorytet najwyższy w sprawie.
    ``id`` to najnowszy wiersz — ``POST /{id}/handled`` zamyka całą sprawę.
    """

    id: int
    event_key: Optional[str] = None
    alert_type: str
    alert_type_label: str
    section: str
    priority: str

    client_id: int
    client_name: str
    order_group_id: Optional[int] = None
    order_id: Optional[int] = None

    title: str
    message: str
    link: Optional[str] = None
    candidate_name: Optional[str] = None
    end_date: Optional[date] = None
    days_left: Optional[int] = None
    missing_fields: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    received_at: Optional[str] = None

    first_alert_at: datetime
    last_alert_at: datetime
    repeat_count: int = 1
    email_sent: bool = False
    email_requested: bool = False
    can_mark_handled: bool = True
    """``False`` dla decyzji MD po zakończeniu współpracy — zamyka ją wyłącznie
    decyzja w zamówieniu (409 ``offboarding_decision_required``)."""


class DlAlertCardsResponse(BaseModel):
    cards: list[DlAlertCard] = Field(default_factory=list)
    total: int = 0
