# Disaster Recovery — Nexus ATS

> ## ⚠️ STATUS: THE RESTORE PATH HAS NEVER BEEN VERIFIED
>
> Established 2026-07-20, re-verified against production 2026-07-27. Everything
> below the status block describes the *intended* design. Treat it as a plan,
> not as a guarantee.
>
> - **The weekly drill has never restored anything.** It was not configured, so
>   every meaningful step in `.github/workflows/backup-drill.yml` — fetch,
>   `pg_restore`, `alembic`, smoke query — was skipped on every run. The job
>   nevertheless reported **success** for months. It now fails loudly instead,
>   and it restores the off-site copy rather than the legacy VPS-local one it
>   used to fetch over SCP — those were two unrelated systems.
> - **The backup sidecar is deployed but kill-switched.** `BACKUP_ENABLED` is
>   `false` in production, so the container runs and does nothing.
> - **The backup script is not in this repository.** This document used to
>   credit `.scripts/backup.sh` "from commit `dfc55bd`". That commit adds
>   `uptime-probe.yml` and nothing else; no backup script has ever been
>   committed. Whatever runs nightly on the VPS is unversioned and unreviewed.
> - **There is no off-site copy.** Dumps live on the same VPS disk that hit
>   98.8% utilisation in July 2026 and on which `docker container prune`
>   destroyed the Postgres container. A disk-level loss takes the backups too.
>   The host script `/root/nexus-offsite-backup.sh` has logged "the off-site
>   account was never created, exiting without error" every night for weeks —
>   **and exits 0**, which is why nothing ever alarmed.
> - **The candidate CV corpus was backed up by nothing at all.** ~136k files /
>   ~37 GB live only in the `nexus-candidate-documents` object-storage bucket;
>   `candidate_documents.file_content` is NULL since the migration to object
>   storage. `pg_dump` therefore preserves `storage_key` and not one byte of the
>   files. An earlier version of this document claimed the `uploads_data` volume
>   covered them — it does not; that volume holds generated contract documents.
>   Now genuinely covered (see the artefact table below), but not yet switched
>   on.
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

| Artefact | Source | Object key | Encrypted | Recoverable from elsewhere? |
|---|---|---|---|---|
| `postgres` | `pg_dump -Fc` over the compose network | `nexus/postgres/YYYY-MM-DD/…dump.age` | age | **No — sole source of truth** |
| `uploads` | `uploads_data` volume, read-only mount | `nexus/uploads/YYYY-MM-DD/…tar.gz.age` | age | **No — generated contract documents** |
| `cv_corpus` | `OBJECT_STORAGE_BUCKET`, incremental mirror | `nexus/candidate-documents/current/<storage_key>` | **no — see below** | **No — the original CVs** |
| `qdrant` | snapshot API, per collection | `nexus/qdrant/YYYY-MM-DD/…snapshot.age` | age | Yes — re-embed from Postgres (costs time + Voyage spend) |

**`uploads` is not the CV corpus.** The `uploads_data` volume holds generated
artefacts (`contracts/`, `client_one_pagers/`, `branded_cvs/`, …). Candidate CVs
have lived in object storage since
`scripts/migrate_cvs_to_object_storage.py`; `candidate_documents.file_content`
is NULL and only `storage_key` remains in the database. Restoring `postgres`
without `cv_corpus` reconstitutes ~136k rows pointing at files that no longer
exist. Reason about the volume list and `object_storage.py`, not about this
table's history.

### Why the CV mirror is not additionally encrypted

A deliberate, argued exception — do not "harden" it without reading this.

- The source bucket already stores these files without client-side encryption,
  and the destination is a private bucket with SSE-B2 at rest. A client-side
  layer on the *copy* would not raise the floor set by the *original*.
- It would introduce a **second independent key** whose loss is silent and
  total. This is the last line of defence; the failure mode that matters most
  here is "the backup turned out to be unreadable", not "someone read the
  backup". One key (`age`) is already one more than zero things that can be
  lost.
- Consequence to accept: anyone holding the B2 credentials can read CVs. The
  bucket is private, the credentials live only in the Coolify vault and in
  GitHub secrets, and both are already sufficient to reach production data.

If this trade is ever revisited, the alternative is `rclone crypt` over the
destination — and the crypt password must then be stored **alongside the age
private key**, in the same password manager entry, or the next person to need a
restore will find half a key.

### Deletions cannot propagate into the mirror

`rclone sync` mirrors deletions, so a purge of the source bucket — accidental,
buggy, or hostile — would erase the only off-site copy on the next nightly run.
The sync therefore uses `--backup-dir`: anything removed or replaced upstream is
moved to `nexus/candidate-documents/replaced/YYYY-MM-DD/` instead of being
deleted, and only that dated prefix is subject to retention. Retention also
explicitly excludes `candidate-documents/current/**`, because those objects are
a live mirror of an immutable corpus rather than dated snapshots — ageing them
out by mtime would erode the backup one day at a time.

