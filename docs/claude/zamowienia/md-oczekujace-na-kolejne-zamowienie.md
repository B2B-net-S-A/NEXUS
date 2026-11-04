# Import MD: wiersz bez numeru czeka na kolejne zamówienie (0492, 21.10.2026)

Arkusz BIK za wrzesień: ta sama osoba w dwóch wierszach — 11,625 MD z numerem
4500030369 i 12,25 MD bez numeru (kolejne zamówienie jeszcze nie wpłynęło).
Import dopasowywał drugi wiersz po nazwisku na to samo zamówienie, sumował
23,875 MD i oznaczał oba wiersze „przekroczenie puli o 12,25 MD”.

- **Nie łączymy wierszy, gdy jeden ma numer, a drugi nie.** Wiersz dopasowany
  po samym nazwisku (`len(matches) == 1`, bez wiążącego numeru) czeka do końca
  pętli w `run_md_import`; jeśli trafia na linię, którą inny wiersz tej osoby
  wskazał numerem (`explicit_md_orders`), dostaje status `awaiting_order`,
  `awaiting_origin_order_id` = ta linia, `md_pending` = jego MD, i nie schodzi
  z żadnej puli. Trafienie na INNĄ linię to nie łączenie — zwykły zapis.
  Przekroczenie puli liczy się więc tylko z wierszy z numerem.
- **„Pozostało do zafakturowania za {miesiąc}: X MD – oczekuje na kolejne
  zamówienie”** składa front (`awaitingMdNote` w `lib/order-consumption.ts`)
  z `awaiting_md`: w wynikach importu przy wierszu z numerem i przy wierszu
  oczekującym (`ImportRowRead.awaiting_md`), na karcie zamówienia przy linii
  (`OrderLineRead.awaiting_md`, także u osoby zakończonej).
- **Kolejne zamówienie** (`services/md_awaiting_orders.next_order_lines`):
  linia tej samej osoby (kandydat kontraktu) u tego samego klienta, na
  zamówieniu MD per osoba (bez kosztowych i wspólnej puli), grupa o wyższym id
  i dacie startu ≥ zamówienia z numerem, `active`/`scheduled`, linia nie
  `cancelled`/`completed`. Kilka → od najwcześniejszego; każde bierze tyle, ile
  ma `md_remaining`, reszta czeka (status zostaje, `md_pending` maleje).
- **Zejście DOKŁADA się do wpisu linii za miesiąc raportu** (`upsert_consumption`
  z sumą), nie nadpisuje go, i nie idzie przez `apply_md_consumption` (żadnych
  przekierowań na poprzednika ani przeniesień na następcę). Wpis w historii
  nowego zamówienia: `EVENT_MD_IMPORT` z `import_id` paczki (łączy się
  z odsyłaczem „Otwórz import →”) i `awaiting_row_id`.
- **Kto wyzwala**: `settle_awaiting_md_for_client` po utworzeniu zamówienia,
  przedłużeniu, dopisaniu osoby (`_add_line_to_group`), aktywacji szkicu
  (`_materialize_group_after_activation` w `api/client_orders.py` i PATCH
  `status=active` szkicu grupy w `update_order_group`) i na końcu importu dla wierszy
  z tej paczki. Nowa ścieżka zakładania zamówień MD musi ją wołać.
  Kolejność blokad: kontrakty i linie kolejnych zamówień, potem wiersze importu.
- **Ponowny import miesiąca** (`plan_reimport` przed blokadami, `apply_reimport`
  po blokadach i PRZED zejściami paczki): klucz to miesiąc + osoba (tokeny
  nazwiska) + klient zamówienia z numerem, a nowa paczka jest prawdą. Klient
  wiersza paczki (`_reimport_persons` w `api/md_consumption.py`) to klient
  zamówienia, na które trafił albo z którego czeka; bez dopasowania — klienci
  jego linii do wyboru albo linii tej osoby w miesiącu. Wiersz tej osoby tylko
  u innego klienta (albo imiennika) nie rusza jej oczekujących MD (audyt
  22.10.2026, F70). Każda osoba z wierszem MD w nowej paczce u tego klienta
  traci wcześniejsze wiersze oczekujące (`superseded`) — także gdy plik korygujący przeniósł te MD na wiersz
  z numerem. Ile już zeszło z kolejnych zamówień, liczy dziennik zamówień
  (wpisy `EVENT_MD_IMPORT` z `awaiting_row_id`, netto): to pokrywa nowe wiersze
  oczekujące bez drugiego zejścia, a nadwyżka ponad nową wartość WRACA
  z kolejnych zamówień (wpis „Cofnięto X MD…”, od najpóźniejszego) — lustro
  nadpisania (linia, miesiąc). Cofnięcie przed zejściami paczki, bo wiersz tej
  paczki może trafić na to samo zamówienie wprost.
- Statusy `awaiting_order`/`superseded` nie wchodzą do `rows_applied`,
  `rows_ambiguous` ani `rows_unmatched`. Na liście „Importy MD” klienta stan
  `awaiting` („Oczekuje na zamówienie”). Lustro DDL w `entrypoint.sh` pilnuje
  `test_md_import_awaiting_order_mirror.py`.
