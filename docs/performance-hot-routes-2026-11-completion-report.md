# Wolne trasy w szczycie 18.11.2026 — pomiar, przyczyna, poprawki

Zgłoszenie 18.11.2026 ok. 13:10: NEXUS „strasznie muli”, Tablica pokazuje
„Nie udało się pobrać danych” (timeout frontu 30 s, `lib/http-timeouts.ts`).

## Pomiar

Źródło: linie `http_outcome` i `runtime_metrics` procesu web z produkcji
(`prod_readonly.py logs`, tylko te dwa rodzaje JSON-ów, odczyt za zgodą Artura).
Rotacja logów kontenera (json-file 10 MB × 5) trzyma ok. 80 minut, a Loki nie ma
odczytu z laptopa, więc okno to **18.11.2026 12:02–13:24 Warszawa**, czyli sam szczyt:
26 553 żądania, 663 powyżej 10 s, **56 powyżej 30 s na 23 różnych trasach**.
Dalsza część dnia (do 18:00) jest dociągana co 30 min do prywatnego katalogu sesji.

Czasy w sekundach. „zapyt.” = średnie `db_statements`.

| Trasa | wywołań | łącznie | p50 | p95 | maks. | zapyt. | >10 s | >30 s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `GET /api/pipeline/kanban/{job_id}` (Tablica) | 983 | 3664 | 1,1 | 18,2 | 39,2 | 94 | 108 | 9 |
| `GET /api/board-tasks/cv` (dzwonek CV, pasek) | 1380 | 2805 | 1,0 | 6,7 | 34,5 | 27 | 25 | 2 |
| `GET ""` (korzenie routerów: board-tasks, request-board, jobs, candidates…) | 1531 | 1889 | 0,3 | 5,1 | 68,5 | 22 | 25 | 2 |
| `GET /api/jobs/{id}/pipeline-scores` (Tablica) | 447 | 1623 | 2,1 | 12,2 | 33,7 | 21 | 42 | 1 |
| `POST /api/candidates/{id}/cv` ¹ | 80 | 1555 | 18,1 | 36,3 | 114,1 | 61 | 70 | 7 |
| `POST /api/candidates/from-cv` ¹ | 78 | 1265 | 14,7 | 29,1 | 34,9 | 58 | 69 | 3 |
| `GET /api/review-batch/me` (pasek) | 698 | 1137 | 0,2 | 9,9 | 30,8 | 37 | 35 | 1 |
| `GET /api/interview-cycle` (pasek, pulpit co 60 s) | 499 | 781 | 0,3 | 8,4 | 32,1 | 26 | 17 | 1 |
| `GET …/summary` (głównie `my-people/summary`, pasek) | 352 | 626 | 0,6 | 8,6 | 25,0 | 17 | 12 | 0 |
| `GET /api/jobs/{job_id}` | 739 | 626 | 0,2 | 4,2 | 25,2 | 20 | 5 | 0 |
| `GET /api/kpis/me/today` (pasek) | 805 | 616 | 0,1 | 3,2 | 28,7 | 8 | 8 | 0 |
| `GET /api/candidates/{id}/also-fits` | 115 | 613 | 3,5 | 11,5 | 37,6 | 149 | 11 | 1 |
| `GET /api/notifications/chats` (pasek) | 431 | 611 | 0,2 | 7,1 | 26,3 | 11 | 9 | 0 |
| `GET /api/notifications/jobs` (pasek) | 602 | 585 | 0,2 | 4,3 | 26,6 | 8 | 8 | 0 |
| `GET /api/pipeline/my-next-steps` (pulpit) | 57 | 576 | 5,5 | 36,7 | 52,8 | 400 | 16 | 4 |
| `POST /api/pipeline/move` | 99 | 494 | 0,6 | 37,8 | 96,9 | 129 | 10 | 6 |
| `GET …/status` (głównie `candidate-contact/status`) | 308 | 483 | 0,5 | 6,3 | 22,2 | 5 | 9 | 0 |
| `GET /api/p0-jobs` (pasek) | 317 | 452 | 0,4 | 6,2 | 22,4 | 12 | 7 | 0 |
| `GET /api/board-tasks/dl-send` (DL) | 448 | 449 | 0,4 | 3,7 | 11,3 | 10 | 2 | 0 |
| `GET /api/candidates/{id}/recommendations` | 249 | 401 | 0,8 | 4,2 | 38,6 | 356 | 5 | 2 |
| `GET …/config` (głównie `hr/config`) | 209 | 388 | 0,5 | 9,9 | 24,2 | 18 | 10 | 0 |
| `GET /api/auth/me` | 235 | 381 | 0,6 | 5,5 | **31,6** | **4** | 5 | 1 |
| `GET /api/users/me/preferences` | 216 | 361 | 0,7 | 6,3 | 18,2 | 4 | 6 | 0 |

