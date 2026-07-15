# Contract framework-rate schedule — completion report

**Data:** 2026-07-15
**Branch:** `claude/contract-rate-scheduling-ce1cc2`

## Cel

„Stawka z umowy ramowej" była pojedynczą wartością w formularzach „Nowy kontrakt"
i „Edycja kontraktu". Teraz można zaplanować zmianę stawki ramowej w czasie —
kolejne etapy z polami **Stawka**, **Obowiązuje od**, **Obowiązuje do** (np. gdy
klient zmienia stawkę ramową w trakcie współpracy). Wzorowane 1:1 na istniejącym
harmonogramie stawki kandydata (`ContractCandidateRate`, migracja 0144).

## Model / rozwiązywanie

- Nowa tabela `contract_framework_rates` (`ContractFrameworkRate`) — `rate`
  `NUMERIC(12,2)` (jak kolumna `contracts.framework_rate`), `effective_from`,
  `effective_to` (doradcze), `note`, `created_by`.
- `Contract.framework_rate_schedule` (relationship, cascade delete) +
  `Contract.effective_framework_rate(on)` — reużywa `_resolve_scheduled_rate`
  (najpóźniejszy `effective_from <= on`, fallback na kolumnę `framework_rate`).
- Stawka ramowa **nie wchodzi do marży** (wartość referencyjna) — harmonogram
  trzyma tylko kolumnę `framework_rate` zsynchronizowaną z krokiem obowiązującym
  dziś, a `_effective_rate_fields` wylicza ją przy odczycie (planowana zmiana
  pojawia się w swojej dacie bez edycji).

## Pliki

**Backend**
- `app/models/contract_framework_rate.py` (nowy), `app/models/__init__.py`
- `app/models/contract.py` — relationship + `effective_framework_rate`
- `alembic/versions/0165_contract_framework_rate_schedule.py` (nowy)
- `entrypoint.sh` — safety-net `CREATE TABLE contract_framework_rates` (prod ma
  chroniczny multi-head drift; nowe tabele MUSZĄ być mirrorowane tutaj)
- `app/schemas/contract.py` — `ContractFrameworkRateInput/Entry` + pole
  `framework_rate_schedule` w Create/Update/Response
- `app/api/contracts.py` — build w create/update, `_framework_schedule_entries`,
  serializacja w `_to_detail`/list/expiring, derywacja w `_effective_rate_fields`,
  eager-load `framework_rate_schedule` we wszystkich blokach `_to_detail`/getattr,
  `_FINANCIAL_CONTRACT_INPUT_FIELDS`

**Frontend**
- `components/contracts/CandidateRateScheduleFields.tsx` — uogólniony
  (`label`/`hint`/`addLabel`), domyślne etykiety = stawka kandydata
- `app/contracts/new/page.tsx` — edytor etapów stawki ramowej (`framework_rate_schedule`)
- `app/contracts/[id]/page.tsx` — inline edytor (plain input ↔ harmonogram,
  „Dodaj etap stawki ramowej"), prefill z persisted schedule, payload logic

**Testy / CI**
- `tests/test_contract_framework_rate_schedule.py` (nowy) + wpis w `.github/workflows/ci.yml`

## Weryfikacja

- Frontend: `tsc --noEmit` 0 błędów; lint bez nowych błędów (tylko pre-existing
  unused-import warnings).
- Backend: brak lokalnego Pythona 3.12 → pytest walidowany w CI (`Backend (ruff
  + pytest)`), test dodany do selektywnej listy.

## Znane ograniczenia / uwagi

- `framework_rate_schedule` serializowany jest tylko dla ról z dostępem
  finansowym (`ContractOperationalResponse` go pomija — jak reszta stawek).
- Backward-compatible: istniejące kontrakty bez harmonogramu używają kolumny
  `framework_rate` (zero backfillu).
