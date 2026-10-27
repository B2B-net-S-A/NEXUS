"""Schematy ogłoszenia do wklejenia na portale (``app/api/job_ads.py``)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.job_ad_publication import AdPublicationRead
from app.services.job_ad import fixed_blocks, generate

Lang = Literal["pl", "en"]
TechLevel = Literal["critical", "must", "nice"]
# Limity jak w `generate.clean_content` — przekroczenie ma być błędem 422,
# nie cichym obcięciem punktu, który rekruter właśnie dopisał.
Item = Annotated[str, StringConstraints(max_length=generate.ITEM_MAX)]
ListItems = list[str]
_LIMITS = generate.LIST_LIMITS


class AdContent(BaseModel):
    """Pola, które rekruter może poprawić ręcznie."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=generate.TITLE_MAX)
    lead: str = Field(default="", max_length=generate.LEAD_MAX)
    about: str = Field(default="", max_length=generate.ABOUT_MAX)
    start: str = Field(default="", max_length=generate.TERM_MAX)
    duration: str = Field(default="", max_length=generate.TERM_MAX)
    # Język pracy (np. „polski, angielski B2”) — nie język ogłoszenia.
    language: str = Field(default="", max_length=generate.TERM_MAX)
    responsibilities: list[Item] = Field(
        default_factory=list, max_length=_LIMITS["responsibilities"]
    )
    requirements: list[Item] = Field(
        default_factory=list, max_length=_LIMITS["requirements"]
    )
    nice_to_have: list[Item] = Field(
        default_factory=list, max_length=_LIMITS["nice_to_have"]
    )
    offer: list[Item] = Field(default_factory=list, max_length=_LIMITS["offer"])


class AdTechItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    level: TechLevel = "must"


class AdGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lang: Lang = "pl"
    # Jak w `AdUpdateRequest`: wersja, którą okno miało na ekranie, gdy
    # rekruter potwierdzał zastąpienie treści.
    expected_updated_at: Optional[datetime] = None


class AdUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: AdContent
    tech: list[AdTechItem] = Field(default_factory=list, max_length=40)
    # `updated_at` wersji, którą okno miało na ekranie. Podane i inne niż
    # w bazie = 409: ktoś w międzyczasie zapisał albo przygotował ogłoszenie.
    expected_updated_at: Optional[datetime] = None


class AdContentRead(AdContent):
    """Odczyt łagodny: nieznany klucz w zapisanym JSONB (wiersz z nowszej
    wersji po wycofaniu wdrożenia) nie może dać 500 przy otwarciu okna."""

    model_config = ConfigDict(extra="ignore")


class AdTechRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    level: TechLevel = "must"


class AdRead(BaseModel):
    lang: Lang
    content: AdContentRead
    tech: list[AdTechRead]
    source: Literal["ai", "template"]
    generated_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Rekrutacja zmieniła się od przygotowania ogłoszenia.
    stale: bool = False


class AdFact(BaseModel):
    key: str
    label: str
    value: str


class AdReadinessItem(BaseModel):
    key: str
    label: str
    present: bool


class AdFinding(BaseModel):
    code: str
    severity: Literal["block", "advise"]
    message: str
    excerpt: Optional[str] = None
    field: Optional[str] = None


class RenderedField(BaseModel):
    key: str
    label: str
    kind: Literal["text", "list", "ordered"]
    text: str
    html: str
    items: list[str]
    auto_count: int = 0
    fixed_count: int = 0


class RenderedPracuj(BaseModel):
    fields: list[RenderedField]
    params: list[str]


class RenderedTech(BaseModel):
    name: str
    level: int
    label: str
    source: TechLevel


class RenderedSection(BaseModel):
    key: str
    heading: Optional[str] = None
    kind: Literal["text", "list", "ordered"]
    text: str
    items: list[str]
    fixed_count: int = 0


class RenderedJjit(BaseModel):
    form_fields: list[AdFact]
    tech_stack: list[RenderedTech]
    # Technologie poza limitem portalu (10) — okno mówi o nich wprost.
    tech_overflow: int = 0
    sections: list[RenderedSection]
    body_html: str
    body_text: str


class RenderedAd(BaseModel):
    title: str
    pracuj: RenderedPracuj
    jjit: RenderedJjit


class AdCareerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Wersja ogłoszenia, którą okno miało na ekranie — strona dostaje
    # dokładnie tę treść, którą osoba przeczytała.
    expected_updated_at: Optional[datetime] = None


class AdCareerState(BaseModel):
    """Strona kariery rekrutacji (21.10.2026)."""

    # none = strony nie ma · live = pokazuje to ogłoszenie ·
    # outdated = działa, ale z inną treścią niż obecne ogłoszenie.
    status: Literal["none", "live", "outdated"] = "none"
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    published_by_name: Optional[str] = None


AdChannel = Literal["kariera", "pracuj", "jjit"]


class AdChannelView(BaseModel):
    """Stan jednego kanału rekrutacji (przypomnienia o ogłoszeniach, 0526)."""

    channel: AdChannel
    # requested = mail do opiekuna Pracuj.pl wyszedł, opiekun ma jeszcze czas.
    state: Literal["live", "missing", "skipped", "requested"]
    since: Optional[datetime] = None
    # Brak robi ta osoba (rekruter: strona kariery; DL: portale).
    mine: bool = False
    owner_names: list[str] = Field(default_factory=list)
    skip_reason: Optional[str] = None
    skipped_by_name: Optional[str] = None


