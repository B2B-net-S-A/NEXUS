"""Wysyłka maila z NEXUSA: stan rezerwacji (INT-04/05/07).

Revision ID: 0342_email_send_state
Revises: 0341_job_champion_similar

``emails.send_state`` — stan wiersza zarezerwowanego PRZED wywołaniem
Microsoft Graph:

* ``pending`` — wysyłka w toku (wiersz założony, Graph jeszcze nie odpowiedział);
* ``sent`` — Graph przyjął wysyłkę;
* ``uncertain`` — szkic powstał, ale odpowiedź na wysyłkę zginęła; nie wiadomo,
  czy mail wyszedł, więc ponowienie z tym samym kluczem NIE wysyła drugi raz.

NULL = wiersz sprzed tej zmiany albo pobrany synchronizacją (traktowany jak
wysłany/odebrany). Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0342_email_send_state"
down_revision = "0341_job_champion_similar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE emails ADD COLUMN IF NOT EXISTS send_state VARCHAR(16) NULL "
        "CONSTRAINT ck_emails_send_state "
        "CHECK (send_state IN ('pending', 'sent', 'uncertain'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE emails DROP COLUMN IF EXISTS send_state")
