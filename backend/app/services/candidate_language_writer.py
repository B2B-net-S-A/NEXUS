"""Single writer for normalized candidate-language facts.

Manual profile edits use the OCC-aware profile-facts service.  Every automated
source (CV, Traffit, Talent Radar, CSV and the legacy backfill) enters through
this module, which deliberately has weaker authority:

* a manually locked fact is never changed or removed;
* a tombstoned fact is never reactivated;
* descriptive proficiency labels stay ``unknown`` (they are not promoted to
  CEFR without an explicit CEFR token from the source);
* the legacy JSONB column is only a compatibility projection of active facts.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_language import CandidateLanguage

AutomatedLanguageSource = Literal[
    "cv",
    "traffit",
    "talent_radar",
    "csv",
    "legacy",
    "unknown",
]

_CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
_NATIVE_LABELS = {
    "native",
    "native speaker",
    "mother tongue",
    "ojczysty",
    "język ojczysty",
    "jezyk ojczysty",
    "rodzimy",
}
_LANGUAGE_CODES = {
    "polish": "pl",
    "polski": "pl",
    "english": "en",
    "angielski": "en",
    "german": "de",
    "deutsch": "de",
    "niemiecki": "de",
    "french": "fr",
    "francuski": "fr",
    "spanish": "es",
    "hiszpanski": "es",
    "hiszpański": "es",
    "italian": "it",
    "wloski": "it",
    "włoski": "it",
    "ukrainian": "uk",
    "ukrainski": "uk",
    "ukraiński": "uk",
    "russian": "ru",
    "rosyjski": "ru",
    "czech": "cs",
    "czeski": "cs",
    "slovak": "sk",
    "slowacki": "sk",
    "słowacki": "sk",
    "dutch": "nl",
    "holenderski": "nl",
    "swedish": "sv",
    "szwedzki": "sv",
    "norwegian": "no",
    "norweski": "no",
    "danish": "da",
    "dunski": "da",
    "duński": "da",
    "finnish": "fi",
    "finski": "fi",
    "fiński": "fi",
    "portuguese": "pt",
    "portugalski": "pt",
    "romanian": "ro",
    "rumunski": "ro",
    "rumuński": "ro",
    "hungarian": "hu",
    "wegierski": "hu",
    "węgierski": "hu",
}
_INLINE_LEVEL_RE = re.compile(
    r"^(?P<name>.+?)(?:\s*[-:–—]\s*|\s*\(\s*|\s+)"
    r"(?P<level>A1|A2|B1|B2|C1|C2|native speaker|native|mother tongue|"
    r"ojczysty|język ojczysty|jezyk ojczysty|fluent|advanced|intermediate|"
    r"basic|beginner|biegły|biegly|zaawansowany|średniozaawansowany|"
    r"sredniozaawansowany|podstawowy)\)?$",
    re.IGNORECASE,
)
_LANGUAGE_NAME_TRANSLITERATION = str.maketrans(
    {
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "ø": "o",
        "Ø": "O",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ß": "ss",
    }
)


@dataclass(frozen=True)
class NormalizedLanguage:
    language_code: str
    language_name: str
    cefr_level: str | None
    is_native: bool
    is_level_unknown: bool


@dataclass(frozen=True)
class LanguageWriteResult:
    parsed: int
    invalid: int
    inserted: int
    updated: int
    tombstoned: int
    protected_manual: int
    protected_tombstone: int
    changed: bool


def _ascii_slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in folded if not unicodedata.combining(char))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    if 2 <= len(slug) <= 16 and re.fullmatch(r"[a-z][a-z0-9-]+", slug):
        return slug
    compact = re.sub(r"[^a-z0-9]", "", slug)
    return f"x-{compact[:14] or 'unknown'}"


def _language_name_identity(value: str) -> str:
    translated = value.translate(_LANGUAGE_NAME_TRANSLITERATION)
    decomposed = unicodedata.normalize("NFKD", translated)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


def _language_code(name: str, explicit_code: Any = None) -> str:
    if isinstance(explicit_code, str):
        candidate = explicit_code.strip().casefold().replace("_", "-")
        if re.fullmatch(r"[a-z][a-z0-9-]{1,15}", candidate):
            return candidate
    key = " ".join(name.casefold().split())
    return _LANGUAGE_CODES.get(key, _ascii_slug(name))


def _proficiency(raw: Any) -> tuple[str | None, bool, bool]:
    """Return CEFR/native/unknown without guessing from descriptive labels."""

    if isinstance(raw, str):
        label = " ".join(raw.strip().split())
        upper = label.upper()
        if upper in _CEFR_LEVELS:
            return upper, False, False
        if label.casefold() in _NATIVE_LABELS:
            return None, True, False
    return None, False, True


def _proficiency_rank(language: NormalizedLanguage) -> int:
    if language.is_native:
        return 99
    if language.cefr_level in _CEFR_LEVELS:
        return _CEFR_LEVELS.index(language.cefr_level)
    return -1


def _split_string_items(value: str) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for raw_part in re.split(r"[,;\n]+", value):
        part = " ".join(raw_part.split())
        if not part:
            continue
        match = _INLINE_LEVEL_RE.fullmatch(part)
        if match:
            items.append((match.group("name").strip(), match.group("level")))
        else:
            items.append((part, None))
    return items


def _raw_language_items(raw: Any) -> Iterable[tuple[str, Any, Any]]:
    if raw is None:
        return
    if isinstance(raw, str):
        for name, level in _split_string_items(raw):
            yield name, level, None
        return
    if isinstance(raw, dict):
        has_named_shape = bool({"name", "language", "lang", "code"} & raw.keys())
        named = raw.get("name") or raw.get("language") or raw.get("lang")
        if named:
            explicit_code = raw.get("code")
            # Some source records contain ``{"lang": "Polish, English"}``.
            for name, inline_level in _split_string_items(str(named)):
                yield (
                    name,
                    raw.get("level") if inline_level is None else inline_level,
                    (explicit_code if not re.search(r"[,;\n]", str(named)) else None),
                )
            return
        explicit_code = raw.get("code")
        if isinstance(explicit_code, str):
            normalized_code = explicit_code.strip().casefold().replace("_", "-")
            if re.fullmatch(r"[a-z][a-z0-9-]{1,15}", normalized_code):
                # Legacy payloads sometimes contain only ``code`` + ``level``.
                # Keep the source spelling as the display name; no translation
                # or guessed language label is introduced during backfill.
                yield explicit_code.strip(), raw.get("level"), explicit_code
                return
        if has_named_shape:
            yield "", None, None
            return
        # Legacy flat-map shape: {"EN": "B2", "PL": "native"}.
        for code, level in raw.items():
            yield str(code), level, code
        return
    if isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        for item in raw:
            yield from _raw_language_items(item)
        return
    yield "", None, None


def normalize_language_payload(raw: Any) -> tuple[list[NormalizedLanguage], int]:
    """Normalize source shapes and deduplicate by code and display identity."""

    normalized: dict[str, NormalizedLanguage] = {}
    invalid = 0
    for raw_name, raw_level, explicit_code in _raw_language_items(raw):
        name = " ".join(str(raw_name).split())[:100]
        if not name:
            invalid += 1
            continue
        code = _language_code(name, explicit_code)
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,15}", code):
            invalid += 1
            continue
        cefr, native, unknown = _proficiency(raw_level)
        item = NormalizedLanguage(
            language_code=code,
            language_name=name,
            cefr_level=cefr,
            is_native=native,
            is_level_unknown=unknown,
        )
        previous = normalized.get(code)
        if previous is None:
            normalized[code] = item
            continue
        # Deterministic conflict handling inside one source snapshot: native is
        # strongest, then the highest explicit CEFR, then unknown.
        if _proficiency_rank(item) > _proficiency_rank(previous):
            normalized[code] = item

    by_name: dict[str, NormalizedLanguage] = {}
    for item in normalized.values():
        name_identity = _language_name_identity(item.language_name)
        previous = by_name.get(name_identity)
        if previous is None or _proficiency_rank(item) > _proficiency_rank(previous):
            by_name[name_identity] = item
    return sorted(by_name.values(), key=lambda item: item.language_code), invalid


def language_projection(rows: Iterable[CandidateLanguage]) -> list[dict[str, object]]:
    projected: list[dict[str, object]] = []
    for row in sorted(rows, key=lambda item: item.language_code):
        if row.deleted_at is not None:
            continue
        level = (
            "native"
            if row.is_native
            else ("unknown" if row.is_level_unknown else row.cefr_level)
        )
        projected.append(
            {
                "code": row.language_code.upper(),
                "lang": row.language_name,
                "level": level,
            }
        )
    return projected


def merge_automated_languages(
    *,
    candidate_id: int,
    existing_rows: list[CandidateLanguage],
    incoming: Sequence[NormalizedLanguage],
    provenance: AutomatedLanguageSource,
    source_ref: str | None,
    replace_source_snapshot: bool,
    now: datetime | None = None,
) -> tuple[list[CandidateLanguage], LanguageWriteResult]:
    """Pure mutation core used by the DB writer and unit tests."""

    timestamp = now or datetime.now(timezone.utc)
    by_code = {row.language_code: row for row in existing_rows}
    desired = {item.language_code: item for item in incoming}
    inserted = updated = tombstoned = protected_manual = protected_tombstone = 0

    for code, item in desired.items():
        row = by_code.get(code)
        if row is not None:
            if row.deleted_at is not None:
                protected_tombstone += 1
                continue
            if row.manual_lock:
                protected_manual += 1
                continue
            next_values = (
                item.language_name,
                item.cefr_level,
                item.is_native,
                item.is_level_unknown,
                provenance,
                source_ref,
            )
            current_values = (
                row.language_name,
                row.cefr_level,
                row.is_native,
                row.is_level_unknown,
                row.provenance,
                row.source_ref,
            )
            if next_values != current_values:
                (
                    row.language_name,
                    row.cefr_level,
                    row.is_native,
                    row.is_level_unknown,
                    row.provenance,
                    row.source_ref,
                ) = next_values
                row.version += 1
                updated += 1
            continue

        row = CandidateLanguage(
            candidate_id=candidate_id,
            language_code=item.language_code,
            language_name=item.language_name,
            cefr_level=item.cefr_level,
            is_native=item.is_native,
            is_level_unknown=item.is_level_unknown,
            provenance=provenance,
            manual_lock=False,
            source_ref=source_ref,
            version=1,
        )
        existing_rows.append(row)
        by_code[code] = row
        inserted += 1

    if replace_source_snapshot:
        for code, row in by_code.items():
            if code in desired or row.deleted_at is not None:
                continue
            if row.manual_lock:
                protected_manual += 1
                continue
            if row.provenance != provenance:
                continue
            row.deleted_at = timestamp
            row.version += 1
            tombstoned += 1

    changed = bool(inserted or updated or tombstoned)
    return existing_rows, LanguageWriteResult(
        parsed=len(incoming),
        invalid=0,
        inserted=inserted,
        updated=updated,
        tombstoned=tombstoned,
        protected_manual=protected_manual,
        protected_tombstone=protected_tombstone,
        changed=changed,
    )


async def sync_candidate_languages_from_source(
    db: AsyncSession,
    *,
    candidate_id: int,
    raw_languages: Any,
    provenance: AutomatedLanguageSource,
    source_ref: str | None = None,
    replace_source_snapshot: bool = True,
) -> LanguageWriteResult:
    """Normalize and persist one complete automated source snapshot."""

    incoming, invalid = normalize_language_payload(raw_languages)
    candidate = await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if candidate is None:
        raise LookupError(f"candidate {candidate_id} not found")
    rows = list(
        (
            await db.scalars(
                select(CandidateLanguage)
                .where(CandidateLanguage.candidate_id == candidate_id)
                .order_by(CandidateLanguage.id.asc())
            )
        ).all()
    )
    rows, result = merge_automated_languages(
        candidate_id=candidate_id,
        existing_rows=rows,
        incoming=incoming,
        provenance=provenance,
        source_ref=(source_ref or None)[:255] if source_ref else None,
        replace_source_snapshot=replace_source_snapshot,
    )
    for row in rows:
        if row.id is None:
            db.add(row)
    projection = language_projection(rows)
    projection_changed = candidate.languages != projection
    if result.changed or projection_changed:
        candidate.languages = projection
        candidate.languages_version = int(candidate.languages_version or 1) + 1
        await db.flush()
    return LanguageWriteResult(
        parsed=result.parsed,
        invalid=invalid,
        inserted=result.inserted,
        updated=result.updated,
        tombstoned=result.tombstoned,
        protected_manual=result.protected_manual,
        protected_tombstone=result.protected_tombstone,
        changed=result.changed or projection_changed,
    )
