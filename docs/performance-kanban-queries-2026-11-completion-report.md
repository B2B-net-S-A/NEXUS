# Tablica: mniej zapytań na żądanie (18.11.2026)

Ciąg dalszy `docs/performance-hot-routes-2026-11-completion-report.md` (PR #3579,
przyczyna główna: pełne zbiórki GC). Tu wiersz „Tablica”: `GET /api/pipeline/kanban/{job_id}`,
`GET /api/jobs/{id}/pipeline-scores`, `POST /api/pipeline/move`.

Produkcja 18.11.2026 12:02–13:24: kanban 983 wywołań, p95 18,2 s, maks. 39 s, średnio
94 zapytania; `pipeline-scores` 447 wywołań, p95 12,2 s, 21 zapytań; `move` p95 37,8 s,
maks. 97 s, 129 zapytań. Reguła repo: wolna trasa = liczba zapytań × kolejka w pętli,
ok. 1,4 ms CPU na zapytanie (`docs/claude/podstawy/stabilizacja-pod-obciazeniem-reguly-po-audycie-13.md`).

## Jak mierzone

Staging z laptopa (kopia produkcji `nexus_staging_nightly_20261118`), `docker exec`
w istniejącym `nexus-staging-backend-1`, kod skopiowany do `/tmp/kb_base` (main
`e6a789fdb`) i `/tmp/kb_branch` (ta gałąź), `PYTHONPATH` na kopię, sesja
`SET TRANSACTION READ ONLY`. Zapytania liczy listener `before_cursor_execute`, miejsce
w kodzie z ramek `greenlet.getcurrent().parent.gr_frame`. Odpowiedź: sha256
`json.dumps(view.model_dump(mode="json"), sort_keys=True)`; `days_in_stage` liczone od
stałego punktu w czasie (inaczej bieg minutę później zmienia je na kartach z rocznicą
ruchu). Każda Tablica dwa razy, w tabeli drugi bieg (ciepłe cache procesu).

## Kanban — `db_statements` i czas przed/po

| Rekrutacja | Karty | Zapytania przed | po | Czas przed [ms] | po [ms] | JSON (rekruter / admin) |
|---|---:|---:|---:|---:|---:|---|
| 789163 | 656 | 97 | 90 | 368 | 474 | ten sam / ten sam |
| 789167 | 407 | 93 | 89 | 585 | 231 | ten sam / ten sam |
| 209102 | 79 | 93 | 82 | 190 | 101 | ten sam / ten sam |
| 454615 | 254 | 101 | 90 | 282 | 171 | ten sam / ten sam |
| 4235 | 137 | 79 | 70 | 176 | 101 | ten sam / ten sam |
| 3471 (zamknięta) | 1 961 | 66 | 44 | 687 | 604 | ten sam / ten sam |

Czas na laptopie z kilkunastoma kontenerami waha się ±50% między biegami (ten sam kod
dawał 260 i 604 ms) — miarą jest liczba zapytań, nie milisekundy. Na Tablicach są
odznaki, które zmiana dotyka (789163: 142 follow-upy, 10 terminarzy rozmów, markery
zatrudnienia), więc porównanie JSON-a sprawdza też ścieżki z danymi.

### Co odpadło

| Zapytania | Zmiana |
|---|---|
| nazwiska `users.id, users.name` ×3–4 → 1 | jedna lista id (dodający, właściciele, ruch mimo braków, dzwoniący z follow-upu), jedno zapytanie; nazwiska dzwoniących dalej osobną mapą |
| `pipeline_stage_defs` ×2–3 → 1 | katalog etapów (`board_tasks._catalog`, 44 wiersze) raz: kolumny Tablicy, etapy spoza szablonu i reguła follow-upu |
| `pipeline_templates` (domyślny) ×2 → 1 | Tablica bez własnego szablonu podaje swój id do follow-upów |
| `clients` rodzina klienta ×2 → 1, a bez umów 0 | `family_loader` dzielony przez „Zatrudniony bez umowy” i „Pracuje u nas”; markery nie czytają rodziny, gdy nikt na Tablicy nie ma umowy |
| `cv_generated_documents` ×2 → 1 | `cv_auto_review.job_stages_auto_cv`: gotowe i „w przygotowaniu” jednym zapytaniem |
| `jobs` w `company_cv_refs` ×2 → 1 | data rekrutacji i nazwa klienta jednym złączeniem |
| `load_snapshots`: `jobs` + najnowszy etap → 0 | Tablica podaje najnowszy etap par i stan rekrutacji, które już ma |
| follow-upy 16–17 → 0 albo 15 | liczone tylko dla kart w kolumnach „czeka na klienta” opublikowanej, niezakończonej rekrutacji (`board_waiting_ids`, ta sama reguła kolumny co `_WAITING_SQL`); wynik dla tych osób ten sam, bo liczy się per osoba |

Zostało ok. 70–90 zapytań w ok. 40 serwisach, po jednym–kilka na serwis (największe:
follow-upy 13, `review_batch.recruiter_ids_for_jobs` 7, terminarz 7, markery 6, zegary
klienta 5). Dalsze cięcie to łączenie zapytań różnych serwisów, nie powtórzenia.

Test: `backend/tests/test_kanban_query_budget.py` — ta sama liczba zapytań dla Tablicy
z 2 i 8 kartami w każdym etapie, sufit 90, nazwiska / definicje etapów / domyślny szablon
/ rodzina klienta / auto-CV najwyżej raz, reguła `board_waiting_ids`.

## `pipeline-scores` — pomiar, bez zmiany

| Rekrutacja | Karty | Zapytania | Czas [ms] (ciepło) | `batch` [ms] |
|---|---:|---:|---:|---:|
| 789163 | 656 | 34 | 527 | 514 |
| 454615 | 254 | 11 | 954 | 936 |
| 209102 | 79 | 11 | 235 | 225 |

11 zapytań na paczkę 256 kart (`evaluate_batch`, wspólny z pełnym wyszukiwaniem). Czas to
CPU ewaluatora (`sql_load`, `eligibility`, `scoring`), nie liczba zapytań; pierwszy bieg
dokłada wektor zapytania (0,4–1,1 s). Do zrobienia osobno (obszar wyszukiwania).

## `move` — pomiar fazy odczytów, bez zmiany

Read-only nie przepuszcza `SELECT … FOR UPDATE`, więc sonda zdejmuje samą klauzulę
blokady i liczy zapytania do pierwszego `INSERT`: 16 (→ Screening), 20 (→ Rozmowa
u klienta), 46 (→ Zweryfikowany, bramki wymagań). Reszta ze średnich 129 to zapisy
i efekty po commicie (`run_move_effects`) — bez zapisu na stagingu ich nie zmierzę.

Ważniejsze niż liczba zapytań: każdy ruch blokuje wiersz rekrutacji
(`recruitment_process_commands.py:1040`, `select(Job)…with_for_update()`) i trzyma
blokadę do commita, więc ruchy w tej samej rekrutacji idą jeden po drugim. Przy pauzach
GC po ~900 ms kolejka na jednej rekrutacji tłumaczy maks. 97 s lepiej niż 129 zapytań.
Do zrobienia osobno (pomiar z zapisem i czas oczekiwania na blokadę).

## Po wdrożeniu

- `/api/health` → SHA z maina z tą zmianą: DO_UZUPEŁNIENIA
- Szczyt 19.11: `db_statements` i p95 kanbanu z logu `http_outcome`: DO_UZUPEŁNIENIA
