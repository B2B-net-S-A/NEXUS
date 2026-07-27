#!/bin/sh
# One backup run: Postgres + uploaded files + candidate CV corpus + Qdrant
# -> off-site.
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
#
# 5. **The CV corpus is mirrored, not tarred.** ~136k objects / ~37 GB live in a
#    separate S3 bucket (`OBJECT_STORAGE_*`) and are the one dataset that cannot
#    be regenerated from anything -- `pg_dump` only preserves the `storage_key`
#    pointing at them. Tarring 37 GB nightly through this container would be
#    absurd; the objects are immutable, so an incremental remote->remote sync
#    costs almost nothing after the first run. See section 4.
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

# Any artefact smaller than this is treated as a torn pipe rather than a
# backup. Shared by every artefact so a new one cannot be added without a
# sanity gate -- the Qdrant branch shipped without one and would have recorded
# a missing object as `ok` with `bytes: 0`.
MIN_ARTEFACT_BYTES=1024

# age encrypts to several recipients at once, so that ANY of the corresponding
# private keys can decrypt. BACKUP_AGE_PUBLIC_KEY therefore accepts a comma- or
# space-separated list, and a second recipient can be added for the restore
# drill (see docs/disaster-recovery.md): the drill needs a private key in GitHub
# secrets, and that key must not be the master one, whose loss is unrecoverable.
# A drill recipient can later be rotated or dropped without re-encrypting a
# single stored object.
#
# Passed via `-R <file>` rather than repeated `-r` flags so the list survives as
# one shell word — an unquoted expansion here would split on any whitespace that
# crept into the variable and silently encrypt to a truncated recipient set.
# Public keys only; nothing secret is written.
RECIPIENTS_FILE=/tmp/age-recipients
echo "$BACKUP_AGE_PUBLIC_KEY" | tr ',' '\n' | tr ' ' '\n' | grep -v '^$' > "$RECIPIENTS_FILE"
[ -s "$RECIPIENTS_FILE" ] || fail "BACKUP_AGE_PUBLIC_KEY contained no usable recipient"
echo "[backup] encrypting to $(wc -l < "$RECIPIENTS_FILE" | tr -d ' ') recipient(s)"

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
# Restricted bucket keys frequently lack CreateBucket/HeadBucket. Without this
# rclone probes the bucket before every operation and aborts on AccessDenied,
# which would look like a transfer failure. Both buckets are created by hand.
export RCLONE_S3_NO_CHECK_BUCKET="true"
# Bez tego rclone po KAŻDYM wgranym obiekcie robi HEAD, żeby odczytać jego
# metadane. Na Backblaze HEAD to transakcja **klasy B** — ta sama pula co
# pobieranie, limitowana dziennie i płatna po przekroczeniu. PUT jest klasy A:
# darmowy i bez limitu. Przy 136 tys. obiektów korpusu CV pierwszy przebieg
# (27.07) wyczerpał dzienną pulę klasy B w kilkanaście minut, po czym każda
# kolejna kopia padała na `403 AccessDenied: Cannot download file, download
# bandwidth or transaction (Class B) cap exceeded`. Zmierzone w tym przebiegu:
# 12 294 obiekty wgrane, 5 941 odrzuconych — około jednej trzeciej korpusu, i to
# deterministycznie, więc te same pliki przepadałyby co noc.
#
# Ustawione globalnie, nie flagą przy `sync`, bo dotyczy też małych `rcat`:
# LATEST.json idzie pojedynczym PUT-em, a jego niepowodzenie kładzie CAŁY
# przebieg (patrz koniec pliku) — i to właśnie manifest padłby jako pierwszy,
# już po tym, jak wszystkie artefakty poprawnie wylądowały.
#
# Czego NIE tracimy: porównanie źródło↔cel rclone i tak robi z listingów
# (`--fast-list`, klasa C), nie z HEAD-ów. Znika jedynie potwierdzenie rozmiaru
# pojedynczego obiektu tuż po wgraniu — co nigdy nie było tu dowodem: bramką
# jest porównanie LICZBY obiektów źródło↔cel, oparte na listingach, i ono działa
# dalej. Odczyt archiwum (odtwarzanie) to osobna sprawa: pobieranie też jest
# klasy B, więc restore wymaga podniesionego limitu na koncie B2.
export RCLONE_S3_NO_HEAD="true"

