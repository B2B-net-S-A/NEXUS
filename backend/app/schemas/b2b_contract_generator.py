"""Pydantic DTOs dla Generatora Umów B2B."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class B2BRoleResponse(BaseModel):
    id: int
    category_key: str
    category_label_pl: str
    category_label_en: str
    slug: str
    name_pl: str
    name_en: str
    area_label_pl: str
    area_label_en: str
    scope_pl: list[str]
    scope_en: list[str]
    display_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class B2BRoleCreate(BaseModel):
    category_key: str
    slug: str
    name_pl: str
    name_en: str
    area_label_pl: str
    area_label_en: str
    scope_pl: list[str] = Field(default_factory=list)
    scope_en: list[str] = Field(default_factory=list)
    display_order: int = 0


class B2BRoleUpdate(BaseModel):
    category_key: Optional[str] = None
    name_pl: Optional[str] = None
    name_en: Optional[str] = None
    area_label_pl: Optional[str] = None
    area_label_en: Optional[str] = None
    scope_pl: Optional[list[str]] = None
    scope_en: Optional[list[str]] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class B2BGenerateRequest(BaseModel):
    # Strony — wymagane przy tworzeniu nowej umowy (gdy brak contract_id).
    candidate_id: Optional[int] = None
    client_id: Optional[int] = None
    job_id: Optional[int] = None
    # Aktualizacja istniejącego draftu B2B zamiast tworzenia nowego.
    contract_id: Optional[int] = None

    role_id: int
    language: str = "pl"

    # Pola edytowalne umowy.
    contract_number: Optional[str] = None
    signing_date: Optional[date] = None
    start_date: date
    project_city: Optional[str] = None
    project_description: Optional[str] = None
    correspondence_address: Optional[str] = None
    rate_candidate: Optional[int] = None
    currency: str = "PLN"
    rate_in_words: Optional[str] = None
    # Nadpisanie zakresu roli na poziomie tej umowy (None = użyj domyślnego).
    scope_items_override: Optional[list[str]] = None


class B2BGenerateResponse(BaseModel):
    contract_id: int
    draft_template_id: Optional[int] = None
    language: str


class B2BContractDetailResponse(BaseModel):
    contract_id: int
    candidate_id: Optional[int] = None
    client_id: Optional[int] = None
    job_id: Optional[int] = None
    role_id: Optional[int] = None
    language: str
    contract_number: Optional[str] = None
    signing_date: Optional[date] = None
    start_date: Optional[date] = None
    project_city: Optional[str] = None
    project_description: Optional[str] = None
    correspondence_address: Optional[str] = None
    rate_candidate: Optional[int] = None
    currency: Optional[str] = None
    rate_in_words: Optional[str] = None
    scope_items_override: Optional[list[str]] = None


class B2BRenderRequest(BaseModel):
    """Standalone render — wszystkie pola wprost z formularza (bez `Contract`)."""

    role_id: Optional[int] = None
    language: str = "pl"
    # Płeć Partnera — steruje formami gramatycznymi w komparycji/deklaracji
    # (Panem/ią, prowadzącym/cą, zwany/a, zapoznałem/am). "m" | "k".
    gender: str = "m"
    # Dane Partnera (firma) — edytowalne; pre-fill z kandydata opcjonalny.
    partner_name: Optional[str] = None
    partner_legal_name: Optional[str] = None
    partner_business_address: Optional[str] = None
    partner_correspondence_address: Optional[str] = None
    partner_nip: Optional[str] = None
    partner_regon: Optional[str] = None
    partner_email: Optional[str] = None
    partner_phone: Optional[str] = None
    # Klient + projekt
    client_name: Optional[str] = None
    project_city: Optional[str] = None
    project_description: Optional[str] = None
    # Warunki
    contract_number: Optional[str] = None
    signing_date: Optional[date] = None
    start_date: Optional[date] = None
    rate_candidate: Optional[int] = None
    currency: str = "PLN"
    rate_in_words: Optional[str] = None
    scope_items_override: Optional[list[str]] = None


class B2BRenderHtmlResponse(BaseModel):
    html: str
    contract_number: Optional[str] = None


class B2BNextNumberResponse(BaseModel):
    contract_number: str
    year: int
    seq: int


class B2BCompanyLookupResponse(BaseModel):
    """Dane firmy z rejestru państwowego (Biała Lista MF / KRS)."""

    name: Optional[str] = None
    # Osoba fizyczna (JDG) — imię i nazwisko; dla spółek None.
    person: Optional[str] = None
    nip: Optional[str] = None
    regon: Optional[str] = None
    krs: Optional[str] = None
    address: Optional[str] = None
    source: Optional[str] = None
