"""PFRON 507–509 — jednorazowe rozdzielenie zamówień nadpisanych „reaktywacją”.

Co się stało (produkcja, noc 9/10.09.2026, ok. 22.07 UTC, jednorazowe
czyszczenie kolejki zamówień z maila po #1472): dokumenty 20, 19 i 18 klienta
122 (PFRON) dostały plan „reactivate”. Ówczesny writer brał ZAKOŃCZONE
zamówienie (koniec 31.08.2026) i przepisywał je W MIEJSCU nowym okresem
01.09–30.11.2026 — numer, okres, stawkę przychodową, koszt i PDF — dopisywał
do ``notes`` zdanie „Powrót po N dniach…” i aktywował. Na tych zamówieniach
rozliczono już faktury za poprzedni okres. Decyzja z 10.09.2026: powrót po
przerwie to NOWE zamówienie (writer poprawiony w P0), a historię odtwarzamy
z zapisu w aplikacji — Delivery Lead weryfikuje wynik.

Źródłem prawdy jest Activity ``order_mail_reactivate``: jej ``details.before``
trzyma tytuł, okres, stawkę przychodową i ścieżkę PDF sprzed nadpisania,
``details.message`` — dokładnie dopisane do notatek zdanie, a ``created_at``
— początek transakcji, w której nadpisanie się wydarzyło (T0).

Dla każdego zamówienia przypiętego PEŁNĄ tożsamością biznesową (klient,
kontrakt, zamówienie, stan bieżący, Activity z dokumentem i datą 31.08, wpis
z maila z planem „reactivate” na 01.09, brak drugiego zamówienia na nowy ani
na przywracany okres, sprawdzalna jednostka stawki) — inaczej pomijamy
i zapisujemy powód, nigdy nie zgadujemy:

a. nowy wiersz ``client_orders`` przejmuje BIEŻĄCY stan (kopia wszystkich
   kolumn z katalogu, więc kolumna dopisana w przyszłości też przejdzie);
   wyjątki mają dowód: ``created_at``/``created_by`` z Activity (zamówienie na
   nowy okres powstało w T0, z ręki automatu), ``notes`` = znacznik
   idempotencji writera, ``total_value`` z planu dokumentu (writer nie ruszał
   tej kolumny, więc bieżąca wartość opisuje POPRZEDNIE zamówienie — nigdy
   nie trafia do nowego wiersza), ``filled_at`` = pierwsza aktywacja nowego
   okresu;
b. oryginał wraca do stanu ``before``: zakończony, stary tytuł/okres/stawka/
   PDF, notatki bez dopisku, koszt z harmonogramu umowy na OSTATNI dzień
   starego okresu (``cost_reference_day`` zamówienia zakończonego — ten sam
   dzień czyta raport zgodności zamówienie ↔ kontrakt), przeliczony jak
   ``convert_rate_between``;
c. przypięty dokument z maila i jego ``apply_result`` wskazują nowy wiersz
   (inne dokumenty wskazujące zamówienie po T0 tylko w paragonie — mogły
   dotyczyć starego okresu);
d. wiersze potomne powstałe w T0 lub później idą za nowym okresem; starsze
   zostają przy oryginale. Tabele z miesiącem rozliczenia rozstrzyga miesiąc.

Kontrakty 397–399 zostają nietknięte. Krok harmonogramu przychodu dla
przywróconego okresu dopisze synchronizacja kontrakt ↔ zamówienia przy
najbliższym zapisie zamówienia tej osoby (surowy SQL jej nie wyzwala) —
paragon ma to jako ``contract_revenue_resync``. Blok jest jednorazowy (marker +
advisory lock) i atomowy; jedno źródło SQL-a dla migracji 0306 i dla bloku
w ``entrypoint.sh`` (alembic na produkcji bywa osierocony).

Uwaga dla edytujących SQL: ``text()`` SQLAlchemy traktuje ``:słowo`` jako
parametr — w treści bloku nie ma godzin („22.07”, nie z dwukropkiem) ani
znaczników w rodzaju ``klucz:wartość``; stąd ``make_timestamptz``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Sequence

PFRON_RENEWAL_SPLIT_MARKER = "0306_pfron_renewal_split_repair"


@dataclass(frozen=True)
class SplitTarget:
    """Jedno nadpisane zamówienie: id zamówienia, jego kontrakt i dokument z maila."""

    order_id: int
    contract_id: int
    document_id: int


PFRON_CLIENT_ID = 122
PFRON_TARGETS: tuple[SplitTarget, ...] = (
    SplitTarget(order_id=507, contract_id=399, document_id=20),
    SplitTarget(order_id=508, contract_id=398, document_id=19),
    SplitTarget(order_id=509, contract_id=397, document_id=18),
)
NEW_PERIOD_START = date(2026, 9, 1)
NEW_PERIOD_END = date(2026, 11, 30)
PREVIOUS_PERIOD_END = date(2026, 8, 31)
#: Okno, w którym musi leżeć Activity nadpisania (T0 ≈ 9.09.2026 22.07 UTC).
INCIDENT_WINDOW = (
    datetime(2026, 9, 9, tzinfo=timezone.utc),
    datetime(2026, 9, 11, tzinfo=timezone.utc),
)

#: Klucze obce do ``client_orders``, które blok obsługuje jawnie. Każdy inny
#: klucz z referencją do przypiętego zamówienia zatrzymuje to zamówienie
#: (powód w paragonie) — nieznanej semantyki nie przenosimy na ślepo.
HANDLED_FOREIGN_KEYS: tuple[tuple[str, str], ...] = (
    ("client_order_group_events", "order_id"),
    ("client_order_invoice_consumptions", "order_id"),
    ("client_order_md_consumptions", "order_id"),
    ("client_order_offboarding_cases", "order_id"),
    ("client_order_offboarding_cases", "target_order_id"),
    ("client_orders", "predecessor_order_id"),
    ("contract_client_rates", "source_order_id"),
    ("dl_alerts", "order_id"),
    ("md_consumption_import_rows", "matched_order_id"),
    ("order_mail_documents", "applied_order_id"),
)

_TEMPLATE = r"""
DO $pfron_renewal_split$
DECLARE
    v_marker CONSTANT TEXT := '__MARKER__';
    v_client_id CONSTANT INTEGER := __CLIENT_ID__;
    v_new_start CONSTANT DATE := DATE '__NEW_START__';
    v_new_end CONSTANT DATE := DATE '__NEW_END__';
    v_previous_end CONSTANT DATE := DATE '__PREVIOUS_END__';
    v_window_start CONSTANT TIMESTAMPTZ := __WINDOW_START__;
    v_window_end CONSTANT TIMESTAMPTZ := __WINDOW_END__;
    v_new_month CONSTANT TEXT := to_char(DATE '__NEW_START__', 'YYYY-MM');
    v_copy_columns TEXT;
    v_fk_inventory JSONB;
    v_results JSONB := '[]'::jsonb;
    v_split_count INTEGER := 0;
    v_skipped_count INTEGER := 0;
    v_target RECORD;
    v_fk RECORD;
    v_order client_orders%ROWTYPE;
    v_activity activities%ROWTYPE;
    v_document order_mail_documents%ROWTYPE;
    v_contract_client_id INTEGER;
    v_contract_unit TEXT;
    v_contract_hours INTEGER;
    v_count INTEGER;
    v_reason TEXT;
    v_reason_detail JSONB;
    v_before JSONB;
    v_text TEXT;
    v_before_title TEXT;
    v_before_title_raw TEXT;
    v_before_start DATE;
    v_before_rate NUMERIC;
    v_before_file TEXT;
    v_applied_rows JSONB;
    v_plan_row JSONB;
    v_row_index TEXT;
    v_message TEXT;
    v_notes_restorable BOOLEAN;
    v_restored_notes TEXT;
    v_schedule_rate NUMERIC;
    v_restored_cost NUMERIC;
    v_cost_source TEXT;
    v_new_total NUMERIC;
    v_total_source TEXT;
    v_new_filled TIMESTAMPTZ;
    v_restored_filled TIMESTAMPTZ;
    v_file_mode TEXT;
    v_file_changed BOOLEAN;
    v_new_row_drops_file BOOLEAN;
    v_order_hours INTEGER;
    v_new_id INTEGER;
    v_moved JSONB;
    v_kept JSONB;
    v_shared_file JSONB;
    v_other_documents JSONB;
