# Migracja Traffit → Nexus (plan)

> Status: **w trakcie** (2026-05-01). Faza 0-3 zmergowana w PR #63 (migracje schema,
> backend required-documents, UI „Wymagane dokumenty"). Faza 4 (importer
> clients+contacts) — w toku. CRM activities wykluczone — patrz
> `~/.claude/plans/crm-activities-bez-woolly-fairy.md` dla pełnego scope tego
> ścieżkowania.
>
> Cel: jednorazowa migracja całej historii rekrutacyjnej z Traffita do Nexusa
> + opcjonalny incremental sync przez webhooki przez okres koegzystencji.

## 1. API Traffita — co już wiemy

### 1.1 Auth (OAuth2 client credentials)
- **Token endpoint:** `POST https://www.<tenant>.traffit.com/oauth2/token`
  - parametry: `client_id`, `client_secret`, `grant_type=client_credentials`, `scope`
  - dokumentacja knowledge.traffit.com mówi `Content-Type: application/json`,
    ale przykłady curl (multipart `-F`) sugerują że oba formaty działają — **pierwszy
    POC test rozstrzygnie**
  - **Token TTL = 30 dni** → cache w pamięci procesu, refresh przy 401
- **Authorization:** `Bearer <access_token>` na każdym requeście
- **Tenant w URL:** wpisz nazwę instancji (prawdopodobnie `b2bnetwork` z client name
  `b2bnetwork_NEXUS` — **do potwierdzenia eksperymentalnie**)

### 1.2 Base URL
- Integration API v2: `https://www.<tenant>.traffit.com/api/integration/v2/`
- Public (unauth): `https://www.<tenant>.traffit.com/public/`

### 1.3 Pagination i filtrowanie (przez nagłówki, nie query string)

Request:
```
X-Request-Page-Size: 200
X-Request-Current-Page: 1
X-Request-Filter: {"updated_at":{"value":"2025-01-01","comparison":">="}}
X-Request-Sort:   {"id":"ASC"}
```

Response:
```
X-Result-Count, X-Result-Current-Page, X-Result-Page-Size,
X-Result-Total-Count, X-Result-Total-Pages
```

Komparatory: `=`, `!=`, `<=`, `>=`, `in`, `like`.

### 1.4 Mapa scope → endpoint (dla naszych scope'ów)

| Scope | Główne endpointy | Cel migracji |
|---|---|---|
| `user` | `/users/`, `/users/groups`, `/users/permission_groups` | Mapowanie userów (rekruterzy/managerowie) |
| `dictionary` | `/dictionaries/`, `/dictionaries/{id}` | Słowniki (źródła, statusy, custom field options) |
| `source` | `/sources/`, `/sources/{id}` | Źródła kandydatów |
| `workflow` | `/workflows/`, `/workflows/details`, `/workflows/stats` | Pipeline'y (definicje stage'ów per recruitment) |
| `client` | `/clients/`, `/clients/{id}` | Klienci |
| `crm_person` | `/crm_persons/` | Osoby kontaktowe u klienta (Contact) |
| ~~`crm_activity`~~ | ~~`/crm_activities/`~~ | **Wykluczone z migracji** (decyzja Artura) |
| `recruitment` | `/recruitments/`, `/recruitments/{id}/states`, `/.../employees`, `/.../rejections` | Joby + workflow + pipeline'y kandydatów |
| `advert` | `/job_posts/`, `/job_posts/{id}` | Ogłoszenia (publikacje) |
| `advert_publish` | publikacja ogłoszeń | (read-only przy migracji) |
| `talent` | `/talents/`, `/talents/employees` | Talent pools |
| `employee` | `/employees/` (+ `/files/`, `/notes/`, `/activities/`, `/tags/`, `/provisions/`) | **GŁÓWNY CHUNK — kandydaci** |
| `file` | `/employees/{id}/files`, `/files/` | CV i inne dokumenty (binary) |
| `form` | `/forms/{id}` | Formularze aplikacyjne (read-only) |
| `message` | (notes/messages w obrębie employee) | Wiadomości do kandydata |
| `provision` | `/provisions/`, `/provisions/types` | Prowizje (jeśli używane) |
| `webhook` | `/webhooks/`, `/webhooks/types` | Rejestracja webhooków (Faza 6) |

