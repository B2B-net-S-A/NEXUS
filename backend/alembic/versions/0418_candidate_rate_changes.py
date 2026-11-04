"""Zmiana stawki kandydata w trakcie procesu: sprawa, ślad, powiadomienia.

Revision ID: 0418_candidate_rate_changes
Revises: 0417_b2b_signature_request

Kandydat po rozmowie u klienta chce wyższej stawki. Do tej migracji korekta
stawki nadpisywała wiersz etapu bez śladu, nikt nie dostawał powiadomienia,
a informacja żyła w wolnym tekście debriefu. Tabela ``candidate_rate_changes``
trzyma każdą zmianę: poprzednią i zgłoszoną stawkę, źródło, powód, negocjację
i decyzję Delivery Leada (decyzje Artura 04.10.2026). Dwa nowe typy
powiadomień: informacja i zadanie dla DL.

SQL ma jedno źródło (``app/services/candidate_rate_change_schema.py``) — ten
sam moduł importuje ``entrypoint.sh``.
"""

from alembic import op

from app.services import candidate_rate_change_schema as schema

revision = "0418_candidate_rate_changes"
down_revision = "0417_b2b_signature_request"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in schema.NOTIFICATION_ENUM_DDL:
            op.execute(stmt)
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Zmiany stawek i decyzje DL żyją tylko w tej tabeli.
    bind = op.get_bind()
    rows = bind.exec_driver_sql("SELECT count(*) FROM candidate_rate_changes").scalar()
    if rows:
        raise RuntimeError(
            f"candidate_rate_changes ma {rows} wierszy — downgrade skasowałby "
            "historię zmian stawek bez śladu."
        )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_rate_from_rate_changes ON candidate_rate_changes"
    )
    op.execute("DROP FUNCTION IF EXISTS trg_rate_from_rate_changes()")
    op.execute("DROP TABLE IF EXISTS candidate_rate_changes")
    # Wartości enuma zostają — Postgres nie ma `ALTER TYPE … DROP VALUE`.
