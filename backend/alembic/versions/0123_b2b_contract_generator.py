"""Generator Umów B2B — katalog ról + dane per-umowa + język szablonu

Revision ID: 0123_b2b_contract_generator
Revises: 0122_candidate_stage_client_rate
Create Date: 2026-06-05 00:00:00.000000

Context:
    Nowy moduł „Generator Umów B2B" — wypełnia jednolitą umowę B2B (PL/EN)
    danymi kandydata (JDG) + rekrutacji + wybranej roli z gotowym zakresem
    usług. Reużywa istniejący system draftów (ContractTemplate/Tiptap/PDF/
    Autenti); ta migracja dokłada tylko warstwę danych.

What this migration does (schema only — dane seeduje idempotentny seeder
    przy starcie aplikacji, by nie nadpisywać edycji z UI):
      1. `b2b_contract_roles`  — katalog ról z dwujęzycznym zakresem (str[] w JSONB).
      2. `b2b_contract_details` — 1:1 z `contracts` (pola edytowalne generatora).
      3. `contract_templates.language` — VARCHAR(2) do rozróżnienia szablonu PL/EN.

Safety net:
    Wszystko idempotentne (`CREATE TABLE/INDEX IF NOT EXISTS`,
    `ADD COLUMN IF NOT EXISTS`).
"""

from alembic import op


revision = "0123_b2b_contract_generator"
down_revision = "0122_candidate_stage_client_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Katalog ról B2B (edytowalny w UI; zakres = lista bulletów w JSONB).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS b2b_contract_roles (
            id                SERIAL PRIMARY KEY,
            category_key      VARCHAR(32)  NOT NULL,
            category_label_pl VARCHAR(120) NOT NULL,
            category_label_en VARCHAR(120) NOT NULL,
            slug              VARCHAR(80)  NOT NULL UNIQUE,
            name_pl           VARCHAR(160) NOT NULL,
            name_en           VARCHAR(160) NOT NULL,
            area_label_pl     VARCHAR(255) NOT NULL,
            area_label_en     VARCHAR(255) NOT NULL,
            scope_pl          JSONB        NOT NULL DEFAULT '[]'::jsonb,
            scope_en          JSONB        NOT NULL DEFAULT '[]'::jsonb,
            display_order     INTEGER      NOT NULL DEFAULT 0,
            is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_b2b_contract_roles_category_key "
        "ON b2b_contract_roles (category_key)"
    )

    # 2. Dane generatora per-umowa (1:1 z contracts).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS b2b_contract_details (
            id                     SERIAL PRIMARY KEY,
            contract_id            INTEGER NOT NULL UNIQUE
                                   REFERENCES contracts (id) ON DELETE CASCADE,
            contract_number        VARCHAR(64),
            signing_date           DATE,
            project_city           VARCHAR(255),
            project_description    TEXT,
            correspondence_address TEXT,
            rate_in_words          VARCHAR(255),
            language               VARCHAR(2) NOT NULL DEFAULT 'pl',
            b2b_role_id            INTEGER
                                   REFERENCES b2b_contract_roles (id)
                                   ON DELETE SET NULL,
            role_scope_override    JSONB,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_b2b_contract_details_b2b_role_id "
        "ON b2b_contract_details (b2b_role_id)"
    )

    # 3. Język szablonu (rozróżnia wersję PL/EN dla generatora).
    op.execute(
        "ALTER TABLE contract_templates "
        "ADD COLUMN IF NOT EXISTS language VARCHAR(2) NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_templates_language "
        "ON contract_templates (language)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contract_templates_language")
    op.execute("ALTER TABLE contract_templates DROP COLUMN IF EXISTS language")
    op.execute("DROP TABLE IF EXISTS b2b_contract_details")
    op.execute("DROP TABLE IF EXISTS b2b_contract_roles")
