"""Domknięcie dwóch historycznych korekt BIK po wdrożeniu workflow zamówień.

Revision ID: 0239_bik_contract_order_backfill
Revises: 0238_contract_order_workflows

Weryfikacja produkcyjna po 0238 wykazała dwa legacy rekordy, których ogólny
backfill nie objął:

* nazwisko Roberta Łuszczyńskiego jest zapisane z rozłożonym znakiem Unicode,
  więc porównanie całego napisu nie aktywowało kontraktu ``#571``;
* przyszłe zamówienie ``4500030684`` powstało przed wprowadzeniem statusu
  ``scheduled`` i nadal było równorzędną aktywną kartą.

Korekta jest celowo wskazana po identyfikatorze/kliencie/numerze/dacie i
wykonuje się tylko raz. Danych nie cofamy w ``downgrade``: po dacie startu
materializer albo operator mogą już wykonać kolejne prawidłowe zmiany, których
automatyczny rollback nie potrafiłby odróżnić od tego backfillu.
"""

from alembic import op

revision = "0239_bik_contract_order_backfill"
down_revision = "0238_contract_order_workflows"
branch_labels = None
depends_on = None


_BACKFILL_SQL = r"""
DO $contract_order_backfill$
DECLARE
    target_group_id INTEGER;
    target_group_count BIGINT := 0;
    contract_rows BIGINT := 0;
    order_line_rows BIGINT := 0;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM app_settings
        WHERE key = '0239_bik_contract_order_backfill'
    ) THEN
        RETURN;
    END IF;

    UPDATE contracts AS contract
       SET status = 'active'::contractstatus,
           updated_at = now()
      FROM candidates AS candidate,
           clients AS client
     WHERE contract.id = 571
       AND contract.client_id = 18
       AND contract.status = 'draft'::contractstatus
       AND candidate.id = contract.candidate_id
       AND btrim(candidate.name) = 'Robert'
       AND btrim(candidate.lastname) LIKE 'Łuszcz%'
       AND client.id = contract.client_id
       AND lower(concat_ws(' ', client.name, client.display_name, client.legal_name))
             LIKE '%biuro informacji kredytowej%';
    GET DIAGNOSTICS contract_rows = ROW_COUNT;

    SELECT count(*), max(order_group.id)
      INTO target_group_count, target_group_id
      FROM client_order_groups AS order_group
      JOIN clients AS client ON client.id = order_group.client_id
     WHERE order_group.client_id = 18
       AND order_group.order_number = '4500030684'
       AND order_group.status = 'active'
       AND order_group.predecessor_group_id IS NOT NULL
       AND order_group.start_date = DATE '2026-09-11'
       AND order_group.start_date > CURRENT_DATE
       AND lower(concat_ws(' ', client.name, client.display_name, client.legal_name))
             LIKE '%biuro informacji kredytowej%';

    IF target_group_count > 1 THEN
        RAISE EXCEPTION
            '0239 expected at most one BIK order group 4500030684, found %',
            target_group_count;
    END IF;

    IF target_group_count = 1 THEN
        UPDATE client_order_groups
           SET status = 'scheduled',
               updated_at = now()
         WHERE id = target_group_id;

        UPDATE client_orders
           SET status = 'draft'::clientorderstatus,
               filled_at = NULL,
               updated_at = now()
         WHERE order_group_id = target_group_id
           AND status = 'active'::clientorderstatus;
        GET DIAGNOSTICS order_line_rows = ROW_COUNT;
    END IF;

    INSERT INTO app_settings (key, value)
    VALUES (
        '0239_bik_contract_order_backfill',
        jsonb_build_object(
            'revision', '0239_bik_contract_order_backfill',
            'completed_at', clock_timestamp(),
            'source', 'alembic',
            'contract_rows', contract_rows,
            'order_group_rows', target_group_count,
            'order_line_rows', order_line_rows,
            'rollback', 'manual_only'
        )
    );
END
$contract_order_backfill$;
"""


def upgrade() -> None:
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    # Celowy no-op: patrz docstring. Marker zostaje jako ślad operacyjny, a
    # ewentualny rollback danych wymaga ręcznej decyzji na aktualnym stanie.
    pass
