"""Karty bez śladu: dzwonek „wróciły do Nowych” i ostrzeżenie dzień wcześniej.

Revision ID: 0793_screening_return_bells
Revises: 0792_cv_page1_highlight_ai

Rekruter zgłosił 26.11.2026, że osoby znikają ze „Screeningu”. Dzwonek
o powrocie szedł typem ``candidate_claim_taken`` po każdym przebiegu (najwyżej
200 kart), a dzienny dedup przepuszczał tylko pierwszy: 24.11 na produkcji
593 z 1 632 kart nie trafiło do żadnego dzwonka. Dwa własne typy, lustro
w ``entrypoint.sh``.
"""

from alembic import op

revision = "0793_screening_return_bells"
down_revision = "0792_cv_page1_highlight_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in ("screening_cards_returned", "screening_cards_return_soon"):
            op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Wartości enuma zostają — Postgres nie ma `ALTER TYPE … DROP VALUE`.
    pass
