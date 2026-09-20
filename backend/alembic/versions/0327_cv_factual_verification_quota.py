"""Kubełek kwoty dla niezależnej kontroli AI treści CV (drugi model).

Revision ID: 0327_cv_factual_verification
Revises: 0326_candidate_documents_sha256_index

`cv_factual_verification` — recenzja gotowego CV względem źródeł, robiona
INNYM modelem niż generator (GPT Luna; decyzja Artura 18.09.2026). Osobny
kubełek od `cv_generator`, choć obie ścieżki biegną w jednym żądaniu:

badanie modeli z 16.09 zmierzyło, że sędzia LLM faworyzuje własne wyjście,
więc recenzent MUSI być innym modelem — a skoro to inny model i inny dostawca,
to i inny strumień wydatku. Bez osobnego kubełka koszt kontroli schowałby się
w koszcie generacji i nie dałoby się odpowiedzieć, ile kosztuje samo
sprawdzanie ani zgasić go bez gaszenia generatora.

Kalka 0319/0275/0240: ADD VALUE w autocommicie (wymóg `ALTER TYPE`), seed poza
blokiem i idempotentny. Zdublowane w safety-necie `entrypoint.sh` — prod
alembic bywa orphaned.
"""

from alembic import op

revision = "0327_cv_factual_verification"
down_revision = "0326_candidate_documents_sha256_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE musi biec w autocommicie: Postgres nie pozwala użyć nowej
    # etykiety enuma w tej samej transakcji, w której ją dodano — a seed niżej
    # używa jej jako literału.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_factual_verification'"
        )

    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'cv_factual_verification', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM ai_features WHERE feature = 'cv_factual_verification')"
    )


def downgrade() -> None:
    # Wartości enuma w Postgresie nie da się usunąć bez przepisania typu, a
    # `ai_features` trzyma do niej FK przez kolumnę. Kasujemy tylko wiersz —
    # nieużywana etykieta enuma nikomu nie szkodzi.
    op.execute("DELETE FROM ai_features WHERE feature = 'cv_factual_verification'")
