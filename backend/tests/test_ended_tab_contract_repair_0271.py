"""Migracja 0271: korekta wskazana w tickecie + audyt klasy — kontrakt SQL-a.

Wzorzec 0250: id kontraktu nie jest zaufane samo — klient, nazwisko, status,
brak wypowiedzenia i data muszą się zgadzać; analogiczne wiersze są wyłącznie
audytowane. Do tego jeden test WYKONUJE blok na bazie testowej: literówka
w nazwie kolumny wyszłaby dopiero na produkcji, a entrypoint połknąłby ją
(`|| echo skipped`).
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.contract_ended_tab_repair import (
    ENDED_TAB_REPAIR_MARKER,
    ENDED_TAB_REPAIR_SQL,
)

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0271_ended_tab_contract_repair.py"


def test_0271_chains_after_jobs_open_state_head():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0271_ended_tab_contract_repair"' in source
    assert 'down_revision = "0270_jobs_open_state_dates"' in source
    assert "ENDED_TAB_REPAIR_SQL" in source


def test_repair_requires_business_identity_not_a_bare_id():
    target = ENDED_TAB_REPAIR_SQL.split("CREATE TEMP TABLE _ticket_target", 1)[1].split(
        "UPDATE contracts", 1
    )[0]
    for value in (
        "c.id = 469",
        "c.status = 'ended'",
        "c.terminated_at IS NULL",
        "c.termination_reason IS NULL",
        "c.end_date = DATE '2026-06-30'",
        "= 'piotr'",
        "= 'klimczak'",
        "LIKE '%velobank%'",
    ):
        assert value in target


def test_only_the_ticket_target_is_updated_and_the_class_is_audited():
    update = ENDED_TAB_REPAIR_SQL.split("UPDATE contracts AS c", 1)[1].split(
        "GET DIAGNOSTICS", 1
    )[0]
    assert "FROM _ticket_target AS t" in update
    assert "_ended_by_order_period" not in update
    assert "end_date = NULL" in update
    audit = ENDED_TAB_REPAIR_SQL.split("CREATE TEMP TABLE _ended_by_order_period", 1)[
        1
    ].split("CREATE TEMP TABLE _ticket_target", 1)[0]
    assert "o.status NOT IN ('draft', 'cancelled')" in audit
    assert "o.end_date > c.end_date" in audit
    assert "c.terminated_at IS NULL" in audit
    assert "audited_contracts" in ENDED_TAB_REPAIR_SQL
    assert "pg_advisory_xact_lock" in ENDED_TAB_REPAIR_SQL


@pytest.mark.asyncio
async def test_repair_block_runs_and_reopens_the_ticket_contract():
    """Wykonanie na bazie: wiersz o kluczach z ticketu wraca na `active`."""
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import (
        Contract,
        ContractStatus,
        ContractType,
        ContractWorkMode,
    )

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        taken = await db.scalar(text("SELECT 1 FROM contracts WHERE id = 469"))
        if taken:
            pytest.skip(
                "id 469 zajęte w bazie testowej — ścieżka korekty niesprawdzalna"
            )
        client = Client(name=f"VeloBank S.A. Test {tag}")
        candidate = Candidate(
            name="Piotr", lastname="Klimczak", email=f"pk-{tag}@example.test"
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            id=469,
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            work_mode=ContractWorkMode.remote,
            status=ContractStatus.ended,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 6, 30),
            rate_candidate=1280,
            rate_client=1600,
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            client_id=client.id,
            contract_id=469,
            title=f"Zamówienie nr 3/07/2026/BL {tag}",
            status=ClientOrderStatus.completed,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 8, 31),
        )
        db.add(order)
        await db.commit()
        order_id, client_id, candidate_id = order.id, client.id, candidate.id

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM app_settings WHERE key = :k"),
                {"k": ENDED_TAB_REPAIR_MARKER},
            )
            await db.execute(text(ENDED_TAB_REPAIR_SQL))
            await db.commit()
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    text("SELECT status::text, end_date FROM contracts WHERE id = 469")
                )
            ).one()
            assert row[0] == "active" and row[1] is None
            receipt = json.loads(
                await db.scalar(
                    text("SELECT value::text FROM app_settings WHERE key = :k"),
                    {"k": ENDED_TAB_REPAIR_MARKER},
                )
            )
            assert receipt["repaired_contracts"] == 1
            assert any(a["contract_id"] == 469 for a in receipt["audited_contracts"])
            audit = await db.scalar(
                text(
                    "SELECT count(*) FROM activities WHERE entity_type = 'contract' "
                    "AND entity_id = 469 AND action = 'contract_reopened' "
                    "AND details->>'source' = :k"
                ),
                {"k": ENDED_TAB_REPAIR_MARKER},
            )
            assert audit == 1
            # Drugi bieg: marker zatrzymuje blok, nic się nie dubluje.
            await db.execute(text(ENDED_TAB_REPAIR_SQL))
            await db.commit()
            audit_again = await db.scalar(
                text(
                    "SELECT count(*) FROM activities WHERE entity_id = 469 "
                    "AND action = 'contract_reopened' AND details->>'source' = :k"
                ),
                {"k": ENDED_TAB_REPAIR_MARKER},
            )
            assert audit_again == 1
    finally:
        # Jawne id 469 nie przesuwa sekwencji — bez sprzątania późniejszy INSERT
        # innego testu trafiłby w zajęte id.
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "DELETE FROM activities WHERE entity_type = 'contract' AND entity_id = 469"
                )
            )
            await db.execute(
                text("DELETE FROM client_orders WHERE id = :o"), {"o": order_id}
            )
            await db.execute(text("DELETE FROM contracts WHERE id = 469"))
            await db.execute(
                text("DELETE FROM candidates WHERE id = :c"), {"c": candidate_id}
            )
            await db.execute(
                text("DELETE FROM clients WHERE id = :c"), {"c": client_id}
            )
            await db.execute(
                text("DELETE FROM app_settings WHERE key = :k"),
                {"k": ENDED_TAB_REPAIR_MARKER},
            )
            await db.commit()
