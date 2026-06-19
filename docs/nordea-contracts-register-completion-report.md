# Per-klient rejestr kontraktów (Nordea) — completion report

> 2026-06-19. Pierwsza iteracja: rejestr kontraktów per klient na `/contracts`,
> uruchamiany przez wybór klienta. Start: Nordea (client_id=11).

## Cel

Artur: „kontrakty per klient będą wyglądały inaczej, bo czasami to czasowe,
czasami pula godzin do wykorzystania. Najpierw zrobimy kontrakty do Nordea."
Wymagane pola: numer projektu (ID), nazwa projektu, imię i nazwisko konsultanta,
start day, end day, status prolongacji (unknown/Yes/No/Negotiate) + co uznam za
słuszne.

## Decyzje (potwierdzone z Arturem)

1. **Gdzie:** `/contracts` z wyborem klienta → rejestr per klient (skaluje się
   na kolejnych klientów).
2. **Model:** rozszerzyć istniejącą tabelę `contracts` (była pusta, 2 wiersze;
   już spina kandydata↔klienta↔ofertę + alerty wygasania).
3. **Pula godzin:** oba warianty od razu — czasowy (start/end) i pula godzin
   (budżet / wykorzystane / pozostałe / % zużycia).

## Co zrobione

### Backend
- **Migracja `0138_contracts_per_client_register`** (chain z `0137`, idempotentna
  `DO $$ IF NOT EXISTS $$` + `ADD COLUMN IF NOT EXISTS` + index):
  - `project_code` VARCHAR(64) — numer/kod projektu klienta (osobny od `id`).
  - `prolongation_status` enum `prolongationstatus` (unknown/yes/no/negotiate),
    default `unknown`, indeks.
  - `engagement_model` enum `engagementmodel` (time_based/hours_pool),
    default `time_based`.
  - `hours_pool_total`, `hours_pool_consumed` INTEGER.
- **Model `Contract`** (`app/models/contract.py`): enumy `ProlongationStatus` +
  `EngagementModel`, pola jak wyżej, properties `hours_pool_remaining` +
  `hours_pool_usage_pct`. `project_name` istniał już wcześniej.
- **Schematy** (`app/schemas/contract.py`): nowe pola w `ContractCreate`,
  `ContractUpdate`, `ContractResponse` (+ computed remaining/pct). Lista
  (`GET /api/contracts?client_id=`) i tak kopiuje wszystkie pola `ContractResponse`
  przez `getattr`, więc properties są zwracane automatycznie.
- **API** (`app/api/contracts.py`): `_to_detail` rozszerzony o nowe pola
  (PATCH/detail zwracają komplet). `list_contracts` już wspierał `client_id`.
  Inline edycja prolongaty = istniejący `PATCH /api/contracts/{id}`.
- **Test** `test_contract_register_fields_round_trip` (in-process): create z pulą
  godzin + prolongatą, weryfikacja computed (remaining=150, pct=25.0), PATCH
  prolongaty, lista per klient zwraca pola.

### Frontend
- **`lib/contract-register.ts`** — etykiety PL + warianty Badge dla prolongaty,
  modelu rozliczeń, statusu; typ `RegisterContractRow`.
- **`ContractsClientPicker`** — combobox klienta (z `/api/clients-lookup`) +
  „Wszyscy klienci (lista globalna)".
- **`ClientContractRegister`** — tabela rejestru: Nr projektu · Projekt ·
  Konsultant · Model · Okres / Pula godzin · Prolongata · Status. Inline-editowalna
  prolongata (Select z kolorem wg statusu, optimistic update) — gated rolą
  (admin/DL/TAC). Pula godzin: pasek postępu + pozostałe/% (czerwony gdy >100%).
- **`ContractRegisterDialog`** — dodawanie/edycja kontraktu (konsultant combobox,
  nr/nazwa projektu, model rozliczeń, daty lub pula godzin, prolongata, status).
- **`/contracts/page.tsx`** — wybór klienta w URL (History API: `?client=11&
  clientName=Nordea`). Brak klienta → globalna lista (bez zmian). Wybrany klient →
  rejestr.

## Weryfikacja

- `ruff check` (app + migracja + test) — pass.
- `tsc --noEmit` (cały frontend) — 0 błędów.
- Import backendu + properties + schematy Create/Update — OK (remaining=150,
  pct=25.0).
- Prod head potwierdzony `0137_talent_pool_is_personal` → migracja chainuje
  poprawnie.

## Znane ograniczenia / next

- `hours_pool_consumed` jest ręczne (brak auto-zliczania z godzin/timesheetów).
- Rejestr ładuje do 100 kontraktów na klienta (page_size=100, bez paginacji UI) —
  wystarczy na start; dodać paginację gdy klient przekroczy 100.
- Per-klient „inny layout" = dziś wspólne kolumny + per-wiersz model rozliczeń.
  Jeśli pojawi się klient z istotnie innym zestawem pól, rozważyć konfigurację
  kolumn per klient.
- Wariant godzinowy ma `start_date` wymagane (kontrakt-create) — pula też ma datę
  startu (sensowne dla rejestru).
