"""Reguły CV per klient — pełna recepta Delivery Leada.

Dwa wejścia, jedna prawda w bazie:

* profil klienta (``/api/clients/{id}/cv-rule``) — odczyt i zapis reguły;
* przegląd zbiorczy (``/api/settings/cv-rules``) — WSZYSTKIE reguły w bazie
  (nie tylko 14 zasianych z szablonów Championa) plus szablony, które nie mają
  jeszcze reguły. Z tego ekranu Delivery Lead zakłada regułę dla dowolnego
  klienta, edytuje ją, zatwierdza, usuwa, kopiuje z innego klienta, lintuje
  instrukcje, ogląda blok promptu, CV próbne, historię i sygnał zwrotny.

``confirmed_at IS NULL`` znaczy **propozycja, która nie obowiązuje**. Generator
czyta wyłącznie reguły zatwierdzone (``resolve_client_rule``), więc zasiane
dopasowanie po nazwie klienta nie może wejść w życie bez decyzji człowieka.
Własną regułę autor zatwierdza tym samym zapisem (``confirm=true``).

Bramka zapisu to ``DeliveryLeadPlus`` (admin / delivery_lead) — decyzja
produktowa z 02.09.2026: reguły CV prowadzi Delivery Lead, TAC ich nie zmienia
(choć kartę klienta edytować może). Zapis CELOWO nie jest zawężany do portfela
DL: to lustro ``PATCH /api/clients/{id}`` — reguła CV jest konfiguracją
klienta. Filtr „moi klienci" jest wygodą interfejsu, nie granicą.

Warstwy reguły (0255 → 0266 → 0267): nazwa pliku i język → instrukcje dla
modelu → blokady (tryb, wymagane wejścia, druga wersja językowa), polityka
prezentacji egzekwowana w kodzie, słownik, wersja + historia + CV próbne.
Każdy zapis zmieniający treść bumpuje ``version`` i zostawia wpis
w ``client_cv_rule_events`` — bez tego reklamacja klienta jest nie do
prześledzenia.
"""

import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import DeliveryLeadPlus, OperationalUser
from app.core.database import AsyncSessionLocal, get_db
from app.models.ai_feature import AIFeatureKey
from app.models.client import Client
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_event import ClientCvRuleEvent
from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.help_material import HelpMaterial
from app.models.user import User
from app.services.ai_quota import AIQuotaExceeded, check_and_increment
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
    generate_cv_for_candidate,
    list_recruitments_with_readiness,
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
)
CLIENT_FLAG_FIELDS: tuple[str, ...] = ("cv_content_mode_cap", "cv_interactive_enabled")

# Prefiksy ostrzeżeń, którymi model zgłasza pominiętą instrukcję klienta
# (prompt PL/EN) — sygnał zwrotny dla DL liczy je per instrukcja.
_SKIPPED_PREFIXES = ("Pominięto instrukcję klienta:", "Skipped client instruction:")
_POLICY_PREFIX = "WERYFIKUJ: domknięto politykę prezentacji klienta w kodzie:"


class GlossaryEntry(BaseModel):
    from_: str = Field(alias="from", min_length=1, max_length=80)
    to: str = Field(min_length=1, max_length=80)

    model_config = {"populate_by_name": True}


class ClientCvRulePayload(BaseModel):
    """Wejście edycji reguły. Wszystkie pola opcjonalne — pusty wzór znaczy
    „ten klient nie ma własnej nazwy pliku", nie „błąd"."""

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
        return value.strip()


class ClientCvRuleRead(BaseModel):
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
    candidate_id: int = Field(..., ge=1)
    stage_id: int = Field(..., ge=1)
    language: Literal["pl", "en"] = "pl"


class PreviewVariant(BaseModel):
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
            client_id=client_id, client_name=client_name, client_policy=None, **flags
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
        if field in ("omit_sections", "glossary"):
            value = list(value or [])
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
        {"from": entry.from_.strip(), "to": entry.to.strip()}
        for entry in payload.glossary
    ] or None


# ── Odczyt / zapis / zatwierdzanie / usuwanie ────────────────────────────────


