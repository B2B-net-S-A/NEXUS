"""Konta serwisowe i klucze API — uwierzytelnianie automatyzacji bez JWT człowieka.

Revision ID: 0220_service_accounts
Revises: 0219_help_materials_champion_profiles
Create Date: 2026-08-11

Dwie tabele:

1. ``service_accounts`` — nieosobowa tożsamość (cron, CI, skrypt operacyjny)
   z własnym, wąskim zestawem scope'ów. Świadomie NIE wiersz w ``users``:
   konto serwisowe udające użytkownika wyciekłoby do list userów, KPI,
   powiadomień i eksportów RODO.
2. ``service_account_keys`` — poświadczenia, N na konto (rotacja bez przestoju:
   wydaj drugi → wdroż → rewokuj pierwszy). Sekret pokazywany RAZ; w bazie
   wyłącznie SHA-256, PK to nie-sekretny revoke-key ``v2$<hex>`` — ten sam
   wzorzec co ``cv_generated_share_tokens`` (0217).

Całość zdublowana w safety-necie ``entrypoint.sh`` (prod alembic bywa orphaned).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0220_service_accounts"
down_revision = "0219_help_materials_champion_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Stabilny identyfikator w logach i audycie. ``name`` bywa przemianowane,
        # slug nie — inaczej historia rozpada się na dwa byty.
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "scopes",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Lustro ``ck_users_roles_array``: scopes musi być tablicą JSON.
        # Gdyby wiersz trzymał string, sprawdzenie uprawnień w Pythonie zrobiłoby
        # z ``in`` test podciągu i cicho rozszerzyło uprawnienia.
        sa.CheckConstraint(
            "jsonb_typeof(scopes) = 'array'",
            name="ck_service_accounts_scopes_array",
        ),
    )
    op.create_index(
        "ix_service_accounts_slug", "service_accounts", ["slug"], unique=True
    )

    op.create_table(
        "service_account_keys",
        # PK = revoke-key ``v2$<hex>``. Nie jest sekretem: trafia do listingów,
        # logów i komunikatów, żeby audyt „którym kluczem" był wykonalny.
        sa.Column("key_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "service_account_id",
            sa.Integer(),
            sa.ForeignKey("service_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("secret_sha256", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # NOT NULL bez server_default — termin wylicza aplikacja przy wydaniu
        # klucza (domyślnie 90 dni, sufit z configu). Domyślna wartość w bazie
        # pozwoliłaby wstawić klucz bez świadomej decyzji o terminie.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoke_reason", sa.String(length=255), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_service_account_keys_service_account_id",
        "service_account_keys",
        ["service_account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_account_keys_service_account_id",
        table_name="service_account_keys",
    )
    op.drop_table("service_account_keys")
    op.drop_index("ix_service_accounts_slug", table_name="service_accounts")
    op.drop_table("service_accounts")
