"""Obserwacje stawki kandydata — wszystko, co kandydat powiedział o stawce.

Czyta (hurtowo, bez zawężania widoczności — to wejście liczenia „Stawki od”):

* karty rekomendacji (``recommendation_cards``: pole wpisane ręcznie wygrywa
  z polem z notatki), klucz ``card:{id}``;
* stawki z etapów (``candidate_stages.expected_rate_*``), klucz ``stage:{id}``;
* zmiany stawki profilu z dziennika (``profile_rate_changed``), klucz
  ``profile:{activity_id}`` — z oznaczeniem jawnego minimum;
* bieżącą stawkę profilu, gdy dziennik jej nie zna (stare wpisy, formularz
  kariery, scalanie), klucz ``profile-current``;
* stawki ze zgłoszeń osób już w bazie, klucz ``apply:{submission_id}``.

Stawki z umów (co płaciliśmy) są tylko do wyświetlenia — czyta je
``candidate_rate_overview``, nie ta funkcja.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.work_time import HOURS_PER_MD_DEC, HOURS_PER_MONTH_DEC
from app.services.candidate_audit import PROFILE_RATE_CHANGED

#: Źródła zapisu profilu, które znaczą „to jest minimum kandydata”.
MINIMUM_SOURCES = frozenset({"trainee_call", "manual_minimum", "stage_minimum"})

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class RateObservation:
    key: str
    candidate_id: int
    amount_hourly: Optional[Decimal]
    raw: Optional[str]
    at: Optional[datetime]
    source: str
    job_id: Optional[int] = None
    author_id: Optional[int] = None
    explicit_minimum: bool = False
    #: Powód, dla którego stawka nie jest porównywalna (inna waluta, jednostka).
    not_comparable: bool = False


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out > 0 else None


def _parse_at(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def card_rate_amount(field: Any) -> Optional[Decimal]:
    """Stawka z pola karty jako PLN/h; zakres „120–140” liczy się dolną granicą."""
    if not isinstance(field, Mapping):
        return None
    if field.get("currency") != "PLN" or field.get("period") != "h":
        return None
    return _decimal(field.get("value"))


def hourly_from_unit(
    value: Any, unit: Optional[str], currency: Optional[str]
) -> Optional[Decimal]:
    """Stawka etapu w PLN/h: dzień ÷ 8, miesiąc ÷ 168; inna waluta = brak."""
    amount = _decimal(value)
    if amount is None:
        return None
    if str(currency or "PLN").strip().upper() != "PLN":
        return None
    if unit == "hourly":
        hourly = amount
    elif unit == "daily":
        hourly = amount / HOURS_PER_MD_DEC
    elif unit == "monthly":
        hourly = amount / HOURS_PER_MONTH_DEC
    else:
        return None
    return hourly.quantize(_CENT)


def _card_observation(row: Mapping[str, Any]) -> Optional[RateObservation]:
    manual = row["manual_rate"]
    notes = row["notes_rate"]
    field = manual if isinstance(manual, Mapping) and manual.get("raw") else notes
    if not isinstance(field, Mapping) or not str(field.get("raw") or "").strip():
        return None
    is_manual = field is manual
    amount = card_rate_amount(field)
    return RateObservation(
        key=f"card:{row['id']}",
        candidate_id=row["candidate_id"],
        amount_hourly=amount,
        raw=str(field.get("raw") or "").strip() or None,
        at=_parse_at(field.get("at")) or row["updated_at"],
        source="card_manual" if is_manual else "card",
        job_id=row["job_id"],
        author_id=(field.get("by") if is_manual else row["note_author_id"]),
        not_comparable=amount is None,
    )


def _profile_observation(row: Mapping[str, Any]) -> Optional[RateObservation]:
    details = row["details"] or {}
    amount = _decimal(details.get("new_amount"))
    if amount is None:
        return None
    source = str(details.get("source") or "manual")
    explicit = details.get("rate_meaning") == "minimum" or source in MINIMUM_SOURCES
    return RateObservation(
        key=f"profile:{row['id']}",
        candidate_id=row["candidate_id"],
        amount_hourly=amount,
        raw=None,
        at=row["created_at"],
        source=f"profile_{source}",
        author_id=row["user_id"],
        explicit_minimum=explicit,
    )


#: Poprawka tej samej osoby w tym czasie zastępuje poprzedni wpis profilu —
#: literówka „15” poprawiona na „150” nie zostaje „Stawką od” na 18 miesięcy.
QUICK_CORRECTION = timedelta(minutes=10)
# dzień UTC celowo: wartość zastępcza do sortowania wpisów bez daty, nie data kalendarzowa
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _without_quick_corrections(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wpisy dziennika profilu bez tych, które ta sama osoba zaraz poprawiła."""
    ordered = sorted(
        rows,
        key=lambda r: (r["candidate_id"], r["created_at"] or _EPOCH, r["id"]),
    )
    kept: list[dict[str, Any]] = []
    for index, row in enumerate(ordered):
        nxt = ordered[index + 1] if index + 1 < len(ordered) else None
        if (
            nxt is not None
            and nxt["candidate_id"] == row["candidate_id"]
            and nxt["user_id"] is not None
            and nxt["user_id"] == row["user_id"]
            and row["created_at"] is not None
            and nxt["created_at"] is not None
            and nxt["created_at"] - row["created_at"] <= QUICK_CORRECTION
        ):
            continue
        kept.append(row)
    return kept


