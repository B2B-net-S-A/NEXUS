"""Klucz AI „AI na zaznaczonym fragmencie” w edytorze CV (13.10.2026).

Revision ID: 0432_cv_selection_edit_ai_key
Revises: 0431_consultant_elsewhere_notif

Edytor CV 2, PR 3: ``cv_selection_edit`` — skróć, rozwiń z oryginału,
przeredaguj, popraw język, na angielski. Trasa niczego nie zapisuje w szkicu
CV, więc schemat się nie zmienia. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0432_cv_selection_edit_ai_key"
down_revision = "0431_consultant_elsewhere_notif"
branch_labels = None
depends_on = None

_KEY = "cv_selection_edit"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed
# tej rewizji jej nie zna — wpis w dzienniku AI dałby 500.
REFUSE_WITH_USAGE = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0432 odmawia: ai_usage_log ma wpisy AI na zaznaczeniu w edytorze CV, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_USAGE)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
