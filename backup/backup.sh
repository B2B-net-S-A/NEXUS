#!/bin/sh
# One backup run: Postgres + Qdrant + uploaded files -> encrypted -> off-site.
#
# Design constraints that shaped this script:
#
# 1. **Never buffer to local disk.** This VPS hit 98.8% disk utilisation in
#    July 2026, and the cleanup that followed (`docker container prune`)
#    destroyed the Postgres container. A backup job that writes a temp dump
#    before uploading would be the most likely thing to push it over again --
#    the irony of the backup causing the outage is not hypothetical here. So
#    everything is a pipe: `producer | age | rclone rcat`. Nothing lands.
#
# 2. **The container holds only a public key.** `age -r <recipient>` encrypts;
#    decryption needs the private key, which lives with Artur, not on the
#    server. A compromised sidecar can write new backups but cannot read old
#    ones.
#
# 3. **Fail loudly, per artefact.** Each artefact is attempted independently and
#    its outcome recorded. A Qdrant failure must not silently cost us the
#    Postgres dump -- that coupling is exactly how the old drill managed to
#    report green while doing nothing.
#
# 4. **Prove the upload.** Every artefact is re-stat'ed after upload and its
#    real remote size recorded. "The pipe exited 0" is not evidence the bytes
#    arrived; `rclone size` on the object is.
set -eu
# pipefail: bez tego status potoku `producer | age | rclone` to wyłącznie kod
# ostatniego procesu — udany `rclone rcat` maskuje `pg_dump`/`tar`/`curl`, który
# padł w środku, i przyjęlibyśmy obcięty backup jako sukces. Z pipefail taki
# potok zwraca niezerowy kod, więc trafia w gałąź `else` (record error) zamiast
# w bramkę rozmiaru. busybox ash (postgres:16-alpine) wspiera `set -o pipefail`.
set -o pipefail

BACKUP_ENABLED="${BACKUP_ENABLED:-false}"
if [ "$BACKUP_ENABLED" != "true" ]; then
    echo "[backup] BACKUP_ENABLED != true — nothing to do (kill-switch)."
    exit 0
fi

fail() {
    echo "[backup] FATAL: $1" >&2
    exit 1
}

# ── Required configuration ───────────────────────────────────────────────────
[ -n "${BACKUP_AGE_PUBLIC_KEY:-}" ] || fail "BACKUP_AGE_PUBLIC_KEY is required (age recipient; public half only)"
[ -n "${BACKUP_S3_BUCKET:-}" ] || fail "BACKUP_S3_BUCKET is required"
[ -n "${BACKUP_S3_ENDPOINT:-}" ] || fail "BACKUP_S3_ENDPOINT is required"
[ -n "${BACKUP_S3_ACCESS_KEY:-}" ] || fail "BACKUP_S3_ACCESS_KEY is required"
[ -n "${BACKUP_S3_SECRET_KEY:-}" ] || fail "BACKUP_S3_SECRET_KEY is required"

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
UPLOADS_DIR="${BACKUP_UPLOADS_DIR:-/data/uploads}"
QDRANT_URL="${BACKUP_QDRANT_URL:-http://qdrant:6333}"
PREFIX="${BACKUP_S3_PREFIX:-nexus}"

STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
DAY="$(date -u +%Y-%m-%d)"

# rclone is configured entirely through env so no config file (and no secret)
# is ever written to the filesystem.
export RCLONE_CONFIG_OFFSITE_TYPE="s3"
export RCLONE_CONFIG_OFFSITE_PROVIDER="${BACKUP_S3_PROVIDER:-Other}"
export RCLONE_CONFIG_OFFSITE_ENDPOINT="$BACKUP_S3_ENDPOINT"
export RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY"
export RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY"
export RCLONE_CONFIG_OFFSITE_REGION="${BACKUP_S3_REGION:-eu-central-1}"
# Object storage bills per request; retry transient failures rather than
# losing a night's backup to one blip.
export RCLONE_RETRIES="3"
export RCLONE_LOW_LEVEL_RETRIES="5"
# Bez limitów czasu nieodpowiadające S3 zawiesza cały potok bezterminowo:
# pg_dump czeka na age, age na rclone, a pozostałe artefakty nigdy nie zostaną
# nawet spróbowane. Kontener wygląda wtedy na żywy, nie robiąc nic.
export RCLONE_TIMEOUT="30m"
export RCLONE_CONNECT_TIMEOUT="60s"

