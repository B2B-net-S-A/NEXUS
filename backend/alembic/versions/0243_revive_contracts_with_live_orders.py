"""Wskrzeszenie kontraktów, pod którymi zamówienie JUŻ TRWA.

Revision ID: 0243_revive_contracts_with_live_orders
Revises: 0242_order_md_transfer_and_bp_bik_backfill

Korekta danych bez zmiany schematu. Domyka historię defektu naprawionego w tej
samej rewizji po stronie kodu: „Dodaj przedłużenie" tworzyło zamówienie pod
istniejącym kontraktem i NIE dotykało jego statusu. Aneks (``/amendments``)
i ``/bulk-extend`` przesuwały ``end_date`` i wołały ``reopen_contract``; trzecia
ścieżka przedłużania współpracy nie robiła ani jednego, ani drugiego.

Skutek zgłoszony przez użytkownika: przedłużenie dodane do kontraktora
z zakładki „Zakończeni" zostawiało go w „Zakończonych", mimo że okres nowego
zamówienia obejmuje dziś (przykład z ticketu: Mariusz Matyszczuk, Erste Bank
Polska S.A., zamówienie K/2026/197070/ŁO/477/26APP na 2026-07-01 → 2026-09-30).
Pigułka czyta ``contract_status``, więc dopóki kontrakt jest ``ended``, żadna
zmiana po stronie zamówień tego nie ruszy — i razem z pigułką milczą MRR,
rejestr umów oraz skaner wygasania.

Reguła jest OGÓLNA, nie punktowa: żadnych identyfikatorów w SQL-u. To świadome
odstępstwo od wzorca 0239/0242 (korekty wskazane po kluczach biznesowych),
bo tutaj naprawiamy KLASĘ wierszy powstałą z jednego defektu kodu, a nie trzy
znane pomyłki operatora. Konsekwencja: „zero dopasowań" jest tu poprawnym
wynikiem (świeża baza, CI), więc migracja go NIE traktuje jak błędu — nie ma
jednorazowej korekty, którą można by po cichu skonsumować.

Trzy rzeczy, których ta migracja NIE robi:

* nie rusza kontraktów ``draft``/``void`` — ``void`` jest terminalny
  (soft-delete zachowujący dokumenty i hashe podpisów), a szkic nie jest
  zakończoną współpracą, tylko niedokończonym wpisem;
* nie liczy zamówień ``draft``/``cancelled`` — szkic nie jest zobowiązaniem,
  a anulowane nie obowiązuje; żadne z nich nie dowodzi, że ktoś pracuje;
* nie wymyśla „Końca zamówienia u klienta" tam, gdzie go nie było
  (``client_order_end_date IS NULL`` zostaje NULL — lustro
  ``_synced_client_order_end``).

Przesunięcie ``end_date`` jest częścią korekty, nie kosmetyką: nocny
``_promote_statuses`` demotuje ``active`` z przeszłą datą końca z powrotem do
``ended``, więc sam status naprawiłby się na jedną noc i skasował następnej.
"""

from alembic import op

revision = "0243_revive_contracts_with_live_orders"
down_revision = "0242_order_md_transfer_and_bp_bik_backfill"
branch_labels = None
depends_on = None


