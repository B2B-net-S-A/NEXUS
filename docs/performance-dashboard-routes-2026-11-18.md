# Pulpit i pasek: trasy z szczytu 18.11.2026 — pomiar przed/po

Uzupełnienie `docs/performance-hot-routes-2026-11-completion-report.md`
(PR #3579, progi GC). Reguła repo: wolna trasa to liczba zapytań razy kolejka
w pętli, ok. 1,4 ms CPU na zapytanie
(`docs/claude/podstawy/stabilizacja-pod-obciazeniem-reguly-po-audycie-13.md`).

## Produkcja 18.11.2026, 12:02–13:24 (punkt wyjścia)

| Trasa | Wywołania | p95 | Zapytania |
|---|---|---|---|
| `GET /api/pipeline/my-next-steps` | 57 | 36,7 s (maks. 53 s) | śr. 400, maks. 432 |
| `GET /api/candidates/{id}/recommendations` | — | — | 356 |
| `GET /api/review-batch/me` | 698 | 9,9 s | 37 |
| `GET /api/interview-cycle` | 499 | 8,4 s | 26 |

## Jak mierzone

Staging z kopii produkcji, istniejący kontener `nexus-staging-backend-1`
(`docker exec`, bez `docker run` backendu). Drzewo `app/` z `origin/main`
(e6a789fdb) i z gałęzi skopiowane do `/tmp` w kontenerze; ten sam skrypt
woła funkcje tras w sesji z `SET TRANSACTION READ ONLY` i rollbackiem,
liczy instrukcje SQL eventem `before_cursor_execute` i zapisuje odpowiedź JSON.
Wyszukiwanie semantyczne w `recommendations` podmienione na stałą listę
170 otwartych rekrutacji (te same dla przed i po, bez wywołań Voyage/Qdrant).
Czasy na bezczynnym stagingu nie odpowiadają szczytowi — miarą jest liczba zapytań.

## Przed / po (staging)

| Trasa | Konta / kandydaci | Zapytania przed | Zapytania po | JSON |
|---|---|---|---|---|
| `recommendations` | 3 kandydatów, pula 170 rekrutacji | 306–308 | **10** | identyczny (3/3) |
| `my-next-steps` | 6 kont, 15–52 „moich” rekrutacji (limit 25) | 791–1363 (4–27 s, 3,5–8,2 MB) | drugi PR, tabela niżej | — |
| `review-batch/me` | 17 rekruterów, porcja włączona tylko dla pomiaru | mediana 43, maks. 46 (mediana 100 ms) | bez zmian | — |
| `interview-cycle` (`mine`) | 17 rekruterów | mediana 24, maks. 32 (mediana 72 ms) | bez zmian | — |

Na stagingu `REVIEW_BATCH_ENABLED` jest wyłączone, więc bez zmiennej
ustawionej dla procesu pomiarowego trasa robi 1 zapytanie i nic nie mówi.

## Co zmienia ten PR

- **`recommendations`**: `rank_jobs_for_candidate` dostaje `contexts`
  z `build_jobs_scoring_contexts` (screening pary i konflikt z klientem
  hurtem). Wcześniej dwa zapytania na każdą rekrutację z puli.
  Test: `backend/tests/test_candidate_recommendations_query_budget.py`
  (stała liczba przy 3 i 12 rekrutacjach; przed zmianą 19 vs 37).
- **`interview-cycle`**: koniec stałej minuty (`CYCLE_REFETCH_MS`). Klucz
  odpytywał się co 60 s na każdej karcie z pulpitem albo ekranem „Rozmowy
  u klienta” (react-query bierze najkrótszy interwał obserwatorów, więc
  5 min paska nic nie dawało). Teraz `cycleRefetchDelayMs`: tuż po najbliższej
  granicy z danych (start, koniec, kwadrans przed startem, koniec okna
  telefonu, termin zadania), bez granic — `WS_BACKED_SAFETY_POLL_MS` (5 min).
  „Zadzwoń teraz” pojawia się sekundę po końcu rozmowy, nie do minuty później.
  Odświeżenie z gniazda (`useNotifications`, powiadomienia „Rozmowy”) bez zmian.
- **`review-batch/me`**: `REVIEW_BATCH_STATUS_POLL_MS` (5 min) z `lib/polling.ts`
  zamiast literału 120 s. Własne decyzje odświeżają porcję od razu
  (`lib/pipeline-move-invalidation.ts`); gniazdo jej nie odświeża i nie odświeżało.

Szacunek ruchu tła: `review-batch/me` 698 → ok. 280 wywołań na te same
82 minuty (×0,4); `interview-cycle` z pulpitem otwartym 60/h → 12/h na kartę
plus kilka dociągnięć na granicach rozmów w ciągu dnia. Do potwierdzenia
w logach po wdrożeniu.

## `my-next-steps` (drugi PR, 19.11.2026)

Ta sama metoda, drzewo `app/` z `origin/main` 774b3b575 (po PR-ze Tablicy #3587)
i z gałęzi `claude/my-next-steps-hurtem`. Każde konto wołane dwa razy, liczony
drugi bieg.

| Konto | Tablic | Zapytania przed | Zapytania po | Czas przed → po | Odpowiedź | JSON |
|---|---|---|---|---|---|---|
| 14 | 25 | 1287 | **71** | 2,9 s → 1,2 s | 6,6 MB | identyczny |
| 86 | 25 | 1170 | **73** | 2,3 s → 0,6 s | 5,4 MB | identyczny |
| 27 | 25 | 1314 | **94** | 2,7 s → 1,0 s | 8,2 MB | identyczny |
| 101 | 22 | 1080 | **81** | 2,2 s → 0,8 s | 6,0 MB | identyczny |
| 30 | 17 | 831 | **68** | 1,4 s → 0,4 s | 3,6 MB | identyczny |
| 91 | 15 | 763 | **83** | 1,2 s → 0,4 s | 3,5 MB | identyczny |

„Identyczny” = bajt w bajt (`cmp`), także pola liczone z zegara, bo oba biegi
szły minutę po sobie. Pojedyncza Tablica (`/kanban/{job_id}`) idzie tą samą
drogą: 8 Tablic (4 największe, 4 najnowsze, 130 KB–48 MB) — liczba zapytań
bez zmian (44–93), JSON bajt w bajt ten sam.

Zostało 68–94 zapytań, bo stałe są per żądanie, nie per tablica: rozbieżność
między kontami to gałęzie warunkowe (porcja dnia, zatrudnieni, kubełek poza
szablonem, przegląd DL). Na produkcji 18.11 średnio 400 zapytań przy p95
36,7 s — przy ok. 1,4 ms CPU na zapytanie to ok. 0,5 s pętli mniej na każde
wywołanie, plus mniej zajętych połączeń z puli.

Rozmiar odpowiedzi się nie zmienia (3,5–8,2 MB, pulpit składa z pełnych
tablic następny krok karty). To osobna decyzja: odchudzenie odpowiedzi
zmienia kontrakt API pulpitu.

Jak: `build_kanban_view` dzieli się na `_load_kanban_boards` (wszystkie
zapytania, każde raz dla listy rekrutacji) i `_render_kanban_board` (bez
zapytań). `/kanban/{job_id}` woła to z listą jednej rekrutacji, `my-next-steps`
z całą listą (`build_kanban_views`). Helpery serwisów dostały warianty
`*_for_jobs`, a stare funkcje wołają nowe — jedna ścieżka kodu.
Testy: `backend/tests/test_my_next_steps_query_budget.py` (ta sama liczba
zapytań dla 2 i 6 tablic; każda tablica = `build_kanban_view` tej rekrutacji,
osoba na trzech tablicach nie przecieka między nimi) i testy wariantów
`*_for_jobs`. Bramka odczytu (`ensure_job_read_access`) zostaje per rekrutacja.

## Czego pierwszy PR nie robił

`my-next-steps` poszło osobnym PR-em (wyżej): wersja zbiorcza przepisuje ok. 30 wywołań
w `build_kanban_view`, które w tym samym czasie zmienia PR Tablicy
(sesja „Tablica: mniej zapytań w kanban”). Pomiar „przed” wyżej jest punktem
odniesienia; porównanie JSON musi pominąć pola liczone z zegara
(`days_in_stage`, `entry_autofill.known.last_note_days`), które różnią się
między dwoma biegami kilka minut od siebie także bez zmian w kodzie.
