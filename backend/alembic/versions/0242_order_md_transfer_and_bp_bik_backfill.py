"""Nowy typ zdarzenia ``transfer_md`` + trzy punktowe korekty danych (BP/BIK).

Revision ID: 0242_order_md_transfer_and_bp_bik_backfill
Revises: 0241_ai_spend_alert_state

Rewizja niesie DWIE różne rzeczy i to jest świadome: poszerzenie domeny
``ck_client_order_group_events_type`` MUSI wejść razem z kodem, który zaczyna
zapisywać wpisy ``transfer_md`` — inaczej pierwszy podział MD między zamówieniami
wywróci się IntegrityError-em w środku transakcji importu z Finansów.

Poszerzenie idzie przez DROP + ADD, nie przez ``EXCEPTION WHEN duplicate_object``.
Ten drugi wzorzec cicho nie robi nic, gdy więz o tej nazwie już istnieje ze starą,
węższą listą — czyli dokładnie w sytuacji, w której poszerzenie jest potrzebne
(precedens 0226 opisany w CLAUDE.md, guard w ``tests/test_order_lifecycle_migration.py``).

Korekty danych są punktowe, wskazane po kluczach biznesowych i wykonują się raz
(marker w ``app_settings``). Każde „zero dopasowań" jest ROZSTRZYGANE, a nie
przemilczane — 0239 powstała właśnie dlatego, że wcześniejsza wersja traktowała
zero trafień jak sukces i konsumowała jednorazową korektę, nic nie zmieniając.
Wzorzec: najpierw wąskie zapytanie o stan DO NAPRAWY, przy zerze drugie, jeszcze
węższe pytanie „czy to już jest naprawione" — i dopiero jego negatywna odpowiedź
przerywa migrację.

Trzy korekty:

1. **BIK, grupa 4500029903 (Michał Leśniak) → ``scheduled``.** Grupa ma poprawne
   ``predecessor_group_id`` (powstała przez „Dodaj przedłużenie"), ale status
   ``active``, więc ``list_order_groups`` renderuje ją jako RÓWNORZĘDNĄ kartę
   zamiast zagnieździć pod poprzednikiem — warunek zagnieżdżenia wymaga
   ``status == 'scheduled'``. Przyczyna: ``extend_order_group`` woła na końcu
   materializator, a data startu (2026-08-15) była już przeszła w dniu utworzenia
   (2026-08-21), więc następca został natychmiast promowany, a poprzednik domknięty.
   Linie wracają do ``draft`` w tej samej transakcji — grupa ``scheduled``
   z aktywnymi liniami to stan, którego reszta modułu zabrania, a materializator
   przy promocji i tak ustawia ``draft → active``.

2. **BIK, linia zamówienia 4500030067 (Michał Leśniak) → ``active``.** Linia jest
   ``completed`` mimo NIEWYCZERPANEGO budżetu MD (13,75 z 13,75). Domknął ją
   materializator przy promocji następcy; operator potem przywrócił samą GRUPĘ
   (``reopen`` świadomie nie rusza linii), więc linia została zamknięta. Po tej
   rewizji o zamknięciu linii MD decyduje wyłącznie wyczerpanie MD, więc ten
   wiersz jest wprost sprzeczny z nową regułą.

3. **Umowa B2B 1476/2026 (Wojciech Sokolnicki) → kontrakt Banku Pocztowego.**
   Wiersz wskazuje projekt Energa (``contract_id`` 560, ``client_id`` 41,
   ``job_id`` 115931), a dokument drukuje stronę „Bank Pocztowy S.A.".
   Dziennik ``b2b_generated_contract_status_events`` jest dla tej umowy PUSTY,
   więc nie jest to znany rozjazd po reaktywacji — to błędny wybór oferty przy
   generowaniu. Rozstrzygnięcie na korzyść dokumentu (decyzja właściciela
   produktu): to dokument jest podpisany przez obie strony, a pola strukturalne
   są tylko jego opisem. Przepięcie odblokowuje usunięcie pustego projektu Energa
   i JEDNOCZEŚNIE obejmuje ochroną projekt, którego umowa naprawdę dotyczy —
   dotąd Bank Pocztowy nie był chroniony wcale.

Projektu Energa ta migracja **nie usuwa**. Kasowanie kontraktu ciągnie kaskadę
(dokumenty, aneksy, harmonogramy, faktury, linie zamówień) i jest nieodwracalne;
po przepięciu umowy operator robi to z interfejsu jednym kliknięciem, widząc,
co usuwa.
"""

