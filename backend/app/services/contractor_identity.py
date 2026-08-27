"""Canonical identity key for aggregate contractor headcounts.

NEXUS has no dedicated contractor entity: a person can have several Candidate
rows and several simultaneous Contracts.  Business headcounts therefore must
not use either ``candidate_id`` or ``contract_id`` as the identity key.

The agreed rule is deliberately narrow:

* normally, normalized first name + surname identify one contractor;
* exactly Filip Jablonski is a known real-name collision, so his normalized
  candidate-profile e-mail is an additional key component.

Contract counts remain separate.  This module only answers "how many people?".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Hashable, Protocol

from sqlalchemy import String, and_, case, cast, func


_FILIP_JABLONSKI = ("filip", "jablonski")
_SQL_SINGLE_CHAR_DIACRITICS = "ąćęłńóśźżđðøàáâãäåçèéêëìíîïñòôõöùúûüýÿčďěňřšťž"
_SQL_SINGLE_CHAR_ASCII = "acelnoszzddoaaaaaaceeeeiiiinoooouuuuyycdenrstz"
_SQL_MULTI_CHAR_TRANSLITERATION = (("æ", "ae"), ("œ", "oe"), ("ß", "ss"))
_NAME_PLACEHOLDERS = (
    "",
    "?",
    "-",
    "nieznane",
    "nieznany",
    "unknown",
    "n/a",
    "na",
)
_PY_SINGLE_CHAR_TRANSLATION = str.maketrans(
    dict(zip(_SQL_SINGLE_CHAR_DIACRITICS, _SQL_SINGLE_CHAR_ASCII, strict=True))
)


class ContractorIdentitySource(Protocol):
    """Small structural type shared by ORM Candidates and lightweight rows."""

    id: int
    name: str
    lastname: str
    email: str | None


def normalize_contractor_email(value: Any) -> str:
    """Normalize the exceptional e-mail discriminator without guessing it."""

    return str(value or "").strip().lower()


def normalize_contractor_name_part(value: Any) -> str:
    """Normalize a name while preserving every Unicode alphabet.

    The candidate source-document matcher intentionally emits ASCII only.
    Reusing it here made Cyrillic, Greek or Arabic names empty and therefore
    split one person by ``candidate_id``.  Headcounts instead apply the same
    explicit transliterations as SQL and retain every remaining Unicode
    alphanumeric character.
    """

    raw = str(value or "").strip().lower()
    if raw in _NAME_PLACEHOLDERS:
        return ""
    folded = raw.translate(_PY_SINGLE_CHAR_TRANSLATION)
    for source, replacement in _SQL_MULTI_CHAR_TRANSLITERATION:
        folded = folded.replace(source, replacement)
    return "".join(character for character in folded if character.isalnum())


def contractor_identity_key(
    first_name: Any,
    last_name: Any,
    email: Any = None,
    *,
    fallback_id: Hashable | None = None,
) -> tuple[Hashable, ...]:
    """Return the business key used by every active-contractor headcount.

    Name normalization folds case, surrounding/internal punctuation and Polish
    diacritics, so display variants such as ``" PIOTR "`` / ``"Piotr"`` and
    ``"Jabłoński"`` / ``"Jablonski"`` agree.  Invalid/placeholder names do
    not all collapse into one fictional person: callers can provide the
    Candidate id as a fail-closed fallback.
    """

    first = normalize_contractor_name_part(first_name)
    last = normalize_contractor_name_part(last_name)

    if not first or not last:
        if fallback_id is not None:
            return ("candidate", fallback_id)
        return ("name", first, last)

    if (first, last) == _FILIP_JABLONSKI:
        normalized_email = normalize_contractor_email(email)
        if normalized_email:
            return ("name_email", first, last, normalized_email)
        # There are two real people with this exact name.  Without the agreed
        # discriminator, merging would be a knowingly unsafe guess.  Candidate
        # id is only a fail-safe for the incomplete exceptional profile.
        return ("name_email_missing", first, last, fallback_id)

    return ("name", first, last)


def contractor_identity_sql_expression(
    first_name,
    last_name,
    email,
    candidate_id,
):
    """SQL expression mirroring the key for grouped/count-distinct queries.

    Postgres ``translate`` + ``replace`` mirror the supported Latin
    transliteration without relying on ICU or the optional ``unaccent``
    extension. Remaining Unicode letters are preserved when the database uses
    a Unicode-aware ``LC_CTYPE``/collation (the production requirement); a
    ``C``/``POSIX`` locale only guarantees ASCII character classes. This is the
    database-side path used where counts participate in directory
    sorting/pagination.
    """

    def _name_part(column):
        raw = func.lower(func.btrim(func.coalesce(column, "")))
        folded = func.translate(
            raw,
            _SQL_SINGLE_CHAR_DIACRITICS,
            _SQL_SINGLE_CHAR_ASCII,
        )
        for source, replacement in _SQL_MULTI_CHAR_TRANSLITERATION:
            folded = func.replace(folded, source, replacement)
        # POSIX ``alnum`` follows the database locale.  With the required
        # Unicode-aware locale it preserves alphabets such as Cyrillic; a
        # C/POSIX locale only guarantees ASCII classification.
        normalized = func.regexp_replace(folded, "[^[:alnum:]]+", "", "g")
        return case((raw.in_(_NAME_PLACEHOLDERS), ""), else_=normalized)

    first = _name_part(first_name)
    last = _name_part(last_name)
    normalized_email = func.lower(func.btrim(func.coalesce(email, "")))
    fallback = func.concat("candidate:", cast(candidate_id, String))
    filip_key = case(
        (
            normalized_email != "",
            func.concat("name_email:filip:jablonski:", normalized_email),
        ),
        else_=func.concat(
            "name_email_missing:filip:jablonski:", cast(candidate_id, String)
        ),
    )
    return case(
        (func.length(first) == 0, fallback),
        (func.length(last) == 0, fallback),
        (
            and_(first == _FILIP_JABLONSKI[0], last == _FILIP_JABLONSKI[1]),
            filip_key,
        ),
        else_=func.concat("name:", first, ":", last),
    )


def candidate_identity_key(candidate: ContractorIdentitySource) -> tuple[Hashable, ...]:
    """Identity key for an ORM Candidate or a compatible query row."""

    return contractor_identity_key(
        candidate.name,
        candidate.lastname,
        candidate.email,
        fallback_id=candidate.id,
    )


def unique_contractor_keys(
    candidates: Iterable[ContractorIdentitySource | None],
) -> set[tuple[Hashable, ...]]:
    """Collect unique person keys, ignoring detached contracts (no Candidate)."""

    return {
        candidate_identity_key(candidate)
        for candidate in candidates
        if candidate is not None
    }


def count_unique_contractors(
    candidates: Iterable[ContractorIdentitySource | None],
) -> int:
    """Count people according to :func:`contractor_identity_key`."""

    return len(unique_contractor_keys(candidates))


@dataclass(frozen=True, slots=True)
class ContractorHeadcount:
    """Explicitly keep people and contracts apart in API/report payloads."""

    contractors: int
    active_contracts: int


def summarize_active_contracts(contracts: Iterable[Any]) -> ContractorHeadcount:
    """Return person headcount and raw contract count from loaded Contracts.

    Callers must eager-load ``Contract.candidate`` before invoking this helper;
    doing so keeps async endpoints free from implicit lazy-loading.
    """

    rows = list(contracts)
    return ContractorHeadcount(
        contractors=count_unique_contractors(
            getattr(contract, "candidate", None) for contract in rows
        ),
        active_contracts=len(rows),
    )