Design decisions worth knowing before changing anything:

- **Nothing buffers to local disk.** Every artefact is a pipe:
  `producer | age | rclone rcat`. This VPS hit 98.8% disk in July 2026 and the
  cleanup that followed destroyed the Postgres container; a backup job that
  staged a temp dump would be the single most likely thing to repeat that.
- **The server holds only a public key.** `age -R <recipients>` encrypts. The
  private half lives in the password manager and never touches the VPS, so a
  compromised sidecar can write new backups but cannot read old ones.
  **Losing that private key loses every backup** — there is no recovery path.
  Store it in the password manager *before* enabling the service, not after.
- **`BACKUP_AGE_PUBLIC_KEY` accepts several recipients** (comma- or
  space-separated) and any one of the matching private keys can decrypt. This
  exists so the weekly drill can hold a *separate* key in GitHub secrets: the
  master key must never be there, and a drill key can be rotated or dropped
  later without re-encrypting a single stored object.
- **Retention only prunes after a fully clean run.** Deleting old good backups
  on a night when the new ones failed converts a backup system into a data-loss
  system.
- **Every upload is verified by re-stat.** A pipe exiting `0` is not evidence
  the bytes arrived; the remote object size is checked, and an implausibly
  small Postgres dump is recorded as a failure rather than a success.
- **`LATEST.json`** at the bucket root records when a backup last genuinely
  succeeded, and per artefact its status, byte count and object count.
  `.github/workflows/uptime-probe.yml` reads it hourly and fails when the
  manifest is stale, reports failures, or is **missing an artefact** — the last
  check matters most, because a manifest that simply stops mentioning
  `cv_corpus` is otherwise indistinguishable from a clean one. That was the
  original bug's exact shape.
- **The sidecar has a healthcheck.** `backup/healthcheck.sh` fails when the
  scheduler's heartbeat goes stale (loop dead or container wedged) or when a run
  has been in progress beyond `BACKUP_MAX_RUN_SECONDS` (hung `rclone`). It
  deliberately says nothing about whether backups *succeed*: a green container
  next to a silently failing backup is the reassurance this system has already
  been burned by.
- **A failed run is retried** three times, 15 minutes apart, before the loop
  gives up until the next day. One transient S3 blip used to cost a full day.

### Activation

Everything ships disabled (`BACKUP_ENABLED=false`); the script exits
immediately. The destination bucket already exists: Backblaze B2
`dynaminds-nexus-offsite`, endpoint `s3.eu-central-003.backblazeb2.com`, region
`eu-central-003`, private, SSE-B2 on, lifecycle "deleted files disappear after
30 days". `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_REGION` and
`BACKUP_S3_PROVIDER=Other` are already set in Coolify. To turn it on:

1. **Generate two age key pairs on a local machine, never on the server:**
   ```bash
   age-keygen -o nexus-backup-master.key   # prints its public key
   age-keygen -o nexus-backup-drill.key    # prints its public key
   ```
   Put **both files** in the password manager. Only the public halves (`age1…`)
   leave the machine. The master key is the one you must not lose; the drill key
   exists so the weekly drill never needs the master.
2. **Coolify env vault** (application `nexus`, uuid `ocgkwcbovpve9wvf9smxl0kx`):
   - `BACKUP_S3_ACCESS_KEY` / `BACKUP_S3_SECRET_KEY` — the B2 application key.
   - `BACKUP_AGE_PUBLIC_KEY` — **both** public keys, comma-separated:
     `age1master…,age1drill…`.
   - `OBJECT_STORAGE_ENDPOINT` / `_ACCESS_KEY` / `_SECRET_KEY` / `_BUCKET` —
     already present for the backend; the sidecar now needs them too, otherwise
     the CV corpus is not backed up and every run fails loudly.
   - `BACKUP_RUN_ON_START=true` for the first deploy, so a misconfiguration
     surfaces in minutes rather than at 02:00 UTC.
