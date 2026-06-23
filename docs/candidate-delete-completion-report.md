# Completion report — Usuwanie kandydata z bazy

**Data:** 2026-06-22
**Branch:** `claude/great-chebyshev-0e7bc3`

## Problem

„Nie można usunąć kandydata z bazy." Endpoint `DELETE /api/candidates/{id}` oraz
klient FE `candidatesApi.delete()` **już istniały**, ale:

1. **Brak akcji w UI** — nigdzie nie było przycisku „Usuń kandydata".
2. **Twardy delete potrafił rzucić 500** — 5 tabel odwoływało się do
   `candidates.id` **bez** reguły `ON DELETE` i **bez** kaskady ORM, więc
   kandydat z umową / screening-note / wpisem w puli / cache'em matchy / eventem
   kalendarza powodował `ForeignKeyViolation`.
3. **Brak czyszczenia Qdrant** — wektor kandydata zostawał osierocony.

## Zmiany

### Backend
- **Migracja `0141_candidate_delete_cascade`** — backfill `ON DELETE` dla 5
  brakujących FK (nazwy constraintów wykrywane przez introspekcję, więc odporne
  na konwencję): `contracts`, `screening_notes`, `talent_pool_memberships`,
  `match_history` → `CASCADE`; `calendar_events` → `SET NULL` (event przeżywa,
  tylko odpięty). Migracja **scala dwie zacommitowane głowice `0138_*`** (na
  `origin/main` historia jest rozwidlona) → po niej znów jedna głowica.
- **Modele** — te same reguły `ondelete=` w definicjach FK (schema-as-code).
  `Candidate.contracts` dostał `passive_deletes=True` (bez tego ORM próbowałby
  wyzerować NOT NULL `contracts.candidate_id` przy delete → IntegrityError).
- **Endpoint `delete_candidate`** — `await db.flush()` (błędy FK ujawniają się
  jako nieudane żądanie, nie późny commit) + best-effort
  `delete_candidate_embedding()` (Qdrant; nigdy nie blokuje deletu).
- **Pozostałe FK bez `ondelete`** (`notes`, `candidate_conflict`, `rate_history`,
  `recruitment_pipeline`) są kaskadowane przez ORM na modelu `Candidate` —
  bezpieczne.

### Frontend
- `CandidateDetailV2`: akcja **„Usuń kandydata"** w menu „Więcej" (gated rolą
  `admin`/`delivery_lead` — zgodnie z `DeliveryLeadPlus` na backendzie),
  destrukcyjny `ConfirmV2` („Tej operacji nie można cofnąć"), mutacja →
  `candidatesApi.delete(id)` → toast + invalidacja list + redirect na
  `/candidates` (lub `onClose()` w trybie embedded drawer).

### Testy / CI
- `tests/test_candidate_delete.py` — auth-required, 404, twardy delete kandydata
  z notatką **i umową** (dowód że wcześniej-blokujące FK teraz kaskadują),
  403 dla rekrutera.
- Zarejestrowany w `.github/workflows/ci.yml` (selektywna lista pytest).

## Weryfikacja
- Backend: `ruff check` + `ruff format --check` ✓, `py_compile` ✓.
- Migracja — **realny Postgres**: introspekcja trafia w `*_candidate_id_fkey`,
  reguły `ON DELETE` ustawione, `DELETE` rodzica kaskaduje 4 tabele i zeruje
  `calendar_events`. **Alembic (Python 3.12)**: graf zacommitowany + `0141`
  (bez WIP 0139/0140) → dokładnie **jedna** głowica, łańcuch 166 rewizji bez
  dangling.
- Frontend: `type-check` ✓, `lint` (exit 0) ✓, `build` ✓.

## Uwaga (WIP użytkownika)
W worktree były **niezacommitowane** pliki nie należące do tego zadania:
`alembic/versions/0139_merge_0138_heads.py`, `0140_contract_line_manager_rates.py`
oraz `docs/recruitment-assignment-filter-completion-report.md`. **Nie** zostały
zacommitowane. Dlatego `0141` celowo zależy od zacommitowanych głowic `0138_*`,
nie od `0140`. Gdy WIP 0139/0140 zostanie zacommitowany, powstaną dwie gałęzie
scalające te same `0138` (0140 i 0141) — `alembic upgrade heads` to obsłuży;
ewentualny pojedynczy head można domknąć trywialnym merge-migration.

## Aktywacja
Po merge i deployu (Coolify rebuild → `alembic upgrade heads`): akcja „Usuń
kandydata" widoczna dla admin/delivery_lead na profilu kandydata.
