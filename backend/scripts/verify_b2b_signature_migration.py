#!/usr/bin/env python3
"""CI probe for the additive generated-contract signature migration.

The probe is intentionally split in two invocations around ``alembic upgrade``:
``seed`` inserts a row using the pre-0195 schema, while ``verify`` proves that
the migration preserved the legal-document snapshot and applied safe defaults.
It only touches one unmistakable CI sentinel row.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import asyncpg


PROBE_YEAR = 2098
PROBE_SEQ = 2_147_480_195
PROBE_NUMBER = "migration-probe-0195"
PROBE_PAYLOAD = '{"probe":"0195","preserve":true}'


def _dsn() -> str:
    value = os.environ["DATABASE_URL"]
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _seed() -> None:
    connection = await asyncpg.connect(_dsn())
    try:
        async with connection.transaction():
            await connection.execute(
                """
                DELETE FROM b2b_generated_contracts
                WHERE year = $1 AND seq = $2
                """,
                PROBE_YEAR,
                PROBE_SEQ,
            )
            await connection.execute(
                """
                INSERT INTO b2b_generated_contracts (
                    year,
                    seq,
                    contract_number,
                    partner_name,
                    client_name,
                    language,
                    signing_date,
                    render_payload
                )
                VALUES ($1, $2, $3, 'Historyczny Partner', 'Historyczny Klient',
                        'pl', DATE '2026-07-24', $4::jsonb)
                """,
                PROBE_YEAR,
                PROBE_SEQ,
                PROBE_NUMBER,
                PROBE_PAYLOAD,
            )
    finally:
        await connection.close()


async def _verify() -> None:
    connection = await asyncpg.connect(_dsn())
    try:
        row = await connection.fetchrow(
            """
            SELECT contract_number,
                   partner_name,
                   client_name,
                   language,
                   signing_date::text AS signing_date,
                   render_payload,
                   signature_status,
                   signature_source,
                   candidate_id,
                   job_id,
                   client_id,
                   contract_id,
                   signed_at,
                   signed_by_user_id
            FROM b2b_generated_contracts
            WHERE year = $1 AND seq = $2
            """,
            PROBE_YEAR,
            PROBE_SEQ,
        )
        assert row is not None, "legacy migration probe row disappeared"
        assert row["contract_number"] == PROBE_NUMBER
        assert row["partner_name"] == "Historyczny Partner"
        assert row["client_name"] == "Historyczny Klient"
        assert row["language"] == "pl"
        assert row["signing_date"] == "2026-07-24"
        assert json.loads(row["render_payload"]) == {
            "probe": "0195",
            "preserve": True,
        }
        assert row["signature_status"] == "unsigned"
        for field in (
            "signature_source",
            "candidate_id",
            "job_id",
            "client_id",
            "contract_id",
            "signed_at",
            "signed_by_user_id",
        ):
            assert row[field] is None, f"{field} was unexpectedly backfilled"

        constraint_names = {
            record["conname"]
            for record in await connection.fetch(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'b2b_generated_contracts'::regclass
                  AND convalidated
                """
            )
        }
        expected_constraints = {
            "ck_b2b_generated_contracts_signature_status",
            "ck_b2b_generated_contracts_signature_source",
            "fk_b2b_generated_contracts_candidate_id",
            "fk_b2b_generated_contracts_job_id",
            "fk_b2b_generated_contracts_client_id",
            "fk_b2b_generated_contracts_contract_id",
            "fk_b2b_generated_contracts_signed_by_user_id",
        }
        assert expected_constraints <= constraint_names

        await connection.execute(
            """
            DELETE FROM b2b_generated_contracts
            WHERE year = $1 AND seq = $2
            """,
            PROBE_YEAR,
            PROBE_SEQ,
        )
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "verify"))
    args = parser.parse_args()
    asyncio.run(_seed() if args.action == "seed" else _verify())


if __name__ == "__main__":
    main()
