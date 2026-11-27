"""Ekran Bezpieczeństwo (0799) bez bazy: czyszczenie, mapowanie źródeł, terminy, lustro DDL.

Dane w testach są fikcyjne — adresy z puli dokumentacyjnej (RFC 5737/3849),
e-maile z ``example.com`` (repo i logi Actions są publiczne).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services import security_schema as schema
from app.services.security_ingest import (
    FalcoEvent,
    IngestBatch,
    WazuhAlert,
    falco_to_event,
    scrub,
    wazuh_severity,
    wazuh_to_event,
)
from app.services.security_screen import add_cadence, effective_status, routine_state
from app.services.security_sync import run_done_on, runs_to_events

ROOT = Path(__file__).resolve().parents[1]


# ── Prywatność ───────────────────────────────────────────────────────────────


def test_scrub_removes_ipv4_ipv6_and_emails() -> None:
    text = (
        "Ban 4 h: 203.0.113.7 i 198.51.100.0/24, IPv6 2001:db8::1, "
        "konto ops@example.com"
    )
    cleaned = scrub(text, 300)
    assert "203.0.113" not in cleaned and "198.51.100" not in cleaned
    assert "2001:db8" not in cleaned and "example.com" not in cleaned
    assert cleaned.count("[adres IP]") == 3 and "[e-mail]" in cleaned


@pytest.mark.parametrize(
    "text",
    [
        "Blocked 203.0.113.7.",
        "from 198.51.100.4. Next",
        "(203.0.113.7)",
        "ip=203.0.113.7;",
    ],
)
def test_scrub_removes_ip_at_sentence_end_and_in_punctuation(text: str) -> None:
    cleaned = scrub(text, 300)
    assert "203.0.113" not in cleaned and "198.51.100" not in cleaned
    assert "[adres IP]" in cleaned


def test_scrub_keeps_times_versions_and_paths() -> None:
    text = "14:02:11 Coolify 4.7.6 → 4.7.7, plik /etc/ssh/sshd_config:12"
    assert scrub(text, 300) == text


def test_scrub_cuts_to_limit() -> None:
    assert len(scrub("x" * 500, 300)) == 300


# ── Walidacja formatu ogólnego ───────────────────────────────────────────────


def _event(**over):
    base = {
        "occurred_at": "2026-11-27T14:02:00Z",
        "kind": "ban",
        "summary": "Ban 4 h: skan ścieżek",
    }
    return {**base, **over}


def test_batch_keeps_last_of_duplicate_fingerprints() -> None:
    batch = IngestBatch.model_validate(
        {
            "source": "ci",
            "scanner": "zizmor",
            "findings": [
                {"fingerprint": "a", "severity": "low", "title": "pierwszy"},
                {"fingerprint": "b", "severity": "low", "title": "inny"},
                {"fingerprint": "a", "severity": "high", "title": "drugi"},
            ],
        }
    )
    assert [(f.fingerprint, f.title) for f in batch.findings] == [
        ("a", "drugi"),
        ("b", "inny"),
    ]


def test_batch_accepts_contract_example() -> None:
    batch = IngestBatch.model_validate(
        {"source": "crowdsec", "events": [_event(count=41, ref="crowdsec:alert:1")]}
    )
    assert batch.events[0].count == 41


@pytest.mark.parametrize(
    "body",
    [
        {"source": "nieznane", "events": []},
        {"source": "crowdsec", "events": [_event(kind="Ban Wielki")]},
        {"source": "crowdsec", "events": [_event(occurred_at="2026-11-27T14:02:00")]},
        {"source": "crowdsec", "events": [_event(severity="pilne")]},
        {"source": "crowdsec", "events": [_event(summary="x" * 301)]},
        {"source": "crowdsec", "events": [_event(ip="203.0.113.7")]},
        {"source": "ci", "complete": True, "findings": []},
        {
            "source": "ci",
            "findings": [
                {
                    "fingerprint": "a",
                    "severity": "high",
                    "title": "t",
                    "steps": ["x" * 301],
                }
            ],
        },
        {"source": "crowdsec", "events": [_event()] * 501},
    ],
    ids=[
        "zrodlo",
        "kind",
        "bez-strefy",
        "waga",
        "dlugi-opis",
        "nieznane-pole",
        "complete-bez-scannera",
        "dlugi-krok",
        "za-duzo-zdarzen",
    ],
)
def test_batch_rejects_invalid_input(body: dict) -> None:
    with pytest.raises(ValidationError):
        IngestBatch.model_validate(body)


# ── Falco i Wazuh natywnie ───────────────────────────────────────────────────


def test_falco_keeps_only_rule_priority_and_container() -> None:
    event = FalcoEvent.model_validate(
        {
            "uuid": "0f0e-1",
            "rule": "Terminal shell in container",
            "priority": "Warning",
            "time": "2026-11-27T13:00:00.123Z",
            "output": "shell spawned cmdline=psql postgres://nexus:sekret@db",
            "output_fields": {
                "container.name": "backend",
                "proc.cmdline": "psql sekret",
            },
        }
    )
    mapped = falco_to_event(event)
    assert mapped.severity == "medium"
    assert mapped.summary == "Terminal shell in container · kontener backend"
    assert "sekret" not in mapped.model_dump_json()
    assert mapped.ref == "falco:0f0e-1"


@pytest.mark.parametrize(
    "level,expected",
    [(3, "info"), (4, "low"), (7, "medium"), (10, "high"), (13, "critical")],
)
def test_wazuh_level_maps_to_severity(level: int, expected: str) -> None:
    assert wazuh_severity(level) == expected


def test_wazuh_alert_drops_full_log_and_maps_kind() -> None:
    alert = WazuhAlert.model_validate(
        {
            "id": "1732712345.123",
            "timestamp": "2026-11-27T12:15:00.000+0000",
            "rule": {
                "level": 7,
                "description": "Integrity checksum changed.",
                "groups": ["ossec", "syscheck"],
            },
            "agent": {"name": "nexus-prod"},
            "full_log": "File '/etc/ssh/sshd_config' changed by 203.0.113.7",
        }
    )
    mapped = wazuh_to_event(alert)
    assert mapped.kind == "fim_change"
    assert mapped.summary == "Integrity checksum changed. · nexus-prod"
    assert "203.0.113" not in mapped.model_dump_json()


# ── Wyjątek po terminie, rutyny ──────────────────────────────────────────────


def _finding(status: str, until: date | None) -> SimpleNamespace:
    return SimpleNamespace(status=status, exception_until=until)


def test_exception_counts_as_excepted_until_its_last_day() -> None:
    today = date(2026, 12, 1)
    assert (
        effective_status(_finding("excepted", date(2026, 12, 1)), today) == "excepted"
    )
    assert (
        effective_status(_finding("excepted", date(2026, 12, 2)), today) == "excepted"
    )


def test_exception_after_deadline_returns_as_open() -> None:
    today = date(2026, 12, 2)
    assert effective_status(_finding("excepted", date(2026, 12, 1)), today) == "open"
    assert effective_status(_finding("fixed", None), today) == "fixed"


@pytest.mark.parametrize(
    "start,cadence,expected",
    [
        (date(2026, 11, 23), "week", date(2026, 11, 30)),
        (date(2026, 11, 13), "month", date(2026, 12, 13)),
        (date(2027, 1, 31), "month", date(2027, 2, 28)),
        (date(2026, 11, 24), "quarter", date(2027, 2, 24)),
        (date(2026, 11, 30), "quarter", date(2027, 2, 28)),
    ],
)
def test_add_cadence(start: date, cadence: str, expected: date) -> None:
    assert add_cadence(start, cadence) == expected


def test_routine_state_overdue_soon_ok() -> None:
    today = date(2026, 12, 10)
    assert (
        routine_state(SimpleNamespace(next_due_on=date(2026, 12, 9)), today)
        == "overdue"
    )
    assert (
        routine_state(SimpleNamespace(next_due_on=date(2026, 12, 13)), today) == "soon"
    )
    assert routine_state(SimpleNamespace(next_due_on=date(2026, 12, 14)), today) == "ok"


# ── Źródła czytane przez NEXUS ───────────────────────────────────────────────


def test_github_runs_become_idempotent_events() -> None:
    runs = [
        {
            "id": 11,
            "status": "completed",
            "conclusion": "success",
            "event": "schedule",
            "run_number": 3,
            "run_started_at": "2026-11-23T05:30:12Z",
        },
        {
            "id": 12,
            "status": "completed",
            "conclusion": "failure",
            "event": "workflow_dispatch",
            "run_number": 4,
            "run_started_at": "2026-11-24T08:00:00Z",
        },
        {
            "id": 13,
            "status": "in_progress",
            "conclusion": None,
            "run_started_at": "2026-11-27T08:00:00Z",
        },
    ]
    events = runs_to_events(runs)
    assert [e.ref for e in events] == ["gh:run:11", "gh:run:12"]
    assert events[0].severity == "info" and "zielony" in events[0].summary
    assert events[1].severity == "high" and "czerwony" in events[1].summary


def test_manual_run_after_midnight_warsaw_counts_for_the_next_day() -> None:
    # 23:30 UTC = 00:30 w Warszawie — rutyna jest wykonana „jutro”, nie dziś.
    assert run_done_on(datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc)) == date(
        2026, 12, 1
    )


def test_new_column_reaches_databases_that_already_ran_0799() -> None:
    assert any(
        "ADD COLUMN IF NOT EXISTS last_run_id" in statement
        for statement in schema.TABLE_DDL
    )


# ── Lustro DDL ───────────────────────────────────────────────────────────────


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_entrypoint_runs_the_single_ddl_source() -> None:
    entry = (ROOT / "entrypoint.sh").read_text()
    assert (
        "_security_schema.TABLE_DDL" in entry and "_security_schema.SEED_DDL" in entry
    )
    assert entry.count("_SECURITY_SCREEN_DDL") >= 3, "lista musi być w fazie DDL"
    squashed = _squash(entry)
    for statement in schema.ENUM_STATEMENTS:
        assert _squash(statement) in squashed


def test_migration_reads_the_single_source() -> None:
    # Numer migracji zmienia przepięcie w pasie migracji — szukamy po nazwie.
    (path,) = (ROOT / "alembic/versions").glob("*_security_screen.py")
    migration = path.read_text()
    assert f'revision = "{path.stem}"' in migration
    assert "schema.TABLE_DDL" in migration and "schema.ENUM_STATEMENTS" in migration
    assert "schema.SEED_DDL" in migration


def test_seed_has_the_five_routines_from_the_report() -> None:
    keys = [row[0] for row in schema.ROUTINE_SEED]
    assert keys == [
        "ci_weekly",
        "pentest_staging",
        "dast_staging",
        "external_scan",
        "accounts_review",
    ]
    assert "ON CONFLICT (key) DO NOTHING" in schema.SEED_DDL[0]


def test_new_notification_type_is_admin_only_and_mailed() -> None:
    from app.models.notification import NotificationType
    from app.services.notification_access import ADMIN_ONLY_NOTIFICATION_TYPES

    assert NotificationType.security_routine_overdue in ADMIN_ONLY_NOTIFICATION_TYPES
