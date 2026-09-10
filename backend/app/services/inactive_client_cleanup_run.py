"""Wykonanie jednorazowego czyszczenia „Nieaktywnych klientów" + raport.

Ocena (co zostaje, co wstrzymane, co do usunięcia) jest w
``inactive_client_cleanup`` i tylko czyta. Tu dzieje się jedyny zapis:
znacznik w audycie manifestu portfela, nagrobek (lista A), usunięcie klienta
i raport z listą B. Commit należy do wołającego.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Collection, Optional

from sqlalchemy import Text, cast, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.client import Client
from app.models.client_cleanup import ClientCleanupRun, PurgedClient
from app.models.client_directory import (
    ClientAlias,
    ClientImportRow,
    ClientPortfolioScope,
)
from app.models.user import User
from app.services.inactive_client_cleanup import (
    CLEANUP_KIND,
    CleanupAlreadyExecutedError,
    ClientEvaluation,
    kept_by_source,
    load_inactive_candidates,
    evaluate_inactive_clients,
)

logger = logging.getLogger(__name__)

# Stała blokady doradczej — serializuje równoległe kliknięcia „Wykonaj".
_ADVISORY_LOCK_KEY = 710_303_001


async def get_cleanup_run(db: AsyncSession) -> Optional[ClientCleanupRun]:
    return await db.scalar(
        select(ClientCleanupRun).where(ClientCleanupRun.kind == CLEANUP_KIND)
    )


async def _snapshot(db: AsyncSession, client_id: int) -> dict[str, Any]:
    scopes = (
        await db.execute(
            select(
                ClientPortfolioScope.id,
                cast(ClientPortfolioScope.category, Text),
                cast(ClientPortfolioScope.category_override, Text),
                ClientPortfolioScope.source_system,
                ClientPortfolioScope.source_key,
                ClientPortfolioScope.label,
                ClientPortfolioScope.archived_at,
                ClientPortfolioScope.framework_contract_id,
                ClientPortfolioScope.contract_start_override,
                ClientPortfolioScope.contract_end_override,
            ).where(ClientPortfolioScope.client_id == client_id)
        )
    ).all()
    aliases = (
        await db.execute(
            select(ClientAlias.alias).where(ClientAlias.client_id == client_id)
        )
    ).scalars()
    activities = (
        await db.execute(
            select(Activity.action, func.count(Activity.id))
            .where(Activity.entity_type == "client", Activity.entity_id == client_id)
            .group_by(Activity.action)
        )
    ).all()
    return {
        "portfolio_scopes": [
            {
                "id": row[0],
                "category": row[1],
                "category_override": row[2],
                "source_system": row[3],
                "source_key": row[4],
                "label": row[5],
                "archived_at": row[6].isoformat() if row[6] else None,
                "framework_contract_id": row[7],
                "contract_start_override": row[8].isoformat() if row[8] else None,
                "contract_end_override": row[9].isoformat() if row[9] else None,
            }
            for row in scopes
        ],
        "aliases": sorted(aliases),
        "activity_actions": {str(action): int(count) for action, count in activities},
    }


async def _purge_client(
    db: AsyncSession,
    evaluation: ClientEvaluation,
    *,
    run: ClientCleanupRun,
    actor: User,
    purged_at: datetime,
) -> None:
    client_id = evaluation.client_id
    snapshot = await _snapshot(db, client_id)

    # Znacznik PRZED usunięciem — FK wyzerują powiązanie, a bez znacznika
    # inwariant manifestu portfela uznałby brak zakresu za dryf (503).
    scope_ids = select(ClientPortfolioScope.id).where(
        ClientPortfolioScope.client_id == client_id
    )
    await db.execute(
        update(ClientImportRow)
        .where(
            or_(
                ClientImportRow.matched_client_id == client_id,
                ClientImportRow.portfolio_scope_id.in_(scope_ids),
            )
        )
        .values(purged_at=purged_at, purged_client_id=client_id)
        .execution_options(synchronize_session=False)
    )
    db.add(
        PurgedClient(
            run_id=run.id,
            client_id=client_id,
            name=evaluation.source_name,
            display_name=(
                evaluation.name if evaluation.name != evaluation.source_name else None
            ),
            legal_name=evaluation.legal_name,
            nip=evaluation.nip,
            status=evaluation.status,
            external_source=evaluation.external_source,
            external_id=evaluation.external_id,
            client_created_at=evaluation.created_at,
            snapshot=snapshot,
            purged_at=purged_at,
        )
    )
    await db.flush()
    result = await db.execute(
        delete(Client)
        .where(Client.id == client_id)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise RuntimeError(f"client {client_id} vanished before delete")
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="purged_inactive_cleanup",
            user_id=actor.id,
            details={"run_id": run.id, "name": evaluation.name},
        )
    )
    await db.flush()


def _held_entry(
    evaluation: ClientEvaluation,
    *,
    extra_reason: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload = evaluation.as_dict()
    if extra_reason is not None:
        payload["reasons"] = [*payload["reasons"], extra_reason]
    return payload


async def execute_inactive_client_cleanup(
    db: AsyncSession,
    *,
    actor: User,
    confirmed_client_ids: Collection[int],
    restrict_ids: Optional[Collection[int]] = None,
    environ: Optional[dict[str, str]] = None,
) -> ClientCleanupRun:
    """Wykonaj czyszczenie. Jednorazowe; commit należy do wołającego.

    Usuwani są WYŁĄCZNIE klienci, którzy (1) w chwili wykonania nadal
    kwalifikują się do usunięcia i (2) byli na liście zatwierdzonej przez
    administratora w podglądzie. Klient, który zakwalifikował się dopiero po
    podglądzie, trafia na listę B — nikt go nie widział, więc nikt go nie
    zatwierdził.
    """

    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY}
    )
    existing = await get_cleanup_run(db)
    if existing is not None:
        raise CleanupAlreadyExecutedError(existing)

    # Blokada wierszy klientów PRZED oceną: wstawienie rekrutacji, zamówienia
    # czy kontaktu wskazującego na klienta bierze FOR KEY SHARE, które czeka
    # na nasze FOR UPDATE — ocena i usunięcie widzą ten sam stan.
    candidate_ids = [
        c.client_id for c in await load_inactive_candidates(db, restrict_ids)
    ]
    if candidate_ids:
        await db.execute(
            select(Client.id)
            .where(Client.id.in_(candidate_ids))
            .order_by(Client.id)
            .with_for_update()
        )
    plan = await evaluate_inactive_clients(
        db, restrict_ids=restrict_ids, environ=environ
    )

    confirmed = set(confirmed_client_ids)
    to_delete = [item for item in plan.deletable if item.client_id in confirmed]
    held: list[dict[str, Any]] = [_held_entry(item) for item in plan.held]
    held.extend(
        _held_entry(
            item,
            extra_reason={
                "code": "not_in_confirmed_preview",
                "label": "Zakwalifikował się po podglądzie — nie był zatwierdzony",
                "count": 1,
                "effect": "nie został usunięty",
            },
        )
        for item in plan.deletable
        if item.client_id not in confirmed
    )

    executed_at = datetime.now(timezone.utc)
    run = ClientCleanupRun(
        kind=CLEANUP_KIND,
        # Jawnie, nie z ``server_default``: raport czyta tę wartość zaraz po
        # zapisie, a atrybut wypełniany przez bazę trzeba by doładować — w sesji
        # async to MissingGreenlet (500 bez CORS, „Network Error").
        executed_at=executed_at,
        executed_by=actor.id,
        executed_by_name=actor.name,
        candidates_count=plan.candidates_count,
        kept_count=len(plan.kept),
        deleted_count=0,
        held_count=0,
        held=[],
        summary={},
    )
    db.add(run)
    await db.flush()

    purged_at = executed_at
    deleted_ids: list[int] = []
    for evaluation in to_delete:
        try:
            async with db.begin_nested():
                await _purge_client(
                    db, evaluation, run=run, actor=actor, purged_at=purged_at
                )
        except Exception as exc:  # noqa: BLE001 — jeden klient nie wywraca reszty
            logger.exception(
                "inactive client cleanup: delete failed for client_id=%s",
                evaluation.client_id,
            )
            held.append(
                _held_entry(
                    evaluation,
                    extra_reason={
                        "code": "delete_failed",
                        "label": f"Usunięcie nie powiodło się ({type(exc).__name__})",
                        "count": 1,
                        "effect": "klient został bez zmian",
                    },
                )
            )
            continue
        deleted_ids.append(evaluation.client_id)

    held.sort(key=lambda item: (str(item["name"]).lower(), item["client_id"]))
    run.deleted_count = len(deleted_ids)
    run.held = held
    run.held_count = len(held)
    run.summary = {
        "evaluated_at": plan.evaluated_at.isoformat(),
        "confirmed_count": len(confirmed),
        "kept_by_source": kept_by_source(plan.kept),
        "deleted_client_ids": deleted_ids,
    }
    await db.flush()
    return run


async def load_cleanup_report(db: AsyncSession) -> Optional[dict[str, Any]]:
    run = await get_cleanup_run(db)
    if run is None:
        return None
    purged = (
        (
            await db.execute(
                select(PurgedClient)
                .where(PurgedClient.run_id == run.id)
                .order_by(
                    func.lower(
                        func.coalesce(PurgedClient.display_name, PurgedClient.name)
                    ),
                    PurgedClient.client_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "run_id": run.id,
        "executed_at": run.executed_at.isoformat() if run.executed_at else None,
        "executed_by_name": run.executed_by_name,
        "candidates_count": run.candidates_count,
        "kept_count": run.kept_count,
        "deleted_count": run.deleted_count,
        "held_count": run.held_count,
        "deleted": [
            {
                "client_id": row.client_id,
                "name": row.display_name or row.name,
                "legal_name": row.legal_name,
                "nip": row.nip,
                "external_source": row.external_source,
                "external_id": row.external_id,
                "purged_at": row.purged_at.isoformat() if row.purged_at else None,
            }
            for row in purged
        ],
        "held": list(run.held or []),
        "summary": dict(run.summary or {}),
    }


async def purged_external_ids(db: AsyncSession, external_source: str) -> set[str]:
    """Nagrobki dla syncu źródłowego — tych rekordów nie wolno odtworzyć.

    Brak tabeli (baza sprzed 0303) = brak nagrobków, a nie awaria fazy:
    sprawdzamy katalog zamiast łapać wyjątek, bo nieudane zapytanie zostawia
    transakcję w stanie przerwanym i wywróciłoby każdy następny upsert.
    """

    if not await db.scalar(text("SELECT to_regclass('purged_clients') IS NOT NULL")):
        return set()
    rows = (
        await db.execute(
            select(PurgedClient.external_id).where(
                PurgedClient.external_source == external_source,
                PurgedClient.external_id.is_not(None),
            )
        )
    ).scalars()
    return {str(value) for value in rows}
