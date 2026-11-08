# Stan QC pary jest jeden i przychodzi z serwera (08.11.2026, QC-11)
<!-- indeks: `qc_state` {kind, n, items, text, tone, who, hint}, słownik nazw, kolejność stanów, nagłówek „Kontrola CV” -->

Audyt z 08.11.2026 znalazł ten sam stan QC przetłumaczony w sześciu miejscach
i cztery nazwy przepuszczenia. Każda poprawka stanu szła w sześciu kopiach.

- `cv_qc.pair_statuses` zwraca `qc_state` (`services/qc_state.py`). Front tylko go
  renderuje: `qcStateText`, `QcStatusBadge`, chip karty, nagłówek „Kontrola CV”.
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

Testy: `tests/test_qc_state.py`, `CvControlSummary.test.tsx`, `QcStatusBadge.test.tsx`.
