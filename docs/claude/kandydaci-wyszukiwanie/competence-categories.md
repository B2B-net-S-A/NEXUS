# Competence Categories (od 24.09.2026 CZTERY — podział profili, filtr, badge wszędzie)

**Od 0371 (decyzja Artura 24.09.2026) zespół ma CZTERY kategorie** — podział
z dawnego InfraReportera: `infrastructure_operations` = „Infra & Operations &
Security / Data & AI”, `software_development` = „Development”,
`security_quality` = „QA” (same testy), `management_delivery` = „Management &
Delivery (PM & BA)”. `data_ai` zostaje w tabeli **nieaktywna** (kasowanie
blokują dwa FK, a seed w entrypoincie wstawiłby ją z powrotem), wszystkie FK
przepięte na infra; rekrutacje security z QA też przeszły do infra. Slugi
i id zostały świadomie — slug siedzi w starym polu tekstowym kandydata
i w tekście embeddingu, więc nowy slug = przeliczenie wektorów całej bazy.
SQL: `services/competence_category_four.py` (migracja 0371 + blok
„competence-categories-four” w entrypoincie, marker w `app_settings`).
Reguły klasyfikacji (`talent_pool_cc`, `job_cc`) są BLOKAMI z nazwą
(qa → security → data → management → infra → software), a dodatki `job_cc`
kluczowane nazwą bloku, nie slugiem — dwa bloki mają ten sam slug. „Pentester”
to security, nie tester (`(?<!pen)tester`). Kandydatów z dawnego
„Bezpieczeństwa i Jakości” przelicza admin: `POST
/api/admin/candidates/backfill-cc?only_missing=false&only_slug=security_quality`.
Plakietka: `competenceTone(slug)` + alias `data_ai → infra` dla starego pola.

Backbone CC istniał od `0033`/`0041` (5 kategorii zaseedowane w entrypoint `_DATA_STATEMENTS`:
`infrastructure_operations`, `software_development`, `data_ai`, `security_quality`,
`management_delivery`). Ten moduł go **odsłania**: filtr w głównej liście + backfill 49k +
badge wszędzie. Decyzja: **5 głównych** (podkategorie = Faza 2), **primary + do 2 pobocznych**.
Pełny opis: `docs/competence-categories-completion-report.md`.

- **Jedno źródło zapisu:** `app/services/candidate_cc_assignment.py::apply_candidate_cc_scores`
  pisze M2M `candidate_competence_categories` (1 primary + do 2 secondary, `confidence` +
  `source` band: `ai_auto` ≥0.80 / `ai_suggested`) I synchronizuje legacy `competence_category`
  (slug) + `competence_category_id` (FK). **Manual-safe:** kandydat z jakimkolwiek wpisem
  `source='manual'` nie jest ruszany. `overwrite=False` = uzupełnij tylko gdy puste. Używają go
  OBIE ścieżki auto (`_auto_assign_primary_cc` w `candidates.py` na wgraniu CV + `public_share.py`
  invite-apply) oraz backfill.
- **Kategoria idzie PO wektorze** (05.10.2026): przy włączonym outboxie indeksu
  `finish_cv_ingest` klasyfikuje kandydata, zanim worker policzy wektor, a bez wektora
  klasyfikator prawie nigdy nie przekracza progu (prod: 122 z 661 nowych CV w 7 dni). Worker
  po udanym zapisie wektora woła `index_outbox_service.assign_cc_after_embed` — tylko kandydat
  bez FK i bez wierszy M2M, własna krótka transakcja po commicie wektora, błąd połykany.
  **Kategoria jest w tekście wektora**, więc przypisana po nim zleca przeliczenie
  (`record_bulk_reindex` w tej samej transakcji; `finish_cv_ingest` zgłasza ponownie, gdy
  kategoria się zmieniła). Bez tego 125 ze 164 CV z października miało wektor bez kategorii
  (badanie 06.10.2026, `docs/audits/2026-10-06/voyage-embeddings-research.md`). Reconciler
  dryfu trzyma kursor w `app_settings['index_drift_reconciler_state']` i co tik sprawdza
  najpierw najwyższe id (`reconcile_once(newest_first=True)`) — kursor w pamięci wracał do
  zera przy każdym deployu, a ~11-godzinny przebieg nie dochodził do nowych kandydatów.
- **Filtr listy:** `GET /api/candidates?competence_category_id=<id>` (repeat = OR), match primary
  LUB secondary (M2M) OR legacy FK. FE: `lib/url-filters.ts` (`competenceCategoryIds`, URL `cc`) +
  sekcja „Kategoria kompetencji" w panelu `CandidatesListV2` (reuse `CompetenceCategoryMultiSelect`)
  + chip w `ActiveFilterChips`.
- **Badge:** `components/v2/CompetenceCategoryBadge.tsx` (token-owy, slug→`name_pl` z cache
  `GET /api/competence-categories`) — w wierszu listy, kafelkach, quick-view, nagłówku profilu.
- **Backfill 49k (aktywacja):** `POST /api/admin/candidates/backfill-cc` (+ `/status`), admin,
  background, resumable, `only_missing=true` domyślnie (tylko `competence_category_id IS NULL` →
  zero nadpisania). To ścieżka prodowa (brak SSH/DB). CLI: `python -m scripts.backfill_candidate_cc
  --dry-run|--commit [--all]`. **Bez migracji** — schemat już jest.
