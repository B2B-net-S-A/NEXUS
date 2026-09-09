"""Reguły CV per klient — pełna recepta Delivery Leada.

Dwa wejścia, jedna prawda w bazie:

* profil klienta (``/api/clients/{id}/cv-rule``) — odczyt i zapis reguły;
* przegląd zbiorczy (``/api/settings/cv-rules``) — wszystkie reguły w zasięgu
  użytkownika (dla administratora cała baza), nie tylko zasiane szablony.
  Delivery Lead zarządza z niego wszystkimi klientami.

``confirmed_at IS NULL`` znaczy **propozycja, która nie obowiązuje**. Generator
czyta wyłącznie reguły zatwierdzone (``resolve_client_rule``), więc zasiane
dopasowanie po nazwie klienta nie może wejść w życie bez decyzji człowieka.
Własną regułę autor zatwierdza tym samym zapisem (``confirm=true``).

Bramka zarządzania to centralne uprawnienie sekcji Delivery oraz resolver
dostępu do konkretnego klienta. Admin i Delivery Lead mają zasięg globalny.
Pojedynczy odczyt
reguły pozostaje dostępny z Pipeline dla rekrutera pracującego przy Jobie tego
klienta — nadal przez ten sam resolver, nigdy organizacyjnie.

Warstwy reguły (0255 → 0266 → 0267): nazwa pliku i język → instrukcje dla
modelu → blokady (tryb, wymagane wejścia, druga wersja językowa), polityka
prezentacji egzekwowana w kodzie, słownik, wersja + historia + CV próbne.
Każdy zapis zmieniający treść bumpuje ``version`` i zostawia wpis
w ``client_cv_rule_events`` — bez tego reklamacja klienta jest nie do
prześledzenia.
"""

import hashlib
import logging
from contextlib import nullcontext
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import OperationalUser
from app.api.section_access import DeliverySectionUser
from app.core.database import AsyncSessionLocal, get_db
from app.models.ai_feature import AIFeatureKey
from app.models.client import Client
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_event import ClientCvRuleEvent
from app.models.client_cv_rule_publication import ClientCvRulePublication
from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.help_material import HelpMaterial
from app.models.user import User
from app.services.cv_generator_b2b.language_aliases import alias_catalog, resolve_alias
from app.services.client_access import (
    deny,
    resolve_client_access,
    resolve_client_visible_client_ids,
)
from app.services.ai_quota import (
    AIQuotaExceeded,
    QuotaState,
    check_and_increment,
    declared_call,
)
from app.services.cv_generator_b2b.client_rules import (
    CONTENT_MODES,
    DATE_FORMATS,
    GENERATOR_INSTRUCTIONS_MAX_LENGTH,
    KNOWN_TOKENS,
    SECTION_KEYS,
    build_filename,
    build_prompt_blocks,
    describe_rule,
    snapshot_rule,
)
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    CandidateGenerationSource,
    generate_cv_from_candidate_source,
    load_candidate_generation_source,
    prepare_source_facts,
    list_recruitments_with_readiness,
)
from app.services.cv_generator_b2b.upload_preflight import validate_cv_file
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["client-cv-rules"])

# Slugi szablonów „Profil Championa — per klient" z migracji 0219. Ekran
# weryfikacji pokazuje WSZYSTKIE czternaście, także te, dla których seed nie
# stworzył wiersza (nazwa klienta wieloznaczna) — inaczej brakująca reguła
# byłaby nieodróżnialna od nieistniejącej.
CHAMPION_SEED_KEYS: tuple[tuple[str, str], ...] = (
    ("profil-championa-wzor-alior-docx", "ALIOR"),
    ("profil-championa-wzor-bank-pocztowy-docx", "Bank Pocztowy"),
    ("profil-championa-wzor-bik-docx", "BIK"),
    ("profil-championa-wzor-bnp-paribas-docx", "BNP PARIBAS"),
    ("profil-championa-wzor-credit-agricole-docx", "Credit Agricole"),
    ("profil-championa-wzor-energa-docx", "ENERGA"),
    ("profil-championa-wzor-kir-docx", "KIR"),
    ("profil-championa-wzor-nordea-docx", "Nordea"),
    ("profil-championa-wzor-orlen-docx", "ORLEN"),
    ("profil-championa-wzor-pansa-docx", "PANSA"),
    ("profil-championa-wzor-pfron-docx", "PFRON"),
    ("profil-championa-wzor-pko-bp-docx", "PKO BP"),
    ("profil-championa-wzor-santander-docx", "SANTANDER"),
    ("profil-championa-wzor-tauron-docx", "Tauron"),
)

# Pola reguły objęte wersjonowaniem i diffem w historii. Kolejność = kolejność
# w `changes`; flagi klienta (`cv_content_mode_cap`, `cv_interactive_enabled`)
# są zapisywane NA KLIENCIE, ale w diffie idą razem — jeden ekran, jedna historia.
RULE_FIELDS: tuple[str, ...] = (
    "filename_pattern",
    "spaces_to_underscores",
    "cv_language",
    "requires_en_copy",
    "requires_rodo_consent_block",
    "notes",
    "generator_instructions",
    "generator_instructions_en",
    "content_mode",
    "content_mode_locked",
    "require_screening_notes_min_chars",
    "require_project_ref",
    "require_position",
    "require_champion",
    "auto_second_language",
    "omit_sections",
    "max_roles",
    "max_bullets_per_role",
    "max_bullet_chars",
    "why_points_max",
    "date_format",
    "glossary",
    "highlight_policy",
    "highlight_terms",
)
CLIENT_FLAG_FIELDS: tuple[str, ...] = ("cv_content_mode_cap", "cv_interactive_enabled")

# Prefiksy ostrzeżeń, którymi model zgłasza pominiętą instrukcję klienta
# (prompt PL/EN) — sygnał zwrotny dla DL liczy je per instrukcja.
_SKIPPED_PREFIXES = ("Pominięto instrukcję klienta:", "Skipped client instruction:")
_POLICY_PREFIX = "WERYFIKUJ: domknięto politykę prezentacji klienta w kodzie:"


class GlossaryEntry(BaseModel):
    kind: Literal["role_translation"] = "role_translation"
    from_: str = Field(alias="from", min_length=1, max_length=80)
    to: str = Field(min_length=1, max_length=80)

    model_config = {"populate_by_name": True}


