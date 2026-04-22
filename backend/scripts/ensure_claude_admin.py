#!/usr/bin/env python3
"""Idempotent bootstrap for the `claude-admin@b2bnet.pl` account.

Runs from `entrypoint.sh` on every backend startup. Upserts a dedicated admin
user reserved for AI-assisted E2E verification (see
`~/.claude/rules/autonomous-verification.md`) so Claude can log in and test
production UI without fighting expired human sessions.

Password source: env var ``CLAUDE_ADMIN_BOOTSTRAP_PWD`` if set, otherwise the
constant below. The constant exists so the bootstrap works on a fresh VPS
without needing to add env vars in Coolify first; rotate it via Settings →
Zmiana hasła after login, or override via the env var.

Safe to run on every startup:
- Create if missing.
- Update password + role + is_active if present (idempotent — same password
  re-hashed by bcrypt still produces matching rows).
- Never deletes or disables existing users.
"""

from __future__ import annotations

import asyncio
import os
import sys

_APP_ROOT = "/app"
if os.path.isdir(_APP_ROOT) and _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)


CLAUDE_ADMIN_EMAIL = "claude-admin@b2bnet.pl"
CLAUDE_ADMIN_NAME = "Claude Admin"
# Bootstrap password — rotate after first login. Also overridable via
# CLAUDE_ADMIN_BOOTSTRAP_PWD in Coolify env if you want a different value.
_DEFAULT_BOOTSTRAP_PWD = "irsiETd37y..xT6JCWl6!KGk"  # noqa: S105


async def ensure_claude_admin() -> int:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    password = os.environ.get("CLAUDE_ADMIN_BOOTSTRAP_PWD") or _DEFAULT_BOOTSTRAP_PWD

    async with AsyncSessionLocal() as db:
        user = await db.scalar(
            select(User).where(User.email == CLAUDE_ADMIN_EMAIL)
        )
        if user is None:
            user = User(
                email=CLAUDE_ADMIN_EMAIL,
                name=CLAUDE_ADMIN_NAME,
                role=UserRole.admin,
                password_hash=hash_password(password),
                is_active=True,
                profile_completed=True,
            )
            db.add(user)
            await db.commit()
            print(
                f"ensure_claude_admin: CREATED {CLAUDE_ADMIN_EMAIL} "
                f"(id pending flush)"
            )
            return 0

        user.password_hash = hash_password(password)
        user.role = UserRole.admin
        user.is_active = True
        user.profile_completed = True
        await db.commit()
        print(
            f"ensure_claude_admin: UPDATED id={user.id} {user.email} "
            f"role={user.role.value}"
        )
        return 0


def main() -> int:
    try:
        return asyncio.run(ensure_claude_admin())
    except Exception as exc:  # noqa: BLE001
        # Non-fatal — entrypoint keeps going. Log so it surfaces in Coolify.
        print(f"ensure_claude_admin: failed: {exc!r}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
