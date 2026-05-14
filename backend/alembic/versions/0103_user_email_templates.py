"""User email templates library — Phase 4.5 of the M365 plan.

Revision ID: 0103_user_email_templates
Revises: 0102_m365_connection_hardening
Create Date: 2026-05-14 14:00:00.000000

Phase 4.5 of the M365 repair plan (.claude/plans/elegant-percolating-thimble.md).

Why a new `user_email_templates` table instead of reusing `email_templates`:
  The existing `email_templates` table (migration 0001) is hard-wired into the
  rejection-email feature — `rejection_emails.template_id` FK in 0045, the
  `category` enum (`application_received` / `screening_invite` / `rejection`
  / ...), and the `is_default` flag for one-default-per-category UX. Reshaping
  it for per-user, Jinja2, share-with-team templates would break that feature.
  Cleaner separation: `email_templates` stays the rejection library, and
  `user_email_templates` is the new per-user M365 outreach library.

Schema:
- `user_id` (FK users, NOT NULL, CASCADE on user delete) — owner.
- `name` (VARCHAR(120)) — display name.
- `subject` (VARCHAR(998)) — RFC 5322 max line length; nullable so the user
  can keep "body-only" snippets and write the subject inline.
- `body_html` (TEXT, NOT NULL) — Jinja2 source; rendered with a sandboxed env
  at /api/user-email-templates/{id}/render.
- `variables` (JSONB, default '[]') — list of Jinja vars referenced in the
  body (auto-detected on save). Powers the variable chips in the editor.
- `is_shared` (BOOLEAN, default false) — when true, all users in the org see
  this template alongside their own. Owner remains the only editor/deleter.
- created_at / updated_at — standard.

Indexes:
- `(user_id)` — list-by-owner.
- partial `(is_shared) WHERE is_shared = true` — shared-templates fan-out
  query.

Idempotent — all `IF NOT EXISTS` guards.
"""

from alembic import op


revision = "0103_user_email_templates"
down_revision = "0102_m365_connection_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_email_templates (
            id          BIGSERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name        VARCHAR(120) NOT NULL,
            subject     VARCHAR(998),
            body_html   TEXT NOT NULL,
            variables   JSONB NOT NULL DEFAULT '[]'::jsonb,
            is_shared   BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_email_templates_user_id "
        "ON user_email_templates (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_email_templates_is_shared "
        "ON user_email_templates (is_shared) WHERE is_shared = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_email_templates CASCADE")
