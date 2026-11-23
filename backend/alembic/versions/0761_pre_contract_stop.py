"""Stop do podpisu umowy przedwstępnej: ustawienie rekrutacji i wybór przy osobie.

Revision ID: 0761_pre_contract_stop
Revises: 0760_novelty_lessons

Decyzje Artura z 23.11.2026: Delivery Lead albo Head of Recruitment ustawia,
że osoba nie przejdzie na wybrany etap, dopóki obie strony nie podpiszą umowy
przedwstępnej — dla całej rekrutacji (``jobs.pre_contract_rule``) albo przy
jednej osobie (``pre_contract_requests.blocks_move``). DDL
w ``app/services/pre_contract_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.pre_contract_schema import STOP_DDL, STOP_DOWNGRADE_DDL

revision = "0761_pre_contract_stop"
down_revision = "0760_novelty_lessons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in STOP_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in STOP_DOWNGRADE_DDL:
        op.execute(statement)