# CTE liczy horyzont per kontrakt JEDNYM przebiegiem:
#   * `has_open_ended` — którekolwiek trwające zamówienie jest bezterminowe,
#     więc bezterminowy staje się też kontrakt (dosłownie to, co mówią dane);
#   * `max_end` — najdalsza data końca wśród trwających zamówień.
# `bool_or`/`max` po grupie, bo kontraktor bywa obsadzony na kilku zamówieniach
# naraz i wygrywa NAJDALSZE — węższe dałoby kontrakt kończący się przed
# zamówieniem, które sam obsługuje.
_REVIVE_SQL = r"""
DO $revive_contracts$
DECLARE
    revived_rows BIGINT := 0;
BEGIN
    IF EXISTS (
        SELECT 1 FROM app_settings
         WHERE key = '0243_revive_contracts_with_live_orders'
    ) THEN
        RETURN;
    END IF;

    CREATE TEMP TABLE _revive_targets ON COMMIT DROP AS
    SELECT c.id AS contract_id,
           -- Status SPRZED korekty — audyt ma nieść to, co naprawdę było.
           -- WHERE łapie `ended` ORAZ `ending`, więc wpisany na sztywno
           -- `from_status = 'ended'` kłamałby dla tych drugich, a wiersz
           -- audytu istnieje właśnie po to, żeby dało się odtworzyć przejście.
           c.status::text              AS previous_status,
           bool_or(o.end_date IS NULL) AS has_open_ended,
           max(o.end_date)             AS max_end
      FROM contracts AS c
      JOIN client_orders AS o
        ON o.contract_id = c.id
     WHERE c.status IN ('ended', 'ending')
       AND o.status NOT IN ('draft', 'cancelled')
       AND o.start_date IS NOT NULL
       AND o.start_date <= CURRENT_DATE
       AND (o.end_date IS NULL OR o.end_date >= CURRENT_DATE)
     GROUP BY c.id, c.status;

    UPDATE contracts AS c
       SET status = 'active',
           end_date = CASE
               WHEN t.has_open_ended THEN NULL
               WHEN c.end_date IS NULL THEN NULL
               WHEN t.max_end > c.end_date THEN t.max_end
               ELSE c.end_date
           END,
           -- „Koniec zamówienia u klienta" idzie za nowym horyzontem tylko
           -- wtedy, gdy kontrakt już go śledził (lustro
           -- `_synced_client_order_end`). NULL zostaje NULL-em.
           client_order_end_date = CASE
               WHEN c.client_order_end_date IS NULL THEN NULL
               WHEN t.has_open_ended THEN NULL
               WHEN t.max_end > c.client_order_end_date THEN t.max_end
               ELSE c.client_order_end_date
           END
      FROM _revive_targets AS t
     WHERE c.id = t.contract_id;
    GET DIAGNOSTICS revived_rows = ROW_COUNT;

    -- Audyt per kontrakt. Bez niego przejście najściślej powiązane
    -- z przychodem (konsultant wracający na `active`) byłoby jedynym bez
    -- śladu `from_status`/`to_status` w osi czasu — dokładnie ta luka, którą
    -- `reopen_contract` zamknęło dla pozostałych dwóch ścieżek przedłużania.
    INSERT INTO activities (entity_type, entity_id, action, details)
    SELECT 'contract',
           t.contract_id,
           'contract_reopened',
           jsonb_build_object(
               'from_status', t.previous_status,
               'to_status', 'active',
               'source', '0243_revive_contracts_with_live_orders'
           )
      FROM _revive_targets AS t;

    INSERT INTO app_settings (key, value)
    VALUES (
        '0243_revive_contracts_with_live_orders',
        jsonb_build_object(
            'revision', '0243_revive_contracts_with_live_orders',
            'completed_at', clock_timestamp(),
            'source', 'alembic',
            'revived_contracts', revived_rows
        )
    )
    ON CONFLICT (key) DO NOTHING;

    RAISE NOTICE '0243 revived % contract(s) with a currently running order',
        revived_rows;
END
$revive_contracts$;
"""


def upgrade() -> None:
    op.execute(_REVIVE_SQL)


def downgrade() -> None:
    # Świadomie bez odwrotności. Zejście w dół musiałoby zgadnąć, które
    # kontrakty były `ended` PRZED korektą, a wskrzeszenie mogło się w tym
    # czasie utrwalić własnym obrotem (aneks, kolejne zamówienie). Ślad, co
    # zmieniono, zostaje w `activities` (`source = 0243_...`) i w
    # `app_settings` — odwrócenie robi się z niego ręcznie i świadomie.
    pass
