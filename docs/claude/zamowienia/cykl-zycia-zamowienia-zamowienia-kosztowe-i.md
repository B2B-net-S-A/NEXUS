# Cykl życia zamówienia, zamówienia kosztowe i powiadomienia Delivery Leada

Migracja `0233`. Trzy obszary, jedna rewizja — spotykają się na jednym wierszu
`client_order_groups`. Pełny opis: `docs/order-lifecycle-cost-and-dl-alerts-completion-report.md`.

- **Zakładka „Zamówienia" to JEDEN widok dla każdego klienta** (stan z audytu
  24.09.2026; od 29.09.2026 tabela z panelem — sekcja „Kontrakty i Zamówienia: lista
  z panelem"): `MultiConsultantOrdersTab` renderuje zamówienia MD/kosztowe i kontraktorów
  z zamówieniami okresowymi w jednej `OrdersTable`. `OrdersAndContractsTab`,
  `OrderGroupCard` i `EndedLineCard` usunięte. Do 09.2026 były dwa widoki i stąd
  historyczne wzmianki w tym pliku o „widoku jednoosobowym”.
- **Cykl życia grupy jest STANEM, nie datą.** `status` ∈ `active | completed | exhausted`.
  Data nie odróżnia zamówienia domkniętego świadomie od takiego, któremu minął termin,
  a to dwie różne decyzje. `exhausted` dochodzi automatycznie przy zerowym budżecie
  i **nie da się go cofnąć** przywróceniem (409) — tam problemem nie jest data, tylko
  brak pieniędzy, więc właściwą akcją jest korekta kwoty albo nowe zamówienie.
- **Zakończenie jest LUSTREM syncu terminacji kontraktu** ([contracts.py:2918](backend/app/api/contracts.py)):
  data zapisuje się zawsze, ale `completed` dostają tylko linie, których dzień już
  nadszedł. Bez tego zakończenie zaplanowane w przód wyłączałoby kogoś, kto dziś pracuje.
  **Import MD/kosztowy rozlicza taką grupę do daty zakończenia** (od 10.09.2026):
  grupa ma `completed` od razu, a jej linie są aktywne, więc
  `active_md_lines`/`active_cost_lines`/`active_shared_md_lines` przyjmują grupę
  `completed` z `closure_date ≥` pierwszy dzień importowanego miesiąca
  (`group_settles_in_month`). Ta sama reguła MUSI być w walidacji po blokadach
  (`md_consumption._ordinary_locked_target_is_valid`) — bez niej cała partia
  kosztowa lub wspólnej puli dostaje 409.
- **Usunięcie zamówienia kasuje WYŁĄCZNIE to zamówienie** (ticket 09.2026, decyzja:
  bez efektów ubocznych). `DELETE …/order-groups/{g}/lines/{l}` i kasowanie całej
  grupy wołają `_delete_line_row` — twarde `db.delete`, nigdy odpięcie. Do tej zmiany
  aktywna linia była odpinana (`order_group_id=NULL`) i wracała na liście jako NOWE
  zamówienie okresowe osoby, a linia z rozliczeniami dostawała `completed` + wpis
  `removed_from_order` (`_keep_consumed_line_as_history`, usunięte), co czytało się
  jak zamknięty projekt. `DELETE /api/clients/{c}/orders/{o}` na zamówieniu
  samodzielnym kasuje trwale w KAŻDYM statusie (dawniej aktywne → `cancelled`);
  linia grupy wołana tą trasą zachowuje starą regułę (szkic znika, reszta anulowana).
  **Rozliczenia blokują (409)** — `services/order_settlements.py`
  (`settlement_blockers`, wspólne z `_assert_group_is_disposable`): kaskada
  zabrałaby MD i faktury z importu Finansów. Front wyszarza kosz linii przy
  `lineHasSettlements` (`lib/order-line-usage.ts`). Status kontraktu, inne zamówienia
  i sprawy offboardingu nie są ruszane; `commit_order_write` tylko przelicza okres
  i stawki kontraktu z tego, co zostało. Pliki PO kasowane są PO commicie.
  Wpisy `removed_from_order` sprzed zmiany są dalej czytane (`_apply_line_history`,
  `sync_md_line_status`, `order_facts`), ale nie powstają nowe. Kasowanie linii
  zabiera jej `dodanie_konsultanta`; `zamiana_kontraktora` ZOSTAJE. Bieżące
  zamówienie na karcie kontraktora ma własny przycisk „Usuń zamówienie", a
  „Zakończ współpracę" (wypowiedzenie umowy, domyka WSZYSTKIE zamówienia osoby) nie
  ma już ikony kosza — to ona była „kaskadowym usuwaniem" ze zgłoszenia.
