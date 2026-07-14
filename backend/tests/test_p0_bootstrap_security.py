"""P0 regression tests for startup credentials and account quarantine."""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient

try:
    import tomllib
except ModuleNotFoundError:  # Python <3.11 local tooling; CI uses Python 3.12.
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def _gitleaks_config() -> dict:
    with (REPO_ROOT / ".gitleaks.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_production_entrypoint_has_no_unconditional_user_seed() -> None:
    entrypoint_path = BACKEND_ROOT / "entrypoint.sh"
    entrypoint = entrypoint_path.read_text()

    subprocess.run(["sh", "-n", str(entrypoint_path)], check=True)
    assert not (BACKEND_ROOT / "scripts" / "ensure_claude_admin.py").exists()
    assert "ensure_claude_admin" not in entrypoint
    assert "CLAUDE_ADMIN_BOOTSTRAP" not in entrypoint
    assert "claude-admin@" not in entrypoint

    enable_guard = entrypoint.index('case "${NEXUS_ENABLE_DEMO_SEED:-false}"')
    production_guard = entrypoint.index('case "${DEBUG:-false}"', enable_guard)
    migration_gate = entrypoint.index("python -m scripts.assert_migration_head")
    seed_call = entrypoint.index("python seed.py", production_guard)
    assert enable_guard < production_guard < migration_gate < seed_call
    assert "NEXUS_ENABLE_DEMO_SEED is enabled while DEBUG is false" in entrypoint
    assert "NEXUS_DEMO_ADMIN_PASSWORD" in entrypoint[:migration_gate]
    assert "NEXUS_DEMO_STAFF_PASSWORD" in entrypoint[:migration_gate]

    # Application startup is schema-read-only and must never create, reactivate,
    # demote, or otherwise mutate login identities. Demo users are created only
    # inside seed.py after the explicit development-only guard.
    user_dml = re.compile(
        r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+users\b",
        re.IGNORECASE,
    )
    assert not user_dml.search(entrypoint)


def test_entrypoint_rejects_production_seed_before_database_access() -> None:
    if os.geteuid() == 0:
        pytest.skip("entrypoint root path performs the Docker privilege handoff")

    env = os.environ.copy()
    env.update(
        {
            "DEBUG": "false",
            "NEXUS_ENABLE_DEMO_SEED": "true",
            "NEXUS_DEMO_ADMIN_PASSWORD": "UniqueAdminPassword-123",
            "NEXUS_DEMO_STAFF_PASSWORD": "UniqueStaffPassword-456",
        }
    )
    result = subprocess.run(
        ["bash", str(BACKEND_ROOT / "entrypoint.sh")],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 64
    assert "refusing to seed a production database" in output
    assert "migration gate" not in output.lower()


def test_demo_seed_rejects_production_even_when_opted_in(monkeypatch) -> None:
    from app.core.demo_seed_policy import require_demo_seed_configuration

    monkeypatch.setenv("NEXUS_ENABLE_DEMO_SEED", "true")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("NEXUS_DEMO_ADMIN_PASSWORD", "UniqueAdminPassword-123")
    monkeypatch.setenv("NEXUS_DEMO_STAFF_PASSWORD", "UniqueStaffPassword-456")

    with pytest.raises(RuntimeError, match="production mode"):
        require_demo_seed_configuration()


def test_demo_seed_requires_environment_passwords(monkeypatch) -> None:
    from app.core.demo_seed_policy import require_demo_seed_configuration

    monkeypatch.setenv("NEXUS_ENABLE_DEMO_SEED", "true")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.delenv("NEXUS_DEMO_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("NEXUS_DEMO_STAFF_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="requires password secrets"):
        require_demo_seed_configuration()


def test_demo_seed_accepts_distinct_env_passwords_in_development(monkeypatch) -> None:
    from app.core.demo_seed_policy import require_demo_seed_configuration

    monkeypatch.setenv("NEXUS_ENABLE_DEMO_SEED", "true")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("NEXUS_DEMO_ADMIN_PASSWORD", "UniqueAdminPassword-123")
    monkeypatch.setenv("NEXUS_DEMO_STAFF_PASSWORD", "UniqueStaffPassword-456")

    assert require_demo_seed_configuration() == (
        "UniqueAdminPassword-123",
        "UniqueStaffPassword-456",
    )


def test_gitleaks_detects_literal_demo_seed_password() -> None:
    config = _gitleaks_config()
    rule = next(
        item for item in config["rules"] if item["id"] == "demo-seed-literal-password"
    )

    assert re.search(rule["path"], "backend/seed_compromised.py")
    literal = '"password": "SyntheticCommittedPassword-123"'
    environment_value = '"password": staff_password'
    assert re.search(rule["regex"], literal)
    assert not re.search(rule["regex"], environment_value)
    assert not re.search(rule["regex"], (BACKEND_ROOT / "seed.py").read_text())


def test_gitleaks_detects_literal_bootstrap_password() -> None:
    config = _gitleaks_config()
    rule = next(
        item for item in config["rules"] if item["id"] == "hardcoded-bootstrap-password"
    )
    variable_name = "_DEFAULT_" + "BOOTSTRAP_PASSWORD"
    synthetic_value = "SyntheticCommittedPassword-123"
    assert re.search(
        rule["regex"],
        f'{variable_name} = "{synthetic_value}"',
    )


def test_gitleaks_has_no_broad_source_path_allowlist() -> None:
    config = _gitleaks_config()
    assert "paths" not in config.get("allowlist", {})

    for rule in config["rules"]:
        for allowlist in rule.get("allowlists", []):
            assert "paths" not in allowlist


def test_gitleaks_history_baseline_is_exact_and_limited() -> None:
    entries = [
        line.strip()
        for line in (REPO_ROOT / ".gitleaksignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    fingerprint = re.compile(
        r"^[0-9a-f]{40}:[^:]+:(?:hardcoded-bootstrap-password|"
        r"demo-seed-literal-password):[0-9]+$"
    )
    assert entries == [
        "4714a91b55bb03c69b649ad547656fe05416d904:"
        "backend/scripts/ensure_claude_admin.py:"
        "hardcoded-bootstrap-password:36"
    ]
    assert all(fingerprint.fullmatch(entry) for entry in entries)


def test_quarantine_sql_is_fail_closed_and_preserves_identity() -> None:
    sql = (
        REPO_ROOT / "docs" / "ops" / "security" / "quarantine-bootstrap-admin.sql"
    ).read_text()
    assert "\\set ON_ERROR_STOP on" in sql
    assert "original_count + quarantine_count <> 1" in sql
    assert "FOR UPDATE" in sql
    assert "password_hash = NULL" in sql
    assert "is_active = false" in sql
    assert "role = 'user'::userrole" in sql
    assert "WHERE id = target_user.id" in sql
    assert "DELETE FROM users" not in sql.upper()
    assert "COMMIT;" in sql


@pytest_asyncio.fixture
async def quarantine_test_user() -> AsyncIterator[dict[str, object]]:
    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.activity import Activity
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex
    email = f"pytest-p0-{unique}@example.com"
    password = f"P0_PreQuarantine_{unique}!"

    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="P0 Quarantine Test",
            role=UserRole.admin,
            roles=[UserRole.admin.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    yield {"id": user_id, "email": email, "password": password}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Activity).where(Activity.user_id == user_id))
        user = await db.scalar(select(User).where(User.id == user_id))
        if user is not None:
            await db.delete(user)
        await db.commit()


@pytest.mark.asyncio
async def test_deactivation_invalidates_login_access_and_refresh(
    app_client: AsyncClient,
    quarantine_test_user: dict[str, object],
) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token, create_refresh_token
    from app.models.user import User, UserRole

    user_id = int(quarantine_test_user["id"])
    email = str(quarantine_test_user["email"])
    password = str(quarantine_test_user["password"])
    access_token = create_access_token(user_id, UserRole.admin.value)
    refresh_token = create_refresh_token(user_id)

    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.id == user_id))
        assert user is not None
        user.is_active = False
        user.password_hash = None
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    access = await app_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    refresh = await app_client.post(
        "/api/auth/refresh", params={"refresh_token": refresh_token}
    )

    assert login.status_code == 401
    assert access.status_code == 401
    assert refresh.status_code == 401