3. **Raise the Backblaze caps FIRST — a fresh account cannot hold this dataset.**
   The free tier stops at 10 GB of storage, and B2 enforces caps by *refusing
   the request*, not by billing: uploads answer
   `403 AccessDenied: Cannot upload files, storage cap exceeded` and reads answer
   `403 … transaction (Class B) cap exceeded`. Both were hit on the first real
   run (2026-07-27) — the storage one only became visible after the Class B one
   was fixed, so expect to clear them in that order.

   Measured 2026-07-27, and the corpus grows — re-measure before trusting these:

   | | objects | GB |
   |---|---:|---:|
   | CV corpus (source bucket) | 139 094 | 41.2 |
   | Postgres dump, per run | 1 | 0.29 |
   | Uploads archive, per run | 1 | 0.41 |
   | Qdrant snapshots, per run | 4 | 0.33 |

   Steady state at 30-day retention ≈ **72 GB** (41 GB mirror + ~31 GB of
   rotating dumps). Set the **storage cap around 100 GB** for headroom, and the
   **Class B / download cap above zero** — without the latter no restore is
   possible, which is the failure mode that makes a backup worthless precisely
   when it is needed. At B2 list price that is roughly **$0.45/month**; the cap
   exists to stop runaway bills, not to be left at the default.
4. Set `BACKUP_ENABLED=true` and redeploy.
5. **Expect the first run to be long.** The initial CV seed transfers ~41 GB /
   ~139k objects through the container. `BACKUP_CV_MAX_DURATION` defaults to
   `6h`; if the first run trips it, the artefact is recorded as failed (on
   purpose — an incomplete corpus is not a backup) and the next run resumes
   where it stopped. Raise the cap or let it finish over two nights.
6. Confirm in the bucket that `LATEST.json` has `failures: 0` and that the
   `cv_corpus` artefact's `objects` count matches the source bucket. Then set
   `BACKUP_RUN_ON_START=false`.
7. **GitHub — repository secrets** (`artur-t-96/Nexus`):
   `BACKUP_AGE_PRIVATE_KEY` (contents of `nexus-backup-drill.key`, *not* the
   master), `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY`.
   **Repository variables:** `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`,
   `BACKUP_S3_REGION`, and `BACKUP_MONITORING_ENABLED=true`.
8. Run `.github/workflows/backup-drill.yml` manually (`workflow_dispatch`). It
   fetches the real off-site dump, decrypts it, restores it, runs `alembic
   upgrade head`, checks five tables are non-empty, and samples 25 `storage_key`
   values against the CV mirror.
9. Turn off the legacy host script (`/root/nexus-offsite-backup.sh` and the
   local `/var/backups/nexus` cron) once the drill has passed, so the two do not
   compete for disk.
10. Only after step 8 has genuinely passed may the status block at the top of
   this document be replaced with a verified date.

> Until `BACKUP_MONITORING_ENABLED` is `true`, the freshness job in
> `uptime-probe.yml` is *skipped*, not passing. Nothing is claiming the backups
> are fine; nothing is watching them either.

### Restoring from an off-site copy

> **FIRST, before anything else: raise the Backblaze caps.** Every read from B2 —
> `rclone cat`, `rclone copy`, even a `HEAD` — is a **Class B** transaction,
> billed and *capped daily*. A fresh account sits at the free-tier default, and
> once that cap is hit B2 answers every download with
> `403 AccessDenied: Cannot download file, download bandwidth or transaction
> (Class B) cap exceeded`. Uploads are Class A: free and uncapped, which is why
> backups can keep succeeding for weeks while restores are silently impossible.
>
> This is not hypothetical — it happened on the very first seeding run
> (2026-07-27) and is what `RCLONE_S3_NO_HEAD` in `backup/backup.sh` works
> around. **Go to secure.backblaze.com → Caps & Alerts and set a daily cap above
> zero *before* starting a restore.** The real cost is negligible (the full
> 37 GB corpus is well under a euro); the cap exists to prevent runaway bills,
> not to be left at the default. Verify with a single object first:
>
> ```bash
> rclone copy offsite:dynaminds-nexus-offsite/nexus/LATEST.json /tmp/
> ```
>
> If that returns 403, the cap is still blocking you — no other step will work.

