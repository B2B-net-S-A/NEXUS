"""Kubełek kwoty dla dat zatrudnienia dopisywanych z kartoteki firmy (ATLAS).

Revision ID: 0319_experience_dates_on_demand
Revises: 0318_dl_alert_md_base_usage_high

`experience_dates_on_demand` — dopisywanie DAT do `candidates.experience` dla
osób, które ATLAS właśnie pokazał na kartotece firmy. OSOBNY kubełek od
`cv_backfill`, mimo że obie ścieżki wołają ten sam moduł:

16.09.2026 zgaszenie `cv_backfill` (jedyny wtedy sposób zatrzymania biegu
masowego) ubiło rykoszetem fazę `candidates_cv_fields` nocnego syncu Traffita,
bo dzieliła ten sam klucz. Ścieżka uruchamiana ruchem użytkownika w INNEJ
aplikacji musi dać się wyłączyć bez gaszenia nocnej — i odwrotnie.

Kalka 0275/0240: ADD VALUE w autocommicie (wymóg `ALTER TYPE`), seed poza
blokiem i idempotentny. Zdublowane w safety-necie `entrypoint.sh` — prod
alembic bywa orphaned.
"""

from alembic import op

revision = "0319_experience_dates_on_demand"
down_revision = "0318_dl_alert_md_base_usage_high"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE musi biec w autocommicie: Postgres nie pozwala użyć nowej
    # etykiety enuma w tej samej transakcji, w której ją dodano — a seed niżej
    # używa jej jako literału.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS "
            "'experience_dates_on_demand'"
        )

    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'experience_dates_on_demand', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM ai_features WHERE feature = 'experience_dates_on_demand')"
    )


def downgrade() -> None:
    # Wartości enuma w Postgresie nie da się usunąć bez przepisania typu, a
    # `ai_features` trzyma do niej FK przez kolumnę. Kasujemy tylko wiersz —
    # nieużywana etykieta enuma nikomu nie szkodzi.
    op.execute("DELETE FROM ai_features WHERE feature = 'experience_dates_on_demand'")
