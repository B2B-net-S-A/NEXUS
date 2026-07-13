# Rozbudowa modułu Kontrakty — raport końcowy

**Data:** 2026-04-22
**Deploy:** commits 67c6fa3 → ce5f515 → 3874f78 → 13bb330 → dab6db7 (main)
**Prod URL:** https://nexus.dynaminds.pl · API: https://api.nexus.dynaminds.pl

## Zakres zrealizowany wg wytycznych Artura

| Wymaganie | Realizacja |
|---|---|
| Start/end day → długość życia | ✅ istniało (`contracts.start_date/end_date`) |
| **Powód zakończenia współpracy + wnioski** | ✅ `termination_reason` (enum 10) + `termination_lessons` + `terminated_at` + dedykowany `POST /{id}/terminate` + dialog UI |
| Stawka kosztowa/przychodowa | ✅ istniało; rozszerzone o `target_rate_min/max` |
| **Stawka vs średnia nasza / raporty rynkowe** | ✅ `GET /{id}/benchmark` + tabela `rate_benchmarks` + Settings admin page z CSV import + karta "Benchmark stawki" na stronie kontraktu |
| Marża % / liczbowo / ARR na kliencie | ✅ istniało (`/margin-by-contractor`, `/margin-by-client`, `/revenue-forecast`) |
| **Kategoryzacja po roli i kliencie + predykcje** | ✅ `GET /contract-analytics/role-client-mix` (role × client heatmap, %) |
| **Flagi zaangażowania konsultanta** | ✅ 5 bool flag (ambasador / weryfikator / side projects / sales / expert) + `engagement_notes` na `candidates` + panel UI + `PATCH /candidates/{id}/engagement` |
| **Data końca zamówienia u klienta + przypomnienia** | ✅ `client_order_end_date` + task `contract_alerts`: 90/60/30/14/7d przed `end_date` + 30d przed `client_order_end_date` |
| **Info o sprzęcie + przypomnienia o zwrocie** | ✅ tabela `contract_equipment` (typ/owner/serial/kaucja/terminy) + tab UI + alert equipment_return_due_14d |
| Umowa i dokumenty + śledzenie zmian | ✅ istniało (`contract_documents` + `contract_amendments`) |
| **Dane kontaktowe + lokalizacja konsultantów** | ✅ `candidates.city/country/region/hub_city/lat/lng` + panel UI + heat-map w `/contract-analytics/location-distribution` |
| **Historia rozmów/notatek per kontrakt** | ✅ `notes.contract_id` + `calls.contract_id` + `GET /{id}/notes` timeline + tab "Notatki / Rozmowy" |

## Artefakty

### Migracja
- `backend/alembic/versions/0037_contracts_expansion.py` (idempotent, down_revision=`0034_merge_phase8_heads`)
- Fallback: `backend/entrypoint.sh` dodaje wszystkie enumy + kolumny idempotentnie (wzór jak 0028+ handling legacy multi-head)

### Nowe modele
- `backend/app/models/contract_equipment.py` — `ContractEquipment`, `EquipmentItemType`, `EquipmentOwner`, `EquipmentReturnStatus`
- `backend/app/models/rate_benchmark.py` — `RateBenchmark`, `SeniorityLevel`
- Rozszerzone: `contract.py` (+`ContractTerminationReason` + 6 pól), `candidate.py` (+11 pól), `note.py`/`call.py` (+`contract_id`), `notification.py` (+3 enum values)

### Nowe endpointy API
| Method | Ścieżka | Opis |
|---|---|---|
| GET/POST | `/api/contracts/{id}/equipment` | Lista + create equipment |
| PATCH/DELETE | `/api/contracts/{id}/equipment/{eq_id}` | Update / usuń |
| GET | `/api/contracts/{id}/notes` | Timeline notes+calls |
| POST | `/api/contracts/{id}/terminate` | Atomowe zakończenie z powodem + lessons |
| GET | `/api/contracts/{id}/benchmark` | Porównanie stawki |
| PATCH | `/api/candidates/{id}/engagement` | Update flag zaangażowania |
| PATCH | `/api/candidates/{id}/location` | Update lokalizacji |
| GET/POST/PATCH/DELETE | `/api/rate-benchmarks` | CRUD |
| POST | `/api/rate-benchmarks/import` | CSV import |
| GET | `/api/contract-analytics/role-client-mix` | Heatmapa rola × klient |
| GET | `/api/contract-analytics/location-distribution` | Rozkład po hub/region |
| GET | `/api/contract-analytics/termination-analysis` | Powody + retencja |

### Task `contract_alerts` (rozszerzony)
- Thresholdy: **90** / 60 / 30 / 14 / 7 dni
- Nowe triggery: `equipment_return_due_14d`, `client_order_ending_30d`
- Dedup via `related_entity_type`/`related_entity_id` + partial unique index `ix_notif_dedup_daily`

### Frontend
**Nowe komponenty** (`frontend/src/components/`):
- `contracts/ContractEquipmentTab.tsx` — pełna tabela + add/edit/mark-returned
- `contracts/ContractTerminationDialog.tsx` — modal z powodem + lessons
- `contracts/ContractRateBenchmarkCard.tsx` — porównanie stawki w Details tab
- `contracts/ContractNotesTab.tsx` — połączony timeline notes+calls
- `candidates/CandidateEngagementPanel.tsx` — 5 flag + notatka
- `candidates/CandidateLocationPanel.tsx` — city/country/region/hub (datalist)

