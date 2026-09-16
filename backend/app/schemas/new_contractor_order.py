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
    """Wycofane (09.2026): formularz zakłada umowę B2B, a ta jest bezterminowa.
    Pole zostaje w schemacie, żeby stara karta przeglądarki dostała czytelne
    422 zamiast cichego zignorowania daty; wartość inna niż ``null`` jest
    odrzucana w endpointcie."""

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

    # Legacy alias = waluta przychodowa klienta. Gdy nowe pola są nieobecne,
    # zachowujemy dawną semantykę jednej waluty dla obu stawek.
    currency: Optional[str] = Field(None, max_length=3)
    rate_client_currency: Optional[str] = Field(None, max_length=3)
    rate_candidate_currency: Optional[str] = Field(None, max_length=3)

    total_value: Optional[Decimal] = Field(None, ge=0, max_digits=13, decimal_places=3)
    """Total value pierwszego Orderu (rate_client × długość okresu) — opcjonalne."""

    notes: Optional[str] = None
    """Notatki — trafiają na Contract.handover_notes + Order.notes."""

    project_part: Optional[str] = Field(None, max_length=8)
    """„Część umowy" — tylko Centrum e-Zdrowia (walidacja w endpointcie przez
    app/services/ezdrowie.py; zabroniona u innych). Od ticketu „Struktura umów
    wykonawczych" jest POCHODNĄ z ``executive_contract_id`` — sama część już
    nie wystarcza."""

    executive_contract_id: Optional[int] = None
    """Umowa wykonawcza Centrum e-Zdrowia — wymagana dla client_id=115
    (``resolve_ezdrowie_assignment``), zabroniona u innych klientów."""


class NewContractorOrderResponse(BaseModel):
    contract_id: int
    order_id: int
    candidate_name: str
    monthly_margin: Optional[Decimal] = None
    """rate_client - rate_candidate przeliczone na miesięczną stawkę."""
