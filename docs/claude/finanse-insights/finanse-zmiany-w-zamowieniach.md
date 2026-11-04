# Finanse → Zmiany w zamówieniach

(Zmiany · Wejścia · Zejścia · Kończące się zamówienia · Braki, 0308)

Comiesięczny audyt zamówień dla działu finansowego (`/finance?view=order-changes`,
`GET /api/finance/order-changes?year&month&q&client_id&date_from&date_to`
+ `/export?…&tab=`, bramka sekcji Finance).
Decyzje Artura 14.09.2026: zmiany do miesiąca WPROWADZENIA; Brakiem nie jest
wypowiedziana umowa, szkic następnego zamówienia ani decyzja offboardingu MD /
„zostaw jako historię"; DL dostaje alert DL + dzwonek. Pełny opis:
`docs/finance-order-changes-completion-report.md`.

- **Zakładka nazywa się tak, jak to, co w niej jest (korekty 16.09 i 20.09.2026).**
  Do 16.09 Wejścia zbierały KAŻDE zamówienie startujące w miesiącu, a Zejścia
  pokazywały wiersze z werdyktem „Kontynuacja". Do 20.09 Wejścia nadal brały za
  nową osobę każdego, kto nie miał wcześniejszego WIERSZA ZAMÓWIENIA, a Zejścia
  mieszały „kończy się zamówienie" z „kończy się współpraca". Finanse czytają te
  listy jako „kto doszedł" i „kogo zdjąć z rozliczeń", więc obie kłamały.
  Stan docelowy: **Wejścia** = pierwsza współpraca (dowód: zamówienie ALBO
  umowa); **Zejścia** = zapisany koniec współpracy; **Kończące się zamówienia**
  = zamówienie bez kolejnego przy żywej współpracy; **Zmiany** = wszystko, co
  dzieje się w trwającej współpracy; **Braki** bez zmian.
