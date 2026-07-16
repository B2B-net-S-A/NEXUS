"""CV share token v2 — hash zamiast sekretu, TTL/max views, audit odwołań.

M4 audyt P1.9 (plan PR-04): tokeny publicznych linków CV były długowieczne
i przechowywane w postaci raw (każdy z dostępem do DB zna sekret; rekruter
znający raw token mógł nim operować). v2:

- ``token_sha256`` — nowe tokeny trzymają wyłącznie skrót SHA-256; raw jest
  pokazywany użytkownikowi raz. Kolumna ``token`` (PK) dla v2 dostaje
  nie-sekretny identyfikator ``v2$<hex>`` używany jako revoke-key.
- ``max_views`` + ``view_count`` + ``last_viewed_at`` — limit i licznik
  wyświetleń (egzekwowane atomowym UPDATE w public endpoint).
- ``revoked_at`` / ``revoked_by`` / ``revoke_reason`` — audyt odwołania.
- ``purpose`` — po co link powstał (audience/purpose scope, wolny opis).

Legacy wiersze (raw w ``token``, NULL w ``token_sha256``) działają w
dual-read do wygaśnięcia. Mirror w ``backend/entrypoint.sh``.

Revision ID: 0176_cv_share_token_v2
Revises: 0175_stage_notif_user_fk_cascade
"""

from alembic import op

revision = "0176_cv_share_token_v2"
down_revision = "0175_stage_notif_user_fk_cascade"
branch_labels = None
depends_on = None

_COLUMNS = [
    "ADD COLUMN IF NOT EXISTS token_sha256 VARCHAR(64)",
    "ADD COLUMN IF NOT EXISTS max_views INTEGER",
    "ADD COLUMN IF NOT EXISTS view_count INTEGER NOT NULL DEFAULT 0",
    "ADD COLUMN IF NOT EXISTS last_viewed_at TIMESTAMPTZ",
    "ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ",
    (
        "ADD COLUMN IF NOT EXISTS revoked_by INTEGER "
        "REFERENCES users(id) ON DELETE SET NULL"
    ),
    "ADD COLUMN IF NOT EXISTS revoke_reason VARCHAR(255)",
    "ADD COLUMN IF NOT EXISTS purpose VARCHAR(120)",
]


def upgrade() -> None:
    for clause in _COLUMNS:
        op.execute(f"ALTER TABLE cv_share_tokens {clause}")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_cv_share_tokens_sha256 "
        "ON cv_share_tokens (token_sha256) WHERE token_sha256 IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_cv_share_tokens_sha256")
    for col in (
        "token_sha256",
        "max_views",
        "view_count",
        "last_viewed_at",
        "revoked_at",
        "revoked_by",
        "revoke_reason",
        "purpose",
    ):
        op.execute(f"ALTER TABLE cv_share_tokens DROP COLUMN IF EXISTS {col}")
