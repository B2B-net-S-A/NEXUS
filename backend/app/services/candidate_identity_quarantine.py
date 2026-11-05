"""Identity-mismatch quarantine for candidate-bound source material.

The detector is intentionally conservative: an automatic mismatch is only
confirmed when both identities have a usable first name and surname and both
parts disagree after transliteration.  Missing surnames, partial disagreement,
a word shared by both identities, a near-equal name part, the same sound or
letters of the name and a profile phone from outside this read stay
``inconclusive`` so a name change, another spelling or split of the same words
or a parsing failure cannot silently quarantine a legitimate source.

Raw names and free text never enter the review row or audit event.  Only
booleans and keyed SHA-256 fingerprints are retained as provenance.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Literal

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.candidate_activity_summary import CandidateActivitySummary
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_language import CandidateLanguage
from app.models.candidate_source_identity_review import (
    CandidateSourceIdentityReview,
)
from app.models.index_outbox import IndexOutboxEvent
from app.models.user import User, UserRole
from app.services import candidate_audit
from app.services.candidate_location_writer import project_candidate_location
from app.services.candidate_name_rules import EMPTY_FIELD_NAME_PHRASES
from app.services.cv_common_words import only_common_cv_words
from app.services.dedup_service import _normalize_phone

logger = logging.getLogger(__name__)

SourceKind = Literal["note", "document", "legacy_cv", "talent_radar_cv"]
IdentityDecision = Literal[
    "confirmed_match",
    "confirmed_mismatch",
    "inconclusive",
]

IDENTITY_DETECTOR_VERSION = "candidate-source-identity-v1"
_PLACEHOLDERS = frozenset(
    {
        "",
        "?",
        "-",
        "nieznane",
        "nieznany",
        "unknown",
        "n/a",
        "na",
    }
    | EMPTY_FIELD_NAME_PHRASES
)
_SPECIAL_TRANSLITERATION = str.maketrans(
    {
        "ł": "l",
        "Ł": "l",
        "đ": "d",
        "Đ": "d",
        "ð": "d",
        "Ð": "d",
        "ø": "o",
        "Ø": "o",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
        "ß": "ss",
    }
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
# Krótsze słowo („de”, „Li”) bywa wspólne dwóm różnym osobom.
_NAME_TOKEN_MIN_CHARS = 3
# Pomiar 05.11.2026 na 608 sprzecznościach: 280 to te same słowa w innym podziale
# na imię i nazwisko, kolejne ok. 90 to literówka albo transliteracja.
_NAME_PART_SIMILAR_RATIO = 0.8
# Ta sama osoba bywa zapisana po polsku, rosyjsku i białorusku bez wspólnego słowa
# (pomiar 05.11.2026 na 133 sprzecznościach: 64 własne CV i 46 cudzych; klucz
# dźwięku zdjął 22 własne i 1 cudzy z tym samym nazwiskiem). Kolejność ma znaczenie.
_NAME_SOUND_REPLACEMENTS = (
    ("szcz", "shch"),
    ("sch", "sh"),
    ("sz", "sh"),
    ("cz", "ch"),
    ("rz", "zh"),
    ("ts", "c"),
    ("tz", "c"),
    ("ck", "k"),
    ("ph", "f"),
    ("th", "t"),
    ("kh", "h"),
    ("ch", "h"),
    ("zh", "z"),
    ("sh", "s"),
    ("x", "ks"),
    ("w", "v"),
    ("y", "i"),
    ("j", "i"),
    ("g", "h"),
    ("q", "k"),
    ("ou", "ov"),
    ("au", "ov"),
    ("e", "a"),
    ("o", "a"),
    ("u", "v"),
)
_REPEATED_CHAR_RE = re.compile(r"(.)\1+")
# Krótszy ciąg liter bywa przypadkiem częścią cudzej nazwy.
_SAME_LETTERS_MIN_CHARS = 6
_FULL_PHONE_DIGITS = 9
# Krótki tekst bywa przypadkiem końcem innego CV; próg jak w `extract_cv_text`.
_SAME_TEXT_TAIL_MIN_CHARS = 100
MISMATCH_HELD_EVIDENCE = "mismatch_held_for_review"


class IdentityQuarantineConflict(RuntimeError):
    """The requested source cannot transition to the requested state."""


class IdentityQuarantineForbidden(PermissionError):
    """The actor is not allowed to override a confirmed mismatch."""


@dataclass(frozen=True)
class IdentityMatchResult:
    decision: IdentityDecision
    evidence: dict[str, bool | str]


async def _purge_candidate_summary_cache(
    db: AsyncSession,
    candidate_id: int,
) -> None:
    """Remove possibly contaminated prose and fence any in-flight publisher."""

    await db.execute(
        update(CandidateActivitySummary)
        .where(CandidateActivitySummary.candidate_id == candidate_id)
        .values(
            summary=None,
            model=None,
            source_version=None,
            source_manifest={},
            generated_by=None,
            generated_at=None,
            generation_lease_token=None,
            generation_lease_expires_at=None,
        )
    )


def _legacy_language_level(row: CandidateLanguage) -> str:
    if row.is_native:
        return "native"
    if row.is_level_unknown:
        return "unknown"
    return str(row.cefr_level)


def _quarantined_cv_language_source_refs(
    *,
    candidate_id: int,
    source_kind: SourceKind,
    source_id: int,
    document_hash: str | None = None,
) -> tuple[str, ...]:
    if source_kind == "legacy_cv":
        return (f"legacy-cv:{candidate_id}",)
    refs = [f"document:{source_id}"]
    if document_hash:
        refs.append(document_hash)
    return tuple(refs)


@dataclass(frozen=True)
class ReplacedPrimaryCv:
    """Stan sprzed wgrania albo wyboru nowego głównego CV.

    Podaje go żądanie, które zrobiło z pliku główne CV. Sama obecność tego
    obiektu mówi bramce tożsamości, że plik niczego jeszcze w profilu nie
    zapisał (odczyt biegnie PO bramce), więc zgodność `cv_filename` z jego nazwą
    nie dowodzi, skąd pochodzą fakty — także wtedy, gdy profil nie miał
    wcześniej żadnego głównego dokumentu (`document_id=None`).
    """

    document_id: int | None
    cv_filename: str | None


async def _hand_primary_back(
    db: AsyncSession,
    *,
    candidate: Candidate,
    quarantined: CandidateDocument,
    replaced: ReplacedPrimaryCv,
    source_kind: SourceKind,
    source_id: int,
) -> None:
    """Przywróć wybór CV sprzed wgrania pliku, który trafił do kwarantanny.

    Fakty w profilu zostają nietknięte — nie pochodzą z tego pliku. Wraca tylko
    wybór głównego CV i wskaźnik `cv_filename`, a profil dostaje znacznik, po
    którym ekran mówi, że wgrane CV nie zasiliło danych.
    """
    previous = None
    if replaced.document_id is not None:
        # Flaga musi zejść z pliku w kwarantannie, zanim dostanie ją poprzedni:
        # `ux_candidate_documents_active_primary_cv` pozwala na jedno główne
        # CV, a jeden flush wysłałby oba UPDATE-y w kolejności id.
        await db.flush()
        previous = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.id == replaced.document_id,
                CandidateDocument.candidate_id == candidate.id,
                CandidateDocument.document_kind == CandidateDocumentKind.cv,
                CandidateDocument.source_deleted_at.is_(None),
                CandidateDocument.outdated_at.is_(None),
            )
        )
    if previous is not None:
        previous.is_primary = True
    if candidate.cv_filename == quarantined.filename:
        # Upload przejął wskaźnik pliku. Stara nazwa równa nowej oznacza, że
        # kopia na dysku jest już nadpisana — wtedy wskaźnika nie ma do czego
        # przywrócić.
        restored = previous.filename if previous is not None else replaced.cv_filename
        candidate.cv_filename = (
            restored
            if previous is not None or restored != quarantined.filename
            else None
        )
    _raw = candidate.cv_extracted_data
    extracted = dict(_raw) if isinstance(_raw, dict) else {}
    extracted["_identity_quarantine_source"] = {"kind": source_kind, "id": source_id}
    candidate.cv_extracted_data = extracted


async def _restore_stage_copies(
    db: AsyncSession, *, candidate: Candidate, document: CandidateDocument
) -> None:
    """Kopie CV etapu z pliku w kwarantannie wracają do bieżącego CV osoby.

    13.10.2026 („Nowe CV w rekrutacji”): CV wgrane z rekrutacji staje się od
    razu kopią CV etapu, a bramka biegnie po zapisie. Bez tego kopia etapu
    zostawała z CV innej osoby — w podglądzie, w pobraniu i w przeglądzie
    zgodności, który czyta ją jako oryginał tej osoby.
    """
    from app.services.candidate_stage_cv_service import (
        restore_stage_copies_after_quarantine,
    )

    await restore_stage_copies_after_quarantine(
        db, candidate=candidate, quarantined_sha256=document.content_sha256
    )


def _same_cv_text(first: str | None, second: str | None) -> bool:
    """Ten sam tekst. Starszy odczyt nie ma linii z OCR nagłówka na początku
    (`extract_cv_text`), więc krótszy tekst może być końcem dłuższego."""

    def folded(text: str | None) -> str:
        return " ".join((text or "").split()).casefold()

    shorter, longer = sorted((folded(first), folded(second)), key=len)
    if not shorter:
        return False
    return shorter == longer or (
        len(shorter) >= _SAME_TEXT_TAIL_MIN_CHARS and longer.endswith(shorter)
    )


async def _side_file_text(
    db: AsyncSession,
    *,
    candidate_id: int,
    document_id: int,
) -> str | None:
    """Tekst pliku, który nie jest głównym CV, gdy profil ma tekst CV.

    Odczyt biegnie przed blokadą wiersza kandydata, bo plik bywa skanem. Awaria
    magazynu albo odczytu oznacza brak dowodu, a decyzja człowieka i tak zapada.
    """
    from fastapi.concurrency import run_in_threadpool

    from app.services import object_storage
    from app.services.cv_backfill import _extract_text_from_bytes

    document = await db.scalar(
        select(CandidateDocument).where(
            CandidateDocument.id == document_id,
            CandidateDocument.candidate_id == candidate_id,
        )
    )
    if document is None or document.is_primary:
        return None
    raw_cv_text = await db.scalar(
        select(Candidate.raw_cv_text).where(Candidate.id == candidate_id)
    )
    if not raw_cv_text:
        return None
    try:
        if document.storage_key:
            content = await run_in_threadpool(
                object_storage.download_cv, document.storage_key
            )
        else:
            content = await db.scalar(
                select(CandidateDocument.file_content).where(
                    CandidateDocument.id == document_id
                )
            )
        if not content:
            return None
        return await _extract_text_from_bytes(bytes(content), document.filename)
    except Exception as exc:  # noqa: BLE001 — brak dowodu, nie błąd decyzji
        logger.warning(
            "[identity_quarantine] side file unreadable document=%s: %s",
            document_id,
            type(exc).__name__,
        )
        return None


async def _clear_quarantined_cv_projection(
    db: AsyncSession,
    *,
    candidate_id: int,
    source_kind: SourceKind,
    source_id: int,
    replaced_primary: ReplacedPrimaryCv | None = None,
    source_text: str | None = None,
) -> dict[str, Any]:
    """Remove only facts provably projected from the quarantined CV source.

    `replaced_primary` podaje żądanie, które właśnie zrobiło z pliku główne CV
    (wgranie albo „Ustaw jako główne CV”). Plik przejmuje flagę i `cv_filename`
    od razu, a odczyt biegnie dopiero po bramce tożsamości — więc zgodność nazwy
    pliku nie dowodzi wtedy, że fakty w profilu pochodzą z niego. Pochodzą
    z wcześniejszego CV albo importu właściwej osoby i zostają (12.10.2026: nowe
    CV jest domyślnie głównym; 91% profili nie ma zapisanego dokumentu
    źródłowego). `None` = ponowny odczyt pliku, który już był głównym CV.

    `source_text` podaje decyzja człowieka: tekst CV w profilu równy tekstowi
    pliku dowodzi pochodzenia także wtedy, gdy plik nie jest główny, a odczyt nie
    zapisał `source_document_id` (6502 i 80774, 05.11.2026). Automat tego dowodu
    nie dostaje: na produkcji 3 z 15 profili z tekstem zgodnym co najmniej w 95%
    z plikiem w kwarantannie ma w odczycie imię i nazwisko właściciela profilu,
    więc decyzja parsera bywa fałszywym alarmem.
    """

    if source_kind in {"note", "talent_radar_cv"}:
        return {"cleared_fields": 0, "tombstoned_languages": 0}
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        return {"cleared_fields": 0, "tombstoned_languages": 0}

    document: CandidateDocument | None = None
    if source_kind == "document":
        document = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.id == source_id,
                CandidateDocument.candidate_id == candidate_id,
            )
        )
        if document is None:
            return {"cleared_fields": 0, "tombstoned_languages": 0}

    # `cv_extracted_data` is not guaranteed to be an object — a non-empty list
    # is truthy, so `or {}` lets it through and `dict(<list>)` raises. Same
    # column, same trap as `_manual_lock` in candidate_location_writer.py.
    _extracted_raw = candidate.cv_extracted_data
    extracted = dict(_extracted_raw) if isinstance(_extracted_raw, dict) else {}
    highlights = (
        extracted.get("cv_highlights")
        if isinstance(extracted.get("cv_highlights"), dict)
        else {}
    )
    projected_document_id = highlights.get("source_document_id")
    legacy_has_newer_document = False
    if source_kind == "legacy_cv":
        legacy_has_newer_document = projected_document_id is not None
        if not legacy_has_newer_document:
            current_primary_document_id = await db.scalar(
                select(CandidateDocument.id).where(
                    CandidateDocument.candidate_id == candidate_id,
                    CandidateDocument.document_kind == CandidateDocumentKind.cv,
                    CandidateDocument.is_primary.is_(True),
                    CandidateDocument.source_deleted_at.is_(None),
                )
            )
            legacy_has_newer_document = current_primary_document_id is not None
    owns_projection = (
        source_kind == "legacy_cv" and not legacy_has_newer_document
    ) or (projected_document_id == source_id)
    if _same_cv_text(source_text, candidate.raw_cv_text):
        owns_projection = True
    # Plik właśnie stał się głównym CV i nie był nim wcześniej (ponowne
    # wgranie TEGO SAMEGO głównego pliku to zwykły ponowny odczyt).
    freshly_selected = (
        document is not None
        and replaced_primary is not None
        and replaced_primary.document_id != source_id
        and not owns_projection
    )
    if (
        document is not None
        and document.is_primary
        and candidate.cv_filename
        and candidate.cv_filename == document.filename
        and not freshly_selected
    ):
        owns_projection = True
    if document is not None:
        # A quarantined source must not remain the selected CV even when legacy
        # rows have no source_document_id provenance.
        document.is_primary = False
    if not owns_projection:
        if freshly_selected and document is not None and replaced_primary is not None:
            await _hand_primary_back(
                db,
                candidate=candidate,
                quarantined=document,
                replaced=replaced_primary,
                source_kind=source_kind,
                source_id=source_id,
            )
        if document is not None:
            await _restore_stage_copies(db, candidate=candidate, document=document)
        return {"cleared_fields": 0, "tombstoned_languages": 0}

    stats = await _clear_cv_projection(
        db,
        candidate=candidate,
        extracted=extracted,
        source_kind=source_kind,
        source_id=source_id,
        document_filename=document.filename if document is not None else None,
        document_hash=document.content_sha256 if document is not None else None,
    )
    if document is not None:
        await _restore_stage_copies(db, candidate=candidate, document=document)
    return stats


async def clear_foreign_cv_projection(
    db: AsyncSession,
    *,
    candidate_id: int,
    document_id: int,
    document_hash: str | None,
) -> dict[str, Any]:
    """Wyczyść z profilu fakty odczytane z CV innej osoby (naprawa danych).

    Audyt 22.10.2026 (F114, decyzja Artura): skrypty naprawcze po cudzym CV
    z maila (`m365_document_repair`, `m365_unreadable_name_rematch`) odpinały
    plik, a tekst CV, umiejętności, podsumowanie AI i wektor z tego pliku
    zostawały. Wołający sam rozstrzyga, że projekcja pochodzi z tego pliku,
    i sam prowadzi główne CV, wskaźnik `cv_filename` i kopie CV etapu — tu
    zostaje czyszczenie jak w kwarantannie tożsamości.
    """
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        return {"cleared_fields": 0, "tombstoned_languages": 0}
    _extracted_raw = candidate.cv_extracted_data
    extracted = dict(_extracted_raw) if isinstance(_extracted_raw, dict) else {}
    stats = await _clear_cv_projection(
        db,
        candidate=candidate,
        extracted=extracted,
        source_kind="document",
        source_id=document_id,
        document_filename=None,
        document_hash=document_hash,
        keep_contact=True,
    )
    await _purge_candidate_summary_cache(db, candidate_id)
    return stats


def _skills_without_cv_read(current: Any, parsed_skills: Any) -> list | None:
    """Kolumna `skills` bez pozycji z odczytu CV; `None` = nie pochodzi z odczytu.

    `_apply_cv_enrichment` zapisuje `normalize_llm_skills(x.skills)`, a w
    `cv_extracted_data` zostaje surowy wynik modelu, więc samo porównanie
    z odczytem zostawiało umiejętności innej osoby (80774, 05.11.2026). Odczyt
    notatek dopisuje na końcu listy, dlatego wystarcza zgodny początek, a dopisek
    zostaje. Inna kolejność nie jest dowodem: FILL_EMPTY nie nadpisuje kolumny.
    """
    from app.services.cv_enrichment import normalize_llm_skills

    if parsed_skills is None:
        return None
    if current == parsed_skills:
        return []
    normalized = normalize_llm_skills(parsed_skills)
    if not normalized or not isinstance(current, list):
        return None
    if current[: len(normalized)] != normalized:
        return None
    return current[len(normalized) :]


async def _clear_cv_projection(
    db: AsyncSession,
    *,
    candidate: Candidate,
    extracted: dict[str, Any],
    source_kind: SourceKind,
    source_id: int,
    document_filename: str | None,
    document_hash: str | None,
    keep_contact: bool = False,
) -> dict[str, Any]:
    """Fakty z CV-źródła znikają z profilu, wektor idzie do skasowania.

    `keep_contact` (naprawa danych, F114): e-mail, telefon, miasto i LinkedIn
    zostają, bo odczyt mógł pochodzić z własnego załącznika osoby.
    """
    candidate_id = candidate.id
    cleared_fields: list[str] = []

    def locked(field: str) -> bool:
        return bool(extracted.get(f"_manual_override_{field}"))

    def clear_if_equal(
        attribute: str,
        parsed_key: str,
        written_form: Callable[[Any], Any] | None = None,
    ) -> None:
        parsed_value = extracted.get(parsed_key)
        if parsed_value is None or locked(parsed_key):
            return
        current = getattr(candidate, attribute, None)
        if current == parsed_value or (
            written_form is not None and current == written_form(parsed_value)
        ):
            setattr(candidate, attribute, None)
            cleared_fields.append(attribute)

    candidate.raw_cv_text = None
    cleared_fields.append("raw_cv_text")
    if source_kind == "legacy_cv" or (
        document_filename is not None and candidate.cv_filename == document_filename
    ):
        candidate.cv_filename = None
        cleared_fields.append("cv_filename")
    candidate.cv_parsed_at = None
    cleared_fields.append("cv_parsed_at")
    # Podsumowanie poprawione ręcznie (blokada z 12.10.2026) nie jest faktem
    # z CV — zostaje jak ręcznie poprawiona historia pracy.
    if candidate.ai_summary is not None and not extracted.get(
        "_manual_override_ai_summary"
    ):
        candidate.ai_summary = None
        cleared_fields.append("ai_summary")

    from app.services.cv_enrichment import (
        NON_CV_EXTRACTED_KEYS,
        _loaded_flag,
        cv_experience_entries,
    )

    # Te same blokady, które `_apply_cv_enrichment` szanuje przy zapisie.
    if not locked("skills") and not _loaded_flag(candidate, "skills_manually_curated"):
        skills_left = _skills_without_cv_read(candidate.skills, extracted.get("skills"))
        if skills_left is not None:
            candidate.skills = skills_left
            cleared_fields.append("skills")
    # Wykształcenie i lata `_apply_cv_enrichment` zapisuje bez zmian, więc tu
    # wystarcza równość z odczytem.
    if (
        extracted.get("education") is not None
        and candidate.education == extracted.get("education")
        and not locked("education")
    ):
        candidate.education = []
        cleared_fields.append("education")
    # Ten sam kształt, który zapisał `_apply_cv_enrichment` (także stanowiska
    # z datami z odczytu v6) — inaczej doświadczenie złej osoby zostawałoby.
    expected_experience = cv_experience_entries(extracted)
    if (
        expected_experience
        and candidate.experience == expected_experience
        and not extracted.get("_manual_override_experience")
    ):
        candidate.experience = []
        cleared_fields.append("experience")
    if (
        extracted.get("years_it_experience") is not None
        and candidate.years_it_experience == extracted.get("years_it_experience")
        and not locked("years_it_experience")
    ):
        candidate.years_it_experience = None
        cleared_fields.append("years_it_experience")

    if not keep_contact:
        # Zapis idzie małymi literami, a odczyt zostaje taki, jak w CV.
        clear_if_equal(
            "email", "email", lambda parsed: str(parsed).strip().lower()[:255]
        )
        clear_if_equal("phone", "phone")
        clear_if_equal("city", "city")
    if "city" in cleared_fields:
        projected_location = project_candidate_location(
            candidate.city,
            candidate.country,
        )
        if candidate.location != projected_location:
            candidate.location = projected_location
            cleared_fields.append("location")
    parsed_linkedin = extracted.get("linkedin_url")
    if (
        not keep_contact
        and parsed_linkedin
        and candidate.linkedin
        and not locked("linkedin")
    ):
        from app.services.proxycurl import normalize_linkedin_url

        # Zapis idzie przez `normalize_linkedin_url`, a odczyt zostaje surowy.
        if candidate.linkedin in (
            parsed_linkedin,
            normalize_linkedin_url(parsed_linkedin),
        ):
            candidate.linkedin = None
            cleared_fields.append("linkedin")

    # Keep only explicit locks and integration-owned metadata. Raw parser
    # output can itself describe the wrong person.
    # Runda 9 (R9-N8-3): fakty z notatek i pochodzenie importu nie pochodzą
    # z tego CV — kwarantanna CV ich nie kasuje.
    candidate.cv_extracted_data = {
        key: value
        for key, value in extracted.items()
        if key.startswith("_manual_override_")
        or key.startswith("traffit_")
        or key in NON_CV_EXTRACTED_KEYS
    }
    candidate.cv_extracted_data["_identity_quarantine_source"] = {
        "kind": source_kind,
        "id": source_id,
    }

    source_refs = _quarantined_cv_language_source_refs(
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
        document_hash=document_hash,
    )
    language_rows = list(
        (
            await db.scalars(
                select(CandidateLanguage).where(
                    CandidateLanguage.candidate_id == candidate_id,
                    CandidateLanguage.deleted_at.is_(None),
                    CandidateLanguage.provenance == "cv",
                    CandidateLanguage.manual_lock.is_(False),
                    CandidateLanguage.source_ref.in_(source_refs),
                )
            )
        ).all()
    )
    now = datetime.now(timezone.utc)
    for language in language_rows:
        language.deleted_at = now
        language.version += 1
    if language_rows:
        candidate.languages_version += 1
        active_languages = list(
            (
                await db.scalars(
                    select(CandidateLanguage)
                    .where(
                        CandidateLanguage.candidate_id == candidate_id,
                        CandidateLanguage.deleted_at.is_(None),
                    )
                    .order_by(CandidateLanguage.language_name.asc())
                )
            ).all()
        )
        candidate.languages = [
            {
                "code": language.language_code.upper(),
                "lang": language.language_name,
                "level": _legacy_language_level(language),
            }
            for language in active_languages
        ]

    from app.services.match_score_cache import mark_stale_for_candidate

    await mark_stale_for_candidate(db, candidate_id)
    # A confirmed mismatch makes the current semantic vector unsafe. Remove it
    # immediately (fail-closed even if this transaction later rolls back) and
    # persist a delete retry in the caller's transaction. Never enqueue an
    # isolated upsert before the quarantine commit: that race can re-index the
    # pre-quarantine row under a post-quarantine hash.
    db.add(
        IndexOutboxEvent(
            entity_type="candidate",
            entity_id=candidate_id,
            entity_revision=int(now.timestamp() * 1_000_000),
            desired_hash="",
            operation="delete",
            status="pending",
        )
    )
    # Kolumna `candidates.embedding_id` jest KOPIĄ identyfikatora — jej jedyną
    # treścią jest "NULL czy nie", czyli predykat "ma wektor". Kasowanie punktu
    # z Qdranta bez wyzerowania tej kolumny zostawiało ją twierdzącą "wektor
    # jest" dla kandydata, któremu go właśnie odebraliśmy. Zerujemy BEZWARUNKOWO
    # (przed próbą kasowania i niezależnie od jej wyniku): intencją kwarantanny
    # jest brak wektora, a nieudane kasowanie ma trwały retry w outboksie wyżej.
    # Zapis idzie w transakcji wołającego — razem z resztą czyszczenia, więc
    # rollback cofa jedno i drugie.
    #
    # `embedding_id` NIE trafia do `cleared_fields`: ta lista raportuje, ile pól
    # z danymi OSOBY wyczyściliśmy, a to jest znacznik indeksu, nie dana osobowa.
    candidate.embedding_id = None
    try:
        from app.services.embedding_service import delete_candidate_embedding

        deleted = await delete_candidate_embedding(candidate_id)
        if not deleted:
            logger.error(
                "[identity_quarantine] immediate vector delete failed; "
                "durable retry staged candidate=%s",
                candidate_id,
            )
    except Exception as exc:  # pragma: no cover - quarantine remains authoritative
        logger.warning(
            "[identity_quarantine] vector delete failed candidate=%s: %s",
            candidate_id,
            exc,
        )
    return {
        "cleared_fields": len(set(cleared_fields)),
        "tombstoned_languages": len(language_rows),
    }


def _fold_person_name(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.casefold() in _PLACEHOLDERS:
        return ""
    translated = raw.translate(_SPECIAL_TRANSLITERATION)
    decomposed = unicodedata.normalize("NFKD", translated)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return ascii_text.casefold()


def normalize_person_name_part(value: Any) -> str:
    """Fold case, accents and punctuation for deterministic identity matching."""

    return _NON_ALNUM_RE.sub("", _fold_person_name(value))


def _person_name_tokens(*values: Any) -> set[str]:
    return {
        token
        for value in values
        for token in _NON_ALNUM_RE.split(_fold_person_name(value))
        if len(token) >= _NAME_TOKEN_MIN_CHARS
    }


def _name_of_common_cv_words(*values: Any) -> bool:
    """Nazwa to wyłącznie częste słowa CV, więc porównanie z nią nic nie dowodzi.

    Bez odsiewu krótkich słów: „Li” jest rzadkie i ratuje nazwę, choć
    `_person_name_tokens` by je pominęło.
    """
    words = [
        word
        for value in values
        for word in _NON_ALNUM_RE.split(_fold_person_name(value))
        if word
    ]
    return bool(words) and only_common_cv_words(words)


def _name_parts_similar(left: str, right: str) -> bool:
    return (
        bool(left and right)
        and SequenceMatcher(None, left, right).ratio() >= _NAME_PART_SIMILAR_RATIO
    )


def _name_sound_key(value: str) -> str:
    """Znormalizowana część nazwy zapisana tak, jak brzmi w językach słowiańskich."""

    key = _REPEATED_CHAR_RE.sub(r"\1", value)
    for spelling, sound in _NAME_SOUND_REPLACEMENTS:
        key = key.replace(spelling, sound)
    return _REPEATED_CHAR_RE.sub(r"\1", key)


def _same_letters_other_split(
    first: str, last: str, other_first: str, other_last: str
) -> bool:
    """Te same litery, tylko inaczej podzielone na słowa („Ale Ksan Dra”)."""

    if not (first and last and other_first and other_last):
        return False
    name = first + last
    other = other_first + other_last
    swapped = other_last + other_first
    for left, right in ((name, other), (name, swapped), (last + first, other)):
        shorter, longer = sorted((left, right), key=len)
        if len(shorter) >= _SAME_LETTERS_MIN_CHARS and shorter in longer:
            return True
    return _name_parts_similar(name, other) or _name_parts_similar(name, swapped)


def profile_phone_in_other_form(candidate: Any, observed_phone: Any) -> bool:
    """Numer z profilu pochodzi spoza tego odczytu, a CV podaje te same cyfry.

    `_apply_cv_contact_fields` zapisuje numer surowo, więc zapis równy odczytowi,
    także zapisanemu wcześniej, mógł przyjść z tego samego pliku i niczego nie
    dowodzi. E-mail nie ma takiego sygnału: zapis idzie małymi literami.
    """

    observed = str(observed_phone or "").strip()
    if not observed:
        return False
    profile = str(candidate.phone or "").strip()
    profile_key = _normalize_phone(profile)
    if (
        not profile_key
        or len(profile_key) < _FULL_PHONE_DIGITS
        or profile_key != _normalize_phone(observed)
    ):
        return False
    stored_read = candidate.cv_extracted_data
    stored_phone = stored_read.get("phone") if isinstance(stored_read, dict) else None
    return profile not in {observed, str(stored_phone or "").strip()}


def identity_unreadable(first_name: Any, last_name: Any) -> bool:
    """Imię albo nazwisko jest wpisane, ale normalizacja nic z niego nie zostawia.

    Tak jest z zapisem cyrylicą: porównanie z odczytem CV zawsze kończy się
    ``inconclusive``, więc bramka nie odróżnia CV tej osoby od cudzego.
    """

    for value in (first_name, last_name):
        raw = str(value or "").strip()
        if raw.casefold() not in _PLACEHOLDERS and not normalize_person_name_part(raw):
            return True
    return False


def _fingerprint(first: str, last: str) -> str:
    # Names have too little entropy for an unkeyed digest. A domain-separated
    # HMAC supports reproducible provenance without enabling a dictionary
    # attack against leaked review rows.
    key = settings.CANDIDATE_IDENTITY_FINGERPRINT_KEY.strip()
    if not key:
        # Production configuration fails during Settings validation. Keep this
        # call-site fail-closed as well so a deliberately DEBUG deployment
        # cannot create fingerprints under an implicit or ephemeral key.
        raise RuntimeError(
            "CANDIDATE_IDENTITY_FINGERPRINT_KEY is required for identity evidence"
        )
    message = f"{IDENTITY_DETECTOR_VERSION}\x00{first}\x1f{last}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def evaluate_identity_match(
    *,
    candidate_first_name: Any,
    candidate_last_name: Any,
    observed_first_name: Any,
    observed_last_name: Any,
    profile_phone_other_form: bool = False,
) -> IdentityMatchResult:
    """Compare a parsed source identity with the canonical candidate identity."""

    candidate_first = normalize_person_name_part(candidate_first_name)
    candidate_last = normalize_person_name_part(candidate_last_name)
    observed_first = normalize_person_name_part(observed_first_name)
    observed_last = normalize_person_name_part(observed_last_name)
    # Pomiar 05.11.2026: 25 z 68 280 profili ma taką nazwę, żadna nie jest nazwą
    # osoby. Każde CV dawało przy niej mismatch, także to, z którego profil powstał.
    candidate_name_common = _name_of_common_cv_words(
        candidate_first_name, candidate_last_name
    )
    candidate_complete = bool(
        candidate_first and candidate_last and not candidate_name_common
    )
    observed_complete = bool(observed_first and observed_last)

    evidence: dict[str, bool | str] = {
        "candidate_identity_complete": candidate_complete,
        "candidate_name_only_common_cv_words": candidate_name_common,
        "observed_identity_complete": observed_complete,
        "first_name_match": bool(
            candidate_first and observed_first and candidate_first == observed_first
        ),
        "last_name_match": bool(
            candidate_last and observed_last and candidate_last == observed_last
        ),
        "name_order_swapped": bool(
            candidate_first
            and candidate_last
            and observed_first
            and observed_last
            and candidate_first == observed_last
            and candidate_last == observed_first
        ),
        # Imię i nazwisko bywają podzielone inaczej niż w CV (Traffit dzielił po
        # pierwszej spacji): to samo słowo po obu stronach nie dowodzi innej osoby.
        "shared_name_word": bool(
            _person_name_tokens(candidate_first_name, candidate_last_name)
            & _person_name_tokens(observed_first_name, observed_last_name)
        ),
        "similar_name_part": any(
            _name_parts_similar(left, right)
            for left, right in (
                (candidate_first, observed_first),
                (candidate_last, observed_last),
                (candidate_first, observed_last),
                (candidate_last, observed_first),
            )
        ),
        "similar_name_sound": any(
            _name_parts_similar(_name_sound_key(left), _name_sound_key(right))
            for left, right in (
                (candidate_first, observed_first),
                (candidate_last, observed_last),
                (candidate_first, observed_last),
                (candidate_last, observed_first),
            )
        ),
        "same_letters_other_split": _same_letters_other_split(
            candidate_first, candidate_last, observed_first, observed_last
        ),
        "profile_phone_other_form": profile_phone_other_form,
    }
    if candidate_complete:
        evidence["candidate_identity_fingerprint"] = _fingerprint(
            candidate_first, candidate_last
        )
    if observed_complete:
        evidence["observed_identity_fingerprint"] = _fingerprint(
            observed_first, observed_last
        )

    if not (candidate_complete and observed_complete):
        return IdentityMatchResult("inconclusive", evidence)
    if (evidence["first_name_match"] and evidence["last_name_match"]) or evidence[
        "name_order_swapped"
    ]:
        return IdentityMatchResult("confirmed_match", evidence)
    if (
        evidence["first_name_match"]
        or evidence["last_name_match"]
        or evidence["shared_name_word"]
        or evidence["similar_name_part"]
        or evidence["similar_name_sound"]
        or evidence["same_letters_other_split"]
        or evidence["profile_phone_other_form"]
    ):
        return IdentityMatchResult("inconclusive", evidence)
    return IdentityMatchResult("confirmed_mismatch", evidence)


def source_is_quarantined_clause(
    *,
    candidate_id_column: Any,
    source_id_column: Any,
    source_kind: SourceKind,
):
    """SQL expression true only for a live, non-overridden mismatch."""

    return exists(
        select(CandidateSourceIdentityReview.id).where(
            CandidateSourceIdentityReview.candidate_id == candidate_id_column,
            CandidateSourceIdentityReview.source_kind == source_kind,
            CandidateSourceIdentityReview.source_id == source_id_column,
            CandidateSourceIdentityReview.decision == "confirmed_mismatch",
            CandidateSourceIdentityReview.override_at.is_(None),
        )
    )


def source_is_eligible_clause(
    *,
    candidate_id_column: Any,
    source_id_column: Any,
    source_kind: SourceKind,
):
    """Fail closed for confirmed mismatches while retaining unknown sources."""

    return ~source_is_quarantined_clause(
        candidate_id_column=candidate_id_column,
        source_id_column=source_id_column,
        source_kind=source_kind,
    )


async def get_identity_review(
    db: AsyncSession,
    *,
    candidate_id: int,
    source_kind: SourceKind,
    source_id: int,
    for_update: bool = False,
) -> CandidateSourceIdentityReview | None:
    stmt = select(CandidateSourceIdentityReview).where(
        CandidateSourceIdentityReview.candidate_id == candidate_id,
        CandidateSourceIdentityReview.source_kind == source_kind,
        CandidateSourceIdentityReview.source_id == source_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def cv_bytes_quarantined(
    db: AsyncSession,
    *,
    candidate_id: int,
    content_sha256: str,
) -> bool:
    """Czy bajty ze wskaźnika kandydata to plik z kwarantanny tej osoby.

    `cv_storage_key` trzyma własną kopię pliku pod innym kluczem niż dokument
    (pomiar 05.11.2026: 0 z 254 równych kluczy, 66 z 243 tych samych bajtów), więc
    porównanie kluczy niczego nie wykrywa. Wskaźnika nie zdejmujemy, bo w pozostałych
    177 profilach to inny plik, a zwolnienie z kwarantanny ma działać bez naprawy.

    54 z tych 66 dokumentów nie ma zapisanego skrótu, więc liczymy go z bajtów. Gdy
    pliku nie da się odczytać, nie da się też wykluczyć kopii, dlatego odpowiedź
    brzmi „tak”: brak tekstu naprawia zwolnienie, cudzego tekstu nikt nie zauważy.
    """
    from fastapi.concurrency import run_in_threadpool

    from app.services import object_storage

    documents = (
        await db.execute(
            select(
                CandidateDocument.id,
                CandidateDocument.content_sha256,
                CandidateDocument.storage_key,
            ).where(
                CandidateDocument.candidate_id == candidate_id,
                source_is_quarantined_clause(
                    candidate_id_column=CandidateDocument.candidate_id,
                    source_id_column=CandidateDocument.id,
                    source_kind="document",
                ),
            )
        )
    ).all()
    if any(document.content_sha256 == content_sha256 for document in documents):
        return True
    for document in documents:
        if document.content_sha256:
            continue
        try:
            content = (
                await run_in_threadpool(
                    object_storage.download_cv, document.storage_key
                )
                if document.storage_key
                else await db.scalar(
                    select(CandidateDocument.file_content).where(
                        CandidateDocument.id == document.id
                    )
                )
            )
        except Exception as exc:  # noqa: BLE001 — bez bajtów nie ma dowodu na inny plik
            logger.warning(
                "[identity_quarantine] quarantined file unreadable document=%s: %s",
                document.id,
                type(exc).__name__,
            )
            return True
        if content and hashlib.sha256(bytes(content)).hexdigest() == content_sha256:
            return True
    return False


async def record_detected_identity(
    db: AsyncSession,
    *,
    candidate: Candidate,
    source_kind: SourceKind,
    source_id: int,
    observed_first_name: Any,
    observed_last_name: Any,
    provenance: str,
    replaced_primary: ReplacedPrimaryCv | None = None,
    observed_name_from_header: bool = False,
    observed_phone: Any = None,
    hold_mismatch_for_review: bool = False,
) -> CandidateSourceIdentityReview:
    """Persist an automatic decision without weakening a manual decision.

    `observed_name_from_header`: nazwę dała reguła nagłówka CV, nie model. Taka
    linia bywa stanowiskiem albo nazwą firmy (05.11.2026: w 4 z 9 przejrzanych
    plików nie była nazwą osoby), więc sama nie dowodzi cudzego pliku.

    `hold_mismatch_for_review`: sprzeczność nazw nie czyści profilu, tylko zostaje
    znacznikiem `MISMATCH_HELD_EVIDENCE` do przeglądu człowieka. Dla biegu
    masowego, bo nikt nie patrzy na wynik wiersz po wierszu, a 23 z 64 własnych CV
    z pomiaru 05.11.2026 nie da się odróżnić od cudzych po nazwie.
    """

    # Serialize first review creation and re-read the identity under the same
    # row lock.  ``candidate`` may have been loaded before a slow parser/model
    # call; comparing against that stale object could quarantine a document
    # after a recruiter has corrected the person's name concurrently.
    locked_candidate = await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked_candidate is None:
        raise IdentityQuarantineConflict("Candidate no longer exists")
    result = evaluate_identity_match(
        candidate_first_name=locked_candidate.name,
        candidate_last_name=locked_candidate.lastname,
        observed_first_name=observed_first_name,
        observed_last_name=observed_last_name,
        profile_phone_other_form=profile_phone_in_other_form(
            locked_candidate, observed_phone
        ),
    )
    mismatch = result.decision == "confirmed_mismatch"
    result = IdentityMatchResult(
        "inconclusive"
        if mismatch and (observed_name_from_header or hold_mismatch_for_review)
        else result.decision,
        {
            **result.evidence,
            "observed_name_from_header": observed_name_from_header,
            MISMATCH_HELD_EVIDENCE: mismatch and hold_mismatch_for_review,
        },
    )
    now = datetime.now(timezone.utc)
    row = await get_identity_review(
        db,
        candidate_id=candidate.id,
        source_kind=source_kind,
        source_id=source_id,
        for_update=True,
    )
    if row is not None and row.decision == "confirmed_mismatch":
        # Confirmed mismatch is a sticky safety decision. Parser retries,
        # model upgrades and newly incomplete names may never make the source
        # eligible again; only the explicit admin/HoR override does that.
        if row.is_quarantined and not hold_mismatch_for_review:
            await _purge_candidate_summary_cache(db, candidate.id)
            await _clear_quarantined_cv_projection(
                db,
                candidate_id=candidate.id,
                source_kind=source_kind,
                source_id=source_id,
                replaced_primary=replaced_primary,
            )
        return row
    if row is None:
        row = CandidateSourceIdentityReview(
            candidate_id=candidate.id,
            source_kind=source_kind,
            source_id=source_id,
            decision=result.decision,
            provenance=provenance[:80],
            detector_version=IDENTITY_DETECTOR_VERSION,
            evidence=result.evidence,
            reviewed_at=now,
        )
        db.add(row)
    elif row.provenance.startswith("manual:"):
        # A parser retry may not clear a human-confirmed mismatch or match.
        return row
    else:
        row.decision = result.decision
        row.provenance = provenance[:80]
        row.detector_version = IDENTITY_DETECTOR_VERSION
        row.evidence = result.evidence
        row.reviewed_at = now

    projection_stats = {"cleared_fields": 0, "tombstoned_languages": 0}
    if row.is_quarantined:
        await _purge_candidate_summary_cache(db, candidate.id)
        projection_stats = await _clear_quarantined_cv_projection(
            db,
            candidate_id=candidate.id,
            source_kind=source_kind,
            source_id=source_id,
            replaced_primary=replaced_primary,
        )
    if row.is_quarantined:
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.IDENTITY_SOURCE_QUARANTINED,
            user_id=None,
            entity_id=candidate.id,
            details={
                "source_kind": source_kind,
                "source_id": source_id,
                "provenance": provenance[:80],
                "detector_version": IDENTITY_DETECTOR_VERSION,
                **projection_stats,
            },
        )
    await db.flush()
    return row


async def mark_confirmed_mismatch(
    db: AsyncSession,
    *,
    candidate_id: int,
    source_kind: SourceKind,
    source_id: int,
    actor_id: int,
    provenance: str,
) -> CandidateSourceIdentityReview:
    """Human confirmation: quarantine a source and clear any old override."""

    source_text = (
        await _side_file_text(db, candidate_id=candidate_id, document_id=source_id)
        if source_kind == "document"
        else None
    )
    await db.execute(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    now = datetime.now(timezone.utc)
    row = await get_identity_review(
        db,
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
        for_update=True,
    )
    evidence = {"manual_confirmation": True}
    if row is None:
        row = CandidateSourceIdentityReview(
            candidate_id=candidate_id,
            source_kind=source_kind,
            source_id=source_id,
            decision="confirmed_mismatch",
            provenance=f"manual:{provenance}"[:80],
            detector_version=IDENTITY_DETECTOR_VERSION,
            evidence=evidence,
            reviewed_by_id=actor_id,
            reviewed_at=now,
        )
        db.add(row)
    else:
        row.decision = "confirmed_mismatch"
        row.provenance = f"manual:{provenance}"[:80]
        row.detector_version = IDENTITY_DETECTOR_VERSION
        row.evidence = evidence
        row.reviewed_by_id = actor_id
        row.reviewed_at = now
        row.override_reason = None
        row.override_by_id = None
        row.override_at = None

    projection_stats = await _clear_quarantined_cv_projection(
        db,
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
        source_text=source_text,
    )
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.IDENTITY_SOURCE_QUARANTINED,
        user_id=actor_id,
        entity_id=candidate_id,
        details={
            "source_kind": source_kind,
            "source_id": source_id,
            "provenance": provenance[:64],
            "detector_version": IDENTITY_DETECTOR_VERSION,
            **projection_stats,
        },
    )
    await _purge_candidate_summary_cache(db, candidate_id)
    await db.flush()
    return row


def _reopen_pointer_read(candidate: Candidate) -> None:
    """Zwolniony plik wraca do odczytu tekstu: wyrok `quarantined` jest końcowy.

    Gdy wskaźnik trzyma też kopię innego pliku z kwarantanny, następny bieg
    zapisze ten wyrok ponownie.
    """
    from app.services.cv_text_backfill import _EXTRACTION_MARKER_KEY, _QUARANTINED

    extracted = candidate.cv_extracted_data
    marker = (
        extracted.get(_EXTRACTION_MARKER_KEY) if isinstance(extracted, dict) else None
    )
    if isinstance(marker, dict) and marker.get("outcome") == _QUARANTINED:
        candidate.cv_extracted_data = {
            key: value
            for key, value in extracted.items()
            if key != _EXTRACTION_MARKER_KEY
        }


def _forget_released_source(
    candidate: Candidate, *, source_kind: SourceKind, source_id: int
) -> None:
    """Profil przestaje mówić, że ten plik czeka na zwolnienie.

    Bez tego ramka w profilu i dok rekrutacji nadal traktowały plik jak CV innej
    osoby. Odczytu to nie wstrzymuje: fakty z tego pliku wyczyściła kwarantanna
    (albo stoją na innym pliku), więc `profile_holds_read_of_file` i tak każe czytać.
    """
    extracted = candidate.cv_extracted_data
    marker = (
        extracted.get("_identity_quarantine_source")
        if isinstance(extracted, dict)
        else None
    )
    if marker == {"kind": source_kind, "id": source_id}:
        candidate.cv_extracted_data = {
            key: value
            for key, value in extracted.items()
            if key != "_identity_quarantine_source"
        }


async def override_identity_quarantine(
    db: AsyncSession,
    *,
    candidate_id: int,
    source_kind: SourceKind,
    source_id: int,
    actor: User,
    reason: str,
) -> CandidateSourceIdentityReview:
    """Release one mismatch; only admin/HoR can cross this domain boundary."""

    if not actor.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        raise IdentityQuarantineForbidden
    clean_reason = " ".join(reason.split()).strip()
    if len(clean_reason) < 3:
        raise ValueError("override reason is required")
    if len(clean_reason) > 500:
        raise ValueError("override reason must be at most 500 characters")

    # Ta sama kolejność blokad co przy zapisie decyzji: najpierw kandydat.
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    row = await get_identity_review(
        db,
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
        for_update=True,
    )
    if row is None or row.decision != "confirmed_mismatch":
        raise IdentityQuarantineConflict(
            "source has no confirmed identity mismatch to override"
        )

    now = datetime.now(timezone.utc)
    row.override_reason = clean_reason
    row.override_by_id = actor.id
    row.override_at = now
    if candidate is not None:
        _reopen_pointer_read(candidate)
        _forget_released_source(candidate, source_kind=source_kind, source_id=source_id)
    reason_sha256 = hashlib.sha256(clean_reason.encode("utf-8")).hexdigest()
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.IDENTITY_SOURCE_QUARANTINE_OVERRIDDEN,
        user_id=actor.id,
        entity_id=candidate_id,
        details={
            "source_kind": source_kind,
            "source_id": source_id,
            "reason_sha256": reason_sha256,
            "reason_length": len(clean_reason),
        },
    )
    await db.flush()
    return row
