# Disaster Recovery — Nexus ATS

This document covers backup policy and restore procedures. Last verified via
automated drill: see `.github/workflows/backup-drill.yml` (runs Mondays 04:00 UTC).

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

`.github/workflows/backup-drill.yml` runs weekly:
1. Fetches the latest dump from the VPS (via SCP; SSH key in `BACKUP_DRILL_SSH_KEY` secret)
2. Stands up a throwaway Postgres 16 + Qdrant in the GitHub Actions runner
3. Runs `pg_restore` into the ephemeral Postgres
4. Runs `alembic -c alembic/alembic.ini upgrade head` to verify schema
   compatibility
5. Runs a sample query: `SELECT count(*) FROM candidates`
6. Reports success/failure in GitHub Actions; alerts if 2 consecutive drills
   fail

The drill catches:
- Dump corruption (restore fails)
- Schema drift (alembic upgrade fails on restored snapshot)
- Backup script regressions (file missing / empty)

## Known gaps

- **Off-site copy not automated** — dumps live only on the VPS. If VPS is
  totally destroyed, backups go with it. Fix: add `rsync` to Hetzner
  Storage Box in the nightly script. Tracked as Phase 8 item.
- **No point-in-time recovery (PITR)** — only daily dumps, losing up to 24h
  of data. WAL-E / wal-g with S3 target would bring PITR to minutes.
- **Drill doesn't exercise Qdrant** — restoring snapshots in CI needs
  Qdrant container + volume mount which is heavyweight. Current drill is
  Postgres-only.
