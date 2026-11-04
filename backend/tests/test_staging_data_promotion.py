"""Pure safety/atomicity tests; PostgreSQL acceptance lives in the *_db module."""

from __future__ import annotations

import argparse
import asyncio
import copy
import importlib.util
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.engine import URL, make_url
from sqlalchemy.sql.dml import Update

from app.services import staging_data_promotion as service


def selection(*records):
    return {
        "version": 1,
        "records": list(records)
        or [
            {
                "table": "clients",
                "pk": {"id": 1},
                "fields": ["notes"],
                "operation": "update",
            }
        ],
    }


def change(pk=1, before="old", after="edited"):
    return {
        "recipe": service.recipes.CLIENT_DESCRIPTIONS.policy_id,
        "table": "clients",
        "pk": {"id": pk},
        "fields": ["notes"],
        "operation": "update",
        "expected_before": {"notes": before},
        "desired_after": {"notes": after},
    }


def package(*changes):
    return service._seal(
        service._envelope(
            "package",
            baseline_digest="a" * 64,
            source_binding="b" * 64,
            changes=list(changes) or [change()],
        )
    )


def row(notes="old", **extra):
    return {"notes": notes, **service.CLIENT_GUARDS, **extra}


class MemoryConnection:
    """A small transaction double. Real SQL/constraints are covered on PG."""

    def __init__(self, rows):
        self.rows = rows
        self.audits = []
        self.writes = []
        self.events = []
        self.active = False
        self.engine = SimpleNamespace(
            url=make_url("postgresql+asyncpg://u:p@127.0.0.1/nexus_staging_unit")
        )
        self.dialect = SimpleNamespace(name="postgresql")

    def in_transaction(self):
        return self.active

    def begin(self):
        conn = self

        class Transaction:
            async def __aenter__(self):
                conn.active = True
                self.before = copy.deepcopy((conn.rows, conn.audits, conn.writes))

            async def __aexit__(self, kind, error, tb):
                conn.active = False
                if error:
                    conn.rows, conn.audits, conn.writes = self.before

        return Transaction()

    async def execute(self, statement):
        if isinstance(statement, Update):
            params = statement.compile().params
            pk = params["id_1"]
            self.events.append("write")
            self.writes.append(pk)
            self.rows[pk].update({k: v for k, v in params.items() if k != "id_1"})
        else:
            self.events.append(str(statement))


@pytest.fixture
def database(monkeypatch):
    conn = MemoryConnection(
        {1: row(), 2: row("second"), 99: row("unrelated new production row")}
    )
    table = Table(
        "clients",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("notes", String),
    )
    monkeypatch.setattr(service, "_binding", AsyncMock(return_value="target"))
    monkeypatch.setattr(service, "_tables", AsyncMock(return_value={"clients": table}))
    monkeypatch.setattr(service, "_actor", AsyncMock())
    monkeypatch.setattr(service, "_audit_schema", AsyncMock(return_value=object()))

    async def read(connection, table, record, lock=False):
        connection.events.append("locked_read" if lock else "read")
        return copy.deepcopy(connection.rows.get(record["pk"]["id"]))

    async def audit(connection, table, item, package_digest, preview_digest, actor_id):
        connection.audits.append(
            (item["pk"]["id"], actor_id, package_digest, preview_digest)
        )

    monkeypatch.setattr(service, "_read", read)
    monkeypatch.setattr(service, "_audit", audit)
    return conn


def test_canonical_digest_and_tampering():
    original = package()
    assert service.digest(dict(reversed(list(original.items())))) == original["digest"]
    original["changes"][0]["desired_after"]["notes"] = "changed after approval"
    with pytest.raises(service.PromotionError, match="artifact_digest_mismatch"):
        service.validate_package(original)


