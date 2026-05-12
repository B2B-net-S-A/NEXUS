"""Extend contacts with key-relationship fields (DL ↔ contact intimacy).

Revision ID: 0096_contacts_key_relationship
Revises: 0095_add_order_rate_client
Create Date: 2026-05-11 18:00:00.000000

Cel: DL na bieżąco buduje relacje z osobami u klienta. Niektóre z osób
kontaktowych to "key relationships" — osoby z którymi DL ma osobistą więź
(różne semantycznie od `is_decision_maker` które dotyczy ich hierarchii w
firmie klienta, nie naszej relacji).

Dodaje 5 kolumn:
- `is_key_relationship` BOOL DEFAULT FALSE — flaga "DL ma dobre relacje"
- `relationship_strength` ENUM — cold/warm/strong/champion
- `relationship_notes` TEXT — długi opis (birthdays, hobbies, jak rozmawiać)
- `key_relationship_owner_id` FK users — który DL/TAC zbudował relację
- `last_personal_touchpoint_at` TIMESTAMPTZ — kiedy ostatnio "kawa razem"
  (osobne od `last_contacted_at` które rejestruje biznesowy kontakt)
"""

from alembic import op


revision = "0096_contacts_key_relationship"
down_revision = "0095_add_order_rate_client"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Enum dla relationship_strength
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'relationshipstrength') THEN
                CREATE TYPE relationshipstrength AS ENUM (
                    'cold', 'warm', 'strong', 'champion'
                );
            END IF;
        END $$
        """
    )

    # 2) ALTER TABLE contacts — 5 nowych kolumn (idempotent)
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS is_key_relationship BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS relationship_strength relationshipstrength NULL"
    )
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS relationship_notes TEXT NULL"
    )
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS key_relationship_owner_id INTEGER NULL "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS last_personal_touchpoint_at TIMESTAMPTZ NULL"
    )

    # 3) Indexes: key contacts query optimization
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contacts_key_relationship "
        "ON contacts(is_key_relationship) WHERE is_key_relationship = TRUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contacts_relationship_owner "
        "ON contacts(key_relationship_owner_id) "
        "WHERE key_relationship_owner_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contacts_relationship_owner")
    op.execute("DROP INDEX IF EXISTS ix_contacts_key_relationship")
    op.execute(
        "ALTER TABLE contacts DROP COLUMN IF EXISTS last_personal_touchpoint_at"
    )
    op.execute(
        "ALTER TABLE contacts DROP COLUMN IF EXISTS key_relationship_owner_id"
    )
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS relationship_notes")
    op.execute(
        "ALTER TABLE contacts DROP COLUMN IF EXISTS relationship_strength"
    )
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS is_key_relationship")
    op.execute("DROP TYPE IF EXISTS relationshipstrength")
