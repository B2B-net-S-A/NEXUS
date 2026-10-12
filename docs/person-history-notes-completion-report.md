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

## PR 2 — „Historia osoby (N)” w dużym podglądzie po lewej

- `screening-form/CandidatePreviewPane.tsx`: przycisk „Historia osoby (N)” obok źródeł CV (N = notatki ludzi),
  treść CV w stałym opakowaniu `hidden` + `contents`, historia montowana przy pierwszym otwarciu; stan można
  sterować z zewnątrz (`historyOpen` / `onHistoryOpenChange`). Wybór źródła CV i „Szukaj w CV” zamykają historię.
- `person/PersonNotesHistory.tsx`, wariant `reader`: wszystkie notatki osoby pogrupowane po rekrutacji
  („Ta rekrutacja” pierwsza), grupy rozwinięte, pigułki Rozmowy / Próby kontaktu / Delivery Lead / Maile /
  Automat / Wszystko z licznikami serwera, tylko do odczytu.
- Edytor CV: `showHistory={false}`; przegląd DL bez zmian (nie dostaje historii).
- Harness `/preview/screening-form` zasiany notatkami i wynikami rekrutacji; strażnik `harness-seeds`,
  wpis `preview.person-history` w spisie funkcji, scenariusz e2e.

### Weryfikacja PR 2

- vitest: `CandidatePreviewPane` (24, w tym: historia nie montuje CV drugi raz, „Szukaj w CV” ją zamyka,
  `showHistory={false}` nie pyta o notatki), `PersonNotesHistory` (13), `app/preview/__tests__`, `cv-editor`,
  `ScreeningWorkbench`, `heavy-bundle-boundaries` — zielone; `npm run type-check`, `eslint` czyste.
- Chromium (Playwright): `/preview/screening-form?state=nowi` przy 1280 × 720 (strona CV 703 px przed
  i po powrocie z historii, 2 strony zamontowane przez cały czas) i 1760 × 950 (dwa podglądy naraz);
  `/preview/job-detail` — przycisk w zakładkach Screening, Rozmowy, Umowa i Notatki, jeden widoczny podgląd;
  `/preview/dl-review?layout=panel` i `/preview/cv-editor` — bez przycisku.

## PR 3 — Screening „zanim zadzwonisz”

- `screening-form/BeforeCallProfile.tsx`: „Warunki — co już wiemy” (ostatnio podana stawka z miesiącem,
  dostępność ze „stan na”, tryb pracy) i „Wcześniej u nas” (ostatnia zakończona rekrutacja z wynikiem
  i powodem, liczba wcześniejszych notatek, „Pokaż”, uwaga o wieku danych po 6 miesiącach).
- `jobs/ScreeningWorkbench.tsx`: „Pokaż” otwiera „Historię osoby” w podglądzie obok (zakładka CV).
- `screening-form/ScreeningFullForm.tsx` + `screening/ScreeningSuggestionChips.tsx`: podpowiedź dostępności
  z notatek pod polem „Dostępność”, tryb z profilu pod „Trybem pracy”; blok stawki bez zmian w treści.
- Harnessy (profil kandydata i historia stawek), strażnik `harness-seeds`, wpis
  `screening.before-call-earlier`, stempel przewodnika `jobs.person`.

### Weryfikacja PR 3

- vitest: `BeforeCallProfile` (6, nowy plik), `ScreeningFullForm` (22, w tym trzy nowe), `ScreeningWorkbench`
  (15, w tym „Pokaż”), `CandidatePreviewPane`, `app/preview/__tests__` — zielone; `npm run type-check`, `eslint`.
- Chromium (Playwright): `/preview/screening-form?state=nowi` i `?state=filled` przy 1280 × 720.

## Sprawdzenie na produkcji

- PR 1 (B2B-net-S-A/NEXUS#2152): scalony 12.10.2026 22:16 UTC, `/api/health` → `94b2e1e69`. Dla otwartej karty
  bez notatek w rekrutacji `GET /api/notes?candidate_id=` oddał 8 notatek ludzi (0 z tej rekrutacji,
  2 rekrutacje i 2 bez rekrutacji) — tyle samo co SQL; `GET /api/pipeline/job/{id}/moves?candidate_id=` oddał
  3 ruchy tej pary (SQL: 3), a bez filtra dalej 113.

## Poza zakresem

- Podpięcie luźnych notatek z Traffita do rekrutacji (`POST /api/admin/traffit/notes-repair/recruitments`) —
  zapis na produkcji, decyzja Artura; interfejs pokazuje je w grupie „Bez rekrutacji”.
- 12 notatek na zamkniętych kopiach po scaleniu duplikatów — ewentualna jednorazowa poprawka danych.
