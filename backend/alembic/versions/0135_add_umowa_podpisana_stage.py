"""Add "Umowa podpisana" stage to the Default B2B pipeline template.

Revision ID: 0135_add_umowa_podpisana_stage
Revises: 0134_merge_0133_heads
Create Date: 2026-06-17

The in-house QES flow advances the candidate to "Umowa wysłana" on send and
"Umowa podpisana" when the signed PDF returns. "Umowa wysłana" already exists in
the Default B2B template (id 1); this inserts "Umowa podpisana" right after it
(before "Zatrudniony"), shifting later stages' order by 1.

Data migration — idempotent (NOT EXISTS guard) and no-ops on DBs where the
Default B2B template / "Umowa wysłana" stage isn't seeded (fresh CI DB). The
+1000 temporary offset avoids transient unique-constraint (template_id, order)
violations during the shift.
"""

from alembic import op

revision = "0135_add_umowa_podpisana_stage"
down_revision = "0134_merge_0133_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE wyslana_order integer;
        BEGIN
            SELECT "order" INTO wyslana_order
              FROM pipeline_stage_defs
              WHERE template_id = 1 AND name = 'Umowa wysłana'
              LIMIT 1;

            IF wyslana_order IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM pipeline_stage_defs
                   WHERE template_id = 1 AND name = 'Umowa podpisana'
               ) THEN
                UPDATE pipeline_stage_defs
                  SET "order" = "order" + 1000
                  WHERE template_id = 1 AND "order" > wyslana_order;

                INSERT INTO pipeline_stage_defs
                    (template_id, name, "order", category, is_terminal,
                     created_at, updated_at)
                  VALUES
                    (1, 'Umowa podpisana', wyslana_order + 1, 'external', false,
                     NOW(), NOW());

                UPDATE pipeline_stage_defs
                  SET "order" = "order" - 999
                  WHERE template_id = 1 AND "order" > 1000;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE podpisana_order integer;
        BEGIN
            SELECT "order" INTO podpisana_order
              FROM pipeline_stage_defs
              WHERE template_id = 1 AND name = 'Umowa podpisana'
              LIMIT 1;

            IF podpisana_order IS NOT NULL THEN
                DELETE FROM pipeline_stage_defs
                  WHERE template_id = 1 AND name = 'Umowa podpisana';
                UPDATE pipeline_stage_defs
                  SET "order" = "order" - 1
                  WHERE template_id = 1 AND "order" > podpisana_order;
            END IF;
        END $$;
        """
    )
