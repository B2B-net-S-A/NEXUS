# Rekrutacja — drobne usprawnienia UX (24.09.2026)

Makiety: https://claude.ai/artifact/1gapo2YTWp7oYbZp9pBdBo (decyzje Artura
24.09: bez kolumny „Co dalej” — lista pokazuje termin; reszta przyjęta).

- *(Od 02.10.2026 ścieżki, „Najbliższego kroku” i paska filtrów nie ma — sekcja „Prostszy ekran rekrutacji”.)*
- **Ścieżka rekrutacji w nagłówku** (`JobRecruitmentPath`,
  `lib/job-recruitment-path.ts`): Zlecenie → Kandydaci → CV do klienta →
  Rozmowy → Umowa + pole „Najbliższy krok” (pierwsza pasująca reguła:
  zlecenie niekompletne → osoby w QC CV → w Zweryfikowanym → propozycje do
  przejrzenia → pusto w Nowych/Screeningu). Liczone z danych, które strona już
  pobiera — bez nowych endpointów. Przycisk „Zlecenie” znika z rzędu, gdy
  ścieżka jest widoczna.
- **Baner Traffita to plakietka w nagłówku** (`ManagedInNexusSwitch`) — ta sama
  bramka i okno potwierdzenia.
- **Tablica:** pasek filtrów i „Zamknięci:” w jednej linii (`DragDropContext`
  obejmuje pasek, bo chipy są celami upuszczenia); puste kolumny wąskie
  (96 px, bez zmiany `droppableId`); podpis „co tu robisz” pod nazwą kolumny
  (`lib/board-column-purpose.ts`, u Nordei wariant Cpro); krok karty
  Zweryfikowany = „Przygotuj CV do QC”, QC = „Popraw CV / wyślij” (lustro
  `services/pipeline_next_action.py` + fixture); plakietka „Twój ruch” albo
  imię/rola osoby z ruchem (`lib/board-card-badges.ts`). Zwykły klik
  w nazwisko otwiera dok, Ctrl/⌘/środkowy — profil w nowej karcie.
- **Dok osoby:** ramka „Następny etap” (`DockNextStage`) czyta
  `move-requirements` i używa tej samej listy co okno „Przesuń dalej”
  (`MoveRequirementList`); link „Profil ↗”; sekcja CV rozróżnia CV firmowe
  i oryginał (`lib/dock-cv-summary.ts`) — „brak pliku” tylko, gdy profil na
  pewno nie ma CV.
- **Okno Zlecenie:** pasek „X z Y gotowe”, budżet PLN/h i tryb pracy
  zapisywane na miejscu (ta sama droga co Champion), reszta braków prowadzi do
  sekcji Championa. Zdania braków rozpoznaje lustro
  `lib/__fixtures__/job-readiness-blockers.json`, pilnowane przez
  `test_job_readiness_blockers_mirror.py` — zmieniasz zdanie bramki handoffu,
  zmień fixture.
- **Propozycje** (`GET /api/jobs/{id}/proposal-facts`,
  `services/proposal_facts.py`): stanowisko, staż, miasto, tryb, dostępność,
  stawka kandydata dla wszystkich ról (decyzja Artura 27.09.2026), historia u tego klienta; bez danych
  kontaktowych, stała liczba zapytań, ≤ 100 osób. „Policz dopasowanie dla N”
  idzie przez `useVisibleMatchScores` (paczki po 20).
- **Ramka „Następny etap” i okno „Przesuń dalej” mają JEDNĄ regułę przycisku**
  (`lib/move-primary.ts`, `planPrimaryStep`): `hand_to_dl`/`hand_to_cpro` =
  przekazanie na etap `primary.target_stage_def_id`, `blocked` = przycisk
  wyłączony z powodem. Wymagania czyta WYŁĄCZNIE `useMoveRequirements` — drugi
  obserwator z atrapą `queryFn` zerował ramkę po `invalidateQueries` (audyt
  24.09.2026).
- **„Mój ruch” = karty z plakietką „Twój ruch”** (`cardNextStep(...).mine`), a
  nawigator doku „N z M” idzie w kolejności widocznej Tablicy
  (`lib/board-dock-order.ts`). U Nordei osoby w kolejce Cpro liczą się osobno
  („N w kolejce Cpro”), nie jako praca w QC.
- **Status „Zamknięta” przy zakresie „Otwarte” przełącza listę na „Wszystkie”**
  (`scopeForStatuses`); stan pracy w wierszu listy to `ROW_STATE_LABEL`
  („Praca: …”). Ponowne otwarcie rekrutacji w NEXUSIE zmienia `finished` na
  `to_review`.
- **Nową stronę dopisz do `SEGMENT_LABELS` w `BreadcrumbV2.tsx`** — test czyta
  katalog `app/` i odrzuca segment bez polskiej nazwy.
