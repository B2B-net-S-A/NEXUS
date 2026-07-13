# LinkedIn-Recruiter-style filtry kandydatów — completion report

**Data:** 2026-04-22
**Feature:** Filtrowanie kandydatów po stanowisku / firmie / kliencie (à la LinkedIn Recruiter)
**Plan:** [`.claude/plans/zbuduj-wszystko-wedle-twoich-fuzzy-orbit.md`](../.claude/plans/zbuduj-wszystko-wedle-twoich-fuzzy-orbit.md)

---

## Co dostarczone

4 nowe filtry w liście kandydatów (`/candidates`) + endpoint autocomplete:

| Filtr | URL param | Źródło danych | Semantyka |
|---|---|---|---|
| Obecna firma | `cur_co=X\|Y` | `Candidate.experience[0].company` | ILIKE substring, OR wewnątrz param |
| Poprzednia firma | `past_co=X\|Y` | `Candidate.experience[1..N].company` | WITH ORDINALITY > 1 (wyklucza current), OR |
| Obecne stanowisko | `title=X\|Y` | `Candidate.experience[0].role` | ILIKE, OR |
| Pracował u klienta | `client_hist=1,2` | `Contract.client_id` + `CandidateConflict.type=current_employment` | historycznie (ignoruje status/active), OR |

Wszystkie filtry AND między różnymi parametrami, OR wewnątrz listy wartości.

**Autocomplete:** `GET /api/candidates/companies/suggest?q=&limit=20` zwraca top-N firm z CV experience z count'ami.

---

## Zmienione pliki

### Backend
- `backend/alembic/versions/0044_experience_search_indexes.py` **NEW** — merge 3 heads (`0043_interview_feedback`, `0043_kpi_coach_nudger`, `0036_microsoft365`) + GIN indeksy na `experience` JSONB i `experience::text` trigram
- `backend/app/api/candidates.py` — 4 nowe Query params, 4 helpery predykatów (`_current_company_predicate`, `_current_title_predicate`, `_past_company_predicate`, `_worked_at_client_predicate`), endpoint `GET /companies/suggest`
- `backend/tests/test_candidates_position_filters.py` **NEW** — 13 testów pokrywających wszystkie filtry + suggest endpoint

### Frontend
- `frontend/src/components/v2/filters/ClientMultiSelect.tsx` **NEW** — multiselect klientów (klon TalentPoolMultiSelect)
- `frontend/src/components/v2/filters/CompanyAutocomplete.tsx` **NEW** — multi-chip tag input z debounced autocomplete
- `frontend/src/components/v2/pages/CandidatesListV2.tsx` — state + URL sync + useQuery + 4 nowe sekcje w sidebarze + active count + clear filters + saved searches
- `frontend/src/components/v2/filters/ActiveFilterChips.tsx` — chipy dla nowych filtrów + clearAll
- `frontend/src/lib/url-filters.ts` — rozszerzony `CandidateFilters` + encoder/decoder + pipe separator dla firm (chronią przecinki "Intel, Inc.")
- `frontend/src/lib/__tests__/url-filters.test.ts` — rozszerzony test round-trip + nowy test pipe-separator

---

## Weryfikacja

### Backend
- ✅ `docker compose exec backend alembic -c alembic/alembic.ini heads` → single head `0044_experience_search_indexes`
- ✅ `docker compose exec backend pytest tests/test_candidates_position_filters.py -v` → **13 passed**
- ✅ GIN indeksy zainstalowane bezpośrednio na dev DB (alembic upgrade ma pre-existing blokadę w innych migracjach, nie związane)
- ✅ Historyczny cURL smoke (token wycofanego konta syntetycznego; nie używać ponownie):
  - `GET /api/candidates/companies/suggest?q=&limit=5` → `[{name:"abb",count:1}, {name:"accenture",...}, ...]`
  - `GET /api/candidates?current_company=allegro` → 1 kandydat (Tomasz Dąbrowski)
  - `GET /api/candidates?current_title=senior` → 2 kandydatów
  - `GET /api/candidates/companies/suggest?q=alle` → `[{name:"allegro",count:1}]`

