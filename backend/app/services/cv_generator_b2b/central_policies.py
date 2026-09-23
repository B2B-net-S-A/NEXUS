"""Reviewed backend-owned policies. Database publications remain the runtime source."""

from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, func

from app.core.config import settings
from app.models.client import Client
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_event import ClientCvRuleEvent
from app.models.client_cv_rule_publication import ClientCvRulePublication

logger = logging.getLogger(__name__)


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
            "version": 2,
            "content_mode": "tailored",
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
        # The "at most four summary points" standard lives in the central
        # system prompt (presentation_title.instructions). Rendering it again
        # as a client instruction made the model report it as "skipped".
        "why_points_max": None,
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
        # A client that no longer matches the reviewed catalog is skipped, not
        # fatal: the others still publish, and `resolve` answers 503 for this
        # one until the catalog is corrected. Only IDs are logged.
        if (client.external_source, client.external_id) != (
            policy["external_source"],
            policy["external_id"],
        ):
            logger.error("CV policy client identity mismatch: client_id=%s", client.id)
            continue
        if client.hidden or client.merged_into_client_id:
            logger.error("CV policy client is not canonical: client_id=%s", client.id)
            continue
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


def job_supports_tailored(job) -> bool:
    """The one predicate for "this recruitment's Champion allows tailoring".

    Automatic mode and every later check in the recruitment path use it, so
    the mode chosen for the user can never be refused with a 422 the user
    did not ask for.
    """
    from app.services.champion_intake import enforce_operation
    from app.services.cv_generator_b2b.standalone_service import champion_present

    if job is None or not getattr(job, "champion_profile", None):
        return False
    if not champion_present(job):
        return False
    try:
        enforce_operation(job, "cv", force=True)
    except HTTPException:
        return False
    return True


MISSING_CHAMPION_NOTICE = (
    "Brak kompletnego Profilu Championa — tryb „Pod rekrutację” nie jest "
    "możliwy, powstanie CV w trybie Redakcja. Uzupełnij Profil Championa "
    "w rekrutacji albo wgraj plik Championa, aby dopasować CV."
)


def policy_content_mode(policy: dict | None) -> str:
    """Mode the catalogue assigns. Decision 21.09.2026: every client, and the
    standard policy, is "Pod rekrutację" (tailored); the per-entry field lets
    a single client be switched later without code changes."""
    mode = (policy or {}).get("content_mode")
    return mode if mode in ("tailored", "polished", "basic") else "tailored"


def resolve_mode(
    requested: str, job, cap=None, *, uploaded_champion: bool = False
) -> tuple[str, str | None]:
    """``(mode, notice)`` for a mode the recruiter chose (decision 21.09.2026:
    the mode is never locked by a central policy).

    Tailored needs a Champion — uploaded with the CV (upload path) or complete
    on the recruitment; without one the CV falls back to polished with a
    notice, never a 422. The client cap always wins."""
    from app.services.cv_generator_b2b.standalone_service import (
        apply_content_mode_cap,
    )

    mode, notice = requested, None
    if mode == "tailored" and not (uploaded_champion or job_supports_tailored(job)):
        mode, notice = "polished", MISSING_CHAMPION_NOTICE
    return apply_content_mode_cap(mode, cap)[0], notice


def automatic_mode_decision(
    job, cap=None, *, uploaded_champion: bool = False, policy: dict | None = None
) -> tuple[str, str | None]:
    """Default mode the form preselects: the catalogue mode, adjusted for
    Champion availability and the client cap. Editable by the recruiter."""
    return resolve_mode(
        policy_content_mode(policy), job, cap, uploaded_champion=uploaded_champion
    )


def automatic_mode(
    job, cap=None, *, uploaded_champion: bool = False, policy: dict | None = None
) -> str:
    return automatic_mode_decision(
        job, cap, uploaded_champion=uploaded_champion, policy=policy
    )[0]


def stamp(
    rule, *, language: str, project_ref: str, stage_id=None, force_both: bool = False
) -> dict | None:
    """Polityka zamrożona na wierszu CV.

    ``force_both`` (rekruter wybrał „Obie", generator v3): pakiet wymaga obu
    wersji także u klienta, który sam ich nie wymaga — dzięki temu ponowienie
    pakietu dorobi brakującą wersję tą samą drogą co u klientów dwujęzycznych.
    """
    if not enabled():
        return None
    policy = dict(getattr(rule, "managed_policy", None) or metadata(policy_for(None)))
    policy.update(
        publication_version=rule.version,
        required_languages=["pl", "en"]
        if policy["requires_en_copy"] or force_both
        else [policy.get("cv_language") or language],
        project_ref=project_ref,
        stage_id=stage_id,
    )
    return policy
