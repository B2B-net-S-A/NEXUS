"""Heal contracts whose status outlived their end date.

Revision ID: 0155_contract_status_coherence_backfill
Revises: 0154_contract_candidate_rate_effective_to
Create Date: 2026-07-07

Kontrakt bezterminowy (``end_date IS NULL``) lub z datą zakończenia w przyszłości
(``end_date > CURRENT_DATE``) nie może mieć statusu „Zakończony" — status
„Zakończony" należy się dopiero po upływie daty zakończenia (patrz reguła w
``_status_after_end_date_change`` + codzienny cron ``_promote_statuses``). Dryf
danych (np. edycja kontraktu na „bezterminowo" gdy był już oznaczony jako
zakończony) zostawiał takie rekordy z fałszywym „Zakończony" w prawym górnym rogu
karty kontraktu — ta migracja jednorazowo je leczy.

Downgrade tylko do ``active``; codzienny cron ponownie awansuje na „Kończący się"
w oknie 30 dni. Migracja jest wyłącznie danymi (żadnych zmian schematu), więc
współgra z entrypoint ``alembic upgrade heads`` oraz DEBUG ``create_all``.
"""

from alembic import op

revision = "0155_contract_status_coherence_backfill"
down_revision = "0154_contract_candidate_rate_effective_to"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # "Zakończony" na kontrakcie bez daty końca lub z datą w przyszłości → active.
    # Jawny cast ``::contractstatus`` zgodny z precedensem (migracja 0046).
    op.execute(
        """
        UPDATE contracts
        SET status = 'active'::contractstatus
        WHERE status = 'ended'::contractstatus
          AND (end_date IS NULL OR end_date > CURRENT_DATE)
        """
    )
    # "Kończący się" na kontrakcie bezterminowym też jest niespójny → active.
    op.execute(
        """
        UPDATE contracts
        SET status = 'active'::contractstatus
        WHERE status = 'ending'::contractstatus
          AND end_date IS NULL
        """
    )


def downgrade() -> None:
    # Jednorazowe uzdrowienie danych — nieodwracalne (nie znamy pierwotnego statusu).
    pass