Pełna lista endpointów — patrz [api.traffit.com](https://api.traffit.com/).

### 1.5 Kluczowe znalezisko: GUID-based lookup
- `X-Get-Find-By-Guid: true` — pozwala znaleźć encję po GUID zamiast po ID.
  Bardzo przydatne, bo **nasze `external_id` może trzymać GUID** — stabilny
  identyfikator między środowiskami (sandbox/prod).
- Większość encji eksponuje zarówno `id` (int) jak i `guid` (uuid).
  **Decyzja:** trzymamy **GUID** w `external_id` jeśli dostępny, inaczej `str(id)`.

### 1.6 Czego dokumentacja **nie** mówi
- Brak rate limitu w docs → defensywnie throttle 5 req/s, exp backoff na 429/5xx.
- Brak gwarancji konsystencji listy podczas paginacji → sortuj po `id ASC` i
  filtruj `updated_at < <import_start_ts>` żeby uniknąć driftu.
- Format błędów niejednolity (3 różne kształty) → handler musi obsłużyć każdy.

## 2. Mapowanie encji Traffit → Nexus

| Traffit | Nexus | Strategia |
|---|---|---|
| `employee` | `candidates` | Główny model. `external_source='traffit'`, `external_id=<guid>`. Już zaprojektowane (kolumny + partial unique index z migracji 0009). |
| `employee.files` | `candidates.cv_file_content` (CV) + nowa tabela `candidate_documents` (reszta) | CV → `LargeBinary` w istniejącej kolumnie. Inne pliki — opcja na Fazę 2 / Phase 2. |
| `employee.notes` | `notes` (Note) | Mapowanie 1:1 z `external_id` na Note. |
| `employee.activities` | `activities` / `notes` (zależnie od typu) | Activity log → Note z prefixem typu. |
| `employee.tags` | `candidates.tags` (JSONB list) | Lista stringów. |
| `employee.sources` | `candidates.source` (free text) + ewentualnie `source_enum` | Mapowanie nazw na nasze enum (linkedin/pracuj/jjit/referral/database/manual). |
| `employee.provisions` | (na razie skip) | Nexus nie ma jeszcze prowizji per kandydat. Trzymać jako JSONB w `cv_extracted_data.provisions` jako safety. |
| `recruitment` | `jobs` | `external_id=<guid>`, `external_source='traffit'`. **Wymaga migracji** dodającej kolumny + partial unique index. |
| `recruitment.workflow` | `pipeline_templates` + `pipeline_stage_defs` | 1 workflow → 1 template. State'y → `pipeline_stage_defs` z mapowaniem na nasze `PipelineStage` enum. |
| `recruitment.states[]` (per recruitment) | `pipeline_template_id` na `Job` | Jeśli unikalny workflow → nowy template; jeśli ten sam → reuse. |
| `recruitment.employees[]` (kandydat w jobie) | `candidate_stages` | Snapshot aktualnego stage'u + historia z `state_changes` jeśli dostępna. |
| `recruitment.rejections` | `candidate_stages.stage='rejected'` + `rejection_reason_id` | Mapowanie reasonów na nasze `rejection_reasons`. |
| `client` | `clients` | `external_id`, `external_source`. **Migracja** kolumn + partial unique index. |
| `crm_person` | `contacts` | Linkujemy do `client_id` po external_id. **Migracja** kolumn. Sieroty bez klienta → klient `__traffit_orphans` (auto-utworzony). |
| ~~`crm_activity`~~ | — | **Wykluczone z migracji** (decyzja Artura). 108 wpisów w Traffit zostaje w starym systemie do referencji. |
| `user` | `users` | **Tylko mapowanie po emailu** — userów już mamy w Nexusie. Generujemy plik `traffit_user_id_to_nexus_user_id.json` dla follow-up FK fixów. |
| `job_post` (advert) | `job_postings` | Jeśli aktywne — zapisujemy URL i status; nie publikujemy ponownie. |
| `talent` (talent pool) | `talent_pools` | Już istnieje model. Mapowanie nazwy + przynależności kandydatów. |
| `dictionary` | (inline) | Słowniki używamy tylko do tłumaczenia ID na nazwy podczas migracji — nic nie zapisujemy. |
| `form` | (skip) | Formularze aplikacyjne nie są re-publikowane. |
| `webhook` | (Faza 6) | Rejestrujemy webhooki w Nexusie po sukcesie one-time migracji. |

### 2.1 Migracje schema potrzebne **przed** migracją danych

Nowa migracja `00XX_traffit_external_ids.py`:

```sql
-- jobs
ALTER TABLE jobs ADD COLUMN external_id varchar(100);
ALTER TABLE jobs ADD COLUMN external_source varchar(50);
CREATE UNIQUE INDEX ux_jobs_external_source_id
  ON jobs (external_source, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX ix_jobs_external_source ON jobs (external_source);

-- clients
ALTER TABLE clients ADD COLUMN external_id varchar(100);
ALTER TABLE clients ADD COLUMN external_source varchar(50);
CREATE UNIQUE INDEX ux_clients_external_source_id
  ON clients (external_source, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX ix_clients_external_source ON clients (external_source);

-- contacts
ALTER TABLE contacts ADD COLUMN external_id varchar(100);
ALTER TABLE contacts ADD COLUMN external_source varchar(50);
CREATE UNIQUE INDEX ux_contacts_external_source_id
  ON contacts (external_source, external_id) WHERE external_id IS NOT NULL;

-- notes
ALTER TABLE notes ADD COLUMN external_id varchar(100);
ALTER TABLE notes ADD COLUMN external_source varchar(50);
CREATE UNIQUE INDEX ux_notes_external_source_id
  ON notes (external_source, external_id) WHERE external_id IS NOT NULL;

-- talent_pools
ALTER TABLE talent_pools ADD COLUMN external_id varchar(100);
ALTER TABLE talent_pools ADD COLUMN external_source varchar(50);
CREATE UNIQUE INDEX ux_talent_pools_external_source_id
  ON talent_pools (external_source, external_id) WHERE external_id IS NOT NULL;
```

Wszystkie idempotentne; `IF NOT EXISTS` na indexy.

## 3. Architektura kodu

```
backend/app/services/traffit/
├── __init__.py
├── client.py            # TraffitClient — auth, paginated_get, retry/backoff, rate limiting
├── mappers.py           # Pure functions: traffit_employee_to_candidate(payload) -> dict
├── importer.py          # TraffitImporter — orchestrator faz, progress streaming
├── files.py             # FileDownloader — pobiera CV/dokumenty (binary)
└── webhook_handler.py   # (Faza 6) — POST /api/traffit/webhook → upsert delta

backend/app/cli/
└── import_traffit.py    # CLI entry: python -m app.cli.import_traffit --phase candidates

backend/app/api/admin/
└── traffit.py           # POST /api/admin/traffit/import — opakowanie CLI, RBAC: admin

backend/tests/
├── test_traffit_client.py
├── test_traffit_mappers.py    # bardzo dużo testów — pure functions
└── test_traffit_importer.py   # integracyjne, mocked HTTP
```

### 3.1 TraffitClient — szkic

```python
class TraffitClient:
    def __init__(self, tenant: str, client_id: str, client_secret: str,
                 throttle_rps: float = 5.0):
        self.base = f"https://www.{tenant}.traffit.com/api/integration/v2"
        self.token_url = f"https://www.{tenant}.traffit.com/oauth2/token"
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: Optional[str] = None
        self._token_exp: Optional[datetime] = None
        self._throttle = AsyncLimiter(throttle_rps)

    async def _ensure_token(self, scope: str) -> str: ...
    async def get(self, path: str, *, scope: str, page: int = 1,
                  page_size: int = 200, filter: dict | None = None,
                  sort: dict | None = None) -> tuple[list[dict], dict]:
        # zwraca (items, paging_meta z X-Result-* nagłówków)

    async def get_paginated(self, path: str, *, scope: str,
                            page_size: int = 200,
                            filter: dict | None = None) -> AsyncIterator[dict]:
        # generator po wszystkich stronach
```

Konfiguracja przez env (Coolify vault):
- `TRAFFIT_TENANT=b2bnetwork`
- `TRAFFIT_CLIENT_ID=b2bnetwork_NEXUS`
- `TRAFFIT_CLIENT_SECRET` (wartość — patrz Coolify env vault; **nigdy** w repo)
- `TRAFFIT_THROTTLE_RPS=5`

### 3.2 Idempotentny UPSERT (wzór z `talent_radar_importer.py`)

```sql
INSERT INTO candidates (..., external_source, external_id, ...)
VALUES (..., 'traffit', :guid, ...)
ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
DO UPDATE SET
    email = COALESCE(EXCLUDED.email, candidates.email),
    name = EXCLUDED.name,
    ...
    updated_at = NOW()
RETURNING (xmax = 0) AS was_insert;
```

Każda faza kończy się commit i loguje run-summary do nowej tabeli
`traffit_import_runs` (id, phase, started_at, finished_at, processed,
inserted, updated, errors, error_samples JSONB) — żeby kolejne uruchomienie
mogło ruszyć od ostatnio przetworzonego `updated_at`.

### 3.3 Co po stronie hot path

Migracja **nie idzie** przez request webowy w 1 wywołaniu — to byłby godzinowy
HTTP request. Dwa tryby:

1. **CLI w kontenerze** (preferred dla one-time): `docker exec` w Coolify
   Terminal → `python -m app.cli.import_traffit --phase all --batch-size 200`.
   Wyjście do logów Coolify.
2. **Background job z progress endpointem** (preferred dla incremental):
   `POST /api/admin/traffit/import` zwraca `run_id`, dalej
   `GET /api/admin/traffit/runs/{id}` pokazuje progress (z tabeli
   `traffit_import_runs`). To samo na webhook (Faza 6).

## 4. Fazy migracji

> Po każdej fazie: dry-run → review → real run → walidacja counts → commit.
> Idempotentne — można re-runować bez duplikatów.

### Faza 0 — POC i discovery (½ dnia)
- [ ] Test token endpointa: `curl POST .../oauth2/token` z secretem z prompta —
      rozstrzygnięcie `application/json` vs multipart.
- [ ] Test pierwszego GET: `/users/?page_size=1` — sprawdź kształt response,
      czy paging headers działają.
- [ ] Counters: `X-Request-Page-Size: 1` na `/users/`, `/employees/`,
      `/recruitments/`, `/clients/`, `/crm_persons/`, `/talents/` —
      przeczytaj `X-Result-Total-Count` i zapisz w `docs/traffit-discovery.md`.
- [ ] Pobierz 1 sample każdej encji + zapisz JSON-y w `tests/fixtures/traffit/` —
      podstawa dla testów mapperów.
- **Wyjście fazy:** wiemy ile rekordów, znamy kształt, mamy fixtures.

### Faza 1 — Migracja schema + szkielet kodu (1 dzień)
- [ ] Migracja Alembic: external_id na `jobs`, `clients`, `contacts`, `notes`,
      `talent_pools` (patrz §2.1).
- [ ] Tabela `traffit_import_runs` (audit/run history).
- [ ] `backend/app/services/traffit/client.py` z testami unit (mocked httpx).
- [ ] `backend/app/services/traffit/mappers.py` — pure functions z testami
      na fixtures z Fazy 0.
- [ ] CLI `python -m app.cli.import_traffit --phase <name> [--dry-run]`
      [--batch-size N].
- **Wyjście:** kod działa offline na fixtures; dry-run nie zmienia nic w DB.

### Faza 2 — Master data (½ dnia)
Kolejność: **users mapping → clients → contacts (CRM persons) → workflows/templates**.

- [ ] **Users mapping** (read-only): `/users/` → JSON
      `migrations/traffit/user_id_map.json` z `{traffit_user_id: nexus_user_id}`
      po lookupie po emailu. Brakujące → log warning, do ręcznego mapowania.
- [ ] **Clients import:** `/clients/` → upsert do `clients` z
      `external_source='traffit'`, `external_id=<guid_or_id>`.
- [ ] **Contacts import:** `/crm_persons/` → upsert do `contacts` z FK do
      client_id (lookup przez external_id klienta).
- [ ] **Workflows import:** `/workflows/details` → utwórz lub remap
      `pipeline_templates` + `pipeline_stage_defs`. Mapowanie state'ów Traffita
      na nasze `PipelineStage` enum (uwaga: Traffit ma per-tenant custom state'y;
      potrzebujemy konfiguracji `traffit_state_to_pipeline_stage.yaml`).
- **Walidacja:** counts match (Traffit total == Nexus z external_source='traffit').

### Faza 3 — Kandydaci + pliki (1-2 dni, zależnie od wolumenu)
- [ ] `/employees/` paginated → upsert do `candidates`.
      Mapper: `name`, `lastname`, `email`, `phone`, `linkedin` (custom field?),
      `location`, `tags`, dane strukturalne z custom_fields → `cv_extracted_data`
      JSONB (catch-all). `created_by` — z `user_id_map.json`.
- [ ] Per-candidate **fetch CV**: `/employees/{id}/files` → znajdź najnowszy CV →
      `/employees/{id}/files/{file_id}/content` (binary) → `cv_file_content` +
      `cv_filename`. Inne pliki: zapisz link i metadata w `cv_extracted_data.files`
      jako safety, do późniejszego importu w Phase 2.
- [ ] **Notes per candidate:** `/employees/{id}/notes` → `notes` (z mapowaniem
      `created_by` przez user_id_map).
- [ ] **Activities:** `/employees/{id}/activities` — generic log; mapowanie
      do `notes` lub `activities` zależnie od typu.
- [ ] **Tags:** `/employees/{id}/tags` → `candidates.tags` JSONB list.
- [ ] **Sources:** `/employees/{id}/sources` → `candidates.source` (free text) +
      best-effort enum mapping.
- **Walidacja:** spot check 10 losowych ID — wizualnie porównaj w UI Traffita
      i w UI Nexusa. CV otwiera się.

### Faza 4 — Recruitments + pipeline state (1 dzień)
- [ ] `/recruitments/` → upsert do `jobs` (z `external_id`,
      `pipeline_template_id` z Fazy 2, `client_id` z Fazy 2).
- [ ] Per-job: `/recruitments/{id}/employees` + `/recruitments/{id}/states/{state_id}` →
      `candidate_stages` rekordy z poprawnym `stage_def_id` i obliczonym
      `PipelineStage` enum z mapy.
- [ ] `/recruitments/{id}/rejections` → osobne rekordy
      `candidate_stages` z `stage='rejected'`, `rejection_reason_id` z lookup.
- **Walidacja:** dla losowych 5 jobów — counters po stage'ach match (Traffit vs
      Nexus). Total rejected match.

