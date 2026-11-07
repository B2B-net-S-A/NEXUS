"""client_cv_rules.cv_title_with_reference — numer zapytania w nagłówku CV (07.11.2026).

Revision ID: 0661_cv_title_with_reference
Revises: 0660_skill_relations

Nagłówek CV to nazwa roli bez numeru zapytania (D2 z 13.10, D4 z 26.10).
Pomiar 07.11: rekruterzy dopisywali numer ręcznie („AML Analyst (43114) –
Imię Nazwisko”). Decyzja Artura: reguła CV klienta może włączyć numer
zapytania w nagłówku; nazwa pliku zostaje bez zmian. Lustro w
``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0661_cv_title_with_reference"
down_revision = "0660_skill_relations"
branch_labels = None
depends_on = None

ADD_COLUMN = (
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS cv_title_with_reference "
    "BOOLEAN NOT NULL DEFAULT FALSE"
)


def upgrade() -> None:
    op.execute(ADD_COLUMN)


def downgrade() -> None:
    op.execute("ALTER TABLE client_cv_rules DROP COLUMN IF EXISTS cv_title_with_reference")
