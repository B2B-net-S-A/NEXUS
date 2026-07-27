"""`RejectionReason.disqualifies_person` — the switch behind the hiring-manager veto.

Only reasons flagged here block re-submitting a candidate to the manager who
already rejected them after an interview. Three properties must hold, and each
of them broke a real feature when it did not:

1. **Default is off.** An unlabelled reason must never block — a 409 justified
   by "Inne" is indefensible to the recruiter who hits it.
2. **Clone carries the flag.** `clone_template` used to copy only
   name/order/category/active, so a cloned process silently lost the veto.
3. **The seed backfill is one-shot.** `_DATA_STATEMENTS` in `entrypoint.sh` runs
   on *every* container start. Without the `app_settings` marker guard it would
   restore the seeded flags after each deploy and quietly undo an admin's
   decision in Settings → Pipeline templates — a bug invisible locally that only
   shows up after a redeploy.

(1) and (2) go through the in-process HTTP fixtures. (3) is a contract test over
the two files that must stay in sync: the Alembic migration and the safety-net.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from httpx import AsyncClient

SEED_MARKER_KEY = "rejection_reason_disqualifies_seeded"

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ENTRYPOINT = _BACKEND_ROOT / "entrypoint.sh"
_MIGRATION = (
    _BACKEND_ROOT
    / "alembic"
    / "versions"
    / "0197_rejection_reason_disqualifies_person.py"
)


async def _create_template(app_client: AsyncClient, headers: dict) -> int:
    r = await app_client.post(
        "/api/pipeline-templates",
        headers=headers,
        json={"name": f"Veto-{uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _add_reason(
    app_client: AsyncClient, headers: dict, template_id: int, **payload
) -> dict:
    body = {"name": f"Powód-{uuid.uuid4().hex[:6]}", "category": "rejected"}
    body.update(payload)
    r = await app_client.post(
        f"/api/pipeline-templates/{template_id}/rejection-reasons",
        headers=headers,
        json=body,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_new_reason_defaults_to_not_disqualifying(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Fail-open: a reason nobody labelled must not block anyone."""
    template_id = await _create_template(app_client, app_auth_headers)
    created = await _add_reason(app_client, app_auth_headers, template_id)

    assert created["disqualifies_person"] is False


async def test_admin_can_toggle_flag_both_ways(
    app_client: AsyncClient, app_auth_headers: dict
):
    """PATCH drives the flag on and back off — the admin owns this decision."""
    template_id = await _create_template(app_client, app_auth_headers)
    reason = await _add_reason(
        app_client, app_auth_headers, template_id, disqualifies_person=True
    )
    assert reason["disqualifies_person"] is True

    r = await app_client.patch(
        f"/api/pipeline-templates/{template_id}/rejection-reasons/{reason['id']}",
        headers=app_auth_headers,
        json={"disqualifies_person": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["disqualifies_person"] is False

    r = await app_client.patch(
        f"/api/pipeline-templates/{template_id}/rejection-reasons/{reason['id']}",
        headers=app_auth_headers,
        json={"disqualifies_person": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["disqualifies_person"] is True


async def test_patching_other_fields_leaves_flag_untouched(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`exclude_unset` semantics: renaming a reason must not clear the veto."""
    template_id = await _create_template(app_client, app_auth_headers)
    reason = await _add_reason(
        app_client, app_auth_headers, template_id, disqualifies_person=True
    )

    r = await app_client.patch(
        f"/api/pipeline-templates/{template_id}/rejection-reasons/{reason['id']}",
        headers=app_auth_headers,
        json={"name": "Zmieniona nazwa"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["disqualifies_person"] is True


async def test_clone_template_carries_the_flag(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A cloned process must keep blocking what the original blocked."""
    template_id = await _create_template(app_client, app_auth_headers)
    blocking = await _add_reason(
        app_client,
        app_auth_headers,
        template_id,
        name="Nie spełnia wymagań technicznych",
        disqualifies_person=True,
    )
    situational = await _add_reason(
        app_client,
        app_auth_headers,
        template_id,
        name="Za wysokie oczekiwania finansowe",
        disqualifies_person=False,
    )

    r = await app_client.post(
        f"/api/pipeline-templates/{template_id}/clone",
        headers=app_auth_headers,
        params={"new_name": f"Klon-{uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 201, r.text

    cloned = {
        row["name"]: row["disqualifies_person"]
        for row in r.json()["rejection_reasons"]
    }
    assert cloned[blocking["name"]] is True
    assert cloned[situational["name"]] is False


def test_entrypoint_mirrors_the_column():
    """Prod Alembic drifts, so the safety-net must add the column too.

    Without this the ORM would select a column the database does not have, and
    `UndefinedColumn` would break *every* terminal pipeline move.
    """
    entrypoint = _ENTRYPOINT.read_text(encoding="utf-8")

    assert (
        "ALTER TABLE rejection_reasons ADD COLUMN IF NOT EXISTS "
        "disqualifies_person BOOLEAN NOT NULL DEFAULT false" in entrypoint
    )


def test_entrypoint_seed_is_guarded_and_matches_the_migration():
    """The per-boot seed must be one-shot and must not diverge from 0197.

    `_DATA_STATEMENTS` runs on every start. The `NOT EXISTS` guard is what makes
    it stop firing once anybody — seed or admin — has flagged a reason.
    """
    entrypoint = _ENTRYPOINT.read_text(encoding="utf-8")
    migration = _MIGRATION.read_text(encoding="utf-8")

    seed_stmt_present = "SET disqualifies_person = true" in entrypoint
    assert seed_stmt_present, "entrypoint lost the disqualifies_person seed"

    # Normalise whitespace *and* padding around parentheses so the assertion
    # tests the guard, not the formatter's line breaks.
    def _sql_shape(text: str) -> str:
        collapsed = " ".join(text.split())
        return collapsed.replace("( ", "(").replace(" )", ")")

    # The marker is claimed in the same statement that seeds, so the seed can
    # only fire on the run that claimed it. Deliberately *not* "is anything
    # flagged yet?" — that version comes back to life the moment an admin turns
    # every seeded reason off.
    for label, source in (("entrypoint", entrypoint), ("migration", migration)):
        shape = _sql_shape(source)
        assert SEED_MARKER_KEY in source, f"{label}: seed marker key missing"
        assert (
            "ON CONFLICT (key) DO NOTHING" in shape
        ), f"{label}: marker insert is not idempotent"
        assert (
            "EXISTS (SELECT 1 FROM marker)" in shape
        ), f"{label}: seed is not gated on the marker → redeploy resets admin intent"

    # Same reason names on both sides, or prod and a fresh DB disagree on which
    # reasons block.
    names_in_migration = set(re.findall(r'"([^"]+)",\s*\n', migration))
    seeded = {
        "Brak doświadczenia",
        "Nie spełnia wymagań technicznych",
        "Nie pasuje kulturowo",
    }
    assert seeded <= names_in_migration, "migration seed list changed"
    for name in seeded:
        assert name in entrypoint, f"entrypoint seed is missing {name!r}"
