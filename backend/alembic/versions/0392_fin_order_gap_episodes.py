"""Braki: kilka na zamówienie (po dacie końca) + epizod przywrócenia (runda 10).

Revision ID: 0392_fin_order_gap_episodes
Revises: 0391_auth_candidate_email_lower_index

R10-N4-1: UNIQUE(order_id) blokował drugi brak tego samego zamówienia.
Zamówienie przedłużone po fakcie uzupełnia swój brak (``filled_late``), a gdy
nowa data końca też minie bez następcy, detektor nie mógł założyć nowego
wiersza — osoba zostawała bez Braku i bez karty DL na zawsze. Unikalność
przechodzi na parę (zamówienie, data końca). Istniejące dane spełniają ją
z definicji (dotąd był co najwyżej jeden wiersz na zamówienie).

R10-N4-3: ``episode`` liczy przywrócenia braku na ``open``; wchodzi do klucza
odhaczenia w Finansach, żeby przywrócony brak nie był od razu „Zrobione".

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``tests/test_order_gap_episodes_mirror.py``. Indeks powstaje PRZED zdjęciem
starego więzu, więc w żadnej chwili tabela nie jest bez unikalności.
"""

from alembic import op

revision = "0392_fin_order_gap_episodes"
down_revision = "0391_auth_candidate_email_lower_index"
branch_labels = None
depends_on = None

ADD_EPISODE = (
    "ALTER TABLE order_gaps ADD COLUMN IF NOT EXISTS episode INTEGER NOT NULL DEFAULT 0"
)
CREATE_ORDER_ENDED_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_order_gaps_order_ended "
    "ON order_gaps (order_id, ended_on)"
)
DROP_ORDER_UNIQUE = (
    "ALTER TABLE order_gaps DROP CONSTRAINT IF EXISTS uq_order_gaps_order_id"
)

DDL_STATEMENTS = [ADD_EPISODE, CREATE_ORDER_ENDED_INDEX, DROP_ORDER_UNIQUE]


def upgrade() -> None:
    for statement in DDL_STATEMENTS:
        op.execute(statement)


# Drugi brak tego samego zamówienia to prawdziwy wpis historii — downgrade nie
# może go skasować po cichu, żeby wrócić do UNIQUE(order_id).
REFUSE_WITH_DUPLICATES = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM order_gaps GROUP BY order_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Downgrade 0392 odmawia: zamówienie ma kilka braków (po jednym na datę końca). Zostaw tę rewizję albo rozstrzygnij wpisy ręcznie.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_DUPLICATES)
    op.execute(
        "ALTER TABLE order_gaps ADD CONSTRAINT uq_order_gaps_order_id UNIQUE (order_id)"
    )
    op.execute("DROP INDEX IF EXISTS ux_order_gaps_order_ended")
    op.execute("ALTER TABLE order_gaps DROP COLUMN IF EXISTS episode")
