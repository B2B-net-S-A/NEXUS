"""Reguła skipowania live-server nie może łapać in-process testów.

``pytest_collection_modifyitems`` w ``tests/conftest.py`` wycisza legacy testy,
które wymagają uvicorna na :8000. Dopóki rozpoznawał je po samej NAZWIE
fixture'a (``client``), łapał też pliki, które nadpisują ``client`` lokalnie
transportem ASGI — nie potrzebują żadnego serwera. Tak zniknął z CI cały
``test_dynareporter_readonly.py``: 6 testów oznaczanych SKIPPED przy każdym
biegu, pytest kończył z kodem 0, a kontrakt pokrycia tego nie widział, bo
audytuje wyłącznie listę ``--ignore``, nigdy skipów w runtime.

Regresja tutaj byłaby CICHA (zielone CI, zero wykonanego pokrycia blokady
zapisu ``DYNAREPORTER_MODE=read_only``), więc pilnujemy jej dwoma poziomami:
jednostkowo predykatu i realnym biegiem pliku, który był ofiarą.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import _client_fixture_is_live_server


class _FixtureDef:
    def __init__(self, baseid: str | None) -> None:
        self.baseid = baseid


class _Item:
    def __init__(self, fixturenames, defs=None, with_info=True) -> None:
        self.fixturenames = fixturenames
        if with_info:
            self._fixtureinfo = type(
                "_Info", (), {"name2fixturedefs": {"client": defs} if defs else {}}
            )()


def test_local_asgi_override_is_not_treated_as_live_server():
    """Fixture zdefiniowany w PLIKU testowym → in-process, nie skipujemy."""
    item = _Item(("client",), [_FixtureDef("tests/test_dynareporter_readonly.py")])
    assert _client_fixture_is_live_server(item) is False


def test_conftest_fixture_is_still_treated_as_live_server():
    """Fixture z conftestu jest przypięty do KATALOGU — to legacy live-server."""
    item = _Item(("client",), [_FixtureDef("tests")])
    assert _client_fixture_is_live_server(item) is True


def test_app_client_wins_over_client():
    item = _Item(("client", "app_client"), [_FixtureDef("tests")])
    assert _client_fixture_is_live_server(item) is False


@pytest.mark.parametrize(
    "item",
    [
        _Item(("client",), defs=None),
        _Item(("client",), [_FixtureDef(None)]),
        _Item(("client",), with_info=False),
    ],
)
def test_unknown_definition_falls_back_to_skipping(item):
    """Bez introspekcji wracamy do starego zachowania.

    Fałszywy skip jest cichy, ale fałszywe URUCHOMIENIE 31 live-serverowych
    testów bez serwera zamieniłoby CI w czerwień na wszystkich PR-ach.
    """
    assert _client_fixture_is_live_server(item) is True


def test_dynareporter_readonly_suite_actually_runs():
    """Realny bieg pliku, który przez tę heurystykę wypadł z CI.

    Asercje jednostkowe wyżej sprawdzają predykat; ta sprawdza SKUTEK — że
    testy blokady zapisu DynaReportera faktycznie się wykonują, a nie tylko
    zbierają. Bez niej powrót do dopasowania po nazwie znowu przeszedłby
    niezauważony (SKIPPED nie psuje kodu wyjścia).
    """
    backend_root = Path(__file__).resolve().parents[1]
    # CI dzieli suite na 4 shardy przez CI_SHARD_COUNT/CI_SHARD_INDEX. Te
    # zmienne dziedziczy podproces, a przy JEDNYM pliku w kolekcji trzy z
    # czterech shardów nie dostają nic — `_apply_ci_shard_filter` podnosi
    # wtedy UsageError. Bez tego nadpisania ten test byłby czerwony w trzech
    # shardach na cztery, i to z powodu, który nie ma nic wspólnego z tym,
    # czego pilnuje.
    env = {**os.environ, "CI_SHARD_COUNT": "1", "CI_SHARD_INDEX": "0"}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_dynareporter_readonly.py",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=backend_root,
        capture_output=True,
        text=True,
        env=env,
    )
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr
    assert proc.returncode == 0, tail
    assert "passed" in tail, tail
    assert "skipped" not in tail, tail
