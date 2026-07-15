# Recruitment-assignment filter — completion report

> Filtr kandydatów po przynależności (lub jej braku) do wybranej rekrutacji.
> Commit `df51c92` — `feat(candidates): filter by assignment to a recruitment`.

## Problem

**Jest:** brak sprawdzenia kandydatów przypisanych do danych rekrutacji.
**Ma być:** możliwość przefiltrowania kandydatów po ich przynależności bądź
braku przynależności do danej rekrutacji.

W NEXUS „rekrutacja" = `Job`; przypisanie kandydata do rekrutacji to wiersz w
`candidate_stages` (`CandidateStage`, klucz `candidate_id` + `job_id`). Lista
kandydatów (`/candidates`) miała filtry pul, „dodany przez", „pracował u
klienta", ale nie pozwalała zapytać „kto jest (lub NIE jest) w pipeline tej
rekrutacji".

## Rozwiązanie

Nowy filtr **„Rekrutacja"** w sekcji „Pule i przynależność" panelu Filtry:
multi-select rekrutacji + przełącznik **Przypisani / Nieprzypisani**.

- **Przypisani** (`assigned`, domyślny) — kandydat ma *jakikolwiek* wiersz
  `candidate_stages` dla którejkolwiek z wybranych rekrutacji (dowolny etap, też
  terminalny `rejected`/`withdrawn`). Semantyka jak membership w talent poolu —
  świadomie inna niż filtr „Zatrudnienie" (`employment=at_client`), który patrzy
  tylko na *ostatni* etap `hired`.
- **Nieprzypisani** (`not_assigned`) — dokładne dopełnienie: kandydat nie jest w
  pipeline *żadnej* z wybranych rekrutacji.

Filtr aktywny tylko gdy wybrano ≥1 rekrutację (przełącznik trybu pojawia się
dopiero wtedy). Multi-select = OR po rekrutacjach.

## Zmiany (commit `df51c92`, 6 plików)

### Backend — `backend/app/api/candidates.py`
- Dwa nowe query-paramy w `GET /api/candidates`:
  - `recruitment_id: list[int]` (repeatable, OR-combined),
  - `recruitment_match: "assigned" | "not_assigned"` (default `assigned`,
    walidacja regexem → 422 na innej wartości).
- Predykat `EXISTS (SELECT 1 FROM candidate_stages WHERE candidate_id =
  candidates.id AND job_id IN (...))`, negowany przez `~` dla `not_assigned`.
  Wzorzec skopiowany 1:1 z istniejącego filtra `talent_pool_id`.
- Predykat dokłada się do wspólnego `query` **przed** `SELECT count(...)`
  (linia ~1407), więc zarówno lista, jak i licznik „Pokaż wyniki (N)" są spójne.

### Backend test — `backend/tests/test_candidates_recruitment_filter.py` (nowy)
5 testów (in-process `app_client`): assigned trafia tylko członków pipeline;
not_assigned to dopełnienie; multi-`recruitment_id` = OR; etap terminalny
(`rejected`) wciąż liczy się jako „assigned"; `recruitment_match=bogus` → 422.

> ⚠️ Follow-up: rejestracja tego pliku na liście `pytest` w `.github/workflows/ci.yml`
> wymaga tokena z scope `workflow` (push z obecnego PAT odrzucony przez regułę
> repo). Test jest uruchamialny lokalnie/ręcznie; do dodania jedną linią obok
> `tests/test_candidates_filters.py`.

### Frontend
- `frontend/src/components/v2/filters/RecruitmentMultiSelect.tsx` (nowy) —
  multi-select rekrutacji, korzysta z istniejącego `/api/jobs-lookup`
  (`{id, title}`). Mirror `ClientMultiSelect`. `value` pozycji = `"<title> #id"`
  (unikalność dla cmdk przy zduplikowanych tytułach).
- `frontend/src/components/v2/pages/CandidatesListV2.tsx` — stan `recruitmentIds`
  + `recruitmentMatch`, sync URL, klucz react-query, paramy API, licznik
  aktywnych filtrów, snapshot (saved searches) + `applyFiltersPatch`,
  `resetAllFilters`, oraz JSX: pole „Rekrutacja" + pille Przypisani/Nieprzypisani.
