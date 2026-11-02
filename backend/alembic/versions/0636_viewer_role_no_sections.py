"""Wycofywany Viewer (``user``) nie ma żadnej sekcji.

Revision ID: 0636_viewer_role_no_sections
Revises: 0635_cpro_mail_events

Audyt najmniejszych dostępów 02.11.2026. Lustro w ``entrypoint.sh`` przez
``hr_schema_bundle``; biegnie raz, potem decyzja admina z panelu wygrywa.
Downgrade przywraca odczyt tylko razem ze znacznikiem, żeby ponowny upgrade
znów zadziałał.
"""

from alembic import op

from app.services import viewer_role_schema as schema

revision = "0636_viewer_role_no_sections"
down_revision = "0635_cpro_mail_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(schema.ZERO_SECTIONS)


def downgrade() -> None:
    op.execute(
        "UPDATE rbac_role_section_permissions SET access = 'read', updated_at = now() "
        "WHERE role = 'user' AND section IN ('sourcing', 'pipeline', 'insights')"
    )
    op.execute(f"DELETE FROM app_settings WHERE key = '{schema.MARKER}'")
