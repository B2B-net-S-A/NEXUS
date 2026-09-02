"""Reguły CV per klient: instrukcje dla generatora AI.

Dokłada ``client_cv_rules.generator_instructions`` — wolny tekst od Delivery
Leada, który generator CV STOSUJE do treści dokumentu (co pominąć, co
wyeksponować, jak długo, jakim stylem). Do 09.2026 jedynym wolnym polem była
``notes`` — notatka dla człowieka, celowo nietrafiająca do modelu.

Instrukcje idą do promptu w osobnym bloku ``<client_presentation_rules>``
w wiadomości użytkownika (nie w systemowym prompcie: ten jest cache'owany
i musi zostać statyczny), a prompt systemowy ogranicza ich moc do PREZENTACJI:
polecenie, które wymagałoby dopisania technologii, obowiązku, lat czy
certyfikatu, model ignoruje i zgłasza w ``warnings``.

Revision ID: 0266_cv_rules_generator_instructions
Revises: 0265_dl_alert_order_mail_review
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0266_cv_rules_generator_instructions"
down_revision = "0265_dl_alert_order_mail_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_cv_rules",
        sa.Column("generator_instructions", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_cv_rules", "generator_instructions")