### Frontend
- ✅ TypeScript check na zmienionych plikach czysty (pre-existing errors w SavedSearchesMenu.tsx/GenerateInviteLinkV2.tsx pozostały — nie moje)
- ✅ `npx vitest run src/lib/__tests__/url-filters.test.ts` → **9 passed** (w tym nowy test pipe separator)
- ✅ `docker compose build --no-cache frontend && docker compose up -d` czysto
- ✅ Chrome MCP E2E smoke na `http://localhost:3001/candidates`:
  - Popup "Filtry zaawansowane" otwiera się, widoczne wszystkie 4 nowe sekcje
  - Autocomplete w "Obecna firma" pokazuje sugestie z count badge'ami
  - Wybór "allegro" → lista filtruje się z 140 → 1 (Tomasz Dąbrowski)
  - Chip "Obecna firma: allegro" pojawia się z X-em do usunięcia
  - Badge "1" na "Filtry zaawansowane"
  - URL `?cur_co=allegro` synchronizuje się

---

## Decyzje projektowe

- **past_company wyklucza current** (LinkedIn-style, ORDINALITY > 1). Jeśli user chce "kiedykolwiek" = ustawia oba filtry.
- **worked_at_client historyczne** (ignoruje `Contract.status` i `CandidateConflict.active`). Current-only wciąż w `employment=at_client`.
- **Case-insensitive ILIKE substring** — wystarczające dla ~140 kandydatów dev-a i ~1-3k prod. Denormalizacja kolumn (`candidate.current_company`) dopiero gdy zaboli performance.
- **Separator pipe `|`** dla company/title values — nazwy firm zawierają przecinki ("Intel, Inc."), CSV tam zawodzi. `workedAtClientIds` to CSV (numeric).
- **Suggest endpoint lowercase'uje nazwy** — akceptowalne uproszczenie na MVP (kolapsuje "Google" i "google").

---

## Znane ograniczenia

1. **Alembic upgrade head zawodzi** (pre-existing problem — `0029` duplicate revision ID w `0029_job_collaborators.py` vs `0032_client_materials.py`). Moje GIN indeksy założyłem ręcznie raz (idempotent `CREATE INDEX IF NOT EXISTS`). Na prod Coolify `entrypoint.sh` toleruje błędy alembic. Do kompletnego fixa potrzebny osobny task: unikalność revision ID w istniejących migracjach.
2. **Autocomplete dla "Obecne stanowisko"** jest free-text (bez suggest endpointu) — celowo MVP. Można dodać `/api/candidates/titles/suggest` w przyszłości.
3. **Performance przy >10k kandydatach:** `jsonb_array_elements` scan dla `past_company` i suggest endpoint nie jest w pełni index-backed. Przy dużej skali denormalizacja `candidate.current_company` + btree index. Obecnie nie dotyczy.

---

## Commit / deploy

**Nie zacommitowane** — zgodnie z rules (`feedback_autonomy.md`): commit tylko na wyraźną prośbę usera.

Sugerowany commit message:
```
feat(candidates): LinkedIn-Recruiter-style filters — current/past company, title, worked-at-client + autocomplete

- 4 nowe filtry URL: cur_co, past_co, title, client_hist
- Endpoint /api/candidates/companies/suggest dla autocomplete
- GIN indexes (JSONB + trigram) na candidates.experience
- Merge Alembic 0044: 0043_interview_feedback + 0043_kpi_coach_nudger + 0036_microsoft365
- Reusable ClientMultiSelect + CompanyAutocomplete w v2/filters/
- 13 backend tests (pytest), 1 nowy frontend test (vitest)
```

Po commicie + push: produkcja tylko health/snapshot smoke. Interaktywny Chrome
smoke wykonaj na staging jednorazowym, imiennym kontem testowym.
