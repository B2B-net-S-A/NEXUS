"""Bramki ``scripts/prod_readonly.py``: odczyt produkcji dla nocnych rutyn.

Reguła zgody Claude Code obejmuje tylko ten skrypt, więc jego bramki są jedyną
granicą tego, co rutyna zrobi na produkcji. Testy nie łączą się z serwerem:
``subprocess.run`` jest podmieniony i każde odrzucone wejście musi skończyć się
przed SSH. Reguła: docs/claude/podstawy/rutyny-nocne.md.
"""

from __future__ import annotations

import importlib.util
import io
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[2]
_PATH = _REPO / "scripts/prod_readonly.py"
_SPEC = importlib.util.spec_from_file_location("prod_readonly", _PATH)
pr = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = pr
_SPEC.loader.exec_module(pr)


@pytest.fixture
def no_ssh(monkeypatch):
    """Każde wywołanie SSH w teście z odrzuconym wejściem to błąd."""

    def boom(*_a, **_k):
        raise AssertionError("odrzucone wejście nie może dojść do SSH")

    monkeypatch.setattr(pr.subprocess, "run", boom)


@pytest.fixture
def fake_ssh(monkeypatch, tmp_path):
    conf = tmp_path / "conf"
    conf.write_text("host=prod.example.test\nkey=/nonexistent/key\n")
    monkeypatch.setenv("NEXUS_PROD_READONLY_CONF", str(conf))
    calls = []

    def run(argv, input=None, **_k):
        calls.append({"argv": argv, "input": input})
        stdout = calls_stdout.pop(0) if calls_stdout else ""
        return pr.subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    calls_stdout: list[str] = []
    monkeypatch.setattr(pr.subprocess, "run", run)
    return calls, calls_stdout


# --- sql: zapis odrzucony ----------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users (id) VALUES (1)",
        "UPDATE users SET name = 'x' WHERE id = 1",
        "DELETE FROM activities",
        "SELECT 1; DROP TABLE users",
        "select 1;\ntruncate candidates",
        "WITH d AS (DELETE FROM notes RETURNING id) SELECT count(*) FROM d",
        "WITH u AS (UPDATE users SET role = 'admin' RETURNING id) SELECT * FROM u",
        "SELECT * INTO copy_users FROM users",
        "SELECT id FROM users FOR UPDATE",
        "SELECT id FROM users FOR KEY SHARE",
        "SET default_transaction_read_only = off",
        "SELECT 1; COMMIT; DELETE FROM users",
        "BEGIN READ WRITE",
        "SELECT set_config('default_transaction_read_only', 'off', false)",
        "SELECT pg_terminate_backend(123)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT query_to_xml('delete from users', true, true, '')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT nextval('users_id_seq')",
        "SELECT 1 \\g /tmp/out",
        "\\! rm -rf /",
        "\\copy users TO '/tmp/u.csv'",
        "SELECT $$x$$",
        "SELECT 'niezamknięty",
        "SELECT 1 /* niezamknięty",
        "COPY users TO STDOUT",
        "",
        "   -- sam komentarz\n",
        "EXPLAIN ANALYZE DELETE FROM users",
    ],
)
def test_write_and_escape_rejected(sql, no_ssh):
    with pytest.raises(pr.Rejected):
        pr.validate_sql(sql)


def test_rejected_sql_never_reaches_ssh(monkeypatch, no_ssh, capsys):
    monkeypatch.setattr(pr.sys, "stdin", io.StringIO("DELETE FROM users"))
    assert pr.main(["sql"]) == 2
    assert "Odrzucone" in capsys.readouterr().err


# --- sql: odczyt przechodzi --------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select count(*) from novelty_progress;",
        "SELECT action, count(*) FROM activities WHERE action IN ('update', 'delete; x') GROUP BY 1",
        "WITH x AS (SELECT id FROM candidates WHERE created_at > now() - interval '7 days') SELECT count(*) FROM x",
        (
            "-- DELETE w komentarzu nie przeszkadza\nSELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'novelty_progress';"
        ),
        "SELECT 1; SELECT 2;",
        "(SELECT 1) UNION ALL (SELECT 2)",
        'SELECT "updated_at" FROM users /* update w komentarzu */ LIMIT 1',
    ],
)
def test_read_query_passes(sql):
    assert pr.validate_sql(sql)


def test_payload_is_read_only_session_and_transaction():
    payload = pr.sql_payload("SELECT count(*) FROM users")
    lines = payload.splitlines()
    assert lines[0] == "SET default_transaction_read_only = on;"
    assert "BEGIN TRANSACTION READ ONLY;" in lines
    assert lines[-1] == "ROLLBACK;"
    assert lines.index("BEGIN TRANSACTION READ ONLY;") < lines.index(
        "SELECT count(*) FROM users;"
    )


