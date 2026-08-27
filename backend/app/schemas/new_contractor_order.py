"""Schemas dla atomic create Contract + Order (Flow B "Nowy kontraktor")."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.order_type import OrderType


class NewContractorOrderRequest(BaseModel):
    """POST `/api/clients/{client_id}/contract-with-order` body.

    Atomic: tworzy nowy kandydacki Contract + pierwszy ClientOrder w 1 transakcji.
    Używane gdy DL dostaje PDF od klienta dla NOWEGO kontraktora (nigdy wcześniej
    nie współpracował z tym klientem).
    """

    candidate_id: int
    job_id: Optional[int] = None
    """Z której rekrutacji wzięło się to zamówienie (zalecane, nullable dla legacy)."""

    framework_contract_id: Optional[int] = None
    """MSA pod którą jest Order. Nullable bo klient może nie mieć MSA."""

    # Contract-level
    contract_start_date: Optional[date] = None
    """Nullable — zamówienie może nie mieć znanej daty "od"."""
    contract_end_date: Optional[date] = None
    """End date kontraktu (typically dłuższy niż pierwszy Order)."""

    # Order-level
    order_type: OrderType = OrderType.periodic
    title: str = Field(..., min_length=1, max_length=255)
    order_start_date: Optional[date] = None
    """Nullable — kolumna "Zamówienie od" bywa pusta."""
    order_end_date: Optional[date] = None

    # Finansowe. Opcjonalne na poziomie schematu, aby Delivery Lead mógł
    # utworzyć część operacyjną bez kwot. Endpoint wymaga obu stawek od Admina
    # i odrzuca każdy jawny klucz finansowy od pozostałych ról.
    rate_client: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=3)
    """Stawka jaką klient nam płaci (z PDF zamówienia) — dziesiętna (np. 164.375)."""

    rate_candidate: Optional[Decimal] = Field(
        None, ge=0, max_digits=12, decimal_places=3
    )
    """Stawka jaką my płacimy kontraktorowi (z naszego B2B) — dziesiętna (np. 157.5)."""

    rate_unit: Optional[str] = None
    """``monthly`` / ``daily`` / ``hourly``; Admin defaultuje do monthly."""

    billing_hours_per_month: Optional[int] = Field(None, ge=1)
    """Dla rate_unit=hourly; Admin defaultuje do 160."""

    currency: Optional[str] = Field(None, max_length=3)

    total_value: Optional[float] = None
    """Total value pierwszego Orderu (rate_client × długość okresu) — opcjonalne."""

    notes: Optional[str] = None
    """Notatki — trafiają na Contract.handover_notes + Order.notes."""

    project_part: Optional[str] = Field(None, max_length=8)
    """„Część umowy" — tylko Centrum e-Zdrowia (walidacja w endpointcie przez
    app/services/ezdrowie.py; wymagana dla client_id=115, zabroniona u innych)."""


class NewContractorOrderResponse(BaseModel):
    contract_id: int
    order_id: int
    candidate_name: str
    monthly_margin: Optional[Decimal] = None
    """rate_client - rate_candidate przeliczone na miesięczną stawkę."""