class ClientCvRulePayload(BaseModel):
    """Wejście edycji reguły. Wszystkie pola opcjonalne — pusty wzór znaczy
    „ten klient nie ma własnej nazwy pliku", nie „błąd"."""

    @model_validator(mode="after")
    def _safe_aliases_for_publication(self) -> "ClientCvRulePayload":
        if self.confirm and any(
            resolve_alias(entry.from_, entry.to) is None for entry in self.glossary
        ):
            raise ValueError(
                "Słownik zawiera niedozwoloną zamianę. Wybierz tłumaczenie "
                "stanowiska z katalogu albo usuń wpis przed publikacją."
            )
        return self

    highlight_policy: Literal[
        "none", "technologies", "must", "must_nice", "explicit"
    ] = "technologies"
    highlight_terms: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _explicit_highlights_for_publication(self) -> "ClientCvRulePayload":
        if (
            self.confirm
            and self.highlight_policy == "explicit"
            and not self.highlight_terms
        ):
            raise ValueError(
                "Podaj technologie do wyróżnienia albo wybierz brak wyróżnień."
            )
        return self

    @field_validator("highlight_terms")
    @classmethod
    def _highlight_terms(cls, terms: list[str]) -> list[str]:
        if any(not term.strip() or len(term.strip()) > 80 for term in terms):
            raise ValueError("Wyróżniane technologie muszą mieć od 1 do 80 znaków.")
        return list(dict.fromkeys(term.strip() for term in terms))

    expected_revision: Optional[int] = Field(default=None, ge=0)
    filename_pattern: Optional[str] = Field(default=None, max_length=300)
    spaces_to_underscores: bool = False
    cv_language: Optional[str] = Field(default=None)
    requires_en_copy: bool = False
    requires_rodo_consent_block: bool = False
    notes: Optional[str] = Field(
        default=None, max_length=GENERATOR_INSTRUCTIONS_MAX_LENGTH
    )
    # Instrukcje dla generatora AI — pola, które trafiają do promptu.
    generator_instructions: Optional[str] = Field(
        default=None, max_length=GENERATOR_INSTRUCTIONS_MAX_LENGTH
    )
    generator_instructions_en: Optional[str] = Field(
        default=None, max_length=GENERATOR_INSTRUCTIONS_MAX_LENGTH
    )
    # ── Blokady ─────────────────────────────────────────────────────────
    content_mode: Optional[str] = None
    content_mode_locked: bool = False
    require_screening_notes_min_chars: Optional[int] = Field(
        default=None, ge=0, le=20000
    )
    require_project_ref: bool = False
    require_position: bool = False
    require_champion: bool = False
    auto_second_language: bool = False
    # ── Polityka prezentacji ────────────────────────────────────────────
    omit_sections: list[str] = Field(default_factory=list, max_length=len(SECTION_KEYS))
    max_roles: Optional[int] = Field(default=None, ge=1, le=30)
    max_bullets_per_role: Optional[int] = Field(default=None, ge=1, le=20)
    max_bullet_chars: Optional[int] = Field(default=None, ge=40, le=600)
    why_points_max: Optional[int] = Field(default=None, ge=1, le=12)
    date_format: Optional[str] = None
    glossary: list[GlossaryEntry] = Field(default_factory=list, max_length=50)
    # ── Flagi klienta prowadzone z tego samego ekranu ──────────────────
    # `None` = nie ruszaj. Zapisywane na `clients`, żeby generator, publiczny
    # link i sufit działały bez zmian — a Delivery Lead miał jeden ekran.
    cv_content_mode_cap: Optional[str] = None
    cv_interactive_enabled: Optional[bool] = None
    # Zatwierdź tym samym zapisem. Osobne kliknięcie „Zatwierdź" chroniło
    # PROPOZYCJE z seeda (dopasowane po nazwie, więc możliwie błędne). Reguła,
    # którą Delivery Lead właśnie wpisał ręcznie, JEST jego decyzją.
    confirm: bool = False

    @field_validator("cv_language")
    @classmethod
    def _known_language(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        if value not in ("pl", "en"):
            raise ValueError("Język CV może być tylko „pl” albo „en”.")
        return value

    @field_validator("content_mode", "cv_content_mode_cap")
    @classmethod
    def _known_mode(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        if value not in CONTENT_MODES:
            raise ValueError(
                "Tryb obróbki treści może być tylko: " + ", ".join(CONTENT_MODES) + "."
            )
        return value

    @field_validator("date_format")
    @classmethod
    def _known_date_format(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        if value not in DATE_FORMATS:
            raise ValueError(
                "Format dat może być tylko: " + ", ".join(DATE_FORMATS) + "."
            )
        return value

    @field_validator("omit_sections")
    @classmethod
    def _known_sections(cls, value: list[str]) -> list[str]:
        unknown = sorted({v for v in value if v not in SECTION_KEYS})
        if unknown:
            raise ValueError(
                "Nieznane sekcje: "
                + ", ".join(unknown)
                + ". Dozwolone: "
                + ", ".join(SECTION_KEYS)
                + "."
            )
        # Kolejność katalogu, bez duplikatów — diff w historii ma być stabilny.
        return [key for key in SECTION_KEYS if key in value]

    @field_validator("notes", "generator_instructions", "generator_instructions_en")
    @classmethod
    def _blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("filename_pattern")
    @classmethod
    def _known_tokens(cls, value: Optional[str]) -> Optional[str]:
        """Odrzuć nieznany token ZANIM trafi do nazwy pliku.

        Bez tej walidacji literówka („{STANOWISKA}") przeszłaby przez zapis
        i wyszła dopiero na dokumencie wysłanym klientowi — jako dosłowny
        nawias klamrowy w nazwie pliku.
        """
        if not value or not value.strip():
            return None
        unknown = [
            tok
            for tok in re.findall(r"\{[A-Za-z_]+\}", value)
            if tok not in KNOWN_TOKENS
        ]
        if unknown:
            raise ValueError(
                "Nieznane pola we wzorze: "
                + ", ".join(sorted(set(unknown)))
                + ". Dozwolone: "
                + ", ".join(KNOWN_TOKENS)
                + "."
            )
        remainder = value
        for token in KNOWN_TOKENS:
            remainder = remainder.replace(token, "")
        if "{" in remainder or "}" in remainder:
            raise ValueError(
                "Nieprawidłowe nawiasy lub pole we wzorze nazwy pliku. "
                "Użyj pełnych pól, np. {STANOWISKO}_{IMIE_NAZWISKO}."
            )
        if "{IMIE_NAZWISKO}" not in value:
            raise ValueError(
                "Wzór musi zawierać pole {IMIE_NAZWISKO} w nawiasach klamrowych; "
                "inaczej generator nie może zastosować nazwy klienta. "
                "Pozostaw pole puste, aby użyć nazwy domyślnej."
            )
        return value.strip()


class ClientCvRuleRead(BaseModel):
    glossary_options: list[dict[str, str]] = Field(default_factory=alias_catalog)
    highlight_policy: str = "technologies"
    highlight_terms: list[str] = Field(default_factory=list)
    edit_revision: int = 0
    draft_payload: Optional[dict[str, Any]] = None
    client_id: int
    client_name: Optional[str] = None
    filename_pattern: Optional[str] = None
    spaces_to_underscores: bool = False
    cv_language: Optional[str] = None
    requires_en_copy: bool = False
    requires_rodo_consent_block: bool = False
    notes: Optional[str] = None
    generator_instructions: Optional[str] = None
    generator_instructions_en: Optional[str] = None
    content_mode: Optional[str] = None
    content_mode_locked: bool = False
    require_screening_notes_min_chars: Optional[int] = None
    require_project_ref: bool = False
    require_position: bool = False
    require_champion: bool = False
    auto_second_language: bool = False
    omit_sections: list[str] = Field(default_factory=list)
    max_roles: Optional[int] = None
    max_bullets_per_role: Optional[int] = None
    max_bullet_chars: Optional[int] = None
    why_points_max: Optional[int] = None
    date_format: Optional[str] = None
    glossary: list[dict[str, str]] = Field(default_factory=list)
    version: int = 1
    # Flagi z karty klienta — prowadzone z tego samego ekranu.
    cv_content_mode_cap: Optional[str] = None
    cv_interactive_enabled: bool = True
    seed_key: Optional[str] = None
    confirmed_at: Optional[str] = None
    confirmed_by_name: Optional[str] = None
    # Czy reguła OBOWIĄZUJE. Front nie może tego wyliczać z `confirmed_at` sam,
    # bo to jedyne miejsce, w którym „propozycja" i „reguła" się rozchodzą.
    is_active: bool = False
    # Opis polityki do banera w generatorze. Pusty string = klient wybrany, ale
    # bez zatwierdzonych reguł; `null` = brak wiersza w ogóle.
    client_policy: Optional[str] = None
    # Podgląd nazwy pliku na przykładowych danych — rekruter widzi skutek wzoru
    # zanim cokolwiek wygeneruje.
    filename_preview: Optional[str] = None


class ClientCvRuleListItem(ClientCvRuleRead):
    """Wiersz przeglądu zbiorczego: reguła + szablon Championa, z którego
    została zasiana (pusty dla reguł założonych ręcznie)."""

    template_label: Optional[str] = None
    template_url: Optional[str] = None
    updated_at: Optional[str] = None


class UnassignedChampionTemplate(BaseModel):
    """Szablon Championa BEZ wiersza reguły — seed nie zasiał go, bo nazwa
    klienta pasowała do zera albo do wielu rekordów."""

    seed_key: str
    label: str
    template_url: Optional[str] = None


class CvRulesOverview(BaseModel):
    rules: list[ClientCvRuleListItem]
    unassigned_templates: list[UnassignedChampionTemplate]


class RuleEventRead(BaseModel):
    id: int
    rule_version: int
    action: str
    changes: dict[str, Any] = Field(default_factory=dict)
    actor_name: Optional[str] = None
    created_at: Optional[str] = None


class SkippedInstructionStat(BaseModel):
    text: str
    count: int


class FeedbackGeneratedItem(BaseModel):
    id: int
    candidate_name: str
    language: str
    content_mode: str
    created_at: Optional[str] = None
    created_by_name: Optional[str] = None
    client_rule_version: Optional[int] = None
    skipped: list[str] = Field(default_factory=list)
    policy_enforced: bool = False


class RuleFeedback(BaseModel):
    days: int
    generated_total: int
    with_skipped_instructions: int
    with_policy_enforced: int
    skipped_by_instruction: list[SkippedInstructionStat]
    recent: list[FeedbackGeneratedItem]


class LintRequest(BaseModel):
    generator_instructions: Optional[str] = Field(
        default=None, max_length=GENERATOR_INSTRUCTIONS_MAX_LENGTH
    )
    generator_instructions_en: Optional[str] = Field(
        default=None, max_length=GENERATOR_INSTRUCTIONS_MAX_LENGTH
    )
    notes: Optional[str] = Field(
        default=None, max_length=GENERATOR_INSTRUCTIONS_MAX_LENGTH
    )


class LintFindingRead(BaseModel):
    field: str
    index: int
    line: str
    verdict: str
    reason: str
    suggestion: str


class LintResponse(BaseModel):
    findings: list[LintFindingRead]
    ok_count: int
    adds_facts_count: int
    unclear_count: int


class PromptPreview(BaseModel):
    language: str
    block: str
    is_active: bool


class PreviewRequest(BaseModel):
    cv_document_id: int | None = Field(default=None, ge=1)
    candidate_id: int = Field(..., ge=1)
    stage_id: int = Field(..., ge=1)
    language: Literal["pl", "en"] = "pl"


class RuleFeedbackItem(BaseModel):
    field: str
    label: str
    status: Literal[
        "satisfied", "not_applicable", "conflict", "needs_review", "skipped"
    ]


class PreviewVariant(BaseModel):
    rule_feedback: list[RuleFeedbackItem] = Field(default_factory=list)
    can_download: bool = False
    docx_sha256: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    warnings: list[str] = Field(default_factory=list)
    filename: Optional[str] = None


class PreviewRead(BaseModel):
    id: int
    client_id: int
    candidate_id: Optional[int] = None
    stage_id: Optional[int] = None
    language: str
    status: str
    error_message: Optional[str] = None
    prompt_block: Optional[str] = None
    with_rule: Optional[PreviewVariant] = None
    without_rule: Optional[PreviewVariant] = None
    created_at: Optional[str] = None


_PREVIEW_POSITION = "Analityk Biznesowy"
_PREVIEW_NAME = "Jan Kowalski"
_PREVIEW_PROJECT = "4521"

_CLIENT_DISPLAY_NAME = func.coalesce(
    func.nullif(func.trim(Client.display_name), ""), Client.name
)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _preview(rule: Optional[ClientCvRule]) -> Optional[str]:
    result = build_filename(
        snapshot_rule(rule),
        position=_PREVIEW_POSITION,
        candidate_name=_PREVIEW_NAME,
        project=_PREVIEW_PROJECT,
    )
    return result.filename if result else None


def _to_read(
    rule: Optional[ClientCvRule],
    *,
    client: Client | None,
    client_id: int,
    client_name: Optional[str],
    confirmed_by_name: Optional[str] = None,
) -> ClientCvRuleRead:
    flags = {
        "cv_content_mode_cap": getattr(client, "cv_content_mode_cap", None),
        "cv_interactive_enabled": bool(getattr(client, "cv_interactive_enabled", True)),
    }
    if rule is None:
        return ClientCvRuleRead(
            client_id=client_id,
            client_name=client_name,
            client_policy=None,
            edit_revision=int(getattr(client, "cv_rule_edit_revision", 0) or 0),
            **flags,
        )
    active = rule.confirmed_at is not None
    snap = snapshot_rule(rule)
    return ClientCvRuleRead(
        client_id=client_id,
        client_name=client_name,
        filename_pattern=rule.filename_pattern,
        spaces_to_underscores=bool(rule.spaces_to_underscores),
        cv_language=rule.cv_language,
        requires_en_copy=bool(rule.requires_en_copy),
        requires_rodo_consent_block=bool(rule.requires_rodo_consent_block),
        notes=rule.notes,
        generator_instructions=rule.generator_instructions,
        generator_instructions_en=rule.generator_instructions_en,
        content_mode=rule.content_mode,
        content_mode_locked=bool(rule.content_mode_locked),
        require_screening_notes_min_chars=rule.require_screening_notes_min_chars,
        require_project_ref=bool(rule.require_project_ref),
        require_position=bool(rule.require_position),
        require_champion=bool(rule.require_champion),
        auto_second_language=bool(rule.auto_second_language),
        omit_sections=list(snap.omit_sections) if snap else [],
        max_roles=rule.max_roles,
        max_bullets_per_role=rule.max_bullets_per_role,
        max_bullet_chars=rule.max_bullet_chars,
        why_points_max=rule.why_points_max,
        date_format=rule.date_format,
        glossary=[
            {"from": src, "to": dst} for src, dst in (snap.glossary if snap else ())
        ],
        version=int(rule.version or 1),
        highlight_policy=rule.highlight_policy or "technologies",
        highlight_terms=list(rule.highlight_terms or []),
        edit_revision=int(rule.edit_revision or 1),
        draft_payload=rule.draft_payload,
        seed_key=rule.seed_key,
        confirmed_at=_iso(rule.confirmed_at),
        confirmed_by_name=confirmed_by_name,
        is_active=active,
        # Niezatwierdzona reguła NIE opisuje polityki — generator jej nie zna,
        # więc twierdzenie „zastosowano" byłoby nieprawdą.
        client_policy=describe_rule(snap) if active else "",
        filename_preview=_preview(rule) if active else None,
        **flags,
    )


async def _client_or_404(db: AsyncSession, client_id: int) -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Klient nie został znaleziony.")
    return client


def _require_shared_rule_section_read(user: User) -> None:
    """Allow the Job/Pipeline consumer without opening the Delivery module.

    A recruiter needs the client's confirmed CV recipe while working on an
    assigned Job.  That narrow read is therefore admitted by either Pipeline
    or Delivery; the client graph is checked separately below.  All management
    endpoints keep the ordinary Delivery section dependency.
    """

    granted = max(
        section_access_for_user(user, ProductSection.delivery),
        section_access_for_user(user, ProductSection.pipeline),
    )
    if granted < SectionAccess.read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "section_access_denied",
                "section": ProductSection.delivery.value,
                "required": SectionAccess.read.name,
                "granted": granted.name,
            },
        )


async def _require_client_rule_access(
    db: AsyncSession,
    user: User,
    client_id: int,
    *,
    write: bool,
) -> None:
    """Enforce the authoritative client graph below the section ceiling."""

    access = await resolve_client_access(db, user, client_id)
    allowed = access.can_edit_knowledge if write else access.can_view_knowledge
    if not allowed:
        action = "edycja" if write else "odczyt"
        raise deny(f"{action} reguł CV klienta jest niedozwolony")


def _client_label(client: Client) -> str:
    return (client.display_name or "").strip() or client.name


async def _rule_for(db: AsyncSession, client_id: int) -> Optional[ClientCvRule]:
    return (
        await db.execute(
            select(ClientCvRule).where(ClientCvRule.client_id == client_id)
        )
    ).scalar_one_or_none()


def _rule_state(rule: Optional[ClientCvRule], client: Client) -> dict[str, Any]:
    """Migawka pól objętych diffem — do porównania przed/po zapisie."""
    state: dict[str, Any] = {}
    for field in RULE_FIELDS:
        value = getattr(rule, field, None) if rule is not None else None
        if field in ("omit_sections", "glossary", "highlight_terms"):
            value = list(value or [])
        if field == "highlight_policy":
            value = value or "technologies"
        state[field] = value
    for field in CLIENT_FLAG_FIELDS:
        state[field] = getattr(client, field, None)
    return state


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: {"from": before.get(key), "to": after.get(key)}
        for key in after
        if before.get(key) != after.get(key)
    }


