# Competence Categories — surface everywhere + filter + backfill

> Cel (Artur): „wszystkie profile w Nexus powinny być podzielone na 5 competence
> category — widoczne wszędzie i można po tym filtrować".

## TL;DR

Backbone CC (5 kategorii, klasyfikator, auto-assign, M2M) **już istniał** — brakowało
trzech rzeczy, które ten PR dowozi:

1. **Filtr w GŁÓWNEJ liście kandydatów** (`GET /api/candidates` ↔ `CandidatesListV2`).
2. **Backfill ~49k istniejących profili** (dotąd kategorię dostawał tylko świeżo wgrany CV).
3. **Badge widoczny wszędzie** — lista, kafelki, quick-view, nagłówek profilu.

Plus ujednolicenie zapisu: auto-assign i backfill piszą teraz **spójnie** M2M
(primary + do 2 pobocznych, z `confidence` + `source`) i synchronizują legacy
`competence_category` (slug) + `competence_category_id` (FK).

Decyzje produktowe (potwierdzone): **5 głównych kategorii** (podkategorie = Faza 2),
**główna + do 2 pobocznych** na profil.

## Zmiany — backend

- **`app/services/candidate_cc_assignment.py`** (nowy) — jedno źródło prawdy:
  - `apply_candidate_cc_scores(candidate, scores, db, *, overwrite)` — zapisuje M2M
    (1 primary + do 2 secondary ≥ `SECONDARY_MIN_SCORE=0.40`), banduje `source`
    (`ai_auto` ≥ 0.80, inaczej `ai_suggested`), synchronizuje legacy slug + FK.
    **Curation-safe:** jeśli kandydat ma jakikolwiek wpis `source='manual'` → nie
    rusza go w ogóle. `overwrite=False` = „uzupełnij tylko gdy puste".
  - `backfill_candidate_ccs(db, *, limit, only_missing, dry_run, progress)` — pętla
    po kandydatach (commit per profil = resumable). `only_missing=True` (default)
    dotyka tylko `competence_category_id IS NULL` → zero ryzyka nadpisania.
- **`app/api/candidates.py`**
  - `_auto_assign_primary_cc` przepięte na wspólny writer (nowe CV → też M2M + poboczne).
  - Filtr listy: nowy param `competence_category_id: list[int]` → `CandidateFilterSpec`
    → klauzula w `_build_candidate_filtered_query` (match primary LUB secondary przez
    M2M, OR legacy FK dla profili sprzed backfillu).
- **`app/api/public_share.py`** — duplikat auto-assign (invite-link apply) też przez writer.
- **`app/api/admin_candidates.py`** — `POST /api/admin/candidates/backfill-cc` (+ `/status`),
  single-flight background job (wzór `backfill-names`). **To jest ścieżka odpalenia na prodzie**
  (brak bezpośredniego dostępu do DB/SSH — patrz memory `nexus-prod-db-access-dead-ssh`).
- **`app/schemas/candidate.py`** — `CandidateResponse.competence_category_id` (dla badge'a).
- **`scripts/backfill_candidate_cc.py`** (nowy) — CLI (`--dry-run` / `--commit` / `--all`) do
  lokalnego preview / kontrolowanych runów.

**Brak migracji** — tabela M2M (`candidate_competence_categories`), FK i seed 5 kategorii
już istnieją (migracje `0033`/`0041` + entrypoint `_DATA_STATEMENTS`). Zero zmian schematu.

## Zmiany — frontend

- **`components/v2/CompetenceCategoryBadge.tsx`** (nowy) — token-owy badge (5 spójnych
  odcieni: info/soft/success/danger/warning), rozwiązuje `name_pl` z cache'owanego
  `GET /api/competence-categories` (współdzielony queryKey z filtrem). Nigdy nie
  pokazuje surowego sluga.
- **Filtr w liście** — `lib/url-filters.ts` (`competenceCategoryIds`, round-trip jako `cc`),
  `CandidatesListV2` (state + snapshot + licznik + patch + reset + sekcja „Kategoria
  kompetencji" w panelu filtrów, reuse gotowego `CompetenceCategoryMultiSelect`),
  `ActiveFilterChips` (chip „Kategoria: …" + clearAll).
- **Badge wszędzie** — wiersz listy (`CandidatesListV2` cela „Kandydat"), kafelki
  (`CandidatesTiles`), quick-view (`CandidateQuickView`), nagłówek profilu
  (`CandidateDetailV2` — zastąpił schowany surowy slug w „faktach").

## Weryfikacja

- `tsc --noEmit` — ✅ czysto.
- `next lint` — ✅ 0 errors (warningi to pre-existing `no-explicit-any` w nietkniętych liniach).
- Vitest `url-filters` — ✅ 35/35 (dodany round-trip `competenceCategoryIds` ↔ `cc`).
- Backend ruff/pytest — przez CI (brak lokalnego venv w worktree).

## Aktywacja na prodzie (po merge + deploy)

1. **Backfill** (to sprawia, że „wszystkie profile podzielone" staje się prawdą):
   ```bash
   # dry-run (podgląd rozkładu, bez zapisu)
   curl -X POST -H "Authorization: Bearer <admin-jwt>" \
     "https://api.nexus.dynaminds.pl/api/admin/candidates/backfill-cc?limit=200"
   curl -H "Authorization: Bearer <admin-jwt>" \
     "https://api.nexus.dynaminds.pl/api/admin/candidates/backfill-cc/status"
   # pełny run: bez limitu (only_missing=true domyślnie)
   ```
   Job leci w tle (Qdrant + keyword per profil, ~kilkanaście–kilkadziesiąt min dla 49k),
   resumable, idempotentny, commit per profil. Domyślnie tylko `competence_category_id IS NULL`.
2. **Chrome smoke** (local Chrome authed jako Admin na `nexus.dynaminds.pl`): filtr
   „Kategoria kompetencji" zwraca wyniki + badge w wierszu/kafelku/quick-view/profilu.

## Znane ograniczenia / follow-up

- **Podkategorie** (~40 ról: Cloud/Backend/Pentester…) — świadomie Faza 2 (nowa tabela +
  strojenie klasyfikatora + UI drill-down).
- **Split-view / detail-panel** (PR #720) nie są w tej gałęzi (branch sprzed #720) — badge
  tam trzeba dołożyć osobno po zmerge'owaniu z main.
- **Test jednostkowy `apply_candidate_cc_scores`** (skip/overwrite/primary+secondary/legacy
  sync) — do dołożenia (potrzebuje DB-fixture + wpisu na listę plików pytest w `ci.yml`).
- Jakość klasyfikacji = istniejący hybrid classifier (ten sam, który już akceptowaliśmy dla
  nowych CV). Profile `<0.30` zostają bez kategorii; `ai_suggested` (0.30–0.80) można później
  przejrzeć/podnieść przez ręczne przypisanie (`source='manual'` jest odporne na re-klasyfikację).