### Faza 5 — Talents (talent pools), advert metadata (½ dnia)
- [ ] `/talents/` → `talent_pools` + przynależności (talent_pool_members).
- [ ] `/job_posts/` (advert) → metadata-only do `job_postings`
      (URL, status, daty); nie re-publikujemy.
- ~~`/crm_activities/`~~ — **wykluczone z migracji** (decyzja Artura).

### Faza 6 — Incremental sync via webhooks (1 dzień, opcjonalnie)
- [ ] `GET /webhook-types` — zobacz co Traffit wysyła (candidate.created,
      candidate.updated, recruitment.state_changed, ...).
- [ ] Endpoint `POST /api/traffit/webhook` z HMAC verification (sprawdź czy
      Traffit podpisuje payloady).
- [ ] Per-event-type → reuse mappers z Fazy 3-4 → upsert.
- [ ] `POST /webhooks/` rejestracja w Traffit kierowana na `<nexus>/api/traffit/webhook`.
- **Use case:** użytkownicy dalej pracują w Traffit przez okres przejścia
      (np. miesiąc), Nexus zostaje zsynchronizowany delta-by-delta.

### Faza 7 — Cutover (½ dnia)
- [ ] Zamrożenie zapisów w Traffit (manualnie z poziomu admin Traffita).
- [ ] Final delta-run wszystkich faz 2-5 z `updated_at >= <freeze_ts>`.
- [ ] Audyt counters, ostatni reconciliation report w `docs/traffit-cutover-report.md`.
- [ ] **Jeśli Faza 6 wdrożona:** `DELETE /webhooks/{id}` (nie potrzebujemy więcej).
- [ ] User communication — Slack/email do recruiters że od dziś Nexus = source of truth.

