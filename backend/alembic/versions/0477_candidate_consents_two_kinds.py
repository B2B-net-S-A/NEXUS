"""Strona kariery: dwie zgody zamiast jednej (decyzja D, 19.10.2026).

Revision ID: 0477_candidate_consents_two_kinds
Revises: 0476_hr_profile_follows_account

Poszerza ``ck_candidate_consents_kind`` o ``recruitment_current``
(obowiązkowa, ta rekrutacja) i ``recruitment_future`` (dobrowolna, przyszłe
rekrutacje). Wiersze ``recruitment_current_future`` zostają bez zmian.

Lustro w ``entrypoint.sh`` — pilnuje ``tests/test_career_migration_mirror.py``.
"""

from alembic import op

revision = "0477_candidate_consents_two_kinds"
down_revision = "0476_hr_profile_follows_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_consents "
        "DROP CONSTRAINT IF EXISTS ck_candidate_consents_kind"
    )
    op.execute(
        "ALTER TABLE candidate_consents ADD CONSTRAINT ck_candidate_consents_kind "
        "CHECK (kind IN ('recruitment_current_future', 'recruitment_current', "
        "'recruitment_future'))"
    )


def downgrade() -> None:
    # Zebranych zgód nie kasujemy — stary więz wraca bez sprawdzania wierszy.
    op.execute(
        "ALTER TABLE candidate_consents "
        "DROP CONSTRAINT IF EXISTS ck_candidate_consents_kind"
    )
    op.execute(
        "ALTER TABLE candidate_consents ADD CONSTRAINT ck_candidate_consents_kind "
        "CHECK (kind IN ('recruitment_current_future')) NOT VALID"
    )
