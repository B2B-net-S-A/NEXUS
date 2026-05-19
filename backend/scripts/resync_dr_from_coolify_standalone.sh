#!/bin/bash
# DR → Nexus resync helper.
#
# Refreshes Nexus's `dr_*` tables from the DR Coolify standalone container
# running on the same Hetzner server. Used when DR data drifts (e.g. someone
# entered KPI on the legacy DR after Faza B cutover, and Nexus needs to catch up).
#
# Usage (run from host):
#   ssh root@<server> 'bash -s' < backend/scripts/resync_dr_from_coolify_standalone.sh
#
# Or manually:
#   ssh root@91.99.199.112
#   /path/to/resync_dr_from_coolify_standalone.sh
#
# Note: DR Coolify standalone (`postgres-wpal3b75*`) must be running. After
# the script, dr_* tables in Nexus reflect DR standalone's state (~99%
# alignment with DR Render — financial fields like `revenue` in
# `dr_board_monthly_report` are zero on standalone, only Render has them).
#
# The script:
#   1. pg_dumps DR standalone (--data-only --no-owner --no-privileges)
#   2. Copies dump into Nexus backend container
#   3. Temporarily edits Nexus users.dynareporter_legacy_id to enable mapping
#      for legacy DR users with email duplicates (9/12/18 → 185/182/167)
#   4. Runs migrate_dynareporter.py twice (with each legacy ID set) to load
#      ALL KPI rows including duplicate-user entries
#   5. Restores Nexus users.dynareporter_legacy_id to canonical (70/71/44)
#
# Idempotent — safe to re-run.

set -euo pipefail

PG_DR=$(docker ps --format '{{.Names}}' | grep '^postgres-wpal3b75' | head -1)
PG_NEXUS=$(docker ps --format '{{.Names}}' | grep '^postgres-ocgk' | head -1)
BACKEND=$(docker ps --format '{{.Names}}' | grep '^backend-ocgk' | head -1)

if [ -z "$PG_DR" ]; then
    echo "ERROR: DR standalone postgres (postgres-wpal3b75*) not running"
    exit 1
fi
if [ -z "$PG_NEXUS" ] || [ -z "$BACKEND" ]; then
    echo "ERROR: Nexus containers not running"
    exit 1
fi

echo "DR postgres:    $PG_DR"
echo "Nexus postgres: $PG_NEXUS"
echo "Nexus backend:  $BACKEND"

# Step 1: dump
DUMP_FILE="/tmp/dr-resync-$(date +%s).sql"
echo ""
echo "[1/5] Dumping DR Coolify standalone (data-only)…"
docker exec "$PG_DR" pg_dump -U dynareporter -d dynareporter \
    --data-only --no-owner --no-privileges > "$DUMP_FILE"
ls -lh "$DUMP_FILE"

# Step 2: copy into backend container
echo ""
echo "[2/5] Copying dump to backend container…"
docker cp "$DUMP_FILE" "$BACKEND:/tmp/dr-resync.sql"

# Step 3: extract Nexus DATABASE_URL → psycopg2 sync format
TARGET_DB=$(docker exec "$BACKEND" sh -c 'echo $DATABASE_URL' | sed 's|postgresql+asyncpg://|postgresql://|')

# Step 4: PASS 1 — set Nexus users.dynareporter_legacy_id to legacy DR ids
#         9 (Diana tac), 12 (Marlena tac), 18 (Patryk tac) so they get mapped.
echo ""
echo "[3/5] PASS 1: load with legacy_id={9,12,18}…"
docker exec "$PG_NEXUS" psql -U nexus -d nexus -c "
UPDATE users SET dynareporter_legacy_id = 9 WHERE id = 185;
UPDATE users SET dynareporter_legacy_id = 12 WHERE id = 182;
UPDATE users SET dynareporter_legacy_id = 18 WHERE id = 167;
"
docker exec "$BACKEND" python /app/scripts/migrate_dynareporter.py \
    --source-dump /tmp/dr-resync.sql --data-only --apply --reset \
    --target-db "$TARGET_DB" 2>&1 | grep -E 'inserted|WARN' | tail -5

# Step 5: PASS 2 — switch legacy_id to other duplicate (70/71/44) and re-run
#         (without --reset → ON CONFLICT DO NOTHING semantics merge them)
echo ""
echo "[4/5] PASS 2: load with legacy_id={70,71,44}…"
docker exec "$PG_NEXUS" psql -U nexus -d nexus -c "
UPDATE users SET dynareporter_legacy_id = 70 WHERE id = 185;
UPDATE users SET dynareporter_legacy_id = 71 WHERE id = 182;
UPDATE users SET dynareporter_legacy_id = 44 WHERE id = 167;
"
docker exec "$BACKEND" python /app/scripts/migrate_dynareporter.py \
    --source-dump /tmp/dr-resync.sql --data-only --apply \
    --target-db "$TARGET_DB" 2>&1 | grep -E 'inserted' | tail -5

# Step 6: sanity check
echo ""
echo "[5/5] Sanity check Maj 2026 KPI:"
docker exec "$PG_NEXUS" psql -U nexus -d nexus -tA -c "
SELECT
  'verif=' || COALESCE(SUM(verifications), 0) || ' rec=' || COALESCE(SUM(recommendations), 0) ||
  ' int=' || COALESCE(SUM(interviews), 0) || ' plac=' || COALESCE(SUM(placements), 0)
FROM dr_kpi_body_leasing
WHERE EXTRACT(YEAR FROM report_date)=2026 AND EXTRACT(MONTH FROM report_date)=5
"
echo ""
echo "Done. Dump kept at: $DUMP_FILE"
