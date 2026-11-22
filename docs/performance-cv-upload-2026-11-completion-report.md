# Upload CV i ikona „CV” w szczycie 18.11.2026 — pomiar i poprawki

Część raportu `docs/performance-hot-routes-2026-11-completion-report.md`
(PR #3579, wiersz „Upload CV”). Okno pomiaru jak tam: logi `http_outcome`
z produkcji 18.11.2026 12:02–13:55 Warszawa, odczyt za zgodą Artura.

## Co zmierzono

### `POST /api/candidates/{id}/cv` i `POST /api/candidates/from-cv`

| Składnik | Gdzie biegnie | Czas | Źródło |
|---|---|---:|---|
| Odczyt modelem (`cv_parser`, Sonnet) | wątek puli (`run_in_threadpool`) | p50 16,5 s, p95 26,3 s, maks. 36 s | `ai_provider_calls` 17.11 7:00–16:00 UTC, 180 wywołań, kopia produkcji |
| Ekstrakcja tekstu PDF | `asyncio.to_thread` + podproces | p50 0,39 s, p95 0,85 s, maks. 6,7 s (ścienny) | 60 ostatnich głównych CV, staging, tylko odczyt |
| CPU ekstrakcji w wątku wołającym | wątek | p50 1,3 ms | jw. (`time.thread_time`) |
| Normalizacja odczytu (`_normalize_cv_output` + fallbacki) | pętla zdarzeń | p50 0,5 ms, p95 1,0 ms | jw. |
| Zapytania | pętla zdarzeń | 58–64 zapytania, `db_ms` p50 0,2–0,3 s | `http_outcome` |

Trasa: `POST /{id}/cv` p50 18,6 s (84 wywołania), `from-cv` p50 15,4 s (81).
Prawie cały czas to czekanie na model w wątku, nie CPU w pętli. Nie ma czego
przenosić do `to_thread` ani do workera. `/cv/preview` nie miał w oknie ani jednego
wywołania, więc każde `from-cv` czytało CV modelem (portal i wtyczka, nie ekran
„Dodaj kandydata”).

Dwie rzeczy były jednak złe:

1. **`duration_ms` liczył zadanie w tle.** `POST /{id}/cv` odpowiada od razu,
   a odczyt CV idzie w `BackgroundTasks`, które Starlette wykonuje wewnątrz
   middleware'u. Ranking tras mieszał więc czekanie ludzi z pracą procesu po
   odpowiedzi.
2. **Połączenie z bazą wisiało „idle in transaction” przez cały odczyt modelem.**
   Zapytania kwoty AI (`ai_feature`) idą sesją wołającego, a sesja trzymała
   połączenie przez całe ok. 16 s odpowiedzi modelu: w zadaniu w tle, w `from-cv`
   i w podglądzie.

### `GET /api/board-tasks/cv` (ikona „CV” w pasku)

| Pomiar | Wartość | Źródło |
|---|---:|---|
| Wywołań | 2 064 w 113 min (18,3/min) | `http_outcome` 11:02–12:55 UTC |
| Aktywne konta z ikoną | 25 (18 rekruterów, 7 DL) | kopia produkcji |
| Odczytów na osobę na minutę | 0,73 (odpytywanie co 5 min daje 0,2) | jw. |
| Porównanie: `GET /api/kpis/me/today` (też co 5 min, mało unieważnień) | 1 104 | `http_outcome` |
| Najgęstsze 10 s | 31 odczytów, w tym 16 z tą samą liczbą zapytań (25) w 8 s | `http_outcome` |
| Zapytań na odczyt | rekruter 4–25 (mediana 22), DL 14–34 (mediana 27) | kopia produkcji, 25 kont, bez auth |
| N+1 po wierszach | brak (zapytania hurtowe po parach kandydat–rekrutacja) | lista zapytań |

Ok. 70% odczytów pochodzi z unieważnień, nie z odpytywania. Serie to jeden
klient powtarzający odczyt co 0,2–0,5 s. Każda ramka `pipeline_changed` z innej
rekrutacji ma własne okno debounce, a ramki tematu `cv` unieważniały klucz osobno.
`invalidateQueries` przerywa trwający odczyt i zaczyna nowy, a serwer i tak liczy
każdy z nich.

Rozważone i odrzucone: krótki cache odpowiedzi per osoba (po ramce gniazda
oddawałby stan sprzed zmiany, o której ramka mówi) i łączenie równoległych
odczytów na serwerze (symulacja na logu: najwyżej 11–17% mniej, bo odczyty idą
po kolei, nie równolegle).

## Poprawki

| Obszar | Zmiana | Test |
|---|---|---|
| `http_outcome` | `duration_ms`, `db_statements` i `db_ms` do ostatniego kawałka odpowiedzi. Praca po nim trafia do `background_ms`, `background_db_statements` i `background_db_ms` (tylko gdy ≥ 100 ms albo z zapytaniami) | `tests/test_request_db_usage.py`: surowe ASGI, strumień, FastAPI + `BackgroundTasks` za `BaseHTTPMiddleware` (czerwone przed zmianą) |
| Odczyt CV modelem | `parse_cv(..., release_db_during_model=True)` w zadaniu w tle wgrania CV, w `from-cv` i w podglądzie: `release_idle_connection` po zapytaniach kwoty, przed modelem. Domyślnie wyłączone (narzędzia CLI z `pg_advisory_xact_lock`) | `tests/test_cv_parser.py` |
| Ikona „CV” | `refreshCvTopicFromRealtime` (`frontend/src/lib/cv-topic-refresh.ts`): pierwsza ramka gniazda od razu, kolejne w oknie 2 s jednym odświeżeniem na końcu. W ukrytej karcie tylko oznacza dane jako nieaktualne, a `useCvTopic` pobiera je przy powrocie, tylko gdy coś je unieważniło. Własne akcje odświeżają jak dawniej | `src/lib/__tests__/cv-topic-refresh.test.ts`, `useNotifications.test.tsx` bez zmian |
| Ikona „CV” — zapytania | bez zmian w kodzie. Test pilnuje stałej liczby zapytań (1 i 6 osób w drodze) i górnej granicy (rekruter 32, DL 42 z auth) | `tests/test_board_tasks_cv_query_budget.py` (CI z Postgresem) |

Odpowiedzi API się nie zmieniają, zmienia się tylko kształt linii logu.

## Przed / po

| Pomiar | Przed (18.11, szczyt) | Po |
|---|---:|---|
| `POST /{id}/cv` `duration_ms` p50 | 18,6 s (z odczytem w tle) | DO_UZUPEŁNIENIA (szczyt po wdrożeniu); odczyt w `background_ms` |
| Połączenie trzymane w czasie odpowiedzi modelu | ok. 16,5 s na odczyt CV | 0 s (test kolejności: kwota → zwolnienie → model) |
| Odczyty ikony „CV” na serię 16 ramek w 1,6 s, jedna karta | 16 | 2 (test) |
| Odczyty ikony „CV” na osobę na minutę | 0,73 | DO_UZUPEŁNIENIA (szczyt po wdrożeniu) |
| Zapytania ikony „CV” | rekruter ≤ 25, DL ≤ 34 | bez zmian, pilnuje test |

## Po wdrożeniu

- `/api/health` → SHA z maina: DO_UZUPEŁNIENIA
- Szczyt po wdrożeniu (z tego samego `prod_readonly.py logs`): liczba
  `GET /cv` na minutę, `duration_ms` i `background_ms` dla `POST /{candidate_id}/cv`:
  DO_UZUPEŁNIENIA
