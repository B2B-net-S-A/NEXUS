"""Źródło dnia podpisu umowy B2B (premia 200% liczy podpis konsultanta).

Revision ID: 0654_b2b_signed_on_source
Revises: 0653_hr_bonus_guarantee

Decyzja Artura z 06.11.2026: dzień podpisu do premii 200% pochodzi z podpisu
kwalifikowanego konsultanta w podpisanym PDF-ie, nie z kliknięcia „Oznacz jako
podpisaną” (w jednej z umów DL oznaczył 30.10, konsultant podpisał 02.11).

* ``signed_on_source`` — ``pdf`` | ``manual`` | ``esign``; NULL = wiersz sprzed
  tej zmiany (data z okna z domyślnie dzisiejszą datą),
* ``signed_on_reason`` — powód ręcznej daty (podpis odręczny, poprawka Płac),
* ``signed_on_set_by`` — kto wpisał datę ręcznie,
* ``consultant_signed_at`` — chwila podpisu konsultanta z pliku albo e-podpisu.

Starszych wierszy nie uzupełniamy. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0654_b2b_signed_on_source"
down_revision = "0653_hr_bonus_guarantee"
branch_labels = None
depends_on = None

_TABLE = "b2b_generated_contracts"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS signed_on_source VARCHAR(16)"
    )
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS signed_on_reason TEXT")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS signed_on_set_by "
        "INTEGER REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS consultant_signed_at TIMESTAMPTZ"
    )
    op.execute(
        f"""DO $$ BEGIN
            ALTER TABLE {_TABLE}
                ADD CONSTRAINT ck_b2b_generated_contracts_signed_on_source
                CHECK (
                    signed_on_source IS NULL OR
                    signed_on_source IN ('pdf', 'manual', 'esign')
                );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$"""
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS "
        "ck_b2b_generated_contracts_signed_on_source"
    )
    for column in (
        "consultant_signed_at",
        "signed_on_set_by",
        "signed_on_reason",
        "signed_on_source",
    ):
        op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS {column}")
