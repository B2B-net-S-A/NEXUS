"""AIFeatureKey ``cv_generator`` + ``mindy_chat`` (+ seed obu wierszy).

Revision ID: 0240_cv_generator_mindy_ai_features
Revises: 0239_bik_contract_order_backfill

Dwie powierzchnie Claude'a stały CAŁKOWICIE poza systemem kwot, bo nie miały
klucza, którym można by je ograniczyć: generowanie CV B2B (najdroższe wywołanie
w produkcie — 16 384 tokeny outputu, łańcuch Sonnet → Opus, do 3 prób na model)
oraz oba endpointy LLM MINDY. Brak klucza znaczył brak miesięcznego sufitu i
zero wierszy w ``ai_usage_log`` — raport zużycia w Ustawieniach → AI zaniżał
wydatki dokładnie o te dwie pozycje, a ``/api/health.checks.ai_features`` nie
miał ich nawet jak wymienić jako nielimitowanych.

JEDNA rewizja na dwa klucze świadomie: dwie osobne dałyby dwie głowy alembica.

Kalka 0230/0236: ADD VALUE w autocommit (wymóg ``ALTER TYPE`` — Postgres nie
pozwala dodać wartości enuma wewnątrz bloku transakcyjnego, w którym miałaby
być potem użyta), seed idempotentny przez ``WHERE NOT EXISTS``. Zdublowane w
safety-necie ``entrypoint.sh``, bo prod alembic bywa osierocony — bez lustra
funkcja jest na produkcji martwa mimo zielonego CI.
"""

from alembic import op

revision = "0240_cv_generator_mindy_ai_features"
down_revision = "0239_bik_contract_order_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Wartości i seedy wypisane WPROST, bez pętli po f-stringach: klucz ma być
    # do znalezienia grepem w tym pliku (kilka starszych rewizji składa go
    # z f-stringa i przez to nie da się ich znaleźć po nazwie klucza).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_generator'")
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'mindy_chat'")

    # Seed dopiero po autocommicie wartości enuma — INSERT używa jej jako
    # literału, więc w tej samej transakcji co ADD VALUE poleciałby błędem.
    # `monthly_limit = 0` = bez sufitu: wpisanie liczby to decyzja administratora
    # (Ustawienia → AI), a nie migracji. Wiersz jest tu po to, żeby funkcja była
    # WIDOCZNA i policzalna — brak wiersza znaczy „fail-open, ale niewidoczne".
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'cv_generator', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'cv_generator')"
    )
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'mindy_chat', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'mindy_chat')"
    )


def downgrade() -> None:
    # PostgreSQL nie kasuje wartości enuma in-place — wartości zostają w typie
    # (bezpieczne, nieużywane po usunięciu seedu).
    op.execute(
        "DELETE FROM ai_features WHERE feature IN ('cv_generator', 'mindy_chat')"
    )