**Rozszerzone strony:**
- `/contracts/[id]` — +2 taby (Sprzęt, Notatki/Rozmowy), benchmark card, pola `client_order_end_date`/`target_rate_min/max` w formie edycji, dialog termination przy zmianie statusu→ended
- `/contracts/analytics` — +3 sekcje (role×client heatmapa, location, termination)
- `/candidates/[id]` — +2 panele w ProfilTab (engagement, location)
- `/settings/rate-benchmarks` — nowa strona admin (CRUD + CSV import)

**API client:** `frontend/src/lib/api.ts` — `contractsApi.{terminate, benchmark, notesTimeline}`, `contractEquipmentApi`, `candidateProfileApi`, `rateBenchmarksApi`, `contractAnalyticsExpansionApi`, stała `CONTRACT_TERMINATION_REASONS` (PL labels).

### Testy
5 nowych suit (`pytest`, in-process app_client):
- `test_contracts_expansion.py` — equipment CRUD, terminate, benchmark shape, notes timeline
- `test_rate_benchmarks.py` — CRUD + CSV import (happy path + malformed rows)
- `test_candidate_engagement.py` — engagement PATCH + location (country uppercasing, empty body 422)
- `test_contract_analytics_expansion.py` — shape check 3 endpointów
- `test_contract_alerts_expansion.py` — 90d w thresholds + stats keys

## Weryfikacja E2E (historyczna; wycofane konto syntetyczne, nie używać ponownie)

| Test | Wynik |
|---|---|
| `https://nexus.dynaminds.pl/contracts/1` — 9 tabów (w tym **Sprzęt**, **Notatki/Rozmowy**) | ✅ |
| Tab Sprzęt: header "Sprzęt kontraktora", btn "Dodaj sprzęt", empty state | ✅ |
| Details: karta "Benchmark stawki" widoczna | ✅ |
| `/contracts/analytics`: Rola × Klient, Lokalizacja konsultantów, Analiza zakończeń | ✅ |
| `/settings/rate-benchmarks`: "Benchmarki stawek" header, btn Dodaj + Import CSV | ✅ |
| `/candidates/1`: Zaangażowanie + Lokalizacja panele (Ambasador firmy, Hub, Miasto) | ✅ |
| API curl: `/api/contracts` 200 · `/api/rate-benchmarks` 200 · `/api/contract-analytics/role-client-mix` 200 (5 aktywnych) | ✅ |

## Gotchas napotkane w trakcie

1. **Zarażenie commita pre-existing WIP.** `git add` na `frontend/src/components/v2/pages/CandidateDetailV2.tsx` i `backend/app/main.py` wciągnęło niescommitowane zmiany M365 (EmailThreadList import, tiptap/dompurify deps, microsoft365_api router) → frontend build crashował na webpack Module not found, backend crashował na ImportError. Fix: `git checkout 90d9e38 -- <file>` + re-apply tylko moich zmian (3874f78 + 13bb330).

2. **Migracja 0037 down_revision.** Początkowo `0036_microsoft365` (lokalnie niescommitowane) → alembic KeyError. Fix: `down_revision = "0034_merge_phase8_heads"` (aktualny prod head).

3. **Alembic 0037 nie zaaplikował się na prod.** Produkcyjne schema zostało w stanie pre-0037 → `/api/contracts` 500 na ORM SELECT (brak kolumn). Fix: dodanie 24 nowych `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + 6 `CREATE TYPE IF NOT EXISTS` do `entrypoint.sh` safety net (pattern jak `cf0d8c0`/`c427278`). Po kolejnym deployu wszystkie kolumny weszły.

## Znane ograniczenia / backlog

- **Geocoding lat/lng** — kolumny zdefiniowane, ale nie wypełniane automatycznie. W UI można dopisać ręcznie; map-view wymaga Mapbox/Leaflet (backlog).
- **Role extraction** (benchmark/analytics) fallbackuje do `candidate.competence_category` gdy brak `job.title`. Pełne NLP matchowanie roli wymaga osobnej pracy.
- **CSV seniority** w imporcie musi być lowercase z enum. Dokumentacja header formatu w UI przy importerze.
- **Strona listy `/contracts`** (ContractsListV2) renderuje sam AppShell bez tabeli — zjawisko pre-existing, nie z mojej rozbudowy (detail `/contracts/{id}` działa poprawnie). Do zbadania osobno.
- **M365 WIP** zachowany w `git status` (niescommitowany) — nie został włączony do tej pracy, bo nie był w scope.

## Pliki zmienione/dodane

**Backend:** 24 pliki (5 nowych modeli/schematów, 4 edytowane modele, 2 edytowane API, 1 nowy API, migracja, task, entrypoint, 5 test suit).
**Frontend:** 10 plików (7 nowych komponentów/stron, 3 edytowane: lib/api.ts, contracts/[id]/page.tsx, contracts/analytics/page.tsx, CandidateDetailV2.tsx).

Szczegółowy diff: `git diff 90d9e38..dab6db7 --stat`.
