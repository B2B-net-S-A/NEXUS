"""Session-revocation floor on users (tokens_valid_after) — F-05.

Dodaje ``users.tokens_valid_after TIMESTAMPTZ`` (nullable). Zamyka dziurę:
po zmianie / resecie hasła wcześniej wybite JWT-y żyły do naturalnego wygaśnięcia,
więc wykradziony/wyciekły token przeżywał reset hasła. Backend ustawia tę kolumnę
na ``now()`` przy każdym zdarzeniu zmiany hasła (self-service change-password,
reset przez token z maila, admin-reset) i odrzuca (401) token, którego ``iat``
jest ściśle wcześniejszy niż ta wartość — w ``get_current_user`` oraz na ścieżce
``/api/auth/refresh``.

NULL = brak floora → istniejący userzy (żaden nie miał jeszcze zdarzenia zmiany
hasła po deployu) nie są dotknięci — wszystkie ich obecne tokeny pozostają ważne
aż do naturalnego wygaśnięcia.

Idempotent: ADD COLUMN IF NOT EXISTS — współgra z entrypoint safety-net
(prod alembic jest orphaned na 0152; DDL jest zmirrorowane 1:1 w
backend/entrypoint.sh, bez którego kolumna nigdy nie pojawia się na prod).

Revision ID: 0192_user_tokens_valid_after
Revises: 0191_contract_lifecycle_invariant
Create Date: 2026-07-22
"""

from alembic import op

revision = "0192_user_tokens_valid_after"
down_revision = "0191_contract_lifecycle_invariant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS tokens_valid_after TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS tokens_valid_after")
