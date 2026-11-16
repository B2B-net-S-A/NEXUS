"""Skrypt hosta `scripts/host/nexus-backup-volume-status.sh` na atrapie `df`.

Cron z audytu 22.09 (PROD-01) nigdy nie trafił na host, więc `/api/health`
dawał `backupVolumePercent: null` do 16.11. Test sprawdza, że to, co zapisuje
skrypt, czyta `read_backup_volume`, i że odpięty wolumen (katalog na `/`)
nie udaje zajętości kopii.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.host_status import read_backup_volume

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "host" / "nexus-backup-volume-status.sh"
CRON = ROOT / "scripts" / "host" / "nexus-backup-volume.cron"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="brak sh")


def _fake_df(bin_dir: Path, line: str) -> None:
    df = bin_dir / "df"
    df.write_text(
        "#!/bin/sh\n"
        "echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
        f"echo '{line}'\n"
    )
    df.chmod(0o755)


def _run(tmp_path: Path, df_line: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_df(bin_dir, df_line)
    backups = tmp_path / "backups-target"
    backups.mkdir()
    link = tmp_path / "var-backups"
    link.symlink_to(backups)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "NEXUS_BACKUP_PATH": str(link),
        "NEXUS_STATUS_DIR": str(tmp_path / "status"),
    }
    return subprocess.run(
        ["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10
    )


def test_writes_status_that_health_reads(tmp_path):
    # Odczyt z 16.11: 197 GB, 136 GB zajęte, 53 GB wolne, 73%.
    res = _run(
        tmp_path,
        "/dev/sdb 206292664 142606336 55574528 73% /mnt/HC_Volume_1",
    )
    assert res.returncode == 0, res.stderr
    out = tmp_path / "status" / "backup-volume.json"
    raw = json.loads(out.read_text())
    assert raw["used_percent"] == 73
    assert raw["avail_gb"] == 53.0
    assert raw["mount"] == "/mnt/HC_Volume_1"
    assert stat.S_IMODE(out.stat().st_mode) == 0o644
    assert not list((tmp_path / "status").glob(".backup-volume.*"))

    percent, checked = read_backup_volume(
        tmp_path / "status", now=datetime.now(timezone.utc)
    )
    assert percent == 73
    assert checked is not None


@pytest.mark.parametrize(
    "df_line",
    [
        "/dev/sda1 76000000 40000000 33000000 55% /",
        "/dev/sdb 206292664 142606336 - - /mnt/HC_Volume_1",
    ],
    ids=["volume-detached-falls-on-root", "unreadable-df"],
)
def test_refuses_and_keeps_old_file(tmp_path, df_line):
    status = tmp_path / "status"
    status.mkdir()
    old = '{"used_percent": 40, "avail_gb": 100.0, "checked_at": "2026-11-16T00:00:00Z"}\n'
    (status / "backup-volume.json").write_text(old)
    res = _run(tmp_path, df_line)
    assert res.returncode != 0
    assert (status / "backup-volume.json").read_text() == old


def test_cron_runs_the_installed_script_every_15_minutes():
    lines = [
        ln for ln in CRON.read_text().splitlines() if ln and not ln.startswith("#")
    ]
    job = [ln for ln in lines if "nexus-backup-volume-status.sh" in ln]
    assert job and job[0].startswith("*/15 * * * * root /usr/local/sbin/")
