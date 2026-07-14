"""R5 snapshot/cutover tests; all execute in-process without network I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.cutover_schemas import (
    AnalyticsCutoverUpsert,
    LegacySnapshotImportItem,
)
from app.analytics.periods import AnalyticsPeriod, AnalyticsPeriodKind, WARSAW
from app.api.analytics_cutovers import router
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import UserRole
from app.services.analytics_v1.cutover import (
    AnalyticsCutoverService,
    CutoverBoundaryError,
    prepare_snapshot,
    resolve_cutover_source,
    snapshot_checksum,
    snapshot_key_for,
    validate_module_key,
    validate_month_start,
)


def _snapshot(**overrides) -> LegacySnapshotImportItem:
    values = {
        "metric_key": "board.pnl",
        "metric_version": "legacy-2026-01",
        "scope": "organization",
        "scope_ref": None,
        "period_start": datetime(2026, 1, 1, tzinfo=WARSAW),
        "period_end": datetime(2026, 2, 1, tzinfo=WARSAW),
        "timezone": "Europe/Warsaw",
        "data": {"revenue": "125.00", "costs": "75.00"},
        "source": "dynareporter",
        "source_ref": "board:2026-01",
    }
    values.update(overrides)
    return LegacySnapshotImportItem(**values)


def _period(start: datetime, end: datetime) -> AnalyticsPeriod:
    return AnalyticsPeriod(
        kind=AnalyticsPeriodKind.custom,
        start=start,
        end=end,
    )


def test_snapshot_identity_and_checksum_are_canonical() -> None:
    first = _snapshot(data={"revenue": "125.00", "costs": "75.00"})
    reordered = _snapshot(data={"costs": "75.00", "revenue": "125.00"})
    same_instants_utc = _snapshot(
        period_start=datetime(2025, 12, 31, 23, tzinfo=timezone.utc),
        period_end=datetime(2026, 1, 31, 23, tzinfo=timezone.utc),
        data={"costs": "75.00", "revenue": "125.00"},
    )
    corrected = _snapshot(data={"revenue": "126.00", "costs": "75.00"})

    key = snapshot_key_for(first)
    checksum = snapshot_checksum(first)
    assert key.startswith("legacy:v1:")
    assert len(key.removeprefix("legacy:v1:")) == 64
    int(key.removeprefix("legacy:v1:"), 16)
    assert len(checksum) == 64
    int(checksum, 16)
    assert snapshot_key_for(first) == snapshot_key_for(reordered)
    assert snapshot_checksum(first) == snapshot_checksum(reordered)
    assert snapshot_key_for(first) == snapshot_key_for(same_instants_utc)
    assert snapshot_checksum(first) == snapshot_checksum(same_instants_utc)
    assert snapshot_key_for(first) == snapshot_key_for(corrected)
    assert snapshot_checksum(first) != snapshot_checksum(corrected)


def test_cutover_requires_exact_warsaw_month_start() -> None:
    utc_equivalent = datetime(2026, 6, 30, 22, tzinfo=timezone.utc)
    normalized = validate_month_start(utc_equivalent)

    assert normalized.isoformat() == "2026-07-01T00:00:00+02:00"
    with pytest.raises(ValueError, match="first day"):
        validate_month_start(datetime(2026, 7, 2, tzinfo=WARSAW))
    with pytest.raises(ValueError, match="UTC offset"):
        validate_month_start(datetime(2026, 7, 1))
    with pytest.raises(ValueError, match="module_key"):
        validate_module_key("../board")


def test_cutover_resolver_never_blends_legacy_and_live() -> None:
    cutover = datetime(2026, 7, 1, tzinfo=WARSAW)
    before = _period(
        datetime(2026, 6, 1, tzinfo=WARSAW),
        datetime(2026, 7, 1, tzinfo=WARSAW),
    )
    after = _period(
        datetime(2026, 7, 1, tzinfo=WARSAW),
        datetime(2026, 8, 1, tzinfo=WARSAW),
    )
    crossing = _period(
        datetime(2026, 6, 1, tzinfo=WARSAW),
        datetime(2026, 8, 1, tzinfo=WARSAW),
    )

    legacy = resolve_cutover_source(
        module_key="board",
        period=before,
        cutover_at=cutover,
        legacy_source="dynareporter",
    )
    live = resolve_cutover_source(
        module_key="board",
        period=after,
        cutover_at=cutover,
        legacy_source="dynareporter",
    )

    assert legacy.source.value == "legacy_snapshot"
    assert live.source.value == "live_ats"
    assert (
        resolve_cutover_source(
            module_key="board",
            period=before,
            cutover_at=None,
        ).source.value
        == "live_ats"
    )
    with pytest.raises(CutoverBoundaryError):
        resolve_cutover_source(
            module_key="board",
            period=crossing,
            cutover_at=cutover,
            legacy_source="dynareporter",
        )


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def one(self):
        assert len(self._rows) == 1
        return self._rows[0]

    def one_or_none(self):
        assert len(self._rows) <= 1
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, *, mappings=None, scalars=None):
        self._mappings = mappings or []
        self._scalars = scalars or []

    def mappings(self):
        return _Rows(self._mappings)

    def scalars(self):
        return _Rows(self._scalars)


class _FakeSession:
    def __init__(self, *responses: _FakeResult):
        self.responses = list(responses)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        assert self.responses, "unexpected database round-trip"
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_batch_import_rejects_empty_service_call() -> None:
    service = AnalyticsCutoverService(cast(AsyncSession, _FakeSession()))
    with pytest.raises(ValueError, match="between 1 and 1000"):
        await service.import_legacy_snapshots([])


@pytest.mark.asyncio
async def test_batch_import_inserts_once_and_skips_duplicate_payload() -> None:
    item = _snapshot()
    key = snapshot_key_for(item)
    db = _FakeSession(
        _FakeResult(mappings=[]),
        _FakeResult(scalars=[key]),
    )

    service = AnalyticsCutoverService(cast(AsyncSession, db))
    result = await service.import_legacy_snapshots([item, item])

    assert result.model_dump() == {
        "total": 2,
        "inserted": 1,
        "skipped": 1,
        "conflicts": 0,
        "inserted_keys": [key],
        "skipped_keys": [key],
        "conflict_keys": [],
    }
    assert len(db.statements) == 2


@pytest.mark.asyncio
async def test_batch_import_reports_same_identity_with_changed_data() -> None:
    original = _snapshot()
    corrected = _snapshot(data={"revenue": "999.00"})
    key = snapshot_key_for(original)
    db = _FakeSession()

    service = AnalyticsCutoverService(cast(AsyncSession, db))
    result = await service.import_legacy_snapshots([original, corrected])

    assert result.inserted == 0
    assert result.skipped == 0
    assert result.conflicts == 2
    assert result.conflict_keys == [key]
    assert len(db.statements) == 0


@pytest.mark.asyncio
async def test_rerun_is_skipped_and_changed_existing_content_conflicts() -> None:
    item = _snapshot()
    prepared = prepare_snapshot(item)
    same_db = _FakeSession(
        _FakeResult(
            mappings=[
                {
                    "snapshot_key": prepared.snapshot_key,
                    "checksum": prepared.checksum,
                }
            ]
        )
    )
    changed_db = _FakeSession(
        _FakeResult(
            mappings=[
                {
                    "snapshot_key": prepared.snapshot_key,
                    "checksum": "0" * 64,
                }
            ]
        )
    )

    same = await AnalyticsCutoverService(
        cast(AsyncSession, same_db)
    ).import_legacy_snapshots([item])
    changed = await AnalyticsCutoverService(
        cast(AsyncSession, changed_db)
    ).import_legacy_snapshots([item])

    assert (same.inserted, same.skipped, same.conflicts) == (0, 1, 0)
    assert same.skipped_keys == [prepared.snapshot_key]
    assert (changed.inserted, changed.skipped, changed.conflicts) == (0, 0, 1)
    assert changed.conflict_keys == [prepared.snapshot_key]
    assert len(same_db.statements) == len(changed_db.statements) == 1


@pytest.mark.asyncio
async def test_concurrent_same_checksum_is_classified_as_idempotent_skip() -> None:
    item = _snapshot()
    prepared = prepare_snapshot(item)
    db = _FakeSession(
        _FakeResult(mappings=[]),
        _FakeResult(scalars=[]),
        _FakeResult(
            mappings=[
                {
                    "snapshot_key": prepared.snapshot_key,
                    "checksum": prepared.checksum,
                }
            ]
        ),
    )

    service = AnalyticsCutoverService(cast(AsyncSession, db))
    result = await service.import_legacy_snapshots([item])

    assert (result.inserted, result.skipped, result.conflicts) == (0, 1, 0)
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_cutover_upsert_is_audited_and_normalized_to_warsaw() -> None:
    now = datetime(2026, 7, 14, 10, tzinfo=timezone.utc)
    cutover = datetime(2026, 7, 1, tzinfo=WARSAW)
    db = _FakeSession(
        _FakeResult(
            mappings=[
                {
                    "module_key": "board",
                    "cutover_at": cutover,
                    "timezone": "Europe/Warsaw",
                    "legacy_source": "dynareporter",
                    "created_by_user_id": 7,
                    "updated_by_user_id": 7,
                    "created_at": now,
                    "updated_at": now,
                }
            ]
        )
    )

    result = await AnalyticsCutoverService(cast(AsyncSession, db)).set_cutover(
        module_key="board",
        payload=AnalyticsCutoverUpsert(
            cutover_at=datetime(2026, 6, 30, 22, tzinfo=timezone.utc)
        ),
        admin_user_id=7,
    )

    assert result.cutover_at == cutover
    assert result.created_by_user_id == result.updated_by_user_id == 7
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in sql


@dataclass
class _User:
    id: int = 42
    role: UserRole = UserRole.delivery_lead
    roles: list[str] = field(default_factory=list)

    def get_all_roles(self) -> set[UserRole]:
        values = {self.role}
        values.update(UserRole(role) for role in self.roles)
        return values

    def has_role(self, role: UserRole | str) -> bool:
        value = role.value if isinstance(role, UserRole) else str(role)
        return any(candidate.value == value for candidate in self.get_all_roles())

    def has_any_role(self, *roles: UserRole) -> bool:
        return any(self.has_role(role) for role in roles)


def _control_app(user: _User, db: _FakeSession) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/analytics/v1")
    app.dependency_overrides[get_current_user] = lambda: user

    async def _db_override():
        yield db

    app.dependency_overrides[get_db] = _db_override
    return app


def test_cutover_openapi_declares_auth_for_every_control_route() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/analytics/v1")
    spec = app.openapi()
    expected = {
        ("/api/analytics/v1/admin/legacy-snapshots/import", "post"),
        ("/api/analytics/v1/legacy-snapshots", "get"),
        ("/api/analytics/v1/admin/cutovers/{module_key}", "put"),
        ("/api/analytics/v1/cutovers", "get"),
        ("/api/analytics/v1/cutovers/{module_key}", "get"),
        ("/api/analytics/v1/cutovers/{module_key}/resolve", "get"),
    }

    for path, method in expected:
        assert spec["paths"][path][method].get("security"), (path, method)


@pytest.mark.asyncio
async def test_delivery_lead_can_read_cutovers_but_cannot_write() -> None:
    db = _FakeSession(_FakeResult(mappings=[]))
    app = _control_app(_User(), db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        read = await client.get("/api/analytics/v1/cutovers")
        write = await client.put(
            "/api/analytics/v1/admin/cutovers/board",
            json={"cutover_at": "2026-07-01T00:00:00+02:00"},
        )
        snapshot_write = await client.post(
            "/api/analytics/v1/admin/legacy-snapshots/import",
            json={"snapshots": [_snapshot().model_dump(mode="json")]},
        )

    assert read.status_code == 200, read.text
    assert read.json() == {"cutovers": []}
    assert write.status_code == 403, write.text
    assert snapshot_write.status_code == 403, snapshot_write.text


@pytest.mark.asyncio
async def test_tac_cannot_read_cutover_control_plane() -> None:
    app = _control_app(
        _User(role=UserRole.tac),
        _FakeSession(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/analytics/v1/cutovers")

    assert response.status_code == 403, response.text
