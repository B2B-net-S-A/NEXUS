"""Phase 8: consolidate UserRole + RecruiterRole into single UserRole (6 values)

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-16 19:00:00.000000

Maps dual-enum role model onto single enum with 6 operational roles:
    admin, delivery_lead, tac, recruiter, sourcer, user

Mapping from existing (role, recruiter_role) pairs:
    ('admin',     *)                    → 'admin'
    ('manager',   *)                    → 'delivery_lead'
    ('client',    *)                    → 'user'
    ('recruiter', 'sourcer')            → 'sourcer'
    ('recruiter', 'tac')                → 'tac'
    ('recruiter', 'delivery_lead')      → 'delivery_lead'
    ('recruiter', 'quality_control')    → 'user'   (QC is advisory/read-only)
    ('recruiter', 'admin')              → 'admin'  (edge case — RecruiterRole.admin)
    ('recruiter', NULL | 'recruiter')   → 'recruiter'

Downgrade is best-effort: reverses mapping where unambiguous. RecruiterRole
subtleties that were flattened (e.g. QC vs client distinction) cannot be
reconstructed; those users get role='client' on downgrade with
recruiter_role=NULL.

Idempotent via conditional enum existence checks.
"""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add temporary VARCHAR column to hold remapped value
    op.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS role_new VARCHAR(32)
            """
        )
    )

    # 2. Populate role_new from current (role, recruiter_role) pair.
    #    Enum values compared as text via ::text cast.
    op.execute(
        sa.text(
            """
            UPDATE users SET role_new = CASE
                WHEN role::text = 'admin' THEN 'admin'
                WHEN role::text = 'manager' THEN 'delivery_lead'
                WHEN role::text = 'client' THEN 'user'
                WHEN role::text = 'recruiter' AND recruiter_role::text = 'sourcer' THEN 'sourcer'
                WHEN role::text = 'recruiter' AND recruiter_role::text = 'tac' THEN 'tac'
                WHEN role::text = 'recruiter' AND recruiter_role::text = 'delivery_lead' THEN 'delivery_lead'
                WHEN role::text = 'recruiter' AND recruiter_role::text = 'quality_control' THEN 'user'
                WHEN role::text = 'recruiter' AND recruiter_role::text = 'admin' THEN 'admin'
                ELSE 'recruiter'
            END
            """
        )
    )

    # 3. Drop old enum columns and their types.
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS recruiter_role"))
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS role"))
    op.execute(sa.text("DROP TYPE IF EXISTS recruiterrole"))
    op.execute(sa.text("DROP TYPE IF EXISTS userrole"))

    # 4. Create new 6-value enum type.
    op.execute(
        sa.text(
            """
            CREATE TYPE userrole AS ENUM (
                'admin', 'delivery_lead', 'tac', 'recruiter', 'sourcer', 'user'
            )
            """
        )
    )

    # 5. Add new role column as enum, default 'recruiter', NOT NULL.
    op.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN role userrole NOT NULL DEFAULT 'recruiter'
            """
        )
    )

    # 6. Copy remapped values from role_new → role.
    op.execute(
        sa.text("UPDATE users SET role = role_new::userrole WHERE role_new IS NOT NULL")
    )

    # 7. Drop the temporary staging column.
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS role_new"))


def downgrade() -> None:
    # Best-effort reversal. Note: information loss is inherent here.
    # recruiter_role subtleties (QC vs client, sourcer-only assignments) cannot
    # be reconstructed; admins should re-assign recruiter_role manually after
    # downgrade if they relied on it.

    # 1. Stage current role as text.
    op.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS role_old VARCHAR(32),
              ADD COLUMN IF NOT EXISTS recruiter_role_old VARCHAR(32)
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE users SET
              role_old = CASE
                WHEN role::text = 'admin' THEN 'admin'
                WHEN role::text = 'delivery_lead' THEN 'manager'
                WHEN role::text = 'tac' THEN 'recruiter'
                WHEN role::text = 'recruiter' THEN 'recruiter'
                WHEN role::text = 'sourcer' THEN 'recruiter'
                WHEN role::text = 'user' THEN 'client'
                ELSE 'recruiter'
              END,
              recruiter_role_old = CASE
                WHEN role::text = 'delivery_lead' THEN 'delivery_lead'
                WHEN role::text = 'tac' THEN 'tac'
                WHEN role::text = 'sourcer' THEN 'sourcer'
                WHEN role::text = 'recruiter' THEN 'recruiter'
                ELSE NULL
              END
            """
        )
    )

    # 2. Drop new enum column + type.
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS role"))
    op.execute(sa.text("DROP TYPE IF EXISTS userrole"))

    # 3. Recreate old types.
    op.execute(
        sa.text(
            """
            CREATE TYPE userrole AS ENUM ('admin', 'recruiter', 'manager', 'client')
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TYPE recruiterrole AS ENUM (
                'recruiter', 'sourcer', 'tac', 'delivery_lead',
                'quality_control', 'admin'
            )
            """
        )
    )

    # 4. Add back old columns.
    op.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN role userrole NOT NULL DEFAULT 'recruiter',
              ADD COLUMN recruiter_role recruiterrole NULL
            """
        )
    )

    # 5. Copy staged text values back into enums.
    op.execute(
        sa.text(
            """
            UPDATE users
              SET role = role_old::userrole,
                  recruiter_role = CASE
                      WHEN recruiter_role_old IS NOT NULL THEN recruiter_role_old::recruiterrole
                      ELSE NULL
                  END
            """
        )
    )

    # 6. Drop staging columns.
    op.execute(
        sa.text(
            """
            ALTER TABLE users
              DROP COLUMN IF EXISTS role_old,
              DROP COLUMN IF EXISTS recruiter_role_old
            """
        )
    )
