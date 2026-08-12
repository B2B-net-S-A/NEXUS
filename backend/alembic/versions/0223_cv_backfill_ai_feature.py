"""Fala 3: nowy AIFeatureKey ``cv_backfill`` + seed ai_features.

Revision ID: 0223_cv_backfill_ai_feature
Revises: 0222_rename_talent_radar_source
Create Date: 2026-08-12

Osobny klucz kwoty dla masowego uzupełniania pól kandydata z tekstu CV.
Świadomie NIE ``cv_parser``: wspólny kubełek znaczy, że bieg na ~39 tys. CV
albo wyczerpie miesięczny limit rekruterów, albo zmusi do podniesienia go do
poziomu, na którym przestaje chronić funkcję interaktywną.

Enum ``aifeaturekey`` istnieje od 0085 — tu tylko dodajemy wartość i seedujemy
domyślny wiersz (enabled, unlimited). ADD VALUE musi lecieć w autocommit.
Zdublowane w safety-net ``entrypoint.sh`` (prod alembic bywa orphaned).
"""

from alembic import op

revision = "0223_cv_backfill_ai_feature"
down_revision = "0222_rename_talent_radar_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_backfill'")

    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'cv_backfill', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'cv_backfill')"
    )


def downgrade() -> None:
    # PostgreSQL nie umie kasować wartości enuma in-place — 'cv_backfill'
    # zostaje w typie (bezpieczne, nikt jej nie użyje po usunięciu seeda).
    op.execute("DELETE FROM ai_features WHERE feature = 'cv_backfill'")