- **Historia osoby na zamówieniu** (`_apply_line_history`, jedno zapytanie o dziennik):
  `origin` (`document` = z PDF-a / `manual`), `added_by_name`/`added_at` (autor
  zdarzenia `dodanie_konsultanta`/`zamiana_kontraktora`), `replaces_name`,
  `removed_from_order`, `cooperation_ended_on`, `md_used`, `history_kept_*`.
  Pochodzenie zapisuje front (`document_name` / `replaces_name` w `OrderLineCreate`);
  linie sprzed tej ewidencji dodane > 2 min po utworzeniu grupy liczą się jako
  `manual`, wcześniejsze — `null` (bez odznaki). **Zapis historyczny**
  (`historical: true`): osoba z ZAKOŃCZONYM kontraktem zostaje na zamówieniu jako
  linia `completed` z datą końca udziału ≤ dziś, wyłącznie dla kontraktu
  w statusie `ended` (`terminated_at` przeżywa wznowienie, więc nie wystarcza);
  nie wznawia kontraktu (`_sync_contract_after_live_group_line` pomija
  `completed`, `sync_md_line_status` nie wskrzesza linii, której kontrakt jest
  `ended`) i nie przepisuje go (`skip_sync_for_contract` — bez tego sync
  przestawiłby zakończonej umowie jednostkę i dopisał krok przychodu po jej końcu).
  `POST …/lines/{id}/keep-history` = decyzja „Zostaw jako historię" (wpis w dzienniku
  z autorem; sprawa offboardingu MD `pending` → 409). PDF zamówienia trafia do
  profilu każdej osoby na zamówieniu przez `_sync_group_pdf_documents` (add_line,
  swap, upload pliku) — zastępca dodany później też go dostaje.
  Pod osobą spoza aktywnej obsady karta zamówienia pisze jedno zdanie dla MD
  i kosztowych: „[osoba] wykorzystał(a) X zł / Y MD na tym zamówieniu przed
  zakończeniem współpracy — ta kwota nie wraca do puli" (`lib/order-line-usage.ts`;
  kwota tylko przy `rate_revenue` z odpowiedzi, czyli z dostępem do finansów).
