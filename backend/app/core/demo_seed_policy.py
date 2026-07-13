"""Fail-closed policy for login-capable demo seed data."""

import os
from typing import Optional


def _is_truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


def require_demo_seed_configuration() -> tuple[str, str]:
    """Return env-provided passwords only for an explicitly enabled dev seed."""
    if not _is_truthy(os.environ.get("NEXUS_ENABLE_DEMO_SEED")):
        raise RuntimeError(
            "Demo seed is disabled. Set NEXUS_ENABLE_DEMO_SEED=true only for "
            "an isolated development database."
        )
    if not _is_truthy(os.environ.get("DEBUG")):
        raise RuntimeError(
            "Refusing to seed demo users while DEBUG is false (production mode)."
        )

    admin_password = os.environ.get("NEXUS_DEMO_ADMIN_PASSWORD", "")
    staff_password = os.environ.get("NEXUS_DEMO_STAFF_PASSWORD", "")
    missing = [
        name
        for name, value in (
            ("NEXUS_DEMO_ADMIN_PASSWORD", admin_password),
            ("NEXUS_DEMO_STAFF_PASSWORD", staff_password),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Demo seed requires password secrets from the environment: "
            + ", ".join(missing)
        )
    if len(admin_password) < 16 or len(staff_password) < 16:
        raise RuntimeError("Demo seed passwords must each be at least 16 characters.")
    if admin_password == staff_password:
        raise RuntimeError("Demo admin and staff passwords must be different.")

    return admin_password, staff_password