## 5. Walidacja i recoverability

### 5.1 Counters reconciliation (po każdej fazie)
```sql
-- Nexus side (per source)
SELECT external_source, count(*) FROM candidates
  WHERE external_source = 'traffit' GROUP BY 1;

-- Traffit side (przez API)
GET /employees/?page_size=1 → X-Result-Total-Count

-- match? jeśli nie — dump diff: ID-y które są w Traffit a nie ma w Nexusie
```

Skrypt `python -m app.cli.import_traffit --phase reconcile` robi to dla każdej
encji i pisze raport `docs/traffit-reconcile-<timestamp>.md`.

### 5.2 Spot checks
- 10 losowych kandydatów → otwórz w Nexusie i w Traffit, vis-a-vis.
- 5 losowych jobów → counters po stage'ach.
- 1 kandydat z 5+ rekrutacjami → cała historia obecna.

### 5.3 Re-runability
Każda faza idempotentna. **Drugi run = 0 inserted, N updated** (te które
zmieniły się w międzyczasie). Test: zaraz po pełnej migracji uruchom drugi
raz → expected `inserted=0`.

### 5.4 Backup przed startem
```bash
# w Coolify Terminal (Postgres container)
pg_dump -Fc -d nexus > /backups/pre-traffit-migration-$(date +%Y%m%d).dump
```
Jeśli coś pójdzie nie tak — `pg_restore` rollback.

