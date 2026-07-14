#!/bin/sh
set -eu

APP_ROOT="${NEXUS_APP_ROOT:-/app}"
UPLOAD_ROOT="${NEXUS_UPLOAD_ROOT:-/tmp/nexus}"

# The container starts as root only to repair ownership on a legacy named
# volume. The application and the explicit migration command both execute as
# the fixed unprivileged UID afterwards.
if [ "$(id -u)" = "0" ]; then
    mkdir -p \
        "$UPLOAD_ROOT/uploads/microsoft365" \
        "$UPLOAD_ROOT/uploads/client_framework_contracts" \
        "$UPLOAD_ROOT/uploads/candidate_documents"
    chown -R appuser:appgroup "$UPLOAD_ROOT"
    exec su-exec appuser:appgroup "$0" "$@"
fi

export PYTHONPATH="$APP_ROOT:${PYTHONPATH:-}"
cd "$APP_ROOT"

case "${1:-serve}" in
    migrate)
        exec "$APP_ROOT/migrate.sh"
        ;;
    serve)
        ;;
    *)
        echo "ERROR: expected entrypoint mode 'serve' or 'migrate'." >&2
        exit 64
        ;;
esac

# Demo data remains an explicit development-only operation. The seed assumes
# an already migrated database and has no schema-creation fallback.
DEMO_SEED_ENABLED=false
case "${NEXUS_ENABLE_DEMO_SEED:-false}" in
    1|true|TRUE|yes|YES)
        case "${DEBUG:-false}" in
            1|true|TRUE|yes|YES)
                if [ -z "${NEXUS_DEMO_ADMIN_PASSWORD:-}" ] || [ -z "${NEXUS_DEMO_STAFF_PASSWORD:-}" ]; then
                    echo "ERROR: demo seed requires NEXUS_DEMO_ADMIN_PASSWORD and NEXUS_DEMO_STAFF_PASSWORD." >&2
                    exit 64
                fi
                DEMO_SEED_ENABLED=true
                ;;
            *)
                echo "ERROR: NEXUS_ENABLE_DEMO_SEED is enabled while DEBUG is false; refusing to seed a production database." >&2
                exit 64
                ;;
        esac
        ;;
    0|false|FALSE|no|NO|"")
        ;;
    *)
        echo "ERROR: NEXUS_ENABLE_DEMO_SEED must be a boolean value." >&2
        exit 64
        ;;
esac

# Serving is read-only with respect to schema. A bounded, read-only revision
# gate refuses to launch uvicorn until the database is at the repository's
# single Alembic head. It never upgrades or stamps the database.
MIGRATION_GATE_ATTEMPTS="${NEXUS_MIGRATION_GATE_ATTEMPTS:-30}"
case "$MIGRATION_GATE_ATTEMPTS" in
    *[!0-9]*|0|"")
        echo "ERROR: NEXUS_MIGRATION_GATE_ATTEMPTS must be a positive integer." >&2
        exit 64
        ;;
esac

attempt=1
while ! python -m scripts.assert_migration_head; do
    if [ "$attempt" -ge "$MIGRATION_GATE_ATTEMPTS" ]; then
        echo "ERROR: database migration gate did not pass; refusing to serve." >&2
        exit 70
    fi
    echo "Database unavailable or not at Alembic head; retrying in 2s..." >&2
    attempt=$((attempt + 1))
    sleep 2
done

# Operational recovery only: a killed M365 sync leaves a data-state lease in
# `running`. This script performs no DDL and is safe to skip; the sync worker
# can recover on a later restart/manual retry.
python scripts/reset_interrupted_m365_sync.py \
    || echo "WARN: interrupted M365 sync reset failed; continuing." >&2

if [ "$DEMO_SEED_ENABLED" = true ]; then
    python seed.py
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
