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
   kolejnego etapu minus 1 dzień; ostatni etap = „bezterminowo". Bez nowej
   kolumny / migracji — zgodne z istniejącym schodkowym resolverem stawki.

## Zmiany

| Plik | Rodzaj | Opis |
|---|---|---|
| `frontend/src/lib/contract-rate-schedule.ts` | nowy | Czysty helper: `isoMinusOneDay`, `formatEffectiveTo`, typ `RateScheduleRow`. |
| `frontend/src/components/contracts/CandidateRateScheduleFields.tsx` | nowy | Współdzielony komponent: etapy `{Stawka, Obowiązuje od, Obowiązuje do}` + przycisk „Dodaj stawkę progresywną". |
| `frontend/src/app/contracts/new/page.tsx` | zmiana | Inline harmonogram zastąpiony współdzielonym komponentem (−97 linii). |
| `frontend/src/components/contracts/ContractRegisterDialog.tsx` | zmiana | Sekcja progresywnej stawki (create-only), payload `candidate_rate_schedule`, walidacja unikalnych dat, reset-on-open. |
| `frontend/src/lib/__tests__/contract-rate-schedule.test.ts` | nowy | 11 testów jednostkowych helpera. |

## Backend

**Bez zmian.** `ContractCreate.candidate_rate_schedule` + endpoint `POST /api/contracts`
już seedowały harmonogram (`ContractCandidateRate`) i wyliczały bieżące
`rate_candidate`. Pole „Obowiązuje do" jest wyłącznie prezentacyjne (front),
więc resolver stawki (`Contract._resolve_scheduled_rate`, kluczowany po
`effective_from`) pozostaje nietknięty — brak migracji, niemożliwe luki/nakładki.

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

- `vitest run` — 11/11 (helper) ✅
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
