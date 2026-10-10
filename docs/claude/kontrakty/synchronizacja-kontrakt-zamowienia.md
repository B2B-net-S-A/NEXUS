# Synchronizacja kontrakt ↔ zamówienia (09.2026, migracja 0304)

Zgłoszenie: kontrakt Bartosza Czapelki (Alior) stał jako „Szkic" (120 zł/h,
bez przychodu i okresu zamówienia), choć zamówienie OIT/0189/2026/ITVM miało
okres 15.09–31.12.2026 i 1340 PLN/MD. Serwis: `services/contract_order_sync.py`.
Każda strona jest źródłem prawdy dla SWOICH pól:

- **Jeden miesiąc roboczy: 168 h = 21 MD × 8 h (0345, decyzja Artura
  22.09.2026).** Każde przeliczenie stawki godzinowej/dziennej na miesiąc (MRR,
  marża, przychód, prognozy, analityka, UI) i między jednostkami czyta
  `app/core/work_time.py` (lustro `frontend/src/lib/work-time.ts`); gołe
  160/176/22 w modułach pieniędzy wywala `test_work_time_constant_guard.py`.
  `billing_hours_per_month` domyślnie 168 (kontrakt i zamówienie); jawnie inna
  liczba nadal wygrywa. Fakt „zamówienia tego kontraktu są w MD” niesie
  `contracts.orders_in_md` — `order_unit_for_contract` czyta kolumnę, nie
  godziny. Migracja 0345 (+ blok `repair-billing-hours-168` w entrypoincie,
  SQL w `services/billing_hours_unification.py`) jednorazowo przepisała
  160/176 → 168 w kontraktach i zamówieniach (paragon `0345_billing_hours_168`,
  same liczby). Zamówienie w innej jednostce czasu niż kontrakt (godzinowy
  kontrakt, miesięczne zamówienie) przelicza się przy najbliższej synchronizacji
  nowym miesiącem — kwota miesięczna po obu stronach zostaje zgodna.

- **Podpis obustronny w Generatorze B2B = kontrakt AKTYWNY od razu**
  (`confirm-fully-signed` → `contract_lifecycle.activate_without_revenue_gate`,
  `source="b2b_signed_agreement"`): start z umowy → bezterminowo, stawka
  kosztowa godzinowa z umowy. Bramka kompletności wymaga obu stawek, a
  przychodowa przychodzi dopiero z zamówienia — dlatego osobne przejście
  z DWOMA dozwolonymi źródłami (drugie: jednorazowa korekta). Wymaga daty startu.
  Rusza też `ready_for_signature` (podpis obustronny zamyka tor QES).
