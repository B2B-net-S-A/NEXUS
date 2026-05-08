# Traffit Gap Roadmap

> Roadmap funkcji do dorobienia w NEXUS, wynikające z audytu Traffit (B2BNetwork instance) z 2026-05-08.
> Pełny audyt + gap matrix: `~/.claude/plans/https-b2bnetwork-traffit-com-dashboard-p-woolly-journal.md` (lokalny u Artura).
> Decyzje produktowe Artura (2026-05-08): bez RODO module, bez Hiring Managers self-service, bez native multipostingu (n8n+Traffit pokrywa), bez Smart Tracker.

## 7 zatwierdzonych pozycji (GO)

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[deferred]` zaplanowane na późniejszą fazę.

### Quick wins (M — sprint każda, niski risk)

- [ ] **#5 — AI features panel** w Settings
  - Master toggle `ai_features_enabled` + per-feature toggles (5 feature: scoring, gen ogłoszeń, CV parser, AI summary, AI raport analytics)
  - Tabela `ai_usage_log(feature, user_id, count, period_start)` + monthly limits per feature
  - UI: `Settings → AI` z licznikiem zużycia "X / Y" + "Odnowienie limitu: 01/MM/YYYY"
  - Transparentność: lista co konkretnie wysyłane do AI per feature (jak Traffit)
  - **Why:** cost control + compliance (klient może wyłączyć AI dla swoich danych)
  - **Effort:** M (sprint)
  - **Dotyka:** `backend/app/models/ai_usage.py` (nowy), `backend/app/api/settings.py`, `backend/app/services/scoring_service.py` (middleware decorator), `frontend/src/app/settings/ai/`

- [ ] **#6 — OAuth2 client manager** (NEXUS jako provider)
  - UI w `Settings → API integration`: lista clients + Client Secret + scoped permissions
  - Scopes inspirowane Traffit: `recruitment`, `candidate`, `talent`, `client`, `webhook`, `dictionary`, ...
  - Auth flow: OAuth2 client credentials grant (Authlib)
  - **Why:** Artur ma 9 systemów konsumujących Traffit API. NEXUS odwraca rolę — staje się hubem dla zewnętrznych systemów (n8n, ChatGPT, Jarvis, TalentRadar, ...)
  - **Effort:** M (sprint)
  - **Dotyka:** `backend/app/models/oauth_client.py` (nowy), `backend/app/api/oauth.py` (nowy), `backend/app/api/deps.py` (scope decorator), `frontend/src/app/settings/api/`

- [ ] **#3 — Bulk akcje na liście kandydatów**
  - Rozszerzyć floating bulk-action bar (`backend/app/api/talent_pools.py:212`) o 6 typów:
    - Wyślij email (z template picker)
    - Anonimizuj (RODO PII zerwanie zostawiając stats)
    - Tagi + Talenty (assign w bulk)
    - Przypisz do rekrutacji (multi-job picker)
    - Zadania (utwórz follow-up)
    - Eksport (CSV/XLSX)
  - **Skip:** Wyślij SMS (provider integration P3)
  - **Why:** rekruterzy klikają one-by-one. Traffit ma 8-typową bulk akcję, NEXUS tylko talent_pools assign.
  - **Effort:** M (sprint)
  - **Dotyka:** `backend/app/api/candidates_bulk.py` (nowy), `frontend/src/components/candidates/BulkActionBar.tsx` (extend)

- [ ] **#4 — Multi-source application tracking + UTM**
  - Tabela `candidate_sources(candidate_id, source, utm_source, utm_medium, utm_campaign, utm_term, utm_content, captured_at)` (multi-row per kandydat)
  - Endpoint `/reports/sources` z agregacją per source + UTM
  - UI multi-line: "Dodany manualnie • 08/05/2026 / E-mail • 09/05/2026 / Aktywny Search • 10/05/2026" (jak Traffit)
  - UTM capture na apply form (frontend)
  - **Why:** atrybucja ROI per kanał — który source daje najlepszych kandydatów. NEXUS dziś ma flat `Candidate.source` field.
  - **Effort:** M (sprint)
  - **Dotyka:** `backend/app/models/candidate.py` (relacja), `backend/app/models/candidate_source.py` (nowy), `frontend/src/app/apply/[token]/page.tsx` (UTM capture), `frontend/src/components/candidates/SourcesPanel.tsx`

### Big rocks (L — kwartał każda)

- [ ] **#1 — Pipeline templates per klient** ⭐
  - Refactor `PipelineStage` enum (13 hardcoded etapów) → tabele:
    - `pipeline_processes(id, name, client_id NULL = global)`
    - `pipeline_stage_defs(id, process_id, ordinal, key, label_pl, label_en, category {internal|external|terminal}, color)`
  - Migracja: enum → wstrzyknięty global "B2B" process + per-klient procesy
  - FK: `Job.pipeline_process_id` (default = "B2B")
  - `CandidateStage.stage_def_id` (nullable migration period; legacy `stage_enum` zachowane na 30 dni)
  - UI: `Settings → Procesy rekrutacyjne` (lista + drag-drop etapy edytor + per-process etapy)
  - Frontend: dynamic Kanban kolumny z procesu, nie z enum
  - **Risk:** hardcoded `PipelineStage.X` w wielu serwisach: `kpi_engine`, `match_history_ttl`, `compute_proposals`, `recommendation_filters`, `scoring_service`, `notification_triggers`, `stage_notification_*`. Każdy musi obsługiwać dynamic stages.
  - **Why:** klienci wymagają custom etapów (decyzja Artura 2026-05-08). Bez tego nie można dodać "NORDEA: Wysłać do Cpro" jak w Traffit.
  - **Effort:** L (kwartał, 1 dev)

- [ ] **#7 — Konfiguracja pól (drag-drop schema editor)**
  - `entity_field_defs(id, entity_type {candidate|job}, key, label, type {text|long_text|number|checkbox|radio|select|multi|date|datetime|file|files|location|link}, options[], required, ordinal, section)`
  - Migracja istniejącego `Job.custom_fields` JSONB → schema-aware
  - UI: `Settings → Konfiguracja pól` per entity (Kandydat / Rekrutacja) z 3-kolumnowym drag-drop layout (react-beautiful-dnd lub @hello-pangea/dnd)
  - Dynamic form renderer w profilu kandydata + szczegółach rekrutacji
  - **Why:** killer feature Traffit. Daje rekruterom autonomię dodawania pól bez release dev.
  - **Effort:** L (kwartał)
  - **Dotyka:** wszędzie gdzie jest custom_fields render w UI + validate w backendzie

- [ ] **#8 — Słowniki UI editor**
  - Generic `dictionaries(name, description)` + `dictionary_items(dictionary_id, key, label_pl, label_en, ordinal, archived)` tables
  - Refactor enums (`JobCloseReason`, `RecruitmentType`, `Skill` taxonomies, `Industry`, `WorkMode`, `ContractType`, ...) → DB rows
  - UI: `Settings → Słowniki` z listą dictionaries + add/edit/archive items
  - Migracja istniejących enum values → DB seed
  - **Why:** klienci/rekruterzy chcą edytować taxonomies bez release dev (zwłaszcza `JobCloseReason` przyczyny odrzucenia, `Industry` branże).
  - **Effort:** L (kwartał)
  - **Risk:** każde miejsce w kodzie używające enum literal (`if reason == JobCloseReason.X:`) musi obsługiwać DB-driven dictionary lookup.

## Świadomie pominięte (NO-GO 2026-05-08)

- ~~Time-to-Hire/Reject/Offer + lejek raporty~~ (NO-GO Artura — niska priorytet teraz)
- ~~Career page generator (white-label)~~ (NO-GO — `/apply` wystarcza, klienci nie wymagają branded portali)
- ~~Indeed + Jooble auto-publish~~ (NO-GO — niski reach vs effort)
- ~~RODO module (klauzule + Asystent + Monitoring raport)~~ (memory `feedback_nexus_scope` aktualna)
- ~~Hiring Managerowie self-service login~~ (komunikacja via rekruter)
- ~~Smart Tracker candidate self-service portal~~ (klienci nie pytają)
- ~~Multiposting native (Pracuj/JJIT/LinkedIn/OLX)~~ (n8n+Traffit pokrywa publikację)
- ~~SMS bulk + scheduling~~ (provider integration, niski ROI)
- ~~IMAP/SMTP inbox sync~~ (m365 wystarcza dla pracowników B2B Network)

## Proponowana kolejność implementacji

1. **#5 AI features panel** (M) — pierwsze, izolowane, low risk, daje szybką wygraną
2. **#6 OAuth2 client manager** (M) — drugie, izolowane, security-focused
3. **#4 Multi-source UTM** (M) — schema additive, nie ruszamy istniejącego flow
4. **#3 Bulk akcje** (M) — extend istniejącego bulk-action bar
5. **#1 Pipeline refactor** (L) — duża zmiana, robić po Quick Wins
6. **#7 Konfiguracja pól** (L) — po #1 (Pipeline refactor zwalnia patterny dla `entity_field_defs`)
7. **#8 Słowniki UI** (L) — ostatnia, dotyka wszędzie, robić gdy reszta stabilna

**ETA łącznie:** ~9-12 miesięcy (4 sprinty M + 3 kwartały L), 1 dev pełny etat.

## Dziennik decyzji

- **2026-05-08** — audyt Traffit ukończony, gap matrix przeanalizowany, decyzje Artura (4 pytania → 4 odpowiedzi). 7 z 14 P0/P1 funkcji = GO. Roadmap zatwierdzony.