class AdReminders(BaseModel):
    channels: list[AdChannelView]
    # „Nie publikujemy” i „Przypomnij”: DL rekrutacji, Head of Recruitment, admin.
    can_manage: bool = False
    recruiter_names: list[str] = Field(default_factory=list)


class AdSkipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=300)


class AdRemindResponse(BaseModel):
    sent_to: list[str]
    # Już dziś przypomniano — drugi mail tego dnia nie wychodzi.
    already: list[str] = Field(default_factory=list)


class PracujRequestRead(BaseModel):
    """Ostatni mail do opiekuna Pracuj.pl wysłany z NEXUSA (27.10.2026)."""

    sent_at: datetime
    sent_by_name: Optional[str] = None
    to: Optional[str] = None
    # Opiekun ma jeszcze czas — przypomnienia o Pracuj.pl milczą.
    waiting: bool = False


RateValue = Annotated[int, Field(ge=1, le=5000)]


class PracujMailPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_from: Optional[RateValue] = None
    rate_to: Optional[RateValue] = None


class PracujMailRequest(PracujMailPreviewRequest):
    # Wersja ogłoszenia z ekranu — mail niesie treść, którą osoba przeczytała.
    expected_updated_at: Optional[datetime] = None
    # Ten sam UUID przy ponowieniu = ten sam mail (bez drugiej wysyłki).
    client_request_id: Optional[str] = Field(default=None, max_length=64)


class PracujMailPreview(BaseModel):
    to_name: str
    to_email: str
    # Skrzynka osoby: ready = wyśle · missing = niepodłączona · reconnect =
    # trzeba połączyć ponownie. Bez „ready” okno daje tylko „Kopiuj treść”.
    mailbox: Literal["ready", "missing", "reconnect"]
    from_address: Optional[str] = None
    subject: str
    body_text: str
    # Stawka, której nie wyślemy (pusta, odwrócona) — komunikat do pola.
    rate_error: Optional[str] = None


class JobAdResponse(BaseModel):
    ad: Optional[AdRead] = None
    career: AdCareerState = Field(default_factory=AdCareerState)
    facts: list[AdFact]
    readiness: list[AdReadinessItem]
    findings: list[AdFinding] = Field(default_factory=list)
    rendered: Optional[RenderedAd] = None
    # Kopiowanie wolno włączyć: ogłoszenie istnieje i nie ma znalezisk blokujących.
    can_copy: bool = False
    # Gdzie ogłoszenie wisi (0432) — także wiersze „zdjęte z portalu”.
    publications: list[AdPublicationRead] = Field(default_factory=list)
    # Trzy kanały i kto je robi (0526); brak = rekrutacja zamknięta.
    reminders: Optional[AdReminders] = None
    # Ostatni mail do opiekuna Pracuj.pl (27.10.2026).
    pracuj_request: Optional[PracujRequestRead] = None


class CareerQueueItem(BaseModel):
    """Otwarta rekrutacja bez strony kariery (kolejka „Opublikuj i następna”)."""

    job_id: int
    title: str
    city: Optional[str] = None
    remote_policy: Optional[str] = None
    delivery_lead_name: Optional[str] = None
    opened_at: Optional[datetime] = None
    # ready = treść czeka · template = złożona bez modelu · missing = brak treści
    ad: Literal["ready", "template", "missing"] = "missing"


class CareerQueueResponse(BaseModel):
    scope: Literal["mine", "all"]
    # Liczby dla obu zakresów — przełącznik i kafel pokazują je od razu.
    mine_count: int
    all_count: int
    items: list[CareerQueueItem]


class MissingAdsItem(BaseModel):
    """Rekrutacja z brakiem, który robi osoba („Ogłoszenia do nadrobienia”)."""

    job_id: int
    title: str
    client: Optional[str] = None
    opened_at: Optional[datetime] = None
    # Otwarta przed startem przypomnień — idzie mailem zbiorczym.
    backlog: bool = False
    channels: list[AdChannelView]


class MissingAdsResponse(BaseModel):
    items: list[MissingAdsItem]


class LangBlocksModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer: ListItems = Field(
        default_factory=list, max_length=fixed_blocks.OFFER_MAX_ITEMS
    )
    process: ListItems = Field(
        default_factory=list, max_length=fixed_blocks.PROCESS_MAX_ITEMS
    )
    about: str = Field(default="", max_length=fixed_blocks.ABOUT_MAX_CHARS)


class PracujCaretakerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=fixed_blocks.CARETAKER_NAME_MAX)
    email: str = Field(max_length=fixed_blocks.CARETAKER_EMAIL_MAX)


class FixedBlocksModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_suffix: Literal["kmx", "km", "none"]
    pl: LangBlocksModel
    en: LangBlocksModel
    # Brak w zapisie = zostaje zapisany opiekun (okno sprzed 27.10.2026).
    pracuj_caretaker: Optional[PracujCaretakerModel] = None