def test_read_query_goes_by_stdin_not_command_line(fake_ssh, tmp_path):
    calls, _ = fake_ssh
    query = tmp_path / "q.sql"
    query.write_text("SELECT count(*) FROM users WHERE id > 5")
    assert pr.main(["sql", "--csv", "-f", str(query)]) == 0
    (call,) = calls
    remote = call["argv"][-1]
    assert "users" not in remote  # zapytanie nie trafia do komendy powłoki na serwerze
    assert "psql -X" in remote and "--csv" in remote and "ON_ERROR_STOP=1" in remote
    assert call["input"].startswith("SET default_transaction_read_only = on;")
    assert "BatchMode=yes" in call["argv"]


# --- env ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "SECRET_KEY",
        "DATABASE_URL",
        "ANTHROPIC_API_KEY",
        "AI_MATCH_TELEMETRY_SALT",
        "SENTRY_DSN",
        "M365_CLIENT_SECRET",
        "JWT_TOKEN_ENABLED",  # końcówka z białej listy nie wygrywa z wzorcem sekretu
        "POSTGRES_PASSWORD",
        "QDRANT_HOST",  # spoza białej listy
        "db_statement_timeout_ms",
        "A;rm",
        "X$(id)",
        "",
    ],
)
def test_secret_or_unlisted_env_rejected(name, no_ssh):
    with pytest.raises(pr.Rejected):
        pr.validate_env_names([name])


def test_secret_env_never_reaches_ssh(no_ssh, capsys):
    assert pr.main(["env", "DB_STATEMENT_TIMEOUT_MS", "SECRET_KEY"]) == 2
    assert "SECRET_KEY" in capsys.readouterr().err


def test_allowlist_has_no_secret_like_names():
    for name in pr.ENV_ALLOWED_NAMES:
        assert not pr._SECRET_NAME.search(name), name


def test_env_filters_on_server_and_reads_process_one(fake_ssh, capsys):
    calls, stdout = fake_ssh
    stdout.append("DB_STATEMENT_TIMEOUT_MS=120000\nSECRET_KEY=nie-powinno-wyjsc\n")
    assert pr.main(["env", "DB_STATEMENT_TIMEOUT_MS", "CONSULTANT_PANEL_ENABLED"]) == 0
    remote = calls[0]["argv"][-1]
    assert (
        "docker inspect -f '{{.State.Pid}}'" in remote and "/proc/$p/environ" in remote
    )
    assert "grep -E '^(DB_STATEMENT_TIMEOUT_MS|CONSULTANT_PANEL_ENABLED)='" in remote
    out = capsys.readouterr().out
    assert "DB_STATEMENT_TIMEOUT_MS=120000" in out
    assert "CONSULTANT_PANEL_ENABLED=<brak w procesie 1>" in out
    assert "SECRET_KEY" not in out  # druga bramka po stronie laptopa


def test_env_remote_failure_is_an_error_not_missing_names(
    monkeypatch, tmp_path, capsys
):
    conf = tmp_path / "conf"
    conf.write_text("host=prod.example.test\nkey=/nonexistent/key\n")
    monkeypatch.setenv("NEXUS_PROD_READONLY_CONF", str(conf))
    monkeypatch.setattr(
        pr.subprocess,
        "run",
        lambda argv, **_k: pr.subprocess.CompletedProcess(
            argv, 4, stdout="", stderr="Brak dostępu.\n"
        ),
    )
    assert pr.main(["env", "DB_STATEMENT_TIMEOUT_MS"]) == 4
    out = capsys.readouterr()
    assert "<brak w procesie 1>" not in out.out
    assert "Brak dostępu." in out.err


# --- backup-log, reszta ------------------------------------------------------


@pytest.mark.parametrize("arg", ["0", "501", "-5", "10;id", "abc"])
def test_backup_log_bounds(arg, no_ssh):
    assert pr.main(["backup-log", arg]) == 2


def test_backup_log_tail(fake_ssh):
    calls, _ = fake_ssh
    assert pr.main(["backup-log", "50"]) == 0
    assert calls[0]["argv"][-1] == "tail -n 50 /var/log/nexus-backup.log"


def test_unknown_subcommand_rejected(no_ssh):
    assert pr.main(["exec", "id"]) == 2
    assert pr.main(["sql", "--file", "/etc/passwd", "extra"]) == 2


def test_no_host_or_key_in_repo_script():
    text = _PATH.read_text()
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text), (
        "adres IP nie może leżeć w publicznym repo"
    )
    assert "BEGIN OPENSSH" not in text
    assert "_ed25519" not in text
