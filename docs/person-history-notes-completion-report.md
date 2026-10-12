# Historia notatek osoby w panelu rekrutacji — raport

Gałąź `claude/historical-notes-display-02eec6`, 12.10.2026. Makiety:
https://claude.ai/artifact/Pm2abFRkegL3rM3CZedKsx. Reguły: `docs/claude/screening-notatki/historia-osoby-w-panelu-rekrutacji.md`.

## Skąd zmiana

Zgłoszenie Artura 12.10.2026: „historyczne notatki się nie wyświetlają”. Zakładka „Notatki i historia” w panelu
osoby i sekcja „Notatki” wąskiego doku pytały o `GET /api/notes?candidate_id=&job_id=`, czyli wyłącznie o notatki
bieżącej rekrutacji. Notatki z innych rekrutacji i bez rekrutacji były tylko w profilu → Historia.

Pomiar na produkcji 12.10.2026 (odczyt, same liczby, bez danych osób):

| | Liczba |
|---|---|
| Otwarte karty w otwartych rekrutacjach | 3 433 |
| Karty bez notatki człowieka w tej rekrutacji | 2 187 |
| …z nich osoba ma notatki ludzi gdzie indziej | 1 417 |
| Notatek poza rekrutacją na taką kartę | mediana 7, p90 38, maks. 137 |
| Notatki ludzi bez rekrutacji (z tego import z Traffita) | 20 853 (20 451) |
| Otwarte karty z luźną notatką z Traffita napisaną po wejściu do tej rekrutacji | 383 (954 notatki) |
| Notatki na zamkniętych kopiach po scaleniu 27 duplikatów (otwarte karty) | 12 (8) |

## Decyzje Artura (12.10.2026)

| | Decyzja |
|---|---|
| Wariant | B („Wcześniej u nas” w zakładce) + C (historia w dużej strefie po lewej), trzy PR-y po kolei |
| Licznik | Notatki ludzi, bez wpisów automatów |
| Odstępstwo od makiety B | Jeden przełącznik „Rozmowy · Wszystko” zamiast „Pokaż pozostałe N” w każdej grupie i osobnego przełącznika automatów |

## PR 1 — „Wcześniej u nas”, licznik, wąski dok, ruchy pary

- **Jedno zapytanie o notatki osoby** (`pages/candidate-notes-query.ts`, klucz i adres jak „Historia” profilu).
  Podział na tę rekrutację i wcześniejsze oraz grupy po rekrutacji liczy `person/notes-by-recruitment.ts`.
- **`person/PersonNotesHistory.tsx`**: „W tej rekrutacji” i „Wcześniej u nas” (grupy od najświeższej notatki,
  najnowsza otwarta; nagłówek z klientem, okresem, najdalszym etapem, powodem i plakietką wyniku). Wariant doku:
  notatki tej rekrutacji, dwie ostatnie rozmowy z innych i „Cała historia (M)”.
- **Wynik rekrutacji** z `GET /api/candidates/{id}/history` osobnym zapytaniem (`pages/candidate-outcomes-query.ts`);
  bez wiersza historii grupa nie ma plakietki.
- **Licznik**: liczba notatek ludzi na zakładce (tekstem — plakietka zrzucała zakładkę do drugiego rzędu
  w kolumnie 460 px) i podpis doku „N tu · M wcześniej”.
- **Ruchy pary**: `GET /api/pipeline/job/{job_id}/moves?candidate_id=` (filtr w CTE) i wspólny
  `recruitment/JobMoveLog.tsx`; „Historia w tej rekrutacji” pokazuje „z etapu → na etap”, osobę i godzinę.
- Strażnicy: trzy wpisy w spisie funkcji rekrutacji, przewodnik `jobs.person` z nową pułapką i stempel,
  harness `/preview/job-detail` z fikcyjną historią, scenariusz e2e.

### Weryfikacja PR 1

- `npx vitest run` na katalogach `person`, `jobs/__tests__`, `recruitment`, `candidate-profile`,
  `app/preview/__tests__`, `app/jobs` i strażnikach spisu funkcji — zielone; `npm run type-check` i `eslint` czyste.
- `ruff check` / `ruff format --check` na `api/pipeline.py` i teście — czyste. Testy z bazą
  (`test_pipeline_job_moves.py`, `test_raw_sql_prepares.py`) sprawdza CI.
- `/preview/job-detail` przeklikane w Chromium (Playwright) przy 1280 × 720, 1536 × 864 i 1280 × 650:
  pasek zakładek w jednym rzędzie także z licznikiem „99+”, grupy z wynikiem, przełącznik „Wszystko”,
  wąski dok z podpisem „0 tu · 8 wcześniej” i przyciskiem „Cała historia (8)”, brak poziomego przewijania.
- e2e `responsive-preview.spec.ts`: nowy scenariusz „Notatki i historia…” oraz „pasek zakładek stoi w miejscu”
  i „wąski dok osoby przewija się w całości” — zielone na lokalnym serwerze.

## PR 2 i PR 3

Dopisywane w kolejnych PR-ach: „Historia osoby (N)” w dużej strefie po lewej oraz Screening „zanim zadzwonisz”.

## Poza zakresem

- Podpięcie luźnych notatek z Traffita do rekrutacji (`POST /api/admin/traffit/notes-repair/recruitments`) —
  zapis na produkcji, decyzja Artura; interfejs pokazuje je w grupie „Bez rekrutacji”.
- 12 notatek na zamkniętych kopiach po scaleniu duplikatów — ewentualna jednorazowa poprawka danych.
