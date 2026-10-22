"""PostgreSQL acceptance tests using synthetic rows in disposable schemas.

Uses the existing CI postgres:16 service. No production models, backups, credentials,
or external services are needed; standalone execution may use ``--noconftest``.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.services import staging_data_promotion as promotion
from app.services import staging_promotion_recipes as recipes


def _test_database_url():
    raw = os.environ.get("STAGING_PROMOTION_TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL"
    )
    if not raw:
        pytest.fail(
            "Opt-in PostgreSQL acceptance requires an explicit test database URL"
        )
    url = make_url(raw)
    if (
        url.get_backend_name() != "postgresql"
        or url.query
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not url.database
        or not (
            url.database.startswith("nexus_staging_") and url.database.endswith("_test")
        )
    ):
        pytest.fail("Synthetic tests require a loopback nexus_staging_*_test database")
    return url.set(drivername="postgresql+asyncpg")


def test_database_url_query_overrides_cannot_escape_loopback(monkeypatch):
    monkeypatch.setenv(
        "STAGING_PROMOTION_TEST_DATABASE_URL",
        "postgresql+asyncpg://127.0.0.1/nexus_staging_guard_test?host=production.example",
    )
    with pytest.raises(pytest.fail.Exception, match="loopback"):
        _test_database_url()


@pytest_asyncio.fixture
async def promotion_db():
    """A fresh namespace protects the app schema, even in shared CI databases."""
    if os.environ.get("STAGING_PROMOTION_DB_ACCEPTANCE") != "1":
        pytest.skip("Dedicated synthetic PostgreSQL acceptance job owns these checks")
    url = _test_database_url()
    schema = "promotion_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    isolated = None
    try:
        async with admin.begin() as conn:
            version = int(await conn.scalar(text("SHOW server_version_num")))
            assert version >= 160000, "Acceptance requires PostgreSQL 16 or newer"
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = create_async_engine(
            url,
            connect_args={"server_settings": {"search_path": schema}},
        )
        async with isolated.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE clients ("
                    "id integer PRIMARY KEY, name varchar(255) DEFAULT 'Synthetic', "
                    "industry varchar(100) UNIQUE, website varchar(500), address text, "
                    "notes text CHECK (notes IS DISTINCT FROM 'reject-write'), "
                    "status text NOT NULL DEFAULT 'prospect', "
                    "hidden boolean NOT NULL DEFAULT false, "
                    "nda_signed boolean NOT NULL DEFAULT false, "
                    "external_source text DEFAULT 'manual', "
                    "merged_into_client_id integer, archived_at timestamptz, deleted_at timestamptz)"
                )
            )
            await conn.execute(
                text(
                    "CREATE TABLE users (id integer PRIMARY KEY, is_active boolean NOT NULL, roles jsonb NOT NULL)"
                )
            )
            await conn.execute(
                text("INSERT INTO users VALUES (101,true,'[\"admin\"]'::jsonb)")
            )
            await conn.execute(
                text(
                    "CREATE TABLE activities (id serial PRIMARY KEY, entity_type text, entity_id integer, "
                    "action text, user_id integer, external_source text, details jsonb, "
                    "created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now())"
                )
            )
            await conn.execute(
                text(
                    "CREATE TABLE alembic_version (version_num varchar(64) PRIMARY KEY)"
                )
            )
            await conn.execute(
                text("INSERT INTO alembic_version VALUES ('synthetic_acceptance_head')")
            )
        yield isolated
    finally:
        if isolated is not None:
            await isolated.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def _execute(engine, sql, params=None):
    async with engine.begin() as conn:
        await conn.execute(text(sql), params or {})


async def _rows(engine):
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, industry, notes FROM clients ORDER BY id")
        )
        return [dict(row) for row in result.mappings()]


async def _artifact(engine, action, *args, **kwargs):
    async with engine.connect() as conn:
        return await action(conn, *args, **kwargs)


def _selection(*records):
    return {"version": 1, "records": list(records)}


def _record(pk, fields=("industry",), operation="update"):
    return {
        "table": "clients",
        "pk": {"id": pk},
        "fields": list(fields),
        "operation": operation,
    }


async def _update_package(engine, changes):
    """Simulate baseline → local edits → package, then restore target baseline."""
    for pk in changes:
        await _execute(
            engine,
            "INSERT INTO clients (id, industry, notes) VALUES (:id, :name, :notes)",
            {"id": pk, "name": f"Baseline {pk}", "notes": f"Untouched {pk}"},
        )
    baseline = await _artifact(
        engine, promotion.snapshot, _selection(*(_record(pk) for pk in changes))
    )
    for pk, name in changes.items():
        await _execute(
            engine,
            "UPDATE clients SET industry=:name WHERE id=:id",
            {"id": pk, "name": name},
        )
    package = await _artifact(engine, promotion.package, baseline)
    for pk in changes:
        await _execute(
            engine,
            "UPDATE clients SET industry=:name WHERE id=:id",
            {"id": pk, "name": f"Baseline {pk}"},
        )
    return package


async def _apply(engine, package, preview):
    return await _artifact(
        engine, promotion.apply, package, preview, preview["digest"], actor_id=101
    )


async def _preview(engine, package):
    return await _artifact(engine, promotion.preview, package, actor_id=101)


@pytest_asyncio.fixture
async def reviewed_module(promotion_db, monkeypatch):
    """A repo-authored test recipe proves extension without any CLI code loader."""
    async with promotion_db.begin() as conn:
        await conn.execute(text("CREATE TABLE recipe_parents (code text PRIMARY KEY)"))
        await conn.execute(
            text("INSERT INTO recipe_parents VALUES ('synthetic-parent')")
        )
        await conn.execute(
            text(
                "CREATE TABLE recipe_tags (id integer PRIMARY KEY, label text NOT NULL UNIQUE, "
                "parent_code text NOT NULL REFERENCES recipe_parents(code), "
                "retired boolean NOT NULL DEFAULT false, domain_state text NOT NULL)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE recipe_events (id serial PRIMARY KEY, tag_id integer NOT NULL "
                "REFERENCES recipe_tags(id), event text NOT NULL)"
            )
        )

    async def validate_domain(conn, operation):
        values = operation["decoded_values"]
        if values.get("label") == "domain-denied":
            raise promotion.PromotionError("synthetic_domain_validation_failed")

    async def insert_handler(conn, table, operation):
        await conn.execute(
            table.insert().values(
                **operation["pk"],
                **operation["decoded_values"],
                domain_state="reviewed",
            )
        )

    async def after_apply(conn, operation):
        await conn.execute(
            text(
                "INSERT INTO recipe_events(tag_id,event) VALUES (:id,'domain-created')"
            ),
            {"id": operation["pk"]["id"]},
        )
        if operation["decoded_values"].get("label") == "fail-after-domain-write":
            raise promotion.PromotionError("synthetic_postapply_failure")

    recipe = recipes.Recipe(
        recipe_id="synthetic-reviewed-tags",
        version=1,
        table="recipe_tags",
        entity_type="synthetic_tag",
        fields={
            "label": recipes.FieldPolicy(
                max_length=100, nullable=False, required_for_insert=True
            ),
            "parent_code": recipes.FieldPolicy(
                max_length=100, nullable=False, required_for_insert=True
            ),
        },
        operations=frozenset({"update", "insert"}),
        lifecycle={"retired": False},
        review_reference="repo:backend/tests/test_staging_data_promotion_db.py",
        preconditions=(
            "Explicit reviewed synthetic recipe, never a CLI-loaded module",
        ),
        constraints=("Parent FK and label uniqueness are enforced by PostgreSQL",),
        postapply_requirements=(
            "Create domain event and normal promotion audit atomically",
        ),
        validate_domain=validate_domain,
        insert_handler=insert_handler,
        after_apply=after_apply,
    )
    registry = recipes.RecipeRegistry([*recipes.DEFAULT_REGISTRY.values(), recipe])
    monkeypatch.setattr(recipes, "DEFAULT_REGISTRY", registry)
    return promotion_db


def _recipe_insert_record(pk=10):
    return {
        "recipe": "synthetic-reviewed-tags",
        "table": "recipe_tags",
        "pk": {"id": pk},
        "fields": ["label", "parent_code"],
        "operation": "insert",
    }


async def _recipe_insert_package(
    engine, label="Reviewed local tag", include_client=True
):
    records = [_recipe_insert_record()]
    if include_client:
        await _execute(
            engine, "INSERT INTO clients(id,industry,notes) VALUES (1,'Before','Keep')"
        )
        records.append(_record(1))
    baseline = await _artifact(engine, promotion.snapshot, _selection(*records))
    await _execute(
        engine,
        "INSERT INTO recipe_tags(id,label,parent_code,domain_state) VALUES (10,:label,'synthetic-parent','reviewed')",
        {"label": label},
    )
    if include_client:
        await _execute(
            engine, "UPDATE clients SET industry='Local reviewed update' WHERE id=1"
        )
    package = await _artifact(engine, promotion.package, baseline)
    await _execute(engine, "DELETE FROM recipe_tags WHERE id=10")
    if include_client:
        await _execute(engine, "UPDATE clients SET industry='Before' WHERE id=1")
    return package


async def _module_rows(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id,label,parent_code,domain_state FROM recipe_tags ORDER BY id"
            )
        )
        return [dict(row) for row in rows.mappings()]


async def _assert_no_partial_promotion(engine):
    assert await _rows(engine) == [{"id": 1, "industry": "Before", "notes": "Keep"}]
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM activities")) == 0
        assert await conn.scalar(text("SELECT count(*) FROM recipe_events")) == 0


@pytest_asyncio.fixture
async def reviewed_finance(promotion_db, monkeypatch):
    async with promotion_db.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE recipe_finance (id integer PRIMARY KEY, amount numeric(24,8) NOT NULL, "
                "enabled boolean NOT NULL, payload jsonb, effective_on date NOT NULL, "
                "observed_at timestamptz NOT NULL, external_id uuid NOT NULL, quantity bigint NOT NULL, "
                "archived boolean NOT NULL DEFAULT false)"
            )
        )
    recipe = recipes.Recipe(
        recipe_id="synthetic-reviewed-finance",
        version=1,
        table="recipe_finance",
        entity_type="synthetic_finance",
        fields={
            name: recipes.FieldPolicy(kind=kind, nullable=name == "payload")
            for name, kind in {
                "amount": "decimal",
                "enabled": "boolean",
                "payload": "json",
                "effective_on": "date",
                "observed_at": "datetime",
                "external_id": "uuid",
                "quantity": "integer",
            }.items()
        },
        lifecycle={"archived": False},
        review_reference="repo:backend/tests/test_staging_data_promotion_db.py",
        preconditions=(
            "Explicit synthetic financial record with typed field policies",
        ),
        constraints=(
            "Exact NUMERIC, JSONB numeric precision and native PostgreSQL types",
        ),
        postapply_requirements=("No float coercion and audit in the same transaction",),
    )
    monkeypatch.setattr(
        recipes,
        "DEFAULT_REGISTRY",
        recipes.RecipeRegistry([*recipes.DEFAULT_REGISTRY.values(), recipe]),
    )
    return promotion_db


def _finance_values(*, desired=False):
    if desired:
        return {
            "amount": Decimal("9007199254740993.12345678"),
            "enabled": True,
            "payload": '{"amount":12345678901234567890.12345678901,"count":9007199254740993,"nested":{"$nexus_type":"decimal","value":"domain-data"},"flags":[true,null]}',
            "effective_on": date(2030, 2, 3),
            "observed_at": datetime(
                2030, 2, 3, 12, 34, 56, 123456, tzinfo=timezone.utc
            ),
            "external_id": uuid.UUID(int=22685491128062790912553268770669400337),
            "quantity": 9_007_199_254_740_993,
        }
    return {
        "amount": Decimal("1.00000001"),
        "enabled": False,
        "payload": '{"phase":"before","amount":1.00000001}',
        "effective_on": date(2026, 1, 1),
        "observed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "external_id": uuid.UUID(int=302240678275694148452353),
        "quantity": 1,
    }


async def _write_finance(engine, values, *, insert=False):
    statement = (
        "INSERT INTO recipe_finance(id,amount,enabled,payload,effective_on,observed_at,external_id,quantity) "
        "VALUES(1,:amount,:enabled,CAST(:payload AS jsonb),:effective_on,:observed_at,:external_id,:quantity)"
        if insert
        else "UPDATE recipe_finance SET amount=:amount,enabled=:enabled,payload=CAST(:payload AS jsonb),"
        "effective_on=:effective_on,observed_at=:observed_at,external_id=:external_id,quantity=:quantity WHERE id=1"
    )
    await _execute(engine, statement, values)


async def _finance_package(engine):
    await _write_finance(engine, _finance_values(), insert=True)
    record = {
        "recipe": "synthetic-reviewed-finance",
        "table": "recipe_finance",
        "pk": {"id": 1},
        "fields": list(_finance_values()),
        "operation": "update",
    }
    baseline = await _artifact(engine, promotion.snapshot, _selection(record))
    await _write_finance(engine, _finance_values(desired=True))
    package = await _artifact(engine, promotion.package, baseline)
    await _write_finance(engine, _finance_values())
    # Exercise the actual JSON wire format, rather than Python-only native values.
    return json.loads(json.dumps(package, ensure_ascii=False, allow_nan=False))


async def _finance_row(engine):
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT amount,enabled,payload::text AS payload,effective_on,observed_at,external_id,quantity FROM recipe_finance WHERE id=1"
            )
        )
        row = dict(result.mappings().one())
        row["payload"] = json.loads(row["payload"], parse_float=Decimal)
        return row


async def test_reviewed_typed_recipe_roundtrips_exact_financial_and_json_values(
    reviewed_finance,
):
    package = await _finance_package(reviewed_finance)
    wire = json.dumps(package, ensure_ascii=False, allow_nan=False)
    assert "9007199254740993.12345678" in wire
    assert "12345678901234567890.12345678901" in wire
    preview = await _preview(reviewed_finance, package)
    await _apply(reviewed_finance, package, preview)
    expected = _finance_values(desired=True)
    expected["payload"] = json.loads(expected["payload"], parse_float=Decimal)
    assert await _finance_row(reviewed_finance) == expected
    async with reviewed_finance.connect() as conn:
        assert (
            await conn.scalar(text("SELECT count(*) FROM activities WHERE user_id=101"))
            == 1
        )


async def test_reviewed_typed_recipe_concurrent_decimal_conflict_changes_nothing_else(
    reviewed_finance,
):
    package = await _finance_package(reviewed_finance)
    preview = await _preview(reviewed_finance, package)
    async with reviewed_finance.begin() as production:
        await production.execute(
            text("UPDATE recipe_finance SET amount=:amount WHERE id=1"),
            {"amount": Decimal("2.00000002")},
        )
    with pytest.raises(promotion.PromotionError):
        await _apply(reviewed_finance, package, preview)
    expected = _finance_values()
    expected["amount"] = Decimal("2.00000002")
    expected["payload"] = json.loads(expected["payload"], parse_float=Decimal)
    assert await _finance_row(reviewed_finance) == expected
    async with reviewed_finance.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM activities")) == 0


@pytest.mark.parametrize(
    "initial_payload,desired_payload,expect_sql_null",
    [(None, "null", False), ("null", None, True)],
    ids=["sql-null-to-json-null", "json-null-to-sql-null"],
)
async def test_reviewed_json_recipe_preserves_sql_null_and_json_null_distinction(
    reviewed_finance, initial_payload, desired_payload, expect_sql_null
):
    initial = {**_finance_values(), "payload": initial_payload}
    await _write_finance(reviewed_finance, initial, insert=True)
    record = {
        "recipe": "synthetic-reviewed-finance",
        "table": "recipe_finance",
        "pk": {"id": 1},
        "fields": ["payload"],
        "operation": "update",
    }
    baseline = await _artifact(reviewed_finance, promotion.snapshot, _selection(record))
    await _write_finance(reviewed_finance, {**initial, "payload": desired_payload})
    package = await _artifact(reviewed_finance, promotion.package, baseline)
    package = json.loads(json.dumps(package, allow_nan=False))
    await _write_finance(reviewed_finance, initial)
    preview = await _preview(reviewed_finance, package)
    await _apply(reviewed_finance, package, preview)
    async with reviewed_finance.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT payload IS NULL AS sql_null,jsonb_typeof(payload) AS json_type FROM recipe_finance WHERE id=1"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert row["sql_null"] is expect_sql_null
        assert row["json_type"] == (None if expect_sql_null else "null")
        assert await conn.scalar(text("SELECT count(*) FROM activities")) == 1


async def test_reviewed_json_not_null_policy_accepts_json_null_and_restores_object(
    reviewed_finance, monkeypatch
):
    original = recipes.get_recipe("synthetic-reviewed-finance")
    strict_recipe = replace(
        original,
        fields={
            **original.fields,
            "payload": recipes.FieldPolicy(kind="json", nullable=False),
        },
    )
    monkeypatch.setattr(
        recipes,
        "DEFAULT_REGISTRY",
        recipes.RecipeRegistry(
            [
                recipe
                for recipe in recipes.DEFAULT_REGISTRY.values()
                if recipe.recipe_id != original.recipe_id
            ]
            + [strict_recipe]
        ),
    )
    await _execute(
        reviewed_finance, "ALTER TABLE recipe_finance ALTER COLUMN payload SET NOT NULL"
    )
    initial = _finance_values()
    await _write_finance(reviewed_finance, initial, insert=True)
    record = {
        "recipe": "synthetic-reviewed-finance",
        "table": "recipe_finance",
        "pk": {"id": 1},
        "fields": ["payload"],
        "operation": "update",
    }
    for source_payload, target_payload, expected_json_type in [
        (initial["payload"], "null", "null"),
        ("null", initial["payload"], "object"),
    ]:
        baseline = await _artifact(
            reviewed_finance, promotion.snapshot, _selection(record)
        )
        await _write_finance(reviewed_finance, {**initial, "payload": target_payload})
        package = await _artifact(reviewed_finance, promotion.package, baseline)
        package = json.loads(json.dumps(package, allow_nan=False))
        await _write_finance(reviewed_finance, {**initial, "payload": source_payload})
        preview = await _preview(reviewed_finance, package)
        await _apply(reviewed_finance, package, preview)
        async with reviewed_finance.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT payload IS NULL AS sql_null,jsonb_typeof(payload) AS json_type FROM recipe_finance WHERE id=1"
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert row["sql_null"] is False
            assert row["json_type"] == expected_json_type
    async with reviewed_finance.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM activities")) == 2


async def test_reviewed_module_insert_preserves_unselected_production_rows(
    reviewed_module,
):
    package = await _recipe_insert_package(reviewed_module)
    async with reviewed_module.begin() as production:
        await production.execute(
            text(
                "INSERT INTO recipe_tags(id,label,parent_code,domain_state) VALUES (99,'Production tag','synthetic-parent','live')"
            )
        )
    preview = await _preview(reviewed_module, package)
    await _apply(reviewed_module, package, preview)
    assert await _module_rows(reviewed_module) == [
        {
            "id": 10,
            "label": "Reviewed local tag",
            "parent_code": "synthetic-parent",
            "domain_state": "reviewed",
        },
        {
            "id": 99,
            "label": "Production tag",
            "parent_code": "synthetic-parent",
            "domain_state": "live",
        },
    ]
    async with reviewed_module.connect() as conn:
        assert (
            await conn.scalar(
                text("SELECT count(*) FROM recipe_events WHERE tag_id=10")
            )
            == 1
        )
        assert (
            await conn.scalar(text("SELECT count(*) FROM activities WHERE user_id=101"))
            == 2
        )


async def test_reviewed_insert_concurrent_pk_collision_rejects_entire_package(
    reviewed_module,
):
    package = await _recipe_insert_package(reviewed_module)
    preview = await _preview(reviewed_module, package)
    async with reviewed_module.begin() as production:
        await production.execute(
            text(
                "INSERT INTO recipe_tags(id,label,parent_code,domain_state) VALUES (10,'Production owns PK','synthetic-parent','live')"
            )
        )
    with pytest.raises(promotion.PromotionError):
        await _apply(reviewed_module, package, preview)
    await _assert_no_partial_promotion(reviewed_module)
    assert (await _module_rows(reviewed_module))[0]["label"] == "Production owns PK"


async def test_reviewed_insert_unique_collision_rolls_back_all_modules(reviewed_module):
    package = await _recipe_insert_package(reviewed_module)
    preview = await _preview(reviewed_module, package)
    async with reviewed_module.begin() as production:
        await production.execute(
            text(
                "INSERT INTO recipe_tags(id,label,parent_code,domain_state) VALUES (99,'Reviewed local tag','synthetic-parent','live')"
            )
        )
    with pytest.raises(promotion.PromotionError):
        await _apply(reviewed_module, package, preview)
    await _assert_no_partial_promotion(reviewed_module)
    assert [row["id"] for row in await _module_rows(reviewed_module)] == [99]


async def test_reviewed_insert_fk_failure_rolls_back_all_modules(reviewed_module):
    package = await _recipe_insert_package(reviewed_module)
    preview = await _preview(reviewed_module, package)
    async with reviewed_module.begin() as production:
        await production.execute(
            text("DELETE FROM recipe_parents WHERE code='synthetic-parent'")
        )
    with pytest.raises(promotion.PromotionError):
        await _apply(reviewed_module, package, preview)
    await _assert_no_partial_promotion(reviewed_module)
    assert await _module_rows(reviewed_module) == []


async def test_reviewed_domain_validation_rejects_invalid_source_values(
    reviewed_module,
):
    package = await _recipe_insert_package(reviewed_module, label="domain-denied")
    preview = await _preview(reviewed_module, package)
    assert preview["conflicts"]
    assert all(
        item["code"] == "recipe_domain_precondition_failed"
        for item in preview["conflicts"]
    )
    with pytest.raises(promotion.ConflictError):
        await _apply(reviewed_module, package, preview)
    await _assert_no_partial_promotion(reviewed_module)
    assert await _module_rows(reviewed_module) == []


async def test_reviewed_insert_cannot_claim_identical_foreign_row_without_receipt(
    reviewed_module,
):
    package = await _recipe_insert_package(reviewed_module)
    preview = await _preview(reviewed_module, package)
    async with reviewed_module.begin() as production:
        await production.execute(
            text(
                "INSERT INTO recipe_tags(id,label,parent_code,domain_state) VALUES (10,'Reviewed local tag','synthetic-parent','reviewed')"
            )
        )
    with pytest.raises(promotion.PromotionError):
        await _apply(reviewed_module, package, preview)
    await _assert_no_partial_promotion(reviewed_module)


async def test_reviewed_audit_constraint_failure_rolls_back_domain_events(
    reviewed_module,
):
    package = await _recipe_insert_package(reviewed_module)
    await _execute(
        reviewed_module,
        "ALTER TABLE activities ADD CONSTRAINT reject_module_audit CHECK(entity_type <> 'synthetic_tag')",
    )
    preview = await _preview(reviewed_module, package)
    with pytest.raises(promotion.PromotionError):
        await _apply(reviewed_module, package, preview)
    await _assert_no_partial_promotion(reviewed_module)
    assert await _module_rows(reviewed_module) == []
    async with reviewed_module.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM activities")) == 0


async def test_reviewed_after_apply_failure_rolls_back_domain_relations_and_audit(
    reviewed_module,
):
    package = await _recipe_insert_package(
        reviewed_module, label="fail-after-domain-write"
    )
    preview = await _preview(reviewed_module, package)
    with pytest.raises(promotion.PromotionError, match="synthetic_postapply_failure"):
        await _apply(reviewed_module, package, preview)
    await _assert_no_partial_promotion(reviewed_module)
    assert await _module_rows(reviewed_module) == []


async def test_reviewed_insert_retry_uses_audit_marker_without_duplicates(
    reviewed_module,
):
    package = await _recipe_insert_package(reviewed_module, include_client=False)
    preview = await _preview(reviewed_module, package)
    await _apply(reviewed_module, package, preview)
    await _apply(reviewed_module, package, preview)
    assert len(await _module_rows(reviewed_module)) == 1
    async with reviewed_module.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM activities")) == 1
        assert await conn.scalar(text("SELECT count(*) FROM recipe_events")) == 1


async def test_promotion_preserves_new_production_rows_and_unselected_fields(
    promotion_db,
):
    package = await _update_package(promotion_db, {1: "Approved local edit"})
    # A different production connection commits live work after the local baseline.
    async with promotion_db.begin() as production:
        await production.execute(
            text("UPDATE clients SET notes='Production-only note' WHERE id=1")
        )
        await production.execute(
            text(
                "INSERT INTO clients (id,industry,notes) VALUES (2,'New production row','Keep me')"
            )
        )
    preview = await _preview(promotion_db, package)
    await _apply(promotion_db, package, preview)
    assert await _rows(promotion_db) == [
        {"id": 1, "industry": "Approved local edit", "notes": "Production-only note"},
        {"id": 2, "industry": "New production row", "notes": "Keep me"},
    ]


async def test_second_connection_change_after_preview_rejects_entire_package(
    promotion_db,
):
    package = await _update_package(promotion_db, {1: "Local one", 2: "Local two"})
    preview = await _preview(promotion_db, package)
    async with promotion_db.begin() as production:
        await production.execute(
            text("UPDATE clients SET industry='Production wins' WHERE id=2")
        )
    with pytest.raises(promotion.PromotionError):
        await _apply(promotion_db, package, preview)
    assert await _rows(promotion_db) == [
        {"id": 1, "industry": "Baseline 1", "notes": "Untouched 1"},
        {"id": 2, "industry": "Production wins", "notes": "Untouched 2"},
    ]


async def test_database_constraint_failure_rolls_back_earlier_write(promotion_db):
    await _execute(
        promotion_db,
        "INSERT INTO clients (id,industry,notes) VALUES (1,'One','Before one'),(2,'Two','Before two')",
    )
    # Source may have a different constraint. Build the package with it disabled,
    # then reinstate the stricter target constraint before preview/apply.
    await _execute(
        promotion_db, "ALTER TABLE clients DROP CONSTRAINT clients_notes_check"
    )
    baseline = await _artifact(
        promotion_db, promotion.snapshot, _selection(_record(1), _record(2, ("notes",)))
    )
    await _execute(promotion_db, "UPDATE clients SET industry='Local one' WHERE id=1")
    await _execute(promotion_db, "UPDATE clients SET notes='reject-write' WHERE id=2")
    package = await _artifact(promotion_db, promotion.package, baseline)
    await _execute(
        promotion_db, "UPDATE clients SET industry='One',notes='Before one' WHERE id=1"
    )
    await _execute(promotion_db, "UPDATE clients SET notes='Before two' WHERE id=2")
    await _execute(
        promotion_db,
        "ALTER TABLE clients ADD CONSTRAINT clients_notes_check CHECK (notes IS DISTINCT FROM 'reject-write')",
    )
    preview = await _preview(promotion_db, package)
    with pytest.raises(promotion.PromotionError):
        await _apply(promotion_db, package, preview)
    assert await _rows(promotion_db) == [
        {"id": 1, "industry": "One", "notes": "Before one"},
        {"id": 2, "industry": "Two", "notes": "Before two"},
    ]


async def test_unique_conflict_rolls_back_whole_package_and_audit(promotion_db):
    package = await _update_package(
        promotion_db, {1: "Local update", 2: "Unique collision"}
    )
    preview = await _preview(promotion_db, package)
    # Another row acquires the unique value after preview.
    async with promotion_db.begin() as production:
        await production.execute(
            text(
                "INSERT INTO clients (id,industry,notes) VALUES (3,'Unique collision','Production wins')"
            )
        )
    with pytest.raises(
        promotion.PromotionError, match="database_constraint_or_execution_failed"
    ) as error:
        await _apply(promotion_db, package, preview)
    assert "Unique collision" not in str(error.value)
    assert await _rows(promotion_db) == [
        {"id": 1, "industry": "Baseline 1", "notes": "Untouched 1"},
        {"id": 2, "industry": "Baseline 2", "notes": "Untouched 2"},
        {"id": 3, "industry": "Unique collision", "notes": "Production wins"},
    ]
    async with promotion_db.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM activities")) == 0


async def test_replaying_approved_update_is_an_idempotent_noop(promotion_db):
    package = await _update_package(promotion_db, {1: "Approved once"})
    preview = await _preview(promotion_db, package)
    await _apply(promotion_db, package, preview)
    first = await _rows(promotion_db)
    await _apply(promotion_db, package, preview)
    assert await _rows(promotion_db) == first
    async with promotion_db.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM activities")) == 1
        assert await conn.scalar(text("SELECT user_id FROM activities")) == 101


async def test_insert_requires_domain_handler_and_never_writes(promotion_db):
    with pytest.raises(
        promotion.PromotionError, match="operation_requires_domain_handler"
    ):
        await _artifact(
            promotion_db,
            promotion.snapshot,
            _selection(_record(1, ("industry",), "insert")),
        )
    assert await _rows(promotion_db) == []


async def test_digest_approval_must_match_exact_preview(promotion_db):
    package = await _update_package(promotion_db, {1: "Approved local edit"})
    preview = await _preview(promotion_db, package)
    with pytest.raises(promotion.PromotionError):
        await _artifact(
            promotion_db, promotion.apply, package, preview, "0" * 64, actor_id=101
        )
    assert await _rows(promotion_db) == [
        {"id": 1, "industry": "Baseline 1", "notes": "Untouched 1"},
    ]


async def test_admin_deactivation_after_preview_prevents_writes(promotion_db):
    package = await _update_package(promotion_db, {1: "Approved local edit"})
    preview = await _preview(promotion_db, package)
    async with promotion_db.begin() as production:
        await production.execute(text("UPDATE users SET is_active=false WHERE id=101"))
    with pytest.raises(
        promotion.PromotionError, match="explicit_active_admin_actor_required"
    ):
        await _apply(promotion_db, package, preview)
    assert await _rows(promotion_db) == [
        {"id": 1, "industry": "Baseline 1", "notes": "Untouched 1"},
    ]


async def test_client_hidden_after_preview_cannot_be_promoted(promotion_db):
    package = await _update_package(promotion_db, {1: "Approved local edit"})
    preview = await _preview(promotion_db, package)
    async with promotion_db.begin() as production:
        await production.execute(text("UPDATE clients SET hidden=true WHERE id=1"))
    with pytest.raises(promotion.ConflictError):
        await _apply(promotion_db, package, preview)
    assert await _rows(promotion_db) == [
        {"id": 1, "industry": "Baseline 1", "notes": "Untouched 1"},
    ]


async def test_schema_change_after_preview_requires_new_approval(promotion_db):
    package = await _update_package(promotion_db, {1: "Approved local edit"})
    preview = await _preview(promotion_db, package)
    async with promotion_db.begin() as production:
        await production.execute(
            text("ALTER TABLE clients ADD COLUMN new_business_field text")
        )
    with pytest.raises(promotion.PromotionError):
        await _apply(promotion_db, package, preview)
    assert await _rows(promotion_db) == [
        {"id": 1, "industry": "Baseline 1", "notes": "Untouched 1"},
    ]
    async with promotion_db.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM activities")) == 0


async def test_preview_cannot_be_reused_after_target_schema_remap(promotion_db):
    package = await _update_package(promotion_db, {1: "Approved local edit"})
    preview = await _preview(promotion_db, package)
    other_schema = "promotion_target_" + uuid.uuid4().hex
    async with promotion_db.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{other_schema}"'))
        await conn.execute(
            text(f'CREATE TABLE "{other_schema}".clients (LIKE clients INCLUDING ALL)')
        )
        await conn.execute(
            text(f'INSERT INTO "{other_schema}".clients SELECT * FROM clients')
        )
        await conn.execute(
            text(
                f'CREATE TABLE "{other_schema}".alembic_version (LIKE alembic_version INCLUDING ALL)'
            )
        )
        await conn.execute(
            text(
                f'INSERT INTO "{other_schema}".alembic_version SELECT * FROM alembic_version'
            )
        )
        await conn.execute(
            text(f'CREATE TABLE "{other_schema}".users (LIKE users INCLUDING ALL)')
        )
        await conn.execute(
            text(f'INSERT INTO "{other_schema}".users SELECT * FROM users')
        )
        await conn.execute(
            text(
                f'CREATE TABLE "{other_schema}".activities (LIKE activities INCLUDING ALL)'
            )
        )
    try:
        async with promotion_db.connect() as conn:
            await conn.execute(text(f'SET search_path TO "{other_schema}"'))
            await conn.commit()
            with pytest.raises(promotion.PromotionError):
                await promotion.apply(
                    conn, package, preview, preview["digest"], actor_id=101
                )
            await conn.rollback()
            rows = (
                await conn.execute(text("SELECT id,industry FROM clients ORDER BY id"))
            ).all()
            assert rows == [(1, "Baseline 1")]
            await conn.execute(text("RESET search_path"))
            await conn.commit()
    finally:
        async with promotion_db.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{other_schema}" CASCADE'))
