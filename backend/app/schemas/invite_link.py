"""Pydantic schemas for candidate invite links."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


InviteLinkStatus = Literal["active", "used", "revoked", "expired"]


class InviteLinkCreate(BaseModel):
    job_id: int = Field(..., description="Published job this link applies to.")
    label: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Private recruiter note, e.g. 'LinkedIn post 04/26'.",
    )
    # 0339: brak/None = bez terminu — link żyje do zamknięcia rekrutacji.
    expires_in_days: Optional[Literal[7, 14, 30, 90]] = Field(
        default=None,
        description="Link validity window; null = valid until the job closes.",
    )


class InviteLinkJobBrief(BaseModel):
    id: int
    title: str


class InviteLinkCreatorBrief(BaseModel):
    id: int
    name: str


class InviteLinkResponse(BaseModel):
    token: str
    url: str
    public_url: str = ""
    kind: Literal["job", "recruiter"] = "job"
    slug: Optional[str] = None
    visit_count: int = 0
    job: InviteLinkJobBrief
    label: Optional[str] = None
    expires_at: Optional[datetime] = None
    revoked: bool = False
    use_count: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime
    status: InviteLinkStatus
    origin_assignment_id: Optional[int] = None
    priority_compliant_at_create: Optional[bool] = None
    created_by_user: Optional[InviteLinkCreatorBrief] = None

    model_config = {"from_attributes": True}


# ── Strona kariery (0339) ─────────────────────────────────────────────────


class CareerLinkBrief(BaseModel):
    slug: str
    public_url: str
    created_at: datetime
    visit_count: int = 0
    # 0489: „O mnie” na stronie rekrutera (``None`` = nie wpisane).
    about: Optional[str] = None


class CareerLinkStats(BaseModel):
    days: int = 30
    applications: int = 0
    new_candidates: int = 0


class CareerLinkJob(BaseModel):
    job_id: int
    title: str
    profile_status: Literal["none", "draft", "approved"]
    show_on_recruiter_page: bool
    has_link: bool


class CareerLinkResponse(BaseModel):
    link: Optional[CareerLinkBrief] = None
    # Adres strony kariery i prefiks stałego linku (z końcowym „/") — front
    # nie zgaduje domeny ani ścieżki.
    base_url: str
    recruiter_base_url: str
    stats: CareerLinkStats
    suggested_slug: str
    jobs: list[CareerLinkJob] = Field(default_factory=list)


class CareerLinkResultCounts(BaseModel):
    """Lejek linku w oknie (etap 4 linków, 19.10.2026). ``visits`` = od początku."""

    visits: int = 0
    applications: int = 0
    new_candidates: int = 0
    existing_candidates: int = 0
    in_process: int = 0
    verified: int = 0
    cv_sent: int = 0
    hired: int = 0


class CareerLinkResultRow(CareerLinkResultCounts):
    kind: Literal["job", "recruiter"]
    slug: Optional[str] = None
    public_url: Optional[str] = None
    job_id: Optional[int] = None
    # Tytuł dla rekrutera (working_title ?? title) — ekran wewnętrzny.
    job_title: Optional[str] = None
    state: Literal["live", "not_live", "closed", "expired", "revoked"]


class CareerLinkResults(BaseModel):
    # ``None`` = od początku.
    days: Optional[int] = None
    totals: CareerLinkResultCounts
    links: list[CareerLinkResultRow] = Field(default_factory=list)


class CareerLinkUpdate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    # 0489: pole pominięte = bez zmiany, pusty napis = usuń. Limit 280 znaków
    # sprawdza trasa po wycięciu znaków formatujących i zbędnych spacji.
    about: Optional[str] = Field(None, max_length=2000)


class SlugAvailability(BaseModel):
    available: bool
    reason: Optional[str] = None


class PublicSections(BaseModel):
    must: bool = True
    nice: bool = True
    params: bool = True
    process: bool = True


class PublicProfileFinding(BaseModel):
    code: Literal["client_name", "money", "contact", "person_name", "internal_code"]
    message: str
    excerpt: str


class PublicProfileLive(BaseModel):
    """Wersja, którą dziś widzi kandydat (19.10.2026).

    ``pending_changes`` = opis w edytorze różni się od opublikowanego; strona
    pokazuje tę wersję, dopóki nikt nie zatwierdzi nowej. Pola tekstowe służą
    też do „Odrzuć zmiany” (zapis szkicu z tymi wartościami)."""

    title: str
    subtitle: Optional[str] = None
    about: Optional[str] = None
    sections: PublicSections
    pending_changes: bool = False


class PublicProfileUpdate(BaseModel):
    public_title: Optional[str] = Field(default=None, max_length=200)
    subtitle: Optional[str] = Field(default=None, max_length=300)
    about: Optional[str] = Field(default=None, max_length=4000)
    sections: Optional[PublicSections] = None
    show_on_recruiter_page: Optional[bool] = None
    # 0478: szablon graficzny; ``null`` = wróć do domyślnego według roli.
    theme: Optional[str] = Field(default=None, max_length=32)

    @field_validator("theme")
    @classmethod
    def _known_theme(cls, value: Optional[str]) -> Optional[str]:
        from app.services.career_theme import THEMES

        if value is not None and value not in THEMES:
            raise ValueError("Nieznany szablon strony.")
        return value


class PublicProfileVisibility(BaseModel):
    show_on_recruiter_page: bool


class PublicProfileResponse(BaseModel):
    job_id: int
    status: Literal["none", "draft", "approved"]
    public_title: Optional[str] = None
    default_title: str
    effective_title: str
    subtitle: Optional[str] = None
    about: Optional[str] = None
    sections: PublicSections
    show_on_recruiter_page: bool = True
    # 0478: wybór rekrutera (``None`` = domyślny) i domyślny według roli.
    theme: Optional[str] = None
    theme_default: str = "grafit"
    approved_at: Optional[datetime] = None
    approved_by_name: Optional[str] = None
    # Zatwierdzony opis, ale must/nice, miasto, start albo długość zmieniły się
    # w rekrutacji — strona pokazuje stan z zatwierdzenia (migawka), a podgląd
    # obok to, co wejdzie po ponownym zatwierdzeniu.
    approved_content_stale: bool = False
    findings: list[PublicProfileFinding] = Field(default_factory=list)
    preview: dict
    # ``None`` = strona rekrutacji daje 404 (opis nigdy niezatwierdzony albo
    # zmienił się klient rekrutacji).
    live: Optional[PublicProfileLive] = None


class PublicProfileDraft(BaseModel):
    subtitle: str
    about: str