- **Rejestr zamówień jest MŁODSZY niż współpraca, którą opisuje** — i to była
  przyczyna zgłoszenia z 09.2026 (konsultantka z umową bezterminową od grudnia,
  pierwszy wiersz zamówienia z września, w Wejściach jako „Nowy konsultant").
  Zmierzone na produkcji: z 63 zamówień startujących we wrześniu 2026 **38 ma
  umowę starszą niż własne zamówienie**, a 11 z nich nie miało ŻADNEGO
  wcześniejszego zamówienia. Dlatego `_classify_by_engagement` czyta
  `contracts` (bez `draft` i `void`) i dokłada szczebel tuż przed `new`.
  **Próg to pierwszy dzień MIESIĄCA, nie dzień startu zamówienia**: osobie
  faktycznie nowej zakłada się umowę razem z pierwszym zamówieniem, często
  z datą o kilka dni wcześniejszą, więc próg „ściśle przed startem" opróżniłby
  zakładkę (pilnuje tego
  `test_contract_starting_in_the_same_month_still_counts_as_an_entry`).
- **Klasyfikacja wejścia: `_classify_entries`, pierwsze trafienie wygrywa** —
  `additional_project` (trwające zamówienie u INNEGO klienta w dniu startu) →
  `order_continuation` (`previous_of`: poprzednie zamówienie u TEGO klienta
  ≤31 dni przed startem — reguła nietknięta) → `client_change` /
  `order_continuation` po kliencie OSTATNIEGO wcześniejszego zamówienia osoby
  (powrót po przerwie, przejście do innego klienta) → **ta sama drabinka na
  UMOWACH** (`_classify_by_engagement`) → `new` (jedyna klasa w Wejściach).
  Dowody z zamówień idą pierwsze, bo są dokładniejsze (niosą klienta, okres
  i numer). Wszystko poza `new` to wiersze syntetyczne w Zmianach, liczone przy
  odczycie — **bez migracji**: CHECK na `order_change_events.field` i dziennik
  zostają nietknięte. Zamówienie zaczynające się PÓŹNIEJ nie czyni z osoby „już
  współpracującej"; dwa zamówienia tego samego dnia u dwóch klientów rozstrzyga
  niższe `order_id` (`_precedes`), żeby osoba naprawdę nowa pokazała się
  w Wejściach raz, a nie zniknęła z nich całkiem.
- **Kontynuacja z UMOWY nie ma poprzedniego numeru zamówienia** — niesie
  `engagement_since` (data startu umowy) i obie warstwy renderują „współpraca
  od DD.MM.RRRR". Puste „—" czytałoby się jak utrata danych, nie jak inny
  rodzaj dowodu. `EntryClass` niesie pola PREZENTACYJNE
  (`running_client_names`, `previous_client_name`), nie surowe `OrderFact`y:
  dowodu z umowy nie da się w nie włożyć.
- **„Zmiana klienta" to konsultant przechodzący do innego klienta, nie zmiana
  pola.** `ClientOrderUpdate` nie ma `client_id` — zamówienia nie da się
  przepiąć z UI, więc literalna zmiana pola nie istnieje i nie ma czego
  zapisywać w dzienniku.
- **Zejście liczy się z FAKTÓW, nie z napisu werdyktu:** wiersz odpada, gdy
  `fact.works_until_md_exhausted or successor is not None`. Warunek stoi PRZED
  drabinką werdyktów, bo intencja zakończenia jest w niej sprawdzana pierwsza —
  rzadkie „wypowiedzenie + żywy następca" zostawałoby inaczej w Zejściach mimo
  tego, że osoba pracuje dalej. `ExitVerdict` nie ma już `continuation`, a
  `OrderExitItem` pól o następcy (zawsze puste).
- **Zejście wymaga ZAPISANEGO końca współpracy** (`load_ending_intents`,
  werdykt `ended_intent`). **Decyzja Artura 20.09.2026: wszystkie pięć rodzajów
  intencji zostaje w Zejściach** — wypowiedziana/zakończona umowa, zamiana
  kontraktora, decyzja DL po offboardingu MD, usunięcie z zamówienia,
  „zostaw jako historia". Wspólny mianownik: człowiek świadomie zapisał, że ta
  osoba schodzi. Nie zawężaj tego do samego `INTENT_CONTRACT_ENDED`.
  Zakres następcy per (osoba, klient) ZOSTAJE: przejście konsultanta do innego
  klienta JEST zejściem z punktu widzenia rozliczeń klienta A.
- **`ending_pending` i `no_successor` to „Kończące się zamówienia"** — osobna
  zakładka (`?sub=ending`, `?tab=ending`), ten sam `OrderExitItem` i ten sam
  render co Zejścia. Bliźniaczy typ różniący się wyłącznie nazwą byłby drugim
  miejscem do rozjechania; rozstrzyga WERDYKT. Wrzesień 2026 na produkcji: do
  87 zamówień kończących się przy żywej umowie stało w Zejściach obok ~13
  faktycznych zakończeń. `_exits` zwraca obie listy z JEDNEGO przebiegu — dwa
  osobne rozjechałyby się przy pierwszej poprawce drabinki i ta sama osoba
  potrafiłaby stać w obu zakładkach albo w żadnej.
- **Zmiany stawek NIE mają progu** — do Zmian trafia każda różnica stawki
  kosztowej i przychodowej. Jedyny filtr jest w `order_change_audit` (pierwsze
  wpisanie stawki to nie zmiana, szkice i anulowane się nie liczą).
- **Filtry (szukaj / klient / zakres dat) liczy SERWER, jedną funkcją
  `apply_filters` na gotowych listach** — ten sam kod obsługuje ekran
  i eksport, więc plik nie może pokazać czego innego niż lista. Data znaczy
  w każdej zakładce co innego (zmiana / start / koniec / dzień wykrycia braku),
  więc etykieta pola zmienia się z zakładką. Liczniki przy podzakładkach liczą
  się z długości list, czyli po filtrach — badge nie obiecuje wierszy, których
  pod nim nie ma. Wiersz BEZ daty nie mieści się w żadnym zakresie.
  `open_gaps_total` zostaje globalne (baner o całej historii).
- **Eksport bierze aktywną podzakładkę** (`?tab=`) z tymi samymi filtrami;
  `tab` pominięty = cały audyt (pięć arkuszy), zgodność wstecz. Tytuł
  arkusza musi zmieścić się w 31 znakach Excela — stąd „Kończące się zam.".
  `OrderChangesPanel` NIE odpytuje API sam — picker klienta wchodzi slotem
  `filters.clientPicker`, bo ten sam komponent renderuje publiczny harness
  `/preview/finance-order-changes`, który musi robić ZERO zapytań.
- **Pustka po filtrach ma własny komunikat** („Żaden wiersz nie pasuje do
  ustawionych filtrów") — pustka pod nagłówkiem miesiąca czyta się jak utrata
  danych. Odwrócony zakres dat nie jedzie do serwera (byłoby 422 w trakcie
  wpisywania drugiej daty), tylko wyświetla prośbę o poprawę.
- **Filtry żyją w adresie** (`q`, `client`, `clientName`, `from`, `to` obok
  `sub`/`month`); `ORDER_CHANGES_URL_KEYS` jest lustrem listy czyszczonej przy
  wyjściu z widoku w `app/finance/page.tsx`. Nazwa klienta jedzie obok id, żeby
  po odświeżeniu chip nie mówił „Klient: 18".

- **Stara wartość istnieje TYLKO w `order_change_events`.** Jedna zmiana na
  TRANSAKCJĘ (`services/order_change_audit.py`): `before_flush` zapamiętuje
  pierwszą starą wartość z `committed_state` (po flushu jest pusty;
  `get_history` zgłasza starą `None` jako brak historii, a `None → data` końca
  to zmiana), a wiersze powstają w `before_commit` jako różnica początek →
  koniec. Zapis per flush rejestrował stan pośredni: PATCH kosztu, który
  synchronizacja z umową cofa przed commitem, dawał dwie „zmiany" autora.
  Bez leniwego doczytywania (`MissingGreenlet`). Filtr szumu: pomija
  zamówienia, które na początku transakcji były szkicem/anulowane, i pierwsze
  wpisanie stawki. Linia grupy → `md_rate_*`; samodzielne → `rate_*` +
  `rate_unit` (tam `md_rate_revenue` to lustro, liczone raz). Historia
  zaczyna się od wdrożenia — widok mówi to wprost.
- **Autor = `session.info` stemplowane w `deps.get_authenticated_user`**
  (prawdziwe konto, nie podglądane). Zapis bez zalogowanej osoby (pętle,
  poczta, sync kosztu z umowy w tle) ma `source="system"`.
- **Jedna reguła następcy dla Zejść i Braków: `services/order_facts.py`.**
  Okres = `COALESCE(linia, grupa)`; następca = inne nieanulowane zamówienie tej
  samej OSOBY (`contracts.candidate_id`, nie kontrakt) u tego samego klienta,
  trwające po końcu (szkic się liczy; zakończone bez daty — nie). Świadomy
  koniec (`load_ending_intents`): umowa `ended`/`void` albo wypowiedziana
  z datą końca ≤ końca zamówienia, `predecessor_order_id` (zamiana),
  offboarding MD `remove`/`transfer`, zdarzenie `zakonczenie_konsultanta`
  z `removed_from_order`/`keep_history`.
- **Osoba z Zejść nie stoi w Brakach** (ticket 09.2026, filtr PRZY ODCZYCIE):
  `_gaps` pomija brak, którego zamówienie ma DZIŚ intencję zakończenia
  (`order_gaps.gap_orders_with_ending_intent` — ta sama `load_ending_intents`
  co Zejścia; typowo DL wypowiada umowę dopiero PO wykryciu braku), oraz brak
  współpracy (`sibling_key`) stojącej w Zejściach tego miesiąca. Wpis w bazie
  zostaje; `open_gaps_total` liczy bez takich wpisów, a `remind_open_gaps`
  zamyka ich karty DL (`handled_by_user_id` puste) zamiast przypominać.
- **Braki (`order_gaps`) nigdy nie są kasowane.** Wykrycie: pętla `order_gaps`
  (00:30 Warszawa + start), `detected_on = koniec + 1`, od
  `ORDER_GAP_TRACKING_START` (domyślnie 2026-08-01) i najwyżej
  `ORDER_GAP_LOOKBACK_DAYS` (45) wstecz — zamknięty miesiąc nie dostaje po
  tygodniach nowych braków. Następca utworzony do końca dnia wykrycia jest NA
  CZAS (decyzja 15.09.2026, UAT B69): brak nie powstaje, a brak założony rano
  i uzupełniony tego samego dnia zostaje w bazie, ale raport Finansów go nie
  pokazuje (`delay_days == 0`). Następca z kolejnego dnia = `filled_late`. **Aktywna linia MD z niewyczerpanym budżetem nie kończy
  się datą** (skaner wygasania też jej nie domyka) — nie jest brakiem, a
  w Zejściach ma werdykt „trwa do wyczerpania budżetu MD". Każdy brak w
  osobnym savepoincie (awaria powiadomienia nie cofa przebiegu). Dzwonek tylko
  dla braków sprzed ≤ 2 dni (pierwszy bieg po wdrożeniu nie zasypuje DL).
  Zamknięcie: `commit_order_write` ORAZ `order_mail_apply` wołają
  `refresh_order_gaps_safely` dla kontraktów ruszonych zamówień (savepoint,
  zawężenie w SQL) i oznaczają alerty DL `handled`. Kontrakt bez osoby jest
  współpracą sam w sobie (`sibling_key`). GET widoku niczego nie zapisuje.
- **Alert `order_missing_successor`** — lustro CHECK `ck_dl_alerts_type`
  w migracji, modelu i OBU definicjach w `entrypoint.sh`; powtórka co
  `DL_ALERT_REPEAT_DAYS` przez regułę w `dl_alerts_scanner`. Dzwonek:
  `NotificationType.order_missing_successor` (enum w `_ENUM_STATEMENTS`),
  jedno powiadomienie na brak. `DlAlertsSection` jest znowu montowana
  w `RoleDashboard` dla presetu `delivery-lead` (od #1304 nie była nigdzie).
- **Dodatkowy projekt** liczony przy odczycie: zamówienie startujące w miesiącu,
  gdy osoba ma w dniu startu trwające (nie szkic) zamówienie u INNEGO klienta.
- **Nordea w Wejściach: gotowa pozycja faktury cyklicznej** (ticket 8, 0382,
  `services/nordea_invoice_lines.py`): `NIDS: <NIIDS number>, IT Retail Banking,
  Nordea Contact: <Contact person z „Invoice reference”>, Contractor: <osoba
  z „Consultant(s)”> ID:`. Zapis w `client_orders.invoice_lines` (JSONB) przy
  wgraniu PDF-a (`_attach_po_bytes` — formularz i poczta), zamówienia sprzed
  wdrożenia dosypuje bieg `order_gaps`; ręczna poprawka
  `PUT /api/finance/order-changes/invoice-lines/{order_id}` (te same osoby co
  „Zrobione”) zostaje przy zamówieniu, a podmiana PDF-a ją nadpisuje. Klient
  Nordea = bramka reguły odczytu (`NORDEA_ORDER_NUMBER_CLIENT_IDS`). Nieodczytane
  pole = `[brak]` + ostrzeżenie; parser sprawdzony 25.09 na 60/60 PDF-ach z prod.
- Harness wizualny (publiczny, zero zapytań): `/preview/finance-order-changes`.
