"""Reviewed recipe contracts: pure, with synthetic values and no database IO."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from uuid import UUID
from types import SimpleNamespace

import pytest

from app.services import staging_promotion_recipes as recipes


CALLS = []


async def synthetic_domain(conn, operation):
    CALLS.append(("validate", conn.in_transaction(), operation["actor_id"]))
    if operation.get("desired_after", {}).get("title") == "invalid-domain-value":
        raise recipes.RecipeError("synthetic_domain_rejected")


async def synthetic_before(conn, operation):
    CALLS.append(("before", conn.in_transaction(), operation["actor_id"]))


async def synthetic_after(conn, operation):
    CALLS.append(("after", conn.in_transaction(), operation["actor_id"]))


async def synthetic_insert(conn, table, operation):
    CALLS.append(("insert", conn.in_transaction(), operation["pk"]["id"]))


def synthetic_recipe(**kwargs):
    return replace(
        recipes.CLIENT_DESCRIPTIONS, recipe_id="synthetic-project-description", table="projects",
        entity_type="project", fields={"title": recipes.FieldPolicy(100, nullable=False, required_for_insert=True)},
        lifecycle={}, review_reference="repo:synthetic-reviewed-recipe-test", **kwargs,
    )


def test_client_recipe_remains_narrow_and_versioned():
    recipe = recipes.get_recipe("client-descriptions")
    assert recipe.table == "clients"
    assert recipe.operations == frozenset({"update"})
    assert set(recipe.fields) == {"industry", "website", "address", "notes"}
    assert recipe.primary_key == ("id",)
    assert recipe.lifecycle == {"hidden": False, "merged_into_client_id": None, "archived_at": None, "deleted_at": None}
    recipe.validate_policy(recipe.policy_id)
    assert len(recipe.policy_digest) == 64


def test_registry_is_explicit_and_rejects_unknown_or_unreviewed_recipes():
    with pytest.raises(recipes.RecipeError, match="not_registered"):
        recipes.get_recipe("projects")
    with pytest.raises(recipes.RecipeError, match="unreviewed"):
        replace(recipes.CLIENT_DESCRIPTIONS, review_reference="")
    with pytest.raises(recipes.RecipeError, match="unreviewed"):
        recipes.RecipeRegistry([{"table": "clients"}])
    with pytest.raises(recipes.RecipeError, match="duplicate"):
        recipes.RecipeRegistry([recipes.CLIENT_DESCRIPTIONS, recipes.CLIENT_DESCRIPTIONS])
    with pytest.raises(TypeError):
        recipes.DEFAULT_REGISTRY["unreviewed"] = synthetic_recipe()
    with pytest.raises(TypeError):
        recipes.CLIENT_DESCRIPTIONS.fields["extra"] = recipes.FieldPolicy(10)


@pytest.mark.parametrize("table", ["users", "roles", "permissions", "app_settings", "integrations", "oauth_connections", "api_keys", "candidate_tokens", "notification_email_outbox", "alembic_version"])
def test_review_marker_does_not_override_sensitive_data_deny(table):
    with pytest.raises(recipes.RecipeError, match="forbidden"):
        replace(recipes.CLIENT_DESCRIPTIONS, table=table)


@pytest.mark.parametrize("name", ["password_hash", "access_token", "secret", "api_key", "private_key", "session_id", "oauth_state", "credentials"])
def test_sensitive_fields_remain_denied_even_in_reviewed_business_table(name):
    with pytest.raises(recipes.RecipeError, match="sensitive"):
        replace(recipes.CLIENT_DESCRIPTIONS, fields={name: recipes.FieldPolicy(100)})


def test_insert_requires_domain_handler_and_explicit_requirements():
    with pytest.raises(recipes.RecipeError, match="domain_handler"):
        synthetic_recipe(operations=frozenset({"insert"}))
    with pytest.raises(recipes.RecipeError, match="domain_contract"):
        synthetic_recipe(constraints=())
    recipe = synthetic_recipe(operations=frozenset({"insert"}), insert_handler=synthetic_insert)
    recipe.validate_values({"title": "Synthetic"}, for_insert=True)
    with pytest.raises(recipes.RecipeError, match="required_field"):
        replace(recipe, fields={"title": recipes.FieldPolicy(100, required_for_insert=True), "notes": recipes.FieldPolicy(100)}).validate_values({"notes": "Present"}, for_insert=True)


def test_field_validators_are_explicit_and_reject_unknown_null_oversize_and_nul():
    recipe = synthetic_recipe()
    for values in ({"title": None}, {"title": "x" * 101}, {"title": "x\x00y"}, {"undeclared": "x"}, {"title": 123}):
        with pytest.raises(recipes.RecipeError):
            recipe.validate_values(values)


def test_table_field_lifecycle_and_handler_change_invalidate_policy():
    recipe = synthetic_recipe()
    binding = recipe.policy_id
    for changed in (
        replace(recipe, table="other_projects"), replace(recipe, version=2),
        replace(recipe, fields={"title": recipes.FieldPolicy(99)}),
        replace(recipe, lifecycle={"hidden": False}),
        replace(recipe, validate_domain=synthetic_domain),
        replace(recipe, constraints=("a-new-constraint",)),
    ):
        assert changed.policy_digest != recipe.policy_digest
        with pytest.raises(recipes.RecipeError, match="policy_mismatch"):
            changed.validate_policy(binding)


def test_domain_hooks_only_execute_inside_existing_transaction():
    recipe = synthetic_recipe(validate_domain=synthetic_domain, before_apply=synthetic_before, after_apply=synthetic_after)
    CALLS.clear()
    operation = {"actor_id": 101, "pk": {"id": 1}, "desired_after": {"title": "Synthetic"}}

    async def exercise():
        with pytest.raises(recipes.RecipeError, match="active_transaction"):
            await recipe.run_hook("validate_domain", SimpleNamespace(in_transaction=lambda: False), operation)
        assert CALLS == []
        conn = SimpleNamespace(in_transaction=lambda: True)
        for phase in ("validate_domain", "before_apply", "after_apply"):
            await recipe.run_hook(phase, conn, operation)
        with pytest.raises(recipes.RecipeError, match="domain_rejected"):
            await recipe.run_hook("validate_domain", conn, {**operation, "desired_after": {"title": "invalid-domain-value"}})
    asyncio.run(exercise())
    assert CALLS[:3] == [("validate", True, 101), ("before", True, 101), ("after", True, 101)]


def test_registry_safe_summaries_include_every_policy_identity():
    summaries = recipes.list_recipes()
    assert len(summaries) == 1
    assert summaries[0]["id"] == "client-descriptions"
    assert summaries[0]["policy_digest"] == recipes.CLIENT_DESCRIPTIONS.policy_digest
    assert summaries[0]["operations"] == ["update"]
    assert "postapply_requirements" in summaries[0]


@pytest.mark.parametrize("kind,value", [
    ("boolean", True), ("integer", 9223372036854775807),
    ("decimal", Decimal("12345678901234567890.12345678")),
    ("date", date(2026, 10, 22)), ("datetime", datetime(2026, 10, 22, tzinfo=timezone.utc)),
    ("uuid", UUID(int=1)),
    ("json", {"amount": Decimal("12345678901234567890.12345678"), "enabled": True, "nested": [None, 1, "x"]}),
])
def test_native_typed_values_validate_without_lossy_conversion(kind, value):
    field = recipes.FieldPolicy(kind=kind, nullable=False)
    field.validate(value)
    assert field.policy()["type"] == kind


@pytest.mark.parametrize("kind,value", [
    ("boolean", 1), ("integer", True), ("integer", 2**63), ("decimal", 12.5),
    ("decimal", Decimal("NaN")), ("decimal", Decimal("Infinity")), ("decimal", Decimal("1e99999999")),
    ("date", datetime(2026, 10, 22)), ("datetime", datetime(2026, 10, 22)),
    ("uuid", str(UUID(int=1))), ("json", {"amount": 12.5}),
    ("json", {"amount": Decimal("NaN")}), ("json", {1: "bad-key"}), ("json", b"bytes"),
])
def test_invalid_or_lossy_typed_values_fail_closed(kind, value):
    with pytest.raises(recipes.RecipeError):
        recipes.FieldPolicy(kind=kind, nullable=False).validate(value)


def test_exact_json_decimal_validation_is_independent_of_decimal_context():
    exact = Decimal("123456789012345678901234567890.12345678901234567890")
    with localcontext() as context:
        context.prec = 3
        recipes.FieldPolicy(kind="json").validate({"exact": exact})
    assert str(exact) == "123456789012345678901234567890.12345678901234567890"
    with pytest.raises(recipes.RecipeError):
        recipes.FieldPolicy(kind="json", max_length=10).validate({"exact": exact})


def positive_amount(value):
    if value <= 0:
        raise recipes.RecipeError("synthetic_amount_must_be_positive")


def test_custom_native_validator_is_in_policy_digest_and_enforced():
    field = recipes.FieldPolicy(kind="decimal", validator=positive_amount)
    field.validate(Decimal("0.01"))
    with pytest.raises(recipes.RecipeError, match="positive"):
        field.validate(Decimal("-1"))
    assert field.policy()["validator"]["source_sha256"]
    plain = replace(recipes.CLIENT_DESCRIPTIONS, fields={"amount": recipes.FieldPolicy(kind="decimal")})
    custom = replace(plain, fields={"amount": field})
    assert plain.policy_digest != custom.policy_digest


def test_json_recursion_and_extreme_number_sizes_are_bounded():
    nested = "leaf"
    for _ in range(34):
        nested = [nested]
    with pytest.raises(recipes.RecipeError, match="complex"):
        recipes.FieldPolicy(kind="json").validate(nested)
    with pytest.raises(recipes.RecipeError, match="large"):
        recipes.FieldPolicy(kind="json").validate(Decimal("1e999999999"))


def test_json_document_null_is_distinct_from_sql_null_and_nullable_constraint():
    policy = recipes.FieldPolicy(kind="json", nullable=False)
    policy.validate(recipes.JSON_NULL)
    policy.validate({"nested-null": None})
    with pytest.raises(recipes.RecipeError, match="null_not_allowed"):
        policy.validate(None)
    recipes.FieldPolicy(kind="json", nullable=True).validate(None)
    assert recipes.JSON_NULL is not None
    assert recipes.JSON_NULL != "json-document-null"
    with pytest.raises(recipes.RecipeError):
        recipes.FieldPolicy(kind="string").validate(recipes.JSON_NULL)
