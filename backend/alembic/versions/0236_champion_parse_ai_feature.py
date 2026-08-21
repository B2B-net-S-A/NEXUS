"""Champion ingest: AIFeatureKey ``champion_profile_parse`` + seed.

Revision ID: 0236_champion_parse_ai_feature
Revises: 0235_job_rate_budget_hourly

Klucz kwotowy dla endpointu ingestu profili Championa (domknięcie ~140 luk
po imporcie 08.2026 + świeży sync nowych rekrutacji przez collector w sesji
przeglądarki). OSOBNY kubełek od ``cv_parser``/``notes_extraction`` z tego
samego powodu co 0214/0230: powierzchnia wsadowa nie może wyczerpać limitu
funkcji interaktywnych ani wymusić limitu, który przestaje chronić.

Kalka 0230: ADD VALUE w autocommit (wymóg ALTER TYPE), seed idempotentny.
Zdublowane w safety-net ``entrypoint.sh`` (prod alembic bywa orphaned).
"""

from alembic import op

revision = "0236_champion_parse_ai_feature"
down_revision = "0235_job_rate_budget_hourly"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'champion_profile_parse'"
        )

    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'champion_profile_parse', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'champion_profile_parse')"
    )


def downgrade() -> None:
    # PostgreSQL nie kasuje wartości enuma in-place — wartość zostaje w typie
    # (bezpieczna, nieużywana po usunięciu seedu).
    op.execute("DELETE FROM ai_features WHERE feature = 'champion_profile_parse'")