## 6. Bezpieczeństwo

- `TRAFFIT_CLIENT_SECRET` **tylko w Coolify env vault** — nigdy w repo, nigdy
  w Dockerfile, nigdy w logach (`logging.debug` filtruje pole, jeśli kiedykolwiek
  trafi do payloadu).
- Token w pamięci procesu, nie w DB.
- Endpoint `/api/admin/traffit/import` → RBAC: tylko `admin` (Artur). Żadnego
  `recruiter` / `delivery_lead`.
- Audyt: wszystko, co zostało zapisane, ma `external_source='traffit'` —
  zawsze można zorientować się skąd pochodzi i (w razie potrzeby) odróżnić
  od ręcznych wpisów.

## 7. Co **nie** wchodzi w zakres jednorazowej migracji

- **Aktywna publikacja ofert** (advert_publish) — nie publikujemy ponownie.
- **Forms** — formularze aplikacyjne; Nexus ma własne (career page V2).
- **Provisions** — Nexus nie ma jeszcze prowizji per kandydat; trzymamy
  jako safety w `cv_extracted_data.provisions`.
- **Custom fields per tenant** — leci do `cv_extracted_data` jako catch-all,
  nie próbujemy bezbłędnie mapować każdego pola.
- **GDPR consent records** — w memory mamy notatkę, że Nexus nie robi GDPR;
  traktujemy jako out-of-scope. Jeśli się zmieni — osobna faza po cutoverze.