```bash
# Postgres
rclone cat offsite:dynaminds-nexus-offsite/nexus/postgres/YYYY-MM-DD/<file>.dump.age \
  | age -d -i nexus-backup-master.key > nexus.dump
pg_restore -h <host> -U nexus -d nexus --clean --if-exists nexus.dump

# Generated documents (contracts, one-pagers, branded CVs)
rclone cat offsite:dynaminds-nexus-offsite/nexus/uploads/YYYY-MM-DD/<file>.tar.gz.age \
  | age -d -i nexus-backup-master.key | tar -xzf - -C /path/to/uploads

# Candidate CV corpus — NOT encrypted and NOT a single archive; it is a mirror
# keyed exactly like the live bucket, so `storage_key` values from the restored
# database resolve directly. Restore it BEFORE announcing the system is back:
# without it every candidate profile has an unreadable CV.
rclone sync offsite:dynaminds-nexus-offsite/nexus/candidate-documents/current \
            cvsrc:nexus-candidate-documents --fast-list --transfers 8
# A file removed upstream in the last 30 days is under .../replaced/YYYY-MM-DD/

# Qdrant — per collection, then POST /api/embed-init to verify shape
rclone cat offsite:dynaminds-nexus-offsite/nexus/qdrant/YYYY-MM-DD/<file>.snapshot.age \
  | age -d -i nexus-backup-master.key > coll.snapshot
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

**Not operational until the secrets in "Activation" step 6 exist.** The job
exits non-zero in that state rather than reporting a green run that proves
nothing.

It previously fetched `/var/backups/nexus/…` from the VPS over SCP — the legacy,
same-disk copy this document itself disowns. So the drill and the backup service
were two unrelated systems, and a green drill said nothing about whether the
off-site copy could be restored. It also never decrypted anything.

`.github/workflows/backup-drill.yml` now runs weekly (Mon 04:00 UTC) against the
real off-site bucket:

1. Reads `LATEST.json`; fails if the last run is older than 36h or recorded any
   failed artefact.
2. Picks the newest object under `nexus/postgres/`, `rclone cat`s it and
   **decrypts it with `age -d`**, then verifies the plaintext is a real archive
   via `pg_restore -l`.
3. Restores into an ephemeral Postgres 16. `pg_restore` runs from
   `postgres:16-alpine`, not the runner's own client, so a client/server version
   mismatch cannot break the drill.
4. `alembic -c alembic/alembic.ini upgrade head` — schema-drift check.
5. Asserts `candidates`, `jobs`, `users`, `clients` and `candidate_documents`
   are all non-empty, that there are no orphan `candidate_documents`, and that
   some rows still carry a `storage_key`.
6. Samples 25 `storage_key` values from the restored database and confirms each
   object exists in the CV mirror.

What each step is there to catch:

- **Decryption** (2) — the failure with no other symptom. A wrong recipient, or
  a private key nobody kept, produces backups that upload cleanly, pass every
  size check, and are permanently unreadable. Nothing else in this repository
  would notice.
- **Freshness** (1) — restoring a three-week-old dump and calling it green is
  the same lie in a different place.
- **Restore + schema** (3, 4) — dump corruption, schema drift.
- **Data presence** (5) — a restore that produces the schema and no rows.
- **CV mirror** (6) — the database restores fine and every candidate's CV is a
  dead link. This is the one the previous drill design could not have caught
  even in principle.

### Reading the stderr filter

`pg_restore --clean` against a fresh database always emits "does not exist"
noise from `DROP` statements. The old filter dropped every line matching that
phrase — which also silenced the genuine failure:

```
pg_restore: error: could not execute query: ERROR:  relation "candidates" does not exist
Command was: COPY public.candidates ...
```

i.e. a `COPY` into a table whose `CREATE` failed: an empty restore reported as
harmless. The filter now classifies by the **command** on the following
`Command was:` line, forgiving only `DROP`, `ALTER TABLE … DROP` and extension
statements. Anything else fails the drill.

## Known gaps

- **Nothing is switched on yet.** The `backup` service, the drill and the
  freshness monitor are all written, reviewed and tested, and all three are
  inert until the credentials in "Activation" exist. Until `LATEST.json` shows a
  clean run *and* the drill has passed once, the only copies of this database
  remain on the same disk as production. This is the whole gap; everything below
  is secondary.
- **The legacy host scripts are unversioned and still running** —
  `/root/nexus-offsite-backup.sh` (which has never copied anything and exits 0
  while saying so) and the local `/var/backups/nexus` cron. Neither can be
  reviewed or restored if the VPS is lost. Turn both off once the new service is
  verified, so the two do not compete for disk.
- **The CV corpus is mirrored unencrypted.** Argued above under "Why the CV
  mirror is not additionally encrypted" — a deliberate trade of confidentiality
  against recoverability, not an oversight.
- **The drill holds a decryption key in GitHub secrets.** Unavoidable: a drill
  that cannot decrypt does not test the thing most likely to be broken. Mitigated
  by using a *separate* recipient key, so it can be rotated or dropped without
  touching the master key or re-encrypting stored objects. Note that the repo's
  existing secrets already permit deploying arbitrary code to production, so this
  does not meaningfully widen the blast radius of a GitHub compromise.
- **No point-in-time recovery (PITR)** — only daily dumps, losing up to 24h
  of data. WAL-E / wal-g with S3 target would bring PITR to minutes.
- **Drill doesn't exercise Qdrant** — restoring snapshots in CI needs
  Qdrant container + volume mount which is heavyweight. Acceptable: Qdrant is
  the one artefact that *can* be regenerated, by re-embedding from Postgres.
- **The CV spot-check samples 25 files, not 136k.** It proves the mirror is
  keyed correctly and populated, not that every object is present. The
  `cv_corpus` object-count gate in `backup.sh` covers completeness nightly.
