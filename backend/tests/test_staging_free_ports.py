"""`scripts/staging/free_ports.py`: pierwsza wolna para portów frontu i backendu gałęzi."""

import importlib.util
from pathlib import Path
import socket
import sys

spec = importlib.util.spec_from_file_location(
    "free_ports", Path(__file__).resolve().parents[2] / "scripts/staging/free_ports.py"
)
fp = importlib.util.module_from_spec(spec)
sys.modules["free_ports"] = fp
spec.loader.exec_module(fp)


def test_first_pair_when_all_free():
    assert fp.free_pair(lambda p: True) == (3101, 8101)


def test_skips_pair_when_front_or_backend_taken():
    taken = {3101, 8102}
    assert fp.free_pair(lambda p: p not in taken) == (3103, 8103)


def test_none_when_everything_taken():
    assert fp.free_pair(lambda p: False) is None


def test_is_free_sees_listening_socket():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert not fp.is_free(s.getsockname()[1])


def test_skips_pair_with_branch_database_or_container():
    """26.11.2026: sesja kopiowała bazę do nexus_branch_8104, zanim zajęła port,
    a następna dostała 8104 i jej migracja czekała na blokadę za pg_dump."""
    busy = fp.ports_from_names(
        [
            "nexus_branch_8101",
            "nexus-staging-backend-branch-8102",
            "nexus_branch_s4",
            "nexus",
        ]
    )
    assert busy == {8101, 8102}
    assert fp.free_pair(lambda p: True, busy) == (3103, 8103)


def test_without_docker_only_sockets_count(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(fp.subprocess, "run", missing)
    assert fp.staging_busy() == frozenset()


def test_failed_command_counts_as_nothing_busy(monkeypatch):
    class Failed:
        returncode, stdout = 1, "nexus_branch_8101\n"

    monkeypatch.setattr(fp.subprocess, "run", lambda *a, **k: Failed())
    assert fp.staging_busy() == frozenset()
