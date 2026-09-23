"""Zakończenie współpracy: rozwiązanie umowy B2B i synchronizacja z Generatorem.

Revision ID: 0355_contract_agreement_termination
Revises: 0354_order_change_checks

* ``contracts.agreement_termination_*`` + ``agreement_last_day`` — rozwiązanie
  umowy B2B zapisane oknem „Zakończ współpracę” (tryb, strona, data złożenia
  wypowiedzenia albo zawarcia porozumienia, ostatni dzień umowy). Komplet albo
  nic — pilnuje ``ck_contracts_agreement_termination_coherence``.
* ``contracts.notice_period_months`` — okres wypowiedzenia z umowy; zasila
  podpowiedź „Ostatniego dnia umowy” przy wypowiedzeniu.
* ``b2b_generated_contracts.termination_*``, ``project_end_date`` — kolumny
  „Tryb” i „Data zakończenia zamówienia” w „Zakończonych umowach”;
  ``termination_restore`` — stan umowy sprzed zmiany wykonanej przez
  zakończenie kontraktu („Cofnij zakończenie” go odtwarza);
  ``previous_generated_contract_id`` — nowa umowa po powrocie po przerwie.
* ``b2b_generated_contract_status_events.details`` — dane rozwiązania
  w historii umowy.
* ``contractdocumenttype`` + ``termination_notice`` / ``termination_agreement``
  — załącznik z okna ląduje w „Dokumentach” kontraktu z właściwym typem.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0355_contract_agreement_termination"
down_revision = "0354_order_change_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE w autocommicie — nowej etykiety nie da się użyć w transakcji,
    # w której ją dodano.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE contractdocumenttype "
            "ADD VALUE IF NOT EXISTS 'termination_notice'"
        )
        op.execute(
            "ALTER TYPE contractdocumenttype "
            "ADD VALUE IF NOT EXISTS 'termination_agreement'"
        )

    for column, sql_type in (
        ("agreement_termination_mode", "VARCHAR(20)"),
        ("agreement_termination_party", "VARCHAR(20)"),
        ("agreement_termination_signed_on", "DATE"),
        ("agreement_last_day", "DATE"),
        ("notice_period_months", "INTEGER"),
    ):
        op.execute(
            f"ALTER TABLE contracts ADD COLUMN IF NOT EXISTS {column} {sql_type}"
        )
    op.execute(
        """
        ALTER TABLE contracts
            ADD CONSTRAINT ck_contracts_agreement_termination_coherence
            CHECK (
                (
                    agreement_termination_mode IS NULL
                    AND agreement_termination_party IS NULL
                    AND agreement_termination_signed_on IS NULL
                    AND agreement_last_day IS NULL
                ) OR (
                    agreement_termination_mode IN ('notice', 'mutual_agreement')
                    AND agreement_termination_party IN ('consultant', 'company')
                    AND agreement_termination_signed_on IS NOT NULL
                    AND agreement_last_day IS NOT NULL
                )
            )
        """
    )
    op.execute(
        """
        ALTER TABLE contracts
            ADD CONSTRAINT ck_contracts_notice_period_months
            CHECK (notice_period_months IS NULL OR notice_period_months BETWEEN 1 AND 24)
        """
    )

    for column, sql_type in (
        ("termination_mode", "VARCHAR(20)"),
        ("termination_party", "VARCHAR(20)"),
        ("termination_signed_on", "DATE"),
        ("project_end_date", "DATE"),
        ("termination_restore", "JSONB"),
        (
            "previous_generated_contract_id",
            "INTEGER REFERENCES b2b_generated_contracts(id) ON DELETE SET NULL",
        ),
    ):
        op.execute(
            f"ALTER TABLE b2b_generated_contracts "
            f"ADD COLUMN IF NOT EXISTS {column} {sql_type}"
        )
    op.execute(
        """
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_termination_mode
            CHECK (termination_mode IS NULL OR termination_mode IN ('notice', 'mutual_agreement'))
        """
    )
    op.execute(
        """
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_termination_party
            CHECK (termination_party IS NULL OR termination_party IN ('consultant', 'company'))
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_previous "
        "ON b2b_generated_contracts (previous_generated_contract_id)"
    )
    op.execute(
        "ALTER TABLE b2b_generated_contract_status_events "
        "ADD COLUMN IF NOT EXISTS details JSONB"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE b2b_generated_contract_status_events DROP COLUMN IF EXISTS details"
    )
    op.execute("DROP INDEX IF EXISTS ix_b2b_generated_contracts_previous")
    op.execute(
        "ALTER TABLE b2b_generated_contracts "
        "DROP CONSTRAINT IF EXISTS ck_b2b_generated_contracts_termination_party"
    )
    op.execute(
        "ALTER TABLE b2b_generated_contracts "
        "DROP CONSTRAINT IF EXISTS ck_b2b_generated_contracts_termination_mode"
    )
    for column in (
        "previous_generated_contract_id",
        "termination_restore",
        "project_end_date",
        "termination_signed_on",
        "termination_party",
        "termination_mode",
    ):
        op.execute(
            f"ALTER TABLE b2b_generated_contracts DROP COLUMN IF EXISTS {column}"
        )
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT IF EXISTS ck_contracts_notice_period_months"
    )
    op.execute(
        "ALTER TABLE contracts "
        "DROP CONSTRAINT IF EXISTS ck_contracts_agreement_termination_coherence"
    )
    for column in (
        "notice_period_months",
        "agreement_last_day",
        "agreement_termination_signed_on",
        "agreement_termination_party",
        "agreement_termination_mode",
    ):
        op.execute(f"ALTER TABLE contracts DROP COLUMN IF EXISTS {column}")
    # Etykiet enuma Postgres nie usuwa (brak DROP VALUE) — zostają nieużywane.
