"""Blue/green Qdrant build validation, atomic cutover and rollback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from app.services.qdrant_factory import (
    ACTIVE_ALIASES,
    VOYAGE4_TEXT_V2,
    VectorSpace,
    physical_collections,
)


class IndexValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CollectionValidation:
    entity: str
    collection: str
    points: int
    dimension: int
    sampled_hashes: int


def _vector_dimension(info: object) -> int:
    config = getattr(info, "config", None)
    params = getattr(config, "params", None)
    vectors = getattr(params, "vectors", None)
    if isinstance(vectors, dict):
        if len(vectors) != 1:
            raise IndexValidationError("named multi-vector collections are unsupported")
        vectors = next(iter(vectors.values()))
    size = getattr(vectors, "size", None)
    if not isinstance(size, int):
        raise IndexValidationError("cannot determine collection vector dimension")
    return size


def ensure_physical_collections(
    client,
    *,
    space: VectorSpace = VOYAGE4_TEXT_V2,
    recreate: bool = False,
) -> dict[str, str]:
    """Create empty blue collections without touching active aliases."""
    from qdrant_client.models import Distance, VectorParams

    targets = physical_collections(space)
    active_targets = set(alias_targets(client).values())
    existing = {item.name for item in client.get_collections().collections}
    for collection in targets.values():
        if recreate and collection in existing:
            if collection in active_targets:
                raise IndexValidationError(
                    f"refusing to recreate active collection {collection}"
                )
            client.delete_collection(collection_name=collection)
            existing.remove(collection)
        if collection not in existing:
            client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(
                    size=space.dimension,
                    distance=Distance.COSINE,
                ),
            )
    return targets


def alias_targets(client) -> dict[str, str]:
    aliases = getattr(client.get_aliases(), "aliases", [])
    return {
        item.alias_name: item.collection_name
        for item in aliases
        if item.alias_name in ACTIVE_ALIASES.values()
    }


def switch_aliases(
    client,
    targets: Mapping[str, str],
    *,
    expected_current: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Atomically repoint all four active aliases and return rollback targets."""
    from qdrant_client.models import (
        CreateAlias,
        CreateAliasOperation,
        DeleteAlias,
        DeleteAliasOperation,
    )

    if set(targets) != set(ACTIVE_ALIASES):
        raise ValueError("targets must contain candidates, jobs and both centroids")
    existing_collections = {item.name for item in client.get_collections().collections}
    missing = set(targets.values()) - existing_collections
    if missing:
        raise IndexValidationError(f"target collections are missing: {sorted(missing)}")

    previous = alias_targets(client)
    if expected_current is not None and previous != dict(expected_current):
        raise IndexValidationError("active aliases changed since validation")

    operations = []
    for alias in ACTIVE_ALIASES.values():
        if alias in previous:
            operations.append(
                DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias))
            )
    for entity, alias in ACTIVE_ALIASES.items():
        operations.append(
            CreateAliasOperation(
                create_alias=CreateAlias(
                    collection_name=targets[entity],
                    alias_name=alias,
                )
            )
        )
    client.update_collection_aliases(change_aliases_operations=operations)
    return previous


def rollback_aliases(
    client,
    previous_alias_targets: Mapping[str, str],
    *,
    expected_current: Optional[Mapping[str, str]] = None,
) -> None:
    """Rollback uses the same atomic operation and never copies vectors."""
    by_entity = {
        entity: previous_alias_targets[alias]
        for entity, alias in ACTIVE_ALIASES.items()
        if alias in previous_alias_targets
    }
    if set(by_entity) != set(ACTIVE_ALIASES):
        raise IndexValidationError("rollback snapshot does not contain all aliases")
    switch_aliases(client, by_entity, expected_current=expected_current)


def validate_physical_collections(
    client,
    *,
    expected_counts: Mapping[str, int],
    sample_hashes: Mapping[str, Mapping[int, str]],
    outbox_backlog: int,
    gold_set_passed: bool,
    space: VectorSpace = VOYAGE4_TEXT_V2,
) -> list[CollectionValidation]:
    """Fail closed before cutover on shape, counts, hashes, queue or quality."""
    if outbox_backlog != 0:
        raise IndexValidationError(f"embedding outbox backlog is {outbox_backlog}")
    if not gold_set_passed:
        raise IndexValidationError("matching gold set did not pass")

    targets = physical_collections(space)
    validations: list[CollectionValidation] = []
    for entity, collection in targets.items():
        info = client.get_collection(collection)
        points = int(getattr(info, "points_count", -1))
        expected = expected_counts.get(entity)
        if expected is None or points != expected:
            raise IndexValidationError(
                f"{entity} count mismatch: expected={expected} actual={points}"
            )
        dimension = _vector_dimension(info)
        if dimension != space.dimension:
            raise IndexValidationError(
                f"{entity} dimension mismatch: expected={space.dimension} actual={dimension}"
            )

        expected_hashes = sample_hashes.get(entity, {})
        sampled = 0
        if expected_hashes:
            rows = client.retrieve(
                collection_name=collection,
                ids=list(expected_hashes),
                with_payload=True,
                with_vectors=False,
            )
            actual_hashes = {
                int(row.id): (row.payload or {}).get("source_hash") for row in rows
            }
            for point_id, expected_hash in expected_hashes.items():
                if actual_hashes.get(point_id) != expected_hash:
                    raise IndexValidationError(
                        f"{entity} source hash mismatch for point {point_id}"
                    )
                sampled += 1
        validations.append(
            CollectionValidation(
                entity=entity,
                collection=collection,
                points=points,
                dimension=dimension,
                sampled_hashes=sampled,
            )
        )
    return validations
