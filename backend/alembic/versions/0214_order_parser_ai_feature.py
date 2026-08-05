"""Order-PDF extraction: nowy AIFeatureKey ``order_parser`` + seed ai_features.

Revision ID: 0214_order_parser_ai_feature
Revises: 0213_proposal_snapshot_freshness
Create Date: 2026-08-05

Backing the "Zczytaj dane z dokumentu" akcji w przedłużeniu zamówienia
(``ExtendOrderDialog``). Endpoint ``POST /api/clients/{id}/orders/extract``
wywołuje Claude do odczytu pól z PDF zamówienia i jest bramkowany przez
``ai_quota.check_and_increment(AIFeatureKey.order_parser)`` (master toggle →
feature toggle → miesięczny limit), tak samo jak ``cv_parser``.

Enum ``aifeaturekey`` istnieje od 0085 — tu tylko dodajemy wartość i seedujemy
domyślny wiersz w ``ai_features`` (enabled, unlimited). ADD VALUE musi lecieć w
autocommit (nie w bloku transakcji); seed INSERT po committcie wartości.
Zdublowane w safety-net ``entrypoint.sh`` (prod alembic bywa orphaned).
"""

from alembic import op

revision = "0214_order_parser_ai_feature"
down_revision = "0213_proposal_snapshot_freshness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rozszerz enum poza transakcją (ALTER TYPE ADD VALUE tego wymaga).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'order_parser'")

    # 2. Seed wiersza konfiguracyjnego (enabled, unlimited). Idempotentny —
    #    WHERE NOT EXISTS. Wartość enuma jest już zacommitowana przez blok wyżej,
    #    więc INSERT może jej użyć w tej transakcji.
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'order_parser', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'order_parser')"
    )


def downgrade() -> None:
    # Usuwamy tylko seed; PostgreSQL nie umie kasować wartości enuma in-place,
    # więc 'order_parser' zostaje w typie (bezpieczne — nikt jej nie użyje).
    op.execute("DELETE FROM ai_features WHERE feature = 'order_parser'")
