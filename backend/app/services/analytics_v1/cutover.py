"""Immutable legacy snapshot import and live/legacy cutover resolution."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    and_,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.cutover_schemas import (
    AnalyticsCutoverResolution,
    AnalyticsCutoverRow,
    AnalyticsCutoverUpsert,
    AnalyticsDataSource,
    LegacySnapshotImportItem,
    LegacySnapshotImportResult,
    LegacySnapshotList,
    LegacySnapshotRow,
    MODULE_KEY_PATTERN,
    WARSAW_TIMEZONE,
)
from app.analytics.periods import AnalyticsPeriod, WARSAW


_metadata = MetaData()
_module_key_re = re.compile(MODULE_KEY_PATTERN)

_snapshots = Table(
    "analytics_metric_snapshots",
    _metadata,
    Column("id", BigInteger, primary_key=True),
    Column("snapshot_key", String(255), nullable=False, unique=True),
    Column("metric_key", String(128), nullable=False),
    Column("metric_version", String(32), nullable=False),
    Column("scope", String(64), nullable=False),
    Column("scope_ref", String(128)),
    Column("period_start", DateTime(timezone=True), nullable=False),
    Column("period_end", DateTime(timezone=True), nullable=False),
    Column("timezone", String(64), nullable=False),
    Column("data", JSONB, nullable=False),
    Column("source", String(64), nullable=False),
    Column("source_ref", String(255)),
    Column("checksum", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

_cutovers = Table(
    "analytics_cutovers",
    _metadata,
    Column("module_key", String(64), primary_key=True),
    Column("cutover_at", DateTime(timezone=True), nullable=False),
    Column("timezone", String(64), nullable=False),
    Column("legacy_source", String(64), nullable=False),
    Column("created_by_user_id", BigInteger),
    Column("updated_by_user_id", BigInteger),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class PreparedSnapshot:
    item: LegacySnapshotImportItem
    snapshot_key: str
    checksum: str

    def insert_values(self) -> dict:
        return {
            "snapshot_key": self.snapshot_key,
            "metric_key": self.item.metric_key,
            "metric_version": self.item.metric_version,
            "scope": self.item.scope,
            "scope_ref": self.item.scope_ref,
            "period_start": self.item.period_start,
            "period_end": self.item.period_end,
            "timezone": self.item.timezone,
            "data": self.item.data,
            "source": self.item.source,
            "source_ref": self.item.source_ref,
            "checksum": self.checksum,
        }


class CutoverBoundaryError(ValueError):
    """Raised when one aggregate would combine legacy and live data."""

    def __init__(
        self,
        *,
        module_key: str,
        period: AnalyticsPeriod,
        cutover_at: datetime,
    ) -> None:
        self.module_key = module_key
        self.period = period
        self.cutover_at = cutover_at
        super().__init__(
            f"Period [{period.start.isoformat()}, {period.end.isoformat()}) "
            f"crosses {module_key!r} cutover at {cutover_at.isoformat()}"
        )


def validate_module_key(module_key: str) -> str:
    if _module_key_re.fullmatch(module_key) is None:
        raise ValueError("invalid analytics module_key")
    return module_key


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot timestamps must include a UTC offset")
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _snapshot_identity(item: LegacySnapshotImportItem) -> dict:
    return {
        "metric_key": item.metric_key,
        "metric_version": item.metric_version,
        "scope": item.scope,
        "scope_ref": item.scope_ref,
        "period_start": _utc_iso(item.period_start),
        "period_end": _utc_iso(item.period_end),
        "timezone": item.timezone,
        "source": item.source,
        "source_ref": item.source_ref,
    }


def snapshot_key_for(item: LegacySnapshotImportItem) -> str:
    """Stable identity key; corrected content becomes a reported conflict."""

    digest = hashlib.sha256(_canonical_json(_snapshot_identity(item))).hexdigest()
    return f"legacy:v1:{digest}"


def snapshot_checksum(item: LegacySnapshotImportItem) -> str:
    payload = {**_snapshot_identity(item), "data": item.data}
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def prepare_snapshot(item: LegacySnapshotImportItem) -> PreparedSnapshot:
    return PreparedSnapshot(
        item=item,
        snapshot_key=snapshot_key_for(item),
        checksum=snapshot_checksum(item),
    )


def validate_month_start(cutover_at: datetime) -> datetime:
    """Return canonical Warsaw month start or reject the timestamp."""

    if cutover_at.tzinfo is None or cutover_at.utcoffset() is None:
        raise ValueError("cutover_at must include a UTC offset")
    local = cutover_at.astimezone(WARSAW)
    expected = datetime(local.year, local.month, 1, tzinfo=WARSAW)
    if local != expected:
        raise ValueError(
            "cutover_at must be the first day of a full month at 00:00 "
            f"in {WARSAW_TIMEZONE}"
        )
    return expected


def resolve_cutover_source(
    *,
    module_key: str,
    period: AnalyticsPeriod,
    cutover_at: datetime | None,
    legacy_source: str | None = None,
) -> AnalyticsCutoverResolution:
    """Select one source for the entire half-open period, never a blend."""

    validate_module_key(module_key)
    if (
        period.start.tzinfo is None
        or period.start.utcoffset() is None
        or period.end.tzinfo is None
        or period.end.utcoffset() is None
    ):
        raise ValueError("analytics period timestamps must be timezone-aware")
    if period.end <= period.start:
        raise ValueError("analytics period end must be later than its start")
    if cutover_at is None:
        return AnalyticsCutoverResolution(
            module_key=module_key,
            source=AnalyticsDataSource.live_ats,
            period_start=period.start,
            period_end=period.end,
            cutover_at=None,
            legacy_source=None,
        )

    canonical_cutover = validate_month_start(cutover_at)
    if period.end <= canonical_cutover:
        source = AnalyticsDataSource.legacy_snapshot
    elif period.start >= canonical_cutover:
        source = AnalyticsDataSource.live_ats
    else:
        raise CutoverBoundaryError(
            module_key=module_key,
            period=period,
            cutover_at=canonical_cutover,
        )
    return AnalyticsCutoverResolution(
        module_key=module_key,
        source=source,
        period_start=period.start,
        period_end=period.end,
        cutover_at=canonical_cutover,
        legacy_source=(
            legacy_source if source is AnalyticsDataSource.legacy_snapshot else None
        ),
    )


class AnalyticsCutoverService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _existing_checksums(self, keys: Iterable[str]) -> dict[str, str]:
        unique_keys = sorted(set(keys))
        if not unique_keys:
            return {}
        result = await self.db.execute(
            select(_snapshots.c.snapshot_key, _snapshots.c.checksum).where(
                _snapshots.c.snapshot_key.in_(unique_keys)
            )
        )
        return {
            str(row["snapshot_key"]): str(row["checksum"])
            for row in result.mappings().all()
        }

    async def import_legacy_snapshots(
        self,
        items: Sequence[LegacySnapshotImportItem],
    ) -> LegacySnapshotImportResult:
        """Batch import with idempotency and race-safe conflict detection."""

        if not 1 <= len(items) <= 1000:
            raise ValueError("snapshot batch must contain between 1 and 1000 items")

        prepared_groups: dict[str, list[PreparedSnapshot]] = defaultdict(list)
        for item in items:
            prepared = prepare_snapshot(item)
            prepared_groups[prepared.snapshot_key].append(prepared)

        inserted = 0
        skipped = 0
        conflicts = 0
        inserted_keys: set[str] = set()
        skipped_keys: set[str] = set()
        conflict_keys: set[str] = set()
        candidates: dict[str, tuple[PreparedSnapshot, int]] = {}
        consistent_groups: dict[str, list[PreparedSnapshot]] = {}

        for key, group in prepared_groups.items():
            checksums = {prepared.checksum for prepared in group}
            if len(checksums) != 1:
                conflicts += len(group)
                conflict_keys.add(key)
                continue
            consistent_groups[key] = group

        existing = await self._existing_checksums(consistent_groups)
        for key, group in consistent_groups.items():
            representative = group[0]
            existing_checksum = existing.get(key)
            if existing_checksum == representative.checksum:
                skipped += len(group)
                skipped_keys.add(key)
            elif existing_checksum is not None:
                conflicts += len(group)
                conflict_keys.add(key)
            else:
                candidates[key] = (representative, len(group))

        if candidates:
            insert_statement = (
                pg_insert(_snapshots)
                .values(
                    [
                        prepared.insert_values()
                        for prepared, _count in candidates.values()
                    ]
                )
                .on_conflict_do_nothing(index_elements=["snapshot_key"])
                .returning(_snapshots.c.snapshot_key)
            )
            inserted_result = await self.db.execute(insert_statement)
            actually_inserted = {str(key) for key in inserted_result.scalars().all()}
            for key in actually_inserted:
                _prepared, occurrences = candidates[key]
                inserted += 1
                skipped += occurrences - 1
                inserted_keys.add(key)
                if occurrences > 1:
                    skipped_keys.add(key)

            raced_keys = set(candidates) - actually_inserted
            raced = await self._existing_checksums(raced_keys)
            for key in raced_keys:
                prepared, occurrences = candidates[key]
                if raced.get(key) == prepared.checksum:
                    skipped += occurrences
                    skipped_keys.add(key)
                else:
                    # Fail closed if a concurrent writer stored different data
                    # or the conflicting row disappeared before verification.
                    conflicts += occurrences
                    conflict_keys.add(key)

        return LegacySnapshotImportResult(
            total=len(items),
            inserted=inserted,
            skipped=skipped,
            conflicts=conflicts,
            inserted_keys=sorted(inserted_keys),
            skipped_keys=sorted(skipped_keys),
            conflict_keys=sorted(conflict_keys),
        )

    async def list_snapshots(
        self,
        *,
        metric_key: str | None,
        scope: str | None,
        source: str | None,
        limit: int,
        offset: int,
    ) -> LegacySnapshotList:
        filters = []
        if metric_key is not None:
            filters.append(_snapshots.c.metric_key == metric_key)
        if scope is not None:
            filters.append(_snapshots.c.scope == scope)
        if source is not None:
            filters.append(_snapshots.c.source == source)
        statement = select(
            _snapshots.c.snapshot_key,
            _snapshots.c.metric_key,
            _snapshots.c.metric_version,
            _snapshots.c.scope,
            _snapshots.c.scope_ref,
            _snapshots.c.period_start,
            _snapshots.c.period_end,
            _snapshots.c.timezone,
            _snapshots.c.data,
            _snapshots.c.source,
            _snapshots.c.source_ref,
            _snapshots.c.checksum,
            _snapshots.c.created_at,
        )
        if filters:
            statement = statement.where(and_(*filters))
        statement = (
            statement.order_by(
                _snapshots.c.period_start.desc(),
                _snapshots.c.snapshot_key,
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(statement)
        return LegacySnapshotList(
            snapshots=[
                LegacySnapshotRow(**dict(row)) for row in result.mappings().all()
            ],
            limit=limit,
            offset=offset,
        )

    async def set_cutover(
        self,
        *,
        module_key: str,
        payload: AnalyticsCutoverUpsert,
        admin_user_id: int,
    ) -> AnalyticsCutoverRow:
        validate_module_key(module_key)
        cutover_at = validate_month_start(payload.cutover_at)
        base_insert = pg_insert(_cutovers).values(
            module_key=module_key,
            cutover_at=cutover_at,
            timezone=payload.timezone,
            legacy_source=payload.legacy_source,
            created_by_user_id=admin_user_id,
            updated_by_user_id=admin_user_id,
        )
        statement = base_insert.on_conflict_do_update(
            index_elements=["module_key"],
            set_={
                "cutover_at": base_insert.excluded.cutover_at,
                "timezone": base_insert.excluded.timezone,
                "legacy_source": base_insert.excluded.legacy_source,
                "updated_by_user_id": admin_user_id,
                "updated_at": func.now(),
            },
        ).returning(*_cutovers.c)
        result = await self.db.execute(statement)
        return AnalyticsCutoverRow(**dict(result.mappings().one()))

    async def get_cutover(self, module_key: str) -> AnalyticsCutoverRow | None:
        validate_module_key(module_key)
        result = await self.db.execute(
            select(_cutovers).where(_cutovers.c.module_key == module_key)
        )
        row = result.mappings().one_or_none()
        return AnalyticsCutoverRow(**dict(row)) if row is not None else None

    async def list_cutovers(self) -> list[AnalyticsCutoverRow]:
        result = await self.db.execute(
            select(_cutovers).order_by(_cutovers.c.module_key)
        )
        return [AnalyticsCutoverRow(**dict(row)) for row in result.mappings().all()]

    async def resolve(
        self,
        *,
        module_key: str,
        period: AnalyticsPeriod,
    ) -> AnalyticsCutoverResolution:
        cutover = await self.get_cutover(module_key)
        return resolve_cutover_source(
            module_key=module_key,
            period=period,
            cutover_at=cutover.cutover_at if cutover else None,
            legacy_source=cutover.legacy_source if cutover else None,
        )
