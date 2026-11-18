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
| `my-next-steps` | 6 kont, 15–52 „moich” rekrutacji (limit 25) | 791–1363 (4–27 s, 3,5–8,2 MB) | bez zmian w tym PR-ze | — |
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

## Czego ten PR nie robi

`my-next-steps` zostaje na osobny PR: wersja zbiorcza przepisuje ok. 30 wywołań
w `build_kanban_view`, które w tym samym czasie zmienia PR Tablicy
(sesja „Tablica: mniej zapytań w kanban”). Pomiar „przed” wyżej jest punktem
odniesienia; porównanie JSON musi pominąć pola liczone z zegara
(`days_in_stage`, `entry_autofill.known.last_note_days`), które różnią się
między dwoma biegami kilka minut od siebie także bez zmian w kodzie.
