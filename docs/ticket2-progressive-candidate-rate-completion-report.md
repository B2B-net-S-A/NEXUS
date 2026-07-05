# Ticket 2 — Progresywna stawka kandydata w formularzu „Nowy kontrakt"

**PR:** [#645](https://github.com/artur-t-96/Nexus/pull/645) · **Data:** 2026-07-05

## Cel (ticket)

- **Jest:** W formularzu *Nowy kontrakt* brak możliwości wprowadzenia progresywnej
  stawki kandydata już na etapie tworzenia kontraktu.
- **Ma być:** Przycisk **„Dodaj stawkę progresywną"** umożliwiający zaplanowanie
  kolejnych etapów stawki kandydata od razu przy tworzeniu. Każdy etap zawiera
  pola: **Stawka kandydata**, **„Obowiązuje od"** oraz **„Obowiązuje do"**.

## Decyzje (uzgodnione z Arturem)

1. **Które formularze:** W NEXUS istnieją *dwa* ekrany „Nowy kontrakt". Wybrano
   **oba** (spójny UX):
   - `/contracts/new` — główny formularz (pełne warunki finansowe). Miał już
     harmonogram *Stawka + Obowiązuje od* (PR #582); dołożono „Obowiązuje do"
     i przemianowano przycisk.
   - Rejestr per-klient (`ContractRegisterDialog`, start: Nordea) — dotąd bez
     żadnych pól stawki. Dodano sekcję od zera (tylko tryb tworzenia).
2. **Pole „Obowiązuje do":** **auto-wyliczane** (read-only), = „Obowiązuje od"
   kolejnego etapu minus 1 dzień; ostatni etap = „bezterminowo". Użytkownik nie
   wpisuje go ręcznie — zgodne ze schodkowym resolverem stawki (kluczowanym po
   `effective_from`).

## Integracja z równolegle scalonym PR #644 (Ticket 1)

W trakcie prac na `main` wylądował **PR #644** („Dodaj stawkę progresywną" w
formularzu **Edycja kontraktu**), który:
- dodał **realną, nullable kolumnę `effective_to`** (`contract_candidate_rates`,
  migracja **0154**) + pola w `ContractCandidateRateInput`/`Entry` +
  `ContractUpdate.candidate_rate_schedule`; `create_contract` już zapisuje
  `effective_to`;
- w formularzu Edycji zrobił „Obowiązuje do" **edytowalnym** (zapis do kolumny).

Rekonciliacja (po scaleniu `main` do tej gałęzi): moje formularze **wysyłają**
wyliczone `effective_to` (mimo że pole jest read-only), aby zapisany harmonogram
był **spójny** z edytowalnym edytorem etapów z PR #644 — kontrakt utworzony tu
pokazuje te same daty „do" po otwarciu w Edycji. Świadoma różnica UX: wpis „do"
przy *tworzeniu* jest auto-wyliczany (wybór Artura), przy *edycji* — edytowalny.
`effective_to` pozostaje doradcze (resolver liczy stawkę po `effective_from`).

## Zmiany

| Plik | Rodzaj | Opis |
|---|---|---|
| `frontend/src/lib/contract-rate-schedule.ts` | nowy | Czysty helper: `isoMinusOneDay`, `effectiveTo`, `formatEffectiveTo`, `buildCandidateRateSchedule`, typy `RateScheduleRow`/`RateScheduleStep`. |
| `frontend/src/components/contracts/CandidateRateScheduleFields.tsx` | nowy | Współdzielony komponent: etapy `{Stawka, Obowiązuje od, Obowiązuje do}` + przycisk „Dodaj stawkę progresywną". |
| `frontend/src/app/contracts/new/page.tsx` | zmiana | Inline harmonogram zastąpiony współdzielonym komponentem (−97 linii). |
| `frontend/src/components/contracts/ContractRegisterDialog.tsx` | zmiana | Sekcja progresywnej stawki (create-only), payload `candidate_rate_schedule`, walidacja unikalnych dat, reset-on-open. |
| `frontend/src/lib/__tests__/contract-rate-schedule.test.ts` | nowy | 18 testów jednostkowych helpera. |

## Backend

**Bez zmian po mojej stronie** — cały backend `effective_to` przyszedł z PR #644
(scalony do tej gałęzi): `ContractCreate.candidate_rate_schedule`,
`ContractCandidateRateInput.effective_to`, migracja 0154 i zapis w
`create_contract`. Front dosyła wyliczone `effective_to`; resolver stawki
(`Contract._resolve_scheduled_rate`) liczy po `effective_from` — bez zmian.

## Semantyka „Obowiązuje do"

```
Etap 1: 150 zł  od 2026-01-01  do 2026-06-30
Etap 2: 165 zł  od 2026-07-01  do 2026-12-31
Etap 3: 180 zł  od 2027-01-01  do bezterminowo
```

Odporne na kolejność wpisywania (porównanie ISO = chronologiczne); etapy bez
wpisanej stawki są pomijane; pierwszy etap bez daty „od" dziedziczy datę
rozpoczęcia kontraktu.

## Weryfikacja

- `vitest run` — 18/18 (helper) ✅
- `npm run type-check` — ✅
- `next lint` (touched) — ✅ (jedyny warning: pre-existing nieużywany `Loader2`
  w `new/page.tsx`, niezwiązany, pod capem `--max-warnings=300`)
- `npm run build` — ✅
- UI smoke przez Chrome po deploy — do zrobienia po merge.

## Znane ograniczenia / świadomy out-of-scope

- Rejestr per-klient (tabela `ClientContractRegister`) nie pokazuje kolumny
  stawki — seedowana stawka jest widoczna w profilu kontraktu. Ticket dotyczy
  *wprowadzania*, nie wyświetlania w rejestrze.
- Edycja stawek istniejącego kontraktu nadal idzie przez aneksy „Zmień stawkę"
  (sekcja progresywnej stawki w dialogu pokazuje się tylko przy tworzeniu).
- Pre-existing nieużywany import `Loader2` w `contracts/new/page.tsx` zostawiony
  świadomie (poza zakresem ticketu).
