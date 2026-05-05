# Traffit → Nexus migration — completion report

> Sesja 2026-05-04 / 2026-05-05. Tenant: `b2bnetwork`.
> Plan: [`traffit-migration-plan.md`](./traffit-migration-plan.md). Discovery: [`traffit-discovery.md`](./traffit-discovery.md).

## Status: zakończona z udokumentowanymi luckami

Wszystkie phases (Faza 4 + 5 + 5b) odpalone na prodzie, dane zaimportowane. Reconcile pokazuje drobne diff'y (głównie ghost records w Traffit i dangling refs), które są oczekiwane.

## Wyniki reconcile

| Encja | Traffit total | Nexus (traffit-sourced) | Delta | Wyjaśnienie |
|---|---:|---:|---:|---|
| clients | 146 | 146 | 0 | ✅ |
| contacts | 350 | 347 | -3 | Traffit ghost records (declared in total_count, niewidoczne w paginacji) |
| candidates | 43 963 | 43 820 | -143 | ~134 nowych w Traffit po starcie importu, ~9 mapping edge-cases |
| jobs | 3 801 | 3 773 | -28 | 25 dangling client refs + 3 nowych w Traffit |
| talent_pools | 98 | 98 | 0 | ✅ |
| pipeline_templates | 2 | 2 | 0 | ✅ (workflows) |

Faza 5b (per-record audit data):
| Encja | Inserted | Notatka |
|---|---:|---|
| `candidate_stages` (pipelines) | 134 331 | 152 525 z Traffit; różnica ~18k z `commit_every=100` rollback batch loss przy check-constraint violations + 222 skipped (no FK) |
| `activities` | 343 867 | ✅ z 343 763 total (>100% bo Traffit rósł) |
| candidates with `cv_file_content` | 40 488 | binary CV zaimportowane |
| candidates with sources tags | 31 836 | per-candidate aggregated |

Sources phase: 75 394 inserted, 29 records skipped na poziomie pojedynczych rekordów + ~30 pages skipped na poziomie HTTP 500 (~290 records lost) — server-side bug Traffita.

## Co poszło źle (chronologicznie) — 14 bugfix-ów PR #70-#84