# Source remote for the candidate CV corpus: the SAME bucket the application
# reads and writes through backend/app/services/object_storage.py. Read-only in
# practice -- this script never writes to `cvsrc`, only reads from it.
export RCLONE_CONFIG_CVSRC_TYPE="s3"
export RCLONE_CONFIG_CVSRC_PROVIDER="${OBJECT_STORAGE_PROVIDER:-Other}"
export RCLONE_CONFIG_CVSRC_ENDPOINT="${OBJECT_STORAGE_ENDPOINT:-}"
export RCLONE_CONFIG_CVSRC_ACCESS_KEY_ID="${OBJECT_STORAGE_ACCESS_KEY:-}"
export RCLONE_CONFIG_CVSRC_SECRET_ACCESS_KEY="${OBJECT_STORAGE_SECRET_KEY:-}"
export RCLONE_CONFIG_CVSRC_REGION="${OBJECT_STORAGE_REGION:-eu-central-1}"

DEST="offsite:${BACKUP_S3_BUCKET}/${PREFIX}"

# Collected per-artefact results, folded into the manifest at the end.
RESULTS=""
FAILURES=0

record() { # name status bytes detail [objects]
    RESULTS="${RESULTS}$(printf '{"artefact":"%s","status":"%s","bytes":%s,"objects":%s,"detail":"%s"}' \
        "$1" "$2" "$3" "${5:-1}" "$4"),"
    if [ "$2" != "ok" ]; then
        FAILURES=$((FAILURES + 1))
        echo "[backup] FAILED $1: $4" >&2
    else
        echo "[backup] ok $1 (${3} bytes remote, ${5:-1} object(s))"
    fi
}

remote_size() { # path -> bytes on stdout, 0 if absent
    rclone size "$1" --json 2>/dev/null | jq -r '.bytes // 0' 2>/dev/null || echo 0
}

remote_count() { # path -> object count on stdout, 0 if absent
    rclone size "$1" --json 2>/dev/null | jq -r '.count // 0' 2>/dev/null || echo 0
}