DEST="offsite:${BACKUP_S3_BUCKET}/${PREFIX}"

# Collected per-artefact results, folded into the manifest at the end.
RESULTS=""
FAILURES=0

record() { # name status bytes detail
    RESULTS="${RESULTS}$(printf '{"artefact":"%s","status":"%s","bytes":%s,"detail":"%s"}' "$1" "$2" "$3" "$4"),"
    if [ "$2" != "ok" ]; then
        FAILURES=$((FAILURES + 1))
        echo "[backup] FAILED $1: $4" >&2
    else
        echo "[backup] ok $1 (${3} bytes remote)"
    fi
}

remote_size() { # path -> bytes on stdout, 0 if absent
    rclone size "$1" --json 2>/dev/null | jq -r '.bytes // 0' 2>/dev/null || echo 0
}

# ── 1. Postgres ──────────────────────────────────────────────────────────────
# The only true source of truth. Custom format (-Fc) so pg_restore can do
# selective restores and parallel jobs.
pg_object="${DEST}/postgres/${DAY}/nexus-${STAMP}.dump.age"
if PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
        -h "${POSTGRES_HOST:-postgres}" \
        -U "${POSTGRES_USER:-nexus}" \
        -d "${POSTGRES_DB:-nexus}" \
        -Fc --no-owner --no-privileges 2>/tmp/pg.err \
    | age -r "$BACKUP_AGE_PUBLIC_KEY" \
    | rclone rcat "$pg_object"; then
    size="$(remote_size "$pg_object")"
    # A "successful" pg_dump that produced almost nothing means the pipe broke
    # somewhere. Treat an implausibly small dump as a failure, not a backup.
    if [ "$size" -lt 1024 ]; then
        record "postgres" "suspect" "$size" "remote object is implausibly small"
    else
        record "postgres" "ok" "$size" ""
    fi
else
    record "postgres" "error" 0 "$(tr -d '\n\"' </tmp/pg.err | tail -c 200)"
fi

# ── 2. Uploaded files (CVs) ──────────────────────────────────────────────────
# Third dataset, previously backed up by nothing at all: the DR policy table
# listed only Postgres and Qdrant. These are the actual candidate CV documents;
# unlike Qdrant they cannot be regenerated from anything.
up_object="${DEST}/uploads/${DAY}/uploads-${STAMP}.tar.gz.age"
if [ -d "$UPLOADS_DIR" ]; then
    if tar -C "$UPLOADS_DIR" -czf - . 2>/tmp/up.err \
        | age -r "$BACKUP_AGE_PUBLIC_KEY" \
        | rclone rcat "$up_object"; then
        up_size="$(remote_size "$up_object")"
        # Ta sama bramka co przy Postgresie: zerwany potok, którego rclone
        # przyjmie jako obiekt zerowej długości, bez tego zapisałby się jako
        # "ok" i spełnił warunek czystego przebiegu — a wtedy retencja
        # skasowałaby dobre stare kopie w noc, w którą nowa jest pusta.
        if [ "$up_size" -lt 1024 ]; then
            record "uploads" "suspect" "$up_size" "remote object is implausibly small"
        else
            record "uploads" "ok" "$up_size" ""
        fi
    else
        record "uploads" "error" 0 "$(tr -d '\n\"' </tmp/up.err | tail -c 200)"
    fi
else
    record "uploads" "error" 0 "upload dir ${UPLOADS_DIR} not mounted"
fi

