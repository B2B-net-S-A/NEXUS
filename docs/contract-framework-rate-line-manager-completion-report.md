# Completion report — Kontrakty: stawka z umowy ramowej + Line Manager + fix walidacji stawek

**Data:** 2026-06-23
**Branch / PR:** `claude/brave-edison-048445` → [#568](https://github.com/artur-t-96/Nexus/pull/568)

## Zgłoszenie

W zakładce **Kontrakty → Nowy kontrakt**:

1. Brak pól **„Stawka z umowy ramowej"** oraz **„Line Manager"**.
2. Pole **Stawka kandydata** nie przyjmowało `115` — komunikat „Wprowadź
   prawidłową wartość. Dwie najbliższe prawidłowe wartości to 100 i 200"
   (przyczyna: `<input type="number" step="100">` → walidacja HTML5 wymusza
   wielokrotność 100).

## Co zrobiono

### Backend
- **Migracja** `0142_contracts_framework_rate_line_manager` (down: `0141`) —
  dodaje `contracts.framework_rate INTEGER` + `contracts.line_manager
  VARCHAR(255)`, idempotentnie (`ADD COLUMN IF NOT EXISTS`).
- `app/models/contract.py` — dwie nullable kolumny. `framework_rate` celowo
  **poza** `calculate_margin()` (wartość referencyjna z MSA, nie billowana).
- `app/schemas/contract.py` — `ContractCreate` / `ContractUpdate` /
  `ContractResponse`.
- `app/api/contracts.py` — `_to_detail()` serializer (ręcznie budowany dict)
  uzupełniony o oba pola. `create` (`Contract(**model_dump())`) i `update`
  (`setattr`) pociągają je automatycznie.

### Frontend
- `app/contracts/new/page.tsx` — pola **Stawka z umowy ramowej** i **Line
  Manager**, wpięte w payload `POST /api/contracts`.
- `app/contracts/[id]/page.tsx` — oba pola w widoku (sekcja „Osadzenie u
  klienta" + sidebar stawek jako „Z umowy ramowej") oraz w trybie edycji
  (PATCH): typ `ContractDetail`, `EditForm`, `contractToForm`, `handleSave`.
- **Fix walidacji:** `step="100"` → `step="1"` na wszystkich inputach stawek
  (kandydat / klient / ramowa / widełki min-max) w obu formularzach. Kolumny
  są `INTEGER`, więc `step="1"` przyjmuje dowolną liczbę całkowitą i nie
  dopuszcza ułamków (które backend `Optional[int]` by odrzucił 422).

## Decyzje / założenia
- **„Stawka z umowy ramowej" = pole wprowadzane ręcznie** (referencyjne).
  `ClientFrameworkContract` (MSA) nie trzyma stawki per-rola, więc nie ma
  źródła do auto-pobrania — najbliżej są `rate_cards` (per klient×rola), ale
  to osobny mechanizm; tu wystarcza wartość odniesienia wpisywana przez TAC.
- **„Line Manager" = pojedyncze pole tekstowe (imię i nazwisko)**, odrębna
  rola od `client_pm_name` (PM projektu). W razie potrzeby łatwo dodać email.

## Weryfikacja
- `ruff` + `py_compile` (zmienione pliki BE) — czysto.
- `tsc --noEmit` — exit 0.
- `next lint` — exit 0 (tylko pre-existing warnings poza zmienianymi plikami).
- CI na PR: `alembic upgrade head` + `pytest` (realny Postgres), frontend build.
- **TODO po merge:** Chrome smoke — utworzenie kontraktu ze stawką `115` +
  oba nowe pola, weryfikacja zapisu na `/contracts/[id]`.

## Pliki
- `backend/alembic/versions/0142_contracts_framework_rate_line_manager.py` (new)
- `backend/app/models/contract.py`
- `backend/app/schemas/contract.py`
- `backend/app/api/contracts.py`
- `frontend/src/app/contracts/new/page.tsx`
- `frontend/src/app/contracts/[id]/page.tsx`
