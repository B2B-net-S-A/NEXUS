#!/bin/bash
set -e

export PYTHONPATH=/app:${PYTHONPATH}

echo "=== Nexus ATS Backend Starting ==="

# Wait for postgres to be ready
echo "Waiting for database..."
until python -c "
import asyncio, asyncpg, os

async def check():
    url = os.environ.get('DATABASE_URL', 'postgresql+asyncpg://nexus:nexus@postgres:5432/nexus')
    url = url.replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    await conn.close()
    print('Database ready!')

asyncio.run(check())
" 2>/dev/null; do
    echo "Database not ready, retrying in 2s..."
    sleep 2
done

# Run migrations
# The alembic.ini lives in /app/alembic/ but script_location=alembic points to /app/alembic
# Run from /app so that 'alembic' dir is found correctly
echo "Running database migrations..."
cd /app
# Tolerate alembic failures in dev: multiple in-flight feature branches can
# produce duplicate-revision or multi-head states. In DEBUG mode the app
# falls back to Base.metadata.create_all() on startup, so tables still exist.
# Production should never hit this path (clean single-head chain on main).
alembic -c alembic/alembic.ini upgrade heads 2>&1 || echo "alembic upgrade failed (likely multi-head in dev); continuing via Base.metadata.create_all"

# Run seed (idempotent - skips if already seeded)
echo "Running seed data..."
python seed.py || echo "seed.py failed (likely pre-existing schema drift from unmerged branches); continuing"

# Ensure the dedicated Claude E2E admin account exists on every startup.
# Idempotent upsert — rotates password to the bootstrap value each boot unless
# CLAUDE_ADMIN_BOOTSTRAP_PWD is set in env. Non-fatal.
echo "Ensuring Claude admin account..."
python scripts/ensure_claude_admin.py || echo "ensure_claude_admin failed; continuing"

# Start the application
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
