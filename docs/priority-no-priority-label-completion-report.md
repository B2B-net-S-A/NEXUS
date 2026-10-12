# Poziom priorytetu „Bez priorytetu” zamiast „P2 Standard” — raport z wdrożenia

12.10.2026. Reguły: `docs/claude/rekrutacja-tablica/role-przy-rekrutacji-delivery-lead-rekruter.md`
(punkt „Priorytet wrócił w trzech poziomach”).

## Po co

Delivery Lead zgłosił, że po minięciu terminu nie może zdjąć priorytetu
z rekrutacji: przełącznik wymaga jednego z trzech poziomów, a żaden nie pasuje.

## Przyczyna

- Środkowy poziom (`p2`, w bazie `medium`) działał już jak brak priorytetu: nie
  ma plakietki, automat nie dobiera do niego ludzi, sortowanie „Wymaga uwagi”
  go nie podbija. Nazywał się jednak „P2 Standard”, więc czytał się jak
  kolejny priorytet.
- W Traffit priorytet był tagiem („P1 – URGENT”, „WILL ACCEPT CANDIDATES”),
  który dało się zdjąć. NEXUS nazwał brak tagu osobnym poziomem.
- Stan na produkcji w dniu zmiany: 207 otwartych rekrutacji, 180 na poziomie
  środkowym, 23 w P1 (żadna po terminie), 4 w „Przyjmujemy kandydatów”.

## Co weszło

- `frontend/src/lib/request-priority.ts` — pełna i krótka nazwa poziomu `p2` to
  „Bez priorytetu”. Z tego źródła biorą ją: panel „Zespół”, `/jobs/new`, filtr
  listy, filtr pulpitu „Requesty i obłożenie” i filtr „Nowe rekrutacje — kto
  prowadzi”.
- `frontend/src/components/v2/jobs/JobsFilterBar.tsx` — podpowiedź filtra:
  „Rekrutacja bez plakietki nie ma priorytetu.”
- Opis parametru `priority_level` w `GET /api/jobs`, docstring
  `services/job_priority.py`, wpis `team.priority` w inwentarzu funkcji, stempel
  przewodnika `jobs.list`.
- Bez migracji i bez zmian w danych.

## Czego zmiana nie robi

- Nie zmienia kluczy ani wartości: `p2`, `medium`, adres `prio=p2` i zapisane
  filtry działają jak dotąd.
- Nie zmienia żadnej reguły: automat dalej dobiera ludzi tylko do P1, P1 stoi
  na górze „Wymaga uwagi”, nowa rekrutacja zaczyna od P1, priorytet nie spada
  sam po terminie.
- Nie dodaje czwartego poziomu ani odznaczania kliknięciem (warianty B i C
  z makiet zostały odrzucone).

## Testy

- Front: `request-priority.test.ts`, `jobs-filter-groups.test.ts`,
  `JobsFilterBar.test.tsx`, `JobSettingsPanel.test.tsx`, `NewJobPage.test.tsx`,
  `AllocationProposalsSection.test.tsx` — oczekują nowej nazwy; test filtra
  sprawdza też nową podpowiedź.
- `segmented-radio.test.tsx` zostaje bez zmian: ma własne dane testowe
  komponentu, niezależne od nazw poziomów.
