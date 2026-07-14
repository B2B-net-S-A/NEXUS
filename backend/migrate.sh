#!/bin/sh
set -eu

APP_ROOT="${NEXUS_APP_ROOT:-/app}"
cd "$APP_ROOT"

# This is the only schema-changing runtime command. It is invoked as a
# one-shot job (`entrypoint.sh migrate`), never during application startup.
exec alembic -c alembic/alembic.ini upgrade head