@router.get("/clients/{client_id}/cv-rule", response_model=ClientCvRuleRead)
async def get_client_cv_rule(
    client_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> ClientCvRuleRead:
    """Reguła CV klienta — także niezatwierdzona.

    Bramka jest lustrem `GET /api/clients/{id}` (`OperationalUser`), bo to
    konfiguracja klienta, a nie dana kandydata. Nie zawęża to nikomu dostępu
    do banera w generatorze: `CANDIDATE_DOCUMENT_ROLES` (bramka obu ścieżek
    generacji) to DOKŁADNIE ten sam zestaw siedmiu ról operacyjnych.
    """
    client = await _client_or_404(db, client_id)
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
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> ClientCvRuleRead:
    """Zapisz regułę.

    Domyślnie zapis **NIE zatwierdza** — reguła zostaje propozycją, dopóki ktoś
    jej nie zatwierdzi. Edycja obowiązującej reguły ZDEJMUJE zatwierdzenie:
    inaczej zmiana wzoru nazwy pliku wchodziłaby na produkcję bez niczyjej
    decyzji, a właśnie po to ten stan istnieje.

    ``confirm=true`` zatwierdza tym samym zapisem — decyzja jest w tym samym
    kliknięciu, więc osobny krok nie wnosiłby nic poza drugim kliknięciem.

    Zmiana treści bumpuje ``version`` i zostawia wpis w historii z diffem pól.
    Sam ponowny zapis identycznej treści (np. tylko zatwierdzenie) wersji nie
    zmienia — stempel na CV ma mówić o TREŚCI reguły, nie o kliknięciach.
    """
    client = await _client_or_404(db, client_id)
    rule = await _rule_for(db, client.id)
    before = _rule_state(rule, client)
    created = rule is None
    if rule is None:
        rule = ClientCvRule(client_id=client.id)
        db.add(rule)

    _apply_payload(rule, payload)
    if (
        payload.cv_content_mode_cap is not None
        or "cv_content_mode_cap" in payload.model_fields_set
    ):
        client.cv_content_mode_cap = payload.cv_content_mode_cap
    if payload.cv_interactive_enabled is not None:
        client.cv_interactive_enabled = payload.cv_interactive_enabled

    after = _rule_state(rule, client)
    changes = _diff(before, after)
    if created:
        rule.version = await _next_version(db, client.id)
    elif changes:
        rule.version = int(rule.version or 1) + 1

    if payload.confirm:
        rule.confirmed_at = datetime.now(timezone.utc)
        rule.confirmed_by = current_user.id
    else:
        rule.confirmed_at = None
        rule.confirmed_by = None

    await db.flush()
    _record_event(
        db,
        client_id=client.id,
        version=int(rule.version or 1),
        action="saved_and_confirmed" if payload.confirm else "saved",
        changes=changes,
        actor=current_user,
    )
    await db.commit()
    await db.refresh(rule)
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
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> ClientCvRuleRead:
    """Zatwierdź regułę — od tej chwili generator ją stosuje."""
    client = await _client_or_404(db, client_id)
    rule = await _rule_for(db, client.id)
    if rule is None:
        raise HTTPException(
            status_code=404,
            detail="Ten klient nie ma jeszcze reguł CV — najpierw je zapisz.",
        )
    rule.confirmed_at = datetime.now(timezone.utc)
    rule.confirmed_by = current_user.id
    _record_event(
        db,
        client_id=client.id,
        version=int(rule.version or 1),
        action="confirmed",
        changes=None,
        actor=current_user,
    )
    await db.commit()
    await db.refresh(rule)
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
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Usuń regułę — klient wraca do globalnej nazwy pliku i wolnego wyboru
    języka. Historia zostaje (FK po kliencie, nie po regule)."""
    client = await _client_or_404(db, client_id)
    rule = await _rule_for(db, client.id)
    if rule is not None:
        _record_event(
            db,
            client_id=client.id,
            version=int(rule.version or 1),
            action="deleted",
            changes=None,
            actor=current_user,
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
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
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
    source_client = await _client_or_404(db, source_client_id)
    source = await _rule_for(db, source_client.id)
    if source is None:
        raise HTTPException(
            status_code=404, detail="Klient źródłowy nie ma reguły CV do skopiowania."
        )
    rule = await _rule_for(db, client.id)
    before = _rule_state(rule, client)
    created = rule is None
    if rule is None:
        rule = ClientCvRule(client_id=client.id)
        db.add(rule)
    for field in RULE_FIELDS:
        value = getattr(source, field, None)
        setattr(rule, field, list(value) if isinstance(value, list) else value)
    rule.seed_key = None
    rule.confirmed_at = None
    rule.confirmed_by = None
    after = _rule_state(rule, client)
    changes = _diff(before, after)
    if created:
        rule.version = await _next_version(db, client.id)
    elif changes:
        rule.version = int(rule.version or 1) + 1
    await db.flush()
    _record_event(
        db,
        client_id=client.id,
        version=int(rule.version or 1),
        action="copied",
        changes={"source_client_id": source_client.id, **changes},
        actor=current_user,
    )
    await db.commit()
    await db.refresh(rule)
    return _to_read(
        rule, client=client, client_id=client.id, client_name=_client_label(client)
    )


# ── Historia, sygnał zwrotny, lint, podgląd promptu, CV próbne ──────────────


@router.get("/clients/{client_id}/cv-rule/history", response_model=list[RuleEventRead])
async def client_cv_rule_history(
    client_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[RuleEventRead]:
    await _client_or_404(db, client_id)
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
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    days: int = Query(90, ge=1, le=365),
) -> RuleFeedback:
    """Co model pomijał, a co kod domykał — per instrukcja, z ostatnich N dni.

    Instrukcja pomijana w co drugim CV to instrukcja do przepisania. Bez tej
    listy DL widzi wyłącznie pojedyncze ostrzeżenia u rekruterów, którzy nie
    mają powodu ich zgłaszać.
    """
    await _client_or_404(db, client_id)
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
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> LintResponse:
    """Oceń instrukcje linia po linii ZANIM trafią do reguły.

    Kwota ``cv_rule_lint`` naliczana przed wywołaniem modelu (jak wszędzie —
    decyzja o dopuszczeniu, nie sukces round-tripu). Lint jest opinią: nie
    blokuje zapisu, tylko pokazuje granicę wcześniej.
    """
    from app.services.cv_generator_b2b.rule_lint import lint_instructions

    await _client_or_404(db, client_id)
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
    try:
        # Jedno pole = jedno wywołanie modelu = jedno obciążenie. Wszystkie
        # naliczane PRZED pierwszym wywołaniem — odmowa w połowie cofa całość.
        for _ in fields:
            await check_and_increment(
                db, AIFeatureKey.cv_rule_lint, user_id=current_user.id
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
    await db.commit()

    request_id = f"cvlint_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    findings: list[LintFindingRead] = []
    for name, text in fields:
        try:
            results = await run_in_threadpool(
                lint_instructions, text or "", request_id=f"{request_id}_{name}"
            )
        except Exception as err:  # noqa: BLE001 — lint nie może wywrócić edytora
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
    return LintResponse(
        findings=findings,
        ok_count=sum(1 for f in findings if f.verdict == "ok"),
        adds_facts_count=sum(1 for f in findings if f.verdict == "adds_facts"),
        unclear_count=sum(1 for f in findings if f.verdict == "unclear"),
    )


@router.get("/clients/{client_id}/cv-rule/prompt-preview", response_model=PromptPreview)
async def client_cv_rule_prompt_preview(
    client_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    language: Literal["pl", "en"] = Query("pl"),
) -> PromptPreview:
    """Dokładny blok, jaki dostanie model — bez tajemnic. Pokazuje stan
    ZAPISANY (także niezatwierdzony), z zaznaczeniem, czy obowiązuje."""
    await _client_or_404(db, client_id)
    rule = await _rule_for(db, client_id)
    return PromptPreview(
        language=language,
        block=build_prompt_blocks(snapshot_rule(rule), language),
        is_active=bool(rule is not None and rule.confirmed_at is not None),
    )


def _variant(value: Optional[dict]) -> Optional[PreviewVariant]:
    if not value:
        return None
    return PreviewVariant(
        payload=value.get("payload"),
        warnings=list(value.get("warnings") or []),
        filename=value.get("filename"),
    )


def _preview_read(row: ClientCvRulePreview) -> PreviewRead:
    status_value = row.status
    error_message = row.error_message
    if (
        status_value == "processing"
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
) -> None:
    """Dwie generacje w tle: z regułą (zapisaną, choćby niezatwierdzoną)
    i bez. Awaria którejkolwiek = wiersz „failed" z powodem; nic nie jest
    zapisywane w `cv_generated_documents`."""
    async with AsyncSessionLocal() as db:
        row = await db.get(ClientCvRulePreview, preview_id)
        if row is None:
            return
        try:
            rule = await _rule_for(db, client_id)
            snap = snapshot_rule(rule)
            with_rule = await generate_cv_for_candidate(
                db,
                candidate_id=candidate_id,
                stage_id=stage_id,
                language=language,  # type: ignore[arg-type]
                client_rule=snap,
            )
            without_rule = await generate_cv_for_candidate(
                db,
                candidate_id=candidate_id,
                stage_id=stage_id,
                language=language,  # type: ignore[arg-type]
                client_rule=None,
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
        row.with_rule = {
            "payload": with_rule.render_payload,
            "warnings": list(with_rule.warnings or []),
            "filename": with_rule.filename,
        }
        row.without_rule = {
            "payload": without_rule.render_payload,
            "warnings": list(without_rule.warnings or []),
            "filename": without_rule.filename,
        }
        row.prompt_block = build_prompt_blocks(snap, language)
        row.status = "ready"
        row.error_message = None
        await db.commit()


@router.post(
    "/clients/{client_id}/cv-rule/preview",
    response_model=PreviewRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_client_cv_rule_preview(
    client_id: int,
    payload: PreviewRequest,
    current_user: DeliveryLeadPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> PreviewRead:
    """CV próbne: wybrany kandydat i rekrutacja u tego klienta, z regułą i bez.

    Dwie generacje = dwa obciążenia kwoty ``cv_generator`` (to są realne
    wywołania najdroższego modelu). Naliczone PRZED zakolejkowaniem — odmowa
    ma być czytelnym 503, nie wierszem „failed".
    """
    await _client_or_404(db, client_id)
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
    # Gotowość rekrutacji (CV, Champion, notatki) PRZED naliczeniem kwoty —
    # inaczej DL płaci dwie generacje za wiersz „failed".
    readiness = await list_recruitments_with_readiness(db, payload.candidate_id)
    match = next((r for r in readiness if r.stage_id == payload.stage_id), None)
    if match is None or not match.ready:
        missing = []
        if match is None or not match.has_cv:
            missing.append("CV w systemie")
        if match is None or not match.has_champion:
            missing.append("Profil Championa")
        if match is None or not match.has_notes:
            missing.append("notatki z rozmów")
        raise HTTPException(
            status_code=422,
            detail="Ta rekrutacja nie jest gotowa do generacji — brakuje: "
            + ", ".join(missing)
            + ".",
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
    try:
        for _ in range(2):
            await check_and_increment(
                db, AIFeatureKey.cv_generator, user_id=current_user.id
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
        created_by=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    background_tasks.add_task(
        _run_rule_preview_job,
        row.id,
        client_id=client_id,
        candidate_id=payload.candidate_id,
        stage_id=payload.stage_id,
        language=payload.language,
    )
    return _preview_read(row)


@router.get(
    "/clients/{client_id}/cv-rule/preview/{preview_id}", response_model=PreviewRead
)
async def get_client_cv_rule_preview(
    client_id: int,
    preview_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> PreviewRead:
    row = await db.get(ClientCvRulePreview, preview_id)
    if row is None or row.client_id != client_id:
        raise HTTPException(status_code=404, detail="Podgląd nie istnieje.")
    return _preview_read(row)


# ── Przegląd zbiorczy ────────────────────────────────────────────────────────


@router.get("/settings/cv-rules", response_model=CvRulesOverview)
async def cv_rules_overview(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CvRulesOverview:
    """Przegląd zbiorczy: KAŻDA reguła w bazie + szablony Championa bez reguły.

    Do 09.2026 ten endpoint zwracał wyłącznie 14 zasianych szablonów, więc
    reguła założona ręcznie dla piętnastego klienta była na tym ekranie
    NIEWIDOCZNA. Teraz lista jest pełna, a szablony bez wiersza idą osobno:
    ukrycie ich sprawiłoby, że brak reguły wyglądałby identycznie jak jej
    nieistnienie i nikt by go nie uzupełnił.

    Odczyt jest nieoskopowany także dla Delivery Leada (lustro
    ``GET /api/clients/{id}/cv-rule``) — zawężenie do portfela robi interfejs,
    jako filtr, który da się wyłączyć.
    """
    seed_labels = dict(CHAMPION_SEED_KEYS)
    seed_keys = list(seed_labels)

    confirmed_by_user = aliased(User)
    rows = (
        await db.execute(
            select(ClientCvRule, Client, _CLIENT_DISPLAY_NAME, confirmed_by_user.name)
            .join(Client, Client.id == ClientCvRule.client_id)
            .outerjoin(
                confirmed_by_user, confirmed_by_user.id == ClientCvRule.confirmed_by
            )
            .order_by(func.lower(_CLIENT_DISPLAY_NAME), ClientCvRule.id)
        )
    ).all()

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

    unassigned = [
        UnassignedChampionTemplate(
            seed_key=key, label=label, template_url=urls.get(key)
        )
        for key, label in CHAMPION_SEED_KEYS
        if key not in seen_seed_keys
    ]
    return CvRulesOverview(rules=rules, unassigned_templates=unassigned)
