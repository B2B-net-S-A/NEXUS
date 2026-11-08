"""Mapa wiedzy IT: powiązania haseł słownika umiejętności.

Revision ID: 0660_skill_relations
Revises: 0659_skill_alias_in_text

Decyzja Artura z 07.11.2026: „wynika z” i „część” spełniają wymaganie wszędzie
(wyszukiwanie, bramka krytycznych, QC, przegląd DL, strażnik generatora),
„zamiennik” i „typowe” dają pytanie do rozmowy. Powiązania proponują dane,
słowniczek „po ludzku” i model; działają po zatwierdzeniu przez HoR+. DDL
w ``app/services/skill_relations_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.skill_relations_schema import DOWNGRADE_DDL, TABLE_DDL

revision = "0660_skill_relations"
down_revision = "0659_skill_alias_in_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