# ── 3. Qdrant ────────────────────────────────────────────────────────────────
# Uses the snapshot API rather than tarring the live volume: copying files from
# a running Qdrant yields a torn, possibly unloadable snapshot. Vectors are
# reconstructible from Postgres by re-embedding, so a Qdrant failure is a
# time-and-Voyage-cost problem, not data loss -- it must never abort the run.
#
# The snapshot does briefly occupy Qdrant's own disk, so it is deleted
# immediately after streaming out, even if the upload failed.
if collections="$(curl -fsS --max-time 30 "${QDRANT_URL}/collections" 2>/dev/null | jq -r '.result.collections[]?.name')"; then
    for c in $collections; do
        # `|| true` w środku podstawienia: to BARE assignment (nie w `if`), więc
        # z pipefail+set -e niezerowy curl przerwałby cały skrypt, porzucając
        # kolejne kolekcje i zapis manifestu — a to łamie „fail loudly, per
        # artefact" (#3). Zamiast tego pusty snap wpada w guard [ -z ] poniżej.
        snap="$(curl -fsS -X POST --max-time 300 "${QDRANT_URL}/collections/${c}/snapshots" 2>/dev/null | jq -r '.result.name // empty' || true)"
        if [ -z "$snap" ]; then
            record "qdrant:${c}" "error" 0 "snapshot creation returned no name"
            continue
        fi
        q_object="${DEST}/qdrant/${DAY}/${c}-${STAMP}.snapshot.age"
        if curl -fsS --max-time 600 "${QDRANT_URL}/collections/${c}/snapshots/${snap}" \
            | age -r "$BACKUP_AGE_PUBLIC_KEY" \
            | rclone rcat "$q_object"; then
            record "qdrant:${c}" "ok" "$(remote_size "$q_object")" ""
        else
            record "qdrant:${c}" "error" 0 "download or upload failed"
        fi
        # Always reclaim the space, success or not.
        curl -fsS -X DELETE --max-time 60 \
            "${QDRANT_URL}/collections/${c}/snapshots/${snap}" >/dev/null 2>&1 \
            || echo "[backup] WARNING: could not delete Qdrant snapshot ${snap}" >&2
    done
else
    record "qdrant" "error" 0 "could not list collections at ${QDRANT_URL}"
fi

# ── 4. Retention ─────────────────────────────────────────────────────────────
# Pruning runs only when every artefact succeeded. Deleting old good backups on
# a night when the new ones failed is how a backup system turns into a data-loss
# system.
if [ "$FAILURES" -eq 0 ]; then
    if rclone delete "$DEST" --min-age "${RETENTION_DAYS}d" 2>/dev/null; then
        rclone rmdirs "$DEST" --leave-root 2>/dev/null || true
        echo "[backup] retention: removed objects older than ${RETENTION_DAYS}d"
    else
        echo "[backup] WARNING: retention pass failed; old objects kept" >&2
    fi
else
    echo "[backup] retention SKIPPED — ${FAILURES} artefact(s) failed this run." >&2
fi

# ── 5. Manifest ──────────────────────────────────────────────────────────────
# LATEST.json is the machine-readable answer to "when did a backup last
# genuinely succeed, and how big was it". Monitoring reads this instead of
# trusting that a scheduled job existed.
#
# DELIBERATE: this object is NOT encrypted, so that monitoring can read it
# without holding the age private key. The `detail` field carries a truncated
# tool error, which for pg_dump can name the host, user and database (never the
# password — that arrives via PGPASSWORD). The bucket is private and this is
# schema-level information, so the trade is accepted knowingly: a manifest only
# readable with the decryption key could not serve its purpose. Do not "fix"
# this by encrypting the manifest.
manifest="$(printf '{"finished_at":"%s","stamp":"%s","failures":%s,"retention_days":%s,"artefacts":[%s]}' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$STAMP" "$FAILURES" "$RETENTION_DAYS" "${RESULTS%,}")"

echo "$manifest" | rclone rcat "${DEST}/LATEST.json" \
    || echo "[backup] WARNING: could not write manifest" >&2
echo "$manifest" | rclone rcat "${DEST}/history/${STAMP}.json" 2>/dev/null || true

echo "[backup] run complete: ${FAILURES} failure(s)"
[ "$FAILURES" -eq 0 ] || exit 1
