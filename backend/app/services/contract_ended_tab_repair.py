"""Reguła zakładki „Zakończeni" — jednorazowa korekta danych (09.2026).

Zgłoszenie: osoby z zakończonym OKRESEM ZAMÓWIENIA trafiały do „Zakończonych"
niekonsekwentnie. U VeloBanku 11 osób miało to samo zamówienie do 31.08 —
do „Zakończonych" trafiły dokładnie te 4, którym umowa miała wpisaną datę końca
30.06 (przepisaną przy założeniu kontraktu z pierwszego okresu zamówienia, bez
wypowiedzenia), reszta miała umowę bezterminową i została w „Aktywnych".

Ticket wskazuje jedną korektę: Piotr Klimczak (VeloBank, Contract 469) dostaje
przedłużenie, więc jego umowa ma wrócić do „Aktywnych". Id nie jest zaufane
samo — klient, nazwisko, status, brak wypowiedzenia i data muszą się zgadzać
(wzorzec 0250). Pozostałe umowy z tej klasy (bez wypowiedzenia, z zamówieniem
trwającym PO dacie końca umowy) są wyłącznie AUDYTOWANE do paragonu
w ``app_settings``: dwie z trzech u VeloBanku to osoby, których na nowym
zamówieniu nie ma, więc masowe wskrzeszenie wciągnęłoby je do MRR i alertów.

Blok jest jednorazowy (marker + advisory lock) i idempotentny; jedno źródło
dla migracji 0271 i dla safety-netu w ``entrypoint.sh`` (alembic na prodzie
bywa osierocony).
"""

ENDED_TAB_REPAIR_MARKER = "0271_ended_tab_contract_repair"
_MARKER = ENDED_TAB_REPAIR_MARKER

ENDED_TAB_REPAIR_SQL = rf"""
DO $ended_tab_repair$
DECLARE
    business_day DATE := (clock_timestamp() AT TIME ZONE 'Europe/Warsaw')::date;
    repaired_rows BIGINT := 0;
    audited_rows BIGINT := 0;
    audited_contracts JSONB := '[]'::jsonb;
BEGIN
    -- Rolling deploy potrafi uruchomić blok dwa razy równolegle.
    PERFORM pg_advisory_xact_lock(hashtext('{_MARKER}'));
    IF EXISTS (SELECT 1 FROM app_settings WHERE key = '{_MARKER}') THEN
        RETURN;
    END IF;

    -- ── A. Audyt klasy: „zakończona" bez wypowiedzenia, a zamówienie trwało
    --       PO dacie końca umowy (data nie była decyzją o końcu współpracy).
    CREATE TEMP TABLE _ended_by_order_period ON COMMIT DROP AS
    SELECT c.id AS contract_id,
           c.client_id,
           c.end_date AS contract_end,
           max(o.end_date) AS latest_order_end
      FROM contracts AS c
      JOIN client_orders AS o
        ON o.contract_id = c.id
       AND o.client_id = c.client_id
     WHERE c.status = 'ended'
       AND c.terminated_at IS NULL
       AND c.termination_reason IS NULL
       AND c.end_date IS NOT NULL
       AND o.status NOT IN ('draft', 'cancelled')
       AND o.end_date IS NOT NULL
       AND o.end_date > c.end_date
     GROUP BY c.id, c.client_id, c.end_date;

    SELECT count(*) INTO audited_rows FROM _ended_by_order_period;
    SELECT coalesce(
               jsonb_agg(
                   jsonb_build_object(
                       'contract_id', contract_id,
                       'client_id', client_id,
                       'contract_end', contract_end,
                       'latest_order_end', latest_order_end
                   )
                   ORDER BY contract_id
               ),
               '[]'::jsonb
           )
      INTO audited_contracts
      FROM _ended_by_order_period;

    -- ── B. Korekta wskazana w tickecie — po pełnych kluczach biznesowych. ──
    CREATE TEMP TABLE _ticket_target ON COMMIT DROP AS
    SELECT c.id AS contract_id,
           c.status::text AS previous_status,
           c.end_date AS previous_end_date
      FROM contracts AS c
      JOIN candidates AS cand ON cand.id = c.candidate_id
      JOIN clients AS cl ON cl.id = c.client_id
     WHERE c.id = 469
       AND c.status = 'ended'
       AND c.terminated_at IS NULL
       AND c.termination_reason IS NULL
       AND c.end_date = DATE '2026-06-30'
       AND lower(coalesce(cand.name, '')) = 'piotr'
       AND lower(coalesce(cand.lastname, '')) = 'klimczak'
       AND lower(concat_ws(' ', cl.name, cl.display_name, cl.legal_name))
           LIKE '%velobank%';

    -- Bezterminowa, nie „do końca zamówienia": datę końca wpisze administracja.
    UPDATE contracts AS c
       SET status = 'active',
           end_date = NULL,
           client_order_end_date = NULL
      FROM _ticket_target AS t
     WHERE c.id = t.contract_id;
    GET DIAGNOSTICS repaired_rows = ROW_COUNT;

    INSERT INTO activities (entity_type, entity_id, action, details)
    SELECT 'contract',
           t.contract_id,
           'contract_reopened',
           jsonb_build_object(
               'from_status', t.previous_status,
               'to_status', 'active',
               'cleared_end_date', t.previous_end_date,
               'reason', 'end_date_was_order_period_not_termination',
               'source', '{_MARKER}'
           )
      FROM _ticket_target AS t;

    INSERT INTO app_settings (key, value)
    VALUES (
        '{_MARKER}',
        jsonb_build_object(
            'revision', '{_MARKER}',
            'completed_at', clock_timestamp(),
            'business_day', business_day,
            'source', 'alembic',
            'repaired_contracts', repaired_rows,
            'audited_ended_by_order_period', audited_rows,
            'audited_contracts', audited_contracts
        )
    )
    ON CONFLICT (key) DO NOTHING;

    RAISE NOTICE '0271 repaired % contract(s); % analogue(s) audited',
        repaired_rows, audited_rows;
END
$ended_tab_repair$;
"""