async def _next_version(db: AsyncSession, client_id: int) -> int:
    """Pierwsza wersja NOWEGO wiersza reguły = max z historii klienta + 1.

    Usunięcie i ponowne założenie reguły nie może zacząć numeracji od 1:
    historia trzyma stare v1..vN, a wygenerowane CV noszą stempel
    `client_rule_version` — dwie różne treści pod tym samym numerem
    zamieniłyby stempel w zgadywankę.
    """
    last = await db.scalar(
        select(func.max(ClientCvRuleEvent.rule_version)).where(
            ClientCvRuleEvent.client_id == client_id
        )
    )
    return int(last or 0) + 1


def _record_event(
    db: AsyncSession,
    *,
    client_id: int,
    version: int,
    action: str,
    changes: Optional[dict[str, Any]],
    actor: User,
) -> None:
    db.add(
        ClientCvRuleEvent(
            client_id=client_id,
            rule_version=version,
            action=action,
            changes=changes or None,
            actor_user_id=actor.id,
            actor_name=actor.name,
        )
    )


def _apply_payload(rule: ClientCvRule, payload: ClientCvRulePayload) -> None:
    rule.highlight_policy = payload.highlight_policy
    rule.highlight_terms = list(payload.highlight_terms) or None
    rule.filename_pattern = payload.filename_pattern
    rule.spaces_to_underscores = payload.spaces_to_underscores
    rule.cv_language = payload.cv_language
    rule.requires_en_copy = payload.requires_en_copy
    rule.requires_rodo_consent_block = payload.requires_rodo_consent_block
    rule.notes = payload.notes
    rule.generator_instructions = payload.generator_instructions
    rule.generator_instructions_en = payload.generator_instructions_en
    rule.content_mode = payload.content_mode
    rule.content_mode_locked = bool(
        payload.content_mode and payload.content_mode_locked
    )
    rule.require_screening_notes_min_chars = (
        payload.require_screening_notes_min_chars or None
    )
    rule.require_project_ref = payload.require_project_ref
    rule.require_position = payload.require_position
    rule.require_champion = payload.require_champion
    rule.auto_second_language = payload.auto_second_language
    rule.omit_sections = list(payload.omit_sections) or None
    rule.max_roles = payload.max_roles
    rule.max_bullets_per_role = payload.max_bullets_per_role
    rule.max_bullet_chars = payload.max_bullet_chars
    rule.why_points_max = payload.why_points_max
    rule.date_format = payload.date_format
    rule.glossary = [
        {"kind": entry.kind, "from": entry.from_.strip(), "to": entry.to.strip()}
        for entry in payload.glossary
    ] or None


