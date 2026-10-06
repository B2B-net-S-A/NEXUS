"""Cofnięcie stawek profilu wpisanych przez scrapery (audyt 06.10.2026, D5).

Scraper pracuj.pl/JJIT (klient OAuth, użytkownik serwisowy) wpisywał stawkę
profilu ``PATCH /api/candidates/{id}/profile-rate`` jako ręczną
(``source='manual'``): dolny próg widełek UoP z formularza ÷ 168 h — np.
48 zł/h. Taka liczba wyglądała jak stawka B2B podana przez kandydata, a znacznik
``_manual_override_rate`` blokował nocny odczyt notatek. Zmierzone 06.10.2026:
1 901 zapisów.

Reguła (decyzja Artura 06.10.2026): cofamy KAŻDY taki zapis, którego nikt
później nie zmienił — wersja stawki profilu kandydata jest dalej tą z ostatniego
zapisu scrapera. Kilka zapisów scrapera z rzędu (wersja N+1 po N) cofa się
łańcuchem do stawki sprzed pierwszego. Na kandydata, pod blokadą wiersza:

* stawka profilu = stawka sprzed scrapera (``write_profile_rate``, źródło
  ``scraper_revert``) z datą POPRZEDNIEJ stawki, nie dzisiejszą;
* znacznik ``_manual_override_rate`` znika, chyba że wcześniej stawkę wpisał
  człowiek;
* każdy zapis scrapera dostaje „Nie licz jako minimum” w ``candidate_rate_decisions``
  (klucz ``profile:{activity_id}``, kwota i data z dziennika) — inaczej „Stawka
  od” dalej liczyłaby 48 zł/h z historii;
* przeliczenie dopasowań (``mark_stale_for_candidate``) i „Stawki od”.

Notatka scrapera zostaje (nic nie znika); jej linię „szacunek stawki B2B …”
nocny odczyt faktów pomija (``notes_insights_extractor.build_notes_blob``).

Paragon ``scraper_rate_revert_2026_10`` = liczby i ID; kwoty (do odwrócenia)
pod ``repair_details_scraper_rate_revert_2026_10``.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.services.candidate_audit import PROFILE_RATE_SCRAPER_REVERTED
from app.services.candidate_profile_rate import is_canonical_profile_rate_currency

RECEIPT_KEY = "scraper_rate_revert_2026_10"
DETAILS_KEY = "repair_details_scraper_rate_revert_2026_10"
REVERT_SOURCE = "scraper_revert"
REVERT_ACTION = PROFILE_RATE_SCRAPER_REVERTED
SAMPLE_SIZE = 20
#: Kandydaci na jedną transakcję (blokady wierszy trzymane do commita).
CHUNK = 200

#: Źródła zapisu stawki przez człowieka — po nich znacznik „ręcznie” zostaje.
HUMAN_RATE_SOURCES = frozenset(
    {"manual", "manual_minimum", "notes_confirmed", "trainee_call", "stage_minimum"}
)

_SCRAPER_WRITES_SQL = text(
    """
    SELECT a.id, a.entity_id AS candidate_id, a.created_at, a.details, a.user_id
    FROM activities a
    WHERE a.entity_type = 'candidate'
      AND a.action = 'profile_rate_changed'
      AND a.details ->> 'source' = 'manual'
      AND a.user_id IN (
          SELECT oc.acting_user_id FROM oauth_clients oc
          WHERE oc.acting_user_id IS NOT NULL
      )
    ORDER BY a.entity_id, a.created_at, a.id
    """
)

# Bieżąca stawka i OSTATNI wpis dziennika stawki — sama wersja nie wystarcza:
# scalenie kandydatów przepina dziennik duplikatu (z jego numerami wersji) na
# ocalałego, więc zapis scrapera 0→1 bywa „bieżący” obok ręcznej stawki 0→1
# (przegląd PR #2055).
_VERSIONS_SQL = text(
    """
    SELECT c.id, c.profile_rate_version, c.expected_rate_hourly,
           c.expected_rate_currency,
           (SELECT a.id FROM activities a
             WHERE a.entity_type = 'candidate' AND a.entity_id = c.id
               AND a.action = 'profile_rate_changed'
             ORDER BY a.created_at DESC, a.id DESC LIMIT 1) AS latest_activity_id
    FROM candidates c WHERE c.id = ANY(:ids)
    """
)

_LATEST_SQL = text(
    """
    SELECT a.id FROM activities a
    WHERE a.entity_type = 'candidate' AND a.entity_id = :cid
      AND a.action = 'profile_rate_changed'
    ORDER BY a.created_at DESC, a.id DESC LIMIT 1
    """
)

_UNCHECKED: Any = object()

# Wcześniejsze zapisy stawki tego kandydata (data poprzedniej stawki, właściciel).
_EARLIER_SQL = text(
    """
    SELECT a.created_at, a.details ->> 'source' AS source,
           (a.user_id IN (SELECT oc.acting_user_id FROM oauth_clients oc
                          WHERE oc.acting_user_id IS NOT NULL)) AS by_integration
    FROM activities a
    WHERE a.entity_type = 'candidate' AND a.entity_id = :cid
      AND a.action = 'profile_rate_changed'
      AND (a.created_at, a.id) < (:at, :aid)
    ORDER BY a.created_at DESC, a.id DESC
    """
)

_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext(:key))")
_READ_SQL = text("SELECT value FROM app_settings WHERE key = :key")
_WRITE_SQL = text(
    """
    INSERT INTO app_settings (key, value, updated_at)
    VALUES (:key, CAST(:value AS jsonb), now())
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
    """
)
_DECISION_SQL = text(
    "INSERT INTO candidate_rate_decisions "
    "(candidate_id, observation_key, decision, observed_amount, observed_at, "
    "decided_by) VALUES (:cid, :key, 'exclude', :amount, :at, :uid) "
    "ON CONFLICT (candidate_id, observation_key) DO UPDATE SET "
    "decision = 'exclude', observed_amount = :amount, observed_at = :at, "
    "decided_by = :uid, decided_at = now()"
)


def _amount(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out.quantize(Decimal("0.01")) if out.is_finite() else None


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ScraperWrite:
    activity_id: int
    created_at: datetime
    old_amount: Optional[Decimal]
    new_amount: Optional[Decimal]
    old_version: int
    new_version: int
    accepts_below_min_rate_cleared: Any = None
    old_currency: Optional[str] = None


@dataclass
class PlannedRevert:
    candidate_id: int
    #: Zapisy scrapera do cofnięcia, od najstarszego.
    chain: list[ScraperWrite] = field(default_factory=list)

    @property
    def expected_version(self) -> int:
        return self.chain[-1].new_version

    @property
    def restore_amount(self) -> Optional[Decimal]:
        return self.chain[0].old_amount

    @property
    def scraper_amount(self) -> Optional[Decimal]:
        return self.chain[-1].new_amount


def _parse(row: Any) -> Optional[ScraperWrite]:
    details = row["details"] if isinstance(row["details"], dict) else {}
    old_version = _int(details.get("old_version"))
    new_version = _int(details.get("new_version"))
    if old_version is None or new_version is None:
        return None
    return ScraperWrite(
        activity_id=int(row["id"]),
        created_at=row["created_at"],
        old_amount=_amount(details.get("old_amount")),
        new_amount=_amount(details.get("new_amount")),
        old_version=old_version,
        new_version=new_version,
        accepts_below_min_rate_cleared=details.get("accepts_below_min_rate_cleared"),
        old_currency=details.get("old_currency"),
    )


def _same_amount(a: Optional[Decimal], b: Any) -> bool:
    return _amount(b) == a


def plan_for_candidate(
    writes: list[ScraperWrite],
    current_version: Optional[int],
    *,
    current_amount: Any = _UNCHECKED,
    current_currency: Any = _UNCHECKED,
    latest_activity_id: Any = _UNCHECKED,
) -> tuple[Optional[list[ScraperWrite]], str]:
    """Łańcuch zapisów scrapera kończący się na bieżącej wersji albo powód.

    Czyste — bez bazy. Zapis, po którym ktoś zmienił stawkę (wersja bieżąca
    inna), zostaje: decyzja człowieka wygrywa ze sprzątaniem. Poza wersją
    bieżąca stawka musi być kwotą scrapera w PLN, a ostatni wpis dziennika
    stawki — zapisem scrapera (scalenie kandydatów dubluje numery wersji).
    """
    if current_version is None:
        return None, "candidate_missing"
    by_new = {w.new_version: w for w in writes}
    head = by_new.get(current_version)
    if head is None:
        return None, "changed_after_scraper"
    if current_amount is not _UNCHECKED and (
        not _same_amount(head.new_amount, current_amount)
        or (
            current_currency is not _UNCHECKED
            and not is_canonical_profile_rate_currency(current_currency)
        )
    ):
        return None, "rate_differs"
    if latest_activity_id is not _UNCHECKED and latest_activity_id != head.activity_id:
        return None, "later_rate_change"
    chain = [head]
    while (prev := by_new.get(chain[0].old_version)) is not None and prev not in chain:
        chain.insert(0, prev)
    # Stawka sprzed scrapera w innej walucie niż PLN: ``write_profile_rate``
    # zapisuje zawsze PLN/h, więc „50 EUR” wróciłoby jako 50 zł/h — zostaje
    # do decyzji człowieka.
    first = chain[0]
    if first.old_amount is not None and not is_canonical_profile_rate_currency(
        first.old_currency
    ):
        return None, "non_pln_previous"
    return chain, "to_revert"


async def build_plan(db: AsyncSession) -> tuple[list[PlannedRevert], dict[str, int]]:
    """Plan cofnięcia (tylko odczyt)."""
    counts: Counter[str] = Counter()
    by_candidate: dict[int, list[ScraperWrite]] = {}
    for row in (await db.execute(_SCRAPER_WRITES_SQL)).mappings():
        counts["scraper_writes"] += 1
        # Konto, które pisało — do sprawdzenia w próbie, że to wyłącznie konta
        # serwisowe integracji, a nie rekruter podpięty jako acting_user.
        counts[f"writes_by_user_{row['user_id']}"] += 1
        parsed = _parse(row)
        if parsed is None:
            counts["writes_without_version"] += 1
            continue
        by_candidate.setdefault(int(row["candidate_id"]), []).append(parsed)
    counts["candidates_with_scraper_writes"] = len(by_candidate)
    current: dict[int, Any] = {}
    if by_candidate:
        for row in (
            await db.execute(_VERSIONS_SQL, {"ids": sorted(by_candidate)})
        ).mappings():
            current[int(row["id"])] = row
    plan: list[PlannedRevert] = []
    for candidate_id in sorted(by_candidate):
        row = current.get(candidate_id)
        if row is None:
            chain, reason = None, "candidate_missing"
        else:
            chain, reason = plan_for_candidate(
                by_candidate[candidate_id],
                int(row["profile_rate_version"] or 0),
                current_amount=row["expected_rate_hourly"],
                current_currency=row["expected_rate_currency"],
                latest_activity_id=row["latest_activity_id"],
            )
        if chain is None:
            counts[reason] += 1
            continue
        plan.append(PlannedRevert(candidate_id=candidate_id, chain=chain))
    counts["to_revert"] = len(plan)
    counts["writes_to_exclude"] = sum(len(p.chain) for p in plan)
    counts["restored_to_empty"] = sum(1 for p in plan if p.restore_amount is None)
    return plan, dict(counts)


def sample(plan: list[PlannedRevert]) -> list[dict[str, Any]]:
    """Przykłady do próby — same identyfikatory (trasa tylko dla admina)."""
    return [
        {
            "candidate_id": item.candidate_id,
            "activity_ids": [w.activity_id for w in item.chain],
            "restored_to_empty": item.restore_amount is None,
        }
        for item in plan[:SAMPLE_SIZE]
    ]


async def lock_for_apply(db: AsyncSession) -> None:
    """Jeden zapis naraz — plan liczymy dopiero pod tą blokadą."""
    await db.execute(_LOCK_SQL, {"key": RECEIPT_KEY})


async def _stored(db: AsyncSession, key: str) -> dict[str, Any]:
    value = await db.scalar(_READ_SQL, {"key": key})
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


async def _revert_one(
    db: AsyncSession, item: PlannedRevert, *, user_id: int
) -> Optional[dict[str, Any]]:
    """Cofnij zapisy scrapera jednego kandydata. ``None`` = zmienił się w międzyczasie."""
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.services.candidate_profile_rate import write_profile_rate
    from app.services.match_score_cache import mark_stale_for_candidate

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == item.candidate_id).with_for_update()
    )
    if (
        candidate is None
        or (candidate.profile_rate_version or 0) != item.expected_version
        or not _same_amount(item.scraper_amount, candidate.expected_rate_hourly)
        or not is_canonical_profile_rate_currency(candidate.expected_rate_currency)
        or await db.scalar(_LATEST_SQL, {"cid": item.candidate_id})
        != item.chain[-1].activity_id
    ):
        return None
    first = item.chain[0]
    earlier = (
        (
            await db.execute(
                _EARLIER_SQL,
                {
                    "cid": item.candidate_id,
                    "at": first.created_at,
                    "aid": first.activity_id,
                },
            )
        )
        .mappings()
        .all()
    )
    previous_rate_at = earlier[0]["created_at"] if earlier else None
    human_owned = any(
        (row["source"] in HUMAN_RATE_SOURCES) and not row["by_integration"]
        for row in earlier
    )
    restored = item.restore_amount
    details = write_profile_rate(
        candidate,
        restored,
        source=REVERT_SOURCE,
        rate_updated_at=previous_rate_at if restored is not None else None,
    )
    # Zgoda praktykanta „poniżej minimum” skasowana zapisem scrapera wraca
    # (dotyczyła stawki, którą właśnie przywracamy).
    if first.accepts_below_min_rate_cleared is not None:
        candidate.accepts_below_min_rate = first.accepts_below_min_rate_cleared
    extracted = (
        dict(candidate.cv_extracted_data)
        if isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    if not human_owned and extracted.pop("_manual_override_rate", None) is not None:
        details["manual_override_rate_dropped"] = True
        candidate.cv_extracted_data = extracted
        flag_modified(candidate, "cv_extracted_data")
    details["reverted_activity_ids"] = [w.activity_id for w in item.chain]
    for write in item.chain:
        await db.execute(
            _DECISION_SQL,
            {
                "cid": item.candidate_id,
                "key": f"profile:{write.activity_id}",
                "amount": write.new_amount,
                "at": write.created_at,
                "uid": user_id,
            },
        )
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=item.candidate_id,
            action=REVERT_ACTION,
            user_id=user_id,
            details=details,
        )
    )
    await mark_stale_for_candidate(db, item.candidate_id)
    await db.flush()
    return {
        "candidate_id": item.candidate_id,
        "activity_ids": [w.activity_id for w in item.chain],
        "scraper_amount": str(item.scraper_amount)
        if item.scraper_amount is not None
        else None,
        "restored_amount": str(restored) if restored is not None else None,
        "previous_rate_at": previous_rate_at.isoformat() if previous_rate_at else None,
        "manual_override_rate_dropped": bool(
            details.get("manual_override_rate_dropped")
        ),
    }


async def apply_plan(
    db: AsyncSession, plan: list[PlannedRevert], counts: dict[str, int], *, user_id: int
) -> dict[str, Any]:
    """Zapis planu paczkami po ``CHUNK`` z commitem; kandydat zmieniony od
    próby zostaje. Paragon i dane odwrócenia DOPISYWANE w tej samej transakcji
    co paczka — przerwany bieg zostawia ślad tego, co zdążył zrobić, a
    ponowny bieg (nowa próba, nowe ``expected``) bierze tylko resztę.
    """
    from app.services.candidate_rate_from import recompute_safely

    applied_at = datetime.now(timezone.utc).isoformat()
    reverted_ids: list[int] = []
    changed = 0
    for start in range(0, len(plan), CHUNK):
        if start:
            # Commit poprzedniej paczki zwolnił blokadę doradczą.
            await lock_for_apply(db)
        chunk_entries: list[dict[str, Any]] = []
        for item in plan[start : start + CHUNK]:
            async with db.begin_nested():
                entry = await _revert_one(db, item, user_id=user_id)
            if entry is None:
                changed += 1
                continue
            chunk_entries.append(entry)
        if chunk_entries:
            await recompute_safely(db, [e["candidate_id"] for e in chunk_entries])
            details = await _stored(db, DETAILS_KEY)
            details["rows"] = [
                *details.get("rows", []),
                *({**e, "applied_at": applied_at} for e in chunk_entries),
            ]
            await db.execute(
                _WRITE_SQL, {"key": DETAILS_KEY, "value": json.dumps(details)}
            )
            reverted_ids.extend(e["candidate_id"] for e in chunk_entries)
            run = {
                "applied_at": applied_at,
                "applied_by": user_id,
                "counts": {
                    **counts,
                    "reverted": len(reverted_ids),
                    "changed_meanwhile": changed,
                },
                "candidate_ids": list(reverted_ids),
            }
            receipt = await _stored(db, RECEIPT_KEY)
            runs = [
                r for r in receipt.get("runs", []) if r.get("applied_at") != applied_at
            ]
            receipt["runs"] = [*runs, run]
            await db.execute(
                _WRITE_SQL, {"key": RECEIPT_KEY, "value": json.dumps(receipt)}
            )
        await db.commit()
    return {
        "applied_at": applied_at,
        "applied_by": user_id,
        "counts": {
            **counts,
            "reverted": len(reverted_ids),
            "changed_meanwhile": changed,
        },
        "candidate_ids": reverted_ids,
    }


__all__ = [
    "DETAILS_KEY",
    "RECEIPT_KEY",
    "REVERT_SOURCE",
    "PlannedRevert",
    "ScraperWrite",
    "apply_plan",
    "build_plan",
    "lock_for_apply",
    "plan_for_candidate",
    "sample",
]
