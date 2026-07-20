"""Safety contract for the off-site backup sidecar (`backup` in compose).

This service is unusual in that it reads every dataset NEXUS holds — the
database, the candidate CV files and the vector store — and ships them off the
host. That makes a handful of its properties load-bearing for security and for
not repeating past outages, and none of them are enforced by anything else.

Pinning them here rather than trusting review, because each has a plausible
"harmless" edit that quietly breaks it: dropping `:ro` while debugging a
permissions problem, defaulting the kill-switch to true to "make it work", or
pasting a real key while testing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _backup_service() -> dict:
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    services = compose.get("services") or {}
    assert "backup" in services, "the backup sidecar is missing from docker-compose.yml"
    return services["backup"]


def test_data_volumes_are_mounted_read_only() -> None:
    """The sidecar reads application data; it must never be able to write it."""
    volumes = _backup_service().get("volumes") or []
    # Without this the test passes vacuously when the `volumes:` block is
    # deleted altogether: the loop below simply never runs, and the mount it
    # exists to protect is gone while CI stays green.
    assert volumes, (
        "the backup service declares no volume mounts — uploads_data must be "
        "mounted read-only, or the CV files are not being backed up at all"
    )
    for volume in volumes:
        # Only string short-syntax mounts are used here.
        assert isinstance(volume, str), f"unexpected mount syntax: {volume!r}"
        assert volume.endswith(":ro"), (
            f"backup mount {volume!r} is writable. This container exists to read "
            "data, and a write-capable mount turns a backup bug into data loss."
        )


def test_kill_switch_defaults_to_disabled() -> None:
    """Shipping enabled-by-default would start shipping PII off-host on merge."""
    env = _backup_service().get("environment") or {}
    enabled = str(env.get("BACKUP_ENABLED", ""))
    assert "false" in enabled, (
        "BACKUP_ENABLED must default to false. Candidate personal data leaves "
        f"the host when this is on; got {enabled!r}."
    )


def test_no_credentials_are_hardcoded() -> None:
    """Every secret must come from the environment, never from the file."""
    env = _backup_service().get("environment") or {}
    for key in (
        "BACKUP_S3_ACCESS_KEY",
        "BACKUP_S3_SECRET_KEY",
        "BACKUP_AGE_PUBLIC_KEY",
        "POSTGRES_PASSWORD",
    ):
        value = str(env.get(key, ""))
        assert value.startswith("${"), (
            f"{key} must be an env substitution, got {value!r} — a literal here "
            "would be committed to the repository."
        )


def test_backup_does_not_publish_ports() -> None:
    """Nothing about this service should be reachable from outside."""
    service = _backup_service()
    assert not service.get("ports"), (
        "the backup sidecar must not publish ports; it initiates outbound "
        "connections only."
    )


def test_scripts_refuse_to_run_without_configuration() -> None:
    """The script must fail closed on missing config, not back up to nowhere."""
    script = (_COMPOSE.parent / "backup" / "backup.sh").read_text(encoding="utf-8")
    for required in (
        "BACKUP_AGE_PUBLIC_KEY",
        "BACKUP_S3_BUCKET",
        "BACKUP_S3_ENDPOINT",
        "BACKUP_S3_ACCESS_KEY",
        "BACKUP_S3_SECRET_KEY",
    ):
        assert f'[ -n "${{{required}:-}}" ] || fail' in script, (
            f"backup.sh must hard-fail when {required} is unset — silently "
            "skipping configuration is how a backup job ends up writing nothing."
        )


def test_retention_is_gated_on_a_clean_run() -> None:
    """Never delete old backups on a night the new ones failed."""
    script = (_COMPOSE.parent / "backup" / "backup.sh").read_text(encoding="utf-8")
    assert 'if [ "$FAILURES" -eq 0 ]; then' in script, (
        "retention must be conditional on zero failures, otherwise a failing "
        "run prunes the last known-good backups and turns this into a "
        "data-loss system."
    )
