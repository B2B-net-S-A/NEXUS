"""Reguły CV per klient jako pełna recepta Delivery Leada.

Do 09.2026 reguła mówiła generatorowi, JAK ma wyglądać wynik (nazwa pliku,
język, instrukcje), ale rekruter nadal miał w formularzu wybory, które mogły
to zepsuć. Ta rewizja daje regule trzy nowe warstwy:

* **blokady** — tryb obróbki treści ustawiany dokładnie (``content_mode`` +
  ``content_mode_locked``), wymagane wejścia (notatki o minimalnej długości,
  numer projektu, stanowisko, profil Championa), automatyczna druga wersja
  językowa;
* **polityka prezentacji egzekwowana deterministycznie** — sekcje do
  pominięcia, limity stanowisk / punktów / długości punktu, format dat,
  słownik klienta; model dostaje to samo jako instrukcje, a renderer
  domyka po fakcie (model bywa nieposłuszny, kod nie);
* **ślad** — ``version`` reguły bumpowany przy każdym zapisie,
  ``client_cv_rule_events`` (kto, kiedy, co zmienił), stempel
  ``cv_generated_documents.client_rule_version`` (z którą wersją reguły
  powstało konkretne CV — bez tego reklamacja klienta jest nie do
  prześledzenia) oraz ``client_cv_rule_previews`` (CV próbne z regułą i bez,
  liczone w tle, bo dwie generacje trwają dłużej niż limit proxy).

Klucz ``aifeaturekey.cv_rule_lint`` — lint instrukcji tanim modelem przy
zapisie reguły (osobny kubełek kwoty, bo to inny strumień wydatku niż
generacja). Kalka 0240: ADD VALUE w autocommit, seed przez WHERE NOT EXISTS.

Revision ID: 0267_client_cv_rules_dl_recipe
Revises: 0266_cv_rules_generator_instructions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0267_client_cv_rules_dl_recipe"
down_revision = "0266_cv_rules_generator_instructions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Reguła: blokady + polityka prezentacji + wersja ─────────────────
    op.add_column(
        "client_cv_rules", sa.Column("content_mode", sa.String(16), nullable=True)
    )
    op.add_column(
        "client_cv_rules",
        sa.Column(
            "content_mode_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "client_cv_rules",
        sa.Column("require_screening_notes_min_chars", sa.Integer(), nullable=True),
    )
    for flag in (
        "require_project_ref",
        "require_position",
        "require_champion",
        "auto_second_language",
    ):
        op.add_column(
            "client_cv_rules",
            sa.Column(
                flag, sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
        )
    op.add_column(
        "client_cv_rules",
        sa.Column("omit_sections", postgresql.JSONB(), nullable=True),
    )
    for limit in ("max_roles", "max_bullets_per_role", "max_bullet_chars", "why_points_max"):
        op.add_column(
            "client_cv_rules", sa.Column(limit, sa.Integer(), nullable=True)
        )
    op.add_column(
        "client_cv_rules", sa.Column("date_format", sa.String(16), nullable=True)
    )
    op.add_column(
        "client_cv_rules", sa.Column("glossary", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "client_cv_rules",
        sa.Column("generator_instructions_en", sa.Text(), nullable=True),
    )
    op.add_column(
        "client_cv_rules",
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
    )
    op.create_check_constraint(
        "ck_client_cv_rules_content_mode",
        "client_cv_rules",
        "content_mode IS NULL OR content_mode IN ('basic', 'polished', 'tailored')",
    )
    op.create_check_constraint(
        "ck_client_cv_rules_date_format",
        "client_cv_rules",
        "date_format IS NULL OR date_format IN ('MM.YYYY', 'MM/YYYY', 'YYYY-MM', 'YYYY')",
    )
    op.create_check_constraint(
        "ck_client_cv_rules_limits_positive",
        "client_cv_rules",
        "(max_roles IS NULL OR max_roles > 0) AND "
        "(max_bullets_per_role IS NULL OR max_bullets_per_role > 0) AND "
        "(max_bullet_chars IS NULL OR max_bullet_chars >= 40) AND "
        "(why_points_max IS NULL OR why_points_max > 0) AND "
        "(require_screening_notes_min_chars IS NULL "
        "OR require_screening_notes_min_chars >= 0)",
    )

    # ── Historia zmian reguły ───────────────────────────────────────────
    op.create_table(
        "client_cv_rule_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_name", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_client_cv_rule_events_client_created",
        "client_cv_rule_events",
        ["client_id", "created_at"],
    )

    # ── CV próbne (z regułą i bez), liczone w tle ────────────────────────
    op.create_table(
        "client_cv_rule_previews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage_id", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(2), nullable=False, server_default="pl"),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="processing"
        ),
        sa.Column("with_rule", postgresql.JSONB(), nullable=True),
        sa.Column("without_rule", postgresql.JSONB(), nullable=True),
        sa.Column("prompt_block", sa.Text(), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_client_cv_rule_previews_client_created",
        "client_cv_rule_previews",
        ["client_id", "created_at"],
    )

    # ── Stempel wersji reguły na wygenerowanym CV ───────────────────────
    op.add_column(
        "cv_generated_documents",
        sa.Column("client_rule_version", sa.Integer(), nullable=True),
    )

    # ── Klucz AI: lint instrukcji przy zapisie reguły ───────────────────
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_rule_lint'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'cv_rule_lint', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'cv_rule_lint')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM ai_features WHERE feature = 'cv_rule_lint'")
    op.drop_column("cv_generated_documents", "client_rule_version")
    op.drop_index(
        "ix_client_cv_rule_previews_client_created", "client_cv_rule_previews"
    )
    op.drop_table("client_cv_rule_previews")
    op.drop_index("ix_client_cv_rule_events_client_created", "client_cv_rule_events")
    op.drop_table("client_cv_rule_events")
    op.drop_constraint("ck_client_cv_rules_limits_positive", "client_cv_rules")
    op.drop_constraint("ck_client_cv_rules_date_format", "client_cv_rules")
    op.drop_constraint("ck_client_cv_rules_content_mode", "client_cv_rules")
    for col in (
        "version",
        "generator_instructions_en",
        "glossary",
        "date_format",
        "why_points_max",
        "max_bullet_chars",
        "max_bullets_per_role",
        "max_roles",
        "omit_sections",
        "auto_second_language",
        "require_champion",
        "require_position",
        "require_project_ref",
        "require_screening_notes_min_chars",
        "content_mode_locked",
        "content_mode",
    ):
        op.drop_column("client_cv_rules", col)
