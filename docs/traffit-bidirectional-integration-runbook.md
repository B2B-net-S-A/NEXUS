# NEXUS ↔ Traffit — integracja dwukierunkowa i runbook wdrożenia

Data implementacji: 2026-07-14

## Cel i bezpieczny stan początkowy

Integracja obsługuje dwukierunkowo kandydatów, przypisania do rekrutacji,
etapy/odrzucenia, notatki i pliki. Traffit pozostaje właścicielem rekrutacji,
workflowów i definicji etapów. Powiązane rekrutacje są procesowo tylko do
odczytu w NEXUS.

Kod jest wdrażany w stanie fail-closed. Sam deploy nie uruchamia nowego
pollingu, inbound apply ani outboundu. Wszystkie nowe przełączniki środowiskowe
mają domyślnie wartość `false`, a runtime control w bazie również startuje jako
wstrzymany i `dry_run=true`.

## Przełączniki

| Zmienna | Domyślnie | Znaczenie |
|---|---:|---|
| `TRAFFIT_INTEGRATION_ENABLED` | `false` | Główny hard kill-switch i wybór nowego workera zamiast legacy daily loop |
| `TRAFFIT_WEBHOOK_ACCEPT_ENABLED` | `false` | Pozwala publicznemu receiverowi zapisywać eventy do inboxa |
| `TRAFFIT_INBOUND_APPLY_ENABLED` | `false` | Pozwala stosować zmiany Traffit w NEXUS |
| `TRAFFIT_POLL_ENABLED` | `false` | Uruchamia polling/reconcile |
| `TRAFFIT_OUTBOUND_ENABLED` | `false` | Pozwala wysyłać outbox do Traffit |
| `TRAFFIT_DRY_RUN` | `true` | Zapisuje i porównuje eventy bez outbound send i inbound apply |
| `TRAFFIT_INTEGRATION_WEBHOOK_SECRET_HASH` | puste | SHA-256 wysokoentropijnego sekretu w URL webhooka; plaintext nie jest przechowywany |
| `TRAFFIT_INTEGRATION_WEBHOOK_HMAC_SECRET` | puste | Opcjonalny HMAC, tylko jeśli tenant potwierdzi obsługę podpisu |
| `TRAFFIT_INTEGRATION_FILE_SLO_RATE_BUDGET_CONFIRMED` | `false` | Jawne potwierdzenie budżetu API dla pełnego skanu aktywnych plików ≤10 min |
| `TRAFFIT_INTEGRATION_SCOPES` | core integration scopes | Scope osobnego klucza integracyjnego; nie używać klucza administracyjnego |

Runtime pause/resume nie może obejść zmiennej środowiskowej. Aby uruchomić
kierunek, jego hard gate oraz odpowiadający mu przełącznik runtime muszą być
jednocześnie włączone.

## Trwały model

- `traffit_entity_links` — mapowanie ID, wspólny snapshot 3-way merge, hashe,
  last-seen, source timestamps oraz bezpieczny stan usunięcia.
- `traffit_field_contracts` — tenantowy kontrakt pól osobno dla create i PATCH,
  adapter, choices, capability oraz quarantine.
- `traffit_outbox_events` — transactional outbox z idempotency key i kolejnością
  per kandydat zabezpieczoną advisory lockiem.
- `traffit_webhook_events` — trwały, deduplikowany inbox, retry, stale-lock
  recovery i dead-letter.
- `traffit_sync_conflicts` — baza/NEXUS/Traffit, decyzja admina i audit.
- `traffit_sync_runs` + `traffit_sync_run_phases` — kompletność faz, cursory,
  liczniki i błędy.
- `traffit_sync_state` — źródłowy cursor i tie-breaker per stream oraz osobne
  dane shadow.
- `integration_leases` — jeden leader, heartbeat 30 s, TTL 90 s.
- `traffit_integration_control` — miękkie runtime gates poniżej env.

Migracja backfilluje linki z istniejących `external_source/external_id`,
`source_ref` notatek i ID dokumentów. Historyczne `traffit_*` oraz
`traffit_<SID>` z `cv_extracted_data` są kopiowane kompatybilnie do
`Candidate.custom_fields`. `candidate_about` ma osobne `profile_about` i nie
jest już współdzielone z lokalnym `ai_summary`.

## Zasady domenowe

- Kandydat: create/PATCH tylko przez pola dopuszczone aktualnym metadata
  kontraktem. Nieobsługiwany typ jest quarantined per pole.
- Job/workflow: inbound-only. Próba zmiany pól procesowych lub lifecycle
  rekrutacji Traffit zwraca `409 managed_by_traffit`.
- Assignment: dodanie automatyczne; usunięcie tworzy manual action.
- Stage: outbound zawsze robi pre-read. Rozbieżność względem wspólnej bazy
  tworzy konflikt. Pending lokalnej akceptacji nie jest wysyłany; ruch inbound
  jest przyjmowany jako autorytatywny i audytowany.
- Rejection: wysyłka wymaga jawnego `RejectionReason.external_id`.
- Notes: append-only, widoczny autor i `[NEXUS:<event_uuid>]`; edycja tworzy
  korektę. Długie rozmowy/e-maile/spotkania są skracane do podsumowania.
- Files: nowa wersja to nowy dokument, deduplikacja po SHA-256 i weryfikacja
  zdalnych bytes. Brak pliku nie powoduje automatycznego delete.