- `frontend/src/lib/url-filters.ts` — pola `recruitmentIds` / `recruitmentMatch`
  w `CandidateFilters` + `DEFAULT_FILTERS`, round-trip URL `recr` / `recr_mode`
  (mode zapisywany tylko dla `not_assigned`), mapowanie na paramy API.
- `frontend/src/lib/__tests__/url-filters.test.ts` — round-trip nowych pól.

## URL / API kontrakt

| Warstwa | Klucz | Przykład |
|---|---|---|
| URL | `recr` (CSV job ids), `recr_mode` | `/candidates?recr=42,7&recr_mode=not_assigned` |
| API | `recruitment_id` (repeat), `recruitment_match` | `?recruitment_id=42&recruitment_id=7&recruitment_match=not_assigned` |

`recr_mode` / `recruitment_match` pomijane gdy `assigned` (domyślne) → brak
szumu w URL i zapytaniu.

## Weryfikacja

- ✅ Frontend `tsc --noEmit` — czysto (wyłapało brakujące pola w teście fixture,
  uzupełnione).
- ✅ Frontend ESLint (zmienione pliki) — 0 errors (2 pre-existing warnings spoza
  zmiany).
- ✅ Backend — AST OK; predykat wzorowany 1:1 na `talent_pool_id`; długości linii
  ≤86 (próg repo ≥88). Ruff/pytest lokalnie niedostępne → gate w CI.
- ✅ Deploy: push `main` → Coolify; `/api/health.version` przeszło na `df51c92`
  (~105 s). Commit potwierdzony jako ancestor `origin/main` (mimo że równoległa
  sesja dorzuciła na wierzch `76df2a3` — moje zmiany są w wdrożonym kodzie:
  `grep recruitment_match` w wdrożonym `candidates.py` = 3 trafienia).
- ✅ UI (Chrome MCP, prod `nexus.dynaminds.pl/candidates`):
  - Filtr „Rekrutacja" renderuje się w „Pule i przynależność" z hintem i
    multi-selectem (`Szukaj rekrutacji…`, realne tytuły z `/api/jobs-lookup`).
  - Wybór 1 rekrutacji → URL `?recr=201184`, badge „Filtry 1", pojawia się
    toggle Przypisani/Nieprzypisani.
  - **Przypisani** + pusta rekrutacja („Architekt Rozwiązań IT", 0 w pipeline)
    → `Pokaż wyniki (0)`; **Nieprzypisani** → `(50 057)` = dokładne dopełnienie.
  - **Przypisani** + 11 rekrutacji (OR) → `Pokaż wyniki (39)`, lista realnych
    członków pipeline z etapami (Nowy/Screening) w kolumnach REKRUTACJE /
    „Przeniósł na etap". Label „11 rekrutacji", URL z 11 id, badge „Filtry 11".
- ℹ️ Frontend vitest lokalnie zablokowany znanym bugiem `@rollup/rollup-darwin-arm64`
  (infra, nie kod) — testy przejdą w CI.
- ℹ️ Przejściowe „no available server" w trakcie testu = restart kontenera przy
  równoległym deployu `76df2a3`; po chwili `/api/health` = healthy, FE = 200.

## Znane ograniczenia / follow-up

1. Rejestracja `test_candidates_recruitment_filter.py` w `ci.yml` (token `workflow`).
2. `/api/jobs-lookup` zwraca `{id, title}` (limit 500, `id DESC`) bez nazwy
   klienta — przy zduplikowanych tytułach rekruter rozróżnia po kolejności/`#id`.
   Ewentualne wzbogacenie o `client_name` to osobna, opcjonalna zmiana.
3. Filtr celowo NIE wprowadza trybu „nieprzypisany do ŻADNEJ rekrutacji" (pusta
   selekcja = filtr nieaktywny) — zgodnie z literalnym wymaganiem („danej
   rekrutacji"). Łatwe do dodania, gdyby było potrzebne.
