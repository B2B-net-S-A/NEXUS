"""Manifest jednorazowego importu zamówień MD Centrum e-Zdrowia (Faza C).

Plik JSON jest przygotowywany POZA repozytorium (niesie nazwiska i stawki ze
zgłoszenia) i wysyłany do ``POST /api/admin/clients/{client_id}/ezdrowie-md-orders/import``
z ``dry_run=true`` (podgląd dopasowań osób) albo ``false`` (zapis). Kształt
opisuje UKŁAD danych ze zgłoszenia: jedna karta zamówienia MD na umowę
wykonawczą, linie z zakresem podstawowym/opcjonalnym i stawkami PLN/MD,
historia miesięczna ze statusem, zastępstwa jako para linii.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

ConsumptionStatus = Literal["accepted", "protocol"]


class SeedContractSpec(BaseModel):
    """Kontrakt zakładany dla osoby, która nie ma kontraktu u klienta."""

    start_date: date
    end_date: Optional[date] = None
    status: Literal["active", "ended"] = "active"

    @model_validator(mode="after")
    def _ended_needs_end(self) -> "SeedContractSpec":
        if self.status == "ended" and self.end_date is None:
            raise ValueError("Kontrakt zakończony wymaga daty końca")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Data końca kontraktu przed datą startu")
        return self


class SeedPerson(BaseModel):
    """Osoba na linii — rozpoznawana kolejno po ``contract_id``, ``candidate_id``, nazwisku."""

    name: str = Field(..., min_length=3, max_length=255)
    contract_id: Optional[int] = Field(None, gt=0)
    candidate_id: Optional[int] = Field(None, gt=0)
    create_if_missing: bool = False
    """Załóż kandydata (imię + nazwisko z ``name``) gdy nikogo nie znaleziono."""
    contract: Optional[SeedContractSpec] = None
    """Wymagany, gdy osoba nie ma kontraktu u klienta (kandydat albo nowa osoba)."""


class SeedConsumption(BaseModel):
    month: str
    md: Decimal = Field(..., ge=0, max_digits=16, decimal_places=6)
    status: Optional[ConsumptionStatus] = None
    note: Optional[str] = Field(None, max_length=255)

    @field_validator("month")
    @classmethod
    def _month_shape(cls, value: str) -> str:
        if not _MONTH_RE.match(value):
            raise ValueError("Miesiąc w formacie RRRR-MM")
        return value


class SeedLine(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    """Identyfikator linii w manifeście (do ``replaces_key`` i raportu)."""
    person: SeedPerson
    base_md: Decimal = Field(..., gt=0, max_digits=16, decimal_places=6)
    optional_md: Optional[Decimal] = Field(None, ge=0, max_digits=16, decimal_places=6)
    rate_cost: Decimal = Field(..., ge=0, max_digits=12, decimal_places=2)
    rate_revenue: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    start_date: date
    end_date: Optional[date] = None
    line_status: Literal["active", "completed"] = "active"
    replaces_key: Optional[str] = None
    """Klucz linii TEJ grupy, za którą ta osoba jest zastępstwem."""
    history: list[SeedConsumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def _completed_needs_end(self) -> "SeedLine":
        if self.line_status == "completed" and self.end_date is None:
            raise ValueError(f"Linia {self.key}: zakończona linia wymaga daty końca")
        months = [row.month for row in self.history]
        if len(months) != len(set(months)):
            raise ValueError(f"Linia {self.key}: powtórzony miesiąc w historii")
        return self


class SeedGroup(BaseModel):
    executive_contract_number: str = Field(..., min_length=1, max_length=64)
    order_number: str = Field(..., min_length=1, max_length=64)
    start_date: date
    end_date: Optional[date] = None
    lines: list[SeedLine] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def _keys_and_replacements(self) -> "SeedGroup":
        keys = [line.key for line in self.lines]
        if len(keys) != len(set(keys)):
            raise ValueError(f"Grupa {self.order_number}: powtórzony klucz linii")
        for line in self.lines:
            if line.replaces_key is not None and line.replaces_key not in keys:
                raise ValueError(
                    f"Grupa {self.order_number}: linia {line.key} zastępuje "
                    f"nieznany klucz {line.replaces_key}"
                )
            if line.replaces_key == line.key:
                raise ValueError(f"Linia {line.key} nie może zastępować samej siebie")
        return self


class EzdrowieMdSeedManifest(BaseModel):
    client_id: int = Field(..., gt=0)
    source: Optional[str] = Field(None, max_length=255)
    supersede_order_ids: list[int] = Field(default_factory=list, max_length=200)
    """Samodzielne SZKICE zamówień, które karty MD zastępują — anulowane, nie kasowane."""
    groups: list[SeedGroup] = Field(..., min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique_order_numbers(self) -> "EzdrowieMdSeedManifest":
        numbers = [group.order_number for group in self.groups]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Powtórzony numer zamówienia w manifeście")
        return self


# ── Raport (dry-run i apply) ───────────────────────────────────────────────

PersonResolution = Literal["resolved", "created", "ambiguous", "missing"]


class SeedPersonReport(BaseModel):
    resolution: PersonResolution
    candidate_id: Optional[int] = None
    contract_id: Optional[int] = None
    contract_created: bool = False
    candidate_created: bool = False
    candidates: list[dict] = Field(default_factory=list)
    """Przy ``ambiguous``: ``[{id, full_name}]`` do wyboru w manifeście."""
    reason: Optional[str] = None


class SeedLineReport(BaseModel):
    key: str
    person: SeedPersonReport
    order_id: Optional[int] = None
    status: str
    md_total: Decimal
    md_optional_total: Optional[Decimal] = None
    md_used: Decimal
    md_base_used: Decimal
    md_optional_used: Decimal
    consumptions: int
    predecessor_key: Optional[str] = None


class SeedGroupReport(BaseModel):
    order_number: str
    executive_contract_number: str
    status: Literal["created", "already_exists", "blocked"]
    group_id: Optional[int] = None
    lines: list[SeedLineReport] = Field(default_factory=list)
    md_positions_total: Decimal = Decimal("0")
    md_used_total: Decimal = Decimal("0")
    contract_value_pln: Decimal = Decimal("0")
    used_value_pln: Decimal = Decimal("0")


class SeedTotals(BaseModel):
    groups_created: int = 0
    lines: int = 0
    consumptions: int = 0
    md_used_sum: Decimal = Decimal("0")
    contracts_created: int = 0
    candidates_created: int = 0
    orders_superseded: int = 0


class EzdrowieMdSeedReport(BaseModel):
    dry_run: bool
    applied: bool
    groups: list[SeedGroupReport]
    superseded: list[dict] = Field(default_factory=list)
    """``[{order_id, status: cancelled|blocked, reason}]``."""
    totals: SeedTotals
    blockers: list[str] = Field(default_factory=list)
    """Powody, dla których ``dry_run=false`` odmówi zapisu (409)."""
    receipt_key: Optional[str] = None