from alembic import op

revision = "0242_order_md_transfer_and_bp_bik_backfill"
down_revision = "0241_ai_spend_alert_state"
branch_labels = None
depends_on = None


_EVENT_TYPES = (
    "'utworzenie', 'dodanie_konsultanta', 'import_md', "
    "'zamiana_kontraktora', 'edycja_reczna', 'zakonczenie', "
    "'przywrocenie', 'wyczerpanie', 'przedluzenie', 'import_faktur', "
    "'transfer_md'"
)

# Dwie OSOBNE instrukcje, nie jedna rozdzielona średnikiem: `op.execute` idzie
# przez asyncpg, a ten przygotowuje każdą instrukcję (`PostgresSyntaxError:
# cannot insert multiple commands into a prepared statement`). Sklejony DROP+ADD
# wywraca całą migrację, więc CHECK zostaje w wąskiej wersji z 0233.
_DROP_EVENT_CHECK = (
    "ALTER TABLE client_order_group_events "
    "DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type"
)

_ADD_EVENT_CHECK = (
    "ALTER TABLE client_order_group_events "
    "ADD CONSTRAINT ck_client_order_group_events_type "
    f"CHECK (event_type IN ({_EVENT_TYPES}))"
)

_BACKFILL_SQL = r"""
DO $bp_bik_backfill$
DECLARE
    scheduled_group_id INTEGER;
    scheduled_group_count BIGINT := 0;
    scheduled_line_rows BIGINT := 0;
    reactivated_line_rows BIGINT := 0;
    md_line_id INTEGER;
    generated_rows BIGINT := 0;
    target_contract_id INTEGER;
    probe_id INTEGER;
BEGIN
    IF EXISTS (
        SELECT 1 FROM app_settings
         WHERE key = '0242_bp_bik_order_and_contract_backfill'
    ) THEN
        RETURN;
    END IF;

    -- ── 1. Grupa 4500029903 (BIK) → scheduled, linie → draft ──────────────
    SELECT count(*), max(g.id)
      INTO scheduled_group_count, scheduled_group_id
      FROM client_order_groups AS g
     WHERE g.client_id = 18
       AND g.order_number = '4500029903'
       AND g.status = 'active'
       AND g.predecessor_group_id IS NOT NULL;

    IF scheduled_group_count > 1 THEN
        RAISE EXCEPTION
            '0242 expected at most one active BIK group 4500029903 with a '
            'predecessor, found %', scheduled_group_count;
    END IF;

    IF scheduled_group_count = 0 THEN
        -- Rozróżnienie, którego 0239 uczy wprost: „nie ma czego poprawiać"
        -- to NIE to samo co „rozpoznaję cel, ale nie umiem go ruszyć".
        -- Na świeżej bazie (CI, nowe środowisko) tej grupy nie ma w ogóle
        -- i to jest stan całkowicie poprawny — wyjątek zablokowałby wtedy
        -- `alembic upgrade heads` każdemu, kto stawia projekt od zera.
        -- Przerywamy WYŁĄCZNIE wtedy, gdy grupa istnieje, ale stoi w stanie,
        -- którego ta korekta nie przewiduje (ani do naprawy, ani naprawiona).
        SELECT g.id INTO probe_id
          FROM client_order_groups AS g
         WHERE g.client_id = 18
           AND g.order_number = '4500029903'
           AND g.status <> 'scheduled'
         LIMIT 1;

        IF probe_id IS NOT NULL THEN
            RAISE EXCEPTION
                '0242 BIK order group 4500029903 (id %) exists but is neither '
                'active-with-predecessor nor already scheduled — the one-shot '
                'correction was NOT consumed; inspect the group before re-running',
                probe_id;
        END IF;
    END IF;

    IF scheduled_group_count = 1 THEN
        UPDATE client_order_groups
           SET status = 'scheduled',
               updated_at = now()
         WHERE id = scheduled_group_id;

        -- Lustro 0239: grupa `scheduled` z aktywnymi liniami to stan zabroniony
        -- w każdym innym miejscu modułu, a materializator przy promocji sam
        -- ustawia `draft → active` i stempluje `filled_at` właściwą datą.
        UPDATE client_orders
           SET status = 'draft'::clientorderstatus,
               filled_at = NULL,
               updated_at = now()
         WHERE order_group_id = scheduled_group_id
           AND status = 'active'::clientorderstatus;
        GET DIAGNOSTICS scheduled_line_rows = ROW_COUNT;
    END IF;

    -- ── 2. Linia 4500030067 (BIK) → active, bo MD nie są wyczerpane ───────
    SELECT o.id INTO md_line_id
      FROM client_orders AS o
      JOIN client_order_groups AS g ON g.id = o.order_group_id
     WHERE g.client_id = 18
       AND g.order_number = '4500030067'
       AND o.status = 'completed'::clientorderstatus
       AND o.md_total IS NOT NULL
       AND o.md_remaining > 0
     ORDER BY o.id
     LIMIT 1;

    IF md_line_id IS NULL THEN
        -- Jak wyżej: brak grupy = świeża baza, nie błąd. Przerywamy tylko
        -- wtedy, gdy grupa 4500030067 U KLIENTA ISTNIEJE, a mimo to nie ma
        -- w niej ani linii MD do wskrzeszenia, ani linii MD już aktywnej.
        SELECT g.id INTO probe_id
          FROM client_order_groups AS g
         WHERE g.client_id = 18
           AND g.order_number = '4500030067'
           AND NOT EXISTS (
               SELECT 1
                 FROM client_orders AS o
                WHERE o.order_group_id = g.id
                  AND o.md_total IS NOT NULL
                  AND o.status = 'active'::clientorderstatus
           )
         LIMIT 1;

        IF probe_id IS NOT NULL THEN
            RAISE EXCEPTION
                '0242 BIK order group 4500030067 (id %) exists but has no MD '
                'line that is either completed-with-budget-left or already '
                'active — the one-shot correction was NOT consumed',
                probe_id;
        END IF;
    ELSE
        UPDATE client_orders
           SET status = 'active'::clientorderstatus,
               updated_at = now()
         WHERE id = md_line_id;
        GET DIAGNOSTICS reactivated_line_rows = ROW_COUNT;
    END IF;

    -- ── 3. Umowa B2B 1476/2026 → kontrakt Banku Pocztowego ────────────────
    -- Kontrakt docelowy wyszukujemy po (kandydat, klient), a nie po samym id —
    -- id 600 pochodzi ze zrzutu produkcji, więc musi jeszcze zostać potwierdzone
    -- kandydatem i klientem, inaczej przepięlibyśmy podpisaną umowę na cudzy wiersz.
    SELECT c.id INTO target_contract_id
      FROM contracts AS c
     WHERE c.candidate_id = 154325
       AND c.client_id = 16
       AND c.status <> 'void'
     ORDER BY c.id
     LIMIT 1;

    IF target_contract_id IS NULL THEN
        -- Brak umowy 1476/2026 = świeża baza, milczymy. Ale jeśli ta konkretna
        -- podpisana umowa ISTNIEJE, a nie ma dokąd jej przepiąć, to jest
        -- rozpoznany cel, którego nie umiemy ruszyć — i o tym trzeba krzyknąć,
        -- bo cichy marker odbiera jedyną szansę na korektę.
        SELECT b.id INTO probe_id
          FROM b2b_generated_contracts AS b
         WHERE b.contract_number = '1476/2026'
           AND b.candidate_id = 154325
           AND b.signature_status = 'signed_both'
         LIMIT 1;

        IF probe_id IS NOT NULL THEN
            RAISE EXCEPTION
                '0242 signed B2B agreement 1476/2026 (id %) exists but there is '
                'no non-void Bank Pocztowy (client 16) contract for candidate '
                '154325 to repoint it to — the one-shot correction was NOT consumed',
                probe_id;
        END IF;
    ELSE
        UPDATE b2b_generated_contracts
           SET contract_id = target_contract_id,
               client_id = 16,
               job_id = (SELECT c.job_id FROM contracts AS c WHERE c.id = target_contract_id),
               updated_at = now()
         WHERE contract_number = '1476/2026'
           AND candidate_id = 154325
           AND signature_status = 'signed_both'
           AND contract_id IS DISTINCT FROM target_contract_id;
        GET DIAGNOSTICS generated_rows = ROW_COUNT;

        IF generated_rows = 0 THEN
            -- Zero zmienionych wierszy jest w porządku, gdy umowa już wskazuje
            -- właściwy kontrakt (powtórny bieg) albo gdy jej w ogóle nie ma
            -- (świeża baza). Krzyczymy tylko, gdy umowa ISTNIEJE i mimo to
            -- nie została przepięta — wtedy nie zgadza się któryś z warunków
            -- (kandydat, status podpisu) i korekta nie zrobiła tego, co miała.
            SELECT b.id INTO probe_id
              FROM b2b_generated_contracts AS b
             WHERE b.contract_number = '1476/2026'
               AND b.contract_id IS DISTINCT FROM target_contract_id
             LIMIT 1;

            IF probe_id IS NOT NULL THEN
                RAISE EXCEPTION
                    '0242 B2B agreement 1476/2026 (id %) exists but was not '
                    'repointed to contract % — check candidate_id and '
                    'signature_status; the one-shot correction was NOT consumed',
                    probe_id, target_contract_id;
            END IF;
        END IF;
    END IF;

    INSERT INTO app_settings (key, value)
    VALUES (
        '0242_bp_bik_order_and_contract_backfill',
        jsonb_build_object(
            'revision', '0242_order_md_transfer_and_bp_bik_backfill',
            'completed_at', clock_timestamp(),
            'source', 'alembic',
            'scheduled_group_rows', scheduled_group_count,
            'scheduled_line_rows', scheduled_line_rows,
            'reactivated_line_rows', reactivated_line_rows,
            'generated_contract_rows', generated_rows,
            'rollback', 'manual_only'
        )
    );
END
$bp_bik_backfill$;
"""


def upgrade() -> None:
    op.execute(_DROP_EVENT_CHECK)
    op.execute(_ADD_EVENT_CHECK)
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    # Domenę zwężamy dopiero po skasowaniu wpisów `transfer_md` — inaczej
    # `ADD CONSTRAINT` odbije się od własnych danych. Korekt danych NIE cofamy:
    # po nich materializator, import MD albo operator mogą już wykonać kolejne
    # prawidłowe zmiany, których automatyczny rollback nie odróżni od backfillu.
    op.execute("DELETE FROM client_order_group_events WHERE event_type = 'transfer_md'")
    op.execute(_DROP_EVENT_CHECK)
    op.execute(
        "ALTER TABLE client_order_group_events "
        "ADD CONSTRAINT ck_client_order_group_events_type "
        "CHECK (event_type IN ("
        "'utworzenie', 'dodanie_konsultanta', 'import_md', "
        "'zamiana_kontraktora', 'edycja_reczna', 'zakonczenie', "
        "'przywrocenie', 'wyczerpanie', 'przedluzenie', 'import_faktur'"
        "))"
    )
