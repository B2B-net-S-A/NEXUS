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
