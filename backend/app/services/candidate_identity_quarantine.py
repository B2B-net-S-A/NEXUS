"""Identity-mismatch quarantine for candidate-bound source material.

The detector is intentionally conservative: an automatic mismatch is only
confirmed when both identities have a usable first name and surname and both
parts disagree after transliteration.  Missing surnames and partial
disagreement stay ``inconclusive`` so a name change or parsing failure cannot
silently quarantine a legitimate source.

Raw names and free text never enter the review row or audit event.  Only
booleans and keyed SHA-256 fingerprints are retained as provenance.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
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


async def _clear_quarantined_cv_projection(
    db: AsyncSession,
    *,
    candidate_id: int,
    source_kind: SourceKind,
    source_id: int,
) -> dict[str, Any]:
    """Remove only facts provably projected from the quarantined CV source."""

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
    if (
        document is not None
        and document.is_primary
        and candidate.cv_filename
        and candidate.cv_filename == document.filename
    ):
        owns_projection = True
    if document is not None:
        # A quarantined source must not remain the selected CV even when legacy
        # rows have no source_document_id provenance.
        document.is_primary = False
    if not owns_projection:
        return {"cleared_fields": 0, "tombstoned_languages": 0}

    cleared_fields: list[str] = []

    def clear_if_equal(attribute: str, parsed_key: str) -> None:
        parsed_value = extracted.get(parsed_key)
        if (
            parsed_value is not None
            and getattr(candidate, attribute, None) == parsed_value
            and not extracted.get(f"_manual_override_{parsed_key}")
        ):
            setattr(candidate, attribute, None)
            cleared_fields.append(attribute)

    candidate.raw_cv_text = None
    cleared_fields.append("raw_cv_text")
    if source_kind == "legacy_cv" or (
        document is not None and candidate.cv_filename == document.filename
    ):
        candidate.cv_filename = None
        cleared_fields.append("cv_filename")
    candidate.cv_parsed_at = None
    cleared_fields.append("cv_parsed_at")
    if candidate.ai_summary is not None:
        candidate.ai_summary = None
        cleared_fields.append("ai_summary")

    if extracted.get("skills") is not None and candidate.skills == extracted.get(
        "skills"
    ):
        candidate.skills = []
        cleared_fields.append("skills")
    if extracted.get("education") is not None and candidate.education == extracted.get(
        "education"
    ):
        candidate.education = []
        cleared_fields.append("education")
    expected_experience = [
        {
            "company": name,
            "role": None,
            "start": None,
            "end": None,
            "desc": None,
        }
        for name in (extracted.get("companies") or [])
    ]
    if (
        expected_experience
        and candidate.experience == expected_experience
        and not extracted.get("_manual_override_experience")
    ):
        candidate.experience = []
        cleared_fields.append("experience")
    if extracted.get(
        "years_it_experience"
    ) is not None and candidate.years_it_experience == extracted.get(
        "years_it_experience"
    ):
        candidate.years_it_experience = None
        cleared_fields.append("years_it_experience")

    clear_if_equal("email", "email")
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
    if extracted.get("linkedin_url") and candidate.linkedin == extracted.get(
        "linkedin_url"
    ):
        candidate.linkedin = None
        cleared_fields.append("linkedin")

    # Keep only explicit locks and integration-owned metadata. Raw parser
    # output can itself describe the wrong person.
    candidate.cv_extracted_data = {
        key: value
        for key, value in extracted.items()
        if key.startswith("_manual_override_") or key.startswith("traffit_")
    }
    candidate.cv_extracted_data["_identity_quarantine_source"] = {
        "kind": source_kind,
        "id": source_id,
    }

    source_refs = _quarantined_cv_language_source_refs(
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
        document_hash=document.content_sha256 if document is not None else None,
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


def normalize_person_name_part(value: Any) -> str:
    """Fold case, accents and punctuation for deterministic identity matching."""

    raw = str(value or "").strip()
    if raw.casefold() in _PLACEHOLDERS:
        return ""
    translated = raw.translate(_SPECIAL_TRANSLITERATION)
    decomposed = unicodedata.normalize("NFKD", translated)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_ALNUM_RE.sub("", ascii_text.casefold())


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
) -> IdentityMatchResult:
    """Compare a parsed source identity with the canonical candidate identity."""

    candidate_first = normalize_person_name_part(candidate_first_name)
    candidate_last = normalize_person_name_part(candidate_last_name)
    observed_first = normalize_person_name_part(observed_first_name)
    observed_last = normalize_person_name_part(observed_last_name)
    candidate_complete = bool(candidate_first and candidate_last)
    observed_complete = bool(observed_first and observed_last)

    evidence: dict[str, bool | str] = {
        "candidate_identity_complete": candidate_complete,
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
    if not evidence["first_name_match"] and not evidence["last_name_match"]:
        return IdentityMatchResult("confirmed_mismatch", evidence)
    return IdentityMatchResult("inconclusive", evidence)


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


async def record_detected_identity(
    db: AsyncSession,
    *,
    candidate: Candidate,
    source_kind: SourceKind,
    source_id: int,
    observed_first_name: Any,
    observed_last_name: Any,
    provenance: str,
) -> CandidateSourceIdentityReview:
    """Persist an automatic decision without weakening a manual decision."""

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
        if row.is_quarantined:
            await _purge_candidate_summary_cache(db, candidate.id)
            await _clear_quarantined_cv_projection(
                db,
                candidate_id=candidate.id,
                source_kind=source_kind,
                source_id=source_id,
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
