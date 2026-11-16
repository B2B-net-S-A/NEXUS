"""CHECK akcji historii kosztów po E2 (dekret) i E3 (przelewy) — z bazą.

E2 dopisał akcje dekretu (``decree``, ``export``, ``unexport``, ``book``), E3 akcję
``account`` (zmiana rachunku odbiorcy). Każdy etap przebudowuje
``ck_finance_cost_entry_events_action`` w bloku DO. Migracja E3 uruchamia tylko swój
blok, a ten budował CHECK z samą listą E1: po migracji akcje dekretu były zakazane,
a przy istniejącym zdarzeniu ``decree`` ``ADD CONSTRAINT`` padał i migracja się
wywracała. Test odtwarza bazę po E2 (CHECK bez ``account``) i sprawdza stan zaraz
po DDL E3 oraz po pełnym biegu entrypointu.
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import engine
from app.services import finance_ledger_schema as ledger
from app.services import finance_payments_schema as payments
from app.services import finance_posting_schema as posting
from app.services.consultant_portal_schema import quoted

_CONSTRAINT = "ck_finance_cost_entry_events_action"
_ALL_ACTIONS = (*ledger.EVENT_ACTIONS, *posting.EVENT_ACTIONS)


async def _definition(conn) -> str:
    return (
        await conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = :name"
            ),
            {"name": _CONSTRAINT},
        )
    ).scalar_one()


async def _assert_all_actions(conn) -> str:
    definition = await _definition(conn)
    missing = [a for a in _ALL_ACTIONS if f"'{a}'" not in definition]
    assert not missing, missing
    return definition


async def test_ddl_e3_zostawia_akcje_dekretu_e2() -> None:
    after_e2 = tuple(action for action in posting.EVENT_ACTIONS if action != "account")
    async with engine.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.execute(
                text(
                    "ALTER TABLE finance_cost_entry_events "
                    f"DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE finance_cost_entry_events ADD CONSTRAINT "
                    f"{_CONSTRAINT} CHECK (action IN ({quoted(after_e2)}))"
                )
            )
            assert "'account'" not in await _definition(conn)

            # Migracja E3: tylko jej blok.
            for statement in payments.CONSTRAINT_DDL:
                await conn.execute(text(statement))
            await _assert_all_actions(conn)

            # Entrypoint: bloki obu etapów, dwa razy — drugi bieg nic nie zmienia.
            for statement in posting.CONSTRAINT_DDL + payments.CONSTRAINT_DDL:
                await conn.execute(text(statement))
            definition = await _assert_all_actions(conn)
            for statement in posting.CONSTRAINT_DDL + payments.CONSTRAINT_DDL:
                await conn.execute(text(statement))
            assert await _definition(conn) == definition
        finally:
            await tx.rollback()
