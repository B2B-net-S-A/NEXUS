"""User OAuth fields (Microsoft SSO) + auth_exchange_codes table.

Revision ID: 0081_user_oauth_fields
Revises: 0080_autenti_signatures, 0080_candidates_cv_storage_key
Create Date: 2026-05-07 16:00:00.000000

Multi-head merge: pulls together two parallel ``0080`` heads that branched
from ``0079_candidate_documents_storage_key``:
- ``0080_autenti_signatures`` (e-signature schema, PR #102)
- ``0080_candidates_cv_storage_key`` (CV → S3 migration, PR #105)

Faza B (SSO "Sign in with Microsoft"):

1. Rozszerzenie tabeli ``users`` o pola identity-provider:
   - ``oauth_provider`` (np. "microsoft") — dotąd NULL dla email/password.
   - ``external_id`` — provider-side stable id (Azure ``oid``).
   - ``azure_oid``, ``microsoft_upn`` — denormalized do raportów + matchowania.
   - ``ALTER password_hash DROP NOT NULL`` — pozwala SSO-only userom istnieć
     bez bcrypt hash. Email+password userzy (artur@b2bnet.pl, claude-admin)
     zachowują niezmienione kolumny.

2. Nowa tabelka ``auth_exchange_codes`` — one-time UUID4 codes do bezpiecznego
   przekazania tokenów z OAuth callbacka do frontu. Rationale: token w
   query string redirectu trafiałby do logów proxy / Sentry / browser history.
   Backend zapisuje (code, access_token, refresh_token, expires_at), redirectuje
   na /login/microsoft/callback?code=<uuid>, frontend POST-uje code → JSON.
   TTL 60s, jednorazowy (consumed_at), partial unique na (oauth_provider,external_id).

Safety net (konwencja z 0078/0080):
- ``IF NOT EXISTS`` na ADD COLUMN (PG 9.6+).
- Partial unique index zamiast full UNIQUE — pozwala na N userów z
  ``oauth_provider IS NULL`` (legacy email/password), wymusza unikalność tylko
  dla par provider+external_id.

Downgrade dropuje wszystko poza ``password_hash NOT NULL`` (re-adding NOT NULL
wymagałoby pewności że żaden wiersz nie ma NULL — w trakcie rollbacku
ryzykowne, więc zostawiamy nullable).
"""

import sqlalchemy as sa
from alembic import op


revision = "0081_user_oauth_fields"
down_revision = (
    "0080_autenti_signatures",
    "0080_candidates_cv_storage_key",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) users — add OAuth identity columns (idempotent for safety on retries).
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(32)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS external_id VARCHAR(128)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS azure_oid VARCHAR(64)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS microsoft_upn VARCHAR(255)")

    # password_hash nullable — pozwala SSO-only userom (recruiter z
    # @b2bnetwork.pl) istnieć bez bcrypt hash. Istniejący userzy zachowują
    # swoje hashe, kolumna była NOT NULL — DROP NOT NULL jest in-place i
    # nie touchuje danych.
    op.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")

    # Partial unique: tylko dla SSO-providerów. Pozwala na wielu userów z
    # oauth_provider=NULL (legacy email/password).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_oauth_provider_external_id "
        "ON users (oauth_provider, external_id) WHERE oauth_provider IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_azure_oid ON users (azure_oid)")

    # 2) auth_exchange_codes — one-time tokens dla SSO callback → frontend.
    op.create_table(
        "auth_exchange_codes",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_auth_exchange_codes_expires_at",
        "auth_exchange_codes",
        ["expires_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_exchange_codes_expires_at",
        table_name="auth_exchange_codes",
        if_exists=True,
    )
    op.drop_table("auth_exchange_codes", if_exists=True)
    op.execute("DROP INDEX IF EXISTS ix_users_azure_oid")
    op.execute("DROP INDEX IF EXISTS ux_users_oauth_provider_external_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS microsoft_upn")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS azure_oid")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS external_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS oauth_provider")
    # NB: password_hash zostaje nullable po downgrade (re-adding NOT NULL
    # wymaga pewności że nie ma NULL-i — bezpieczniej zostawić).
