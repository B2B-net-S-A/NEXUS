"""Decyzje „Wymagania do poprawy” — porządki wymagań otwartych rekrutacji (13.10.2026).

Revision ID: 0438_requirement_cleanup_decisions
Revises: 0437_candidate_source_created_at

Decyzja Artura 13.10.2026 (wariant A, D4): otwarte rekrutacje dostają
propozycję uporządkowania wymagań — zdania do „Rekruter sprawdza w rozmowie”,
technologia bez komentarza w nawiasie, krytyczne tylko ze słów do szukania.
Delivery Lead zatwierdza albo odrzuca ją z pulpitu. Propozycję liczy kod na
żywo (`app/services/requirement_cleanup.py`); tabela trzyma tylko decyzję
i odcisk profilu, którego dotyczyła.

DDL ma jedno źródło z entrypointem: `app/services/requirement_cleanup_schema.py`.
"""

from alembic import op

from app.services import requirement_cleanup_schema

revision = "0438_requirement_cleanup_decisions"
down_revision = "0437_candidate_source_created_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in requirement_cleanup_schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS requirement_cleanup_decisions")
