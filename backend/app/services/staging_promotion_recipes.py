"""Reviewed, repository-authored promotion recipes; never loaded from CLI artifacts.

A recipe is domain code, like a migration: its author owns validators, lifecycle,
constraints, transactional hooks and postapply checks. Registering a table alone
is insufficient. Identity/session/secret/operational data are deliberately denied.
Only the client description recipe is currently reviewed and enabled.
"""

from __future__ import annotations

from collections.abc import Mapping, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
import hashlib
import inspect
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Awaitable, Callable
from uuid import UUID

NAME = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
RECIPE_ID = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")
DENIED_TABLES = frozenset(
    {
        "users",
        "roles",
        "permissions",
        "user_roles",
        "service_account_keys",
        "m365_connections",
        "graph_subscriptions",
        "alembic_version",
        "activities",
        "notification_email_outbox",
        "email_outbox",
        "background_tasks",
        "settings",
        "system_settings",
        "app_settings",
        "integrations",
        "sync_state",
        "oauth_connections",
        "api_keys",
        "encryption_keys",
        "webhooks",
    }
)
DENIED_NAMES = re.compile(
    r"(?:^|_)(?:secrets?|sessions?|tokens?|credentials?|passwords?|outbox|cursors?|"
    r"auth|oauth|permissions?|roles?|settings|integrations?|operational|sync|access)(?:_|$)"
    r"|(?:^|_)(?:api|private|encryption)_keys?(?:_|$)"
)
Hook = Callable[[Any, dict], Awaitable[None]]
InsertHandler = Callable[[Any, Any, dict], Awaitable[None]]


class _JsonNull(Enum):
    DOCUMENT = "json-document-null"


# SQL NULL remains Python None. Domain hooks/validators receive this singleton
# for an entire JSON document `null`; nulls nested inside JSON stay Python None.
JSON_NULL = _JsonNull.DOCUMENT


class RecipeError(ValueError):
    """Machine-readable policy failures, without record data."""


def _json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _function_identity(
    function: Callable, *, async_required: bool = True
) -> dict[str, str]:
    # These functions are trusted repository code, never dynamic artifact imports.
    if inspect.iscoroutinefunction(function) is not async_required:
        raise RecipeError("recipe_hook_must_be_async_repo_function")
    try:
        source = inspect.getsource(function)
    except (OSError, TypeError):
        raise RecipeError("recipe_hook_source_required") from None
    module_path = inspect.getsourcefile(function)
    if not module_path:
        raise RecipeError("recipe_hook_source_required")
    return {
        "module": function.__module__,
        "name": function.__qualname__,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "module_sha256": hashlib.sha256(Path(module_path).read_bytes()).hexdigest(),
    }


async def _no_op(conn: Any, operation: dict) -> None:
    """Description-only recipe has no additional domain side effects."""


@dataclass(frozen=True)
class FieldPolicy:
    max_length: int = 100_000
    nullable: bool = True
    required_for_insert: bool = False
    kind: str = "string"
    validator: Callable[[Any], None] | None = None

    def __post_init__(self):
        if type(self.max_length) is not int or not 0 < self.max_length <= 1_000_000:
            raise RecipeError("invalid_recipe_field_limit")
        if (
            type(self.nullable) is not bool
            or type(self.required_for_insert) is not bool
        ):
            raise RecipeError("invalid_recipe_field_policy")
        if self.kind not in {
            "string",
            "boolean",
            "integer",
            "decimal",
            "date",
            "datetime",
            "uuid",
            "json",
        }:
            raise RecipeError("unsupported_recipe_field_kind")
        if self.validator is not None:
            _function_identity(self.validator, async_required=False)

    def validate(self, value: Any) -> None:
        if value is None:
            if not self.nullable:
                raise RecipeError("recipe_null_not_allowed")
            return
        valid = False
        if self.kind == "string":
            valid = (
                isinstance(value, str)
                and len(value) <= self.max_length
                and "\x00" not in value
            )
        elif self.kind == "boolean":
            valid = type(value) is bool
        elif self.kind == "integer":
            valid = type(value) is int and -(2**63) <= value < 2**63
        elif self.kind == "decimal":
            valid = (
                isinstance(value, Decimal)
                and value.is_finite()
                and len(value.as_tuple().digits) + abs(value.as_tuple().exponent)
                <= self.max_length
            )
        elif self.kind == "date":
            valid = type(value) is date
        elif self.kind == "datetime":
            valid = (
                isinstance(value, datetime)
                and value.tzinfo is not None
                and value.utcoffset() == timedelta(0)
            )
        elif self.kind == "uuid":
            valid = isinstance(value, UUID)
        elif self.kind == "json":
            try:
                valid = (
                    value is JSON_NULL
                    or _json_value_size(value, [0]) <= self.max_length
                )
            except RecipeError:
                raise
            except (ValueError, UnicodeError):
                raise RecipeError("invalid_recipe_json_value") from None
        if not valid:
            raise RecipeError("invalid_recipe_field_value")
        if self.validator is not None:
            try:
                if self.validator(value) is False:
                    raise RecipeError("recipe_value_validator_rejected")
            except RecipeError:
                raise
            except Exception:
                raise RecipeError("recipe_value_validator_rejected") from None

    def policy(self) -> dict:
        return {
            "type": self.kind,
            "max_length": self.max_length,
            "nullable": self.nullable,
            "required_for_insert": self.required_for_insert,
            "validator": _function_identity(self.validator, async_required=False)
            if self.validator
            else None,
        }


