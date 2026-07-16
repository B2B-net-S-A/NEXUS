# Traffit ↔ NEXUS bidirectional — faza startowa (PR 0 / PR 2 / PR 3a) — raport ukończenia

> Data: 2026-07-16
> Plan wykonawczy: [traffit-nexus-bidirectional-integration-recommendation-and-claude-implementation-plan-2026-07-16.md](traffit-nexus-bidirectional-integration-recommendation-and-claude-implementation-plan-2026-07-16.md)
> Zakres tej fazy: weryfikacja planu + PR 0 (stabilizacja) + PR 2 (persistence) + PR 3a (silnik merge). **Zero aktywacji — wszystkie gate'y OFF.**

## 1. Weryfikacja planu vs stan faktyczny

| Twierdzenie planu | Stan faktyczny | Werdykt |
|---|---|---|
| `origin/main` = `99d9d70` | przesunął się (w trakcie sesji `b947142` → `bbee39e`); pracowano ze świeżego maina | OK (zgodnie z instrukcją odświeżenia) |
| Prod `healthy`, `traffit=degraded` | potwierdzone | OK |
| WIP `297c151` na `wip/uncommitted-main-snapshot-2026-07-15` | istnieje; użyty wyłącznie referencyjnie przez `git show` | OK |
| Graf Alembic „wielogłowicowy" | **25 headów** (statyczna analiza); prod schema realnie dostarczana przez entrypoint safety-net + `create_all` | plan niedoszacował skali — wnioski §9.8 tym bardziej obowiązują |
| Smoke-test bez UA `dynaminds-smoke-test` | naprawione równolegle w #764 (`SMOKE_UA`); nasz duplikat wycofany przy rebase | OK |
| P0/P1 blokery WIP (§4.1) | potwierdzone w kodzie WIP (m.in. `_public_value` zrównujący MISSING z null w `merge.py`) | OK — naprawione w PR 3a dla merge |

**Odkrycia spoza planu:**

1. **Delivery path był zepsuty** — wszystkie deploye na main failowały HTTP 429 „Deployment queue is full": deployment `#1818` wisiał `in_progress` >16 h (next build zamarł na „Collecting page data"), a za nim 25 zakolejkowanych. Prod tkwił 18 commitów za mainem. Naprawione operacyjnie (cancel przez Coolify API + świeży deploy); równolegle #763/#764 dodały odporny deploy workflow.
2. **Przyczyna `traffit=degraded`**: daily run kończy `last_status="errors"` przez **311 błędów fazy `pipelines`** (na 175 849; 0,18%), pozostałe fazy czyste. Treść błędów była **tracona** — `_summarize()` wycinał `error_samples` przed zapisem watermarku (→ PR 0).
3. **Żaden test traffit nie był uruchamiany w CI** — jawna lista pytest nie zawierała nawet legacy `test_traffit_client/mappers/sync` (→ dodane w PR 3a).

## 2. Dowiezione PR-y

### PR 0 — [#765](https://github.com/artur-t-96/Nexus/pull/765) (merged)
- `_summarize()` persystuje `error_samples` (≤10 × 200 znaków; identyfikatory + repr wyjątku, bez wartości pól kandydata) w `traffit_sync_state.stats` → diagnoza z `GET /api/admin/traffit/sync/status`.
- 3 testy regresyjne.
- Po deployu odpalony ręczny `POST /api/admin/traffit/sync?mode=delta` — sample 311 błędów będą czytelne po zakończeniu fazy pipelines (~2-3 h).

