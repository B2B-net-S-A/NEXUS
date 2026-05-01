# Traffit API — Discovery report (Faza 0)

> Wynik POC + counters + sample fetch z tenanta `b2bnetwork`. Generowane 2026-05-01.
> Plan migracji: [`traffit-migration-plan.md`](./traffit-migration-plan.md) +
> [`~/.claude/plans/crm-activities-bez-woolly-fairy.md`](../../../.claude/plans/crm-activities-bez-woolly-fairy.md).

## 1. Auth

- **Tenant URL:** `https://b2bnetwork.traffit.com` (**bez `www.`** — cert SSL nie pokrywa `*.www.traffit.com`)
- **Token endpoint:** `POST https://b2bnetwork.traffit.com/oauth2/token`
- **Działają oba formaty:** `application/json` i multipart/form-data — używamy JSON (czytelniejsze).
- **Token TTL:** `expires_in: 2592000` (30 dni).
- **Token format:** 40-znakowy hex string, `token_type: Bearer`.
- **Scope w prompcie Artura:** wszystkie 17 zapotrzebowanych zwracają HTTP 200 — zero gap, nie potrzebujemy dodatkowego setupu z Account Managerem Traffita.

## 2. Counters (skala migracji)

| Encja | Endpoint | Total | Komentarz |
|---|---|---:|---|
| **Kandydaci** | `/employees/` | **43,573** | Główny chunk Fazy 5 |
| **Recruitments / Joby** | `/recruitments/` | **3,793** | Faza 5 |
| **Sources** (per kandydat) | `/sources/` | **75,426** | ~1.7 źródła na kandydata |
| **Klienci** | `/clients/` | **146** | Faza 4 |
| **CRM persons** | `/crm_persons/` | **347** | Faza 4 — kontakty |
| **Talent pools** | `/talents/` | 98 | Faza 5 |
| **Users** | `/users/` | 141 | Mapping po emailu (read-only) |
| **CRM activities** | `/crm_activities/` | 108 | **NIE importujemy** (decyzja Artura) |
| **Workflows** | `/workflows/` | 2 | Łatwy mapping na pipeline_templates |
| **Provisions** | `/provisions/` | 2 | Skip (nie używamy w Nexusie) |
| **Job posts** | `/job_posts/` | — | **404** — endpoint inny niż w docs; sprawdzić w Fazie 5 |

## 3. Krytyczne odkrycia

### 3.1 `guid` field NIE występuje w response — używamy `id` (int)

`X-Response-Metadata: true` deklaruje pole `guid` w schemach każdej encji
(`required: false`), ale **regularne odpowiedzi go nie zawierają** — nawet z
`X-Additional-Modules: guid`. Pewnie historyczne dane z API v1 nie mają GUID-ów.

**Decyzja:** `external_id = str(traffit_id)` (int). W obrębie tenanta stabilne.
Idempotent UPSERT na `(external_source='traffit', external_id=str(id))` działa.

### 3.2 Endpointy bez trailing slash redirektują 301

`/talents/`, `/workflows/`, `/sources/`, `/provisions/` zwracają 301 → ten sam path bez `/`.
`/employees/`, `/recruitments/`, `/clients/`, `/crm_persons/`, `/users/` są OK z `/`.
**TraffitClient musi follow-redirect** (curl `-L`, httpx `follow_redirects=True`).

### 3.3 Schema w tym tenantcie jest skąpa — szczególnie clients i crm_persons

**Pełna lista pól w response (regularnie + przez X-Additional-Modules):**

#### `clients` — TYLKO 8 pól
```
id, name, status, created_at, created_by{id}, updated_at, updated_by{id}
```
- **Brak:** phone, email, website, address, industry, nip, regon
- `status` to free text PL/EN ("Aktywny", "active") — nie enum
- → po imporcie Artur uzupełnia te pola ręcznie w UI Nexusa (146 klientów)

#### `crm_persons` — 11 pól
```
id, name, lastname, email, status, client{id},
created_at, created_by{id}, updated_at, updated_by{id}
```
- **Brak:** phone, mobile, position, department, is_decision_maker, notes
- → te pola w `Contact` Nexusa zostają puste; uzupełniane ręcznie

#### `employees` (kandydaci) — 24 pola, **bogatszy shape**
```
id, name, lastname, email, mobile, linkedin, linkedin_id, status,
candidate_about, candidate_location, candidate_languages,
files [{filename, file_uploaded}],          ← inline lista plików
_Position, _certificates, _education, _experience, _nationality,
_previous_employers, _technologie,           ← custom fields per tenant
created_at/by, updated_at/by
```
- Custom fields prefixowane `_` — często NULL, ale gdy są to mają wartości typu text
- `files` inline z filename + datą upload — **bez ID pliku**, więc binary trzeba pobrać przez `GET /employees/{id}/files` (osobny call)

