"""Prepy: Przygotowanie rekrutera jako trzeci prep (F3, decyzje Artura z 24.11.2026).

Revision ID: 0772_prep_meeting_preparation
Revises: 0771_cv_preview_reads

``prep_meetings.prep_no`` dostaje wartość 0 — Przygotowanie, które rekruter
prowadzi z kandydatem przed Prepem 1 z Delivery Leadem (fundamenty prepa
i specyfika klienta). Prep 1 i Prep 2 zachowują numery, więc istniejące
wiersze, oceny i ustawienia ocen nie zmieniają znaczenia.

Lustro w ``entrypoint.sh`` to blok w ``_CONSTRAINT_STATEMENTS``: ``CREATE
TABLE`` z 0370 zostaje 1:1 (pilnuje ``test_prep_meetings_schema.py``),
a poszerzenie biegnie po nim — świeża baza też kończy z (0, 1, 2).
Pilnuje ``test_prep_preparation_schema.py``.
"""

from alembic import op

revision = "0772_prep_meeting_preparation"
down_revision = "0771_cv_preview_reads"
branch_labels = None
depends_on = None

UPGRADE_SQL = """DO $$ BEGIN
        ALTER TABLE prep_meetings
            DROP CONSTRAINT IF EXISTS ck_prep_meetings_prep_no;
        ALTER TABLE prep_meetings
            ADD CONSTRAINT ck_prep_meetings_prep_no
            CHECK (prep_no IN (0, 1, 2));
    END $$"""

# Zwężenie wróci tylko na bazie bez Przygotowań — inaczej więz by nie wszedł.
DOWNGRADE_SQL = """DO $$ BEGIN
        ALTER TABLE prep_meetings
            DROP CONSTRAINT IF EXISTS ck_prep_meetings_prep_no;
        ALTER TABLE prep_meetings
            ADD CONSTRAINT ck_prep_meetings_prep_no
            CHECK (prep_no IN (1, 2));
    END $$"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
