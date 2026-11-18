"""Scheduler retry decisions against the real SQL predicate, without Postgres."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine

from app.tasks import law_radar


@pytest.fixture
def retry_db():
    metadata = MetaData()
    table = Table(
        "law_radar_runs",
        metadata,
        Column("kind", String),
        Column("status", String),
        Column("started_at", DateTime(timezone=True)),
    )
    engine = create_engine("sqlite://")
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:

            class Session:
                async def scalar(self, statement):
                    value = connection.scalar(statement)
                    if isinstance(value, datetime):
                        return value.replace(tzinfo=timezone.utc)
                    return value

            yield table, connection, Session()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "status,age_minutes,retry",
    [
        ("expired", 121, True),
        ("expired", 61, True),
        ("expired", 60, False),
        ("expired", 59, False),
        ("failed", 61, True),
        ("failed", 60, False),
        ("started", 121, False),
        ("received", 121, False),
    ],
)
@pytest.mark.asyncio
async def test_collect_retries_failed_or_expired_but_not_an_open_or_received_run(
    retry_db, status: str, age_minutes: int, retry: bool
) -> None:
    now = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)
    local = now.astimezone(ZoneInfo("Europe/Warsaw"))
    table, connection, db = retry_db
    connection.execute(
        table.insert(),
        [
            {
                "kind": "collect",
                "status": "received",
                "started_at": now - timedelta(days=1),
            },
            {
                "kind": "collect",
                "status": status,
                "started_at": now - timedelta(minutes=age_minutes),
            },
            # The other bot must not suppress collection.
            {"kind": "analyze", "status": "received", "started_at": now},
        ],
    )
    last = await law_radar.last_start(db, "collect", now=now)
    assert law_radar.collect_due(local, last) is retry


@pytest.mark.asyncio
async def test_received_collection_still_blocks_retry_after_a_later_expiry(
    retry_db,
) -> None:
    now = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)
    table, connection, db = retry_db
    connection.execute(
        table.insert(),
        [
            {
                "kind": "collect",
                "status": "received",
                "started_at": now - timedelta(hours=4),
            },
            {
                "kind": "collect",
                "status": "expired",
                "started_at": now - timedelta(hours=2),
            },
        ],
    )
    last = await law_radar.last_start(db, "collect", now=now)
    assert not law_radar.collect_due(now.astimezone(ZoneInfo("Europe/Warsaw")), last)


@pytest.mark.parametrize(
    "attempts,available", [(0, True), (2, True), (3, False), (4, False)]
)
@pytest.mark.asyncio
async def test_retry_cap_counts_only_collections_in_the_current_business_day(
    retry_db, attempts: int, available: bool
) -> None:
    table, connection, db = retry_db
    local = datetime(2026, 11, 17, 0, 30, tzinfo=ZoneInfo("Europe/Warsaw"))
    now = local.astimezone(timezone.utc)
    rows = [
        {
            "kind": "collect",
            "status": "expired",
            "started_at": now - timedelta(minutes=5),
        }
    ] * attempts
    rows += [
        # These attempts share the UTC date with today, but are yesterday in Warsaw.
        {"kind": "collect", "status": "expired", "started_at": now - timedelta(hours=1)}
    ] * 3
    rows += [
        {"kind": "analyze", "status": "started", "started_at": now},
        {"kind": "collect", "status": "expired", "started_at": now + timedelta(days=1)},
    ]
    connection.execute(table.insert(), rows)
    assert await law_radar.collect_retry_available(db, local=local) is available
