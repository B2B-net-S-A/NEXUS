"""Lekcje nowości: postęp osoby w lekcji i stan porannej porcji.

Revision ID: 0757_novelty_lessons
Revises: 0756_client_form_upload_scale

Decyzje Artura z 23.11.2026: nowość przechodzi się jako lekcja na Poligonie
(pokaz → samodzielnie → pytanie), najwyżej 5 lekcji dziennie, porcję można
odłożyć raz dziennie do 15:00, a admin może ją pominąć. DDL
w ``app/services/novelty_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.novelty_schema import LESSON_DDL, LESSON_DOWNGRADE_DDL

revision = "0757_novelty_lessons"
down_revision = "0756_client_form_upload_scale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in LESSON_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in LESSON_DOWNGRADE_DDL:
        op.execute(statement)