## 8. Pre-flight checklist (przed Fazą 0)

- [ ] Potwierdzić tenant URL: `b2bnetwork` czy inny? (test `curl https://www.b2bnetwork.traffit.com/api/integration/v2/users/`).
- [ ] Skopiować `TRAFFIT_CLIENT_ID` + `TRAFFIT_CLIENT_SECRET` do Coolify env vault
      (do dev environment najpierw, **nie prod**).
- [ ] Sprawdzić czy account ma scope **wszystkie podane w prompcie** —
      pierwsze 401 z brakiem scope = gap do uzupełnienia z Account Manager Traffita.
- [ ] Backup nexus DB (pkt 5.4).
- [ ] Branch: `feat/traffit-migration` od `main`. Po każdej fazie — PR/merge
      do `main` po zielonych testach.

## 9. Estymacja

| Faza | Effort | Ryzyko |
|---|---|---|
| 0 — POC | ½ dnia | Niskie (read-only) |
| 1 — Schema + szkielet | 1 dzień | Niskie |
| 2 — Master data | ½ dnia | Średnie (workflow→template mapping) |
| 3 — Kandydaci + pliki | 1-2 dni | **Wysokie** (skala bytes, custom fields, edge cases w CV) |
| 4 — Recruitments + state | 1 dzień | Średnie (state machine mismatch) |
| 5 — Talents/CRM/advert | ½ dnia | Niskie |
| 6 — Webhooks (opcjonalnie) | 1 dzień | Średnie (HMAC, idempotency) |
| 7 — Cutover | ½ dnia | Niskie |
| **TOTAL one-time** | **4-5 dni** | |
| **TOTAL z webhookami** | **5-6 dni** | |