@pytest.mark.parametrize(
    "table,field,operation",
    [
        ("users", "email", "update"),
        ("clients", "status", "update"),
        ("clients", "name", "update"),
        ("clients", "external_id", "update"),
        ("clients", "notes", "delete"),
        ("clients", "notes", "insert"),
        ("candidates", "name", "update"),
        ("jobs", "description", "update"),
        ("clients; DROP TABLE users", "notes", "update"),
    ],
)
def test_positive_policy_denies_arbitrary_tables_identity_workflow_and_inserts(
    table, field, operation
):
    with pytest.raises(service.PromotionError):
        service.validate_selection(
            selection(
                {
                    "table": table,
                    "pk": {"id": 1},
                    "fields": [field],
                    "operation": operation,
                }
            )
        )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@production/nexus_staging_x",
        "postgresql+asyncpg://u:p@localhost/nexus",
        "postgresql+asyncpg://u:p@localhost/nexus_staging_",
        "postgresql+asyncpg://u:p@localhost/nexus_staging_x?host=production",
        "postgresql+asyncpg://u:p@/nexus_staging_x",
        "sqlite:///nexus_staging_x",
    ],
)
def test_source_loopback_and_staging_database_required(url):
    with pytest.raises(service.PromotionError, match="source_must_be_local_staging"):
        service.validate_source_url(url)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_local_named_staging_source_allowed(host):
    assert (
        service.validate_source_url(
            f"postgresql+asyncpg://u:p@{host}/nexus_staging_unit"
        ).database
        == "nexus_staging_unit"
    )


def test_snapshot_then_package_omits_unselected_and_unchanged_fields(database):
    async def exercise():
        baseline = await service.snapshot(
            database,
            selection(
                {"table": "clients", "pk": {"id": 1}, "fields": ["notes", "industry"]}
            ),
        )
        database.rows[1].update(notes="edited", name="unselected new name")
        result = await service.package(database, baseline)
        assert result["changes"] == [change()]
        assert "unselected new name" not in json.dumps(result)
        assert not database.writes

    database.rows[1]["industry"] = None
    asyncio.run(exercise())


def test_snapshot_rejects_nonwritable_record(database):
    database.rows[1]["hidden"] = True
    with pytest.raises(service.PromotionError, match="not_writable"):
        asyncio.run(service.snapshot(database, selection()))


def test_source_binding_rejects_another_clone(database):
    async def exercise():
        baseline = await service.snapshot(database, selection())
        baseline["source_binding"] = "another database"
        service._seal(baseline)
        with pytest.raises(service.PromotionError, match="source_binding_mismatch"):
            await service.package(database, baseline)

    asyncio.run(exercise())


def test_apply_preserves_unrelated_fields_and_new_production_records(database):
    async def exercise():
        artifact = package()
        preview = await service.preview(database, artifact, actor_id=7)
        database.rows[1]["website"] = "new unrelated production field"
        expected_unrelated = copy.deepcopy(database.rows[99])
        result = await service.apply(
            database, artifact, preview, preview["digest"], actor_id=7
        )
        assert result["applied"] == 1
        assert database.rows[1]["notes"] == "edited"
        assert database.rows[1]["website"] == "new unrelated production field"
        assert database.rows[99] == expected_unrelated
        assert database.audits[0][1:] == (7, artifact["digest"], preview["digest"])
        assert database.events.index("locked_read") < database.events.index("write")

    asyncio.run(exercise())


def test_concurrent_selected_field_conflict_before_any_write(database):
    async def exercise():
        artifact = package(change(), change(2, "second", "edited second"))
        preview = await service.preview(database, artifact, actor_id=7)
        database.rows[2]["notes"] = "concurrent production edit"
        with pytest.raises(service.ConflictError, match="promotion_conflict") as error:
            await service.apply(
                database, artifact, preview, preview["digest"], actor_id=7
            )
        assert error.value.conflicts == [
            {"operation_index": 1, "code": "field_conflict"}
        ]
        assert database.rows[1]["notes"] == "old"
        assert database.rows[2]["notes"] == "concurrent production edit"
        assert database.writes == database.audits == []

    asyncio.run(exercise())


def test_production_archive_after_preview_is_conflict(database):
    async def exercise():
        artifact = package()
        preview = await service.preview(database, artifact, actor_id=7)
        database.rows[1]["archived_at"] = "now"
        with pytest.raises(service.ConflictError):
            await service.apply(
                database, artifact, preview, preview["digest"], actor_id=7
            )
        assert database.writes == []

    asyncio.run(exercise())


def test_exact_desired_retry_no_writes_no_duplicate_audit(database):
    async def exercise():
        artifact = package()
        preview = await service.preview(database, artifact, actor_id=7)
        await service.apply(database, artifact, preview, preview["digest"], actor_id=7)
        result = await service.apply(
            database, artifact, preview, preview["digest"], actor_id=7
        )
        assert result["applied"] == 0 and result["already_applied"] == 1
        assert database.writes == [1] and len(database.audits) == 1
        database.rows[1]["notes"] = "later edit"
        with pytest.raises(service.ConflictError):
            await service.apply(
                database, artifact, preview, preview["digest"], actor_id=7
            )

    asyncio.run(exercise())