- **Wyczerpanie MD (BIK, Polkomtel) pomija osoby z zakończoną współpracą**
  (rozstrzygnięcie otwartego pytania z ticketu 09.2026): linia `completed`
  z niewykorzystanym limitem nie trzyma zamówienia otwartego; zamówienie kończy się,
  gdy ktoś NAPRAWDĘ wyczerpał limit, a nikt na obsadzie nie ma już MD. WYJĄTEK:
  nierozstrzygnięta sprawa offboardingu MD w grupie trzyma zamówienie otwarte —
  po zamknięciu „przywróć" i „przenieś" nie miałyby dokąd wrócić.
  **Dane testowe:** od 09.2026 skasowanie grupy i usunięcie linii kasują linie
  trwale (patrz „Usunięcie zamówienia kasuje WYŁĄCZNIE to zamówienie"). Osierocone
  wiersze `client_orders` po kasowaniu grup sprzed tej zmiany usuwasz
  `DELETE /orders/{id}` (samodzielne zamówienie jest kasowane w każdym statusie) —
  najpierw linia-następca, potem poprzednik, bo `predecessor_order_id` wskazuje wstecz.
- **Przedłużenie to NOWA grupa** z `predecessor_group_id`, nie edycja poprzedniej:
  poprzednia musi zostać taka, jaka była, bo na jej podstawie rozliczono już faktury.
  Typ rozliczenia DZIEDZICZY się po poprzedniku.
- **Zamówienie kosztowe (`is_cost_based`) — kwota mieszka na GRUPIE, nie na linii.**
  To jedna pula dzielona przez kilku konsultantów; trzymanie jej per osoba wymagałoby
  podziału z góry, czego nikt nie robi. Linia kosztowa ma obie stawki i **puste pola MD** —
  dlatego 0233 rozluźnia `ck_client_orders_md_coherence`: budżet nadal wymaga dodatniej
  stawki przychodowej, ale stawka bez budżetu jest legalna (do 0233 taka linia w ogóle
  nie dawała się zapisać).
- **Trzy liczby, nie jedna.** Ticket nazywa „zużyciem" wartość, która MALEJE — czyli
  resztę. UI pokazuje `budget_amount` / `budget_used` / `budget_remaining` + pasek, bo
  jedno pole podpisane „zużycie", a pokazujące resztę, myli w rozmowie o pieniądzach.
- **Rozliczenie przelicza się od zera przy każdej zmianie** (`cost_orders.settle_group`),
  po `(period_month, order_id)`. To jest mechanizm idempotencji importu razem z UNIQUE
  `(order_id, period_month)`, a stała kolejność jest tym, co sprawia, że odpowiedź na
  pytanie „której osobie zabrakło budżetu" nie zmienia się między odczytami.
  `settled_amount`/`unsettled_amount` są ZAPISANE, nie liczone przy odczycie.
- **Reszta nie schodzi poniżej zera**, a nadwyżka ląduje jako `unsettled_amount` na
  konkretnej linii — „budżet przekroczony o X" bez wskazania osoby nie daje się rozliczyć
  z klientem. `budget_manual_adjustment` jest osobną kolumną (jak `md_manual_adjustment`):
  korekta nadpisująca resztę wprost przeżyłaby do najbliższego importu.
- **Import kosztowy to DRUGA, niezależna ścieżka w „Import zużycia MD"** (`/finance?view=md`),
  nie w „Wynikach miesięcznych" — tamten moduł świadomie nie przechowuje „Uwag" i ta
  decyzja zostaje. Numer wybierany jest przez KONFRONTACJĘ z istniejącymi zamówieniami
  (`extract_order_number_candidates`), nie heurystyką „najdłuższy ciąg cyfr": obok numeru
  stoi często rok albo numer transzy. Wiersz wchodzi na tę ścieżkę tylko gdy ma **numer
  i kwotę** — bez kwoty nie ma czego odjąć, więc czerwień byłaby fałszywym alarmem.
  `cost_status` jest OSOBNĄ kolumną od `status`: jeden wiersz bywa MD-dopasowany po
  nazwisku i kosztowo-niedopasowany po numerze.
- **Parser MD wyklucza nagłówki stawkowe** (`_MD_ANTI_HEADERS`). Realny arkusz z Finansów
  ma obok siebie „Średnia Stawka MD" i „Ilość MD"; bez tego wygrywała pierwsza z brzegu
  i system odejmował 1000 „dni" zamiast 15 — błąd CICHY, bo liczba jest poprawna
  arytmetycznie, tylko opisuje co innego.
- **`dl_alerts` to OSOBNA tabela, nie `notifications`.** Tamta zna wyłącznie `is_read`:
  nie wie kto i kiedy sprawę załatwił, więc nie ma czasu reakcji, czyli nie ma czego
  wyeksportować. Ma też dobowy indeks dedupu, który tłumiłby powtórki, i fail-closed
  filtr widoczności, przez który rola Finanse i tak by tych wpisów nie zobaczyła.
- **Powtórka co 7 dni jest NOWYM wierszem**, nie aktualizacją — raport ma pokazywać, ile
  tygodni sprawa czekała. Numer okna wchodzi w `dedupe_key`; okno liczy się od daty
  PIERWSZEGO alertu tej sprawy, nie od poniedziałku (inaczej wszystkie alerty
  zsynchronizowałyby się w jeden dzień). Powtórki ustają po `handled` **albo** gdy warunek
  ustąpi. Wpisy nie są kasowane — log JEST raportem.
- **Uprawnienia cyklu życia są SZERSZE niż uprawnienia do stawek i to jest świadome.**
  `_ORDER_LIFECYCLE_ROLES` = admin + delivery_lead (przypisany) + finance (z
  `MANAGE_FINANCE`); HoR NIE (nie ma sekcji Delivery — audyt 22.09.2026 sprostował
  wcześniejszy opis). Stawki linii MD: admin + przypisany DL + `MANAGE_FINANCE`
  (decyzja 22.09: Finanse zmieniają kwoty). Test
  `test_rate_gate_did_not_leak_to_lifecycle_roles` broni granicy przed
  „uproszczeniem" obu list do jednej.
- **Kontraktor bez zamówienia w widoku jednoosobowym** ma teraz edytowalne numer, okres
  i obie stawki; pierwszy zapis zakłada szkic `ClientOrder`. To była przyczyna zgłoszenia
  „u Banku Pocztowego nie da się nic wpisać" — u Aliora pola działały wyłącznie dlatego,
  że jego zamówienia zostały kiedyś zaimportowane. Różnica DANYCH, nie konfiguracji.
- **Odczyt PDF ma DWIE polityki nadpisywania i nie wolno ich ujednolicać:** widok MD pyta
  „Tak/Nie" przy rozbieżności z ręcznym wpisem, widok jednoosobowy nadpisuje po cichu.
  Oba wymogi są w ticketach wprost. Wspólna warstwa: `lib/order-extraction.ts`.
- **Zamiana kontraktora DZIAŁA na zamówieniu kosztowym i nie rusza puli.** Guard był
  pisany wyłącznie pod tryb MD (`md_total is None` → 422), a linia kosztowa ma `md_total`
  puste **z definicji** — więc przycisk renderował się aktywny i gwarantowanie kończył się
  błędem „Linia nie ma budżetu MD do przeniesienia", czyli komunikatem o danych do
  uzupełnienia w stanie, którego nie da się usunąć. W trybie kosztowym nie ma czego
  przenosić: zmienia się osoba i jej stawki, a nowa linia dostaje **komplet NULL-i** w
  polach MD (`ck_client_orders_md_coherence` dopuszcza tylko wszystko albo nic).
  `settle_group` nie filtruje po statusie linii, więc domknięcie poprzednika **nie
  odsłania wydanych już pieniędzy** — dlatego zamiana nie wymaga przeliczenia budżetu.
  Przejście potwierdzone na produkcji end-to-end (Polkomtel, 2026-08-18, zamówienie
  testowe usunięte po weryfikacji): nowa linia ma komplet NULL-i w polach MD, poprzednik
  `completed` z datą zamiany, `budget_remaining` bez zmian, a wpis w historii brzmi
  „Zamiana kontraktora … (zamówienie kosztowe): … Kwota zamówienia zostaje wspólna dla
  całej grupy" — bez arytmetyki MD.
- **Weryfikując te ekrany przeglądarką: akcje destrukcyjne wołają natywny `window.confirm`,
  który ZAMRAŻA automatyzację.** `Input.dispatchMouseEvent` leci w timeout, screenshot
  zwraca „Script injection timed out", klawiatura nie pomaga (dialog jest poza stroną),
  a `navigate` co prawda odmraża kartę, ale **odrzuca** dialog, czyli akcja się nie
  wykonuje. Usuwanie/zakończenie testuj przez API (`fetch` z Bearer w zalogowanej karcie);
  przez interfejs weryfikuj to, co nie kończy się natywnym dialogiem.
- **Centrum e-Zdrowia a „kontraktor bez zamówienia":** `POST /orders` wymaga tam części
  umowy (`validate_project_part(..., require=True)`), a select renderował się wyłącznie
  przy istniejącym `activeOrder` — u TEGO klienta objaw „nie da się nic wpisać" przeżywał
  więc poprawkę T6, i to jako surowe 422. Teraz część umowy jest **polem, które zakłada
  szkic**: renderuje się bez zamówienia, a próba zapisu czegokolwiek innego bez niej
  odmawia po polsku, po stronie przeglądarki, zamiast lecieć po odpowiedź serwera.
- **`?tab=` na profilu klienta jest LOAD-BEARING.** Trzy źródła powiadomień linkują wprost
  do zakładki ze sprawą (`dl_alerts_scanner.py`, `dl_portal_expiry_scanner.py`,
  `pipeline.py` — wszystkie `/clients/{id}?tab=zamowienia`), a strona trzymała `useState`
  na stałe `"profil"` i parametru nie czytała. Kliknięcie powiadomienia lądowało na
  Profilu i kazało odbiorcy szukać samodzielnie.
  **Sam inicjalizator `useState` NIE wystarcza** — odpala się raz na cykl życia
  komponentu, a użytkownik już na `/clients/1` klikający powiadomienie do
  `/clients/1?tab=zamowienia` dostaje MIĘKKĄ nawigację App Routera: adres się zmienia,
  komponent się nie odmontowuje, stan zostaje. Dla Delivery Leada siedzącego na profilu
  klienta to scenariusz codzienny, nie brzegowy. Logika mieszka w
  `frontend/src/lib/client-tab.ts` (`useClientTab`) właśnie po to, żeby dała się
  przetestować bez montowania całego ciężkiego profilu — efekt zależy od WARTOŚCI
  parametru, nie od tożsamości `searchParams`, więc ręczne kliknięcie w inną zakładkę
  nie jest cofane przy najbliższym renderze.
  **Klucze `?tab=` w backendzie muszą pochodzić z `client-tab.ts`** — pilnuje tego
  `tests/test_client_tab_links.py`. Do 10.09 alert nowego szkicu z maila linkował
  do `?tab=orders`, a alerty umów ramowych do `?tab=framework-contracts`; oba
  klucze nie istnieją, więc odbiorca lądował na Profilu.
- **Aktywacja na prodzie: `COST_ORDER_CLIENT_IDS=15` (Polkomtel) USTAWIONE 2026-08-18.**
  Nie panelem i nie po SSH (klucze martwe, hasła do panelu nie znamy) — workflow
  **„Coolify set env"** (`.github/workflows/coolify-set-env.yml`, `workflow_dispatch`);
  to jest droga do każdej przyszłej zmiany env na prodzie. Zweryfikowane na żywym API:
  `cost_orders_enabled` = `true` u Polkomtela i `false` u BIK/BNP, mimo że wszyscy trzej
  są wielo-konsultantowi. `DL_ALERTS_ENABLED` domyślnie `true` (wyłączenie kończy pętlę
  skanera PRZED nią, nie budzi procesu co 24 h).
  **Uwaga:** sama zmienna to połowa aktywacji — checkbox renderuje się dopiero, gdy
  `GET /api/clients/{id}` zwraca `cost_orders_enabled`. To pole było zaplanowane,
  udokumentowane i konsumowane przez front, a mimo to nigdy nie powstało (PR #1196);
  wyszło z odpytania produkcji, nie z zielonych testów.
  **Od 09.2026 `cost_orders_enabled` NIE bramkuje już UI** — typ kosztowy jest
  dostępny u każdego klienta (patrz „Okno „Nowe zamówienie"…"). Flaga zostaje jako
  informacja dla automatów (np. brak auto-szkicu po zatrudnieniu).
