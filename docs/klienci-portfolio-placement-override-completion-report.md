# Klienci — manifest-safe placement override (raport)

Data: 2026-08-05. Branch: `claude/klienci-status-umowy-9e3e53`. Status: gotowe do
review; **niewdrożone** (deploy = merge do `main` → Coolify) — czeka na akceptację.

## Problem (zgłoszenie użytkownika)

„Alior Bank S.A." i „Credit Agricole Bank Polska S.A." są w zakładce **Nieaktywni
klienci**, mimo aktywnych umów. Próba przeniesienia i ustawienia dat kończy się
komunikatem „zaktualizowano", ale nic się nie zmienia.

## Diagnoza (co się naprawdę dzieje)

- Zakładki **Aktywni/Relacyjni/Nieaktywni** filtrują po `ClientPortfolioScope.category`
  (pochodzi z **manifestu portfela**, `client_portfolio_2026_07_30.json`).
  Kolumna „Status klienta" to **osobne** pole `Client.status`.
- Edycja klienta („Edytuj") zapisuje tylko `Client.status` → toast „Firma
  zaktualizowana", ale klient **nie zmienia zakładki** (to inne pole).
- W UI **nie było żadnej akcji** zmieniającej kategorię portfela.
- Dodatkowo: na produkcji Alior/Credit Agricole **już są** w Aktywni jako rekordy
  z manifestu (Credit Agricole z datami 11.05.2026–31.12.2027), a w Nieaktywni
  wiszą **duplikaty** operacyjne (Alior Bank S.A. #39 z 10 konsultantami; Credit
  Agricole Bank Polska S.A. #116). Fizyczne scalenie duplikatów (deliverable A)
  **odłożone** świadomą decyzją — ten PR to **deliverable B** (działające UI).

## Kluczowe ograniczenie bezpieczeństwa

`get_client_portfolio_import_health` porównuje żywe zakresy manifestu
(`source_system='client_excel'`) z zaimportowanymi wierszami po **bazowej**
`category` i datach podpiętej umowy ramowej. Ręczna zmiana tych kolumn rozjeżdża
stan z manifestem → `applied_manifest_state_inconsistent` → `/api/health/deep`
zwraca **503** (bez self-heal). To ta sama klasa, która 2026-08-03 zapętliła
backend (#1024). Dlatego edycja UI **nie może** zmieniać bazowych kolumn.

## Rozwiązanie — nakładka placementu (override), niewidoczna dla inwariantu

Dodane 3 nullable kolumny na `client_portfolio_scopes`:
`category_override`, `contract_start_override`, `contract_end_override`.

- **Katalog CZYTA** wartości efektywne: `COALESCE(override, base)` — kategoria,
  daty, liczniki i eksport. Klient przenosi się między zakładkami natychmiast.
- **Inwariant NADAL czyta** bazowe kolumny (niezmienione) → `/api/health/deep`
  zielony, zero dryfu, zero ryzyka boot-loopu.
- **Manifest apply** nigdy nie pisze `*_override` → override przeżywa re-apply.

### Backend

- Migracja `0215_client_portfolio_scope_overrides` (down_revision `0214`), additywna,
  reużywa enum `clientportfoliocategory`, CHECK `ck_client_portfolio_scopes_override_dates`
  (koherencja dat). Lustro w `entrypoint.sh` (prod alembic osierocony).
- Nowy endpoint `PATCH /api/clients/{id}/portfolio-scopes/{scope}/placement`
  (AdminUser) — pisze **tylko** `*_override`; `null` czyści (powrót do manifestu),
  pole pominięte = bez zmian; walidacja `end >= start` (422) + CHECK jako backstop.
- **Utwardzenie „miny":** istniejący `PATCH …/portfolio-scopes/{scope}` odrzuca (409)
  zmianę `category`/`framework_contract_id` na zakresie z manifestu; `DELETE`
  (archiwizacja) też odrzuca (409) zakres z manifestu — to był **dokładnie**
  mechanizm awarii 2026-08-03. `label` pozostaje edytowalny; zakresy `manual`
  edytowalne swobodnie (są poza inwariantem).
- Katalog: `_directory_rows_statement` + `_directory_counts_statement` na
  `COALESCE(category_override, category)`; daty przez `COALESCE(*_override, MSA)`;
  `has_contract_period`; item niesie `category`, `category_base`, `*_override`.

### Frontend

- Lista Klienci (`ClientsListV2`): kolumna **Akcje** + przycisk **„Przenieś"**
  (tylko `admin` — capability `client.portfolio.manage`) → dialog DS (`AppModal`):
  zakładka (3 opcje) + daty umowy; „Przywróć z manifestu" czyści override.
  Wybór kategorii **bazowej** czyści override (bez redundantnego pinowania).
- Znacznik **„ręcznie"** na wierszach z realnym override (efektywna ≠ bazowa lub
  daty). Daty w wierszu czytane z wartości efektywnych (nie bramkowane `msa_id`).
- **Rozróżnienie status vs kategoria:** tooltip nagłówka „Status klienta" +
  przeetykietowanie w modalu edycji klienta na „Status handlowy" z podpowiedzią,
  że o zakładce decyduje kategoria portfela.

## Jak używać (po wdrożeniu)

1. Klienci → zakładka gdzie widać klienta → wiersz → **Przenieś**.
2. Wybierz zakładkę docelową (np. Aktywni) i/lub ustaw daty umowy → **Zapisz**.
3. Wiersz przechodzi natychmiast; `/api/health/deep` pozostaje zielony.

> Uwaga: to nie usuwa duplikatów Alior/Credit Agricole (deliverable A, odłożone).
> Override pozwala jednak ustawić poprawne zakładki od ręki.

## Weryfikacja

- **Backend:** `alembic upgrade heads` (0215 czysto) + `pytest
  tests/test_client_directory.py tests/test_client_directory_migration_contract.py`
  → **31 passed** (postgres:16 + obraz CI). Testy dowodzą m.in., że **bazowa
  `category` jest nietknięta** po przeniesieniu (override ≠ base), bramki 409
  (PATCH/DELETE na manifeście), 422 na niespójnych datach, oraz parytet
  migracja↔entrypoint↔model dla 0215.
- **Frontend:** `type-check` czysty (jedyne błędy: środowiskowy `chart.tsx` z
  pożyczonego `node_modules` — nie w CI); ESLint 0 błędów; Vitest capabilities
  163 / Debounce 16 / Export 5 (w izolacji) — zielone.
- **Adwersaryjna weryfikacja** (4 recenzentów, read-only): SQL czysty; 3 findingi
  (DELETE guard, mylący badge, brak testu parytetu) — **wszystkie naprawione**.

## Znane ograniczenia / follow-up

- **Deliverable A** (scalenie duplikatów #38333↔#39, #38342↔#116) — odłożone; do
  wykonania jako osobna, zwalidowana operacja na prodzie (prod-write przez Artura),
  bez ryzykownego re-cutu manifestu.
- Placement to **admin-only**. Jeśli DL ma przenosić swoich klientów — poszerzyć
  guard endpointu do `DlAssignedOrAdmin` + capability (osobny PR).
- Override dat współistnieje z datami MSA; przy przyszłym scaleniu (A) trzeba je
  pogodzić.
