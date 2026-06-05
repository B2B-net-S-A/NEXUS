# Candidate `?q=` search performance — completion report

**Data:** 2026-06-05
**PR:** [#432](https://github.com/artur-t-96/Nexus/pull/432)
**Branch:** `claude/confident-bohr-20af5c`

## Problem (zmierzone na prodzie)

`GET /api/candidates?q=<fraza>` zajmował **~11.9s** dla dłuższych fraz
(`q=PKO BP: Programista Java Middle ZOB-2727`), podczas gdy `/api/jobs?q=` (~100ms)
i `/api/clients?q=` (~77ms) były natychmiastowe. Globalna paleta ⌘K
(`CommandPaletteV2`) woła ten endpoint na każde (debounced) wyszukanie → stałe,
kosztowne obciążenie DB (ryzyko jak przy incydencie notifications-runaway 2026-05-22).

## Root cause

`single_phrase_filter` (`app/services/advanced_candidate_search.py`) budował
`ILIKE '%fraza%'` OR-owany po **18 kolumnach** (w tym `raw_cv_text` ~171MB),
każda owinięta w `COALESCE(col,'')` (co uniemożliwia dopasowanie indeksu),
zmieszany z **nieindeksowalnym** `similarity() > próg` oraz cross-table
`notes EXISTS`. W efekcie planner nie mógł użyć **żadnego** z istniejących
indeksów trigramowych (`ix_candidates_cv_trgm` 207MB był martwy) → **pełny
Seq Scan po 47 600 wierszach**.

`EXPLAIN ANALYZE` (przed): `Seq Scan on candidates ... Rows Removed by Filter:
47600`, count sam **~5.5s** + notes SubPlan **~1s**; cały request (count + select)
~12s.

## Rozwiązanie

Każda fraza dopasowywana jest jako `candidates.id IN (UNION pod-zapytań id)`,
gdzie **każda gałąź korzysta z własnego GIN `pg_trgm`** (Append bitmap index
scanów):

| Gałąź | Indeks | Pochodzenie |
|---|---|---|
| `search_doc ILIKE` | `ix_candidates_search_doc_trgm` | migracja 0126 (nowy) |
| `raw_cv_text ILIKE` | `ix_candidates_cv_trgm` | migracja 0013 (istniejący) |
| `notes.content ILIKE` | `ix_notes_content_trgm` | migracja 0126 (nowy) |
| fuzzy `identity %` (tylko `?q=` ≥3 zn.) | `ix_candidates_identity_trgm` | migracja 0013 (istniejący) |

- **`candidates.search_doc`** — `STORED generated` kolumna = spacja-złączona
  konkatenacja wszystkich pól tekstowych **poza** `raw_cv_text` (ma własny indeks,
  nadal używany przez `/api/search/candidates`) i notes (osobna tabela). Bez
  `raw_cv_text` kolumna ma tylko **~28MB** (avg 617B) → tani rewrite i krótki
  `ACCESS EXCLUSIVE` lock przy `ADD COLUMN`.
- Gałąź **fuzzy** (typo-tolerancja identity) wpięta w ten sam UNION przez operator
  `%`; próg podawany przez `pg_trgm.similarity_threshold` (`SET LOCAL` —
  transaction-scoped, auto-reset, bez wycieku na pooled connection). `self_group()`
  wymusza nawiasy wokół `||` (w PG `%` wiąże mocniej niż `||`).
- Zakres pól i semantyka substring **bez zmian** względem starego per-column OR.

## Weryfikacja

- **Parytet wyników (PROD, realne 47.6k wierszy):** dla 10 fraz
  (`Python`, `Java`, `Nordea`, `Programista Java`, `kubernetes`, `Senior`,
  `Kowalski`, `warszawa`, długa `PKO BP: …`, `o`) → `only_old=0` i `only_new=0`
  w każdym przypadku (identyczne zbiory wynikowe vs stary OR).
- **Wydajność (EXPLAIN ANALYZE, PROD):** bare `raw_cv_text ILIKE` → bitmap scan
  **109ms** (vs 5500ms seq); `identity %` + SET LOCAL → **31ms**; UNION-of-ids
  (cv+identity+exp) → **267ms**.
- **Testy:** 88 zielonych (`test_candidates_advanced_search` 17 + listy/filtry/sort 71)
  na świeżym Postgres 16 z pełnym łańcuchem migracji. `ruff` clean.
- **Migracja:** single-head (`down=0125_b2b_generated_contracts`), zastosowana
  czysto na świeżej bazie (search_doc generated + 3 indeksy obecne).

## Po deployu (Coolify auto-deploy z `main`)

<!-- UZUPEŁNIĆ PO DEPLOYU -->
- [ ] `/api/health` → nowy `GIT_SHA`
- [ ] `search_doc` + `ix_candidates_search_doc_trgm` + `ix_notes_content_trgm` na prodzie
- [ ] `EXPLAIN ANALYZE` realnego `?q=` długiej frazy < ~1s
- [ ] paleta ⌘K — wyniki kandydatów pojawiają się szybko (Chrome MCP)

## Pliki

- `backend/alembic/versions/0126_candidate_search_doc.py` (nowy)
- `backend/app/services/advanced_candidate_search.py`
- `backend/app/api/candidates.py`

## Znane ograniczenia / follow-up

- Pathologiczne 1-znakowe `?q=` (np. `o` → 47.4k trafień) wciąż wymagają sortu
  całego zbioru po `created_at` (brak indeksu na `created_at`) — nieistotne dla
  realnych fraz; ⌘K i tak debounce'uje.
- `/api/search/candidates` (`app/api/search.py`) to osobny endpoint (FTS `fts_doc`
  + własny `raw_cv_text ILIKE`) — poza zakresem tej zmiany; `ix_candidates_cv_trgm`
  świadomie zachowany dla niego.