- **Zamówienie → kontrakt** (każdy zapis zamówienia): z najnowszego
  „uzupełnionego" zamówienia (status ≠ cancelled, jest `start_date` I dodatnia
  stawka przychodowa — auto-szkic z podpisu ma start umowy i PUSTĄ stawkę, więc
  nie udaje okresu) kontrakt dostaje **okres zamówienia** w OSOBNYCH polach
  `client_order_start_date`/`client_order_end_date` (nigdy `start_date`/
  `end_date`; kolejne zamówienie nadpisuje poprzednie) oraz **stawkę
  przychodową** jako krok `client_rate_schedule` od daty startu zamówienia
  (`source_order_id` — krok z zamówienia vs krok ręczny/z aneksu; przyszła
  stawka obowiązuje od swojej daty). **Jednostka kontraktu = jednostka
  najnowszego zamówienia, ALE NIGDY MD** (`contract_unit_for_order`, ticket
  „Ujednolicenie stawek w module Kontrakty", 14.09.2026): zamówienie w MD daje
  kontrakt w zł/h (MD ÷ 8), ryczałt i stawka godzinowa przechodzą bez zmian.
  Przełączenie przelicza KAŻDĄ kwotę kontraktu (obie stawki + harmonogramy,
  ramowa, widełki) z precyzją 6 miejsc (`CONTRACT_RATE_SCALE`, kolumny
  `NUMERIC(16,6)` od 0309 — 1001,55 zł/MD = 125,19375 zł/h; zamówienia zostają
  przy 3 miejscach). Zamówienie w MD oznacza kontrakt `orders_in_md = true`
  (od 0345; do 22.09.2026 ten fakt niosła liczba 176 h/mc), a godziny zostają
  168: czytniki pieniędzy liczą MD × 21, a godziny × `billing_hours_per_month`,
  więc MRR/marża miesięczna są takie jak przy dawnym kontrakcie w MD. Jawnie
  wybrana jednostka w PATCH (`follow_order_unit=False`) zostawia też godziny.
  **Zamówienie nie jest ruszane** — zostaje w MD, koszt wraca do niego ×8 bez
  zmiany kwoty. Wszystkie inne zapisy kontraktu też nie dają MD
  (`apply_contract_hourly_policy`): POST `/api/contracts`, `contract-with-order`
  i szkic z maila przeliczają kontrakt podany w MD; PATCH/aneks przejścia NA MD
  odmawiają 422 (`contract_rates_are_hourly`), a zapis kontraktu wciąż w MD
  przelicza go w całości. Formularze Kontraktów nie mają opcji „Dziennie".
  Jednorazowo `contract_hourly_rate_repair.py` (blok w `entrypoint.sh`, marker
  `0309_contract_hourly_rates`): każdy kontrakt `daily` → zł/h + 176 h/mc (od 0345: 168 h + `orders_in_md`),
  kontrola odwrotności (×8 == dawna kwota) i miesięcznego ekwiwalentu, suma
  kontrolna `client_orders` przed/po (różnica = rollback); czeka na poszerzone
  kolumny, bez nich nie stawia markera. DDL 0309 zdejmuje i zakłada ponownie
  trigger walut `trg_contract_rate_currencies_legacy_sync` (ma `margin`
  w `UPDATE OF`, Postgres inaczej odmawia zmiany typu).
  Szkic z kompletem danych przechodzi na `active` przez zwykłą bramkę
  (`auto_activate_complete_draft`) — ale nie szkic, którego `end_date` minęło.
- **Kontrakt → zamówienie: stawka kosztowa.** Kontrakt jest JEDYNYM źródłem:
  ręczny koszt w zamówieniu przegrywa przy zapisie (UI: pole tylko do odczytu,
  „z kontraktu", gdy kontrakt ma stawkę). Zamówienie niesie jedną liczbę, więc
  dostaje stawkę z harmonogramu na „dziś przycięte do okresu zamówienia"
  (`cost_reference_day`), a przebieg dobowy (`run_daily_order_cost_sync` w cyklu
  `contract_alerts`) wprowadza każdą zaplanowaną podwyżkę w jej dniu. Zakończone
  i anulowane zamówienia są historią — nietknięte.
- **Linie zamówień zbiorczych MD/kosztowych (`order_group_id`) są POZA
  kierunkiem kosztowym — świadomie.** Ich stawkę kosztową prowadzi per linia DL
  (patrz „Zamówienia wielo-konsultantowe"), a kontrakty tych osób bywają szkicami
  z obsady bez stawki albo ze stawką sprzed lat — nadpisanie przestawiłoby
  rozliczenia BIK/Polkomtela/BNP pierwszej nocy. Kierunek zamówienie → kontrakt
  (okres, przychód, jednostka) je obejmuje.
- **Hak jest JEDEN: `order_write_errors.commit_order_write`** (22 wywołania).
  Listener `after_flush` na `Session` zbiera `contract_id` ruszonych zamówień
  w `session.info`, a `sync_pending_order_contracts` synchronizuje je przed
  commitem — w savepoincie, fail-soft (awaria = log, zamówienie i tak zapisane).
  Writery spoza routerów wołają go jawnie: auto-zapis z maila
  (`order_mail_apply.apply_document`), import Nordea (`admin_import`). Nowy
  writer spoza tych ścieżek MUSI zrobić to samo.
- **Po synchronizacji `_refresh_expired` doczytuje TYLKO wygasłe atrybuty.**
  Sync zmienia zamówienie, które handler już `refresh`-ował, więc serwerowe
  `updated_at` wygasa → `MissingGreenlet` przy serializacji. `refresh` całego
  obiektu wygasiłby relacje (harmonogramy) — dlatego lista atrybutów.
- **PATCH kontraktu**: jawna `rate_unit`/waluta w tym zapisie wygrywa z
  zamówieniem (`follow_order_unit`/`follow_order_currency=False`); ręczna
  stawka przychodowa przy istniejącym harmonogramie dopisuje krok od dziś
  (`apply_manual_client_rate`) — ale TYLKO przy realnej zmianie, bo formularz
  wysyła całą stawkę także nieruszaną, a krok z niezmienioną wartością
  przykryłby późniejszą korektę w zamówieniu.
- **Cała synchronizacja czeka na marker jednorazowej korekty**
  (`sync_enabled`): padnięty blok w entrypoincie (loguje i idzie dalej) nie
  może pozwolić zapisom zamówień zatrzeć niezgodności przed migawką. Ścieżki
  kontraktu (PATCH, aneksy, `/bulk-extend`, `/bulk-mark-ended`, `/terminate`,
  potwierdzenie podpisu) wołają `resync_contract_safely` — savepoint + log;
  błąd projekcji nie cofa zapisu użytkownika. Przedłużenie/zakończenie MUSI
  resyncować: `_synced_client_order_end` wpisałby datę końca UMOWY w okres
  zamówienia.
- **Alert kontraktowy „koniec zamówienia u klienta" pomija okres prowadzony
  synchronizacją** (`client_order_start_date IS NOT NULL`) — o końcu zamówienia
  ostrzega już skaner zamówień; dwa alerty nie deduplikują się (inne encje).
- **Jednorazowo (`contract_order_sync_repair.py`, blok w `entrypoint.sh`,
  marker `0304_contract_order_sync_repair`)**: NAJPIERW migawka raportu zgodności
  zamówienie ↔ kontrakt (stan sprzed wdrożenia — potem sync by go zatarł), POTEM
  szkice: zwykły → `active` (z okresem i przychodem, gdy osoba ma uzupełnione
  zamówienie); minione `end_date` + trwające zamówienie → bezterminowy
  `active` (aktywny z minioną datą zakończyłby cron razem z zamówieniami
  i sprawami offboardingu MD); minione bez zamówienia → `ended` bez
  offboardingu; **duplikat żywego kontraktu tej osoby u klienta → ZOSTAJE
  szkicem** (aktywny podwoiłby MRR; decyzja w raporcie). Przebieg dobowy kosztów
  rusza dopiero po markerze i odświeża też cache `rate_client` kontraktów,
  którym wszedł krok (formularz odsyła kolumnę). Excel:
  `GET /api/contracts/order-sync-report` (Admin, bez przycisku w UI) — arkusze
  „Przed wdrożeniem", „Poprawione szkice", „Stan bieżący".
