# Kolejka w kolumnie i filtr „Kto dodał” — raport

Gałąź `claude/nexus-candidate-stage-filters-d6e654`, 14.10.2026. Reguły: `docs/claude/rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md`,
sekcja „Kolejka w kolumnie i filtr „Kto dodał””. Makiety i decyzje D1–D5: https://claude.ai/artifact/XdnEDtUXR7PRm7TtJhn4kj.

## Skąd ta zmiana

Prośba rekrutera przekazana przez Artura: przy screeningu chce widzieć tylko osoby, które sam dodał, i przechodzić
strzałkami tylko po jednym etapie. W rekrutacji 383089 (produkcja, odczyt 14.10.2026) panel pokazywał „1 z 66”,
choć w „Nowych” było 43; 23 z nich dodała jedna osoba. Filtra nie było od 02.10.2026 (pasek filtrów zdjęty).
Artur zatwierdził D1–D5.

## Co się zmieniło

- **D1 — strzałki po kolumnie.** „‹ N z M ›” chodzi po kolumnie otwartej osoby (z etapami złożonymi w tę kolumnę),
  z filtrem „Kto dodał”. Za licznikiem nazwa kolejki („Nowi · dodani przez Ciebie”) — klik otwiera menu filtra.
  Przejście po odrzuceniu i „Zrezygnował” bierze tę samą kolejkę; po ostatniej osobie kolumny panel się zamyka.
  Osoba, która wypadła z kolejki, ma „Wróć do kolejki ›”.
- **D2 — „Kto dodał”.** Jeden przycisk w linii faktów nagłówka rekrutacji. Menu: Wszyscy, Ty, pozostałe osoby
  od największej liczby, Brak danych. Karty innych znikają z kolumn w toku; licznik „N z M”; kolumna pusta przez
  filtr mówi to i ma „Pokaż wszystkich (M)”. Zamknięci, kafle i liczby DL bez filtra.
- **D3 —** filtr tylko w adresie `?added_by=<numer>|none`, zapis przez `useUrlWriter`.
- **D4 —** na ostatniej osobie pasek „To ostatnia z N osób w kolejce.” z „Od pierwszej”, „Wszyscy (N)”
  i „Dalej: <kolumna> (K) ›”.
- **D5 —** „dodał” = osoba z pierwszego wpisu etapu pary; backend podaje `added_to_job_by_id` w odpowiedzi Tablicy.
- Przeciąganie przy filtrze bierze kartę po `draggableId`; zaznaczenie ukrytych osób jest czyszczone.
- Pliki: `backend/app/api/pipeline.py`, `backend/app/schemas/pipeline.py`, `frontend/src/lib/board-added-by.ts` (nowy),
  `lib/board-dock-order.ts`, `components/v2/jobs/AddedByFilter.tsx` (nowy), `JobDetailCompactHeader.tsx`
  (`factsTrailing`), `PipelineCandidateDock.tsx`, `pages/KanbanBoardV2.tsx`, `kanban-shared.tsx`, `modals/RejectionV2.tsx`,
  `app/jobs/[id]/page.tsx`, harness `app/preview/job-detail/page.tsx`. Bez migracji.
- Inwentarz funkcji: `board.added-by-filter`, `board.filter-empty-column`, `person.queue-in-column`, `person.queue-end`.
  Przewodniki Jarvisa `jobs.board` i `jobs.person` mówią o filtrze i kolejce; stemple `jobs.board`, `jobs.person`,
  `job.champion` przeliczone.

## Jak sprawdzone

- Frontend: 21 plików testów powiązanych z Tablicą, panelem, nagłówkiem, stroną rekrutacji, inwentarzem i pomocą —
  1038 testów zielonych (`vitest --no-file-parallelism`); `npm run type-check`; eslint zmienionych plików.
  Nowe testy: `board-added-by.test.ts`, `AddedByFilter.test.tsx`, dopiski w `board-dock-order.test.ts`,
  `KanbanBoardV2.test.tsx` (7 przypadków z 14.10.2026 + przepisane oczekiwania „po całej Tablicy”),
  `PipelineCandidateDock.test.tsx`, `JobDetailCompactHeader.test.tsx`, `JobDetailPage.routing.test.tsx`.
- Backend bez bazy: `test_screen_guides_freshness.py`, `test_claude_md_index.py` (22), `test_recruitment_open_visibility.py`
  (19 bez bazy), ruff. Test pola z bazą (`test_jobs_list_needs_action.py`) sprawdza CI.
- Przeklikane na harnessie `/preview/job-detail` w 1280×720: menu „Kto dodał” z liczbami, Tablica z „Ty · 4 z 8”,
  „Nowi 2 z 4”, Screening „0 z 1” z „Pokaż wszystkich (1)”; „Rozwiń” → „1 z 2 · Nowi · dodani przez Ciebie”,
  ostatnia osoba z paskiem i „Dalej: Rozmowa u klienta (1)”, które otwiera zwykły dok.

## Poza zakresem

- „Wzięte przez Ciebie” (rezerwacja „Biorę”) w menu — dopiero, gdy zespół o to poprosi (D5).
- Pamięć filtra między wejściami — świadomie nie (D3).
