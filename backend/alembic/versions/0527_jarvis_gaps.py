"""Jarvis: „Czego Jarvis nie umie” — karta braku i zgłoszenia.

Revision ID: 0527_jarvis_gaps
Revises: 0526_job_ad_reminders

Decyzja Artura 27.10.2026: gdy Jarvis czegoś nie zrobi, mówi, czego brakuje
(rola tego nie widzi / jeszcze nie umie / NEXUS tego nie przechowuje), co
zrobić teraz, i daje przycisk „Zgłoś, że tego potrzebuję”. Tabela
``jarvis_gaps`` trzyma te karty — z niej admin widzi, czego ludzie chcą.

SQL ma jedno źródło (``app/services/jarvis/gap_schema.py``) — te same
instrukcje stoją dosłownie w ``entrypoint.sh``.
"""

from alembic import op

from app.services.jarvis import gap_schema as schema

revision = "0527_jarvis_gaps"
down_revision = "0526_job_ad_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