- Delete: rekord połączony z Traffit nie jest kasowany. API zwraca `202` z ID
  zgłoszenia do admina.

## API

- `POST /api/integrations/traffit/webhooks/{subscription_id}/{secret}` — zapis
  sygnału do inboxa i natychmiastowe `202`.
- `GET /api/admin/traffit/integration/status` — leader, lag, cursory, kolejki,
  konflikty, field contracts i file SLO.
- `POST /api/admin/traffit/integration/reconcile` — body
  `{"scope":"active"}` lub `{"scope":"full"}`, odpowiedź `202` + `run_id`.
- `GET /api/admin/traffit/integration/events` i
  `POST /events/{direction:id}/retry`.
- `GET /api/admin/traffit/integration/conflicts` i
  `POST /conflicts/{id}/resolve`.
- `POST /api/admin/traffit/integration/control` — runtime pause/resume.
- `POST /api/admin/traffit/integration/contracts/refresh` — ręczne odświeżenie
  metadata po discovery/HTTP 400.

Akcje mutujące control-plane są admin-only. Każdy użytkownik może otrzymać w
odpowiedzi encji `IntegrationSyncState`: `synced`, `pending`, `conflict`,
`error` albo `manual_action_required`.

## Polling, reconcile i SLO

- Live polling: co 5 minut, 48 h overlap; cursor przesuwa się tylko po pełnym
  sukcesie strony/fazy.
- Webhook jest sygnałem: worker zawsze pobiera bieżący rekord przed apply.
- Active reconcile: kandydaci i manifesty plików przypisane do opublikowanych
  rekrutacji Traffit.
- Full reconcile: tenantowy safety net co tydzień. Pierwszy pełny live scan
  buduje baseline i nie generuje tombstone'ów.
- Brak encji: minimum dwa kompletne skany i siedem dni grace; potem manual
  action, nigdy hard-delete.
- Pliki: shardy muszą objąć aktywną populację w maksymalnie 10 minut. Bez
  potwierdzonego rate budget `file_slo_ready=false`, co blokuje go-live plików.
- Retry: pojedynczy refresh po 401, `Retry-After` po 429, backoff+jitter dla
  sieci/5xx, 4xx walidacyjne do manual/conflict. Niejednoznaczny create bez
  potwierdzonego GUID lookup nigdy nie jest ślepo ponawiany.

## Etapy aktywacji

### 1. Discovery i naprawa legacy health

1. Utrzymać legacy `/api/health.checks.traffit=healthy` przez minimum 48 h.
2. Utworzyć sandboxowego kandydata i osobny klucz API z minimalnymi scope'ami.
3. Potwierdzić POST/PATCH metadata, GUID, clear semantics (`null`, `""`, `[]`),
   note marker, upload/download, webhook events, rejection reasons i limity.
4. Ustawić wyłącznie master + webhook accept w dry-run; nie włączać apply/send.

### 2. Baseline i shadow

1. Uruchomić migrację i sprawdzić count/hash parity aktywnego zakresu.
2. `TRAFFIT_INTEGRATION_ENABLED=true`, wszystkie kierunki hard gate `false`,
   `TRAFFIT_DRY_RUN=true`.
3. Włączyć kontrolowany polling i receiver; pozostawić inbound apply/outbound
   send wyłączone.
4. Minimum 72 h bez dead-letterów i bez niewyjaśnionych różnic.
5. Potwierdzić pełny file sweep ≤10 min i jawnie ustawić rate-budget gate.

### 3. Połowa zespołu i hypercare

1. Rozwiązać wszystkie konflikty aktywnego zakresu.
2. Wyłączyć `TRAFFIT_SYNC_ENABLED`; nowy master gwarantuje, że legacy i nowy
   worker nie działają równolegle.
3. Ustawić hard gates oraz runtime gates i dopiero wtedy `dry_run=false`.
4. Przez 7 dni mierzyć p99 lag, duplikaty, dead-lettery, parity i czas obsługi
   konfliktów. Wymagane ≥99% zmian widocznych do 15 min.
5. Kolejną grupę przenosić dopiero po 14 kolejnych dniach spełnienia kryteriów.

## Rollback

Najpierw zatrzymać `TRAFFIT_OUTBOUND_ENABLED` i/lub
`TRAFFIT_INBOUND_APPLY_ENABLED`. Receiver może nadal zapisywać inbox, dzięki
czemu po wznowieniu nic nie ginie. Jeśli potrzebny jest rollback aplikacji,
użyć poprzedniego deploymentu w Coolify. Nie wykonywać downgrade migracji na
produkcji bez osobnego planu zachowania ledgerów.

## Weryfikacja po deployu

1. `GET /api/health` — globalnie healthy; przy wyłączonym masterze Traffit może
   pozostać w legacy shape. Przy włączonym masterze obiekt raportuje leadera,
   inbound/outbound lag, oldest event, dead-lettery, ostatni full reconcile i
   `file_slo_ready`.
2. Zalogowany admin: `/settings/traffit` — status, kolejki, runy, konflikty,
   control i retry renderują się bez błędów konsoli.
3. Użytkownik nie-admin widzi statusy, ale nie ma akcji resolve/retry/control.
4. Rekrutacja Traffit pokazuje „Zarządzane w Traffit”, a PATCH procesowy zwraca
   `409 managed_by_traffit`.
5. Nie włączać live send/apply podczas samego smoke testu deployu.

