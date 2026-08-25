"""Korekta przypisania klienta: BNP Paribas Cardif → CARDIF - ASSURANCES…

Revision ID: 0244_cardif_client_reassignment
Revises: 0243_revive_contracts_with_live_orders

Korekta danych bez zmiany schematu. Dwa niezależne zgłoszenia tej samej
pomyłki (Marek Cyran, Maciej Rogala) wskazały, że w liście wyboru klienta stoją
obok siebie dwa rekordy o mylnie podobnych nazwach — ``BNP Paribas Cardif``
(id 52) i ``CARDIF - ASSURANCES RISQUES DIVERS SPÓŁKA AKCYJNA ODDZIAŁ
W POLSCE`` (id 38335) — a wybór sąsiada nie daje ŻADNEGO widocznego sygnału.

Wiersze do poprawienia ustalone raportem ``client-lookup`` na produkcji
(2026-08-25), nie zgadywane:

* kontrakt 521 (M. Rogala, oferta 280899) — client 52 → 38335
* kontrakt 551 (M. Cyran, oferta 64690) — client 52 → 38335
* umowa B2B 1474/2026 (Rogala, id 61) — client 52 → 38335
* umowa B2B 1438/2026 (Cyran, id 24) — client 52 → 38335

Trzy rzeczy, których ta migracja ŚWIADOMIE NIE ROBI:

1. **Nie kasuje ani nie unieważnia żadnego kontraktu.** Zgłoszenie prosiło
   o usunięcie „projektu BNP" Marka Cyrana i pozostawienie kontraktu 602 —
   ale dane mówią odwrotnie niż założenie zgłoszenia: to kontrakt 551 (ten
   „do usunięcia") niesie PODPISANĄ umowę 1438/2026 i realną ofertę, a 602 nie
   ma ani umowy, ani oferty. Wykonanie tego dosłownie osierociłoby podpisany
   dokument. Decyzja właściciela produktu (2026-08-25): najpierw sama korekta
   klienta, kasowanie później i świadomie, z interfejsu.

2. **Nie tyka ``render_payload``.** To zapis dokumentu podpisanego przez obie
   strony. 0242 rozstrzygnęła identyczny konflikt NA KORZYŚĆ dokumentu i ta
   reguła zostaje. Skutek do zaraportowania człowiekowi, nie do zamiecenia:
   umowa 1474/2026 nadal DRUKUJE „BNP Paribas Cardif", więc jej pola
   strukturalne będą się teraz różnić od treści dokumentu. Umowy 1438/2026 to
   nie dotyczy — tam dokument od początku drukuje CARDIF, więc korekta pola
   usuwa rozjazd, zamiast go tworzyć.

3. **Nie przemiata reszty bazy.** Zgłoszenie wprost żąda, by masowa korekta
   poczekała na weryfikację zespołu produktowego (raport:
   ``GET /api/admin/client-mixups``). Ruszamy wyłącznie cztery wskazane wiersze.

Zamówienia klienta jadą RAZEM z kontraktem: ``client_orders`` niesie własne
``client_id``, więc przepięcie samego kontraktu zostawiłoby zamówienie
wskazujące poprzedniego klienta — dokładnie tę „osieroconą" niespójność,
o której sprawdzenie prosiło zgłoszenie. Stan zweryfikowany na produkcji
(``client-lookup``, 2026-08-25): zamówienia 46 (kontrakt 521) i 78
(kontrakt 551) są w statusie ``draft`` i **nie należą do żadnej grupy**
(``order_group_id IS NULL``). To było warunkiem bezpieczeństwa tej korekty —
linia w grupie wielo-konsultantowej ma dodatkowe więzy po stronie
``client_order_groups``, których ta migracja nie rusza, więc przepięcie takiej
linii samej zrobiłoby nową niespójność zamiast usunąć starą.

Uwaga do kontekstu, gdyby ktoś wracał do pomysłu kasowania: kontrakt 602
(Cyran, właściwy klient) NIE jest pustym duplikatem — ma aktywne zamówienie
462 „Projekt DHS POL0208". Kontrakt 551 ma z kolei podpisaną umowę i ofertę,
ale zamówienie w szkicu. To wygląda na DWA RÓŻNE projekty tej samej osoby,
nie na jeden zdublowany wpis.

Na świeżej bazie (CI, nowe środowisko) tych wierszy nie ma i to jest stan
POPRAWNY — migracja nie może wtedy przerwać ``alembic upgrade heads``. Wyjątek
leci WYŁĄCZNIE wtedy, gdy wiersz istnieje, ale stoi w stanie, którego ta
korekta nie przewiduje (ani do naprawy, ani naprawiony).
"""