¹ `duration_ms` obejmuje zadanie w tle (`BackgroundTasks` z odczytem CV biegnie
wewnątrz middleware'u, po wysłaniu odpowiedzi), więc to praca procesu web, a nie
czas czekania użytkownika. Front nie woła `POST /{id}/cv` (wtyczka albo klient zewnętrzny).

Logowane `route` to ścieżka względem routera, więc `GET ""`, `/summary`, `/status`
i `/config` łączą kilka tras; przypisanie do ekranów z wywołań w `frontend/src`.

## Przyczyna: pełne zbiórki GC, nie zapytania tras

`GET /api/auth/me` ma 4 zapytania, a trwało do 31,6 s. Wolne są wszystkie trasy naraz,
bo stoi cały proces. `runtime_metrics` minuta po minucie:

- `loop_lag_ms_p99` jest równe `gc_gen2_ms_max` w każdej minucie z co najmniej dwiema
  pełnymi zbiórkami (np. 12:01 UTC: 8 zbiórek, maks. 1 446 ms przy lagu 1 446 ms).
  Minuty z jedną albo zerem zbiórek mają lag 12–50 ms.
- W szczycie (12:09–12:12 UTC) **9–10 pełnych zbiórek na minutę po ok. 900 ms**, czyli
  ok. 9,5 s na minutę, w których proces nie obsługuje nikogo. CPU 100–123%.
- Zapytania wszystkich tras w oknie: 582 366, czyli ok. 815 s CPU przy 1,4 ms na zapytanie.

Mechanizm: przy domyślnych progach Pythona (700, 10, 10) obiekty żądania, które czeka
sekundy na pętlę, przeżywają młode zbiórki, trafiają do najstarszej generacji i co kilka
sekund odpalają pełną zbiórkę po całej stercie poza tym, co zamroził start
(`freeze_startup_heap`). Im wolniej, tym więcej obiektów przeżywa i tym częściej.

### Laboratorium na stagingu

`docker exec` w istniejącym backendzie stagingu (kopia produkcji z 18.11, transakcja
read-only, bez `docker run`): import całej aplikacji, zamrożenie jak przy starcie,
8 równoległych `build_kanban_view` dla 7 Tablic (148–1 992 kart) i budzik co 50 ms.

| Progi GC | czas | Tablic | pełnych zbiórek | zatrzymanie łącznie | maks. zbiórka | lag maks. | RSS |
|---|---:|---:|---:|---:|---:|---:|---:|
| domyślne (700, 10, 10) | 90 s | 575 | 69 | 7,6 s | 234 ms | 582 ms | 696 MB |
| 10000, 10, 10 | 90 s | 606 | 10 | 1,2 s | 157 ms | 507 ms | 700 MB |
| 50000, 20, 10 | 90 s | 670 | 0 | 0 | — | 297 ms | 710 MB |
| 50000, 20, 100 | 90 s | 773 | 0 | 0 | — | 181 ms | 707 MB |
| domyślne (700, 10, 10) | 421 s | 2 436 | 288 | 37,5 s (8,9%) | 242 ms | 400 ms | 697 MB |
| 50000, 20, 100 | 421 s | 3 045 (+25%) | 0 | 0 | — | 297 ms | 745 MB |
| 50000, 20, 10 | 422 s | 1 843 ² | 1 | 0,4 s | 379 ms | 460 ms | 710 MB |

Biegi wyżej szły po kolei przy obciążonym laptopie (load 33 od innych sesji), więc liczba
Tablic między wierszami jest zaszumiona (²). Liczba zbiórek od szumu nie zależy. Ten sam
szum dla wszystkich: trzy warianty równocześnie, 6 równoległych Tablic, 240 s:

| Progi GC | Tablic | pełnych zbiórek | zatrzymanie | RSS |
|---|---:|---:|---:|---:|
| domyślne (700, 10, 10) | 1 154 | 135 | 15,4 s (6,4%) | 641 MB |
| **50000, 20, 10 (wybrane)** | 1 265 (+10%) | 1 | 0,16 s | 648 MB |
| 50000, 20, 100 | 1 263 (+9%) | 0 | 0 | 663 MB |

Wybrane `50000,20,10`: ten sam zysk co trzeci próg 100, a pełna zbiórka zostaje możliwa
(cykle śmieci nie leżą w pamięci bez końca).

Pełna zbiórka w laboratorium trwa ok. 240 ms, na produkcji ok. 900 ms: sterta procesu
produkcyjnego poza zamrożeniem jest ok. 4× większa (pamięć procesu po kilku godzinach
ruchu). Żeby to rozpisać, `runtime_metrics` dostaje `gc_frozen`, `alloc_blocks`
(bloki pamięci Pythona) i `cache_entries` (`app.core.cache`).

## Poprawki

| Obszar | Zmiana | PR | Stan |
|---|---|---|---|
| Proces web (wszystkie trasy) | `GC_THRESHOLDS` po zamrożeniu sterty; sprzątanie wygasłych wpisów `app.core.cache` raz na minutę; `gc_frozen`/`alloc_blocks`/`cache_entries` w `runtime_metrics` | PR_GC | w kolejce |
| Tablica (`kanban`, `pipeline-scores`, `move`) | ok. 100 zapytań stałych (nie N+1 po kartach: 97–109 dla Tablic 148–1 992 kart), kilka powtórzonych (`client_family_ids`, `load_modules`, `client_clocks`, `load_followups`, `app_settings` ×3) | karta sesji | do zrobienia |
| Pulpit i pasek (`my-next-steps` 400 zapytań, `review-batch/me`, `interview-cycle` co 60 s poza `polling.ts`, `recommendations` 356) | | karta sesji | do zrobienia |
| Upload CV (`POST /{id}/cv`, `from-cv`, `board-tasks/cv`) | odczyt CV w `BackgroundTasks` procesu web | karta sesji | do zrobienia |

Odpowiedzi API się nie zmieniają: zmiana dotyczy wyłącznie progów GC i usuwania już
wygasłych wpisów cache (których `cache_get` i tak nie oddawał).

## Odpytywanie w tle

Otwarta karta bez klikania: pasek ok. 2,7 GET/min, Tablica 2,9–3,5, pulpit 4,5–5
(najwięcej `interview-cycle` co 60 s z lokalnej stałej `CYCLE_REFETCH_MS`,
`lib/api/interviewCycle.ts:33`, i `review-batch/me` co 120 s literałem,
`lib/api/reviewBatch.ts:172`). Wszystkie odpytywania react-query stoją przy ukrytej
karcie. Bez obsługi ukrytej karty: `AdPublications.tsx:118` (co 10 s unieważnia listę
`/api/jobs` w trakcie publikacji JJIT) i `CvToClientCard.tsx:613` (co 4 s).

## Wieloprocesowy web (etap 2) — osobna decyzja

`docs/claude/podstawy/web-i-worker-osobno.md`, sekcja „Kilka procesów web”: przed
`WEB_CONCURRENCY>1` trzeba przenieść limiter, gniazda (`process_bus` z web), `ALIAS_MAP`
i stany ręcznych backfilli. Daje to drugi rdzeń (serwer ma 8 vCPU), ale nie usuwa pauz GC
w żadnym procesie. Decyzja Artura po pomiarze z nowymi progami.

## Po wdrożeniu

- `/api/health` → SHA z maina: DO_UZUPEŁNIENIA
- Następny szczyt: `gc_gen2_count`, `gc_gen2_ms_max`, `loop_lag_ms_p99`, `rss_mb` i tabela
  tras powyżej 30 s: DO_UZUPEŁNIENIA