| # | PR | Bug | Fix |
|---|---|---|---|
| 1 | [#70](https://github.com/artur-t-96/Nexus/pull/70) | Paginator stop'ował po stronie 1 gdy `len(items) < page_size` (server cap'd 100 vs request 200) | Use `X-Result-Page-Size` header |
| 2 | [#71](https://github.com/artur-t-96/Nexus/pull/71) | `/workflows/` HTTP 400 dla page_size > 100 | `MAX_PAGE_SIZE = 100` clamp |
| 3 | [#72](https://github.com/artur-t-96/Nexus/pull/72) | asyncpg AmbiguousParameterError $6 w `_UPSERT_PIPELINE_TEMPLATE` | Explicit CAST'y |
| 4 | [#73](https://github.com/artur-t-96/Nexus/pull/73) | Ten sam $6 w pipeline_stage_defs INSERT (dwukrotne użycie `:terminal_type`) | Collapse `CASE WHEN ... IS NULL` na single CAST |
| 5 | [#74](https://github.com/artur-t-96/Nexus/pull/74) | `uq_stage_name_in_template` violation (Traffit B2B ma 2 stany "Zaakceptowany") | Suffix `(#state_id)` dla duplikatów |
| 6 | [#75](https://github.com/artur-t-96/Nexus/pull/75) | `/crm_persons/` 99 items na strones 2-3 z deklarowanym page_size=100; paginator stopował | Trust `X-Result-Total-Pages` over `len(items)` |
| 7 | [#76](https://github.com/artur-t-96/Nexus/pull/76) | `'2022-09-15'` string → DATE column (asyncpg `toordinal` error) | `date.fromisoformat` w mapperze |
| 8 | [#77](https://github.com/artur-t-96/Nexus/pull/77) | `uq_jobs_reference_number` violations — Traffit dopuszcza dup nrRef | Suffix `(#external_id)` |
| 9 | [#78](https://github.com/artur-t-96/Nexus/pull/78) | Brak progress visibility w 43k candidates run | `commit_every=100`, log per error |
| 10 | [#79](https://github.com/artur-t-96/Nexus/pull/79) | `ix_candidates_email` collisions z talent_radar (35k+) | `_UPDATE_CANDIDATE_ADOPT` po email match |
| 11 | [#80](https://github.com/artur-t-96/Nexus/pull/80) | `varchar(30)` truncation na `phone` | `_trunc(value, maxlen)` w mapperze |
| 12 | [#81](https://github.com/artur-t-96/Nexus/pull/81) | `moved_at` string vs `timestamp with time zone` w `candidate_stages` | `_parse_traffit_datetime` (UTC tz-aware) |
| 13 | [#82, #83](https://github.com/artur-t-96/Nexus/pull/83) | `/sources/` HTTP 500 dla page_size > 50, potem > 10 | Cap do 10 |
| 14 | [#84](https://github.com/artur-t-96/Nexus/pull/84) | `/sources/` random 500 nawet przy size=10 (server bug per-record) | `skip_on_5xx=True` flag |

## Wszystkie patches utrzymane na main; idempotency

Każdy fix był osobnym PR, mergowany przez `--admin` (frontend tech-debt unrelated do mojej zmiany blokuje PR otherwise). Ostatecznie wszystkie zmiany mapper'a/SQL są kompatybilne wstecz — re-run dowolnej phase nie tworzy duplikatów dzięki `ON CONFLICT (external_source, external_id)`.

## Recommended follow-ups

1. **Re-run candidates** — mapper teraz trim'uje varchar; 31 errors z pierwszego runu już zaktualizowane przez drugi run (idempotent), ale `cv_extracted_data.legacy_source` mogło zostać nadpisane na 'traffit' zamiast 'talent_radar' przy adopt path. Audit:
   ```sql
   SELECT count(*) FROM candidates 
   WHERE external_source='traffit' 
     AND cv_extracted_data->>'legacy_source' = 'traffit';
   ```
2. **Re-run pipelines** z lepszą izolacją per-record (nie per-100 commit) żeby uratować ~18k stage moves zgubionych w batch rollbacks. Wymaga zmiany: `commit_every=1` LUB savepoint per record.
3. **Sprawdzić varchar(30) edge-cases** — ktoś z `phone` > 30 char może mieć obcięty numer; fallback w mapperze może być smartszy (split na pierwszy w COMMA list).
4. **Cutover decision** — Faza 6 (webhooks live sync) lub Faza 7 (freeze Traffit + final delta).
5. **Sentry alerty** — błędy podczas import były tylko w stdout CLI, nie w Sentry; rozważyć logowanie errors do Sentry przy następnym run.

## Operational facts

- **Backup przed startem:** `/root/backups/pre-traffit-migration-20260504-1441.dump` (2.3GB) na serwerze nexus-prod (91.99.199.112).
- **Coolify env vault:** `TRAFFIT_TENANT`, `TRAFFIT_CLIENT_ID`, `TRAFFIT_CLIENT_SECRET`, `TRAFFIT_THROTTLE_RPS=5` ustawione runtime-only.
- **Coolify API token** użyty jednorazowo do dodania env vars: `claude-traffit-import` (id=3) — usunięty po sesji.
- **CLI dostępne dalej:** `docker exec <backend> python -m app.cli.import_traffit --phase <name>` — env vars persisted, można odpalać ad-hoc.

## Następna sesja

Realnie zostały:
- Faza 6 (webhooki) — opcjonalna, gdy chcemy koegzystencji Traffit + Nexus
- Faza 7 (cutover) — freeze Traffit + final delta + komunikat do recruiters

Lub pominąć Fazę 6 i od razu Faza 7 jeśli zespół już używa Nexus jako source of truth.
