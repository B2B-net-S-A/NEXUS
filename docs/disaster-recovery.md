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

## Off-site backup (compose service `backup`)

The replacement for the unversioned VPS script. Lives in `backup/` in this
repository, deploys through the normal `git push` → Coolify pipeline, and needs
no SSH access to install or change.

| Artefact | Source | Object key | Recoverable from elsewhere? |
|---|---|---|---|
| Postgres | `pg_dump -Fc` over the compose network | `nexus/postgres/YYYY-MM-DD/…dump.age` | **No — sole source of truth** |
| Uploaded CVs | `uploads_data` volume, read-only mount | `nexus/uploads/YYYY-MM-DD/…tar.gz.age` | **No — original documents** |
| Qdrant | snapshot API, per collection | `nexus/qdrant/YYYY-MM-DD/…snapshot.age` | Yes — re-embed from Postgres (costs time + Voyage spend) |

Design decisions worth knowing before changing anything:

- **Nothing buffers to local disk.** Every artefact is a pipe:
  `producer | age | rclone rcat`. This VPS hit 98.8% disk in July 2026 and the
  cleanup that followed destroyed the Postgres container; a backup job that
  staged a temp dump would be the single most likely thing to repeat that.
- **The server holds only a public key.** `age -r <recipient>` encrypts. The
  private half lives in the password manager and never touches the VPS, so a
  compromised sidecar can write new backups but cannot read old ones.
  **Losing that private key loses every backup** — there is no recovery path.
- **Retention only prunes after a fully clean run.** Deleting old good backups
  on a night when the new ones failed converts a backup system into a data-loss
  system.
- **Every upload is verified by re-stat.** A pipe exiting `0` is not evidence
  the bytes arrived; the remote object size is checked, and an implausibly
  small Postgres dump is recorded as a failure rather than a success.
- **`LATEST.json`** at the bucket root records when a backup last genuinely
  succeeded and how large each artefact was. Monitoring should read that rather
  than assume a scheduled job implies a stored backup — assuming exactly that
  is what hid the broken drill for months.

### Activation

Everything ships disabled (`BACKUP_ENABLED=false`); the script exits
immediately. To turn it on:

1. Create a Hetzner Object Storage bucket (Germany) and an access key pair.
2. Generate the encryption key **on a local machine, not the server**:
   ```bash
   age-keygen -o nexus-backup.key   # prints the public key; keep the file safe
   ```
   Store `nexus-backup.key` in the password manager. Put **only** the public
   key (`age1…`) into Coolify.
3. In the Coolify env vault set `BACKUP_S3_*`, `BACKUP_AGE_PUBLIC_KEY`, and
   `BACKUP_RUN_ON_START=true` for the first deploy so a misconfiguration
   surfaces in minutes rather than at 02:00 UTC.
4. Set `BACKUP_ENABLED=true` and redeploy.
5. Confirm `LATEST.json` exists in the bucket and `failures` is `0`, then set
   `BACKUP_RUN_ON_START=false`.
6. Only after a **restore has actually been rehearsed** from these objects may
   the status block at the top of this document be replaced with a verified
   date.

### Restoring from an off-site copy

```bash
# Postgres
rclone cat offsite:nexus-backups/nexus/postgres/YYYY-MM-DD/<file>.dump.age \
  | age -d -i nexus-backup.key > nexus.dump
pg_restore -h <host> -U nexus -d nexus --clean --if-exists nexus.dump

# Uploaded CVs
rclone cat offsite:nexus-backups/nexus/uploads/YYYY-MM-DD/<file>.tar.gz.age \
  | age -d -i nexus-backup.key | tar -xzf - -C /path/to/uploads

# Qdrant — per collection, then POST /api/embed-init to verify shape
rclone cat offsite:nexus-backups/nexus/qdrant/YYYY-MM-DD/<file>.snapshot.age \
  | age -d -i nexus-backup.key > coll.snapshot
```

## Legacy backup policy (VPS-local, unverified)

> Retained for reference only. The script below **has never been present in
> this repository** — see the status block. Do not rely on it.

Nightly backup job on the Hetzner VPS. Two snapshots are captured:

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
- **The legacy backup script is unversioned** — it exists only on the VPS, so
  it cannot be reviewed, cannot be restored if the VPS is lost, and its actual
  behaviour (does it still run? does rotation work? is the dump non-empty?) is
  unknown. Superseded by the `backup/` service in this repo, but the old script
  is presumably still running on the host and should be turned off once the new
  one is verified, so the two do not compete for disk.
- **Off-site copy — built, not yet switched on.** Addressed by the `backup`
  compose service; it remains a gap until `BACKUP_ENABLED=true` and
  `LATEST.json` shows a clean run. Until then, backups still exist only on the
  VPS disk.
- **CV files were backed up by nothing at all** — the legacy policy table above
  covers Postgres and Qdrant only, but candidate CVs live in a third volume
  (`uploads_data` → `/tmp/nexus/uploads`) that no backup ever touched. Unlike
  Qdrant these cannot be regenerated from anything. Now covered by the new
  service; also a reminder to check the volume list, not the documentation,
  when reasoning about what is protected.
- **No point-in-time recovery (PITR)** — only daily dumps, losing up to 24h
  of data. WAL-E / wal-g with S3 target would bring PITR to minutes.
- **Drill doesn't exercise Qdrant** — restoring snapshots in CI needs
  Qdrant container + volume mount which is heavyweight. Current drill is
  Postgres-only.
