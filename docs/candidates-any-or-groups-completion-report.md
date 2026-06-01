# Wiele grup OR w wyszukiwaniu zaawansowanym kandydatów

**Data:** 2026-06-01
**Branch:** `claude/jolly-shockley-2cd27d`

## Problem

Panel „Zaawansowane wyszukiwanie” na `/candidates` pozwalał ustawić tylko **jedną**
kombinację „Którakolwiek z wymienionych fraz” (jeden bucket OR, np. `React OR TypeScript`).
Rekruterzy potrzebowali wielu takich grup łączonych przez ORAZ, np.:

```
(React LUB TypeScript) ORAZ (Java LUB Node.js)
```

## Rozwiązanie

Bucket **ANY** stał się listą **grup OR**, które łączą się przez AND. Frazy w jednej
grupie nadal łączą się przez OR. Jedna grupa = dotychczasowe zachowanie (pełna
kompatybilność wsteczna z zapisanymi wyszukiwaniami i udostępnionymi URL-ami).

Złożenie SQL: `AND(all, OR(grupa_0), OR(grupa_1), …, NOT p1, …)`.

## Zmiany

### Backend (FastAPI)
- `app/services/advanced_candidate_search.py` — `build_advanced_filter(..., q_any_groups)`;
  legacy `q_any` to grupa 0, dodatkowe grupy z `q_any_groups`; puste grupy odrzucane,
  cap `_MAX_ANY_GROUPS=10`.
- `app/api/candidates.py` (GET `/api/candidates`) — nowy param `q_any_group` (każda
  wartość = jedna grupa, frazy złączone `|`), np. `?q_any_group=react|vue&q_any_group=java|kotlin`.
  Zaktualizowane: highlight (sort=relevance) + `extract_search_terms`.
- `app/api/search.py` (POST `/api/search/candidates`) — przekazuje `body.q_any_groups`.
- `app/schemas/candidate_search.py` — `q_any_groups: list[list[str]]`.
- `app/services/candidate_snippets.py` — `extract_search_terms(..., q_any_groups)`.

### Frontend (Next.js)
- `components/v2/filters/AdvancedSearchPopover.tsx` — `AdvancedSearchValue.any: string[][]`;
  UI z wieloma grupami, przyciskiem „Dodaj grupę (ORAZ)”, łącznikami „ORAZ”, usuwaniem grup
  (max 5 grup). Wydzielony pod-komponent `ChipField`.
- `lib/url-filters.ts` — `qAny: string[][]`; URL używa **powtarzalnego** param `q_any`
  (jedna wartość = jedna grupa, frazy `|`); API używa `q_any_group`. Stary `?q_any=a|b`
  dekoduje się do jednej grupy.
- `lib/candidate-search-api.ts` — `q_any_groups?: string[][]` (legacy `q_any` zostaje).
- `components/v2/filters/FiltersPanel.tsx`, `pages/CandidateSearchView.tsx` — mapowanie
  grup do `q_any_groups`.
- `pages/CandidatesListV2.tsx` — stan `qAny: string[][]`, memo `qAnyGroups` (czyści puste),
  URL/API/podświetlanie/liczniki/chipy.
- `components/v2/filters/ActiveFilterChips.tsx` — chip per fraza, etykieta „Grupa N” gdy >1 grupa.

## Testy / weryfikacja

- **Backend:** `ruff` czysty; struktura wyrażenia SQL zweryfikowana (1 grupa = płaski OR,
  2 grupy = `(OR) AND (OR)`, puste grupy odrzucane, wszystko puste → None). Nowe testy
  integracyjne: `test_q_any_groups_and_of_ors`, `test_legacy_q_any_ands_with_extra_group`
  (uruchamiane w CI na test-DB).
- **Frontend:** `tsc --noEmit` 0 błędów; `vitest` 23/23 (3 nowe testy grup);
  `eslint` 0 błędów (3 pre-existing warnings, niezwiązane).

## Kompatybilność wsteczna

- Stare URL-e / zapisane wyszukiwania `?q_any=React|TypeScript` → jedna grupa, bez zmian.
- API `q_any` (powtarzalne pojedyncze frazy) nadal działa = grupa 0.
- POST `/api/search` `q_any` zachowane; nowe grupy w `q_any_groups`.
