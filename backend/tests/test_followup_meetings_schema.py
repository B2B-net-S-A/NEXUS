"""Keep migration, startup repair and deep-health checks aligned."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_followup_schema_is_repaired_and_probed() -> None:
    migration = (ROOT / "alembic/versions/0379_followup_teams_meetings.py").read_text()
    entrypoint = (ROOT / "entrypoint.sh").read_text()
    main = (ROOT / "app/main.py").read_text()
    for column in (
        "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE",
        "calendar_event_id INTEGER NOT NULL UNIQUE REFERENCES calendar_events(id) ON DELETE CASCADE",
        "transcript_vtt TEXT NULL",
        "transcript_text TEXT NULL",
        "client_request_id VARCHAR(80) NOT NULL UNIQUE",
    ):
        assert column in migration
        assert column in entrypoint
    assert '("followup_meetings", FollowupMeeting)' in main
