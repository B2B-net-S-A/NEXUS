"""Kroki jednorazowe w `entrypoint.sh` nie uruchamiają Pythona po znaczniku.

Pomiar z 02.11.2026: start backendu 170 s, z czego 42 kroki naprawcze 131 s.
Każdy to osobny proces Pythona z importem `app.models` (3–4 s) tylko po to, żeby
odczytać znacznik w `app_settings` i wyjść. API leży przez cały start, więc każda
kolejna naprawa wydłużała przerwę przy wdrożeniu (62 s we wrześniu, 245 s w listopadzie).

Funkcje są wycinane z PRAWDZIWEGO skryptu i uruchamiane w `bash` z podstawionym
`python`, test na kopii dowodziłby tylko kopii.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ENTRYPOINT = _ROOT / "entrypoint.sh"
_MARKED_CALL = re.compile(r"^run_unless_marked((?: \"[^\"]+\")+) <<'PY' \|\| echo ", re.M)
_ONE_SHOT_PHASE = re.compile(
    r"^(repair-|cleanup-|job-names-backfill$|working-title-prose-fix$"
    r"|client-reference-from-title$|stage-cv-copy-filenames$"
    r"|competence-categories-four$|seed-placement-exclusions$)"
)
# Po znaczniku dalej łapie kontrakty zapisane później starą ścieżką, więc ma
# działać przy każdym starcie (`contract_hourly_rate_repair.py`).
_RUNS_ON_EVERY_START = {"repair-contract-hourly-rates"}


def _phases() -> dict[str, str]:
    """Faza z `startup_phase "x"` → tekst skryptu do następnej fazy."""
    source = _ENTRYPOINT.read_text(encoding="utf-8")
    matches = list(re.finditer(r'^startup_phase "([^"]*)"$', source, re.M))
    return {
        match.group(1): source[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(source)
        ]
        for i, match in enumerate(matches)
    }


def _function(name: str) -> str:
    source = _ENTRYPOINT.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{.*?^\}}", source, re.S | re.M)
    assert match, f"nie znaleziono {name}() w entrypoint.sh"
    return match.group(0)


def _run(tmp_path: Path, markers: str | None, call: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "python"
    fake.write_text(
        '#!/bin/sh\necho "python ran"\ncat\nexit "${FAKE_PYTHON_RC:-0}"\n', encoding="utf-8"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    markers_file = tmp_path / "markers"
    if markers is not None:
        markers_file.write_text(markers, encoding="utf-8")
    script = "\n".join(
        ["set -e", f'REPAIR_MARKERS_FILE="{markers_file}"', _function("run_unless_marked"), call]
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )


_BLOCK = "run_unless_marked {} <<'PY' || echo \"fallback\"\nprint('body')\nPY\necho after"


def test_marker_present_skips_python_and_consumes_the_heredoc(tmp_path: Path) -> None:
    out = _run(tmp_path, "inne\n0306_x\n", _BLOCK.format('"0306_x"'))
    assert out.returncode == 0, out.stderr
    assert "python ran" not in out.stdout
    assert "print('body')" not in out.stdout
    assert out.stdout.splitlines()[-1] == "after"
    assert "fallback" not in out.stdout


def test_missing_marker_runs_the_block_as_before(tmp_path: Path) -> None:
    out = _run(tmp_path, "inne\n", _BLOCK.format('"0306_x"'))
    assert out.returncode == 0, out.stderr
    assert "python ran" in out.stdout
    assert "print('body')" in out.stdout


def test_marker_must_match_a_whole_line(tmp_path: Path) -> None:
    """`0306_x_details` nie może udawać znacznika `0306_x`."""
    out = _run(tmp_path, "0306_x_details\nprefix_0306_x\n", _BLOCK.format('"0306_x"'))
    assert "python ran" in out.stdout


def test_block_with_two_steps_needs_both_markers(tmp_path: Path) -> None:
    out = _run(tmp_path, "a\n", _BLOCK.format('"a" "b"'))
    assert "python ran" in out.stdout


def test_both_markers_present_skip_a_two_step_block(tmp_path: Path) -> None:
    out = _run(tmp_path, "a\nb\n", _BLOCK.format('"a" "b"'))
    assert "python ran" not in out.stdout


@pytest.mark.parametrize("markers", [None, ""])
def test_no_marker_list_runs_every_block(tmp_path: Path, markers: str | None) -> None:
    """Odczyt padł albo baza jest pusta: wszystko idzie jak przed tą zmianą."""
    out = _run(tmp_path, markers, _BLOCK.format('"0306_x"'))
    assert out.returncode == 0, out.stderr
    assert "python ran" in out.stdout


def test_failed_block_still_reaches_the_fallback(tmp_path: Path) -> None:
    script = _BLOCK.format('"0306_x"').replace("run_unless_marked", "FAKE_PYTHON_RC=3 run_unless_marked")
    out = _run(tmp_path, "", script)
    assert out.returncode == 0, out.stderr
    assert "fallback" in out.stdout
    assert out.stdout.splitlines()[-1] == "after"


def test_every_one_shot_phase_is_gated_by_its_marker() -> None:
    """Nowa naprawa bez znacznika to kolejne 3–4 s przerwy przy każdym wdrożeniu."""
    phases = _phases()
    one_shot = {name for name in phases if _ONE_SHOT_PHASE.match(name)}
    assert len(one_shot) >= 42
    ungated = {name for name in one_shot if not _MARKED_CALL.search(phases[name])}
    assert ungated == _RUNS_ON_EVERY_START


def test_gating_markers_are_defined_by_the_services_the_block_runs() -> None:
    """Literówka w znaczniku nie psuje danych (krok wykona się jak dziś), ale po
    cichu odbiera całą oszczędność, więc znacznik musi istnieć w module bloku albo
    w module, z którego ten importuje."""
    for name, body in _phases().items():
        call = _MARKED_CALL.search(body)
        if not call:
            continue
        sources = _service_sources(body)
        assert sources, f"{name}: blok nie importuje żadnego serwisu"
        for marker in re.findall(r'"([^"]+)"', call.group(1)):
            assert f'"{marker}"' in sources, f"{name}: {marker} nie występuje w serwisach bloku"


def _service_sources(body: str) -> str:
    texts: list[str] = []
    for module in re.findall(r"^from (app\.services[\w.]+) import", body, re.M):
        path = _ROOT / (module.replace(".", "/") + ".py")
        text = path.read_text(encoding="utf-8")
        texts.append(text)
        for imported in re.findall(r"^from (app\.services[\w.]+) import", text, re.M):
            nested = _ROOT / (imported.replace(".", "/") + ".py")
            if nested.exists():
                texts.append(nested.read_text(encoding="utf-8"))
    return "\n".join(texts)


def test_marker_read_runs_before_the_first_gated_block() -> None:
    source = _ENTRYPOINT.read_text(encoding="utf-8")
    read = source.index('startup_phase "read-repair-markers"')
    first = _MARKED_CALL.search(source)
    assert first and read < first.start()
    schema_ready = source.index('startup_phase "metadata-create-all"')
    assert schema_ready < read, "app_settings musi już istnieć"
