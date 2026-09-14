"""MON-01 (audyt Codexa, 14.09.2026): monitor Sentry nie może być zielony,
gdy nie odczytał projektu.

Skrypt ``.github/scripts/sentry_daily_digest.py`` zamieniał błąd API/sieci
na tekst w treści digestu i kończył się kodem 0 — codzienny „digest" z
wygasłym tokenem wyglądał identycznie jak zdrowy bieg. Test ładuje skrypt
po ścieżce (wzorzec ``test_cv_quality_ops.py``) i podstawia sam odczyt
Sentry — bez sieci, bez prawdziwego tokena.
"""

from __future__ import annotations

import importlib.util
import io
import urllib.error
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "sentry_daily_digest",
    Path(__file__).parents[2] / ".github/scripts/sentry_daily_digest.py",
)
digest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(digest)

_WORKFLOW = Path(__file__).parents[2] / ".github/workflows/sentry-daily-monitor.yml"


def _http_error(project: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url=f"https://sentry.example/{project}",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b""),
    )


def _fake_fetch(failing: set[str]):
    def fetch_issues(token, project, query="is:unresolved", sort="freq", **kwargs):  # noqa: ANN001
        if project in failing:
            raise _http_error(project)
        return [
            {
                "id": "1" if project == "nexus-be" else "2",
                "shortId": f"{project.upper()}-1",
                "count": 3,
                "userCount": 1,
                "title": "synthetic",
                "permalink": "https://sentry.example/1",
            }
        ]

    return fetch_issues


@pytest.fixture
def dry_run_env(monkeypatch):
    monkeypatch.setenv("SENTRY_READ_TOKEN", "test-token-not-real")
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.delenv("TEAMS_SENTRY_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(digest, "SENTRY_PROJECTS", ["nexus-be", "nexus-fe"])
    monkeypatch.setattr(digest, "enrich_issue", lambda token, issue: issue)


def test_unread_project_fails_the_run_but_the_rest_is_still_delivered(
    dry_run_env, monkeypatch, capsys
):
    monkeypatch.setattr(digest, "fetch_issues", _fake_fetch({"nexus-be"}))

    assert digest.main() == 1

    captured = capsys.readouterr()
    assert "nexus-be — MONITORING READ FAILED" in captured.out
    assert "INCOMPLETE MONITORING" in captured.out
    # To, co się udało odczytać, nadal idzie w digeście.
    assert "NEXUS-FE-1" in captured.out
    assert "nexus-fe — MONITORING READ FAILED" not in captured.out


def test_all_projects_read_exits_zero(dry_run_env, monkeypatch, capsys):
    monkeypatch.setattr(digest, "fetch_issues", _fake_fetch(set()))

    assert digest.main() == 0

    captured = capsys.readouterr()
    assert "MONITORING READ FAILED" not in captured.out
    assert "INCOMPLETE MONITORING" not in captured.out


def test_partial_digest_is_posted_to_teams_before_failing(monkeypatch):
    """Wysyłka NIE jest pomijana: Teams dostaje częściowy digest z jawną
    linią o nieodczytanym projekcie, a dopiero potem bieg kończy się kodem 1."""
    monkeypatch.setenv("SENTRY_READ_TOKEN", "test-token-not-real")
    monkeypatch.setenv("TEAMS_SENTRY_WEBHOOK_URL", "https://hooks.example/not-real")
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(digest, "SENTRY_PROJECTS", ["nexus-be", "nexus-fe"])
    monkeypatch.setattr(digest, "enrich_issue", lambda token, issue: issue)
    monkeypatch.setattr(digest, "fetch_issues", _fake_fetch({"nexus-fe"}))
    posted: list[str] = []
    monkeypatch.setattr(
        digest, "post_to_teams", lambda webhook, text: posted.append(text)
    )

    assert digest.main() == 1

    assert len(posted) == 1
    assert "nexus-fe — MONITORING READ FAILED" in posted[0]
    assert "NEXUS-BE-1" in posted[0]


def test_project_section_reports_read_failure_as_a_flag(monkeypatch):
    monkeypatch.setattr(digest, "fetch_issues", _fake_fetch({"nexus-be"}))
    monkeypatch.setattr(digest, "enrich_issue", lambda token, issue: issue)

    text, ok = digest.project_section("t", "nexus-be", redact=True)
    assert ok is False
    assert "MONITORING READ FAILED (HTTPError)" in text

    text, ok = digest.project_section("t", "nexus-fe", redact=True)
    assert ok is True
    assert "NEXUS-FE-1" in text


def test_workflow_fails_without_token_instead_of_skipping(monkeypatch):
    """The workflow delegates credential validation to the tested script."""
    source = _WORKFLOW.read_text("utf-8")
    assert "secrets.SENTRY_READ_TOKEN" in source
    assert "secrets.TEAMS_SENTRY_WEBHOOK_URL" in source
    assert "run: python .github/scripts/sentry_daily_digest.py" in source
    monkeypatch.delenv("SENTRY_READ_TOKEN", raising=False)
    assert digest.main() == 1