def _validated_recipe(
    recipe: dict[str, Any], *, confirm: bool = False
) -> ClientCvRulePayload:
    try:
        return ClientCvRulePayload(**recipe, confirm=confirm)
    except ValidationError as error:
        raise HTTPException(
            status_code=422,
            detail="Reguła wymaga poprawienia przed publikacją lub podglądem: "
            + error.errors()[0]["msg"],
        ) from error


def _editable_rule(rule: ClientCvRule | None) -> ClientCvRule | None:
    if rule is None or not rule.draft_payload:
        return rule
    draft = ClientCvRule(version=rule.version)
    _apply_payload(draft, _validated_recipe(rule.draft_payload))
    return draft


async def _lock_rule_edit(
    db: AsyncSession, client: Client, expected_revision: int | None
) -> ClientCvRule | None:
    # Lock the parent too: two concurrent first saves must not race the UNIQUE FK.
    await db.execute(select(Client.id).where(Client.id == client.id).with_for_update())
    await db.refresh(client)
    rule = await _rule_for(db, client.id)
    actual = max(
        int(getattr(client, "cv_rule_edit_revision", 0) or 0),
        int(rule.edit_revision or 1) if rule is not None else 0,
    )
    if expected_revision is None or expected_revision != actual:
        raise HTTPException(
            status_code=409,
            detail="Reguła została zmieniona lub formularz nie ma aktualnej wersji. "
            "Odśwież regułę i porównaj zmiany przed ponownym zapisem.",
        )
    return rule


def _recipe_payload(payload: ClientCvRulePayload, client: Client) -> dict[str, Any]:
    recipe = payload.model_dump(
        by_alias=True, include=set(RULE_FIELDS + CLIENT_FLAG_FIELDS)
    )
    # Omitted flags retain their effective value; explicit null clears the cap.
    if "cv_content_mode_cap" not in payload.model_fields_set:
        recipe["cv_content_mode_cap"] = client.cv_content_mode_cap
    if payload.cv_interactive_enabled is None:
        recipe["cv_interactive_enabled"] = bool(client.cv_interactive_enabled)
    return recipe


async def _store_recipe(
    db: AsyncSession,
    client: Client,
    rule: ClientCvRule | None,
    payload: ClientCvRulePayload,
    actor: User,
    *,
    action: str | None = None,
    event_context: dict[str, Any] | None = None,
) -> ClientCvRule:
    if rule is None:
        rule = ClientCvRule(
            client_id=client.id,
            edit_revision=int(getattr(client, "cv_rule_edit_revision", 0) or 0),
        )
        rule.version = await _next_version(db, client.id)
        db.add(rule)
    was_active = rule.confirmed_at is not None
    effective_before = _rule_state(rule, client)
    edit_before = rule.draft_payload or effective_before
    recipe = _recipe_payload(payload, client)
    if payload.confirm:
        _apply_payload(rule, payload)
        for field in CLIENT_FLAG_FIELDS:
            setattr(client, field, recipe[field])
        effective_after = _rule_state(rule, client)
        changes = _diff(effective_before, effective_after)
        if was_active and changes:
            rule.version = int(rule.version or 1) + 1
        if not was_active or changes:
            rule.confirmed_at = datetime.now(timezone.utc)
            rule.confirmed_by = actor.id
            db.add(
                ClientCvRulePublication(
                    client_id=client.id,
                    version=rule.version,
                    recipe=effective_after,
                    published_at=rule.confirmed_at,
                    published_by=actor.id,
                )
            )
        rule.draft_payload = None
    else:
        rule.draft_payload = recipe
        # Legacy readers may display never-published proposals, but runtime still
        # rejects them through confirmed_at. Never touch the live client flags.
        if not was_active:
            _apply_payload(rule, payload)
        changes = _diff(edit_before, recipe)
    rule.edit_revision = (
        max(
            int(rule.edit_revision or 0),
            int(getattr(client, "cv_rule_edit_revision", 0) or 0),
        )
        + 1
    )
    client.cv_rule_edit_revision = rule.edit_revision
    await db.flush()
    _record_event(
        db,
        client_id=client.id,
        version=int(rule.version or 1),
        action=action or ("saved_and_confirmed" if payload.confirm else "saved"),
        changes={**changes, **(event_context or {})},
        actor=actor,
    )
    await db.commit()
    await db.refresh(rule)
    return rule


# ── Odczyt / zapis / zatwierdzanie / usuwanie ────────────────────────────────


