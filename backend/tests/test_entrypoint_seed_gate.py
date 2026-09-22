"""PROD-08 (audyt 22.09 r2): dane demo z seed.py tylko przy NEXUS_DEMO_SEED=true."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = BACKEND / "entrypoint.sh"


def _seed_block() -> str:
    text = ENTRYPOINT.read_text()
    start = text.index('startup_phase "seed"')
    end = text.index("startup_phase", start + 1)
    return text[start:end]


def test_entrypoint_runs_seed_only_behind_the_flag():
    block = _seed_block()
    assert 'if [ "${NEXUS_DEMO_SEED:-false}" = "true" ]; then' in block
    assert "python seed.py" in block
    # Żadne wywołanie seed.py poza bramką.
    text = ENTRYPOINT.read_text()
    assert len(re.findall(r"^\s*python seed\.py", text, re.M)) == 1


@pytest.mark.parametrize(("flag", "runs"), [(None, False), ("false", False), ("true", True)])
def test_seed_block_obeys_the_flag_in_bash(tmp_path, flag, runs):
    block = _seed_block().replace('startup_phase "seed"', "")
    script = tmp_path / "gate.sh"
    script.write_text(
        "set -e\npython() { echo RAN-SEED; }\n" + block,
    )
    env = {"PATH": "/usr/bin:/bin"}
    if flag is not None:
        env["NEXUS_DEMO_SEED"] = flag
    out = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=env, check=True
    ).stdout
    assert ("RAN-SEED" in out) is runs
    if not runs:
        assert "seed skipped" in out


async def test_seed_functions_return_without_the_flag(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("nexus_seed", BACKEND / "seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def _explode(*args, **kwargs):  # pragma: no cover - nie może zostać wywołane
        raise AssertionError("seed dotknął bazy bez NEXUS_DEMO_SEED")

    monkeypatch.delenv("NEXUS_DEMO_SEED", raising=False)
    monkeypatch.setattr(module, "create_async_engine", _explode)
    assert module.demo_seed_enabled() is False
    await module.seed()
    await module.seed_extended()
    monkeypatch.setenv("NEXUS_DEMO_SEED", "true")
    assert module.demo_seed_enabled() is True
