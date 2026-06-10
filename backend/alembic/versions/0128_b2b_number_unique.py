"""Generator Umów B2B — UNIQUE(year, seq) na b2b_generated_contracts

Revision ID: 0128_b2b_number_unique
Revises: 0127_client_display_override
Create Date: 2026-06-10 18:30:00.000000

Context:
    Prod miał duplikat numeru umowy (id=6 i id=7 → „1434/2026”): wiersze powstały
    przed PR #469 (brak walidacji unikalności) — id=7 wygenerowany 2026-06-10
    07:09 UTC, fix #469 zdeployowany ~09:00 UTC. SELECT-check z #469 nadal nie
    chroni przed race'em dwóch równoległych renderów; ten constraint domyka to
    na poziomie DB.

    Dlaczego (year, seq), NIE (year, contract_number): od #469 `seq` = liczbowy
    prefiks numeru („1435/2026” → seq=1435), więc unikalność (year, seq) ≡
    unikalność kanonicznego numeru dla wszystkich nowych wierszy. Natomiast
    legacy wiersze (id 5-7) mają seq będący licznikiem wierszy (5,6,7) i
    zdublowany contract_number — index na (year, contract_number) nie zbudowałby
    się na prodzie bez modyfikacji danych (świadomie odroczone do decyzji).
    Pary (year, seq) na prodzie są unikalne (zweryfikowane 2026-06-10).

Safety net: idempotentne (`CREATE UNIQUE INDEX IF NOT EXISTS`).
"""

from alembic import op


revision = "0128_b2b_number_unique"
down_revision = "0127_client_display_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_b2b_generated_contracts_year_seq "
        "ON b2b_generated_contracts (year, seq)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_b2b_generated_contracts_year_seq")
