"""Scalanie zdublowanych kontaktów klienta z Traffita (25.09.2026).

Import Traffita zakłada kontakt na KAŻDY rekord `/crm_persons/`, a Traffit ma
tę samą osobę bywa dwa razy (inne id). Weto hiring managera dopasowuje
rekrutacje po id kontaktu, więc dwa rekordy jednej osoby rozbijają weto na dwie.

Samo usunięcie duplikatu nie działa: faza `contacts` nocnego syncu przegląda
wszystkie `/crm_persons/` i robi upsert po `(external_source, external_id)`,
więc następnej nocy wiersz wróciłby. Dlatego scalenie zapisuje ALIAS
(`app_settings[ALIASES_KEY]`: id rekordu Traffita → id kontaktu, który został),
a import pomija rekordy z aliasem.

Zostaje kontakt o niższym id — ta sama reguła co wybór wśród duplikatów przy
dopasowaniu hiring managera (`job_hiring_manager.pick_matching_contact`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.job import Job
from app.services.job_hiring_manager import name_key

logger = logging.getLogger(__name__)

ALIASES_KEY = "traffit_contact_aliases"
REPAIR_MARKER = "contact_duplicates_merge_2026_09_25"

# Pola uzupełniane w kontakcie, który zostaje — wyłącznie gdy są w nim puste.
_FILL_FIELDS = ("email", "phone", "position", "department", "notes")


@dataclass(frozen=True)
class MergePair:
    client_id: int
    survivor_id: int
    survivor_external_id: str
    duplicate_id: int
    duplicate_external_id: str


# Trzy pary z produkcji 25.09.2026 (ta sama osoba u tego samego klienta,
# oba rekordy z importu Traffita). Bez nazwisk w repo — tylko id.
TARGETS: tuple[MergePair, ...] = (
    MergePair(
        client_id=12,
        survivor_id=422,
        survivor_external_id="214",
        duplicate_id=491,
        duplicate_external_id="284",
    ),
    MergePair(
        client_id=18,
        survivor_id=32,
        survivor_external_id="22",
        duplicate_id=459,
        duplicate_external_id="251",
    ),
    MergePair(
        client_id=5182,
        survivor_id=181,
        survivor_external_id="172",
        duplicate_id=182,
        duplicate_external_id="173",
    ),
)


async def load_traffit_contact_aliases(db: AsyncSession) -> dict[str, int]:
    """Id rekordów Traffita scalonych w inny kontakt (import je pomija)."""

    setting = await db.get(AppSetting, ALIASES_KEY)
    raw = (setting.value or {}).get("aliases", {}) if setting else {}
    return {str(k): int(v) for k, v in raw.items()}


async def _add_alias(db: AsyncSession, external_id: str, survivor_id: int) -> None:
    setting = await db.get(AppSetting, ALIASES_KEY, with_for_update=True)
    if setting is None:
        db.add(
            AppSetting(key=ALIASES_KEY, value={"aliases": {external_id: survivor_id}})
        )
        return
    aliases = dict((setting.value or {}).get("aliases", {}))
    aliases[external_id] = survivor_id
    # Nowy słownik — JSONB bez MutableDict nie widzi zmian w miejscu.
    setting.value = {**(setting.value or {}), "aliases": aliases}


async def merge_pair(db: AsyncSession, pair: MergePair) -> dict[str, Any]:
    """Scal jedną parę; niezgodność z oczekiwanym stanem = pominięcie z kodem."""

    result: dict[str, Any] = {
        "survivor_id": pair.survivor_id,
        "duplicate_id": pair.duplicate_id,
        "skipped": None,
    }
    rows = {
        c.id: c
        for c in (
            await db.execute(
                select(Contact)
                .where(Contact.id.in_([pair.survivor_id, pair.duplicate_id]))
                .with_for_update()
            )
        ).scalars()
    }
    survivor = rows.get(pair.survivor_id)
    duplicate = rows.get(pair.duplicate_id)
    if survivor is None or duplicate is None:
        result["skipped"] = "contact_missing"
        return result
    if not (
        survivor.client_id == duplicate.client_id == pair.client_id
        and survivor.external_source == duplicate.external_source == "traffit"
        and survivor.external_id == pair.survivor_external_id
        and duplicate.external_id == pair.duplicate_external_id
    ):
        result["skipped"] = "identity_mismatch"
        return result
    if name_key(survivor.name) != name_key(duplicate.name):
        result["skipped"] = "different_person"
        return result

    filled = []
    for field in _FILL_FIELDS:
        if (
            not (getattr(survivor, field) or "").strip()
            and (getattr(duplicate, field) or "").strip()
        ):
            setattr(survivor, field, getattr(duplicate, field))
            filled.append(field)

    jobs = await db.execute(
        update(Job)
        .where(Job.hiring_manager_contact_id == pair.duplicate_id)
        .values(hiring_manager_contact_id=pair.survivor_id)
    )
    contracts = await db.execute(
        update(Contract)
        .where(Contract.client_pm_contact_id == pair.duplicate_id)
        .values(client_pm_contact_id=pair.survivor_id)
    )
    await _add_alias(db, pair.duplicate_external_id, pair.survivor_id)
    await db.delete(duplicate)
    # Ten sam dziennik co `record_client_audit`, ale bez autora — korekta
    # przy starcie nie ma zalogowanej osoby.
    db.add(
        Activity(
            entity_type="client",
            entity_id=pair.client_id,
            action="contact_merged",
            user_id=None,
            details={
                "survivor_id": pair.survivor_id,
                "duplicate_id": pair.duplicate_id,
                "fields": filled,
            },
        )
    )
    result.update(
        {
            "filled_fields": filled,
            "jobs_repointed": jobs.rowcount or 0,
            "contracts_repointed": contracts.rowcount or 0,
        }
    )
    return result


async def run_contact_duplicate_merge(
    db: AsyncSession,
    *,
    targets: Iterable[MergePair] = TARGETS,
    marker: str = REPAIR_MARKER,
) -> Optional[dict[str, Any]]:
    """Wykonaj korektę raz; ``None`` = już wykonana. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    pairs = list(targets)
    results = [await merge_pair(db, pair) for pair in pairs]
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(pairs),
        "merged": sum(1 for r in results if r["skipped"] is None),
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("contact duplicate merge: %s/%s", summary["merged"], len(pairs))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    skipped = [
        f"{r['duplicate_id']}:{r['skipped']}"
        for r in summary["results"]
        if r["skipped"] is not None
    ]
    return f"merged {summary['merged']}/{summary['requested']}" + (
        f"; skipped {', '.join(skipped)}" if skipped else ""
    )
