# Moduł 2 — PR 1/7: P0 containment, capability guards, fail-closed conflicts

> Realizacja PR 1/7 z planu `docs/candidate-talent-module-audit-and-claude-implementation-plan-2026-07-16.md`.
> Baza: `origin/main` @ `e25225b` (dokładnie SHA audytu — numery linii planu były aktualne).

## Weryfikacja audytu (przed implementacją)

Wszystkie ustalenia P0 potwierdzone w kodzie na `e25225b`:

| ID | Potwierdzenie |
|---|---|
| M2-SEC-01 | `CurrentUser` na list/detail/search/export/documents/CV — `candidates.py`, `search.py` |
| M2-SEC-02 | `anonymize_pii` (bulk do 500) dostępne dla każdego zalogowanego — `candidates_bulk.py:144-201` |
| M2-SEC-03 | `industry_blocklist=false` pomijało ładowanie WSZYSTKICH konfliktów — `recommendation_filters.py:216-220` |
| M2-SEC-04 | notes/sources/talent-pools/marketplace-read/stawki na `CurrentUser`/`get_current_user` |
| M2-PRIV-02 | hard delete DL+ z kaskadą przez kontrakty/notatki (migracje 0141+0146) |
| M2-TEST-01 | `test_rbac.py` istnieje, ale NIE był na liście CI |

## Zakres zmian

### Backend — nowe moduły

- **`app/api/candidate_access.py`** — centralne capability guards (union primary+secondary ról przez `has_any_role`):
  - `CandidateSearchAccess` / `CandidatePIIAccess` / `CandidateDocumentAccess` — role operacyjne (admin, head_of_recruitment, delivery_lead, tac, recruiter, sourcer); rola `user` (viewer/klient) wykluczona wszędzie;
  - `CandidateWriteAccess` — parytet z `RecruiterPlus`;
  - `CandidateExportAccess` — admin, HoR, DL, TAC (recruiter/sourcer tracą eksport — rekomendacja audytu §19.3);
  - `CandidateFinanceAccess` — admin, DL, TAC („stawka do klienta”);
  - `privacy_workflow_unavailable()` — 409 dla zablokowanych operacji destrukcyjnych;
  - świadomie **bez feature flagi** przywracającej `CurrentUser` (wymóg planu).
- **`app/services/candidate_audit.py`** — immutable audit events na istniejącej tabeli `Activity` (bez PII w `details`): `export_requested`, `cv_downloaded`, `bulk_cv_downloaded`, `document_downloaded`, `document_url_issued`, `sensitive_operation_blocked`, `bulk_action_executed`.

### Backend — podmienione guardy (rola `user` → 403)

- `candidates.py`: list, suggest ×2, check-exists, check-duplicates, detail, timeline, history, risk, documents ×3, cv-download, bulk-cv-download, suggested-pools, competence-categories(list);
- `candidates.py` eksporty (GET+POST) → `CandidateExportAccess` + audit event;
- `candidates.py` client-rate → `CandidateFinanceAccess`; expected-rate → `CandidateWriteAccess` (parytet z pipeline move, używane w kanbanie);
- `candidates_bulk.py` → `CandidateWriteAccess`; akcja `anonymize_pii` → **409 zawsze** (guard PRZED załadowaniem wierszy — eskalacja przez body niemożliwa) + audit;
- `DELETE /api/candidates/{id}` → **409 zawsze** („privacy workflow required”) + audit; stary cascade-handler usunięty;
- `search.py`: scores/diagnostics/advanced/semantic → `CandidateSearchAccess`; unified `/` i `/global` zostają `CurrentUser`, ale **sekcja candidates jest pomijana** dla ról bez capability (joby/klienci działają dla viewerów);
- `notes.py`: odczyty → `CandidatePIIAccess`, mutacje → `CandidateWriteAccess` (`_can_modify_note` autor/admin bez zmian);
- `candidate_sources.py`: GET → `CandidatePIIAccess`, POST → `CandidateWriteAccess`, raport → `CandidatePIIAccess`;
- `talent_pools.py`: odczyty → `CandidateSearchAccess`, wszystkie mutacje → `CandidateWriteAccess`;
- `marketplace.py`: odczyty → `CandidateSearchAccess` (mutacje już były `RecruiterPlus`);
- `recommendations.py`: rekomendacje/pipeline-scores/candidates-from-similar/reverse/seeking → `require_candidate_read`; `assign-to-job` → `CandidateWriteAccess`;
- `phase3_actions.py` (shortlist email, client proposal) i `cv_match_preview.py` → `require_candidate_write`.

