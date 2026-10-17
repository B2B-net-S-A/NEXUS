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

Struktura u klienta (17.10.2026): podwładni duplikatu przechodzą pod kontakt,
który zostaje, a jego puste „podlega pod” i dział biorą wartości duplikatu.
Pętla (zachowany podlegał pod kogoś z podwładnych duplikatu) jest przerywana
na zachowanym — to ta sama osoba, więc sprzeczne dane, nie dwie hierarchie.
Opinie klienta zapisane od duplikatu przechodzą na kontakt, który zostaje.
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
    # Sesja ma `autoflush=False`, a `get(..., with_for_update=True)` pyta bazę
    # z pominięciem mapy tożsamości. Bez flusha druga para w tym samym biegu
    # nie widziała wiersza aliasów dodanego przez pierwszą i dodawała drugi
    # z tym samym kluczem — korekta z 25.09 padała na `app_settings_pkey`
    # przy każdym starcie i nie zapisała się do 14.10.2026.
    await db.flush()
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


# Runda 10 (R10-N11-4): nagrobki kontaktów z Traffita usuniętych w NEXUSIE.
# Faza `contacts` przegląda co noc cały `/crm_persons/` i robi upsert po
# `external_id`, więc usunięty kontakt wracał następnej nocy (lustro aliasów
# wyżej i nagrobków klientów/kandydatów).
DELETED_KEY = "traffit_contact_tombstones"


async def load_deleted_traffit_contacts(db: AsyncSession) -> set[str]:
    """Id rekordów Traffita, których kontakty usunięto w NEXUSIE."""

    setting = await db.get(AppSetting, DELETED_KEY)
    raw = (setting.value or {}).get("external_ids", []) if setting else []
    return {str(v) for v in raw if v is not None}


async def add_deleted_traffit_contact(db: AsyncSession, external_id: str) -> None:
    setting = await db.get(AppSetting, DELETED_KEY, with_for_update=True)
    if setting is None:
        db.add(AppSetting(key=DELETED_KEY, value={"external_ids": [external_id]}))
        return
    ids = [str(v) for v in (setting.value or {}).get("external_ids", [])]
    if external_id not in ids:
        ids.append(external_id)
    setting.value = {**(setting.value or {}), "external_ids": ids}


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
    org = await merge_org(
        db, survivor_id=pair.survivor_id, duplicate_id=pair.duplicate_id
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
            **org,
        }
    )
    return result


async def merge_org(
    db: AsyncSession, *, survivor_id: int, duplicate_id: int
) -> dict[str, int]:
    """Struktura u klienta i opinie przy scaleniu dwóch kontaktów jednej osoby."""

    from app.models.contract_care import CONTACTS_ORG, ClientFeedbackSession
    from app.services.care.client_people import manager_chain_reaches

    org = CONTACTS_ORG
    rows = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    org.c.id, org.c.reports_to_contact_id, org.c.client_area_id
                ).where(org.c.id.in_([survivor_id, duplicate_id]))
            )
        ).all()
    }
    survivor, duplicate = rows[survivor_id], rows[duplicate_id]
    manager = survivor.reports_to_contact_id
    if manager == duplicate_id:
        manager = None
    if manager is None and duplicate.reports_to_contact_id not in (
        None,
        survivor_id,
        duplicate_id,
    ):
        manager = duplicate.reports_to_contact_id
    area = survivor.client_area_id or duplicate.client_area_id
    await db.execute(
        update(org)
        .where(org.c.id == survivor_id)
        .values(reports_to_contact_id=manager, client_area_id=area)
    )
    subordinates = await db.execute(
        update(org)
        .where(org.c.reports_to_contact_id == duplicate_id, org.c.id != survivor_id)
        .values(reports_to_contact_id=survivor_id)
    )
    # Jedyne nowe krawędzie prowadzą DO zachowanego, więc pętla — jeśli jest —
    # przechodzi przez niego: przerywamy ją na jego „podlega pod”.
    loop_broken = 0
    if manager is not None and await manager_chain_reaches(
        db, start_id=manager, target_id=survivor_id
    ):
        await db.execute(
            update(org)
            .where(org.c.id == survivor_id)
            .values(reports_to_contact_id=None)
        )
        loop_broken = 1
    feedback = await db.execute(
        update(ClientFeedbackSession)
        .where(ClientFeedbackSession.contact_id == duplicate_id)
        .values(contact_id=survivor_id)
    )
    return {
        "subordinates_repointed": subordinates.rowcount or 0,
        "reports_to_loop_broken": loop_broken,
        "feedback_sessions_repointed": feedback.rowcount or 0,
    }


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
