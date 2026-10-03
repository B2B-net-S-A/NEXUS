"""Stawka do klienta z wpisów Delivery Leada w notatkach (etap 8, 03.10.2026).

W Traffit Delivery Lead zapisywał cenę wysłania kandydata notatką („Wyślijmy
za 161 zł/h”). W NEXUSIE ta liczba ma własne pole etapu
(``candidate_stages.client_rate_*``), a notatki rodzaju ``dl_rate`` są zakryte
dla rekrutera. Ten moduł przenosi JEDNOZNACZNE wpisy do pola — nic nie kasuje
i niczego nie nadpisuje:

* tylko notatka z rekrutacją, z jedną kwotą i czasownikiem wysyłki przed nią
  („wyślijmy / wysyłamy / wysłany za N”); para kwot („150/110”), sama liczba
  przy wzmiance, inna waluta albo stawka dzienna/miesięczna zostają w notatce;
* tylko para (kandydat, rekrutacja), która nie ma stawki do klienta na żadnym
  wierszu etapu; kwota trafia na pierwszy wiersz „CV wysłane” albo późniejszy;
* para z dwiema różnymi kwotami w notatkach jest pomijana — nie zgadujemy.

Plan liczy ta sama funkcja dla próby i zapisu; zapis dotyka wyłącznie wierszy,
które w chwili UPDATE nadal mają puste pole.
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import note_kinds

RECEIPT_KEY = "client_rate_notes_backfill_2026_10"
# Kwoty leżą pod kluczem innego kształtu — publiczny odczyt paragonów migracji
# go nie drukuje.
DETAILS_KEY = "repair_details_client_rate_notes_backfill_2026_10"

RATE_MIN, RATE_MAX = 40, 400
# Etapy, na których kandydat był już u klienta — tam należy cena wysłania.
SENT_STAGES: tuple[str, ...] = (
    "cv_sent",
    "client_interview",
    "acceptance",
    "negotiation",
    "hired",
    "onboarding",
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MENTION_RE = re.compile(r"@[^\s@]+ [^\s@]+|\$\$user_\d+\$\$")
_AMOUNT_RE = re.compile(r"(?<![\d.,/])\d{2,3}(?:[.,]\d{1,2})?(?![\d/])")
_SEND_RE = re.compile(
    r"(?:wy[sś]l\w*|wysy[lł]a\w*|wys[lł]an\w*)\s+(?:go |j[aą] |cv )?(?:za|po)\s+"
    r"(\d{2,3})(?:[.,](\d{1,2}))?(?![\d/])"
)
_OTHER_UNIT_RE = re.compile(r"eur|usd|€|\$|\bmd\b|dzie[nń]|dniówk|mies|brutto")


def extract_client_rate(content: Optional[str]) -> Optional[Decimal]:
    """Stawka do klienta w PLN/h z wpisu Delivery Leada albo ``None``.

    Zwraca kwotę tylko wtedy, gdy notatka niesie dokładnie jedną liczbę i stoi
    ona po czasowniku wysyłki. Każda wątpliwość = ``None`` (wpis zostaje
    w notatce i nic się z nim nie dzieje).
    """
    plain = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", content or ""))).lower()
    plain = _MENTION_RE.sub(" ", plain)
    if _OTHER_UNIT_RE.search(plain):
        return None
    match = _SEND_RE.search(plain)
    if match is None or len(_AMOUNT_RE.findall(plain)) != 1:
        return None
    value = Decimal(f"{match.group(1)}.{(match.group(2) or '0').ljust(2, '0')}")
    return value if RATE_MIN <= value <= RATE_MAX else None


@dataclass(frozen=True)
class PlannedRate:
    stage_id: int
    candidate_id: int
    job_id: int
    note_id: int
    value: Decimal


_NOTES_SQL = text(
    f"""
    SELECT id, candidate_id, job_id, content
      FROM notes
     WHERE kind = '{note_kinds.DL_RATE}'
       AND parent_note_id IS NULL
       AND source_deleted_at IS NULL
       AND candidate_id IS NOT NULL
       AND job_id IS NOT NULL
     ORDER BY created_at, id
    """
)

_STAGES_SQL = text(
    """
    SELECT id, candidate_id, job_id, stage::text AS stage, client_rate_value
      FROM candidate_stages
     WHERE (candidate_id, job_id) IN (
               SELECT * FROM unnest(CAST(:candidates AS int[]), CAST(:jobs AS int[]))
           )
     ORDER BY moved_at, id
    """
)


async def build_plan(db: AsyncSession) -> tuple[list[PlannedRate], dict[str, int]]:
    """(wiersze do uzupełnienia, liczniki). Czysty odczyt."""
    counts: Counter[str] = Counter()
    by_pair: dict[tuple[int, int], list[tuple[int, Decimal]]] = {}
    for row in (await db.execute(_NOTES_SQL)).all():
        counts["notes_with_job"] += 1
        value = extract_client_rate(row.content)
        if value is None:
            counts["notes_not_unambiguous"] += 1
            continue
        by_pair.setdefault((row.candidate_id, row.job_id), []).append((row.id, value))
    counts["pairs_with_rate_note"] = len(by_pair)

    candidates: dict[tuple[int, int], tuple[int, Decimal]] = {}
    for pair, found in by_pair.items():
        if len({value for _, value in found}) > 1:
            counts["pairs_with_different_amounts"] += 1
            continue
        candidates[pair] = found[-1]
    if not candidates:
        return [], dict(counts)

    stages: dict[tuple[int, int], list[Any]] = {}
    for row in (
        await db.execute(
            _STAGES_SQL,
            {
                "candidates": [pair[0] for pair in candidates],
                "jobs": [pair[1] for pair in candidates],
            },
        )
    ).all():
        stages.setdefault((row.candidate_id, row.job_id), []).append(row)

    plan: list[PlannedRate] = []
    for pair, (note_id, value) in candidates.items():
        rows = stages.get(pair, [])
        if not rows:
            counts["pairs_without_stage"] += 1
        elif any(row.client_rate_value is not None for row in rows):
            counts["pairs_already_have_rate"] += 1
        else:
            target = next((row for row in rows if row.stage in SENT_STAGES), None)
            if target is None:
                counts["pairs_never_sent"] += 1
                continue
            plan.append(
                PlannedRate(
                    stage_id=target.id,
                    candidate_id=pair[0],
                    job_id=pair[1],
                    note_id=note_id,
                    value=value,
                )
            )
    counts["to_fill"] = len(plan)
    return plan, dict(counts)


_APPLY_SQL = text(
    """
    UPDATE candidate_stages
       SET client_rate_value = :value,
           client_rate_unit = 'hourly',
           client_rate_currency = 'PLN'
     WHERE id = :stage_id
       AND client_rate_value IS NULL
    """
)

_RECEIPT_SQL = text(
    """
    INSERT INTO app_settings (key, value, updated_at)
    VALUES (:key, CAST(:value AS jsonb), now())
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
    """
)


async def apply_plan(
    db: AsyncSession, plan: list[PlannedRate], counts: dict[str, int], *, user_id: int
) -> dict[str, Any]:
    """Zapisuje plan; wiersz, który w międzyczasie dostał stawkę, zostaje."""
    filled: list[PlannedRate] = []
    for item in plan:
        result = await db.execute(
            _APPLY_SQL, {"value": item.value, "stage_id": item.stage_id}
        )
        if result.rowcount:
            filled.append(item)
    now = datetime.now(timezone.utc).isoformat()
    receipt = {
        "applied_at": now,
        "applied_by": user_id,
        "counts": {**counts, "filled": len(filled)},
        "stage_ids": [item.stage_id for item in filled],
    }
    details = {
        "applied_at": now,
        "rows": [
            {
                "stage_id": item.stage_id,
                "note_id": item.note_id,
                "value": str(item.value),
            }
            for item in filled
        ],
    }
    await db.execute(_RECEIPT_SQL, {"key": RECEIPT_KEY, "value": json.dumps(receipt)})
    await db.execute(_RECEIPT_SQL, {"key": DETAILS_KEY, "value": json.dumps(details)})
    return receipt
