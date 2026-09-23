"""Anulowanie zamówienia MD/kosztowego z możliwością przywrócenia.

Revision ID: 0358_order_group_cancel
Revises: 0357_application_confirmation

* ``client_order_groups.status`` dostaje wartość ``cancelled``. Do tej pory
  jedynym wyjściem z omyłkowo założonego zamówienia było usunięcie, które
  kasuje też dziennik zdarzeń — anulowanie zostawia wpis w rejestrze.
* ``status_before_cancel`` pamięta stan sprzed anulowania; ``cancelled_at``,
  ``cancelled_by_user_id`` i ``cancellation_reason`` — kto, kiedy i dlaczego.
  Statusy LINII sprzed anulowania niesie payload zdarzenia ``order_cancelled``.
* ``ck_client_order_group_events_type`` dostaje ``order_cancelled`` oraz
  ``order_restored``.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0358_order_group_cancel"
down_revision = "0357_application_confirmation"
branch_labels = None
depends_on = None


_EVENT_TYPES_OLD = (
    "'utworzenie', 'dodanie_konsultanta', 'import_md', "
    "'zamiana_kontraktora', 'edycja_reczna', 'zakonczenie', "
    "'przywrocenie', 'wyczerpanie', 'przedluzenie', 'import_faktur', "
    "'transfer_md', 'zakonczenie_konsultanta', "
    "'decyzja_md_wymagana', 'usuniecie_puli_md', "
    "'przeniesienie_puli_md', 'przywrocenie_konsultanta'"
)
_EVENT_TYPES_NEW = _EVENT_TYPES_OLD + ", 'order_cancelled', 'order_restored'"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE client_order_groups "
        "ADD COLUMN IF NOT EXISTS status_before_cancel VARCHAR(16) NULL"
    )
    op.execute(
        "ALTER TABLE client_order_groups "
        "ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "ALTER TABLE client_order_groups "
        "ADD COLUMN IF NOT EXISTS cancelled_by_user_id INTEGER NULL "
        "REFERENCES users (id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE client_order_groups "
        "ADD COLUMN IF NOT EXISTS cancellation_reason TEXT NULL"
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE client_order_groups
                DROP CONSTRAINT IF EXISTS ck_client_order_groups_status;
            ALTER TABLE client_order_groups
                ADD CONSTRAINT ck_client_order_groups_status
                CHECK (status IN ('draft', 'active', 'scheduled', 'completed',
                                  'exhausted', 'cancelled'));
            ALTER TABLE client_order_groups
                DROP CONSTRAINT IF EXISTS ck_client_order_groups_cancel_coherence;
            ALTER TABLE client_order_groups
                ADD CONSTRAINT ck_client_order_groups_cancel_coherence
                CHECK (
                    (status = 'cancelled' AND status_before_cancel IN
                        ('draft', 'active', 'scheduled', 'completed', 'exhausted'))
                    OR (status <> 'cancelled' AND status_before_cancel IS NULL)
                );
            ALTER TABLE client_order_group_events
                DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type;
            ALTER TABLE client_order_group_events
                ADD CONSTRAINT ck_client_order_group_events_type
                CHECK (event_type IN ("""
        + _EVENT_TYPES_NEW
        + """));
        END $$
        """
    )


def downgrade() -> None:
    # Anulowane zamówienie wraca do stanu sprzed anulowania. Linii nie
    # odtwarzamy — ich statusy żyją w payloadzie zdarzenia, które i tak
    # przemianowujemy na edycję ręczną, żeby zmieścić się w węższym CHECK-u.
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE client_order_groups
                DROP CONSTRAINT IF EXISTS ck_client_order_groups_cancel_coherence;
            UPDATE client_order_groups
               SET status = status_before_cancel
             WHERE status = 'cancelled' AND status_before_cancel IS NOT NULL;
            ALTER TABLE client_order_groups
                DROP CONSTRAINT IF EXISTS ck_client_order_groups_status;
            ALTER TABLE client_order_groups
                ADD CONSTRAINT ck_client_order_groups_status
                CHECK (status IN ('draft', 'active', 'scheduled', 'completed',
                                  'exhausted'));
            UPDATE client_order_group_events
               SET event_type = 'edycja_reczna'
             WHERE event_type IN ('order_cancelled', 'order_restored');
            ALTER TABLE client_order_group_events
                DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type;
            ALTER TABLE client_order_group_events
                ADD CONSTRAINT ck_client_order_group_events_type
                CHECK (event_type IN ("""
        + _EVENT_TYPES_OLD
        + """));
        END $$
        """
    )
    op.execute(
        "ALTER TABLE client_order_groups DROP COLUMN IF EXISTS cancellation_reason"
    )
    op.execute(
        "ALTER TABLE client_order_groups DROP COLUMN IF EXISTS cancelled_by_user_id"
    )
    op.execute("ALTER TABLE client_order_groups DROP COLUMN IF EXISTS cancelled_at")
    op.execute(
        "ALTER TABLE client_order_groups DROP COLUMN IF EXISTS status_before_cancel"
    )
