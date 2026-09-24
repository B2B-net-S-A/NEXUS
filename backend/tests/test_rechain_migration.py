"""Testy ``scripts/rechain_migration.py`` na jednorazowym repo gita w tmp_path.

Bez aplikacji i bez bazy — lokalnie:
``cd backend && python3 -m pytest --noconftest -q tests/test_rechain_migration.py``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts import rechain_migration as rechain

VERSIONS = "backend/alembic/versions"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def sh(repo: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV, "HOME": str(repo)}
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout


def migration(revision: str, down: str, title: str, annotated: bool = False) -> str:
    if annotated:
        header = f'revision: str = "{revision}"\ndown_revision: Union[str, None] = "{down}"\n'
    else:
        header = f'revision = "{revision}"\ndown_revision = "{down}"\n'
    return (
        f'"""{title}\n\nRevision ID: {revision}\nRevises: {down}\n"""\n\n'
        "from typing import Union\n\n"
        f"{header}\n\ndef upgrade():\n    pass\n\n\ndef downgrade():\n    pass\n"
    )


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str) -> None:
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", message)


def base_repo(tmp_path: Path) -> Path:
    """main: 0366 <- 0367 <- 0368 (+ stary merge z krotką) i entrypoint z numerami."""
    repo = tmp_path / "repo"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    write(
        repo,
        f"{VERSIONS}/0001_a.py",
        '"""a"""\nrevision = "0001"\ndown_revision = None\n',
    )
    write(
        repo,
        f"{VERSIONS}/0002_b.py",
        '"""b"""\nrevision = "0002_b"\ndown_revision = "0001"\n',
    )
    write(
        repo,
        f"{VERSIONS}/0003_c.py",
        '"""c"""\nrevision = "0003_c"\ndown_revision = "0001"\n',
    )
    write(
        repo,
        f"{VERSIONS}/0366_merge.py",
        '"""m"""\nrevision: str = "0366_merge"\n'
        'down_revision: tuple[str, str] = (\n    "0002_b",\n    "0003_c",\n)\n',
    )
    write(
        repo,
        f"{VERSIONS}/0367_x.py",
        migration("0367_x", "0366_merge", "x", annotated=True),
    )
    write(repo, f"{VERSIONS}/0368_y.py", migration("0368_y", "0367_x", "y"))
    write(
        repo,
        "backend/entrypoint.sh",
        "#!/bin/sh\n# 0367: x\n# 0368: y\necho done\n",
    )
    commit(repo, "base")
    return repo


def add_pr_branch(repo: Path) -> None:
    """Gałąź PR-a: 0369_prep na 0368_y + linie w entrypoint.sh i teście."""
    sh(repo, "checkout", "-q", "-b", "pr", "main")
    write(
        repo,
        f"{VERSIONS}/0369_prep.py",
        migration("0369_prep", "0368_y", "ocena prepu"),
    )
    ep = (repo / "backend/entrypoint.sh").read_text()
    ep = ep.replace("echo done\n", "# 0369: ocena prepu (0369_prep)\necho done\n")
    write(repo, "backend/entrypoint.sh", ep)
    write(
        repo,
        "backend/tests/test_prep.py",
        'REV = "0369_prep"\n'
        "# 0369 dodana przez PR\n"
        "# 0369_academy z maina to inna migracja — ta linia zostaje\n",
    )
    commit(repo, "pr: 0369_prep")


def advance_main_with_collision(repo: Path) -> None:
    """main dostaje własną 0369 (Akademia) i linię entrypointu z tym numerem."""
    sh(repo, "checkout", "-q", "main")
    write(
        repo,
        f"{VERSIONS}/0369_academy.py",
        migration("0369_academy", "0368_y", "Akademia"),
    )
    ep = (repo / "backend/entrypoint.sh").read_text()
    ep = ep.replace("echo done\n", "# 0369: Akademia\necho done\n")
    write(repo, "backend/entrypoint.sh", ep)
    commit(repo, "main: 0369_academy")
    sh(repo, "checkout", "-q", "pr")
    # Konflikt na entrypoint.sh (obie strony dopisały linię w tym samym miejscu)
    # rozwiązujemy tak, jak zrobiłby to człowiek: obie linie zostają.
    proc = subprocess.run(
        ["git", "merge", "-q", "--no-edit", "main"],
        cwd=repo,
        env={**os.environ, **GIT_ENV, "HOME": str(repo)},
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        write(
            repo,
            "backend/entrypoint.sh",
            "#!/bin/sh\n# 0367: x\n# 0368: y\n# 0369: Akademia\n"
            "# 0369: ocena prepu (0369_prep)\necho done\n",
        )
        sh(repo, "add", "-A")
        sh(repo, "commit", "-q", "--no-edit")


def run_script(repo: Path, *args: str) -> tuple[int, str]:
    lines: list[str] = []
    code = rechain.run(
        str(repo),
        "main",
        VERSIONS,
        dry_run="--dry-run" in args,
        out=lines.append,
    )
    return code, "\n".join(lines)


def test_collision_renumbers_only_pr_lines(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    add_pr_branch(repo)
    advance_main_with_collision(repo)

    code, output = run_script(repo)
    assert code == 0, output

    versions = repo / VERSIONS
    assert not (versions / "0369_prep.py").exists()
    moved = (versions / "0370_prep.py").read_text()
    assert 'revision = "0370_prep"' in moved
    assert 'down_revision = "0369_academy"' in moved
    assert "Revision ID: 0370_prep" in moved
    assert "Revises: 0369_academy" in moved
    assert "0369_prep" not in moved
    # Migracja z maina nietknięta.
    assert (versions / "0369_academy.py").read_text() == migration(
        "0369_academy", "0368_y", "Akademia"
    )

    ep = (repo / "backend/entrypoint.sh").read_text().splitlines()
    assert "# 0369: Akademia" in ep  # linia maina
    assert "# 0370: ocena prepu (0370_prep)" in ep  # linia PR-a
    assert "# 0368: y" in ep

    test_file = (repo / "backend/tests/test_prep.py").read_text().splitlines()
    assert test_file[0] == 'REV = "0370_prep"'
    assert test_file[1] == "# 0370 dodana przez PR"
    # Linia PR-a, która wymienia migrację z maina o tym samym numerze, zostaje.
    assert test_file[2] == "# 0369_academy z maina to inna migracja — ta linia zostaje"

    # Rename zarejestrowany w indeksie (git mv), a skrypt jest idempotentny.
    status = sh(repo, "status", "--porcelain")
    assert "0370_prep.py" in status
    sh(repo, "commit", "-q", "-am", "rechain")
    code, output = run_script(repo)
    assert code == 0
    assert "nic do zrobienia" in output


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    add_pr_branch(repo)
    advance_main_with_collision(repo)
    before = sh(repo, "status", "--porcelain")

    code, output = run_script(repo, "--dry-run")

    assert code == 0
    assert "0370_prep" in output
    assert "--dry-run" in output
    assert (repo / VERSIONS / "0369_prep.py").exists()
    assert sh(repo, "status", "--porcelain") == before


def test_noop_when_already_on_head(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    add_pr_branch(repo)

    code, output = run_script(repo)

    assert code == 0
    assert "nic do zrobienia" in output
    assert (repo / VERSIONS / "0369_prep.py").exists()
    assert sh(repo, "status", "--porcelain") == ""


def test_chain_of_two_pr_migrations_keeps_internal_link(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    sh(repo, "checkout", "-q", "-b", "pr", "main")
    write(repo, f"{VERSIONS}/0369_a.py", migration("0369_a", "0368_y", "a"))
    write(repo, f"{VERSIONS}/0370_b.py", migration("0370_b", "0369_a", "b"))
    write(repo, "notes.txt", "0369 i 0370 z PR-a\n")
    commit(repo, "pr: 0369_a + 0370_b")
    sh(repo, "checkout", "-q", "main")
    write(repo, f"{VERSIONS}/0369_z.py", migration("0369_z", "0368_y", "z"))
    commit(repo, "main: 0369_z")
    sh(repo, "checkout", "-q", "pr")
    sh(repo, "merge", "-q", "--no-edit", "main")

    code, output = run_script(repo)
    assert code == 0, output

    a = (repo / VERSIONS / "0370_a.py").read_text()
    b = (repo / VERSIONS / "0371_b.py").read_text()
    assert 'revision = "0370_a"' in a and 'down_revision = "0369_z"' in a
    # Bez kaskady 0370 -> 0371 na nowym id pierwszej migracji.
    assert 'revision = "0371_b"' in b and 'down_revision = "0370_a"' in b
    assert "Revises: 0370_a" in b
    assert (repo / "notes.txt").read_text() == "0370 i 0371 z PR-a\n"


def test_wrong_parent_with_free_number_only_repoints(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    sh(repo, "checkout", "-q", "-b", "pr", "main")
    write(repo, f"{VERSIONS}/0370_late.py", migration("0370_late", "0368_y", "late"))
    commit(repo, "pr: 0370_late na 0368")
    sh(repo, "checkout", "-q", "main")
    write(repo, f"{VERSIONS}/0369_z.py", migration("0369_z", "0368_y", "z"))
    commit(repo, "main: 0369_z")
    sh(repo, "checkout", "-q", "pr")
    sh(repo, "merge", "-q", "--no-edit", "main")

    code, output = run_script(repo)
    assert code == 0, output

    text = (repo / VERSIONS / "0370_late.py").read_text()
    assert 'revision = "0370_late"' in text
    assert 'down_revision = "0369_z"' in text


def test_aborts_when_base_has_two_heads(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    write(repo, f"{VERSIONS}/0369_q.py", migration("0369_q", "0367_x", "q"))
    commit(repo, "main: druga głowa")
    add_pr_branch(repo)

    with pytest.raises(rechain.RechainError, match="głowy"):
        run_script(repo)
    assert (repo / VERSIONS / "0369_prep.py").exists()


def test_cli_reports_error_in_polish(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, f"{VERSIONS}/0369_q.py", migration("0369_q", "0367_x", "q"))
    commit(repo, "main: druga głowa")
    add_pr_branch(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(repo))

    assert rechain.main(["--base", "main"]) == 1
    assert "Błąd:" in capsys.readouterr().err
