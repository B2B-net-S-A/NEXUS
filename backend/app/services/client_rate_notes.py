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
* para z dwiema różnymi kwotami albo z dodatkowym wpisem o cenie, którego nie
  da się odczytać, jest pomijana — nie zgadujemy.

Plan liczy ta sama funkcja dla próby i zapisu. Sam zapis idzie przez wspólną
warstwę zapisu etapów (``recruitment_process_commands``) i dotyka wyłącznie
par, które pod blokadą nadal nie mają stawki na żadnym wierszu etapu.
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
# Po kwocie może stać WYŁĄCZNIE to, co znaczy „złotych za godzinę”: nic,
# „zł/PLN”, „/h”, „netto”, „+ VAT” — a potem koniec zdania. Biała lista zamiast
# listy zakazów: „160 GBP”, „160 zł/mc”, „150%”, „150 tys.” i „161,555” nie
# przechodzą, bo nie pasują do wzoru, a nie dlatego, że ktoś je przewidział.
_SEND_RE = re.compile(
    r"(?:wy[sś]l\w*|wysy[lł]a\w*|wys[lł]an\w*)\s+(?:go |j[aą] |cv )?(?:za|po)\s+"
    r"(\d{2,3})(?:[.,](\d{1,2}))?(?![.,]?\d)"
    r"(?:\s*(?:zł|zl|pln))?(?:\s*/\s*(?:h|godz\w*))?(?:\s*netto)?(?:\s*\+\s*vat)?"
    r"(?=\s*(?:[.,;!)]|$))"
)
# Przeczenie, warunek albo pytanie: „nie wysyłamy za 160”, „jeśli klient się
# zgodzi…”, „wyślijmy za 160?” — to nie jest zapisana cena.
_DOUBT_RE = re.compile(
    r"\b(?:nie|bez|ani|czy|chyba|mo[zż]e|gdyby|albo|lub)\b|je[sś]li|je[zż]eli|\?"
)


def _plain(content: Optional[str]) -> str:
    plain = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", content or ""))).lower()
    return _MENTION_RE.sub(" ", plain).strip()


def extract_client_rate(content: Optional[str]) -> Optional[Decimal]:
    """Stawka do klienta w PLN/h z wpisu Delivery Leada albo ``None``.

    Zwraca kwotę tylko wtedy, gdy notatka niesie dokładnie jedną liczbę, stoi
    ona po czasowniku wysyłki, po niej jest najwyżej „zł / h / netto / + VAT”
    i koniec zdania, a w treści nie ma przeczenia, warunku ani pytania. Każda
    wątpliwość = ``None`` (wpis zostaje w notatce i nic się z nim nie dzieje).
    """
    plain = _plain(content)
    if _DOUBT_RE.search(plain):
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
    unclear_pairs: set[tuple[int, int]] = set()
    for row in (await db.execute(_NOTES_SQL)).all():
        counts["notes_with_job"] += 1
        pair = (row.candidate_id, row.job_id)
        value = extract_client_rate(row.content)
        if value is None:
            counts["notes_not_unambiguous"] += 1
            unclear_pairs.add(pair)
            continue
        by_pair.setdefault(pair, []).append((row.id, value))
    counts["pairs_with_rate_note"] = len(by_pair)

    candidates: dict[tuple[int, int], tuple[int, Decimal]] = {}
    for pair, found in by_pair.items():
        # Drugi wpis o cenie, którego nie da się odczytać („160/130”, sama
        # liczba przy wzmiance), mógł ją zmienić — nie zgadujemy, który ważny.
        if pair in unclear_pairs:
            counts["pairs_with_unclear_note"] += 1
        elif len({value for _, value in found}) > 1:
            counts["pairs_with_different_amounts"] += 1
        else:
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


_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext(:key))")
_READ_SQL = text("SELECT value FROM app_settings WHERE key = :key")
_WRITE_SQL = text(
    """
    INSERT INTO app_settings (key, value, updated_at)
    VALUES (:key, CAST(:value AS jsonb), now())
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
    """
)


async def lock_for_apply(db: AsyncSession) -> None:
    """Jeden zapis naraz — plan liczymy dopiero pod tą blokadą."""
    await db.execute(_LOCK_SQL, {"key": RECEIPT_KEY})


async def _stored(db: AsyncSession, key: str) -> dict[str, Any]:
    value = await db.scalar(_READ_SQL, {"key": key})
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


async def apply_plan(
    db: AsyncSession, plan: list[PlannedRate], counts: dict[str, int], *, user_id: int
) -> dict[str, Any]:
    """Zapisuje plan; para, która w międzyczasie dostała stawkę, zostaje.

    Paragon i szczegóły są DOPISYWANE do poprzednich przebiegów: lista
    ``rows`` (wiersz etapu, notatka, kwota) to jedyna droga odwrócenia zapisu,
    więc kolejny przebieg nie może jej zastąpić.
    """
    # Import w funkcji: reguła odczytu kwoty ma zostać lekkim modułem, a pola
    # etapu wolno zmieniać tylko przez wspólną warstwę zapisu.
    from app.services import recruitment_process_commands

    filled: list[PlannedRate] = []
    for item in plan:
        if await recruitment_process_commands.fill_missing_client_rate(
            db,
            stage_id=item.stage_id,
            rate_value=item.value,
            rate_unit="hourly",
            rate_currency="PLN",
        ):
            filled.append(item)
    run = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "applied_by": user_id,
        "counts": {**counts, "filled": len(filled)},
        "stage_ids": [item.stage_id for item in filled],
    }
    if not filled:
        return run
    receipt = await _stored(db, RECEIPT_KEY)
    details = await _stored(db, DETAILS_KEY)
    receipt["runs"] = [*receipt.get("runs", []), run]
    details["rows"] = [
        *details.get("rows", []),
        *(
            {
                "stage_id": item.stage_id,
                "note_id": item.note_id,
                "value": str(item.value),
                "applied_at": run["applied_at"],
            }
            for item in filled
        ),
    ]
    await db.execute(_WRITE_SQL, {"key": RECEIPT_KEY, "value": json.dumps(receipt)})
    await db.execute(_WRITE_SQL, {"key": DETAILS_KEY, "value": json.dumps(details)})
    return run