def test_failure_during_audit_rolls_back_every_business_write(database, monkeypatch):
    async def fail_audit(*args):
        raise RuntimeError("audit storage failed")

    monkeypatch.setattr(service, "_audit", fail_audit)

    async def exercise():
        artifact = package()
        preview = await service.preview(database, artifact, actor_id=7)
        with pytest.raises(RuntimeError):
            await service.apply(
                database, artifact, preview, preview["digest"], actor_id=7
            )
        assert database.rows[1]["notes"] == "old" and not database.writes

    asyncio.run(exercise())


def test_approval_binds_preview_not_just_package(database):
    async def exercise():
        artifact = package()
        preview = await service.preview(database, artifact, actor_id=7)
        for invalid in (artifact["digest"], "0" * 64, ""):
            with pytest.raises(
                service.PromotionError, match="approval_digest_mismatch"
            ):
                await service.apply(database, artifact, preview, invalid, actor_id=7)
        with pytest.raises(service.PromotionError, match="preview_actor_mismatch"):
            await service.apply(
                database, artifact, preview, preview["digest"], actor_id=8
            )
        assert not database.writes

    asyncio.run(exercise())


def test_expired_preview_requires_new_approval(database):
    async def exercise():
        artifact = package()
        preview = await service.preview(database, artifact, actor_id=7)
        preview["created_at"] = (service._now() - timedelta(hours=1)).isoformat()
        preview["expires_at"] = (service._now() - timedelta(minutes=45)).isoformat()
        service._seal(preview)
        with pytest.raises(service.PromotionError, match="preview_expired"):
            await service.apply(
                database, artifact, preview, preview["digest"], actor_id=7
            )
        assert not database.writes

    asyncio.run(exercise())


def test_remapped_production_binding_is_denied(database, monkeypatch):
    async def exercise():
        artifact = package()
        preview = await service.preview(database, artifact, actor_id=7)
        monkeypatch.setattr(
            service, "_binding", AsyncMock(return_value="different target")
        )
        with pytest.raises(service.PromotionError, match="target_binding_mismatch"):
            await service.apply(
                database, artifact, preview, preview["digest"], actor_id=7
            )
        assert not database.writes

    asyncio.run(exercise())


def test_secure_artifacts_outside_repository_and_no_overwrite(tmp_path):
    path = tmp_path / "private.json"
    service.write_artifact(path, package())
    assert path.stat().st_mode & 0o777 == 0o600
    assert service.read_artifact(path)["kind"] == "package"
    with pytest.raises(service.PromotionError, match="artifact_write_failed"):
        service.write_artifact(path, package())
    path.chmod(0o644)
    with pytest.raises(service.PromotionError, match="mode_0600"):
        service.read_artifact(path)
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").mkdir()
    with pytest.raises(service.PromotionError, match="outside_repository"):
        service.write_artifact(repository / "private.json", package())
    alias = tmp_path / "symlink.json"
    alias.symlink_to(path)
    with pytest.raises(service.PromotionError, match="symlink"):
        service.read_artifact(alias)