@router.get("/clients/{client_id}/cv-rule", response_model=ClientCvRuleRead)
async def get_client_cv_rule(
    client_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> ClientCvRuleRead:
    """Reguła CV klienta — także niezatwierdzona.

    Jest to wąski odczyt współdzielony przez Delivery i Pipeline. Rekruter
    zobaczy regułę wyłącznie klienta osiągalnego przez przypisany Job;
    Delivery Lead każdego klienta.
    """
    client = await _client_or_404(db, client_id)
    _require_shared_rule_section_read(current_user)
    await _require_client_rule_access(db, current_user, client.id, write=False)
    rule = await _rule_for(db, client.id)
    confirmed_by_name = None
    if rule is not None and rule.confirmed_by:
        confirmed_by_name = await db.scalar(
            select(User.name).where(User.id == rule.confirmed_by)
        )
    return _to_read(
        rule,
        client=client,
        client_id=client.id,
        client_name=_client_label(client),
        confirmed_by_name=confirmed_by_name,
    )


@router.put("/clients/{client_id}/cv-rule", response_model=ClientCvRuleRead)
async def upsert_client_cv_rule(
    client_id: int,
    payload: ClientCvRulePayload,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> ClientCvRuleRead:
    """Save an independent draft, or atomically publish the complete recipe."""
    client = await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client.id, write=True)
    rule = await _lock_rule_edit(db, client, payload.expected_revision)
    rule = await _store_recipe(db, client, rule, payload, current_user)
    return _to_read(
        rule,
        client=client,
        client_id=client.id,
        client_name=_client_label(client),
        confirmed_by_name=current_user.name if payload.confirm else None,
    )


@router.post("/clients/{client_id}/cv-rule/confirm", response_model=ClientCvRuleRead)
async def confirm_client_cv_rule(
    client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
    expected_revision: Optional[int] = Query(None, ge=0),
) -> ClientCvRuleRead:
    """Publish the saved draft and its client flags as one version."""
    client = await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client.id, write=True)
    rule = await _lock_rule_edit(db, client, expected_revision)
    if rule is None:
        raise HTTPException(status_code=404, detail="Najpierw zapisz regułę CV.")
    payload = _validated_recipe(
        rule.draft_payload or _rule_state(rule, client), confirm=True
    )
    rule = await _store_recipe(
        db, client, rule, payload, current_user, action="confirmed"
    )
    return _to_read(
        rule,
        client=client,
        client_id=client.id,
        client_name=_client_label(client),
        confirmed_by_name=current_user.name,
    )


@router.delete("/clients/{client_id}/cv-rule", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client_cv_rule(
    client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
    expected_revision: Optional[int] = Query(None, ge=0),
) -> None:
    """Usuń regułę — klient wraca do globalnej nazwy pliku i wolnego wyboru
    języka. Historia zostaje (FK po kliencie, nie po regule)."""
    client = await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client.id, write=True)
    rule = await _lock_rule_edit(db, client, expected_revision)
    if rule is not None:
        _record_event(
            db,
            client_id=client.id,
            version=int(rule.version or 1),
            action="deleted",
            changes={
                "cv_content_mode_cap": {"from": client.cv_content_mode_cap, "to": None},
                "cv_interactive_enabled": {
                    "from": client.cv_interactive_enabled,
                    "to": True,
                },
            },
            actor=current_user,
        )
        client.cv_content_mode_cap = None
        client.cv_interactive_enabled = True
        client.cv_rule_edit_revision = (
            max(
                int(rule.edit_revision or 0),
                int(getattr(client, "cv_rule_edit_revision", 0) or 0),
            )
            + 1
        )
        await db.delete(rule)
        await db.commit()


@router.post(
    "/clients/{client_id}/cv-rule/copy-from/{source_client_id}",
    response_model=ClientCvRuleRead,
)
async def copy_client_cv_rule(
    client_id: int,
    source_client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
    expected_revision: Optional[int] = Query(None, ge=0),
) -> ClientCvRuleRead:
    """Skopiuj treść reguły z innego klienta — jako PROPOZYCJĘ.

    Banki chcą podobnych rzeczy; jeden klik zamiast przepisywania. Kopia nie
    jest zatwierdzana automatycznie: skopiowana nazwa pliku „B2B_PANSA_…"
    u innego klienta jest dokładnie tą pomyłką, przed którą chroni krok
    zatwierdzenia. Flagi karty klienta (sufit, interaktywne CV) NIE są
    kopiowane — to obietnice złożone konkretnemu klientowi.
    """
    if client_id == source_client_id:
        raise HTTPException(
            status_code=422, detail="Wskaż innego klienta niż docelowy."
        )
    client = await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client.id, write=True)
    source_client = await _client_or_404(db, source_client_id)
    await _require_client_rule_access(db, current_user, source_client.id, write=False)
    source = await _rule_for(db, source_client.id)
    if source is None:
        raise HTTPException(
            status_code=404, detail="Klient źródłowy nie ma reguły CV do skopiowania."
        )
    rule = await _lock_rule_edit(db, client, expected_revision)
    recipe = _rule_state(source, client)
    # Copy only rule fields; flags remain those of the target client.
    payload = _validated_recipe(recipe)
    rule = await _store_recipe(
        db,
        client,
        rule,
        payload,
        current_user,
        action="copied",
        event_context={"source_client_id": source_client.id},
    )
    return _to_read(
        rule, client=client, client_id=client.id, client_name=_client_label(client)
    )


@router.get("/clients/{client_id}/cv-rule/versions")
async def list_cv_rule_versions(
    client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client_id, write=False)
    rows = (
        await db.scalars(
            select(ClientCvRulePublication)
            .where(ClientCvRulePublication.client_id == client_id)
            .order_by(ClientCvRulePublication.version.desc())
        )
    ).all()
    return [
        {"version": row.version, "published_at": _iso(row.published_at)} for row in rows
    ]


@router.post(
    "/clients/{client_id}/cv-rule/versions/{version}/restore",
    response_model=ClientCvRuleRead,
)
async def restore_cv_rule_version(
    client_id: int,
    version: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
    expected_revision: Optional[int] = Query(None, ge=0),
) -> ClientCvRuleRead:
    """Restore an immutable publication into a draft, never silently activate it."""
    client = await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client_id, write=True)
    rule = await _lock_rule_edit(db, client, expected_revision)
    publication = await db.get(ClientCvRulePublication, (client_id, version))
    if publication is None:
        raise HTTPException(
            status_code=404, detail="Nie znaleziono opublikowanej wersji."
        )
    payload = _validated_recipe(publication.recipe)
    rule = await _store_recipe(
        db,
        client,
        rule,
        payload,
        current_user,
        action="restored",
        event_context={"restored_version": version},
    )
    return _to_read(
        rule, client=client, client_id=client.id, client_name=_client_label(client)
    )


# ── Historia, sygnał zwrotny, lint, podgląd promptu, CV próbne ──────────────