BEGIN
    -- Rolling deploy potrafi uruchomić blok dwa razy równolegle.
    PERFORM pg_advisory_xact_lock(hashtext(v_marker));
    IF EXISTS (SELECT 1 FROM app_settings WHERE key = v_marker) THEN
        RETURN;
    END IF;

    -- Kolumny do skopiowania bieżącego stanu: z katalogu, bez klucza
    -- głównego i kolumn generowanych — kolumna dopisana w przyszłości też
    -- trafi do nowego wiersza.
    SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum)
      INTO v_copy_columns
      FROM pg_attribute AS a
     WHERE a.attrelid = 'client_orders'::regclass
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND a.attgenerated = ''
       AND a.attidentity = ''
       AND a.attname <> 'id';

    -- Inwentarz WSZYSTKICH kluczy obcych do client_orders w chwili biegu.
    SELECT coalesce(
               jsonb_agg(
                   jsonb_build_object(
                       'table', c.conrelid::regclass::text,
                       'column', a.attname,
                       'on_delete',
                       CASE c.confdeltype
                           WHEN 'c' THEN 'CASCADE'
                           WHEN 'n' THEN 'SET NULL'
                           WHEN 'r' THEN 'RESTRICT'
                           WHEN 'd' THEN 'SET DEFAULT'
                           ELSE 'NO ACTION'
                       END,
                       'handled',
                       (c.conrelid::regclass::text, a.attname::text)
                           IN (__HANDLED_FKS__)
                   )
                   ORDER BY c.conrelid::regclass::text, a.attname
               ),
               '[]'::jsonb
           )
      INTO v_fk_inventory
      FROM pg_constraint AS c
      JOIN pg_attribute AS a
        ON a.attrelid = c.conrelid
       AND a.attnum = c.conkey[1]
     WHERE c.contype = 'f'
       AND c.confrelid = 'client_orders'::regclass;

    FOR v_target IN
        SELECT *
          FROM (VALUES __TARGETS__) AS t(order_id, contract_id, document_id)
         ORDER BY t.order_id
    LOOP
        v_reason := NULL;
        v_reason_detail := NULL;

        -- ── Tożsamość biznesowa: klient, kontrakt, zamówienie, stan bieżący ──
        SELECT * INTO v_order
          FROM client_orders
         WHERE id = v_target.order_id
           FOR UPDATE;
        IF NOT FOUND THEN
            v_reason := 'order_missing';
        ELSIF v_order.client_id <> v_client_id THEN
            v_reason := 'client_mismatch';
        ELSIF v_order.contract_id <> v_target.contract_id THEN
            v_reason := 'contract_mismatch';
        END IF;

        IF v_reason IS NULL THEN
            SELECT c.client_id, c.rate_unit::text, c.billing_hours_per_month
              INTO v_contract_client_id, v_contract_unit, v_contract_hours
              FROM contracts AS c
             WHERE c.id = v_target.contract_id;
            IF NOT FOUND OR v_contract_client_id IS DISTINCT FROM v_client_id THEN
                v_reason := 'contract_client_mismatch';
            ELSIF v_order.status::text <> 'active'
               OR v_order.start_date IS DISTINCT FROM v_new_start
               OR v_order.end_date IS DISTINCT FROM v_new_end THEN
                v_reason := 'state_changed';
                v_reason_detail := jsonb_build_object(
                    'status', v_order.status::text,
                    'start_date', v_order.start_date,
                    'end_date', v_order.end_date
                );
            ELSIF v_order.order_group_id IS NOT NULL
               OR v_order.md_total IS NOT NULL THEN
                -- Budżet MD/linia grupy: przeniesienie zużycia wymagałoby
                -- przeliczenia budżetu — poza zakresem tej korekty.
                v_reason := 'group_line_or_md_budget';
            END IF;
        END IF;

        -- ── Activity nadpisania: dokładnie jedna, z dokumentem i datą 31.08 ──
        IF v_reason IS NULL THEN
            SELECT count(*) INTO v_count
              FROM activities
             WHERE entity_type = 'client_order'
               AND entity_id = v_order.id
               AND action = 'order_mail_reactivate';
            IF v_count = 0 THEN
                v_reason := 'reactivate_activity_missing';
            ELSIF v_count > 1 THEN
                v_reason := 'reactivate_activity_ambiguous';
            ELSE
                SELECT * INTO v_activity
                  FROM activities
                 WHERE entity_type = 'client_order'
                   AND entity_id = v_order.id
                   AND action = 'order_mail_reactivate';
                v_before := v_activity.details -> 'before';
                IF v_activity.details ->> 'document_id'
                       IS DISTINCT FROM v_target.document_id::text
                   OR jsonb_typeof(v_before) IS DISTINCT FROM 'object'
                   OR v_before ->> 'end_date'
                       IS DISTINCT FROM to_char(v_previous_end, 'YYYY-MM-DD')
                   OR v_activity.created_at < v_window_start
                   OR v_activity.created_at >= v_window_end THEN
                    v_reason := 'reactivate_activity_mismatch';
                END IF;
            END IF;
        END IF;

        -- ── Stan sprzed nadpisania musi dać się odczytać bez zgadywania ──────
        IF v_reason IS NULL THEN
            -- Pusty tytuł odrzucamy po przycięciu, ale przywracamy dosłownie.
            v_before_title_raw := v_before ->> 'title';
            v_before_title := nullif(btrim(v_before_title_raw), '');
            v_text := v_before ->> 'start_date';
            IF v_before_title IS NULL THEN
                v_reason := 'before_title_missing';
            ELSIF NOT (v_before ? 'file_path') THEN
                v_reason := 'before_file_path_missing';
            ELSIF v_text IS NOT NULL
              AND v_text NOT IN ('None', '')
              AND v_text !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
                v_reason := 'before_start_unparseable';
            ELSE
                v_before_start := CASE
                    WHEN v_text IS NULL OR v_text IN ('None', '') THEN NULL
                    ELSE v_text::date
                END;
                v_before_file := nullif(v_before ->> 'file_path', '');
                v_text := v_before ->> 'rate_client';
                IF v_text IS NULL OR v_text IN ('None', '') THEN
                    v_before_rate := NULL;
                ELSIF v_text ~ '^[0-9]+(\.[0-9]+)?$' THEN
                    v_before_rate := v_text::numeric;
                ELSE
                    v_reason := 'before_rate_unparseable';
                END IF;
                IF v_reason IS NULL
                   AND v_before_start IS NOT NULL
                   AND v_before_start > v_previous_end THEN
                    v_reason := 'before_period_invalid';
                END IF;
            END IF;
        END IF;

        -- ── Dokument z maila zapisał TO zamówienie ─────────────────────────────
        IF v_reason IS NULL THEN
            SELECT * INTO v_document
              FROM order_mail_documents
             WHERE id = v_target.document_id
               FOR UPDATE;
            IF NOT FOUND OR v_document.client_id IS DISTINCT FROM v_client_id THEN
                v_reason := 'document_missing';
            END IF;
            v_applied_rows := v_document.proposal -> 'apply_result' -> 'rows';
            IF v_reason IS NOT NULL THEN
                NULL;
            ELSIF jsonb_typeof(v_applied_rows) IS DISTINCT FROM 'array'
               OR NOT EXISTS (
                   SELECT 1
                     FROM jsonb_array_elements(v_applied_rows) AS r(value)
                    WHERE r.value ->> 'order_id' = v_order.id::text
               ) THEN
                v_reason := 'document_not_applied_to_order';
            ELSIF jsonb_typeof(v_document.proposal -> 'rows') IS DISTINCT FROM 'array' THEN
                v_reason := 'document_plan_mismatch';
            ELSE
                -- Wiersz planu, który zapisał TO zamówienie: musi być powrotem
                -- po przerwie z tego zamówienia na nowy okres. Z niego też
                -- bierze się wartość całkowita nowego okresu.
                v_row_index := (
                    SELECT r.value ->> 'row_index'
                      FROM jsonb_array_elements(v_applied_rows) AS r(value)
                     WHERE r.value ->> 'order_id' = v_order.id::text
                     LIMIT 1
                );
                v_plan_row := (
                    SELECT p.value
                      FROM jsonb_array_elements(v_document.proposal -> 'rows') AS p(value)
                     WHERE p.value ->> 'row_index' IS NOT DISTINCT FROM v_row_index
                     LIMIT 1
                );
                IF v_plan_row IS NULL
                   OR v_plan_row ->> 'action' IS DISTINCT FROM 'reactivate'
                   OR v_plan_row ->> 'target_order_id' IS DISTINCT FROM v_order.id::text
                   OR v_plan_row ->> 'start_date'
                       IS DISTINCT FROM to_char(v_new_start, 'YYYY-MM-DD') THEN
                    v_reason := 'document_plan_mismatch';
                END IF;
            END IF;
        END IF;

        -- ── Nikt nie założył już zamówienia na nowy okres tej osoby ────────────
        IF v_reason IS NULL
           AND EXISTS (
               SELECT 1
                 FROM client_orders AS o2
                WHERE o2.contract_id = v_order.contract_id
                  AND o2.id <> v_order.id
                  AND (o2.start_date IS NULL OR o2.start_date <= v_new_end)
                  AND (
                      (
                          o2.status::text IN ('draft', 'active', 'paused')
                          AND (o2.end_date IS NULL OR o2.end_date >= v_new_start)
                      )
                      OR (
                          o2.status::text = 'completed'
                          AND o2.end_date >= v_new_start
                      )
                  )
           ) THEN
            v_reason := 'another_order_covers_new_period';
        END IF;

        -- ── …ani na okres, który przywracamy (ktoś go odtworzył ręcznie) ──────
        -- Zamówienie założone PO nadpisaniu na stary okres = przywrócenie
        -- oryginału policzyłoby ten okres dwa razy. Starsze zamówienia są
        -- historią, która istniała obok oryginału — nie przeszkadzają.
        IF v_reason IS NULL
           AND EXISTS (
               SELECT 1
                 FROM client_orders AS o4
                WHERE o4.contract_id = v_order.contract_id
                  AND o4.id <> v_order.id
                  AND o4.status::text <> 'cancelled'
                  AND o4.created_at >= v_activity.created_at
                  AND (o4.start_date IS NULL OR o4.start_date <= v_previous_end)
                  AND (
                      o4.end_date IS NULL
                      OR v_before_start IS NULL
                      OR o4.end_date >= v_before_start
                  )
           ) THEN
            v_reason := 'another_order_covers_previous_period';
        END IF;

        -- ── Jednostka stawki: ``before`` jej nie niesie ────────────────────────
        -- Writer przestawiał ``rate_unit`` na jednostkę z PDF-a. Stawka
        -- przywrócona pod cudzą jednostką to cichy błąd 8×/22×/160×, więc
        -- rząd wielkości obu stawek musi się zgadzać; inaczej człowiek.
        -- Bez bieżącej stawki nie ma czym tego sprawdzić — też człowiek.
        IF v_reason IS NULL
           AND v_before_rate IS NOT NULL
           AND (v_order.rate_client IS NULL OR v_order.rate_client <= 0) THEN
            v_reason := 'rate_unit_unverifiable';
            v_reason_detail := jsonb_build_object(
                'before_rate_client', v_before_rate,
                'current_rate_client', v_order.rate_client,
                'current_rate_unit', v_order.rate_unit::text
            );
        ELSIF v_reason IS NULL
           AND v_before_rate IS NOT NULL
           AND (
               v_before_rate / v_order.rate_client < 0.5
               OR v_before_rate / v_order.rate_client > 2
           ) THEN
            v_reason := 'rate_unit_change_suspected';
            v_reason_detail := jsonb_build_object(
                'before_rate_client', v_before_rate,
                'current_rate_client', v_order.rate_client,
                'current_rate_unit', v_order.rate_unit::text
            );
        END IF;

        -- ── Klucz obcy, którego blok nie zna, a który wskazuje zamówienie ─────
        IF v_reason IS NULL THEN
            v_reason_detail := '[]'::jsonb;
            FOR v_fk IN
                SELECT c.conrelid::regclass AS rel, a.attname::text AS col
                  FROM pg_constraint AS c
                  JOIN pg_attribute AS a
                    ON a.attrelid = c.conrelid
                   AND a.attnum = c.conkey[1]
                 WHERE c.contype = 'f'
                   AND c.confrelid = 'client_orders'::regclass
                   AND (c.conrelid::regclass::text, a.attname::text)
                       NOT IN (__HANDLED_FKS__)
            LOOP
                EXECUTE format('SELECT count(*) FROM %s WHERE %I = $1', v_fk.rel, v_fk.col)
                   INTO v_count
                  USING v_order.id;
                IF v_count > 0 THEN
                    v_reason_detail := v_reason_detail || jsonb_build_array(
                        jsonb_build_object(
                            'table', v_fk.rel::text,
                            'column', v_fk.col,
                            'rows', v_count
                        )
                    );
                END IF;
            END LOOP;
            IF jsonb_array_length(v_reason_detail) > 0 THEN
                v_reason := 'unknown_foreign_key_reference';
            ELSE
                v_reason_detail := NULL;
            END IF;
        END IF;

        IF v_reason IS NOT NULL THEN
            v_skipped_count := v_skipped_count + 1;
            v_results := v_results || jsonb_build_array(
                jsonb_build_object(
                    'order_id', v_target.order_id,
                    'contract_id', v_target.contract_id,
                    'document_id', v_target.document_id,
                    'status', 'skipped',
                    'reason', v_reason,
                    'detail', v_reason_detail
                )
            );
            CONTINUE;
        END IF;

        -- ── Wyliczenia przed zapisem ───────────────────────────────────────────
        -- Notatki: writer dopisał dokładnie ``details.message`` po znaku nowej
        -- linii (albo w miejsce pustych notatek — pusty napis i NULL są wtedy
        -- nie do odróżnienia, wraca NULL).
        v_message := nullif(v_activity.details ->> 'message', '');
        v_notes_restorable := false;
        v_restored_notes := v_order.notes;
        IF v_message IS NOT NULL AND v_order.notes = v_message THEN
            v_notes_restorable := true;
            v_restored_notes := NULL;
        ELSIF v_message IS NOT NULL
          AND length(v_order.notes) > length(v_message) + 1
          AND right(v_order.notes, length(v_message) + 1) = chr(10) || v_message THEN
            v_notes_restorable := true;
            v_restored_notes := left(
                v_order.notes, length(v_order.notes) - length(v_message) - 1
            );
        END IF;

        -- Koszt oryginału: harmonogram umowy na OSTATNI dzień starego okresu —
        -- ``cost_reference_day`` zamówienia zakończonego, ten sam dzień czyta
        -- raport zgodności (resolver ``Contract._resolve_scheduled_rate``).
        -- Jednostka jak ``convert_rate_between``: 1 MD = 8 h, 1 mc = 22 MD,
        -- h ↔ mc po godzinach strony miesięcznej. Bieżący koszt nigdy nie
        -- wraca do oryginału: to koszt NOWEGO okresu.
        v_schedule_rate := NULL;
        IF EXISTS (
            SELECT 1 FROM contract_candidate_rates
             WHERE contract_id = v_order.contract_id
        ) THEN
            SELECT r.rate INTO v_schedule_rate
              FROM contract_candidate_rates AS r
             WHERE r.contract_id = v_order.contract_id
               AND r.effective_from <= v_previous_end
             ORDER BY r.effective_from DESC, r.id DESC
             LIMIT 1;
            IF v_schedule_rate IS NULL THEN
                SELECT r.rate INTO v_schedule_rate
                  FROM contract_candidate_rates AS r
                 WHERE r.contract_id = v_order.contract_id
                 ORDER BY r.effective_from ASC, r.id DESC
                 LIMIT 1;
            END IF;
            v_cost_source := 'contract_schedule_on_previous_last_day';
        ELSE
            SELECT c.rate_candidate INTO v_schedule_rate
              FROM contracts AS c
             WHERE c.id = v_order.contract_id;
            v_cost_source := 'contract_column';
        END IF;
        v_contract_hours := coalesce(nullif(v_contract_hours, 0), 160);
        v_order_hours := coalesce(nullif(v_order.billing_hours_per_month, 0), 160);
        v_restored_cost := round(
            CASE
                WHEN v_schedule_rate IS NULL OR v_contract_unit IS NULL THEN NULL
                WHEN v_contract_unit = v_order.rate_unit::text THEN v_schedule_rate
                WHEN v_contract_unit = 'hourly' AND v_order.rate_unit::text = 'daily'
                    THEN v_schedule_rate * 8
                WHEN v_contract_unit = 'daily' AND v_order.rate_unit::text = 'hourly'
                    THEN v_schedule_rate / 8
                WHEN v_contract_unit = 'daily' AND v_order.rate_unit::text = 'monthly'
                    THEN v_schedule_rate * 22
                WHEN v_contract_unit = 'monthly' AND v_order.rate_unit::text = 'daily'
                    THEN v_schedule_rate / 22
                WHEN v_contract_unit = 'hourly' AND v_order.rate_unit::text = 'monthly'
                    THEN v_schedule_rate * v_order_hours
                WHEN v_contract_unit = 'monthly' AND v_order.rate_unit::text = 'hourly'
                    THEN v_schedule_rate / v_contract_hours
            END,
            3
        );
        IF v_restored_cost IS NULL THEN
            v_cost_source := 'contract_has_no_cost_left_empty';
        END IF;

        -- Wartość całkowita: writer jej nie ruszał, więc bieżąca kolumna należy
        -- do POPRZEDNIEGO zamówienia i zostaje przy nim. Nowy okres dostaje
        -- wartość z przypiętego wiersza planu (jak nowe zamówienie
        -- w poprawionym writerze) — w razie wątpliwości pustą, nigdy starą:
        -- stara zdublowałaby przychód w sumach ``total_value``.
        v_text := v_plan_row ->> 'total_value';
        IF v_text IS NULL OR v_text IN ('', 'None') THEN
            v_new_total := NULL;
            v_total_source := 'plan_without_total_value';
        ELSIF v_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN
            v_new_total := v_text::numeric;
            v_total_source := 'plan';
        ELSE
            v_new_total := NULL;
            v_total_source := 'plan_unparseable_left_empty';
        END IF;

        -- Pierwsza aktywacja: ``_activate_complete_draft`` stempluje ją tylko
        -- wtedy, gdy jest pusta. Stempel z T0 lub później należy do nowego
        -- okresu (oryginał miał wtedy NULL); wcześniejszy — do oryginału,
        -- a nowy okres aktywował writer w T0.
        IF v_order.filled_at IS NULL THEN
            v_new_filled := NULL;
            v_restored_filled := NULL;
        ELSIF v_order.filled_at >= v_activity.created_at THEN
            v_new_filled := v_order.filled_at;
            v_restored_filled := NULL;
        ELSE
            v_new_filled := v_activity.created_at;
            v_restored_filled := v_order.filled_at;
        END IF;

        -- PDF: ścieżka sprzed nadpisania wraca do oryginału (writer nie kasował
        -- zastąpionego pliku). Metadane poza ścieżką nie są w ``before`` —
        -- nazwa z nazwy pliku na dysku, reszta pusta. Wgranie albo usunięcie
        -- PDF-u w aplikacji po T0 mogło skasować właśnie ten plik z dysku
        -- (zastąpiony blob jest zwalniany po zapisie), więc wtedy nie
        -- podpinamy ścieżki — zostaje w paragonie do sprawdzenia.
        v_file_changed := EXISTS (
            SELECT 1
              FROM activities
             WHERE entity_type = 'client'
               AND entity_id = v_order.client_id
               AND action IN ('order_file_uploaded', 'order_file_deleted')
               AND details ->> 'order_id' = v_order.id::text
               AND created_at >= v_activity.created_at
        );
        IF v_before_file IS NULL THEN
            v_file_mode := 'previous_order_had_no_file';
        ELSIF v_file_changed THEN
            v_file_mode := 'previous_file_uncertain_after_file_change';
        ELSIF v_before_file IS NOT DISTINCT FROM v_order.file_path THEN
            v_file_mode := 'writer_did_not_replace_file';
        ELSE
            v_file_mode := 'previous_file_restored';
        END IF;
        -- Ten sam plik w obu wierszach = skasowanie go w jednym osierociłoby
        -- drugi. Plik sprzed nadpisania należy do oryginału.
        v_new_row_drops_file := v_before_file IS NOT NULL
            AND v_order.file_path IS NOT DISTINCT FROM v_before_file;
        SELECT coalesce(jsonb_agg(o3.id ORDER BY o3.id), '[]'::jsonb)
          INTO v_shared_file
          FROM client_orders AS o3
         WHERE v_before_file IS NOT NULL
           AND o3.file_path = v_before_file
           AND o3.id <> v_order.id;
        -- Inne dokumenty z maila wskazujące to zamówienie po T0 mogły dotyczyć
        -- STAREGO okresu (ten sam bieg czyszczenia) — nie przepinamy ich,
        -- tylko wypisujemy do przeglądu.
        SELECT coalesce(jsonb_agg(d2.id ORDER BY d2.id), '[]'::jsonb)
          INTO v_other_documents
          FROM order_mail_documents AS d2
         WHERE d2.id <> v_target.document_id
           AND coalesce(d2.applied_at, d2.created_at) >= v_activity.created_at
           AND (
               d2.applied_order_id = v_order.id
               OR (
                   jsonb_typeof(d2.proposal -> 'apply_result' -> 'rows') = 'array'
                   AND EXISTS (
                       SELECT 1
                         FROM jsonb_array_elements(d2.proposal -> 'apply_result' -> 'rows')
                              AS e3(value)
                        WHERE e3.value ->> 'order_id' = v_order.id::text
                   )
               )
           );

        -- ── a. Nowy wiersz = bieżący stan zamówienia ───────────────────────────
        EXECUTE format(
            'INSERT INTO client_orders (%s) SELECT %s FROM client_orders WHERE id = $1 RETURNING id',
            v_copy_columns,
            v_copy_columns
        )
           INTO v_new_id
          USING v_order.id;

        UPDATE client_orders
           SET created_at = v_activity.created_at,
               updated_at = now(),
               created_by_user_id = v_activity.user_id,
               notes = CASE
                   WHEN v_notes_restorable
                       THEN 'Zamówienie z maila (dokument #' || v_target.document_id || ')'
                   ELSE v_order.notes
               END,
               total_value = v_new_total,
               filled_at = v_new_filled,
               -- PDF nowego okresu nie został dołączony: nie dzielimy pliku
               -- oryginału (skasowanie go w jednym wierszu osierociłoby drugi).
               filename = CASE WHEN v_new_row_drops_file THEN NULL ELSE filename END,
               file_path = CASE WHEN v_new_row_drops_file THEN NULL ELSE file_path END,
               content_type = CASE WHEN v_new_row_drops_file THEN NULL ELSE content_type END,
               size_bytes = CASE WHEN v_new_row_drops_file THEN NULL ELSE size_bytes END,
               file_uploaded_by = CASE WHEN v_new_row_drops_file THEN NULL ELSE file_uploaded_by END,
               file_uploaded_at = CASE WHEN v_new_row_drops_file THEN NULL ELSE file_uploaded_at END
         WHERE id = v_new_id;

        -- ── b. Oryginał wraca do stanu sprzed nadpisania ───────────────────────
        UPDATE client_orders
           SET status = 'completed',
               title = v_before_title_raw,
               start_date = v_before_start,
               end_date = v_previous_end,
               rate_client = v_before_rate,
               rate_candidate = v_restored_cost,
               notes = v_restored_notes,
               filled_at = v_restored_filled,
               filename = CASE v_file_mode
                   WHEN 'previous_file_restored' THEN regexp_replace(
                       substring(v_before_file from '([^/]+)$'),
                       '^[0-9a-f]{8}-',
                       ''
                   )
                   WHEN 'writer_did_not_replace_file' THEN filename
               END,
               file_path = CASE v_file_mode
                   WHEN 'previous_file_restored' THEN v_before_file
                   WHEN 'writer_did_not_replace_file' THEN file_path
               END,
               content_type = CASE v_file_mode
                   WHEN 'previous_file_restored' THEN CASE
                       WHEN v_before_file ILIKE '%.pdf' THEN 'application/pdf'
                   END
                   WHEN 'writer_did_not_replace_file' THEN content_type
               END,
               size_bytes = CASE
                   WHEN v_file_mode = 'writer_did_not_replace_file' THEN size_bytes
               END,
               file_uploaded_by = CASE
                   WHEN v_file_mode = 'writer_did_not_replace_file' THEN file_uploaded_by
               END,
               file_uploaded_at = CASE
                   WHEN v_file_mode = 'writer_did_not_replace_file' THEN file_uploaded_at
               END,
               updated_at = now()
         WHERE id = v_order.id;

        -- ── c. Przypięty dokument z maila wskazuje nowy wiersz ─────────────────
        v_moved := '{}'::jsonb;
        UPDATE order_mail_documents AS d
           SET applied_order_id = CASE
                   WHEN d.applied_order_id = v_order.id THEN v_new_id
                   ELSE d.applied_order_id
               END,
               proposal = CASE
                   WHEN jsonb_typeof(d.proposal -> 'apply_result' -> 'rows') = 'array'
                   THEN jsonb_set(
                       d.proposal,
                       ARRAY['apply_result', 'rows'],
                       coalesce(
                           (
                               SELECT jsonb_agg(
                                          CASE
                                              WHEN e.value ->> 'order_id' = v_order.id::text
                                              THEN jsonb_set(e.value, ARRAY['order_id'], to_jsonb(v_new_id))
                                              ELSE e.value
                                          END
                                          ORDER BY e.ordinality
                                      )
                                 FROM jsonb_array_elements(d.proposal -> 'apply_result' -> 'rows')
                                      WITH ORDINALITY AS e(value, ordinality)
                           ),
                           '[]'::jsonb
                       )
                   )
                   ELSE d.proposal
               END
         WHERE d.id = v_target.document_id;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('order_mail_documents', v_count);

        -- ── d. Wiersze potomne nowego okresu (T0 lub później) ──────────────────
        -- Activity nadpisania zostaje przy oryginale: opisuje, co mu zrobiono.
        UPDATE activities
           SET entity_id = v_new_id
         WHERE entity_type = 'client_order'
           AND entity_id = v_order.id
           AND created_at >= v_activity.created_at
           AND id <> v_activity.id;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('activities_client_order', v_count);

        UPDATE activities
           SET details = jsonb_set(details, ARRAY['order_id'], to_jsonb(v_new_id))
         WHERE entity_type = 'client'
           AND entity_id = v_order.client_id
           AND details ->> 'order_id' = v_order.id::text
           AND created_at >= v_activity.created_at;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('activities_client_details', v_count);

        -- ``ix_notif_dedup_daily`` nie zawiera typu encji — kolizji z cudzym
        -- powiadomieniem o tym samym numerze nie przenosimy (liczba w paragonie).
        UPDATE notifications AS n
           SET related_entity_id = v_new_id
         WHERE n.related_entity_type = 'client_order'
           AND n.related_entity_id = v_order.id
           AND n.created_at >= v_activity.created_at
           AND NOT EXISTS (
               SELECT 1
                 FROM notifications AS x
                WHERE x.user_id = n.user_id
                  AND x.notification_type = n.notification_type
                  AND x.related_entity_id = v_new_id
                  AND date_trunc('day', x.created_at AT TIME ZONE 'Europe/Warsaw')
                      = date_trunc('day', n.created_at AT TIME ZONE 'Europe/Warsaw')
           );
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('notifications', v_count);

        -- Klucz sprawy w ``dedupe_key`` niesie id zamówienia — bez przepisania
        -- „obsłużone” przestałoby wyciszać sprawę nowego wiersza.
        UPDATE dl_alerts
           SET order_id = v_new_id,
               dedupe_key = left(
                   regexp_replace(
                       dedupe_key,
                       ':(order|mail-draft):' || v_order.id || ':',
                       ':\1:' || v_new_id || ':'
                   ),
                   255
               )
         WHERE order_id = v_order.id
           AND created_at >= v_activity.created_at;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('dl_alerts', v_count);

        UPDATE contract_client_rates
           SET source_order_id = v_new_id
         WHERE source_order_id = v_order.id
           AND created_at >= v_activity.created_at
           AND effective_from >= v_new_start;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('contract_client_rates', v_count);

        UPDATE client_order_md_consumptions
           SET order_id = v_new_id
         WHERE order_id = v_order.id
           AND created_at >= v_activity.created_at
           AND period_month >= v_new_month;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('client_order_md_consumptions', v_count);

        UPDATE client_order_invoice_consumptions
           SET order_id = v_new_id
         WHERE order_id = v_order.id
           AND created_at >= v_activity.created_at
           AND period_month >= v_new_month;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('client_order_invoice_consumptions', v_count);

        UPDATE md_consumption_import_rows AS r
           SET matched_order_id = CASE
                   WHEN r.matched_order_id = v_order.id THEN v_new_id
                   ELSE r.matched_order_id
               END,
               candidate_order_ids = CASE
                   WHEN jsonb_typeof(r.candidate_order_ids) = 'array' THEN coalesce(
                       (
                           SELECT jsonb_agg(
                                      CASE
                                          WHEN e.value = to_jsonb(v_order.id) THEN to_jsonb(v_new_id)
                                          ELSE e.value
                                      END
                                      ORDER BY e.ordinality
                                  )
                             FROM jsonb_array_elements(r.candidate_order_ids)
                                  WITH ORDINALITY AS e(value, ordinality)
                       ),
                       '[]'::jsonb
                   )
                   ELSE r.candidate_order_ids
               END
          FROM md_consumption_imports AS i
         WHERE i.id = r.import_id
           AND r.created_at >= v_activity.created_at
           AND i.period_month >= v_new_month
           AND (
               r.matched_order_id = v_order.id
               OR (
                   jsonb_typeof(r.candidate_order_ids) = 'array'
                   AND r.candidate_order_ids @> jsonb_build_array(v_order.id)
               )
           );
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('md_consumption_import_rows', v_count);

        UPDATE client_order_offboarding_cases
           SET order_id = v_new_id
         WHERE order_id = v_order.id
           AND created_at >= v_activity.created_at;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('client_order_offboarding_cases', v_count);

        UPDATE client_order_offboarding_cases
           SET target_order_id = v_new_id
         WHERE target_order_id = v_order.id
           AND created_at >= v_activity.created_at;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('client_order_offboarding_targets', v_count);

        UPDATE client_order_group_events
           SET order_id = v_new_id
         WHERE order_id = v_order.id
           AND created_at >= v_activity.created_at;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('client_order_group_events', v_count);

        UPDATE client_orders
           SET predecessor_order_id = v_new_id
         WHERE predecessor_order_id = v_order.id
           AND created_at >= v_activity.created_at
           AND id <> v_new_id;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_moved := v_moved || jsonb_build_object('client_orders_predecessor', v_count);

        -- Co zostało przy oryginale MIMO daty po T0 (miesiąc sprzed nowego
        -- okresu albo kolizja powiadomienia) — do przeglądu w paragonie.
        v_kept := jsonb_build_object(
            'md_consumptions_before_new_period', (
                SELECT count(*) FROM client_order_md_consumptions
                 WHERE order_id = v_order.id
                   AND created_at >= v_activity.created_at
            ),
            'invoice_consumptions_before_new_period', (
                SELECT count(*) FROM client_order_invoice_consumptions
                 WHERE order_id = v_order.id
                   AND created_at >= v_activity.created_at
            ),
            'notifications_colliding', (
                SELECT count(*) FROM notifications
                 WHERE related_entity_type = 'client_order'
                   AND related_entity_id = v_order.id
                   AND created_at >= v_activity.created_at
            ),
            'contract_activities_naming_order', (
                SELECT count(*) FROM activities
                 WHERE entity_type = 'contract'
                   AND entity_id = v_order.contract_id
                   AND created_at >= v_activity.created_at
                   AND (
                       details ->> 'source_order_id' = v_order.id::text
                       OR (
                           jsonb_typeof(details -> 'order_cost_synced') = 'array'
                           AND details -> 'order_cost_synced' @> jsonb_build_array(v_order.id)
                       )
                   )
            )
        );

        -- ── Ślad w historii obu wierszy ────────────────────────────────────────
        INSERT INTO activities (entity_type, entity_id, action, details)
        VALUES (
            'client_order',
            v_order.id,
            'order_mail_overwrite_reverted',
            jsonb_build_object(
                'source', v_marker,
                'document_id', v_target.document_id,
                'reverted_activity_id', v_activity.id,
                'split_to_order_id', v_new_id,
                'restored', jsonb_build_object(
                    'status', 'completed',
                    'title', v_before_title_raw,
                    'start_date', v_before_start,
                    'end_date', v_previous_end,
                    'rate_client', v_before_rate,
                    'rate_candidate', v_restored_cost,
                    'file_path', CASE v_file_mode
                        WHEN 'previous_file_restored' THEN v_before_file
                        WHEN 'writer_did_not_replace_file' THEN v_order.file_path
                    END
                ),
                'message',
                'Przywrócono stan sprzed nadpisania zamówieniem z maila (dokument #'
                    || v_target.document_id || '). Okres '
                    || to_char(v_new_start, 'DD.MM.YYYY') || '–'
                    || to_char(v_new_end, 'DD.MM.YYYY')
                    || ' przeniesiono do nowego zamówienia #' || v_new_id || '.'
            )
        );
        INSERT INTO activities (entity_type, entity_id, action, details)
        VALUES (
            'client_order',
            v_new_id,
            'order_mail_renewal',
            jsonb_build_object(
                'source', v_marker,
                'document_id', v_target.document_id,
                'renewal_of_order_id', v_order.id,
                'split_from_order_id', v_order.id,
                'previous_end_date', to_char(v_previous_end, 'YYYY-MM-DD'),
                'gap_days', v_new_start - v_previous_end,
                'message',
                'Powrót po ' || (v_new_start - v_previous_end)
                    || ' dniach od zakończenia poprzedniego zamówienia #' || v_order.id
                    || ' — nowe zamówienie wydzielone jednorazową korektą, poprzednie przywrócone'
            )
        );

        v_split_count := v_split_count + 1;
        v_results := v_results || jsonb_build_array(
            jsonb_build_object(
                'order_id', v_target.order_id,
                'contract_id', v_target.contract_id,
                'document_id', v_target.document_id,
                'status', 'split',
                'new_order_id', v_new_id,
                'incident_at', v_activity.created_at,
                'reverted_activity_id', v_activity.id,
                'restored_order', jsonb_build_object(
                    'title', v_before_title_raw,
                    'start_date', v_before_start,
                    'end_date', v_previous_end,
                    'rate_client', v_before_rate,
                    'rate_unit_kept', v_order.rate_unit::text,
                    'rate_candidate', v_restored_cost,
                    'rate_candidate_before_repair', v_order.rate_candidate,
                    'rate_candidate_source', v_cost_source,
                    'notes_restored', v_notes_restorable,
                    'filled_at', v_restored_filled,
                    'file_mode', v_file_mode,
                    'file_path', CASE v_file_mode
                        WHEN 'previous_file_restored' THEN v_before_file
                        WHEN 'writer_did_not_replace_file' THEN v_order.file_path
                    END,
                    'file_path_before_overwrite', v_before_file,
                    'file_path_also_on_orders', v_shared_file
                ),
                'new_order', jsonb_build_object(
                    'title', v_order.title,
                    'start_date', v_order.start_date,
                    'end_date', v_order.end_date,
                    'rate_client', v_order.rate_client,
                    'rate_candidate', v_order.rate_candidate,
                    'rate_unit', v_order.rate_unit::text,
                    'total_value', v_new_total,
                    'total_value_source', v_total_source,
                    'total_value_left_on_previous', v_order.total_value,
                    'filled_at', v_new_filled,
                    'file_path', CASE
                        WHEN v_new_row_drops_file THEN NULL
                        ELSE v_order.file_path
                    END
                ),
                'moved_to_new_order', v_moved,
                'kept_on_previous_order_after_incident', v_kept,
                'documents_left_for_review', v_other_documents,
                -- Krok przychodu dla przywróconego okresu dopisze synchronizacja
                -- kontrakt ↔ zamówienia przy najbliższym zapisie zamówienia.
                'contract_revenue_resync', 'pending_next_order_write'
            )
        );
    END LOOP;

    INSERT INTO app_settings (key, value)
    VALUES (
        v_marker,
        jsonb_build_object(
            'revision', v_marker,
            'completed_at', clock_timestamp(),
            'client_id', v_client_id,
            'new_period', jsonb_build_object('start', v_new_start, 'end', v_new_end),
            'previous_end', v_previous_end,
            'split', v_split_count,
            'skipped', v_skipped_count,
            'foreign_keys_to_client_orders', v_fk_inventory,
            'orders', v_results
        )
    )
    ON CONFLICT (key) DO NOTHING;

    RAISE NOTICE '0306 PFRON split % order(s), skipped %', v_split_count, v_skipped_count;
