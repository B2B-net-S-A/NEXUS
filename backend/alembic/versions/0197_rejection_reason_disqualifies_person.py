"""Mark which rejection reasons are a verdict about the *person*.

A hiring manager who interviewed a candidate and rejected them must not be
offered that candidate again. But not every rejection says something about the
candidate: "za wysokie oczekiwania finansowe" or "zatrudniony gdzie indziej"
are situational and must never block a future submission. This flag is the
switch that separates the two, editable by an admin without a deploy.

Default is ``false`` — an unknown or unlabelled reason never blocks
(fail-open). The seed backfill is gated on a one-shot marker row in
``app_settings``: the entrypoint safety-net replays this statement on every
container start, and without the marker a redeploy would silently restore the
seeded flags and undo an admin's deliberate change in the settings panel.
The marker is written in the same statement that seeds, so the two cannot
diverge — and unlike "is anything flagged yet?", it still holds when an admin
turns *all* the seeded reasons off.

Also indexes ``candidate_stages.rejection_reason_id``: it had a foreign key but
no index, and the verdict lookup joins through it.

Revision ID: 0197_rejection_reason_disqualifies_person
Revises: 0196_b2b_signature_automation
"""

from alembic import op


revision = "0197_rejection_reason_disqualifies_person"
down_revision = "0196_b2b_signature_automation"
branch_labels = None
depends_on = None


# Mirrored in entrypoint.sh `_DATA_STATEMENTS`; both sides must stay in sync
# (see tests/test_rejection_reason_disqualifies.py).
SEED_MARKER_KEY = "rejection_reason_disqualifies_seeded"

# Seeded in 0006_pipeline_templates. Only reasons that judge the candidate.
# "Inne (rejected)" stays false on purpose — a 409 justified by "Inne" is
# indefensible to the recruiter who hits it.
_DISQUALIFYING_SEED_NAMES = (
    "Brak doświadczenia",
    "Nie spełnia wymagań technicznych",
    "Nie pasuje kulturowo",
)


def upgrade() -> None:
    # Production bootstrapping mirrors this additive DDL in entrypoint.sh
    # because some installations cannot yet rely on Alembic being current.
    # Every statement must therefore tolerate the safety-net having run first.
    op.execute(
        """
        ALTER TABLE rejection_reasons
            ADD COLUMN IF NOT EXISTS disqualifies_person BOOLEAN
                NOT NULL DEFAULT false
        """
    )

    # One-shot: the marker insert and the seed are the same statement, so the
    # seed can only fire on the run that claims the marker.
    names = ", ".join(f"'{n}'" for n in _DISQUALIFYING_SEED_NAMES)
    op.execute(
        f"""
        WITH marker AS (
            INSERT INTO app_settings (key, value)
            VALUES ('{SEED_MARKER_KEY}', 'true'::jsonb)
            ON CONFLICT (key) DO NOTHING
            RETURNING key
        )
        UPDATE rejection_reasons
           SET disqualifies_person = true
         WHERE category = 'rejected'
           AND name IN ({names})
           AND EXISTS (SELECT 1 FROM marker)
        """
    )

    # FK without an index — the verdict lookup joins candidate_stages →
    # rejection_reasons on this column.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_candidate_stages_rejection_reason_id
            ON candidate_stages (rejection_reason_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidate_stages_rejection_reason_id")
    op.execute(
        "ALTER TABLE rejection_reasons DROP COLUMN IF EXISTS disqualifies_person"
    )
