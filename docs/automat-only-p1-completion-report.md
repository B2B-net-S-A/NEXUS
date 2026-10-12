# Automat przydziału dobiera rekrutera tylko do requestów P1 — raport z wdrożenia

12.10.2026. Reguły: `docs/claude/rekrutacja-tablica/przydzial-ludzi-do-requestow-stany-requestu-i.md`
(punkt „Automat dobiera i proponuje ludzi tylko do requestów P1”).

## Po co

Head of Recruitment zgłosił: zdejmuje rekrutera z requestu P2 na pulpicie
„Requesty i obłożenie”, a po chwili przy requeście jest ktoś inny. Prosił, żeby
automat dodawał rekrutera tylko przy P1.

## Przyczyna

- Pętla automatu (`tasks/recruitment_allocation.allocation_loop`) woła planer co
  30 s.
- Planer obsadzał każdy request z puli, przy którym nikt nie pracował. Priorytet
  ustawiał tylko kolejność; jedyną bramką było „Przyjmujemy kandydatów”.
- Ręczne zdjęcie blokuje parę (request, osoba), nie request — ta sama osoba nie
  wracała, ale planer brał następną najmniej obłożoną. W trybie `auto` stawała
  się od razu prowadzącą i dostawała dzwonek.

## Co weszło

- `backend/app/services/request_allocation_plan.py` — `RequestInfo.automat_assigns`
  (P1 i nie „Przyjmujemy kandydatów”); nowe przydziały i propozycje tylko dla
  takich requestów; żywa propozycja przy innym requeście jest zwalniana z powodem
  `not_p1`, więc tryb `auto` jej nie aktywuje. Osoby już przypisane zostają.
- Urlop nie zwalnia osoby z requestu innego niż P1 (znalezione w przeglądzie
  kodu): nikt by jej nie zastąpił, a zwolnienie automatu jest trwałe. Dziś to
  ścieżka uśpiona (urlopy z Compassa są wyłączone), po ich włączeniu jeden
  dzień urlopu zdejmowałby osobę z jej requestów P2 na stałe. „Poza
  przydziałem”, brak kategorii i nieaktywne konto zwalniają jak dotąd, tylko
  bez następcy.
- `backend/app/services/new_job_leads.py` — „Automat przydziela…” w „Nowe
  rekrutacje — kto prowadzi” tylko dla P1.
- Front, jedna reguła `automatAssigns` w `lib/request-priority.ts`:
  nagłówek pulpitu (oba tryby), potwierdzenie zdjęcia ostatniej osoby
  (`refillNote`: P1 dostanie kolejną osobę, P2 zostanie bez rekrutera), pole
  „Rekruter” przy przekazaniu do searchu i na `/jobs/new`, panel „Zespół”,
  okno ponownego otwarcia, opis w „Kategoriach kompetencji”.
- Harness `/preview/request-allocation?mode=auto` — pulpit w trybie, w którym
  działa produkcja.
- Bez migracji i bez zmian w danych.

## Czego zmiana nie robi

- Nie zdejmuje osób, które automat przypisał do P2 przed wdrożeniem. Zdejmuje
  je człowiek; po zdjęciu nikt nie jest dokładany.
- Nie zmienia P1: po ręcznym zdjęciu ostatniej osoby automat dobierze kolejną
  (okno potwierdzenia to mówi).
- Nie blokuje przekazania do searchu z opcją automatu przy P2 — pole mówi, że
  rekrutacja zostanie bez rekrutera.

## Testy

- `backend/tests/test_request_allocation_plan.py` — nowe przypadki padały na
  starym planerze (5 z 7, potem 2 z 3 dla urlopu) i przechodzą po zmianie;
  cały plik: 48 zielonych (lokalnie, bez bazy).
- `backend/tests/test_audit_r4_recruitment.py`, `test_request_allocation_proposals.py`,
  `test_board_tasks.py` — dopasowane; testy z bazą biegną w CI.
- Front: vitest na zmienionych modułach i ich zależnych testach, `tsc --noEmit`,
  eslint na zmienionych plikach.