# Every single-object artefact ends the same way: re-stat the remote object and
# refuse to call an implausibly small one a backup. Factored out because the
# Qdrant branch was written without this check and therefore recorded a missing
# snapshot as a clean success -- which also let retention prune the last good
# copies on that same run.
gate_and_record() { # name object
    _size="$(remote_size "$2")"
    if [ "$_size" -lt "$MIN_ARTEFACT_BYTES" ]; then
        record "$1" "suspect" "$_size" "remote object is implausibly small (<${MIN_ARTEFACT_BYTES}B)"
    else
        record "$1" "ok" "$_size" ""
    fi
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
    | age -R "$RECIPIENTS_FILE" \
    | rclone rcat "$pg_object"; then
    # A "successful" pg_dump that produced almost nothing means the pipe broke
    # somewhere. Treat an implausibly small dump as a failure, not a backup.
    gate_and_record "postgres" "$pg_object"
else
    record "postgres" "error" 0 "$(tr -d '\n\"' </tmp/pg.err | tail -c 200)"
fi

# ── 2. Generated documents on the uploads volume ─────────────────────────────
# The `uploads_data` volume. NOTE: despite the historical "Uploaded files (CVs)"
# heading this is NOT the candidate CV corpus -- these are generated contract
# artefacts (`contracts/`, `client_one_pagers/`, `branded_cvs/`, ...). Candidate
# CVs live in object storage and are handled by section 3. Confusing the two is
# what left ~136k CV files backed up by nothing while the DR document claimed
# they were covered.
up_object="${DEST}/uploads/${DAY}/uploads-${STAMP}.tar.gz.age"
if [ -d "$UPLOADS_DIR" ]; then
    if tar -C "$UPLOADS_DIR" -czf - . 2>/tmp/up.err \
        | age -R "$RECIPIENTS_FILE" \
        | rclone rcat "$up_object"; then
        # Ta sama bramka co przy Postgresie: zerwany potok, którego rclone
        # przyjmie jako obiekt zerowej długości, bez tego zapisałby się jako
        # "ok" i spełnił warunek czystego przebiegu — a wtedy retencja
        # skasowałaby dobre stare kopie w noc, w którą nowa jest pusta.
        gate_and_record "uploads" "$up_object"
    else
        record "uploads" "error" 0 "$(tr -d '\n\"' </tmp/up.err | tail -c 200)"
    fi
else
    record "uploads" "error" 0 "upload dir ${UPLOADS_DIR} not mounted"
fi

# ── 3. Candidate CV corpus (object storage -> off-site) ──────────────────────
# The dataset with no second copy anywhere. After
# scripts/migrate_cvs_to_object_storage.py, `candidate_documents.file_content`
# is NULL and the bytes exist ONLY in the `OBJECT_STORAGE_BUCKET` S3 bucket;
# `pg_dump` therefore preserves nothing but `storage_key` -- rows pointing at
# files that would no longer exist. ~136k objects / ~37 GB.
#
# Mirrored incrementally rather than tarred: the objects are immutable, so after
# the first seeding run each night transfers only genuinely new CVs.
#
# `--backup-dir` instead of a plain sync: `rclone sync` propagates deletions,
# so a mistaken (or malicious) purge of the source bucket would erase the only
# off-site copy on the very next run. Replaced and deleted objects are moved
# into a dated `replaced/` prefix instead, which the normal retention pass ages
# out -- that also keeps GDPR erasure eventually effective on the backup.
#
# DELIBERATELY NOT `rclone crypt`. The other artefacts are age-encrypted because
# they are produced here; this one is copied between two buckets that already
# hold the files unencrypted at rest on the source side, so a client-side layer
# on the copy would not raise the real security floor -- it would only add a
# SECOND independent key whose loss silently costs us the last line of defence.
# The destination bucket is private with SSE-B2 at rest. This trade is argued in
# docs/disaster-recovery.md; do not "harden" it without reading that first.
cv_dest="${DEST}/candidate-documents/current"
cv_archive="${DEST}/candidate-documents/replaced/${DAY}"
CV_BUCKET="${OBJECT_STORAGE_BUCKET:-nexus-candidate-documents}"
if [ -z "${OBJECT_STORAGE_ENDPOINT:-}" ] || [ -z "${OBJECT_STORAGE_ACCESS_KEY:-}" ] \
    || [ -z "${OBJECT_STORAGE_SECRET_KEY:-}" ]; then
    # Recorded as a failure, never skipped: an unset variable silently dropping
    # the only irreplaceable dataset is precisely the bug being fixed here.
    record "cv_corpus" "error" 0 "OBJECT_STORAGE_* not configured — CV corpus NOT backed up" 0
else
    cv_rc=0
    # HEAD po wgraniu jest wyłączony globalnie — patrz RCLONE_S3_NO_HEAD wyżej.
    rclone sync "cvsrc:${CV_BUCKET}" "$cv_dest" \
        --backup-dir "$cv_archive" \
        --fast-list \
        --transfers "${BACKUP_CV_TRANSFERS:-8}" \
        --checkers "${BACKUP_CV_CHECKERS:-16}" \
        --max-duration "${BACKUP_CV_MAX_DURATION:-6h}" \
        --stats-one-line --stats 5m 2>/tmp/cv.err || cv_rc=$?
    if [ "$cv_rc" -eq 0 ]; then
        src_count="$(remote_count "cvsrc:${CV_BUCKET}")"
        dst_count="$(remote_count "$cv_dest")"
        dst_bytes="$(remote_size "$cv_dest")"
        # Counting is the real gate here, not bytes: a partial sync produces a
        # perfectly plausible multi-GB mirror that is missing thousands of CVs.
        if [ "$src_count" -eq 0 ]; then
            record "cv_corpus" "suspect" "$dst_bytes" \
                "source bucket ${CV_BUCKET} lists zero objects" "$dst_count"
        elif [ "$dst_count" -lt "$src_count" ]; then
            record "cv_corpus" "suspect" "$dst_bytes" \
                "mirror has ${dst_count} objects, source has ${src_count}" "$dst_count"
        else
            record "cv_corpus" "ok" "$dst_bytes" "" "$dst_count"
        fi
    elif [ "$cv_rc" -eq 10 ]; then
        # rclone exit 10 = "max duration reached". Still a failure: an
        # incomplete corpus must not read as a clean night, and retention must
        # stay blocked. Named separately because this is the EXPECTED outcome of
        # the first seeding run (~37 GB) and would otherwise look like a broken
        # pipeline. Progress is kept; the next run resumes where this stopped.
        record "cv_corpus" "error" 0 \
            "max duration ${BACKUP_CV_MAX_DURATION:-6h} reached — mirror incomplete, resumes next run" 0
    else
        record "cv_corpus" "error" 0 "$(tr -d '\n\"' </tmp/cv.err | tail -c 200)" 0
    fi
fi

# ── 4. Qdrant ────────────────────────────────────────────────────────────────
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
            | age -R "$RECIPIENTS_FILE" \
            | rclone rcat "$q_object"; then
            # Same gate as postgres/uploads. Without it `remote_size` returning
            # 0 for an object that never arrived (or for a failed `rclone size`)
            # was recorded as `ok` with `bytes: 0` — a clean run on paper, which
            # then also unblocked retention.
            gate_and_record "qdrant:${c}" "$q_object"
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

# ── 5. Retention ─────────────────────────────────────────────────────────────
# Pruning runs only when every artefact succeeded. Deleting old good backups on
# a night when the new ones failed is how a backup system turns into a data-loss
# system.
#
# `--exclude` on the mirror: objects under `candidate-documents/current` are the
# live copy of an immutable corpus, not dated snapshots. Ageing them out by
# mtime would delete every CV older than the retention window — the mirror would
# quietly erode into uselessness. Only the dated `replaced/` quarantine and the
# per-day snapshot prefixes are pruned.
if [ "$FAILURES" -eq 0 ]; then
    if rclone delete "$DEST" --min-age "${RETENTION_DAYS}d" \
        --exclude "/candidate-documents/current/**" 2>/dev/null; then
        rclone rmdirs "$DEST" --leave-root 2>/dev/null || true
        echo "[backup] retention: removed objects older than ${RETENTION_DAYS}d"
    else
        echo "[backup] WARNING: retention pass failed; old objects kept" >&2
    fi
else
    echo "[backup] retention SKIPPED — ${FAILURES} artefact(s) failed this run." >&2
fi

# ── 6. Manifest ──────────────────────────────────────────────────────────────
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

# The manifest upload used to be `|| echo WARNING` with no effect on the exit
# code. Now that `.github/workflows/uptime-probe.yml` alarms on the age and
# contents of this object, a manifest that never lands is indistinguishable from
# a backup service that stopped running -- and would raise that alarm anyway,
# hours later, with a misleading cause. Fail here instead, where the reason is
# still on screen.
if ! echo "$manifest" | rclone rcat "${DEST}/LATEST.json"; then
    echo "[backup] FAILED manifest: could not write ${DEST}/LATEST.json" >&2
    FAILURES=$((FAILURES + 1))
fi
echo "$manifest" | rclone rcat "${DEST}/history/${STAMP}.json" 2>/dev/null || true

echo "[backup] run complete: ${FAILURES} failure(s)"
[ "$FAILURES" -eq 0 ] || exit 1