### Backend — fail-closed hard conflicts (M2-SEC-03)

`recommendation_filters.apply_user_filters`: konflikty ładowane **zawsze** (dla kandydatów z DB); twarde `blacklist/competitor/nda` zawsze wykluczają; `industry_blocklist` steruje **wyłącznie** miękkimi ostrzeżeniami (`current_employment`). Kandydaci efemeryczni (CV-preview, `id=None`) — bez lookupu.

### Frontend

- `middleware.ts`: `/candidates`, `/talents`, `/sourcing` ograniczone do ról operacyjnych (viewer → `/403`; anonim → `/login?next=`);
- `RecommendationFiltersBar.tsx`: checkbox „Respektuj NDA / blacklist” → „Pokaż miękkie ostrzeżenia” (twarde konflikty niezależne od UI);
- `CandidatesBulkBar.tsx`: akcja „Anonimizuj (RODO)” usunięta;
- `CandidateDetailV2.tsx`: „Usuń kandydata” + confirm usunięte;
- `CandidatesListV2.tsx`: przyciski eksportu (wyniki + zaznaczone) za `RequireRole minRole="tac"`.

### Testy + CI

- **Nowy** `tests/test_candidate_module_access.py` (dodany do listy CI): macierz rola×endpoint (19 read + 6 write endpointów × 7 ról), finance capability, eksport TAC+, audit eksportu bez PII, bulk anonymize 409 + baza nietknięta, eskalacja przez body, fail-closed hard conflicts (unit z NDA/current_employment), anti-enumeracja (403 dla istniejącego i nieistniejącego ID), secondary-role union, projekcja global/unified search;
- `test_candidate_delete.py` przepisany na zablokowany kontrakt (409 + kandydat przeżywa + audit event); test niezmienniczości FK zachowany;
- `test_rbac.py` zaktualizowany (`/api/candidates` nie jest już all-roles).

## Świadomie odłożony zakres (wraca w kolejnych PR planu)

- podział DTO (`CandidateSearchSummary` / `OperationalProfile` / `FinanceView` / `LegalView` / `ClientShareView`) — role operacyjne nadal dostają pełny `CandidateResponse`; viewer nie dostaje nic (403), więc P0 zamknięte; pełna projekcja per-capability → PR 2/5;
- audit 403 z poziomu guardów (wymaga middleware) — zdarzenia `sensitive_operation_blocked` emitowane w ścieżkach 409; pełne deny-metryki → PR 7;
- reauth/reason/idempotency dla bulk — razem z privacy executorem w PR 2;
- pole `roles` (secondary) w JWT middleware frontendu już wspierane (`payload.roles`);
- `test_rbac.py` nie dodany do CI w tym PR (nigdy nie był uruchamiany na tym środowisku; marker/manifest modułu → PR 7).

## Zmiany zachowania wymagające komunikacji

1. **Rola `user` traci cały moduł kandydatów** (listy, profile, CV, search, pule, targ, notatki) — zgodnie z §19.1 planu (rekomendacja: tak).
2. **Recruiter/sourcer tracą eksport CSV/XLSX** (zostaje TAC+) — §19.3.
3. **„Usuń kandydata” i „Anonimizuj (RODO)” wyłączone** do czasu privacy executora (PR 2) — interim: status `blacklisted`.
4. **Checkbox NDA/blacklist** nie wyłącza już twardych konfliktów (tylko miękkie ostrzeżenia).
