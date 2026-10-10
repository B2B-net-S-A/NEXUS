# Historia zamówienia, „Zużycie MD" i „Importy MD" (ticket 7, 25.09.2026)

Historia zamówienia MD mieszała zdarzenia biznesowe, pojedyncze zejścia
z importów i techniczne edycje pól (4500030197: 23 wpisy, 6 edycji jednej
osoby w 3 minuty, dwa razy „Zakończono zamówienie").

- **Dziennik `client_order_group_events` zostaje nietknięty; widok składa
  `services/order_history.build_history` przy odczycie** (`GET …/history`).
  `/events` (surowy dziennik) czytają dziesiątki testów i raporty — nie
  przerabiaj go na widok. Licznik `event_count` karty liczy wpisy widoku.
- **Reguły widoku:** import = jeden wpis na `payload.import_id` (link „Otwórz
  import →" do `?tab=importy-md&import=`); edycje linii tej samej osoby przez
  tego samego autora w odstępie ≤ 15 min = jeden wpis z wynikiem netto
  i rozwinięciem; seria złożona WYŁĄCZNIE z ręcznych zejść („zejście MD")
  albo pól technicznych nie trafia do historii; identyczny wpis w tej samej
  minucie — raz (a `record_event` nie dopisuje identycznego wpisu dwa razy
  w jednej transakcji).
- **`update_line` zapisuje realne zmiany**: `payload.diff` (biznesowe
  „przed → po"), `payload.technical` (waluty, jednostka stawki),
  `md_remaining_before`. Formularz odsyła komplet pól — zapis tych samych
  wartości nie zostawia wpisu. Wpisy sprzed tej zmiany mają same nazwy pól.
- **Pola techniczne są w Timeline kontraktu** (`/api/contracts/{id}/activities`
  dokleja wpisy `order_line_fields_changed` z dziennika zamówień, polskie
  polskie nazwy) — WYŁĄCZNIE wpisy z `payload.technical`. Starsze wpisy
  wymieniały waluty w `changed` przy każdym zapisie formularza, więc nie
  dowodzą zmiany i na Timeline nie trafiają.
- **Okno „Zużycie MD"** (`GET …/consumptions`, `services/md_consumption_view`):
  saldo po miesiącu liczone WSTECZ od dzisiejszego `md_remaining` (ostatni
  wiersz = pasek karty), numer z importu z wierszy `md_consumption_import_rows`
  (ręczny wpis kasuje `import_id` na zejściu), korekty z dziennika pod
  miesiącem. Przycisk „Zużycie" na karcie czyta `consumption_recent`
  i `consumption_flags` z listy grup (brak zejścia za poprzedni miesiąc tylko,
  gdy import za ten miesiąc już był).
- **„Importy MD" na profilu klienta** (`api/client_md_imports.py`, bramka
  karty zamówień): wyłącznie wiersze tego klienta — zaksięgowane na jego
  linie, z wyborem między jego liniami albo niezaksięgowane z DOKŁADNIE jego
  numerem (`md_consumption_view.same_order_number`: równość cyfr, nie
  zawieranie się — „2026" siedzi w „OIT/0189/2026/ITVM"). Wiersz zaksięgowany
  u innego klienta nie wychodzi nigdy (kwoty faktur). Import bez takich
  wierszy = 404. Rozstrzyganie wierszy zostaje w Finansach.
  „Pobierz do Excela” (`GET …/md-imports/{id}/export`, 02.10.2026) i ekran
  czytają te same wiersze z jednej funkcji `_load_detail` — plik nie może
  pokazać więcej niż ekran (zakres klienta, redakcja kwot).
