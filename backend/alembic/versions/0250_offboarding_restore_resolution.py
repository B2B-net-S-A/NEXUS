"""Third Delivery Lead decision after an MD offboarding: restore the line.

Revision ID: 0250_offboarding_restore_resolution
Revises: 0249_order_rate_snapshots_offboarding

``remove`` forfeits the remaining pool and ``transfer`` hands it to somebody
else.  Both assume the engagement really ended.  The reported cases are the
third one: the cooperation continues, so the line has to go back to the active
roster with its MD pool untouched.  Without a value for that outcome the only
way out of a pending case was to record a decision that did not happen.

Two closed domains widen here and both are widened the same way — DROP the old
constraint, then ADD the new definition in the same Alembic transaction.
Swallowing ``duplicate_object`` would keep the OLD, narrower definition under
the same name, so the migration would report success and change nothing (the
trap documented for 0226/0233).
"""

from alembic import op


revision = "0250_offboarding_restore_resolution"
down_revision = "0249_order_rate_snapshots_offboarding"
branch_labels = None
depends_on = None


_RESOLUTION_CHECK_SQL = (
    "ALTER TABLE client_order_offboarding_cases "
    "ADD CONSTRAINT ck_client_order_offboarding_resolution "
    "CHECK (resolution IS NULL OR resolution IN ('remove', 'transfer', 'restore'))"
)

# ``restore`` disposes of nothing, so it carries neither a recipient nor a rate
# basis.  Separate constraint from the ``remove`` one on purpose: each name
# still says which decision it guards.
_RESTORE_TARGET_CHECK_SQL = (
    "ALTER TABLE client_order_offboarding_cases "
    "ADD CONSTRAINT ck_client_order_offboarding_restore_target "
    "CHECK (resolution IS DISTINCT FROM 'restore' "
    "OR (target_order_id IS NULL AND rate_basis IS NULL))"
)

_EVENT_CHECK_SQL = (
    "ALTER TABLE client_order_group_events "
    "ADD CONSTRAINT ck_client_order_group_events_type CHECK (event_type IN ("
    "'utworzenie', 'dodanie_konsultanta', 'import_md', "
    "'zamiana_kontraktora', 'edycja_reczna', 'zakonczenie', "
    "'przywrocenie', 'wyczerpanie', 'przedluzenie', 'import_faktur', "
    "'transfer_md', 'zakonczenie_konsultanta', 'decyzja_md_wymagana', "
    "'usuniecie_puli_md', 'przeniesienie_puli_md', "
    "'przywrocenie_konsultanta'))"
)

_EVENT_CHECK_SQL_0249 = (
    "ALTER TABLE client_order_group_events "
    "ADD CONSTRAINT ck_client_order_group_events_type CHECK (event_type IN ("
    "'utworzenie', 'dodanie_konsultanta', 'import_md', "
    "'zamiana_kontraktora', 'edycja_reczna', 'zakonczenie', "
    "'przywrocenie', 'wyczerpanie', 'przedluzenie', 'import_faktur', "
    "'transfer_md', 'zakonczenie_konsultanta', 'decyzja_md_wymagana', "
    "'usuniecie_puli_md', 'przeniesienie_puli_md'))"
)

_RESOLUTION_CHECK_SQL_0249 = (
    "ALTER TABLE client_order_offboarding_cases "
    "ADD CONSTRAINT ck_client_order_offboarding_resolution "
    "CHECK (resolution IS NULL OR resolution IN ('remove', 'transfer'))"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE client_order_offboarding_cases "
        "DROP CONSTRAINT IF EXISTS ck_client_order_offboarding_resolution"
    )
    op.execute(_RESOLUTION_CHECK_SQL)

    op.execute(
        "ALTER TABLE client_order_offboarding_cases "
        "DROP CONSTRAINT IF EXISTS ck_client_order_offboarding_restore_target"
    )
    op.execute(_RESTORE_TARGET_CHECK_SQL)

    op.execute(
        "ALTER TABLE client_order_group_events "
        "DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type"
    )
    op.execute(_EVENT_CHECK_SQL)


def downgrade() -> None:
    # Rows using the widened domains have to go before the narrower checks come
    # back, otherwise ADD CONSTRAINT fails on existing data.
    op.execute(
        "DELETE FROM client_order_group_events "
        "WHERE event_type = 'przywrocenie_konsultanta'"
    )
    op.execute(
        "ALTER TABLE client_order_group_events "
        "DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type"
    )
    op.execute(_EVENT_CHECK_SQL_0249)

    # A resolved case cannot become pending again (that would resurrect an
    # alert for a decision somebody already made), so downgrade rewrites the
    # outcome to the closest surviving value and keeps the audit trail in
    # ``resolution_payload``.
    op.execute(
        "UPDATE client_order_offboarding_cases "
        "SET resolution = 'remove', "
        "resolution_payload = COALESCE(resolution_payload, '{}'::jsonb) "
        "|| jsonb_build_object('downgraded_from', 'restore') "
        "WHERE resolution = 'restore'"
    )
    op.execute(
        "ALTER TABLE client_order_offboarding_cases "
        "DROP CONSTRAINT IF EXISTS ck_client_order_offboarding_restore_target"
    )
    op.execute(
        "ALTER TABLE client_order_offboarding_cases "
        "DROP CONSTRAINT IF EXISTS ck_client_order_offboarding_resolution"
    )
    op.execute(_RESOLUTION_CHECK_SQL_0249)
