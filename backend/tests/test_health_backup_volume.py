"""Audyt 22.09 r2 (PROD-01): zajętość wolumenu kopii w `/api/health`.

Wolumen kopii (98 GB) zapełniał się bez niczyjej wiedzy — `diskPercent`
widzi tylko `/`. Cron hosta zapisuje `backup-volume.json` do katalogu
montowanego read-only; plik starszy niż 2 h = `null` (nie fałszywe zero).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.services.host_status import read_backup_volume

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


def _write(tmp_path, **payload):
    (tmp_path / "backup-volume.json").write_text(json.dumps(payload))


def test_fresh_status_gives_the_percent(tmp_path):
    _write(
        tmp_path, used_percent=48.4, avail_gb=51.2, checked_at="2026-09-22T11:45:00Z"
    )
    percent, checked = read_backup_volume(tmp_path, now=NOW)
    assert percent == 48
    assert checked == "2026-09-22T11:45:00+00:00"


def test_stale_status_gives_null_not_zero(tmp_path):
    _write(
        tmp_path,
        used_percent=97,
        checked_at=(NOW - timedelta(hours=3)).isoformat(),
    )
    percent, checked = read_backup_volume(tmp_path, now=NOW)
    assert percent is None
    assert checked is not None


@pytest.mark.parametrize(
    "content", ["", "not json", "[]", json.dumps({"used_percent": "x"})]
)
def test_missing_or_broken_file_is_null(tmp_path, content):
    if content:
        (tmp_path / "backup-volume.json").write_text(content)
    assert read_backup_volume(tmp_path, now=NOW)[0] is None


@pytest.mark.asyncio
async def test_health_exposes_backup_volume_percent(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.main import app

    _write(
        tmp_path,
        used_percent=81,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
    monkeypatch.setattr(settings, "HOST_STATUS_DIR", str(tmp_path))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = (await client.get("/api/health")).json()
    assert body["backupVolumePercent"] == 81
    assert body["backupVolumeCheckedAt"]


def test_compose_mounts_only_the_status_directory_read_only():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "- /var/lib/nexus-status:/run/nexus-host-status:ro" in compose
