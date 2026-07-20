# Disaster Recovery — Nexus ATS

> ## ⚠️ STATUS: THE RESTORE PATH HAS NEVER BEEN VERIFIED
>
> Established 2026-07-20. Everything below the status block describes the
> *intended* design. Treat it as a plan, not as a guarantee.
>
> - **The weekly drill has never restored anything.** `BACKUP_DRILL_SSH_KEY`
>   is not configured, so every meaningful step in
>   `.github/workflows/backup-drill.yml` — fetch, `pg_restore`, `alembic`,
>   smoke query — was skipped on every run. The job nevertheless reported
>   **success** for months. It now fails loudly instead.
> - **The backup script is not in this repository.** This document used to
>   credit `.scripts/backup.sh` "from commit `dfc55bd`". That commit adds
>   `uptime-probe.yml` and nothing else; no backup script has ever been
>   committed. Whatever runs nightly on the VPS is unversioned and unreviewed.
> - **There is no off-site copy.** Dumps live on the same VPS disk that hit
>   98.8% utilisation in July 2026 and on which `docker container prune`
>   destroyed the Postgres container. A disk-level loss takes the backups too.
> - **Consequence:** there is currently no evidence that a NEXUS backup exists,
>   is complete, or can be restored.
>
> Restoring the guarantee, in order: get an off-site copy first, make the
> backup script reviewable by committing it here, then make the drill exercise
> the real path so this block can be replaced with a verified date.

This document covers backup policy and restore procedures.

## Backup policy

Nightly backup job runs on the Hetzner VPS (`.scripts/backup.sh` from commit
`dfc55bd`). Two snapshots are captured:

| Source | Destination | Retention | Size (rough) |
|---|---|---|---|
| PostgreSQL (`nexus` + `postgres` DB, pg_dump -Fc) | `/var/backups/nexus/postgres/YYYY-MM-DD.dump` | 14 days | ~50 MB (growing) |
| Qdrant snapshot (all collections) | `/var/backups/nexus/qdrant/YYYY-MM-DD.tar.gz` | 14 days | ~250 MB (for 31k vectors × 1024-dim) |

Both are rotated by the same script. VPS has 2 copies on its local disk; for
off-site copies, set `HETZNER_STORAGE_BOX` in the backup script env.

## Restore procedure (full disaster)

Assumes Coolify + Postgres + Qdrant containers are destroyed. You have the
backup files on a recovery machine.

### 1. Provision fresh VPS + Coolify

Follow `.local-state/coolify_setup_info.txt` step-by-step. Point GoDaddy DNS
to the new IP.

### 2. Restore Postgres

```bash
# On the Nexus app container via Coolify Terminal tab:
pg_restore -h postgres -U nexus -d nexus --clean --if-exists /backups/YYYY-MM-DD.dump
```

Alternative via Coolify UI: Configuration → Persistent Storage → mount
volume with the dump, then Terminal → `pg_restore`.

Run `alembic upgrade head` after restore in case schema drift.

### 3. Restore Qdrant

```bash
# Stop Qdrant first
docker compose stop qdrant
# Extract snapshots into qdrant data volume
cd /var/lib/docker/volumes/nexus_qdrant_data/_data
tar xzf /var/backups/nexus/qdrant/YYYY-MM-DD.tar.gz
docker compose start qdrant
```

Then call `POST /api/embed-init` (admin) to verify collection shape.

### 4. Verify

- `GET /api/embed-diagnostics` — expect `ping_ok: true`, `nexus_candidates > 0`
- `GET /api/candidates?page_size=1` — expect realistic `total`
- Login flow works via `/login`
- `GET /api/jobs/1/recommendations?top_k=3` returns matches

If vectors are stale vs DB candidates (e.g. embeddings restore older than DB
restore): run `POST /api/admin/import-talent-radar?copy_embeddings=true`
with DATABASE_URL pointing to the restored state.

## Automated drill

**Not operational — see the status block at the top.** The steps below are what
the workflow is written to do; because `BACKUP_DRILL_SSH_KEY` is absent, steps
1–5 have never executed. The job now exits non-zero in that state rather than
reporting a green run that proves nothing.

`.github/workflows/backup-drill.yml` runs weekly:
1. Fetches the latest dump from the VPS (via SCP; SSH key in `BACKUP_DRILL_SSH_KEY` secret)
2. Stands up a throwaway Postgres 16 + Qdrant in the GitHub Actions runner
3. Runs `pg_restore` into the ephemeral Postgres
4. Runs `alembic -c alembic/alembic.ini upgrade head` to verify schema
   compatibility
5. Runs a sample query: `SELECT count(*) FROM candidates`
6. Reports success/failure in GitHub Actions; alerts if 2 consecutive drills
   fail

Once operational, the drill would catch:
- Dump corruption (restore fails)
- Schema drift (alembic upgrade fails on restored snapshot)
- Backup script regressions (file missing / empty)

None of these are currently being caught.

## Known gaps

- **The drill does not run** — `BACKUP_DRILL_SSH_KEY` is unset; see the status
  block. Until it runs, none of the three classes above are detected. This is
  the gap that hid all the others: a green weekly job read as reassurance.
- **The backup script is unversioned** — it exists only on the VPS, so it
  cannot be reviewed, cannot be restored if the VPS is lost, and its actual
  behaviour (does it still run? does rotation work? is the dump non-empty?) is
  unknown. It belongs in this repository.
- **Off-site copy not automated** — dumps live only on the VPS. If the VPS is
  destroyed, backups go with it. Documented as a "Phase 8 item" since the
  original commit and never done. This is now the first thing to fix, because
  every other guarantee is worthless without a copy that survives the host.
- **No point-in-time recovery (PITR)** — only daily dumps, losing up to 24h
  of data. WAL-E / wal-g with S3 target would bring PITR to minutes.
- **Drill doesn't exercise Qdrant** — restoring snapshots in CI needs
  Qdrant container + volume mount which is heavyweight. Current drill is
  Postgres-only.
