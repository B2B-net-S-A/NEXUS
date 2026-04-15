#!/bin/bash
set -e

export PYTHONPATH=/app:${PYTHONPATH}

echo "=== DynaMinds ATS Backend Starting ==="

# Wait for postgres to be ready
echo "Waiting for database..."
until python -c "
import asyncio, asyncpg, os

async def check():
    url = os.environ.get('DATABASE_URL', 'postgresql+asyncpg://dynaminds:dynaminds@postgres:5432/dynaminds')
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
alembic -c alembic/alembic.ini upgrade head

# Run seed (idempotent - skips if already seeded)
echo "Running seed data..."
python seed.py

# Start the application
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
