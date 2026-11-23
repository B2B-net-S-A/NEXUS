# Rozliczenia: automat przyjmuje RCP „Bez uwag” (reguła `order.auto_accept_clean`)

<!-- indeks: przyjmuj RCP bez uwag automatycznie, automat przyjęcia, poranny bieg, N-ty dzień roboczy, Do poprawy wyłącza automat, przyjął automat, Finanse widzą tylko wyjątki, client_settlements_auto_accept -->

Decyzja Artura z 23.11.2026, rekomendacja 1 z makiet panelu Finansów. W październiku
93 z 200 osób (bez Nordei) miało RCP „Bez uwag”, a Finanse przyjmowały każde ręcznie.
Przy włączonej regule klienta robi to automat, a Finanse zajmują się tylko wyjątkami.

Kod: `services/client_settlements/auto_accept.py` (termin i bieg),
`tasks/client_settlements_auto_accept.py` (pętla), `service.accept_batch(auto=True)`.

- **Reguła w katalogu, domyślnie wyłączona.** Sekcja „Zamówienie i MD”, na ekranie
  przełącznik zamiast poziomów (`Rule.switch`): włączona = `block`, wyłączona = `off`.
  Działa od miesiąca zapisu reguł, jak każda reguła klienta.
- **Ta sama ścieżka co „Przyjmij RCP bez uwag”.** Automat woła `accept_batch`, więc MD
  schodzą z zamówienia tylko według `order.charge_on_accept`, a konsultant dostaje to
  samo co przy ręcznym przyjęciu (`portal_documents.accept`, przez wyłącznik panelu).
  W stanie portalu „Tylko zespół” nikt nic nie dostaje. Nie dopisuj automatowi
  własnej wysyłki.
- **Tylko „Bez uwag” po przeliczeniu.** Przyjęcie liczy rozliczenie od nowa i odmawia,
  gdy wynik nie jest `ok` (`require_clean`). To samo dotyczy ręcznego przyjęcia
  zbiorczego: RCP, które po przeliczeniu ma uwagi, zostaje na karcie osoby.
- **„Do poprawy” wyłącza automat dla tego rozliczenia na zawsze.** Znacznik
  `auto_accept_off` w danych przy kontrolach przeżywa przeliczenie i nowy plik.
  Takie RCP Finanse przyjmują same, także przyciskiem zbiorczym.
- **Termin.** Miesiąc `M` automat bierze od N-tego dnia roboczego miesiąca po nim
  (parametr, domyślnie 3, od 1 do 15), w kalendarzu firmy. Starsze miesiące od razu,
  bieżący miesiąc kalendarzowy nigdy. Przegląda trzy ostatnie miesiące.
- **Kiedy biegnie.** Pętla co godzinę, przyjmuje raz dziennie w dzień roboczy między
  7:00 a 12:00. Restart po wieczornym wdrożeniu czeka do rana. Moduł rozliczeń zamknięty
  (`client_settlements` albo `HR_PROGRAM_ENABLED`) = automat nic nie robi. Na stagingu
  pętla jest wyłączona (`STAGING_BLOCKED_TASKS`).
- **Ślad.** `accepted_by` jest puste, w danych przy kontrolach `auto_accepted` z chwilą
  przyjęcia, a w Historii zdarzeń zamówienia opis zejścia MD kończy się zdaniem
  „Przyjął automat (reguła klienta …)” z `payload.auto`. Karta osoby i wiersz miesiąca
  pokazują „Przyjął automat”.
- **Ekran.** Nad tabelą miesiąca pasek: ile RCP „Bez uwag” przyjmie się samo i od kiedy
  (`month_view.auto_accept`, `null` przy wyłączonej regule). Liczba nie obejmuje RCP
  po „Do poprawy”.
