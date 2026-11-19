"""Jednorazowe sprzątanie zdublowanych i mylnych aneksów kontraktów (19.11.2026).

Odczyt produkcji 19.11.2026: na 130 aneksów kontraktów trzy kontrakty miały po
2–3 identyczne aneksy, a w jednym pomyłkę wpisu poprawiano kolejnymi aneksami.
Wszystkie powstały ręcznie w oknie „Dodaj aneks” 29.06–10.07.2026 przy
wprowadzaniu wstecz. Aneksu nie da się usunąć w aplikacji, a od 19.11.2026
okno nie przyjmuje już takich wpisów (`contract_amendment_guard`). Decyzja Artura
z 19.11.2026: usunąć je jednorazową naprawą.

Usuwamy:

- aneksy-duplikaty: 3 i 29 (#155, jak aneks 1), 31 (#116, jak aneks 7) i 20
  (#444, jak aneks 19);
- poprawkę wpisu w #398: aneks 47 („przedłużenie” skracające koniec z 31.08 na
  31.07) i aneks 48 (ta sama stawka co w zrzucie, inny dzień wejścia); aneksy 45
  i 46 zostają;
- identyczne kroki harmonogramu: stawka kandydata 6 i 17 (#155, jak krok 5), 31
  (#116, jak krok 30) i 197 (#263, jak krok 198 z podpisanego aneksu 97) oraz
  stawka klienta 22 (#398, ta sama stawka co krok 23 od 01.07).

Każdy cel jest przypięty do stanu z 19.11.2026 (kontrakt, typ, dzień). Gdy stan
się zmienił albo coś na cel wskazuje, cel jest pomijany z kodem powodu. Krok
znika tylko wtedy, gdy harmonogram bez niego daje tę samą stawkę w każdym dniu
(resolver kontraktu), więc kwoty się nie zmieniają.

Paragon pod ``REPAIR_MARKER`` niesie liczby, ID, daty i kody powodów. Usunięte
wiersze w całości (z kwotami, do ewentualnego odtworzenia) leżą pod
``DETAILS_KEY``. Ten klucz nie zaczyna się od numeru rewizji, więc publiczny
workflow paragonów go nie drukuje (`scripts/show_migration_receipts.py`).
Historia kontraktu dostaje wpis ``amendment_history_cleaned`` z samymi ID.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, NamedTuple, Optional, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.contract import Contract
from app.models.contract_amendment import ContractAmendment
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate

logger = logging.getLogger(__name__)

REPAIR_MARKER = "contract_amendment_history_cleanup_2026_11_19"
DETAILS_KEY = "repair_details_contract_amendment_history_2026_11_19"
ACTIVITY_ACTION = "amendment_history_cleaned"


class AmendmentTarget(NamedTuple):
    amendment_id: int
    contract_id: int
    amendment_type: str
    effective_date: date
    # Aneks, który zostaje i ma identyczne ``new_values``.
    duplicate_of: Optional[int] = None
    # Poprawka wpisu: „przedłużenie” z ``old_end`` na wcześniejsze ``new_end``.
    old_end: Optional[date] = None
    new_end: Optional[date] = None
    # Poprawka wpisu: stawka klienta równa zrzutowi ``old_values`` (bez kandydata).
    same_client_rate_as_snapshot: bool = False


class StepTarget(NamedTuple):
    schedule: str  # "candidate" | "client"
    step_id: int
    contract_id: int
    effective_from: date
    # Krok, który zostaje i daje tę samą stawkę.
    same_as: int


AMENDMENTS: tuple[AmendmentTarget, ...] = (
    AmendmentTarget(3, 155, "rate_change", date(2026, 7, 1), duplicate_of=1),
    AmendmentTarget(29, 155, "rate_change", date(2026, 7, 1), duplicate_of=1),
    AmendmentTarget(31, 116, "rate_change", date(2026, 8, 1), duplicate_of=7),
    AmendmentTarget(20, 444, "extension", date(2026, 7, 1), duplicate_of=19),
    AmendmentTarget(
        47,
        398,
        "extension",
        date(2026, 7, 1),
        old_end=date(2026, 8, 31),
        new_end=date(2026, 7, 31),
    ),
    AmendmentTarget(
        48, 398, "rate_change", date(2026, 7, 1), same_client_rate_as_snapshot=True
    ),
)

STEPS: tuple[StepTarget, ...] = (
    StepTarget("candidate", 6, 155, date(2026, 7, 1), same_as=5),
    StepTarget("candidate", 17, 155, date(2026, 7, 1), same_as=5),
    StepTarget("candidate", 31, 116, date(2026, 8, 1), same_as=30),
    StepTarget("candidate", 197, 263, date(2027, 1, 1), same_as=198),
    StepTarget("client", 22, 398, date(2026, 7, 10), same_as=23),
)

_SCHEDULE_MODELS = {"candidate": ContractCandidateRate, "client": ContractClientRate}


def same_rates_without(steps: Sequence[Any], step_id: int) -> bool:
    """Czy harmonogram bez kroku ``step_id`` daje tę samą stawkę w każdym dniu.

    ``steps`` w kolejności wczytywania relacji (``effective_from``, ``id``),
    bo od niej zależy rozstrzygnięcie remisu w resolverze. Stawka jest stała
    między datami kroków, więc wystarczy porównać dzień każdego kroku i dzień
    przed najwcześniejszym.
    """
    without = [step for step in steps if step.id != step_id]
    if len(without) == len(steps) or not without:
        return False
    days = {step.effective_from for step in steps}
    days.add(min(days) - timedelta(days=1))
    resolve = Contract._resolve_scheduled_rate
    return all(resolve(steps, day, None) == resolve(without, day, None) for day in days)


def _as_text(value: object) -> Optional[str]:
    return None if value is None else str(value)


def _iso(value: Optional[date | datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


async def _amendment_referenced(db: AsyncSession, amendment_id: int) -> bool:
    row = await db.execute(
        text(
            """
            SELECT
              (SELECT count(*) FROM client_order_revenue_steps
                WHERE contract_amendment_id = :id)
            + (SELECT count(*) FROM b2b_contract_documents
                WHERE (effect_summary->>'amendment_id') = CAST(:id AS text)
                   OR coalesce(effect_summary->'amendment_ids', '[]'::jsonb)
                      @> to_jsonb(CAST(:id AS integer)))
            + (SELECT count(*) FROM contract_document_rate_reads
                WHERE coalesce(decision_amendment_ids, '[]'::jsonb)
                      @> to_jsonb(CAST(:id AS integer)))
            """
        ),
        {"id": amendment_id},
    )
    return bool(row.scalar())


async def _step_referenced(db: AsyncSession, step_id: int) -> bool:
    count = await db.scalar(
        text(
            "SELECT count(*) FROM contract_document_rate_reads "
            "WHERE coalesce(finding->'created_step_ids', '[]'::jsonb) "
            "@> to_jsonb(CAST(:id AS integer))"
        ),
        {"id": step_id},
    )
    return bool(count)


def _correction_matches(target: AmendmentTarget, amendment: ContractAmendment) -> bool:
    old = amendment.old_values or {}
    new = amendment.new_values or {}
    if target.old_end is not None or target.new_end is not None:
        return old.get("end_date") == _iso(target.old_end) and new.get(
            "end_date"
        ) == _iso(target.new_end)
    if target.same_client_rate_as_snapshot:
        new_rate, old_rate = new.get("rate_client"), old.get("rate_client")
        if "rate_candidate" in new or new_rate is None or old_rate is None:
            return False
        return Decimal(str(new_rate)) == Decimal(str(old_rate))
    return False


async def _remove_amendment(
    db: AsyncSession, target: AmendmentTarget
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    result: dict[str, Any] = {
        "amendment_id": target.amendment_id,
        "contract_id": target.contract_id,
        "skipped": None,
    }
    amendment = await db.get(ContractAmendment, target.amendment_id)
    if amendment is None:
        result["skipped"] = "missing"
        return result, None
    if (
        amendment.contract_id != target.contract_id
        or amendment.amendment_type.value != target.amendment_type
        or amendment.effective_date != target.effective_date
    ):
        result["skipped"] = "identity_mismatch"
        return result, None
    if target.duplicate_of is not None:
        keeper = await db.get(ContractAmendment, target.duplicate_of)
        if (
            keeper is None
            or keeper.contract_id != amendment.contract_id
            or keeper.amendment_type != amendment.amendment_type
            or keeper.effective_date != amendment.effective_date
        ):
            result["skipped"] = "keeper_missing"
            return result, None
        same = await db.scalar(
            text(
                "SELECT a.new_values = k.new_values FROM contract_amendments a, "
                "contract_amendments k WHERE a.id = :a AND k.id = :k"
            ),
            {"a": amendment.id, "k": keeper.id},
        )
        if not same:
            result["skipped"] = "values_differ"
            return result, None
    elif not _correction_matches(target, amendment):
        result["skipped"] = "values_differ"
        return result, None
    if await _amendment_referenced(db, amendment.id):
        result["skipped"] = "referenced"
        return result, None

    removed = {
        "amendment_id": amendment.id,
        "contract_id": amendment.contract_id,
        "amendment_type": amendment.amendment_type.value,
        "effective_date": _iso(amendment.effective_date),
        "old_values": amendment.old_values,
        "new_values": amendment.new_values,
        "reason": amendment.reason,
        "document_id": amendment.document_id,
        "created_by": amendment.created_by,
        "created_at": _iso(amendment.created_at),
        "duplicate_of": target.duplicate_of,
    }
    await db.delete(amendment)
    return result, removed


async def _remove_step(
    db: AsyncSession, target: StepTarget
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    result: dict[str, Any] = {
        "schedule": target.schedule,
        "step_id": target.step_id,
        "contract_id": target.contract_id,
        "skipped": None,
    }
    model = _SCHEDULE_MODELS[target.schedule]
    steps = list(
        (
            await db.scalars(
                select(model)
                .where(model.contract_id == target.contract_id)
                .order_by(model.effective_from, model.id)
            )
        ).all()
    )
    by_id = {step.id: step for step in steps}
    step = by_id.get(target.step_id)
    if step is None:
        exists_elsewhere = await db.scalar(
            select(func.count()).select_from(model).where(model.id == target.step_id)
        )
        result["skipped"] = "identity_mismatch" if exists_elsewhere else "missing"
        return result, None
    if step.effective_from != target.effective_from:
        result["skipped"] = "identity_mismatch"
        return result, None
    keeper = by_id.get(target.same_as)
    if keeper is None:
        result["skipped"] = "keeper_missing"
        return result, None
    if keeper.rate != step.rate:
        result["skipped"] = "rate_differs"
        return result, None
    if not same_rates_without(steps, step.id):
        result["skipped"] = "changes_rate"
        return result, None
    if await _step_referenced(db, step.id):
        result["skipped"] = "referenced"
        return result, None

    removed = {
        "schedule": target.schedule,
        "step_id": step.id,
        "contract_id": step.contract_id,
        "rate": _as_text(step.rate),
        "effective_from": _iso(step.effective_from),
        "effective_to": _iso(getattr(step, "effective_to", None)),
        "note": step.note,
        "source_order_id": getattr(step, "source_order_id", None),
        "created_by": step.created_by,
        "created_at": _iso(step.created_at),
        "same_as": target.same_as,
    }
    await db.delete(step)
    return result, removed


async def run_contract_amendment_history_repair(
    db: AsyncSession,
    *,
    amendments: Iterable[AmendmentTarget] = AMENDMENTS,
    steps: Iterable[StepTarget] = STEPS,
    marker: str = REPAIR_MARKER,
    details_key: str = DETAILS_KEY,
) -> Optional[dict[str, Any]]:
    """Wykonaj sprzątanie; ``None`` = już wykonane. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None

    amendment_targets = list(amendments)
    step_targets = list(steps)
    amendment_results: list[dict[str, Any]] = []
    step_results: list[dict[str, Any]] = []
    removed_rows: dict[str, list[dict[str, Any]]] = {"amendments": [], "steps": []}
    for target in amendment_targets:
        result, removed = await _remove_amendment(db, target)
        amendment_results.append(result)
        if removed is not None:
            removed_rows["amendments"].append(removed)
    for target in step_targets:
        result, removed = await _remove_step(db, target)
        step_results.append(result)
        if removed is not None:
            removed_rows["steps"].append(removed)

    by_contract: dict[int, dict[str, list[int]]] = {}
    for row in removed_rows["amendments"]:
        entry = by_contract.setdefault(row["contract_id"], {})
        entry.setdefault("removed_amendment_ids", []).append(row["amendment_id"])
    for row in removed_rows["steps"]:
        entry = by_contract.setdefault(row["contract_id"], {})
        key = f"removed_{row['schedule']}_rate_step_ids"
        entry.setdefault(key, []).append(row["step_id"])
    for contract_id, details in sorted(by_contract.items()):
        db.add(
            Activity(
                entity_type="contract",
                entity_id=contract_id,
                action=ACTIVITY_ACTION,
                user_id=None,
                details={"source": marker, **details},
            )
        )

    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "amendments_requested": len(amendment_targets),
        "amendments_removed": len(removed_rows["amendments"]),
        "steps_requested": len(step_targets),
        "steps_removed": len(removed_rows["steps"]),
        "amendment_results": amendment_results,
        "step_results": step_results,
    }
    db.add(AppSetting(key=marker, value=summary))
    db.add(AppSetting(key=details_key, value=removed_rows))
    await db.flush()
    logger.info(
        "contract amendment history repair: amendments %s/%s, steps %s/%s",
        summary["amendments_removed"],
        summary["amendments_requested"],
        summary["steps_removed"],
        summary["steps_requested"],
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    skipped = [
        f"amendment {r['amendment_id']}:{r['skipped']}"
        for r in summary["amendment_results"]
        if r["skipped"] is not None
    ] + [
        f"step {r['schedule']}/{r['step_id']}:{r['skipped']}"
        for r in summary["step_results"]
        if r["skipped"] is not None
    ]
    return (
        f"amendments {summary['amendments_removed']}/{summary['amendments_requested']}, "
        f"steps {summary['steps_removed']}/{summary['steps_requested']}"
        + (f"; skipped {', '.join(skipped)}" if skipped else "")
    )