_CARDS_SQL = text(
    "SELECT rc.id, rc.candidate_id, rc.job_id, rc.updated_at, "
    "rc.fields_manual->'rate' AS manual_rate, rc.fields_notes->'rate' AS notes_rate, "
    "n.author_id AS note_author_id "
    "FROM recommendation_cards rc "
    "LEFT JOIN notes n ON n.id = CASE WHEN (rc.fields_notes->'rate'->>'note_id') ~ '^[0-9]+$' "
    "THEN (rc.fields_notes->'rate'->>'note_id')::int END "
    "WHERE rc.candidate_id = ANY(:ids) "
    "AND (rc.fields_notes ? 'rate' OR rc.fields_manual ? 'rate')"
)

_STAGES_SQL = text(
    "SELECT id, candidate_id, job_id, expected_rate_value, expected_rate_unit::text AS unit, "
    "expected_rate_currency, moved_at, moved_by "
    "FROM candidate_stages WHERE candidate_id = ANY(:ids) "
    "AND expected_rate_value IS NOT NULL"
)

_PROFILE_SQL = text(
    "SELECT id, entity_id AS candidate_id, user_id, created_at, details "
    "FROM activities WHERE entity_type = 'candidate' AND action = :action "
    "AND entity_id = ANY(:ids)"
)

_CURRENT_SQL = text(
    "SELECT id, expected_rate_hourly, expected_rate_currency, "
    "profile_rate_updated_at, created_at FROM candidates WHERE id = ANY(:ids)"
)

_SUBMISSIONS_SQL = text(
    "SELECT id, matched_candidate_id AS candidate_id, job_id, created_at, "
    "raw_payload->>'expected_rate_hourly' AS rate "
    "FROM application_submissions WHERE matched_candidate_id = ANY(:ids) "
    "AND raw_payload ? 'expected_rate_hourly'"
)


async def collect(
    db: AsyncSession, candidate_ids: Iterable[int]
) -> dict[int, list[RateObservation]]:
    """Obserwacje każdego kandydata (pusta lista, gdy nic nie powiedział)."""
    ids = sorted({int(cid) for cid in candidate_ids})
    out: dict[int, list[RateObservation]] = {cid: [] for cid in ids}
    if not ids:
        return out
    params = {"ids": ids}

    for row in (await db.execute(_CARDS_SQL, params)).mappings():
        obs = _card_observation(row)
        if obs is not None:
            out[obs.candidate_id].append(obs)

    for row in (await db.execute(_STAGES_SQL, params)).mappings():
        amount = hourly_from_unit(
            row["expected_rate_value"], row["unit"], row["expected_rate_currency"]
        )
        unit = {"hourly": "h", "daily": "dzień", "monthly": "mies."}.get(
            row["unit"] or "", "?"
        )
        out[row["candidate_id"]].append(
            RateObservation(
                key=f"stage:{row['id']}",
                candidate_id=row["candidate_id"],
                amount_hourly=amount,
                raw=(
                    f"{Decimal(row['expected_rate_value']).normalize():f} "
                    f"{row['expected_rate_currency'] or 'PLN'}/{unit}"
                ),
                at=row["moved_at"],
                source="stage",
                job_id=row["job_id"],
                author_id=row["moved_by"],
                not_comparable=amount is None,
            )
        )

    known_profile_amounts: dict[int, set[Decimal]] = defaultdict(set)
    profile_rows = [
        dict(row)
        for row in (
            await db.execute(_PROFILE_SQL, {**params, "action": PROFILE_RATE_CHANGED})
        ).mappings()
    ]
    for row in _without_quick_corrections(profile_rows):
        obs = _profile_observation(row)
        if obs is not None:
            out[obs.candidate_id].append(obs)
    for row in profile_rows:
        amount = _decimal((row["details"] or {}).get("new_amount"))
        if amount is not None:
            known_profile_amounts[row["candidate_id"]].add(amount)

    for row in (await db.execute(_CURRENT_SQL, params)).mappings():
        amount = _decimal(row["expected_rate_hourly"])
        currency = str(row["expected_rate_currency"] or "").strip().upper()
        if amount is None or currency not in {"", "PLN"}:
            continue
        if amount in known_profile_amounts.get(row["id"], set()):
            continue
        out[row["id"]].append(
            RateObservation(
                key="profile-current",
                candidate_id=row["id"],
                amount_hourly=amount,
                raw=None,
                at=row["profile_rate_updated_at"] or row["created_at"],
                source="profile",
            )
        )

    for row in (await db.execute(_SUBMISSIONS_SQL, params)).mappings():
        amount = _decimal(row["rate"])
        out[row["candidate_id"]].append(
            RateObservation(
                key=f"apply:{row['id']}",
                candidate_id=row["candidate_id"],
                amount_hourly=amount,
                raw=None,
                at=row["created_at"],
                source="application",
                job_id=row["job_id"],
                not_comparable=amount is None,
            )
        )
    return out