def _json_value_size(value: Any, count: list[int], depth: int = 0) -> int:
    """Validate exact JSON numbers without Decimal->float coercion or rounding."""
    count[0] += 1
    if depth > 32 or count[0] > 100_000:
        raise RecipeError("recipe_json_too_complex")
    if value is None or type(value) in {bool, int}:
        return len(_json(value))
    if isinstance(value, str):
        if "\x00" in value:
            raise RecipeError("invalid_recipe_json_value")
        return len(_json(value))
    if isinstance(value, Decimal) and value.is_finite():
        # Bound exponent expansion before format('f'), independent of decimal context.
        sign, digits, exponent = value.as_tuple()
        size = len(digits) + abs(exponent) + sign + 2
        if size > 1_000_000:
            raise RecipeError("recipe_json_number_too_large")
        return len(format(value, "f"))
    if isinstance(value, list):
        return (
            2
            + max(0, len(value) - 1)
            + sum(_json_value_size(item, count, depth + 1) for item in value)
        )
    if isinstance(value, dict) and all(
        isinstance(key, str) and "\x00" not in key for key in value
    ):
        return (
            2
            + max(0, len(value) - 1)
            + sum(
                len(_json(key)) + 1 + _json_value_size(item, count, depth + 1)
                for key, item in value.items()
            )
        )
    raise RecipeError("invalid_recipe_json_value")


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    version: int
    table: str
    entity_type: str
    fields: Mapping[str, FieldPolicy]
    review_reference: str = ""
    primary_key: tuple[str, ...] = ("id",)
    operations: frozenset[str] = frozenset({"update"})
    lifecycle: Mapping[str, Any] = field(default_factory=dict)
    preconditions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    postapply_requirements: tuple[str, ...] = ()
    validate_domain: Hook = _no_op
    before_apply: Hook = _no_op
    after_apply: Hook = _no_op
    insert_handler: InsertHandler | None = None
    data_category: str = "business"

    def __post_init__(self):
        if (
            not isinstance(self.recipe_id, str)
            or not RECIPE_ID.fullmatch(self.recipe_id)
            or type(self.version) is not int
            or self.version < 1
        ):
            raise RecipeError("invalid_recipe_identity")
        if (
            not isinstance(self.table, str)
            or not isinstance(self.entity_type, str)
            or not NAME.fullmatch(self.table)
            or not NAME.fullmatch(self.entity_type)
        ):
            raise RecipeError("invalid_recipe_table_or_entity")
        if (
            self.data_category != "business"
            or self.table in DENIED_TABLES
            or DENIED_NAMES.search(self.table)
        ):
            raise RecipeError("recipe_data_category_forbidden")
        if (
            not isinstance(self.review_reference, str)
            or not self.review_reference.startswith("repo:")
            or len(self.review_reference) <= 5
        ):
            raise RecipeError("unreviewed_recipe_not_allowed")
        if self.primary_key != ("id",):
            raise RecipeError("recipe_primary_key_requires_engine_support")
        operations = frozenset(self.operations)
        if not operations or not operations <= {"update", "insert"}:
            raise RecipeError("recipe_operation_not_allowed")
        if "insert" in operations and self.insert_handler is None:
            raise RecipeError("insert_requires_reviewed_domain_handler")
        if "insert" not in operations and self.insert_handler is not None:
            raise RecipeError("unused_insert_handler")
        fields = dict(self.fields)
        lifecycle = dict(self.lifecycle)
        if not fields or set(fields) & set(self.primary_key):
            raise RecipeError("invalid_recipe_fields")
        for name, policy in fields.items():
            if (
                not isinstance(name, str)
                or not NAME.fullmatch(name)
                or DENIED_NAMES.search(name)
                or not isinstance(policy, FieldPolicy)
            ):
                raise RecipeError("invalid_or_sensitive_recipe_field")
        if any(
            not isinstance(name, str) or not NAME.fullmatch(name) for name in lifecycle
        ) or set(lifecycle) & set(fields):
            raise RecipeError("invalid_recipe_lifecycle")
        if any(
            not isinstance(v, (str, bool, int, type(None))) for v in lifecycle.values()
        ):
            raise RecipeError("invalid_recipe_lifecycle")
        for requirements in (
            self.preconditions,
            self.constraints,
            self.postapply_requirements,
        ):
            if not requirements or any(
                not isinstance(item, str) or not item for item in requirements
            ):
                raise RecipeError("recipe_requires_explicit_domain_contract")
        for function in (self.validate_domain, self.before_apply, self.after_apply):
            _function_identity(function)
        if self.insert_handler is not None:
            _function_identity(self.insert_handler)
        object.__setattr__(self, "fields", MappingProxyType(fields))
        object.__setattr__(self, "lifecycle", MappingProxyType(lifecycle))
        object.__setattr__(self, "operations", operations)
        for name in (
            "preconditions",
            "constraints",
            "postapply_requirements",
            "primary_key",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def policy_digest(self) -> str:
        policy = {
            "recipe_id": self.recipe_id,
            "version": self.version,
            "table": self.table,
            "entity_type": self.entity_type,
            "primary_key": self.primary_key,
            "operations": sorted(self.operations),
            "data_category": self.data_category,
            "fields": {name: value.policy() for name, value in self.fields.items()},
            "lifecycle": dict(self.lifecycle),
            "review_reference": self.review_reference,
            "preconditions": self.preconditions,
            "constraints": self.constraints,
            "postapply_requirements": self.postapply_requirements,
            "hooks": {
                name: _function_identity(getattr(self, name))
                for name in ("validate_domain", "before_apply", "after_apply")
            },
            "insert_handler": _function_identity(self.insert_handler)
            if self.insert_handler
            else None,
            # Registry/helper edits also invalidate previously approved packages.
            "registry_source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        }
        return hashlib.sha256(_json(policy)).hexdigest()

    @property
    def policy_id(self) -> dict:
        return {
            "id": self.recipe_id,
            "version": self.version,
            "policy_digest": self.policy_digest,
        }

    def validate_policy(self, binding: dict) -> None:
        if binding != self.policy_id:
            raise RecipeError("recipe_policy_mismatch")

    def validate_values(self, values: dict, *, for_insert: bool = False) -> None:
        if (
            not isinstance(values, dict)
            or not values
            or not set(values) <= set(self.fields)
        ):
            raise RecipeError("recipe_field_not_allowed")
        for name, value in values.items():
            self.fields[name].validate(value)
        if for_insert and any(
            policy.required_for_insert and name not in values
            for name, policy in self.fields.items()
        ):
            raise RecipeError("recipe_insert_required_field_missing")

    async def run_hook(self, phase: str, conn: Any, operation: dict) -> None:
        if phase not in {"validate_domain", "before_apply", "after_apply"}:
            raise RecipeError("unknown_recipe_hook")
        if not conn.in_transaction():
            raise RecipeError("recipe_requires_active_transaction")
        await getattr(self, phase)(conn, operation)
        if not conn.in_transaction():
            raise RecipeError("recipe_hook_changed_transaction")


class RecipeRegistry(Mapping[str, Recipe]):
    """Static registry constructed in repository code, with no mutable registration API."""

    def __init__(self, recipes):
        entries = {}
        for recipe in recipes:
            if not isinstance(recipe, Recipe):
                raise RecipeError("unreviewed_recipe_not_allowed")
            if recipe.recipe_id in entries:
                raise RecipeError("duplicate_recipe_identity")
            entries[recipe.recipe_id] = recipe
        self._entries = MappingProxyType(entries)

    def __getitem__(self, key: str) -> Recipe:
        return self._entries[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


CLIENT_DESCRIPTIONS = Recipe(
    recipe_id="client-descriptions",
    version=1,
    table="clients",
    entity_type="client",
    fields={
        "industry": FieldPolicy(100),
        "website": FieldPolicy(500),
        "address": FieldPolicy(500),
        "notes": FieldPolicy(100_000),
    },
    review_reference="repo:staging-data-promotion-client-descriptions-v1",
    lifecycle={
        "hidden": False,
        "merged_into_client_id": None,
        "archived_at": None,
        "deleted_at": None,
    },
    preconditions=(
        "record-exists-and-is-writable",
        "exact-expected-before-for-every-selected-field",
    ),
    constraints=(
        "postgresql-column-and-table-constraints",
        "only-description-fields-change",
    ),
    postapply_requirements=(
        "activity-audit-in-same-transaction",
        "no-background-or-external-effects",
    ),
)
DEFAULT_REGISTRY = RecipeRegistry([CLIENT_DESCRIPTIONS])


def get_recipe(recipe_id: str) -> Recipe:
    if not isinstance(recipe_id, str) or recipe_id not in DEFAULT_REGISTRY:
        raise RecipeError("recipe_not_registered")
    return DEFAULT_REGISTRY[recipe_id]


def list_recipes() -> list[dict]:
    return [
        {
            **recipe.policy_id,
            "table": recipe.table,
            "entity_type": recipe.entity_type,
            "primary_key": list(recipe.primary_key),
            "operations": sorted(recipe.operations),
            "fields": sorted(recipe.fields),
            "postapply_requirements": list(recipe.postapply_requirements),
        }
        for recipe in DEFAULT_REGISTRY.values()
    ]
