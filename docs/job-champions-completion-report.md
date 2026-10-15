# Championi rekrutacji — raport z wdrożenia (D1–D9, 15.10.2026)

Zgłoszenie DL i rekruterów (przez Artura): Delivery Lead nie wiedział, gdzie
oznaczyć „Mamy championa” (menu „⋯”), rekruterzy nie wiedzieli, czy champion
jest i kto nim jest, a rekrutacja z championem dalej wyglądała na P1.
Makiety v2 i decyzje: https://claude.ai/artifact/VsMAfe4GgPC3g9LHEx2M1z —
Artur: „tak na D1–D9, wdrażaj”.

## Co działa

| Decyzja | Zachowanie | Gdzie |
|---|---|---|
| D1 | Champion = jedna albo kilka osób; stare flagi bez osób zostają | `job_champions` (0450), `services/job_champions.py` |
| D2 | Jedno miejsce: plakietka statusu → okienko „Championi”; to samo pod „⋯” → „Championi…” | `JobChampionsStatus.tsx`, `JobDetailCompactHeader.tsx` |
| D3 | Widać w czterech istniejących elementach: plakietka statusu, karta Tablicy, panel osoby, dymek na liście | `board-card-badges.ts`, `PipelineCandidateDock.tsx`, `JobListCells.tsx` |
| D4 | Na liście osoby od „CV wysłane” wzwyż; spoza listy = 422 bez zapisu | `job_champion_rules.ELIGIBLE_COLUMNS` |
| D5 | „Nie szukamy”, gdy championi ∪ zatrudnieni ≥ max(headcount, 1) | `job_champion_rules.search_stops` |
| D6 | P1 wstrzymany (sort „Wymaga uwagi”, filtr poziomu, „P1” z pauzą), `jobs.priority` bez zmian | `job_priority.py`, `RequestPriorityChip`, `JobPriorityMenu` |
| D7 | Champion schodzi sam przy zamknięciu karty / usunięciu; ostatni → „Szukamy” + P1 + ludzie wracają | `job_champions.reconcile` po commicie |
| D8 | Dzwonki `champions_changed` i `champion_search_resumed` do rekruterów i DL | `job_champions.notify` |
| D9 | Zapis przy „Do przejrzenia” / „Klient milczy” przestawia na „Szukamy” | `set_champions` → `set_work_state` |

Reguła: `docs/claude/rekrutacja-tablica/podobne-rekrutacje-przepiecia-i-status-requestu.md`,
sekcja „Championi rekrutacji”.

## Weryfikacja

- Lokalnie (bez bazy): `ruff check`/`format` na `app/`, testy reguł, lustra migracji,
  rejestrów dzwonków, macierzy authz (`job_champions.json`), strażników tras,
  kontraktu API v1, indeksu `CLAUDE.md`, projekcji konta podglądu.
- Front: Vitest na zmienionych plikach i strażnikach (644 testy), `npm run type-check`.
- Harness `/preview/job-detail?champion=two|seats|legacy|none` i `/preview/jobs-list-v3`
  przeklikane przy 1280 × 720 (plakietka, okienko DL i rekrutera, karty, panel osoby,
  okno odrzucenia, „Szukamy · 1 z 2”, stara flaga, „⋯ → Championi…”, lista).
- Testy z bazą (`tests/test_job_champions.py` i poprawione `test_job_similar_links.py`,
  `test_audit_r8_allocation.py`) — w CI.

## Przegląd przed PR-em (poprawione)

- Konto podglądu dostawało 500 na detalu (redakcja ustawiała `champions` na `None`
  w polu bez `Optional`) — pola `Optional`, `champion_seats` w redakcji.
- Hak championa brał `allocation_lock` w środku ruchu karty (blokada kandydata
  i klucza rekrutacji już trzymane) — przeniesiony za commit, we własnej transakcji.
- Dobowy dedup dzwonków połykał drugą zmianę listy tego samego dnia — dzwonki
  bez `related_entity_id`.

## Poza zakresem / do wiadomości

- Zatrudnienie z podpisu umowy B2B nie przelicza od razu flagi przy kilku miejscach
  (przeliczy najbliższy zapis listy albo ruch championa).
- Import z Traffita wyłączony (14.10) — jego odrzucenia nie mają haka.
- Scalenie bliźniaczych rekrutacji przenosi championów, flaga celu przelicza się
  przy najbliższej zmianie.
- Ekran „Porządek w requestach” zdejmuje championów starym `POST …/champion-found`
  (`found:false` czyści listę) — działa bez zmian.
- Niepotwierdzone: liczby z produkcji (ile rekrutacji ma dziś flagę, ile ma więcej
  niż jedno miejsce) — odczyt bazy produkcyjnej wymaga zgody Artura.
