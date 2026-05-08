"""Custom-field schema editor (Traffit gap #7).

Revision ID: 0089_entity_field_defs
Revises: 0088_dictionaries
Create Date: 2026-05-08 14:45:00.000000

Adds ``entity_field_defs`` to back the Settings → Konfiguracja pól page.
Lets admins define custom fields per Candidate / Job entity without a
deploy. Field VALUES still live in the existing ``custom_fields`` JSONB
column on the parent entity; this table holds the SCHEMA only.

Two new enums:
- ``entityfieldtype`` — which entity (candidate / job)
- ``entityfieldtypeenum`` — renderable field type (text, number, ...)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0089_entity_field_defs"
down_revision = "0088_dictionaries"
branch_labels = None
depends_on = None


_ENTITY_TYPES = ("candidate", "job")
_FIELD_TYPES = (
    "text",
    "long_text",
    "number",
    "checkbox",
    "radio",
    "select",
    "multi_select",
    "date",
    "datetime",
    "file",
    "files",
    "location",
    "link",
)


def upgrade() -> None:
    # Idempotent enum creation — same DO $$ pattern as 0085 / 0087.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE entityfieldtype AS ENUM ('candidate', 'job');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE entityfieldtypeenum AS ENUM (
                'text','long_text','number','checkbox','radio','select',
                'multi_select','date','datetime','file','files',
                'location','link'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.create_table(
        "entity_field_defs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entity_type",
            postgresql.ENUM(*_ENTITY_TYPES, name="entityfieldtype", create_type=False),
            nullable=False,
        ),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("label_pl", sa.String(200), nullable=False),
        sa.Column("label_en", sa.String(200), nullable=True),
        sa.Column("help_text", sa.String(500), nullable=True),
        sa.Column(
            "field_type",
            postgresql.ENUM(
                *_FIELD_TYPES, name="entityfieldtypeenum", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "options",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("section", sa.String(40), nullable=True, server_default="middle"),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_edited_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "entity_type", "key", name="uq_entity_field_defs_entity_key"
        ),
    )
    op.create_index(
        "ix_entity_field_defs_entity_type",
        "entity_field_defs",
        ["entity_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_field_defs_entity_type", table_name="entity_field_defs")
    op.drop_table("entity_field_defs")
    op.execute("DROP TYPE IF EXISTS entityfieldtypeenum")
    op.execute("DROP TYPE IF EXISTS entityfieldtype")
