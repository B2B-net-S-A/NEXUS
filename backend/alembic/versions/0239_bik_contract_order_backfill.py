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

Ponieważ marker czyni tę korektę JEDNORAZOWĄ, każde „nic nie zrobiłem" musi być
rozstrzygnięte, a nie przemilczane. Stąd dwie bramki:

* aktywacja kontraktu wymaga kompletu ``ACTIVATION_REQUIRED_FIELDS`` (lustro
  ``validate_ready_for_activation``) i dopisuje wiersz ``contract_activated``,
  a rozpoznany, ale niekompletny szkic przerywa migrację zamiast zostawiać
  aktywnego konsultanta bez marży i bez zdarzenia w historii;
* zerowe dopasowanie grupy zamówień jest akceptowane tylko wtedy, gdy u BIK nie
  stoi przyszłe zamówienie ``4500030684`` w statusie ``active`` — w przeciwnym
  razie marker skonsumowałby korektę, a poprzednik nigdy nie zostałby domknięty.
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
    activity_rows BIGINT := 0;
    missing_activation_fields TEXT[];
    stray_group_id INTEGER;
    stray_group_start DATE;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM app_settings
        WHERE key = '0239_bik_contract_order_backfill'
    ) THEN
        RETURN;
    END IF;

    -- Sześć warunków „IS NOT NULL" to lustro ``ACTIVATION_REQUIRED_FIELDS``
    -- (app/services/contract_service.py). ``activate_contract`` jest jedyną
    -- dozwoloną drogą do ``active`` i odrzuca niekompletny szkic, bo bez tych
    -- pól marża, finanse i alerty końca umowy pokazują śmieci. SQL, który
    -- aktywuje to, czego API aktywować nie pozwala, wpuszcza konsultanta do
    -- rejestru z marżą „—" i zerowym wkładem do kafla MRR — cicho, bez awarii.
    -- Sprawdzamy SUROWE kolumny, a nie stawki z harmonogramów: dokładnie te
    -- kolumny czyta ``validate_ready_for_activation``, więc każdy inny warunek
    -- rozjechałby migrację z bramką API zamiast ją odwzorować.
    UPDATE contracts AS contract
       SET status = 'active'::contractstatus,
           updated_at = now()
      FROM candidates AS candidate,
           clients AS client
     WHERE contract.id = 571
       AND contract.client_id = 18
       AND contract.status = 'draft'::contractstatus
       AND contract.start_date IS NOT NULL
       AND contract.end_date IS NOT NULL
       AND contract.rate_candidate IS NOT NULL
       AND contract.rate_client IS NOT NULL
       AND contract.contract_type IS NOT NULL
       AND contract.work_mode IS NOT NULL
       AND candidate.id = contract.candidate_id
       AND btrim(candidate.name) = 'Robert'
       AND btrim(candidate.lastname) LIKE 'Łuszcz%'
       AND client.id = contract.client_id
       AND lower(concat_ws(' ', client.name, client.display_name, client.legal_name))
             LIKE '%biuro informacji kredytowej%';
    GET DIAGNOSTICS contract_rows = ROW_COUNT;

    IF contract_rows = 1 THEN
        -- ``activate_contract`` dopisuje wiersz ``contract_activated``; bez
        -- niego historia kontraktu (GET /api/contracts/{id}/activity) skacze
        -- ze szkicu na aktywny bez zdarzenia i nie widać, że zmienił to
        -- backfill, a nie człowiek. ``user_id`` zostaje NULL — aktorem jest
        -- migracja, a podstawienie tu czyjegokolwiek konta byłoby fałszem
        -- w dzienniku audytowym.
        INSERT INTO activities (entity_type, entity_id, action, details)
        VALUES (
            'contract',
            571,
            'contract_activated',
            jsonb_build_object(
                'from_status', 'draft',
                'to_status', 'active',
                'source', '0239_bik_contract_order_backfill'
            )
        );
        GET DIAGNOSTICS activity_rows = ROW_COUNT;
    ELSE
        -- Rozróżniamy „nie ma czego poprawiać" od „rozpoznaję cel i NIE umiem
        -- go poprawić". Jeżeli kontrakt 571 nadal jest szkicem tej osoby u tego
        -- klienta, a brakuje mu pól aktywacyjnych, to jednorazowa korekta nie
        -- ma jak zadziałać — a marker niżej skonsumowałby ją bezpowrotnie,
        -- bez retry i bez alarmu (jedynym śladem byłoby ``contract_rows: 0``
        -- w JSON-ie, którego nikt nie czyta). Głośne przerwanie jest tu tańsze:
        -- właściwą ścieżką jest uzupełnienie pól i aktywacja przez UI.
        SELECT array_remove(ARRAY[
                   CASE WHEN contract.start_date IS NULL THEN 'start_date' END,
                   CASE WHEN contract.end_date IS NULL THEN 'end_date' END,
                   CASE WHEN contract.rate_candidate IS NULL
                        THEN 'rate_candidate' END,
                   CASE WHEN contract.rate_client IS NULL
                        THEN 'rate_client' END,
                   CASE WHEN contract.contract_type IS NULL
                        THEN 'contract_type' END,
                   CASE WHEN contract.work_mode IS NULL THEN 'work_mode' END
               ], NULL)
          INTO missing_activation_fields
          FROM contracts AS contract
          JOIN candidates AS candidate ON candidate.id = contract.candidate_id
          JOIN clients AS client ON client.id = contract.client_id
         WHERE contract.id = 571
           AND contract.client_id = 18
           AND contract.status = 'draft'::contractstatus
           AND btrim(candidate.name) = 'Robert'
           AND btrim(candidate.lastname) LIKE 'Łuszcz%'
           AND lower(concat_ws(
                   ' ', client.name, client.display_name, client.legal_name
               )) LIKE '%biuro informacji kredytowej%';

        IF coalesce(array_length(missing_activation_fields, 1), 0) > 0 THEN
            RAISE EXCEPTION
                '0239 contract 571 is still a draft and cannot be activated '
                'by SQL — missing activation fields: %. Fill them in and '
                'activate through the UI.',
                array_to_string(missing_activation_fields, ', ');
        END IF;
    END IF;

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

    IF target_group_count = 0 THEN
        -- Fail-closed łapał wyłącznie NADMIAR, a zero traktował jak sukces:
        -- marker niżej zapisuje się bezwarunkowo, więc jednorazowa korekta
        -- znikała, mimo że nic nie zrobiła. Zapytanie wyżej ma sześć
        -- koniunkcji (m.in. ``predecessor_group_id IS NOT NULL`` i dokładny
        -- numer), a grupa powstała starą ścieżką, w której powiązanie
        -- z poprzednikiem wcale nie musiało zostać zapisane — więc zero
        -- oznacza albo „już poprawione", albo „nie rozpoznaję kształtu".
        --
        -- Rozstrzyga to WĘŻSZE pytanie: czy u BIK stoi grupa 4500030684, która
        -- jest ``active``, choć zaczyna się dopiero w przyszłości. Taka grupa
        -- nie może być aktywna (``materialize_scheduled_order_groups`` promuje
        -- wyłącznie ``scheduled``, więc w dniu startu nie domknie poprzednika
        -- i u klienta zostaną dwie równorzędne karty tego samego zamówienia).
        -- Przerywamy głośno, bo cichy marker znosi retry i nie ma tu żadnego
        -- alarmu — ``/api/health`` o tej rozbieżności nie wie.
        --
        -- Warunek celowo NIE odpala się po dacie startu: od 11.09.2026 status
        -- ``active`` jest dla tej grupy stanem POPRAWNYM i wyjątek blokowałby
        -- migrację bez końca.
        SELECT order_group.id, order_group.start_date
          INTO stray_group_id, stray_group_start
          FROM client_order_groups AS order_group
         WHERE order_group.client_id = 18
           AND order_group.order_number = '4500030684'
           AND order_group.status = 'active'
           AND order_group.start_date IS NOT NULL
           AND order_group.start_date > CURRENT_DATE
         ORDER BY order_group.id
         LIMIT 1;

        IF stray_group_id IS NOT NULL THEN
            RAISE EXCEPTION
                '0239 BIK order group 4500030684 (id %) is active but starts '
                'in the future (%) — it does not match the expected shape, so '
                'the one-shot correction was NOT consumed',
                stray_group_id,
                stray_group_start;
        END IF;
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
            'contract_activity_rows', activity_rows,
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
