# Budżet rekrutacji „od–do” (0420, 06.10.2026)

Zgłoszenie DL (BNP): klient podaje „60–80 zł/h”, pole przyjmowało jedną liczbę,
więc wpisywany był środek (70) — kandydat za 75 dostawał „ponad budżet”.

- **Budżetem jest górna granica** (`rate_budget_hourly`,
  `resolve_job_budget_hourly`) — dla plakietek, oceny, bramek, gotowości,
  Talent Radaru. `jobs.rate_budget_hourly_min` („od”) jest WYŁĄCZNIE do
  wyświetlania; nie dokładaj go do dopasowań ani odcisku requestu.
- Jedna reguła: `services/job_budget_range.py` (`effective_min`: kolumna albo
  przedział z `basics.rate_raw` Championa, gdy jego góra jest budżetem; „od”
  ≥ budżetu nie jest pokazywane), lustro frontu `lib/job-budget.ts`
  (`formatJobBudgetLabel` → „60,00–80,00 PLN/h” / „do 80,00 PLN/h”).
  PATCH: wysłane „od” ≥ budżetu = 422; obniżenie samego budżetu poniżej „od”
  czyści „od” (też edycja stawki w Championie).
- **Goły przedział w mailu** („Stawka: 60-80”, obie liczby 30–400) to
  podpowiedź z prośbą „Sprawdź” (`champion_intake.bare_hourly_range`, odczyt
  requestu i szkic AI Championa — tam `rate_raw` dostaje kanoniczne
  „60–80 zł/h”). Pojedyncza goła liczba dalej nie jest budżetem (REC-07).
- Brief „Po ludzku” mówi „Od 60 do 80 zł…”; klucz `budget_pln_hourly_b2b_net_min`
  jest w wejściu tylko przy przedziale (hash innych briefów bez zmian).
- **Dni w biurze zostają jedną liczbą — maksimum** (decyzja 06.10.2026): przy
  wpisie miesięcznym 4 i 6 dni dają tę samą liczbę tygodniową w bramkach.
  Pole ma podpowiedź „wpisz górną liczbę”.