def _cli():
    spec = importlib.util.spec_from_file_location(
        "promotion_cli", Path(__file__).parents[1] / "scripts/staging_data_promotion.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_connection_errors_do_not_print_credentials_or_pii(monkeypatch, capsys):
    cli = _cli()
    secret = "DO_NOT_PRINT_SECRET"

    async def failing(args):
        raise RuntimeError(
            URL.create(
                "postgresql",
                username="user",
                password=secret,
                host="host",
                database="db",
            ).render_as_string(hide_password=False)
            + " private-person@example.test"
        )

    monkeypatch.setattr(cli, "run", failing)
    monkeypatch.setattr(
        "sys.argv",
        [
            "promotion",
            "preview",
            "--target-url-env",
            "TARGET",
            "--package",
            "p",
            "--out",
            "o",
            "--actor-id",
            "7",
        ],
    )
    assert cli.main() == 2
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert "private-person" not in output.out + output.err
    assert json.loads(output.out)["code"] == "database_or_io_operation_failed"


def test_cli_rejects_wrong_source_before_connect(monkeypatch):
    cli = _cli()
    monkeypatch.setenv("STAGING_UNIT_URL", "postgresql+asyncpg://u:p@127.0.0.1/nexus")
    connect = AsyncMock()
    monkeypatch.setattr(cli, "create_async_engine", connect)
    with pytest.raises(service.PromotionError, match="source_must_be_local_staging"):
        asyncio.run(
            cli.run(
                argparse.Namespace(
                    command="snapshot", source_url_env="STAGING_UNIT_URL"
                )
            )
        )
    connect.assert_not_called()


def test_artifact_directory_symlink_and_parent_traversal_denied(tmp_path):
    tmp_path = tmp_path.resolve()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    target = private / "manifest.json"
    service.write_artifact(target, package())
    alias = tmp_path / "directory-link"
    alias.symlink_to(private, target_is_directory=True)
    for action in (
        lambda: service.read_artifact(alias / "manifest.json"),
        lambda: service.write_artifact(alias / "new.json", package()),
        lambda: service.read_artifact(private / ".." / "private" / "manifest.json"),
    ):
        with pytest.raises(service.PromotionError, match="symlink|traversal"):
            action()
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").mkdir()
    repo_alias = tmp_path / "repository-link"
    repo_alias.symlink_to(repository, target_is_directory=True)
    with pytest.raises(service.PromotionError, match="symlink"):
        service.write_artifact(repo_alias / "manifest.json", package())


def test_artifact_writable_by_other_users_parent_denied(tmp_path):
    tmp_path = tmp_path.resolve()
    directory = tmp_path / "insecure"
    directory.mkdir(mode=0o700)
    directory.chmod(0o777)
    try:
        with pytest.raises(service.PromotionError, match="not_writable_by_others"):
            service.write_artifact(directory / "manifest.json", package())
    finally:
        directory.chmod(0o700)


def test_preview_expiring_while_waiting_for_row_locks_never_writes(
    database, monkeypatch
):
    async def exercise():
        artifact = package()
        preview = await service.preview(database, artifact, actor_id=7)
        original = service._inspect_state

        async def waited(*args, **kwargs):
            result = await original(*args, **kwargs)
            monkeypatch.setattr(
                service,
                "_now",
                lambda: (
                    service._parse_time(preview["expires_at"]) + timedelta(seconds=1)
                ),
            )
            return result

        monkeypatch.setattr(service, "_inspect_state", waited)
        with pytest.raises(service.PromotionError, match="preview_expired"):
            await service.apply(
                database, artifact, preview, preview["digest"], actor_id=7
            )
        assert database.writes == database.audits == []

    asyncio.run(exercise())


def test_real_sqlalchemy_column_collection_guard_checks(monkeypatch):
    """ColumnCollection.keys is a list, unlike dict.keys: do not mock guards."""
    from sqlalchemy import Boolean, DateTime, JSON

    clients = Table(
        "clients",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("notes", String),
        Column("hidden", Boolean),
        Column("merged_into_client_id", Integer),
        Column("archived_at", DateTime),
        Column("deleted_at", DateTime),
    )
    users = Table(
        "users",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("roles", JSON),
        Column("is_active", Boolean),
    )
    audit = Table(
        "activities",
        MetaData(),
        *[
            Column(name, JSON if name == "details" else String)
            for name in (
                "entity_type",
                "entity_id",
                "action",
                "user_id",
                "external_source",
                "details",
            )
        ],
    )
    monkeypatch.setattr(
        service,
        "Table",
        lambda name, *args, **kwargs: {
            "clients": clients,
            "users": users,
            "activities": audit,
        }[name],
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def mappings(self):
            return self

        def one_or_none(self):
            return self.value

    class Connection:
        async def run_sync(self, callback):
            return callback(SimpleNamespace(scalar=lambda statement: "public"))

        async def execute(self, statement):
            if "users" in str(statement):
                return Result({"roles": ["admin"], "is_active": True})
            return Result(row())

    async def exercise():
        conn = Connection()
        tables = await service._tables(conn, {"clients"})
        assert tables["clients"] is clients
        assert await service._read(conn, clients, selection()["records"][0]) == row()
        await service._actor(conn, 7, lock=True)
        assert await service._audit_schema(conn, tables) is audit

    asyncio.run(exercise())


def test_typed_wire_roundtrips_without_decimal_precision_or_json_shape_loss():
    from datetime import date, datetime, timezone
    from decimal import Decimal, localcontext
    from uuid import UUID

    Field = service.recipes.FieldPolicy
    values = [
        (Field(kind="boolean"), True),
        (Field(kind="integer"), 2**63 - 1),
        (
            Field(kind="decimal"),
            Decimal("123456789012345678901234567890.1234567890123456789"),
        ),
        (Field(kind="date"), date(2026, 10, 22)),
        (Field(kind="datetime"), datetime(2026, 10, 22, 17, 15, tzinfo=timezone.utc)),
        (Field(kind="uuid"), UUID(int=42)),
        (
            Field(kind="json"),
            {
                "$nexus_type": "decimal",
                "value": "domain data",
                "number": Decimal("12345678901234567890.1234567890123456789"),
                "flags": [True, None, 10],
            },
        ),
    ]
    with localcontext() as context:
        context.prec = 4
        for policy, value in values:
            wire = service.encode_value(policy, value)
            assert service.decode_value(policy, wire) == value
            assert json.loads(json.dumps(wire)) == wire
    with pytest.raises(service.PromotionError):
        service.encode_value(Field(kind="decimal"), 1.2)
    with pytest.raises(service.PromotionError):
        service.encode_value(Field(kind="integer"), True)
    with pytest.raises(service.PromotionError):
        service.encode_value(Field(kind="json"), {"lossy": 1.2})


def test_database_json_raw_text_preserves_exact_numbers_and_json_null():
    from decimal import Decimal

    policy = service.recipes.FieldPolicy(kind="json")
    raw = '{"amount":12345678901234567890.123456789012345678901,"$nexus_type":"json","value":{"a":true}}'
    wire = service.encode_value(policy, raw, json_from_database=True)
    decoded = service.decode_value(policy, wire)
    assert decoded["amount"] == Decimal("12345678901234567890.123456789012345678901")
    assert decoded["value"] == {"a": True}
    assert service.encode_value(policy, None, json_from_database=True) is None
    json_null = service.encode_value(policy, "null", json_from_database=True)
    assert json_null == {"$nexus_type": "json", "value": "null"}
    assert service.decode_value(policy, json_null) is service.recipes.JSON_NULL
    with pytest.raises(service.PromotionError):
        service.decode_value(
            service.recipes.FieldPolicy(kind="decimal"),
            {"$nexus_type": "decimal", "value": "1.00"},
        )


def test_schema_fingerprint_material_changes_for_columns_and_constraints():
    from sqlalchemy import Boolean, UniqueConstraint

    metadata = MetaData()
    table = Table(
        "records",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("label", String(50)),
    )
    first = service.digest({"schema": service._schema_shape({"records": table})})
    table.append_column(Column("enabled", Boolean, nullable=False))
    second = service.digest({"schema": service._schema_shape({"records": table})})
    assert first != second
    table.append_constraint(UniqueConstraint("label", name="uq_records_label"))
    assert second != service.digest(
        {"schema": service._schema_shape({"records": table})}
    )


def test_artifacts_pin_exact_reviewed_recipe_version_and_fingerprint(monkeypatch):
    from dataclasses import replace

    artifact = package()
    newer = replace(service.recipes.CLIENT_DESCRIPTIONS, version=2)
    monkeypatch.setattr(
        service.recipes, "DEFAULT_REGISTRY", service.recipes.RecipeRegistry([newer])
    )
    with pytest.raises(service.PromotionError, match="policy_changed"):
        service.validate_package(artifact)


async def _synthetic_insert_handler(conn, table, operation):
    await conn.execute(
        table.insert().values(
            id=operation["pk"]["id"], retired=False, **operation["decoded_values"]
        )
    )


def _synthetic_recipe():
    return service.recipes.Recipe(
        recipe_id="reviewed-descriptions",
        version=1,
        table="business_records",
        entity_type="business_record",
        fields={
            "label": service.recipes.FieldPolicy(
                100, nullable=False, required_for_insert=True
            )
        },
        lifecycle={"retired": False},
        operations=frozenset({"update", "insert"}),
        insert_handler=_synthetic_insert_handler,
        review_reference="repo:synthetic-acceptance-only",
        preconditions=("target absent for creation",),
        constraints=("database constraints",),
        postapply_requirements=("created row exact projection and audit receipt",),
    )


def test_registry_drives_new_module_insert_without_engine_table_changes(
    database, monkeypatch
):
    from sqlalchemy import Boolean
    from sqlalchemy.sql.dml import Insert

    recipe = _synthetic_recipe()
    monkeypatch.setattr(
        service.recipes,
        "DEFAULT_REGISTRY",
        service.recipes.RecipeRegistry([service.recipes.CLIENT_DESCRIPTIONS, recipe]),
    )
    table = Table(
        "business_records",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("label", String),
        Column("retired", Boolean),
    )
    monkeypatch.setattr(
        service, "_tables", AsyncMock(return_value={"business_records": table})
    )
    original_execute = database.execute

    async def execute(statement):
        if isinstance(statement, Insert):
            values = statement.compile().params
            pk = values.pop("id")
            assert pk not in database.rows
            database.rows[pk] = values
            database.writes.append(pk)
        else:
            await original_execute(statement)

    monkeypatch.setattr(database, "execute", execute)

    async def receipt(conn, change, digest, table):
        return any(
            audit[0] == change["pk"]["id"] and audit[2] == digest
            for audit in conn.audits
        )

    monkeypatch.setattr(service, "_has_insert_receipt", receipt)
    request = {
        "version": 1,
        "records": [
            {
                "recipe": recipe.recipe_id,
                "table": recipe.table,
                "pk": {"id": 10},
                "fields": ["label"],
                "operation": "insert",
            }
        ],
    }

    async def exercise():
        baseline = await service.snapshot(database, request)
        assert baseline["records"][0]["expected_before"] is None
        database.rows[10] = {"label": "approved new data", "retired": False}
        artifact = await service.package(database, baseline)
        del database.rows[10]
        plan = await service.preview(database, artifact, actor_id=7)
        result = await service.apply(
            database, artifact, plan, plan["digest"], actor_id=7
        )
        assert (
            result["applied"] == 1 and database.rows[10]["label"] == "approved new data"
        )
        repeated = await service.apply(
            database, artifact, plan, plan["digest"], actor_id=7
        )
        assert repeated["applied"] == 0 and len(database.audits) == 1
        database.audits.clear()
        # An identical foreign row is not proof of a successful previous insert.
        collision = await service.preview(database, artifact, actor_id=7)
        assert collision["conflicts"] == [
            {"operation_index": 0, "code": "insert_primary_key_exists"}
        ]
        with pytest.raises(service.ConflictError):
            await service.apply(
                database, artifact, collision, collision["digest"], actor_id=7
            )

    asyncio.run(exercise())


def test_cli_lists_only_reviewed_recipes_without_database(monkeypatch, capsys):
    cli = _cli()
    monkeypatch.setattr("sys.argv", ["promotion", "--list-recipes"])
    monkeypatch.setattr(
        cli,
        "create_async_engine",
        lambda *a, **k: pytest.fail("listing must not connect"),
    )
    assert cli.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["recipes"][0]["id"] == "client-descriptions"
    assert output["recipes"][0]["operations"] == ["update"]


def test_json_database_binding_distinguishes_sql_null_from_json_null(monkeypatch):
    from sqlalchemy.dialects import postgresql

    recipe = service.recipes.Recipe(
        recipe_id="json-descriptions",
        version=1,
        table="json_records",
        entity_type="json_record",
        fields={"payload": service.recipes.FieldPolicy(kind="json")},
        review_reference="repo:synthetic-json-null-acceptance",
        preconditions=("exact before",),
        constraints=("postgresql json type",),
        postapply_requirements=("audit and exact projection",),
    )
    monkeypatch.setattr(
        service.recipes, "DEFAULT_REGISTRY", service.recipes.RecipeRegistry([recipe])
    )
    table = Table(
        "json_records",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("payload", postgresql.JSONB),
    )
    record = {
        "recipe": recipe.policy_id,
        "table": recipe.table,
        "operation": "update",
        "pk": {"id": 1},
        "fields": ["payload"],
        "desired_after": {"payload": None},
    }
    sql_null = service._db_values(record, table)["payload"]
    assert str(sql_null.compile(dialect=postgresql.dialect())) == "NULL"
    record["desired_after"]["payload"] = {"$nexus_type": "json", "value": "null"}
    json_null = service._db_values(record, table)["payload"].compile(
        dialect=postgresql.dialect()
    )
    assert "CAST(" in str(json_null) and "AS JSONB)" in str(json_null)
    assert list(json_null.params.values()) == ["null"]


def test_not_null_json_document_null_is_distinct_from_forbidden_sql_null():
    policy = service.recipes.FieldPolicy(kind="json", nullable=False)
    expected = {"$nexus_type": "json", "value": "null"}
    assert service.encode_value(policy, "null", json_from_database=True) == expected
    assert service.decode_value(policy, expected) is service.recipes.JSON_NULL
    assert service.encode_value(policy, service.recipes.JSON_NULL) == expected
    with pytest.raises(service.PromotionError):
        service.encode_value(policy, None)
    with pytest.raises(service.PromotionError):
        service.decode_value(policy, None)