## 10. Pierwsze kroki (right now)

1. POC token endpointa. Mały skrypt sanity-check, w terminalu, **bez commita
   z secretem**:
   ```bash
   export TRAFFIT_TENANT=b2bnetwork  # do potwierdzenia
   export TRAFFIT_CLIENT_ID=b2bnetwork_NEXUS
   read -rs TRAFFIT_CLIENT_SECRET; export TRAFFIT_CLIENT_SECRET

   # Spróbuj JSON
   curl -sS -X POST "https://www.${TRAFFIT_TENANT}.traffit.com/oauth2/token" \
     -H "Content-Type: application/json" \
     -d "{\"client_id\":\"${TRAFFIT_CLIENT_ID}\",\"client_secret\":\"${TRAFFIT_CLIENT_SECRET}\",\"grant_type\":\"client_credentials\",\"scope\":\"user\"}"

   # Jeśli 400/415 — spróbuj multipart
   curl -sS -X POST "https://www.${TRAFFIT_TENANT}.traffit.com/oauth2/token" \
     -F client_id="${TRAFFIT_CLIENT_ID}" \
     -F client_secret="${TRAFFIT_CLIENT_SECRET}" \
     -F grant_type=client_credentials \
     -F scope=user

   # Jeśli token jest:
   TOKEN=...
   curl -sS "https://www.${TRAFFIT_TENANT}.traffit.com/api/integration/v2/users/" \
     -H "Authorization: Bearer ${TOKEN}" \
     -H "X-Request-Page-Size: 1" -i | head -50
   ```
2. Counters z §Faza 0 — tabelka w `docs/traffit-discovery.md`.
3. Decyzja: scope szerszy niż obecny client name? Czy są feature pakiety które
   trzeba dokupić?

---

**Następny krok dla mnie (po Twojej akceptacji):** Faza 0 (POC + counters)
i pierwszy commit z `docs/traffit-discovery.md` + szkielet
`backend/app/services/traffit/client.py` (sam shape, bez logiki, żeby
nie commitować jeszcze nic co się łączy z prod).
