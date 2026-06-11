# Filtr Competence Category na liście ofert — raport ukończenia

**Data:** 2026-06-11 · **PR:** [#484](https://github.com/artur-t-96/Nexus/pull/484) · **Backfill:** wykonany na prod

## Problem

Filtr „Kategoria" na `/jobs` istniał w UI (`CompetenceCategoryMultiSelect`) i API
(`competence_category_id`), ale **wszystkie 3919 jobów na prodzie miało
`competence_category_id = NULL`** — wybranie dowolnej kategorii zwracało 0 ofert.

Przyczyna: hybrydowy klasyfikator (`cc_classifier.classify_job_to_cc`) przy
tworzeniu joba wpadał w `tie=True` przy mikroskopijnych score'ach (keyword ratio
liczone od *wszystkich* keywordów kategorii; drafty bez embeddingu w Qdrant) —
nawet „Tester Middle" / „Senior DevOps Engineer" nie dostawały kategorii.

## Zmiany

| Plik | Co |
|---|---|
| `backend/app/services/job_cc.py` | **NOWY** — deterministyczny klasyfikator tytuł→CC (reguły `talent_pool_cc` + wzorce PL/prod: programista, analityk, kierownik, architekt chmurowy, dev-ops, testów/testowania, VMware, CSIRT, malware…); `resolve_job_cc_id` = tytuł najpierw, hybryda (no-tie, score ≥ 0.30) jako fallback |
| `backend/app/services/talent_pool_cc.py` | publiczny alias `BASE_CC_RULES` |
| `backend/app/api/jobs.py` | create-path używa `resolve_job_cc_id` → nowe joby dostają CC od razu |
| `backend/scripts/backfill_job_cc.py` | **NOWY** — idempotentny backfill (`--dry-run`/`--commit`, `--title-only`, `--limit`, batch po 500) |
| `backend/tests/test_job_cc.py` | **NOWY** — 73 tytuły z prod przypięte + testy precedencji (187 testów razem z pool CC) |

Migracje: brak. Endpointy: brak nowych (param `competence_category_id` istniał).
Frontend: bez zmian (filtr był gotowy).

## Backfill na prod (2026-06-11)

```
Assigned 3582/3919 (tier title: 3571, hybrid: 11, unmatched: 337)
  software_development         1046
  management_delivery          1031
  security_quality              874
  infrastructure_operations     371
  data_ai                       260
```

337 bez kategorii to nie-role („Opportunity", „Stara kadencja", przetargi-zbiorcze) —
świadomie NULL, lista nie zgaduje.

## Weryfikacja

- **API:** `GET /api/jobs?competence_category_id=N` → totals 371/1046/260/874/1031
  (1:1 z DB); multi-select `1+3` → 631 ✓
- **UI (agent-browser, prod):** `/jobs` → „Kategoria: dowolna" → wybór „Dane i AI"
  → **260 ofert**; + „Infrastruktura i Operacje" → **631 ofert**, trigger
  „Kategorie: 2"; screenshot zweryfikowany wizualnie ✓
- Testy: `pytest tests/test_job_cc.py tests/test_talent_pool_cc.py` — 187 passed; ruff clean.

## Znane ograniczenia / follow-up

- 337 jobów bez kategorii (nie-role) — filtr ich celowo nie pokazuje przy aktywnej kategorii.
- Edycja tytułu joba (PATCH) nie re-klasyfikuje — CC zostaje z create/backfillu;
  użytkownik może zmienić ręcznie w formularzu joba.
- `cc_classifier` (hybryda) ma zaszumione centroidy (data_ai scoruje wysoko dla
  wszystkiego) — nie ruszane, bo title-tier załatwia 91%; ewentualny tuning
  centroidów = osobny temat.