### PR 2 — [#767](https://github.com/artur-t-96/Nexus/pull/767) (merged)
- 9 tabel persistence: `traffit_entity_links` (baza 3-way merge + `base_schema_hash`), `traffit_field_contracts`, `traffit_outbox_events` (transactional outbox, `idempotency_key` UNIQUE, `sequence` per agregat), `traffit_webhook_events` (durable inbox, dedupe per subskrypcja), `traffit_sync_conflicts` (konflikty + manual actions, **`idempotency_key` = jeden DELETE → jedna sprawa**), `traffit_sync_runs`/`_phases`, `integration_leases` (fencing `generation`), `traffit_integration_control` (fail-closed poza `dry_run=true`).
- Rozszerzenia encji: `candidates.profile_about` + `custom_fields`; `notes` external identity + `supersedes_note_id`; `candidate_documents.content_sha256`/manifest; `rejection_reasons.external_*`; `traffit_sync_state` kursory shadow/live.
- Migracja `0173` z aktualnego grafu (świadomie NIE skopiowana z WIP-owej `0161`) + **mirror DDL 1:1 w `entrypoint.sh`** + test pilnujący synchronizacji migracja↔entrypoint.
- Env gates: `TRAFFIT_INTEGRATION_ENABLED` / `WEBHOOK_ACCEPT` / `INBOUND_APPLY` / `POLL` / `OUTBOUND` = **False**, `TRAFFIT_DRY_RUN` = **True**.
- Prod proof: deploy `bbee39e` → `/api/health` healthy z nowym SHA, `/api/health/deep` healthy (0 failing).

### PR 3a — [#768](https://github.com/artur-t-96/Nexus/pull/768)
- `backend/app/services/traffit/merge.py` — przepisany silnik 3-way merge z sentinelem **`MISSING ≠ null`** (naprawa P0 „wyzerowanie lokalnych pól"): patch zawiera wyłącznie ścieżki obecne w snapshocie źródłowym; konflikt nie nadpisuje żadnej strony; `get_path`/`set_path` (P1 custom fields); listy atomowe; kolizje kształtu atomowe; `contract_paths`.
- 21 testów (tabela reguł §13, regresja P0, MISSING vs null, partial custom-fields, seeded property tests).
- `ci.yml`: dodane **wszystkie** pliki testów traffit do jawnej listy pytest.

## 3. Świadome odstępstwo od kolejności planu

Plan każe wykonać PR 1 (tenant discovery) przed persistence. PR 1 wymaga **sandboxowego tenanta Traffit** (round-trip note/file, clear semantics), którego nie ma w env — wykonano PR 2/3a najpierw, bo są schema-only/pure-logic i nie zależą od wyników discovery (kontrakty pól są dynamiczne — JSONB `traffit_field_contracts` absorbuje dowolny wynik discovery). **Outbound pozostaje zablokowany do czasu discovery** zgodnie z §4.1 P0 („brak świeżego kontraktu metadata nie blokuje outboundu" — u nas blokuje, bo gate'y OFF).

## 4. Następne kroki

1. **Odczyt sampli 311 błędów** po zakończeniu ręcznego delta runu (`GET /api/admin/traffit/sync/status`, faza `pipelines` → `stats.error_samples`) → root-cause fix osobnym PR-em → `traffit` wraca do `healthy`; gate wejścia: healthy ≥ 48 h.
2. **PR 1 discovery** — wymaga decyzji Artura: sandbox tenant Traffit (lub zgoda na read-only discovery na prod tenancie: metadata, webhook types, workflows, GUID lookup — bez zapisów).
3. **PR 3b** — entity link backfill z istniejących external IDs + refactor legacy importera na wspólny applier + shadow cursory.
4. PR 4–8 sekwencyjnie (inbox/webhook, outbox/outbound, assignments/stages, notes/files, admin UI) — wg planu, gate'y OFF.
5. Sandbox E2E + 72 h shadow + go/no-go raport przed jakimkolwiek live send (jawne „go" Artura).

## 5. Znane ograniczenia

- `test_traffit_sync.py` i `test_traffit_integration_models.py` weryfikowane w CI (Python 3.12); lokalny mac ma 3.9 (składnia `X | Y` blokuje import łańcucha `app.models`).
- Faza `pipelines` w daily sync robi pełny skan 175k rekordów (filtr delta po `created_at` nie ogranicza `recruitment_history`) — ~1 h/run; kandydat na optymalizację przy PR 3b (cursor `(timestamp, id)`).
- Advisory check `review` (claude-code-action) failuje wewnętrznym błędem akcji („directory mismatch … indicates a bug") — nie dotyczy kodu, nie jest required.
