"""Jednorazowa naprawa danych po rozdzieleniu zamówień MD i okresowych.

SQL mieszka TUTAJ, a nie w migracji, bo ma DWÓCH wołających: migrację
``0262_separate_md_periodic`` oraz safety-net w ``entrypoint.sh`` (alembic na
produkcji bywa osierocony, a ta naprawa jest treścią ticketu, nie kosmetyką).
Dwie kopie tego samego bloku rozjechałyby się przy pierwszej poprawce.

Blok jest jednorazowy i idempotentny: advisory lock serializuje równoległe
deploye, a marker w ``app_settings`` sprawia, że drugie wywołanie kończy się
natychmiast. Dlatego wołanie go przy każdym starcie kontenera jest bezpieczne.
"""

from __future__ import annotations


SEPARATE_MD_PERIODIC_MARKER = "0262_separate_md_periodic"
_MARKER = SEPARATE_MD_PERIODIC_MARKER

SEPARATE_MD_PERIODIC_SQL = rf"""
DO $separate_md_periodic$
DECLARE
    business_day DATE := (clock_timestamp() AT TIME ZONE 'Europe/Warsaw')::date;
    shells_deleted BIGINT := 0;
    duplicates_cancelled BIGINT := 0;
    contracts_freed BIGINT := 0;
    contracts_reactivated BIGINT := 0;
    duplicates_by_client JSONB := '[]'::jsonb;
    freed_contract_ids JSONB := '[]'::jsonb;
BEGIN
    -- Rolling deploy potrafi uruchomić migrację dwa razy równolegle.
    PERFORM pg_advisory_xact_lock(hashtext('{_MARKER}'));
    IF EXISTS (SELECT 1 FROM app_settings WHERE key = '{_MARKER}') THEN
        RETURN;
    END IF;

    -- ── A. Duplikaty zamówień okresowych obok żywej linii grupowej ────────
    CREATE TEMP TABLE _dup_periodic ON COMMIT DROP AS
    SELECT o.id AS order_id,
           o.contract_id,
           o.client_id,
           o.status::text AS previous_status,
           (
               o.status = 'draft'
               AND btrim(coalesce(o.title, '')) = '(bez numeru)'
               AND o.file_path IS NULL
               AND o.md_total IS NULL
               AND o.filled_at IS NULL
           ) AS is_empty_shell
      FROM client_orders AS o
      JOIN contracts AS c ON c.id = o.contract_id
     WHERE o.order_group_id IS NULL
       AND o.client_id = c.client_id
       AND o.status IN ('draft', 'active', 'paused')
       AND EXISTS (
           SELECT 1
             FROM client_orders AS g
            WHERE g.contract_id = o.contract_id
              AND g.order_group_id IS NOT NULL
              AND g.status IN ('draft', 'active', 'paused')
       )
     ORDER BY o.id;

    -- Snapshot to DOWÓD, nie prawo zapisu: równoległa transakcja aplikacji
    -- może w tej chwili anulować albo domknąć dokładnie ten wiersz. Blokujemy
    -- go osobnym zapytaniem (CTAS z `FOR UPDATE` nie łączy się z `DISTINCT`,
    -- którego wymaga krok B — jeden wzorzec w obu krokach jest czytelniejszy
    -- niż dwa).
    PERFORM o.id
       FROM client_orders AS o
       JOIN _dup_periodic AS d ON d.order_id = o.id
      ORDER BY o.id
        FOR UPDATE OF o;

    DELETE FROM client_orders AS o
     USING _dup_periodic AS d
     WHERE o.id = d.order_id
       AND d.is_empty_shell;
    GET DIAGNOSTICS shells_deleted = ROW_COUNT;

    UPDATE client_orders AS o
       SET status = 'cancelled'
      FROM _dup_periodic AS d
     WHERE o.id = d.order_id
       AND NOT d.is_empty_shell;
    GET DIAGNOSTICS duplicates_cancelled = ROW_COUNT;

    INSERT INTO activities (entity_type, entity_id, action, details)
    SELECT 'client_order',
           d.order_id,
           CASE WHEN d.is_empty_shell THEN 'order_deleted' ELSE 'order_cancelled' END,
           jsonb_build_object(
               'contract_id', d.contract_id,
               'client_id', d.client_id,
               'previous_status', d.previous_status,
               'reason', 'duplicate_of_group_line',
               'source', '{_MARKER}'
           )
      FROM _dup_periodic AS d;

    SELECT coalesce(jsonb_agg(row_to_json(summary)), '[]'::jsonb)
      INTO duplicates_by_client
      FROM (
          SELECT client_id,
                 count(*) FILTER (WHERE is_empty_shell) AS deleted_shells,
                 count(*) FILTER (WHERE NOT is_empty_shell) AS cancelled_orders
            FROM _dup_periodic
           GROUP BY client_id
           ORDER BY client_id
      ) AS summary;

    -- ── B. Data końca umowy przepisana z zamówienia ───────────────────────
    CREATE TEMP TABLE _order_dated_contracts ON COMMIT DROP AS
    SELECT DISTINCT c.id AS contract_id,
           c.client_id,
           c.status::text AS previous_status,
           c.end_date AS previous_end_date
      FROM contracts AS c
      JOIN client_orders AS line ON line.contract_id = c.id
      LEFT JOIN client_order_groups AS grp ON grp.id = line.order_group_id
     WHERE c.end_date IS NOT NULL
       AND c.terminated_at IS NULL
       AND c.termination_reason IS NULL
       AND c.status IN ('draft', 'active', 'ending', 'ended')
       AND line.order_group_id IS NOT NULL
       AND line.client_id = c.client_id
       AND line.status IN ('draft', 'active', 'paused')
       -- Linia dalej obowiązuje: konsultant NIE zakończył współpracy.
       AND (line.start_date IS NULL OR line.start_date <= business_day)
       AND (
           coalesce(line.end_date, grp.end_date) IS NULL
           OR coalesce(line.end_date, grp.end_date) >= business_day
       )
       -- Data umowy jest DOKŁADNIE datą zamówienia — to jej pochodzenie.
       AND c.end_date = coalesce(line.end_date, grp.end_date)
       AND NOT EXISTS (
           SELECT 1
             FROM contract_amendments AS a
            WHERE a.contract_id = c.id
              AND a.amendment_type = 'early_termination'
       )
     ORDER BY c.id;

    PERFORM c.id
       FROM contracts AS c
       JOIN _order_dated_contracts AS t ON t.contract_id = c.id
      ORDER BY c.id
        FOR UPDATE OF c;

    UPDATE contracts AS c
       SET end_date = NULL,
           status = CASE
               WHEN c.status IN ('ending', 'ended') THEN 'active'
               ELSE c.status
           END
      FROM _order_dated_contracts AS t
     WHERE c.id = t.contract_id;
    GET DIAGNOSTICS contracts_freed = ROW_COUNT;

    SELECT count(*) INTO contracts_reactivated
      FROM _order_dated_contracts
     WHERE previous_status IN ('ending', 'ended');

    INSERT INTO activities (entity_type, entity_id, action, details)
    SELECT 'contract',
           t.contract_id,
           CASE
               WHEN t.previous_status IN ('ending', 'ended') THEN 'contract_reopened'
               ELSE 'updated'
           END,
           jsonb_build_object(
               'from_status', t.previous_status,
               'to_status',
               CASE
                   WHEN t.previous_status IN ('ending', 'ended') THEN 'active'
                   ELSE t.previous_status
               END,
               'cleared_end_date', t.previous_end_date,
               'reason', 'end_date_copied_from_client_order',
               'source', '{_MARKER}'
           )
      FROM _order_dated_contracts AS t;

    SELECT coalesce(jsonb_agg(contract_id ORDER BY contract_id), '[]'::jsonb)
      INTO freed_contract_ids
      FROM _order_dated_contracts;

    INSERT INTO app_settings (key, value)
    VALUES (
        '{_MARKER}',
        jsonb_build_object(
            'revision', '{_MARKER}',
            'completed_at', clock_timestamp(),
            'business_day', business_day,
            'source', 'alembic',
            'duplicate_shells_deleted', shells_deleted,
            'duplicate_orders_cancelled', duplicates_cancelled,
            'duplicates_by_client', duplicates_by_client,
            'contracts_end_date_cleared', contracts_freed,
            'contracts_reactivated', contracts_reactivated,
            'contract_ids', freed_contract_ids
        )
    )
    ON CONFLICT (key) DO NOTHING;
END
$separate_md_periodic$;
"""