@router.get("/clients/{client_id}/cv-rule/history", response_model=list[RuleEventRead])
async def client_cv_rule_history(
    client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[RuleEventRead]:
    await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client_id, write=False)
    rows = (
        await db.scalars(
            select(ClientCvRuleEvent)
            .where(ClientCvRuleEvent.client_id == client_id)
            .order_by(ClientCvRuleEvent.created_at.desc(), ClientCvRuleEvent.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        RuleEventRead(
            id=e.id,
            rule_version=e.rule_version,
            action=e.action,
            changes=dict(e.changes or {}),
            actor_name=e.actor_name,
            created_at=_iso(e.created_at),
        )
        for e in rows
    ]


def _skipped_from_warnings(warnings: list[str] | None) -> tuple[list[str], bool]:
    skipped: list[str] = []
    policy = False
    for raw in warnings or []:
        text = str(raw).strip()
        for prefix in _SKIPPED_PREFIXES:
            if text.startswith(prefix):
                skipped.append(text[len(prefix) :].strip(" .„”\"'"))
                break
        if text.startswith(_POLICY_PREFIX):
            policy = True
    return skipped, policy


@router.get("/clients/{client_id}/cv-rule/feedback", response_model=RuleFeedback)
async def client_cv_rule_feedback(
    client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(90, ge=1, le=365),
) -> RuleFeedback:
    """Co model pomijał, a co kod domykał — per instrukcja, z ostatnich N dni.

    Instrukcja pomijana w co drugim CV to instrukcja do przepisania. Bez tej
    listy DL widzi wyłącznie pojedyncze ostrzeżenia u rekruterów, którzy nie
    mają powodu ich zgłaszać.
    """
    await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client_id, write=False)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(CvGeneratedDocument, User.name)
            .outerjoin(User, User.id == CvGeneratedDocument.created_by)
            .where(
                CvGeneratedDocument.client_id == client_id,
                CvGeneratedDocument.status == "ready",
                CvGeneratedDocument.created_at >= since,
            )
            .order_by(CvGeneratedDocument.created_at.desc())
            .limit(500)
        )
    ).all()
    counts: dict[str, int] = {}
    with_skipped = 0
    with_policy = 0
    recent: list[FeedbackGeneratedItem] = []
    for doc, creator in rows:
        skipped, policy = _skipped_from_warnings(doc.warnings)
        if skipped:
            with_skipped += 1
            for text in skipped:
                counts[text] = counts.get(text, 0) + 1
        if policy:
            with_policy += 1
        if len(recent) < 20:
            recent.append(
                FeedbackGeneratedItem(
                    id=doc.id,
                    candidate_name=doc.candidate_name,
                    language=doc.language,
                    content_mode=doc.content_mode,
                    created_at=_iso(doc.created_at),
                    created_by_name=creator,
                    client_rule_version=doc.client_rule_version,
                    skipped=skipped,
                    policy_enforced=policy,
                )
            )
    stats = sorted(
        (SkippedInstructionStat(text=t, count=c) for t, c in counts.items()),
        key=lambda s: (-s.count, s.text),
    )
    return RuleFeedback(
        days=days,
        generated_total=len(rows),
        with_skipped_instructions=with_skipped,
        with_policy_enforced=with_policy,
        skipped_by_instruction=stats,
        recent=recent,
    )


@router.post("/clients/{client_id}/cv-rule/lint", response_model=LintResponse)
async def lint_client_cv_rule(
    client_id: int,
    payload: LintRequest,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> LintResponse:
    """Oceń instrukcje linia po linii ZANIM trafią do reguły.

    Kwota ``cv_rule_lint`` naliczana przed wywołaniem modelu (jak wszędzie —
    decyzja o dopuszczeniu, nie sukces round-tripu). Lint jest opinią: nie
    blokuje zapisu, tylko pokazuje granicę wcześniej.
    """
    from app.services.cv_generator_b2b.rule_lint import lint_instructions

    await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client_id, write=True)
    fields = [
        ("generator_instructions", payload.generator_instructions),
        ("generator_instructions_en", payload.generator_instructions_en),
        ("notes", payload.notes),
    ]
    fields = [(name, text) for name, text in fields if (text or "").strip()]
    if not fields:
        return LintResponse(
            findings=[], ok_count=0, adds_facts_count=0, unclear_count=0
        )
    request_id = f"cvlint_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    findings: list[LintFindingRead] = []
    try:
        # Jedno pole = jedno obciążenie (kontrakt billingowy: per pole, NIE jeden
        # batch N jednostek). Naliczamy WSZYSTKIE pola PRZED jakimkolwiek
        # wywołaniem modelu: jeśli limit skończy się na którymś polu,
        # check_and_increment rzuca AIQuotaExceeded, łapie to `except` niżej,
        # a rollback cofa naliczenia — Delivery Lead dostaje pełną ocenę albo
        # czyste 503, nigdy połowy. Błąd modelu PO naliczeniu nie zwraca kwoty
        # (liczymy decyzję o dopuszczeniu, nie sukces round-tripu).
        #
        # check_and_increment bezpośrednio + wywołanie modelu w `declared_call`,
        # a nie `ai_feature`: (1) `ai_feature` zdedupikowałby N wywołań tej samej
        # cechy do jednego obciążenia, (2) pod AI_QUOTA_STRICT niezadeklarowane
        # wywołanie dolatuje do granicy dostawcy jako UNGATED — declared_call
        # deklaruje już-naliczone wywołanie na czas swojego bloku (contextvar
        # kopiowany do wątku run_in_threadpool).
        charged: list[tuple[str, str, QuotaState]] = []
        for name, text in fields:
            state = await check_and_increment(
                db, AIFeatureKey.cv_rule_lint, user_id=current_user.id
            )
            charged.append((name, text or "", state))
        await db.commit()
        for name, text, state in charged:
            try:
                with declared_call(
                    AIFeatureKey.cv_rule_lint, user_id=current_user.id, state=state
                ):
                    results = await run_in_threadpool(
                        lint_instructions,
                        text,
                        request_id=f"{request_id}_{name}",
                    )
            except HTTPException:
                raise
            except Exception as err:  # noqa: BLE001 — lint nie wywraca edytora
                logger.warning("[cv_rule_lint] %s failed: %s", name, err)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Nie udało się ocenić instrukcji — spróbuj za chwilę.",
                ) from err
            findings.extend(
                LintFindingRead(
                    field=name,
                    index=f.index,
                    line=f.line,
                    verdict=f.verdict,
                    reason=f.reason,
                    suggestion=f.suggestion,
                )
                for f in results
            )
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "feature": exc.feature.value,
                "reason": exc.reason,
                "used": exc.used,
                "limit": exc.limit,
            },
        ) from exc
    return LintResponse(
        findings=findings,
        ok_count=sum(1 for f in findings if f.verdict == "ok"),
        adds_facts_count=sum(1 for f in findings if f.verdict == "adds_facts"),
        unclear_count=sum(1 for f in findings if f.verdict == "unclear"),
    )


@router.get("/clients/{client_id}/cv-rule/prompt-preview", response_model=PromptPreview)
async def client_cv_rule_prompt_preview(
    client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
    language: Literal["pl", "en"] = Query("pl"),
) -> PromptPreview:
    """Dokładny blok, jaki dostanie model — bez tajemnic. Pokazuje stan
    ZAPISANY (także niezatwierdzony), z zaznaczeniem, czy obowiązuje."""
    await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client_id, write=False)
    rule = await _rule_for(db, client_id)
    return PromptPreview(
        language=language,
        block=build_prompt_blocks(snapshot_rule(_editable_rule(rule)), language),
        is_active=bool(
            rule is not None
            and rule.confirmed_at is not None
            and not rule.draft_payload
        ),
    )


def _variant(value: Optional[dict]) -> Optional[PreviewVariant]:
    if not value:
        return None
    return PreviewVariant(
        rule_feedback=value.get("rule_feedback") or [],
        can_download=bool(value.get("docx_sha256")),
        docx_sha256=value.get("docx_sha256"),
        payload=value.get("payload"),
        warnings=list(value.get("warnings") or []),
        filename=value.get("filename"),
    )


def _preview_read(row: ClientCvRulePreview, *, durable: bool = False) -> PreviewRead:
    status_value = row.status
    error_message = row.error_message
    if (
        status_value == "processing"
        and not durable
        and row.created_at is not None
        and datetime.now(timezone.utc) - row.created_at > PREVIEW_STALE_AFTER
    ):
        status_value = "failed"
        error_message = (
            "Podgląd nie zakończył się w 15 minut (restart serwera w trakcie?) "
            "— uruchom go ponownie."
        )
    return PreviewRead(
        id=row.id,
        client_id=row.client_id,
        candidate_id=row.candidate_id,
        stage_id=row.stage_id,
        language=row.language,
        status=status_value,
        error_message=error_message,
        prompt_block=row.prompt_block,
        with_rule=_variant(row.with_rule),
        without_rule=_variant(row.without_rule),
        created_at=_iso(row.created_at),
    )


async def _mark_preview_failed(db: AsyncSession, preview_id: int, message: str) -> None:
    """Zapisz porażkę PO rollbacku — sesja po błędzie bazy w trakcie generacji
    jest w stanie, w którym `commit()` sam rzuca, a wiersz zostałby
    „processing" na zawsze."""
    await db.rollback()
    from app.services.cv_generator_b2b.job_leases import lock_owned_job

    await lock_owned_job(db)
    row = await db.get(ClientCvRulePreview, preview_id)
    if row is None:
        return
    row.status = "failed"
    row.error_message = message[:1000]
    await db.commit()


