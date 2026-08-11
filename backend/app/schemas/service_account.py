"""Schematy Pydantic dla kont serwisowych i kluczy API (Ustawienia → API).

Zasada przewijająca się przez cały plik: **sekret nie ma pola w żadnym modelu
odczytu**. Nie „jest pomijany przy serializacji", tylko fizycznie nie istnieje
w ``ServiceAccountKeyOut`` — jedyna klasa niosąca klucz to
``ServiceAccountKeyCreateResponse``, zwracana wyłącznie z POST-a tworzącego.
Dzięki temu dołożenie nowego endpointu listującego nie ma jak przypadkiem
wystawić poświadczenia.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.service_account import ServiceScope

# Slug jest identyfikatorem w logach i audycie, więc trzymamy go w wąskim
# alfabecie: bez spacji, bez wielkich liter, bez znaków, które trzeba by
# escape'ować w zapytaniach do Loki/Grafany.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


class ScopeInfo(BaseModel):
    """Pozycja słownika scope'ów dla pickera w Ustawieniach."""

    value: str
    label: str


class ServiceAccountKeyOut(BaseModel):
    """Metadane klucza. Nie ma tu pola na sekret i nie wolno go dodać."""

    key_id: str
    label: str
    created_at: datetime
    created_by: Optional[int]
    expires_at: datetime
    revoked_at: Optional[datetime]
    revoked_by: Optional[int]
    revoke_reason: Optional[str]
    last_used_at: Optional[datetime]
    last_used_ip: Optional[str]

    model_config = {"from_attributes": True}


class ServiceAccountOut(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str]
    scopes: List[str]
    is_active: bool
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    keys: List[ServiceAccountKeyOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ServiceAccountCreate(BaseModel):
    slug: str = Field(..., min_length=3, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=2000)
    scopes: List[ServiceScope] = Field(
        default_factory=list,
        description="Uprawnienia konta. Pusta lista = konto bez żadnych uprawnień.",
    )

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        normalised = value.strip().lower()
        if not _SLUG_RE.match(normalised):
            raise ValueError(
                "slug: małe litery, cyfry i myślniki; musi zaczynać się "
                "i kończyć znakiem alfanumerycznym"
            )
        return normalised


class ServiceAccountUpdate(BaseModel):
    """PATCH częściowy — pominięte pole zostaje bez zmian.

    Rozróżnienie idzie po ``model_fields_set`` w handlerze (wzorzec
    ``B2BGeneratedContractUpdate``), bo wszystkie pola są ``Optional``, więc
    ``None`` znaczy „nie podano", a nie „wyczyść".

    ``slug`` jest świadomie NIEZMIENNY: to identyfikator w historycznych logach,
    a przemianowanie rozspójniłoby audyt wstecz. Do zmiany etykiety jest ``name``.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=2000)
    scopes: Optional[List[ServiceScope]] = None
    is_active: Optional[bool] = None


class ServiceAccountKeyCreate(BaseModel):
    label: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Po co ten klucz, np. 'GitHub Actions deploy'.",
    )
    expires_in_days: Optional[int] = Field(
        None,
        ge=1,
        description=(
            "Ważność w dniach. Pominięte = domyślny okres z konfiguracji; "
            "wartość powyżej sufitu jest przycinana do sufitu."
        ),
    )


class ServiceAccountKeyCreateResponse(BaseModel):
    """JEDYNE miejsce, w którym sekret opuszcza serwer.

    Zwracane raz, w odpowiedzi na utworzenie klucza. Potem w bazie zostaje
    wyłącznie SHA-256, więc klucza nie da się odzyskać — zgubiony wymienia się
    przez wydanie nowego i rewokację starego (na tym samym koncie, więc audyt
    się nie rwie).
    """

    key: ServiceAccountKeyOut
    api_key: str = Field(
        ...,
        description=(
            "Pełny klucz API do nagłówka X-API-Key. Pokazywany RAZ — "
            "nie da się go odczytać ponownie."
        ),
    )


class ServiceAccountKeyRevoke(BaseModel):
    reason: Optional[str] = Field(None, max_length=255)
