"""Editable taxonomy tables (Traffit gap #8).

Revision ID: 0088_dictionaries
Revises: 0087_candidate_source_events
Create Date: 2026-05-08 14:30:00.000000

Backs Settings → Słowniki: a single generic (dictionaries, dictionary_items)
pair so admins can extend taxonomies without a deploy. See
``backend/app/models/dictionary.py`` for the rationale on a unified
schema vs per-taxonomy tables.

Seeds two dictionaries that have no enum backing today:
- ``industry`` — sector picker on Job (corresponds to Traffit "Branża")
- ``rejection_reason`` — why a candidate fell out (free-form for now,
  will replace ad-hoc strings on CandidateStage in a follow-up)

Existing enum-backed taxonomies (``CandidateSource``, ``ContractType``,
``RecruitmentType``, ...) are NOT seeded here — they get a
mirror-into-dictionary task when the UI editor is wired into their
respective forms (separate per-taxonomy migrations).
"""

from alembic import op
import sqlalchemy as sa


revision = "0088_dictionaries"
down_revision = "0087_candidate_source_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dictionaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("label_pl", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("enforced", sa.Boolean(), nullable=False, server_default=sa.false()),
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
    )
    op.create_index("ix_dictionaries_slug", "dictionaries", ["slug"])

    op.create_table(
        "dictionary_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "dictionary_id",
            sa.Integer(),
            sa.ForeignKey("dictionaries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("label_pl", sa.String(200), nullable=False),
        sa.Column("label_en", sa.String(200), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "last_edited_by",
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
            "dictionary_id", "key", name="uq_dictionary_items_dict_key"
        ),
    )
    op.create_index(
        "ix_dictionary_items_dictionary_id",
        "dictionary_items",
        ["dictionary_id"],
    )

    # ── Seed two greenfield taxonomies ────────────────────────────────────────

    op.execute(
        """
        INSERT INTO dictionaries (slug, label_pl, description, enforced)
        VALUES
            ('industry', 'Branża', 'Sektor klienta — używane na rekrutacji', false),
            ('rejection_reason', 'Powody odrzucenia',
             'Powody odpadnięcia kandydata — używane w raporcie odrzuceń', false)
        """
    )

    # Initial industries — common B2B Network targets. Admins extend via UI.
    industries = [
        ("banking", "Bankowość"),
        ("insurance", "Ubezpieczenia"),
        ("retail", "Handel detaliczny"),
        ("logistics", "Logistyka"),
        ("manufacturing", "Produkcja"),
        ("software", "Software / IT"),
        ("public_sector", "Sektor publiczny"),
        ("healthcare", "Ochrona zdrowia"),
    ]
    for ordinal, (key, label) in enumerate(industries):
        op.execute(
            f"""
            INSERT INTO dictionary_items (dictionary_id, key, label_pl, ordinal)
            VALUES (
                (SELECT id FROM dictionaries WHERE slug = 'industry'),
                '{key}', '{label.replace("'", "''")}', {ordinal}
            )
            """
        )

    rejection_reasons = [
        ("po_cv", "Po CV"),
        ("po_screeningu", "Po screeningu"),
        ("rate_too_high", "Stawka poza budżetem"),
        ("not_available", "Brak dostępności"),
        ("client_choice", "Wybór klienta"),
        ("candidate_withdrew", "Kandydat się wycofał"),
        ("technical_skills", "Niewystarczające umiejętności techniczne"),
    ]
    for ordinal, (key, label) in enumerate(rejection_reasons):
        op.execute(
            f"""
            INSERT INTO dictionary_items (dictionary_id, key, label_pl, ordinal)
            VALUES (
                (SELECT id FROM dictionaries WHERE slug = 'rejection_reason'),
                '{key}', '{label.replace("'", "''")}', {ordinal}
            )
            """
        )


def downgrade() -> None:
    op.drop_index("ix_dictionary_items_dictionary_id", table_name="dictionary_items")
    op.drop_table("dictionary_items")
    op.drop_index("ix_dictionaries_slug", table_name="dictionaries")
    op.drop_table("dictionaries")