#### `recruitments` — 13 pól
```
id, name, nrRef, client{id}, workflow_id, responsible_person, status,
closing_date, is_closed, is_confidential,
created_at/by, updated_at/by
```
- Workflow per recruitment tylko jako ID — workflow detail osobno
- `nrRef` — externalny numer referencyjny (mapuje się do `Job.reference_number`)

### 3.4 Workflow states są ustandardyzowane przez `type`

Pierwszy workflow (`B2B`, id=4) ma 14+ state'ów z type'ami:
`start`, `screening`, `initial_accept`, `technical_verification`, `task`,
`client_verification` + `is_rejection: true` na rejected states.

**Mapowanie na `PipelineStage` Nexusa** (do wpisania w `traffit_state_to_pipeline_stage.yaml` w Fazie 5):

| Traffit `type` | Nexus `PipelineStage` |
|---|---|
| `start` | `new` |
| `screening` | `screening` |
| `initial_accept` | `verified` |
| `technical_verification` | `interview` |
| `task` | (ad-hoc — `screening` z notatką) |
| `client_verification` | `cv_sent` lub `client_interview` (per state name) |
| `is_rejection: true` | `rejected` |

Tylko **2 workflowy total** → mapping w 1h. Pełne dumps states w fixtures.

### 3.5 X-Response-Metadata zwraca meta-schemę zamiast danych

To narzędzie **discovery, nie produkcyjne**. Bez nagłówka — pełne dane.
Schema jest jednak skrócona (np. crm_persons schema deklaruje 12 pól, regular
response zwraca 11). Ground truth: **regular response**, nie schema.

## 4. Decyzje / wpływ na plan migracji

### 4.1 `external_id = str(traffit_id)` (int → string)
Brak GUID w tym tenantcie. Reszta planu bez zmian.

### 4.2 Pole `external_payload JSONB` na `Contact` — niepotrzebne
W b2bnetwork tenantcie `crm_persons` nie ma custom fields. Migracja Alembic
1.1 może to pole **pominąć**. Ale: **na `candidates` `external_payload` JSONB
będzie kluczowe** (custom fields `_Position`, `_certificates`, etc.).
Update planu: dodaj `external_payload` na `candidates`, **nie** na `contacts`.

### 4.3 Mapping `client.status` (free text → enum)
- "Aktywny" / "active" / "Active" → `ClientStatus.active`
- "Nieaktywny" / "inactive" → `ClientStatus.inactive`
- "Prospekt" / "prospect" / "Lead" → `ClientStatus.prospect`
- inne (raw) → `external_payload` JSONB + `status='active'` jako fallback
- **Decyzja:** dorzućmy `external_payload JSONB` na `clients` zamiast na `contacts`
  (raw `status`, raw `name` przed normalizacją, surowe metadane).

### 4.4 Wąskie gardło Fazy 5: 43k kandydatów × CV files
Każdy CV to osobny request `/employees/{id}/files/{file_id}/content`. Przy
throttle 5 req/s — **~150 minut na same CV** (najwolniej). Plus list paginacja
+ detail + files metadata = **~5h netto** dla całej Fazy 5 jeśli wszystko gładko.

### 4.5 `/crm_activities/` ma 108 wpisów — i tak ich nie importujemy
Zgodnie z decyzją Artura. Ale: **Faza 6 (webhook live sync) musi tego nie
subskrybować** — żeby nie wciągać activities incrementalnie.

## 5. Fixtures

Anonymizowane (PII zastąpione placeholderami) w
`backend/tests/fixtures/traffit/`:

```
clients_{list,detail,schema}.json
crm_persons_{list,detail,schema}.json
employees_{list,schema}.json
recruitments_{list,detail,schema}.json
talents_{list,detail}.json
users_{list,detail}.json
workflows_{list,detail,4_detail,details}.json
sources_list.json
```

Bezpieczne do commit'u — nie zawierają imion, emaili, telefonów, ani nazw klientów.

## 6. Następne kroki

1. **Faza 1** — 3 migracje Alembic (external_ids na clients/contacts/+candidates `external_payload`,
   required_document_templates, client_required_documents) + seed 4 startowe szablony
2. **Faza 2** — backend endpoints required-documents
3. **Faza 3** — frontend MaterialsTab sub-tabs
4. **Faza 4** — TraffitClient + mappers + importer dla clients/contacts (najpierw, łatwa skala)
5. **Faza 5** — kandydaci/joby/pipelines (po sprawdzeniu Fazy 4 na małej skali)

## 7. Coolify env vault — wymagane sekrety

Po akcepcie Fazy 0:
```
TRAFFIT_TENANT=b2bnetwork
TRAFFIT_CLIENT_ID=b2bnetwork_NEXUS
TRAFFIT_CLIENT_SECRET=<z prompta Artura, kopiuj wprost do Coolify env vault — NIGDY do repo>
TRAFFIT_THROTTLE_RPS=5
```
