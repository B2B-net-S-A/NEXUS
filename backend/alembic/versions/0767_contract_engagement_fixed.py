"""Model rozliczeń kontraktu „FIX / produkt” (``engagementmodel`` += ``fixed``).

Revision ID: 0767_contract_engagement_fixed
Revises: 0766_cpro_invoice_buyer_bell

Przegląd skrzynek z 23.11.2026 (projekty FIX: testy bezpieczeństwa, projekt
z limitem MD na fazę): klient odbiera produkt protokołem, a godziny
podwykonawcy są kosztem firmy, które akceptuje PM firmy. Decyzja Artura
z 24.11.2026: typ przy kontrakcie, nie reguła klienta, bo u jednego klienta
bywa i T&M, i FIX. Lustro w ``entrypoint.sh`` (``_ENUM_STATEMENTS``).
"""

from alembic import op

revision = "0767_contract_engagement_fixed"
down_revision = "0766_cpro_invoice_buyer_bell"
branch_labels = None
depends_on = None

VALUE = "fixed"
ADD_VALUE = "ALTER TYPE engagementmodel ADD VALUE IF NOT EXISTS 'fixed'"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(ADD_VALUE)


# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed tej
# rewizji jej nie zna — kontrakt z ``fixed`` dałby 500 przy odczycie rejestru.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM contracts WHERE engagement_model::text = '{VALUE}'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0767 odmawia: contracts ma kontrakty {VALUE}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
