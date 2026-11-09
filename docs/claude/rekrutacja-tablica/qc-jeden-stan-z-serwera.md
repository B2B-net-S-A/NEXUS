# Stan QC pary jest jeden i przychodzi z serwera (08.11.2026, QC-11)
<!-- indeks: `qc_state` {kind, n, items, text, tone, who, hint}, słownik nazw, kolejność stanów, nagłówek „Kontrola CV” -->

Audyt z 08.11.2026 znalazł ten sam stan QC przetłumaczony w sześciu miejscach
i cztery nazwy przepuszczenia. Każda poprawka stanu szła w sześciu kopiach.

- `cv_qc.pair_statuses` zwraca `qc_state` (`services/qc_state.py`). Front tylko go
  renderuje: `qcStateText`, `QcStatusBadge`, chip karty, nagłówek „Kontrola CV”.
- `run_qc` (odpowiedź `/qc`) zwraca ten sam `qc_state`, policzony z bieżących `checks`
  (`qc_state_of_checks`, lustro ścieżek jsonpath z `pair_statuses`). Panel osoby i okno QC
  czytają go zamiast liczyć z `passed` (09.11.2026: panel mówił „bez blokad”, karta
  „wskaż stanowisko”). Nowe pole z `checks` dopisz po obu stronach.
  Ramka „Następny etap” (`move_requirements._qc_result_item`) bierze ten sam tekst.
- Słownik: „QC: sprawdzone”, „QC: sprawdzone ręcznie · Anna K.”, „QC: wskaż
  stanowisko · 3”, „QC: obejrzyj zgodę RODO”, „QC: kandydat nie ma: Kafka”,
  „QC: 2 do poprawy”, „QC: przepuszczone · Anna K.”, „QC: jeszcze nie sprawdzone”.
  Nowej nazwy na istniejący stan nie dopisuj na froncie.
- `manual_items` liczy wymagania bez wskazanego stanowiska i zgodę RODO z pliku
  spoza NEXUSA, a pozostałe sprawdzenia „sprawdź ręcznie” po nazwie. Ta sama liczba
  stoi na karcie, w pigułce i w panelu.
- Kolejność przy zdanym QC: najpierw „wskaż stanowisko” (ruch rekrutera), potem luka
  kandydata (decyzja Delivery Leada), potem „sprawdzone ręcznie”, potem „sprawdzone”.
- „Kontrola CV” w przeglądzie DL ma w nagłówku stan i jedno „Otwórz QC”. Pasek nad CV
  nie powtarza już wyniku QC.

Testy: `tests/test_qc_state.py`, `test_qc_endpoint_says_the_same_state_as_the_board`, `CvControlSummary.test.tsx`, `QcStatusBadge.test.tsx`.

## Co zatrzymuje parę u rekrutera (QC-7, QC-8, 08.11.2026)

- **Niesprawdzone stanowiska albo zgoda RODO z pliku** (`manual_items`): zdane QC nie
  wchodzi do kolejki Delivery Leada (`dl_send_queue.readiness_of`, `isReadyForDlSend`).
  Ruch ma rekruter: „Wskaż stanowisko w QC”. W trybie doradczym może przesunąć mimo to
  („Przesuń mimo uwag…”, dzwonek do DL), wtedy para jest `overridden` i trafia do kolejki.
- **Luka kandydata** przy wysyłce do klienta: Delivery Lead wybiera „Wysyłam mimo braku”
  albo „Wracam do rekrutera” (`GapDecision`). Wybór jedzie jako `gap_decision`
  i zostaje w `Activity` (`cv_qc_gap_decision`, lista luk). Pomiar: odrzucenia u klienta
  z luką i bez luki, po 21 dniach.
- **Starszy plik B2B** (QC-4): `cv_present` = manual z `fix: "use_older_cv"`, „Użyj tego CV”
  wczytuje plik jako szkic tej pary. Wysyłka bez decyzji dalej stoi (`holds_send`), bo
  nie ma CV tej rekrutacji. Reguła „plik sprzed rekrutacji nie jest jej CV” obowiązuje.
- **Obejścia z gotowym powodem** (QC-5): „Kandydat potwierdził” wymaga wskazania uwagi
  i słów kandydata (15 znaków), „Nie dotyczy tej roli” wskazania uwagi.
- **Wskazanie stanowisk** ma odcisk oryginału (`original_fp`): po wgraniu innego QC pyta
  znowu. „Nigdzie — tylko na liście” pyta raz, zanim zapisze.
