"""Repair the two reported Nordea contracts and audit the wider stale class.

Revision ID: 0250_live_order_contract_repair
Revises: 0249_order_rate_snapshots_offboarding

Revision 0243 repaired stale rows present when the original POST-order fix
shipped.  The Nordea CSV importer and PATCH draft->active still skipped that
runtime service, so later active orders could again coexist with an ``ended``
contract.

The ticket explicitly identifies Contract 327/order 285493 (Grzegorz
Krolikowski) and Contract 165/order 285623 (Wojciech Drag) for correction.
Those IDs are never trusted alone: client, candidate, order number, active
status and effective period must all match.  The same query audits analogous
rows across every client, but does not mutate them; its per-client counts and
contract IDs are persisted in app_settings for production review.
"""

from alembic import op

revision = "0250_live_order_contract_repair"
down_revision = "0249_order_rate_snapshots_offboarding"
branch_labels = None
depends_on = None


_MARKER = "0250_live_order_contract_repair"

_REPAIR_SQL = rf"""
DO $live_order_contract_repair$
DECLARE
    business_day DATE := (clock_timestamp() AT TIME ZONE 'Europe/Warsaw')::date;
    audited_rows BIGINT := 0;
    affected_clients BIGINT := 0;
    repaired_rows BIGINT := 0;
    other_rows BIGINT := 0;
    known_records BIGINT := 0;
    known_already_active BIGINT := 0;
    by_client JSONB := '[]'::jsonb;
    audited_contract_ids JSONB := '[]'::jsonb;
    ticket_targets JSONB := '[]'::jsonb;
BEGIN
    -- Rolling deploys may overlap.  Serialize before reading the one-shot
    -- marker so neither corrections nor Activity rows can be duplicated.
    PERFORM pg_advisory_xact_lock(hashtext('{_MARKER}'));
    IF EXISTS (SELECT 1 FROM app_settings WHERE key = '{_MARKER}') THEN
        RETURN;
    END IF;

    CREATE TEMP TABLE _stale_live_order_audit ON COMMIT DROP AS
    SELECT c.id AS contract_id,
           c.client_id,
           c.status::text AS previous_status,
           lower(coalesce(candidate.name, '')) AS candidate_first_name,
           lower(coalesce(candidate.lastname, '')) AS candidate_last_name,
           lower(concat_ws(' ', client.name, client.display_name, client.legal_name))
               AS client_labels,
           bool_or(o.end_date IS NULL) AS has_open_ended,
           max(o.end_date) AS max_end,
           array_agg(o.id ORDER BY o.id) AS live_order_ids,
           array_agg(o.title ORDER BY o.id) AS live_order_numbers
      FROM contracts AS c
      JOIN clients AS client ON client.id = c.client_id
      JOIN candidates AS candidate ON candidate.id = c.candidate_id
     JOIN client_orders AS o ON o.contract_id = c.id
     WHERE c.status IN ('ended', 'ending')
       AND o.client_id = c.client_id
       AND o.status = 'active'
       AND o.start_date IS NOT NULL
       AND o.start_date <= business_day
       AND (o.end_date IS NULL OR o.end_date >= business_day)
     GROUP BY c.id,
              c.client_id,
              c.status,
              candidate.name,
              candidate.lastname,
              client.name,
              client.display_name,
              client.legal_name;

    CREATE TEMP TABLE _ticket_live_order_targets ON COMMIT DROP AS
    SELECT audit.*
      FROM _stale_live_order_audit AS audit
     WHERE audit.client_labels LIKE '%nordea%'
       AND (
           (
               audit.contract_id = 327
               AND audit.candidate_first_name = 'grzegorz'
               AND audit.candidate_last_name = 'królikowski'
               AND '285493' = ANY(audit.live_order_numbers)
               AND EXISTS (
                   SELECT 1
                     FROM client_orders AS target_order
                    WHERE target_order.contract_id = audit.contract_id
                      AND target_order.status = 'active'
                      AND btrim(target_order.title) = '285493'
                      AND target_order.start_date = DATE '2026-08-29'
                      AND target_order.end_date = DATE '2027-02-28'
               )
           )
           OR
           (
               audit.contract_id = 165
               AND audit.candidate_first_name = 'wojciech'
               AND audit.candidate_last_name = 'drąg'
               AND '285623' = ANY(audit.live_order_numbers)
               AND EXISTS (
                   SELECT 1
                     FROM client_orders AS target_order
                    WHERE target_order.contract_id = audit.contract_id
                      AND target_order.status = 'active'
                      AND btrim(target_order.title) = '285623'
                      AND target_order.start_date = DATE '2026-08-29'
                      AND target_order.end_date = DATE '2026-11-30'
               )
           )
       );

    -- Snapshot the two ticket identities BEFORE the repair.  Reading their
    -- status after the UPDATE would make every repaired row look as if it had
    -- already been active when the migration started, corrupting the receipt.
    CREATE TEMP TABLE _known_ticket_live_order_records ON COMMIT DROP AS
    SELECT DISTINCT c.id AS contract_id,
           c.status::text AS previous_status
      FROM contracts AS c
      JOIN clients AS client ON client.id = c.client_id
      JOIN candidates AS candidate ON candidate.id = c.candidate_id
     JOIN client_orders AS o ON o.contract_id = c.id
     WHERE o.client_id = c.client_id
       AND o.status = 'active'
       AND o.start_date IS NOT NULL
       AND o.start_date <= business_day
       AND (o.end_date IS NULL OR o.end_date >= business_day)
       AND lower(concat_ws(' ', client.name, client.display_name, client.legal_name))
           LIKE '%nordea%'
       AND (
           (
               c.id = 327
               AND lower(coalesce(candidate.name, '')) = 'grzegorz'
               AND lower(coalesce(candidate.lastname, '')) = 'królikowski'
               AND btrim(o.title) = '285493'
               AND o.start_date = DATE '2026-08-29'
               AND o.end_date = DATE '2027-02-28'
           )
           OR
           (
               c.id = 165
               AND lower(coalesce(candidate.name, '')) = 'wojciech'
               AND lower(coalesce(candidate.lastname, '')) = 'drąg'
               AND btrim(o.title) = '285623'
               AND o.start_date = DATE '2026-08-29'
               AND o.end_date = DATE '2026-11-30'
           )
       );

    -- The audit snapshot above is intentionally read-only evidence, not write
    -- authority.  A rolling application transaction may void the Contract or
    -- cancel/edit the exact Order after that snapshot.  Lock both action rows,
    -- then rebuild the target from their current values; a waiter rechecks the
    -- WHERE predicate after the concurrent transaction commits.
    PERFORM c.id
      FROM _ticket_live_order_targets AS t
      JOIN contracts AS c ON c.id = t.contract_id
      JOIN clients AS client ON client.id = c.client_id
      JOIN candidates AS candidate ON candidate.id = c.candidate_id
      JOIN client_orders AS target_order ON target_order.contract_id = c.id
     WHERE c.status IN ('ended', 'ending')
       AND target_order.client_id = c.client_id
       AND target_order.status = 'active'
       AND target_order.start_date IS NOT NULL
       AND target_order.start_date <= business_day
       AND (target_order.end_date IS NULL OR target_order.end_date >= business_day)
       AND lower(concat_ws(' ', client.name, client.display_name, client.legal_name))
           LIKE '%nordea%'
       AND (
           (
               c.id = 327
               AND lower(coalesce(candidate.name, '')) = 'grzegorz'
               AND lower(coalesce(candidate.lastname, '')) = 'królikowski'
               AND btrim(target_order.title) = '285493'
               AND target_order.start_date = DATE '2026-08-29'
               AND target_order.end_date = DATE '2027-02-28'
           )
           OR
           (
               c.id = 165
               AND lower(coalesce(candidate.name, '')) = 'wojciech'
               AND lower(coalesce(candidate.lastname, '')) = 'drąg'
               AND btrim(target_order.title) = '285623'
               AND target_order.start_date = DATE '2026-08-29'
               AND target_order.end_date = DATE '2026-11-30'
           )
       )
     ORDER BY c.id, target_order.id
       FOR UPDATE OF c, target_order;

    CREATE TEMP TABLE _action_ticket_targets ON COMMIT DROP AS
    SELECT DISTINCT ON (t.contract_id)
           t.contract_id,
           t.client_id,
           c.status::text AS previous_status,
           (target_order.end_date IS NULL) AS has_open_ended,
           target_order.end_date AS max_end,
           ARRAY[target_order.id] AS live_order_ids,
           ARRAY[target_order.title] AS live_order_numbers,
           target_order.id AS exact_order_id
      FROM _ticket_live_order_targets AS t
      JOIN contracts AS c ON c.id = t.contract_id
      JOIN clients AS client ON client.id = c.client_id
      JOIN candidates AS candidate ON candidate.id = c.candidate_id
      JOIN client_orders AS target_order ON target_order.contract_id = c.id
     WHERE c.status IN ('ended', 'ending')
       AND target_order.client_id = c.client_id
       AND target_order.status = 'active'
       AND target_order.start_date IS NOT NULL
       AND target_order.start_date <= business_day
       AND (target_order.end_date IS NULL OR target_order.end_date >= business_day)
       AND lower(concat_ws(' ', client.name, client.display_name, client.legal_name))
           LIKE '%nordea%'
       AND (
           (
               c.id = 327
               AND lower(coalesce(candidate.name, '')) = 'grzegorz'
               AND lower(coalesce(candidate.lastname, '')) = 'królikowski'
               AND btrim(target_order.title) = '285493'
               AND target_order.start_date = DATE '2026-08-29'
               AND target_order.end_date = DATE '2027-02-28'
           )
           OR
           (
               c.id = 165
               AND lower(coalesce(candidate.name, '')) = 'wojciech'
               AND lower(coalesce(candidate.lastname, '')) = 'drąg'
               AND btrim(target_order.title) = '285623'
               AND target_order.start_date = DATE '2026-08-29'
               AND target_order.end_date = DATE '2026-11-30'
           )
       )
     ORDER BY t.contract_id, target_order.id;

    -- Receipt rows come from UPDATE ... RETURNING, never from the earlier
    -- candidate snapshot.  The explicit guards are repeated in the UPDATE so
    -- neither a stale temp table nor a future refactor can weaken action-time
    -- validation.  ``exact_order_id`` is already locked until commit.
    CREATE TEMP TABLE _repaired_ticket_targets ON COMMIT DROP AS
    WITH updated AS (
        UPDATE contracts AS c
           SET status = 'active',
               end_date = CASE
                   WHEN t.has_open_ended THEN NULL
                   WHEN c.end_date IS NULL THEN NULL
                   WHEN t.max_end > c.end_date THEN t.max_end
                   ELSE c.end_date
               END,
               client_order_end_date = CASE
                   WHEN c.client_order_end_date IS NULL THEN NULL
                   WHEN t.has_open_ended THEN NULL
                   WHEN t.max_end > c.client_order_end_date THEN t.max_end
                   ELSE c.client_order_end_date
               END
          FROM _action_ticket_targets AS t
         WHERE c.id = t.contract_id
           AND c.status IN ('ended', 'ending')
           AND EXISTS (
               SELECT 1
                 FROM client_orders AS target_order
                WHERE target_order.id = t.exact_order_id
                  AND target_order.contract_id = c.id
                  AND target_order.client_id = c.client_id
                  AND target_order.status = 'active'
                  AND target_order.start_date IS NOT NULL
                  AND target_order.start_date <= business_day
                  AND (target_order.end_date IS NULL
                       OR target_order.end_date >= business_day)
                  AND (
                      (
                          c.id = 327
                          AND btrim(target_order.title) = '285493'
                          AND target_order.start_date = DATE '2026-08-29'
                          AND target_order.end_date = DATE '2027-02-28'
                      )
                      OR
                      (
                          c.id = 165
                          AND btrim(target_order.title) = '285623'
                          AND target_order.start_date = DATE '2026-08-29'
                          AND target_order.end_date = DATE '2026-11-30'
                      )
                  )
           )
        RETURNING c.id AS contract_id
    )
    SELECT t.contract_id,
           t.client_id,
           t.previous_status,
           t.live_order_ids,
           t.live_order_numbers
      FROM updated AS u
      JOIN _action_ticket_targets AS t ON t.contract_id = u.contract_id;

    SELECT count(*) INTO repaired_rows FROM _repaired_ticket_targets;

    INSERT INTO activities (entity_type, entity_id, action, details)
    SELECT 'contract',
           t.contract_id,
           'contract_reopened',
           jsonb_build_object(
               'from_status', t.previous_status,
               'to_status', 'active',
               'source', '{_MARKER}',
               'client_id', t.client_id,
               'live_order_ids', to_jsonb(t.live_order_ids),
               'live_order_numbers', to_jsonb(t.live_order_numbers)
           )
      FROM _repaired_ticket_targets AS t;

    SELECT count(*), count(DISTINCT client_id)
      INTO audited_rows, affected_clients
      FROM _stale_live_order_audit;
    other_rows := audited_rows - repaired_rows;

    SELECT count(*),
           count(*) FILTER (WHERE previous_status = 'active')
      INTO known_records, known_already_active
      FROM _known_ticket_live_order_records;

    SELECT coalesce(
               jsonb_agg(
                   jsonb_build_object(
                       'client_id', grouped.client_id,
                       'contracts', grouped.contracts
                   ) ORDER BY grouped.client_id
               ),
               '[]'::jsonb
           )
      INTO by_client
      FROM (
          SELECT client_id, count(*) AS contracts
            FROM _stale_live_order_audit
           GROUP BY client_id
      ) AS grouped;

    SELECT coalesce(jsonb_agg(contract_id ORDER BY contract_id), '[]'::jsonb)
      INTO audited_contract_ids
      FROM _stale_live_order_audit;

    SELECT coalesce(
               jsonb_agg(
                   jsonb_build_object(
                       'contract_id', contract_id,
                       'client_id', client_id,
                       'live_order_numbers', to_jsonb(live_order_numbers)
                   ) ORDER BY contract_id
               ),
               '[]'::jsonb
           )
      INTO ticket_targets
      FROM _repaired_ticket_targets;

    INSERT INTO app_settings (key, value)
    VALUES (
        '{_MARKER}',
        jsonb_build_object(
            'revision', '{_MARKER}',
            'completed_at', clock_timestamp(),
            'business_day', business_day,
            'source', 'alembic',
            'audited_stale_contracts', audited_rows,
            'affected_clients', affected_clients,
            'ticket_contracts_repaired', repaired_rows,
            'analogous_contracts_not_mutated', other_rows,
            'known_ticket_records_found', known_records,
            'known_ticket_records_already_active', known_already_active,
            'by_client', by_client,
            'audited_contract_ids', audited_contract_ids,
            'ticket_targets', ticket_targets
        )
    )
    ON CONFLICT (key) DO NOTHING;

    RAISE NOTICE
        '0250 audited % stale contract(s) for % client(s), repaired % ticket contract(s), left % analogous contract(s) read-only',
        audited_rows, affected_clients, repaired_rows, other_rows;
END
$live_order_contract_repair$;
"""


def upgrade() -> None:
    op.execute(_REPAIR_SQL)


def downgrade() -> None:
    # No automatic reversal: after deployment an order may legitimately keep
    # the contract active.  The prior status is preserved in Activity.details.
    pass