END
$pfron_renewal_split$;
"""


def _timestamptz_literal(moment: datetime) -> str:
    """``make_timestamptz`` zamiast literału z dwukropkami (``text()`` = bindy)."""
    utc = moment.astimezone(timezone.utc)
    return (
        f"make_timestamptz({utc.year}, {utc.month}, {utc.day}, "
        f"{utc.hour}, {utc.minute}, {utc.second}, 'UTC')"
    )


def build_renewal_split_sql(
    *,
    marker: str,
    client_id: int,
    targets: Sequence[SplitTarget],
    new_start: date,
    new_end: date,
    previous_end: date,
    incident_window: tuple[datetime, datetime],
) -> str:
    """Blok SQL dla podanych celów — produkcja i test używają tej samej treści.

    Wartości są liczbami i datami z kodu, nie wejściem użytkownika; marker
    przechodzi przez walidację, bo ląduje w literale SQL.
    """
    if not targets:
        raise ValueError("Brak zamówień do korekty")
    if not marker.replace("_", "").isalnum() or len(marker) > 100:
        raise ValueError("Marker musi być identyfikatorem (litery, cyfry, _)")
    values = ", ".join(
        f"({int(t.order_id)}, {int(t.contract_id)}, {int(t.document_id)})"
        for t in targets
    )
    handled = ", ".join(
        f"('{table}', '{column}')" for table, column in HANDLED_FOREIGN_KEYS
    )
    replacements = {
        "__MARKER__": marker,
        "__CLIENT_ID__": str(int(client_id)),
        "__NEW_START__": new_start.isoformat(),
        "__NEW_END__": new_end.isoformat(),
        "__PREVIOUS_END__": previous_end.isoformat(),
        "__WINDOW_START__": _timestamptz_literal(incident_window[0]),
        "__WINDOW_END__": _timestamptz_literal(incident_window[1]),
        "__TARGETS__": values,
        "__HANDLED_FKS__": handled,
    }
    sql = _TEMPLATE
    for token, value in replacements.items():
        sql = sql.replace(token, value)
    return sql


PFRON_RENEWAL_SPLIT_SQL = build_renewal_split_sql(
    marker=PFRON_RENEWAL_SPLIT_MARKER,
    client_id=PFRON_CLIENT_ID,
    targets=PFRON_TARGETS,
    new_start=NEW_PERIOD_START,
    new_end=NEW_PERIOD_END,
    previous_end=PREVIOUS_PERIOD_END,
    incident_window=INCIDENT_WINDOW,
)