from alembic import op

revision = "0244_cardif_client_reassignment"
down_revision = "0243_revive_contracts_with_live_orders"
branch_labels = None
depends_on = None


_SQL = r"""
DO $cardif_fix$
DECLARE
    src_id   CONSTANT INTEGER := 52;
    dst_id   CONSTANT INTEGER := 38335;
    src_name TEXT;
    dst_name TEXT;
    moved_contracts BIGINT := 0;
    moved_orders    BIGINT := 0;
    moved_b2b       BIGINT := 0;
    stray           INTEGER;
BEGIN
    IF EXISTS (
        SELECT 1 FROM app_settings WHERE key = '0244_cardif_client_reassignment'
    ) THEN
        RETURN;
    END IF;

    SELECT name INTO src_name FROM clients WHERE id = src_id;
    SELECT name INTO dst_name FROM clients WHERE id = dst_id;

    -- Świeża baza: tych klientów po prostu nie ma. To NIE jest błąd.
    IF src_name IS NULL OR dst_name IS NULL THEN
        RAISE NOTICE '0244: klienci % / % nie istnieja — pomijam (swieza baza)', src_id, dst_id;
        INSERT INTO app_settings (key, value)
        VALUES ('0244_cardif_client_reassignment',
                jsonb_build_object('revision', '0244_cardif_client_reassignment',
                                   'completed_at', clock_timestamp(),
                                   'skipped', 'clients absent'))
        ON CONFLICT (key) DO NOTHING;
        RETURN;
    END IF;

    -- Identyfikatory sa ZAHARDKODOWANE, wiec nazwa jest kontrola, ze na tej
    -- bazie znacza to samo co na produkcji 2026-08-25. Bez tego migracja
    -- przepielaby przypadkowych klientow na innym srodowisku.
    IF position('cardif' in lower(src_name)) = 0
       OR position('cardif' in lower(dst_name)) = 0 THEN
        RAISE EXCEPTION
            '0244: klient % to "%" a % to "%" — to nie jest para BNP/CARDIF, przerywam',
            src_id, src_name, dst_id, dst_name;
    END IF;

    -- ── kontrakty 521 i 551 ────────────────────────────────────────────────
    -- Klucz biznesowy (nazwisko + oferta) obok id: id moze sie powtorzyc na
    -- innym srodowisku, para nazwisko+oferta juz nie.
    FOR stray IN
        SELECT c.id FROM contracts c
          JOIN candidates cand ON cand.id = c.candidate_id
         WHERE c.id IN (521, 551)
           AND c.client_id NOT IN (src_id, dst_id)
    LOOP
        RAISE EXCEPTION
            '0244: kontrakt % wskazuje klienta spoza pary BNP/CARDIF — przerywam', stray;
    END LOOP;

    -- RETURNING do tabeli tymczasowej, NIE ponowny SELECT po UPDATE. Gdyby
    -- ktorys kontrakt zostal recznie przepiety na dst_id przed ta migracja
    -- (realne przy takich zgloszeniach), UPDATE by go pominal, a SELECT
    -- „WHERE client_id = dst_id" i tak zapisalby dla niego wiersz audytu
    -- „old=52 new=38335" — czyli przypisalby tej migracji zmiane, ktorej nie
    -- zrobila. Audyt ma opisywac to, co sie NAPRAWDE wydarzylo.
    CREATE TEMP TABLE _moved_contracts ON COMMIT DROP AS
    WITH upd AS (
        UPDATE contracts SET client_id = dst_id
         WHERE id IN (521, 551) AND client_id = src_id
        RETURNING id
    )
    SELECT id FROM upd;
    GET DIAGNOSTICS moved_contracts = ROW_COUNT;

    -- ── zamowienia tych kontraktow ─────────────────────────────────────────
    -- Linia nalezaca do grupy wielo-konsultantowej ma wiezy po stronie
    -- `client_order_groups`, ktorych ta migracja NIE rusza — przepiecie samego
    -- zamowienia zrobiloby wtedy nowa niespojnosc zamiast usunac stara.
    -- Na produkcji sprawdzone (2026-08-25): zamowienia 46 i 78 maja
    -- `order_group_id IS NULL`. To sprawdzenie jest tu mimo to, bo miedzy
    -- weryfikacja a wdrozeniem ktos moze dolaczyc linie do grupy — a wtedy
    -- ZATRZYMANIE migracji jest wlasciwa odpowiedzia, mimo ze blokuje deploy.
    -- Warunek jest waski: na swiezej bazie tych zamowien nie ma w ogole.
    FOR stray IN
        SELECT co.id FROM client_orders co
         WHERE co.contract_id IN (521, 551)
           AND co.client_id = src_id
           AND co.order_group_id IS NOT NULL
    LOOP
        RAISE EXCEPTION
            '0244: zamowienie % nalezy do grupy — przepiecie samej linii '
            'zrobiloby niespojnosc z client_order_groups; przerywam', stray;
    END LOOP;

    UPDATE client_orders SET client_id = dst_id
     WHERE contract_id IN (521, 551) AND client_id = src_id;
    GET DIAGNOSTICS moved_orders = ROW_COUNT;

    -- ── umowy B2B 1474/2026 i 1438/2026 ────────────────────────────────────
    UPDATE b2b_generated_contracts
       SET client_id = dst_id,
           client_name = dst_name
     WHERE contract_number IN ('1474/2026', '1438/2026')
       AND client_id = src_id;
    GET DIAGNOSTICS moved_b2b = ROW_COUNT;

    -- Audyt per kontrakt: bez niego zmiana przypisania klienta jest niewidoczna
    -- na osi czasu, a to ona odpowiada za client-scope, MRR i alerty DL.
    INSERT INTO activities (entity_type, entity_id, action, details)
    SELECT 'contract', m.id, 'updated',
           jsonb_build_object('field', 'client_id',
                              'old', src_id, 'new', dst_id,
                              'source', '0244_cardif_client_reassignment')
      FROM _moved_contracts m;

    INSERT INTO app_settings (key, value)
    VALUES ('0244_cardif_client_reassignment',
            jsonb_build_object('revision', '0244_cardif_client_reassignment',
                               'completed_at', clock_timestamp(),
                               'source', 'alembic',
                               'moved_contracts', moved_contracts,
                               'moved_orders', moved_orders,
                               'moved_b2b', moved_b2b))
    ON CONFLICT (key) DO NOTHING;

    RAISE NOTICE '0244: kontrakty=% zamowienia=% umowyB2B=%',
        moved_contracts, moved_orders, moved_b2b;
END
$cardif_fix$;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    # Bez odwrotnosci: zejscie musialoby zgadnac, ktore wiersze wskazywaly
    # klienta 52 PRZED korekta, a przypisanie moglo sie w miedzyczasie zmienic
    # wlasnym obrotem. Slad zostaje w `activities` (source = 0244_...) oraz
    # w `app_settings` — odwrocenie robi sie z niego recznie i swiadomie.
    pass
