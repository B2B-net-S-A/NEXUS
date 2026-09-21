"""Reviewed backend-owned policies. Database publications remain the runtime source."""

from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, func

from app.core.config import settings
from app.models.client import Client
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_event import ClientCvRuleEvent
from app.models.client_cv_rule_publication import ClientCvRulePublication


def enabled() -> bool:
    return settings.CV_CENTRAL_POLICIES_ENABLED


@lru_cache(maxsize=1)
def catalog() -> tuple[dict, ...]:
    return tuple(
        json.loads((Path(__file__).parents[2] / "data/cv_policies.json").read_text())
    )


def policy_for(client_id: int | None) -> dict:
    entry = next((p for p in catalog() if p["client_id"] == client_id), None)
    return dict(
        entry
        or {
            "key": "standard",
            "version": 1,
            "source_url": None,
            "filename_pattern": "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
            "spaces_to_underscores": False,
            "cv_language": None,
            "requires_en_copy": False,
            "auto_second_language": False,
            "requires_rodo_consent_block": False,
            "require_project_ref": False,
            "require_position": False,
            "require_recommendation_note": False,
        }
    )


def recipe_for(policy: dict) -> dict:
    # Whitelist presentation fields only; never ingest the operational playbook.
    return {
        **{
            k: policy[k]
            for k in (
                "filename_pattern",
                "spaces_to_underscores",
                "cv_language",
                "requires_en_copy",
                "auto_second_language",
                "requires_rodo_consent_block",
            )
        },
        "content_mode": None,
        "content_mode_locked": False,
        "require_project_ref": False,
        "require_position": False,
        "require_champion": False,
        "require_screening_notes_min_chars": None,
        "notes": None,
        "generator_instructions": None,
        "generator_instructions_en": None,
        "omit_sections": None,
        "max_roles": None,
        "max_bullets_per_role": None,
        "max_bullet_chars": None,
        "why_points_max": 4,
        "date_format": None,
        "glossary": None,
        "highlight_policy": "technologies",
        "highlight_terms": None,
    }


def metadata(policy: dict) -> dict:
    return {
        k: v for k, v in policy.items() if k not in ("external_source", "external_id")
    }


async def synchronize(db) -> int:
    """Atomic, idempotent publication. Parent locks serialize concurrent app starts."""
    count = 0
    for policy in sorted(catalog(), key=lambda p: p["client_id"]):
        client = await db.scalar(
            select(Client).where(Client.id == policy["client_id"]).with_for_update()
        )
        if client is None:
            continue  # Empty development database: never fabricate clients.
        if (client.external_source, client.external_id) != (
            policy["external_source"],
            policy["external_id"],
        ):
            raise RuntimeError(f"CV policy client identity mismatch: {client.id}")
        if client.hidden or client.merged_into_client_id:
            raise RuntimeError(f"CV policy client is not canonical: {client.id}")
        rule = await db.scalar(
            select(ClientCvRule).where(ClientCvRule.client_id == client.id)
        )
        desired = recipe_for(policy)
        managed = metadata(policy)
        if (
            rule
            and rule.managed_policy == managed
            and all(getattr(rule, k) == v for k, v in desired.items())
            and rule.confirmed_at
        ):
            continue
        flags = {
            k: getattr(client, k)
            for k in ("cv_content_mode_cap", "cv_interactive_enabled")
        }
        old = {**{k: getattr(rule, k) for k in desired}, **flags} if rule else {}
        draft = rule.draft_payload if rule else None
        versions = [int(rule.version or 0)] if rule else [0]
        for model, column in (
            (ClientCvRulePublication, ClientCvRulePublication.version),
            (ClientCvRuleEvent, ClientCvRuleEvent.rule_version),
        ):
            versions.append(
                int(
                    await db.scalar(
                        select(func.max(column)).where(model.client_id == client.id)
                    )
                    or 0
                )
            )
        version = max(versions) + 1
        if (
            rule
            and rule.confirmed_at
            and not await db.get(ClientCvRulePublication, (client.id, rule.version))
        ):
            db.add(
                ClientCvRulePublication(
                    client_id=client.id,
                    version=rule.version,
                    recipe=old,
                    published_at=rule.confirmed_at,
                    published_by=rule.confirmed_by,
                )
            )
        if rule is None:
            rule = ClientCvRule(client_id=client.id)
            db.add(rule)
        for key, value in desired.items():
            setattr(rule, key, value)
        rule.version = version
        rule.managed_policy = managed
        rule.seed_key = policy["key"]
        rule.confirmed_at = datetime.now(timezone.utc)
        rule.confirmed_by = None
        rule.draft_payload = None
        rule.edit_revision = (
            max(rule.edit_revision or 0, client.cv_rule_edit_revision or 0) + 1
        )
        client.cv_rule_edit_revision = rule.edit_revision
        db.add(
            ClientCvRulePublication(
                client_id=client.id,
                version=version,
                recipe={**desired, **flags, "managed_policy": managed},
                published_at=rule.confirmed_at,
            )
        )
        db.add(
            ClientCvRuleEvent(
                client_id=client.id,
                rule_version=version,
                action="central_published",
                actor_name="Centralny katalog CV",
                changes={
                    "previous_recipe": old,
                    "previous_draft": draft,
                    "managed_policy": managed,
                },
            )
        )
        count += 1
    await db.commit()
    return count


async def resolve(db, client_id: int | None):
    policy = policy_for(client_id)
    if policy["key"] == "standard":
        return ClientCvRule(
            client_id=client_id,
            version=0,
            confirmed_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
            managed_policy=metadata(policy),
            **recipe_for(policy),
        )
    row = await db.scalar(
        select(ClientCvRule).where(
            ClientCvRule.client_id == client_id, ClientCvRule.confirmed_at.is_not(None)
        )
    )
    if row is None or row.managed_policy != metadata(policy):
        raise HTTPException(
            503,
            "Polityka CV klienta oczekuje na synchronizację. Spróbuj ponownie później.",
        )
    return row


def automatic_mode(job, cap=None) -> str:
    from app.services.champion_intake import enforce_operation
    from app.services.cv_generator_b2b.standalone_service import (
        apply_content_mode_cap,
        champion_present,
    )

    mode = "polished"
    if (
        job is not None
        and getattr(job, "champion_profile", None)
        and champion_present(job)
    ):
        try:
            enforce_operation(job, "cv", force=True)
            mode = "tailored"
        except HTTPException:
            pass
    return apply_content_mode_cap(mode, cap)[0]


def stamp(rule, *, language: str, project_ref: str, stage_id=None) -> dict | None:
    if not enabled():
        return None
    policy = dict(getattr(rule, "managed_policy", None) or metadata(policy_for(None)))
    policy.update(
        publication_version=rule.version,
        required_languages=["pl", "en"]
        if policy["requires_en_copy"]
        else [policy.get("cv_language") or language],
        project_ref=project_ref,
        stage_id=stage_id,
    )
    return policy
