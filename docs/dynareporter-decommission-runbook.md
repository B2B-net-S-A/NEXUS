# DynaReporter Coolify standalone decommission (Faza B.4)

> Operacyjne kroki shutdown'u Coolify standalone DynaReporter
> (app UUID `wpal3b75siiiu8lzw8ccg7ad` na server 91.99.199.112).
>
> **Render zostaje per user request** — nie ruszać Render web service ani DB.
>
> **Pre-req:** Faza B.3 cutover done (DNS CNAME do nexus, 24-48h
> observation window passed bez problemów).

## Pre-flight checklist

- [ ] PR #206-#222 zmergowane na main
- [ ] Wszystkie 11 modułów B.2 dostępne pod nexus.dynaminds.pl/dynareporter/*
- [ ] DNS reports.dynaminds.pl → CNAME → nexus.dynaminds.pl (verify: `dig`)
- [ ] 24-48h obserwacji bez zgłoszeń od użytkowników
- [ ] Backup volume `dynareporter_pgdata` (dla peace of mind)

## Krok 1 — Backup volume (last-resort safety)

Na serwerze:

```bash
ssh root@91.99.199.112

# Backup volume directory
docker run --rm -v dynareporter_pgdata:/source -v /backup/dynareporter:/dest \
  alpine sh -c "tar czf /dest/dynareporter-pgdata-$(date +%Y%m%d).tar.gz -C /source ."

# Verify backup size
ls -lh /backup/dynareporter/
```

## Krok 2 — Stop containers (NIE delete)

Via Coolify API:

```bash
TOKEN="<bearer>"
APP_UUID="wpal3b75siiiu8lzw8ccg7ad"

curl -X GET -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" \
  "https://coolify-nexus.dynaminds.pl/api/v1/applications/$APP_UUID/stop"
```

Lub przez UI: `https://coolify-nexus.dynaminds.pl` → Resources → dynareporter → Stop.

**Containers zatrzymane**, ale:
- Application config zachowana
- Volume zachowany
- Obraz Docker zachowany
- Można uruchomić ponownie w 1-2 min jeśli trzeba

## Krok 3 — Free server resources sanity

```bash
ssh root@91.99.199.112 "
echo '=== Memory ===' && free -m | head -2
echo '=== Disk ===' && df -h | grep -v tmp
echo '=== Containers ===' && docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Image}}' | head -10
"
```

Po Stop'ie powinno być ~500MB-1GB extra free RAM (DynaReporter app + postgres).

## Krok 4 — Update memory entry

`~/.claude/projects/-Users-arturtwardowski-NEXUS--ATS-/memory/project_dynareporter_migration.md`:

```diff
- **Stan: Faza A live** (reports.dynaminds.pl pod Coolify standalone)
+ **Stan: Faza B done 2026-05-XX** (pełna migracja do Nexus monorepo;
+   /dynareporter/* dostępne pod nexus.dynaminds.pl; Coolify standalone
+   Stopped, volume zachowany; Render zostaje per user).
```

## Krok 5 — Sprzątanie session artifacts (opcjonalne)

Lokalne pliki z trakcji migracji:

```bash
# Usuń secrets (Coolify token, Render creds) — zostają w przypadku potrzeby
# ale nie są już aktywne (Coolify standalone Stopped, Render zostaje read-only)
ls /tmp/dynareporter-migration/
# render-db-url.env    — Render DB external URL (Render live, ale read-only)
# web-service.env      — Render web service env vars (Coolify env vault ma kopię)
# coolify-token.env    — Coolify Bearer token (można delete, są w gh secrets repo)
# render-dump.sql      — kompletny dump z Render z 2026-05-18
# render-dump-clean.sql — z --clean --if-exists

# Decyzja Artura: usunąć? zostawić w /tmp?
# Recomendacja: zachować render-dump.sql przez 3 miesiące (audit trail)
```

## Krok 6 — Render shutdown (PER USER DECISION)

**NIE wykonuj automatycznie.** Per user explicit request "Render zostaje".

Jeśli Artur w przyszłości zdecyduje (np. po 6 miesiącach):

1. https://dashboard.render.com → InfraReporter Web service → Suspend
2. https://dashboard.render.com → infrareporter-db → Delete (po przejrzeniu
   ostatniego pg_dump w `/tmp/dynareporter-migration/render-dump.sql`)

Render Free tier ma 90-day grace dla suspended, potem auto-delete.
Paid plan: auto-bill kontynuowany do explicit delete.

## Rollback (jeśli okaże się że coś brakuje)

W Coolify panel → Resources → dynareporter → Start.

Albo via API:

```bash
curl -X GET -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" \
  "https://coolify-nexus.dynaminds.pl/api/v1/applications/$APP_UUID/start"
```

DNS rollback: `reports.dynaminds.pl` → A 91.99.199.112 (CF dashboard
albo JS API). Coolify standalone serwuje znowu — 1-2 min do propagacji.

## Final state po B.4

- ✅ Nexus monorepo serwuje całą funkcjonalność DynaReportera pod
  `nexus.dynaminds.pl/dynareporter/*`
- ✅ Stary URL `reports.dynaminds.pl` → CNAME → nexus (działa nadal,
  redirect via dynareporter_redirect.py)
- ✅ 74 userów zmigrowanych, ~2k rows danych
- ✅ Coolify standalone Stopped (volume zachowany dla rollbacku)
- ✅ Render web + DB live (Artur decyduje kiedy wyłączyć)

**Faza B kompletna.**