# Podgląd „processing" starszy niż to okno to zadanie zabite w locie (Coolify
# restartuje kontener przy każdym pushu) — pokazujemy je jako awarię, żeby
# przycisk i odpytywanie nie wisiały w nieskończoność.
PREVIEW_STALE_AFTER = timedelta(minutes=15)
# Podglądy niosą pełne CV kandydata — nie są dokumentami do wysłania, więc
# nie ma powodu trzymać ich dłużej niż kilka dni.
PREVIEW_RETENTION = timedelta(days=7)


async def _run_rule_preview_job(
    preview_id: int,
    *,
    client_id: int,
    candidate_id: int,
    stage_id: int,
    language: str,
    quota_state: "QuotaState | None" = None,
    quota_user_id: int | None = None,
    source: CandidateGenerationSource | None = None,
) -> None:
    """Dwie generacje w tle: z regułą (zapisaną, choćby niezatwierdzoną)
    i bez. Awaria którejkolwiek = wiersz „failed" z powodem; nic nie jest
    zapisywane w `cv_generated_documents`.

    `quota_state` pochodzi z naliczenia zrobionego w handlerze i służy WYŁĄCZNIE
    do zadeklarowania wywołania — `BackgroundTasks` biegnie po zamknięciu
    handlera, więc contextvar ustawiony przez `ai_feature` już nie żyje, a
    bramka na granicy dostawcy widziałaby te dwie generacje jako
    niezadeklarowane. Naliczenia tu NIE MA i być nie może: byłoby drugie.
    """
    declaration = (
        declared_call(
            AIFeatureKey.cv_generator, user_id=quota_user_id, state=quota_state
        )
        if quota_state is not None
        else nullcontext()
    )
    with declaration:
        await _run_rule_preview_job_inner(
            preview_id,
            client_id=client_id,
            candidate_id=candidate_id,
            stage_id=stage_id,
            language=language,
            source=source,
        )


async def _run_rule_preview_job_inner(
    preview_id: int,
    *,
    client_id: int,
    candidate_id: int,
    stage_id: int,
    language: str,
    source: CandidateGenerationSource | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(ClientCvRulePreview, preview_id)
        if row is None:
            return
        try:
            if row.recipe_snapshot is None:
                raise StandaloneGenerationError(
                    code="extraction_failed",
                    message="Podgląd nie ma zapisanej wersji reguły. Uruchom go ponownie.",
                )
            recipe = ClientCvRulePayload(**row.recipe_snapshot)
            frozen = ClientCvRule()
            _apply_payload(frozen, recipe)
            snap = snapshot_rule(frozen)
            source = source or await load_candidate_generation_source(
                db,
                candidate_id=candidate_id,
                stage_id=stage_id,
                language=language,
            )
            facts = await run_in_threadpool(
                prepare_source_facts,
                cv_bytes=source.cv_bytes,
                cv_filename=source.cv_filename,
                screening_notes_text=source.screening_notes_text,
                request_id=f"cv-rule-preview:{preview_id}:source",
            )
            with_rule = await generate_cv_from_candidate_source(
                source,
                prepared_source_facts=facts,
                language=language,  # type: ignore[arg-type]
                client_rule=snap,
                client_policy_override=row.recipe_snapshot,
            )
            without_rule = await generate_cv_from_candidate_source(
                source,
                prepared_source_facts=facts,
                language=language,  # type: ignore[arg-type]
                client_rule=None,
                client_policy_override={"cv_content_mode_cap": None},
            )
        except StandaloneGenerationError as err:
            await _mark_preview_failed(db, preview_id, err.message)
            return
        except Exception as err:  # noqa: BLE001 — job w tle nie może paść cicho
            logger.exception("[cv_rule_preview] job %s crashed: %s", preview_id, err)
            await _mark_preview_failed(
                db, preview_id, "Nieoczekiwany błąd generacji CV próbnego."
            )
            return
        from app.services.cv_generator_b2b.job_leases import lock_owned_job

        await lock_owned_job(db)
        row.with_rule_docx = with_rule.docx_bytes
        row.without_rule_docx = without_rule.docx_bytes
        from app.services.cv_generator_b2b.rule_feedback import presentation_feedback

        row.with_rule = {
            "rule_feedback": presentation_feedback(
                with_rule.render_payload or {}, snap
            ),
            "docx_sha256": hashlib.sha256(with_rule.docx_bytes).hexdigest(),
            "payload": with_rule.render_payload,
            "warnings": list(with_rule.warnings or []),
            "filename": with_rule.filename,
        }
        row.without_rule = {
            "docx_sha256": hashlib.sha256(without_rule.docx_bytes).hexdigest(),
            "payload": without_rule.render_payload,
            "warnings": list(without_rule.warnings or []),
            "filename": without_rule.filename,
        }
        row.prompt_block = build_prompt_blocks(snap, language)
        row.status = "ready"
        row.error_message = None
        await db.commit()


async def _require_preview_inputs(
    db: AsyncSession,
    *,
    client_id: int,
    candidate_id: int,
    stage_id: int,
    recipe_snapshot: dict,
) -> None:
    frozen = ClientCvRule()
    _apply_payload(frozen, ClientCvRulePayload(**recipe_snapshot))
    variants = (
        ("Z regułą", snapshot_rule(frozen), recipe_snapshot.get("cv_content_mode_cap")),
        ("Bez reguły", None, None),
    )
    for label, rule, cap in variants:
        readiness = await list_recruitments_with_readiness(
            db,
            candidate_id,
            rule_overrides={client_id: rule},
            content_mode_cap_overrides={client_id: cap},
        )
        match = next((r for r in readiness if r.stage_id == stage_id), None)
        if match is None or not match.ready:
            missing = (
                match.missing_inputs if match is not None else ["aktywna rekrutacja"]
            )
            raise HTTPException(
                status_code=422,
                detail=f"Ta rekrutacja nie jest gotowa do generacji ({label}) — brakuje: "
                + ", ".join(missing)
                + ".",
            )


@router.post(
    "/clients/{client_id}/cv-rule/preview",
    response_model=PreviewRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_client_cv_rule_preview(
    client_id: int,
    payload: PreviewRequest,
    current_user: DeliverySectionUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> PreviewRead:
    """CV próbne: wybrany kandydat i rekrutacja u tego klienta, z regułą i bez.

    Dwie generacje = dwa obciążenia kwoty ``cv_generator`` (to są realne
    wywołania najdroższego modelu). Naliczone PRZED zakolejkowaniem — odmowa
    ma być czytelnym 503, nie wierszem „failed".
    """
    client = await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client_id, write=True)
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage

    stage_client = (
        await db.execute(
            select(Job.client_id, CandidateStage.candidate_id)
            .join(CandidateStage, CandidateStage.job_id == Job.id)
            .where(CandidateStage.id == payload.stage_id)
        )
    ).first()
    if stage_client is None or stage_client[1] != payload.candidate_id:
        raise HTTPException(
            status_code=404, detail="Rekrutacja nie należy do tego kandydata."
        )
    if stage_client[0] != client_id:
        raise HTTPException(
            status_code=422,
            detail="Wybrana rekrutacja należy do innego klienta niż ta reguła.",
        )
    await db.execute(select(Client.id).where(Client.id == client_id).with_for_update())
    await db.refresh(client)
    rule = await _rule_for(db, client_id)
    editable = _editable_rule(rule)
    from app.api.cv_generator_b2b import _enforce_client_language

    _enforce_client_language(editable, payload.language)
    recipe_snapshot = (
        rule.draft_payload
        if rule is not None and rule.draft_payload
        else _rule_state(rule, client)
    )
    # No stored rule: use validated defaults instead of nullable ORM placeholders.
    if rule is None:
        recipe_snapshot = _recipe_payload(ClientCvRulePayload(), client)
    _validated_recipe(recipe_snapshot)
    await _require_preview_inputs(
        db,
        client_id=client_id,
        candidate_id=payload.candidate_id,
        stage_id=payload.stage_id,
        recipe_snapshot=recipe_snapshot,
    )
    try:
        source = await load_candidate_generation_source(
            db,
            candidate_id=payload.candidate_id,
            stage_id=payload.stage_id,
            language=payload.language,
            cv_document_id=payload.cv_document_id,
        )
        await run_in_threadpool(validate_cv_file, source.cv_bytes, source.cv_filename)
    except StandaloneGenerationError as err:
        raise HTTPException(status_code=422, detail=err.message) from None
    if (source.candidate_id, source.stage_id, source.client_id) != (
        payload.candidate_id,
        payload.stage_id,
        client_id,
    ):
        raise HTTPException(
            status_code=409,
            detail="Źródła rekrutacji zmieniły się. Wybierz proces ponownie.",
        )
    # Sprzątanie: podglądy starsze niż okno retencji znikają przy okazji
    # kolejnego — bez osobnego crona.
    from sqlalchemy import delete as sa_delete

    await db.execute(
        sa_delete(ClientCvRulePreview).where(
            ClientCvRulePreview.client_id == client_id,
            ClientCvRulePreview.created_at
            < datetime.now(timezone.utc) - PREVIEW_RETENTION,
        )
    )

    async def charge_preview():
        try:
            # Both variants and their admission commit with the durable job,
            # before a worker can make a provider call.
            return await check_and_increment(
                db,
                AIFeatureKey.cv_generator,
                user_id=current_user.id,
                units=2,
                commit_with_caller=True,
            )
        except AIQuotaExceeded as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "feature": exc.feature.value,
                    "reason": exc.reason,
                    "used": exc.used,
                    "limit": exc.limit,
                },
            ) from exc

    row = ClientCvRulePreview(
        client_id=client_id,
        candidate_id=payload.candidate_id,
        stage_id=payload.stage_id,
        language=payload.language,
        status="processing",
        recipe_snapshot=recipe_snapshot,
        created_by=current_user.id,
    )
    db.add(row)
    await db.flush()
    from app.services.cv_generator_b2b.durable_jobs import persist_job, execute_job

    durable_id = await persist_job(
        db,
        kind="preview",
        preview_id=row.id,
        user_id=current_user.id,
        charge=charge_preview,
        inputs=dict(
            client_id=client_id,
            candidate_id=payload.candidate_id,
            stage_id=payload.stage_id,
            language=payload.language,
            # Kwota jest naliczona WYŻEJ, w handlerze — bramka musi tam zostać,
            # bo odmowa w tle zostawiłaby wiersz „failed" zamiast czytelnego 503.
            # Zadanie dostaje sam stan, żeby móc się ZADEKLAROWAĆ: contextvar
            # ustawiony przez handler nie dożywa do `BackgroundTasks`.
            quota_user_id=current_user.id,
            source=source,
        ),
    )
    await db.commit()
    await db.refresh(row)
    background_tasks.add_task(execute_job, durable_id)
    return _preview_read(row, durable=True)


