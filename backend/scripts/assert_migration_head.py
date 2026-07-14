"""Read-only startup gate: require exactly one applied Alembic head."""

from __future__ import annotations

import asyncio
import sys

from app.core.migration_gate import require_current_migration_head


def main() -> int:
    try:
        asyncio.run(require_current_migration_head())
    except Exception as exc:  # noqa: BLE001 - CLI boundary must fail closed
        print(f"migration gate failed: {exc}", file=sys.stderr)
        return 1
    print("database migration gate: current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