@router.get(
    "/clients/{client_id}/cv-rule/preview/{preview_id}", response_model=PreviewRead
)
async def get_client_cv_rule_preview(
    client_id: int,
    preview_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> PreviewRead:
    await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client_id, write=False)
    row = await db.get(ClientCvRulePreview, preview_id)
    if row is None or row.client_id != client_id:
        raise HTTPException(status_code=404, detail="Podgląd nie istnieje.")
    from app.models.cv_generation_job import CvGenerationJob

    durable_id = await db.scalar(
        select(CvGenerationJob.id).where(CvGenerationJob.preview_id == row.id)
    )
    return _preview_read(row, durable=durable_id is not None)


# ── Przegląd zbiorczy ────────────────────────────────────────────────────────


@router.get("/settings/cv-rules", response_model=CvRulesOverview)
async def cv_rules_overview(
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> CvRulesOverview:
    """Przegląd zbiorczy reguł w autoryzowanym grafie klientów.

    Do 09.2026 ten endpoint zwracał wyłącznie 14 zasianych szablonów, więc
    reguła założona ręcznie dla piętnastego klienta była na tym ekranie
    niewidoczna. Administrator nadal widzi pełną listę i nieprzypisane
    szablony. Użytkownik z ograniczonym grafem (w szczególności Delivery Lead)
    widzi wyłącznie reguły swoich klientów; nieprzypisane szablony są ukryte,
    bo nie mają klienta, którego przypisanie można zweryfikować.
    """
    seed_labels = dict(CHAMPION_SEED_KEYS)
    seed_keys = list(seed_labels)
    visible_client_ids = await resolve_client_visible_client_ids(db, current_user)

    confirmed_by_user = aliased(User)
    rules_stmt = (
        select(ClientCvRule, Client, _CLIENT_DISPLAY_NAME, confirmed_by_user.name)
        .join(Client, Client.id == ClientCvRule.client_id)
        .outerjoin(confirmed_by_user, confirmed_by_user.id == ClientCvRule.confirmed_by)
        .order_by(func.lower(_CLIENT_DISPLAY_NAME), ClientCvRule.id)
    )
    if visible_client_ids is not None:
        rules_stmt = rules_stmt.where(ClientCvRule.client_id.in_(visible_client_ids))
    rows = (await db.execute(rules_stmt)).all()

    urls = dict(
        (
            await db.execute(
                select(HelpMaterial.slug, HelpMaterial.url).where(
                    HelpMaterial.slug.in_(seed_keys)
                )
            )
        ).all()
    )

    rules: list[ClientCvRuleListItem] = []
    seen_seed_keys: set[str] = set()
    for rule, client, client_name, confirmed_by_name in rows:
        base = _to_read(
            rule,
            client=client,
            client_id=rule.client_id,
            client_name=client_name,
            confirmed_by_name=confirmed_by_name,
        )
        if rule.seed_key:
            seen_seed_keys.add(rule.seed_key)
        rules.append(
            ClientCvRuleListItem(
                **base.model_dump(),
                template_label=seed_labels.get(rule.seed_key or ""),
                template_url=urls.get(rule.seed_key) if rule.seed_key else None,
                updated_at=_iso(rule.updated_at),
            )
        )

    unassigned = (
        [
            UnassignedChampionTemplate(
                seed_key=key, label=label, template_url=urls.get(key)
            )
            for key, label in CHAMPION_SEED_KEYS
            if key not in seen_seed_keys
        ]
        if visible_client_ids is None
        else []
    )
    return CvRulesOverview(rules=rules, unassigned_templates=unassigned)


@router.get("/clients/{client_id}/cv-rule/preview/{preview_id}/docx/{variant}")
async def download_rule_preview_docx(
    client_id: int,
    preview_id: int,
    variant: Literal["with_rule", "without_rule"],
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import Response
    from urllib.parse import quote

    await _client_or_404(db, client_id)
    await _require_client_rule_access(db, current_user, client_id, write=False)
    row = await db.get(ClientCvRulePreview, preview_id)
    if row is None or row.client_id != client_id:
        raise HTTPException(404, "Podgląd nie istnieje.")
    content = row.with_rule_docx if variant == "with_rule" else row.without_rule_docx
    metadata = row.with_rule if variant == "with_rule" else row.without_rule
    if row.status != "ready" or not content or not metadata:
        raise HTTPException(
            409, "Ten podgląd nie ma zapisanego pliku DOCX. Uruchom nową próbę."
        )
    digest = hashlib.sha256(content).hexdigest()
    if digest != metadata.get("docx_sha256"):
        raise HTTPException(409, "Nie można potwierdzić integralności pliku podglądu.")
    filename = metadata.get("filename") or "cv-probne.docx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(filename, safe=""),
            "Cache-Control": "no-store",
            "X-Content-SHA256": digest,
        },
    )
