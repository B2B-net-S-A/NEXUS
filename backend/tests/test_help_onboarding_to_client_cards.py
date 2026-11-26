"""Pomoc bez wzorów Word: formularze onboardingowe na karty klientów (26.11.2026)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.services.help_onboarding_to_client_cards import (
    DOCUMENTS_LIMIT,
    ONBOARDING_SLUG_TO_CLIENT,
    REPAIR_MARKER,
    REPLACED_TEMPLATE_SLUGS,
    _merged,
    summarize_for_log,
)

_ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _doc(n: int) -> dict[str, str]:
    return {"name": f"Plik {n}", "url": f"https://example.org/{n}"}


# ── Bez bazy ────────────────────────────────────────────────────────────────


def test_every_slug_is_seeded_by_the_entrypoint() -> None:
    """Krok czyta wiersze po slugu — literówka znaczyłaby cichy brak formularza."""
    source = _ENTRYPOINT.read_text(encoding="utf-8")
    for slug in [*ONBOARDING_SLUG_TO_CLIENT, *REPLACED_TEMPLATE_SLUGS]:
        if slug == "umowa-przedwstepna-cez":
            continue  # dodany przez admina w UI (14.09.2026), seeda nie ma
        assert f"'{slug}'" in source, slug


def test_entrypoint_runs_the_step_under_its_marker() -> None:
    source = _ENTRYPOINT.read_text(encoding="utf-8")
    assert f'run_unless_marked "{REPAIR_MARKER}"' in source


def test_prep_invite_is_not_touched() -> None:
    assert "zaproszenie-prep-spotkanie" not in ONBOARDING_SLUG_TO_CLIENT
    assert "zaproszenie-prep-spotkanie" not in REPLACED_TEMPLATE_SLUGS


def test_merge_skips_links_already_on_the_card() -> None:
    assert _merged([_doc(1)], [_doc(1)]) is None
    assert _merged([_doc(1)], [_doc(1), _doc(2)]) == [_doc(1), _doc(2)]
    assert _merged(None, [_doc(3), _doc(3)]) == [_doc(3)]


def test_merge_respects_the_card_limit() -> None:
    full = [_doc(i) for i in range(DOCUMENTS_LIMIT)]
    assert _merged(full, [_doc(999)]) is None
    almost = full[:-1]
    assert _merged(almost, [_doc(998), _doc(999)]) == [*almost, _doc(998)]


def test_log_has_only_ids_and_counts() -> None:
    summary = {
        "changed": 1,
        "documents_added": 3,
        "unpublished": 7,
        "results": [{"client_id": 5, "skipped": "no_card", "added": 0}],
    }
    assert (
        summarize_for_log(summary) == "cards=1 docs=3 unpublished=7 skipped=5:no_card"
    )
    assert summarize_for_log(None) == "already done"


# ── Na bazie ────────────────────────────────────────────────────────────────


async def _client_with_card(documents: list | None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client, ClientStatus
    from app.models.client_playbook import ClientPlaybook

    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"Pomoc {uuid.uuid4().hex[:6]}", status=ClientStatus.active
        )
        db.add(client)
        await db.flush()
        db.add(ClientPlaybook(client_id=client.id, version=1, documents=documents))
        await db.commit()
        return client.id


async def _material(slug: str, url: str | None, *, body: str | None = None) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.help_material import HelpMaterial

    async with AsyncSessionLocal() as db:
        db.add(
            HelpMaterial(
                slug=slug,
                category="Onboarding — test",
                title=f"{slug}.docx",
                url=url,
                template_body=body,
                is_published=True,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_forms_move_to_cards_once_and_leave_help() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.models.client import Client
    from app.models.client_playbook import ClientPlaybook
    from app.models.client_playbook_event import ClientPlaybookEvent
    from app.models.help_material import HelpMaterial
    from app.services.help_onboarding_to_client_cards import (
        run_help_onboarding_to_client_cards,
    )

    tag = uuid.uuid4().hex[:6]
    marker = f"test_help_onboarding_{tag}"
    s = {k: f"{k}-{tag}" for k in ("a1", "a2", "b1", "gone", "tpl", "prep")}
    fresh = await _client_with_card(None)
    has_link = await _client_with_card(
        [{"name": "Już jest", "url": "https://x.test/b1"}]
    )
    missing = 999_999_321
    await _material(s["a1"], "https://x.test/a1")
    await _material(s["a2"], "https://x.test/a2")
    await _material(s["b1"], "https://x.test/b1")
    await _material(s["gone"], "https://x.test/gone")
    await _material(s["tpl"], "https://x.test/tpl")
    await _material(s["prep"], None, body="Dzień dobry")
    mapping = {s["a1"]: fresh, s["a2"]: fresh, s["b1"]: has_link, s["gone"]: missing}
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_help_onboarding_to_client_cards(
                db, marker=marker, slug_to_client=mapping, replaced_slugs=(s["tpl"],)
            )
            await db.commit()
        assert summary is not None
        assert summary["changed"] == 1 and summary["documents_added"] == 2
        skipped = {r["client_id"]: r["skipped"] for r in summary["results"]}
        assert skipped == {
            fresh: None,
            has_link: "nothing_to_change",
            missing: "no_card",
        }

        async with AsyncSessionLocal() as db:
            cards = {
                c.client_id: c
                for c in (
                    await db.execute(
                        select(ClientPlaybook).where(
                            ClientPlaybook.client_id.in_([fresh, has_link])
                        )
                    )
                ).scalars()
            }
            events = (
                (
                    await db.execute(
                        select(ClientPlaybookEvent).where(
                            ClientPlaybookEvent.client_id.in_([fresh, has_link])
                        )
                    )
                )
                .scalars()
                .all()
            )
            published = {
                m.slug: m.is_published
                for m in (
                    await db.execute(
                        select(HelpMaterial).where(
                            HelpMaterial.slug.in_(list(s.values()))
                        )
                    )
                ).scalars()
            }
        assert cards[fresh].documents == [
            {"name": f"{s['a1']}.docx", "url": "https://x.test/a1"},
            {"name": f"{s['a2']}.docx", "url": "https://x.test/a2"},
        ]
        assert cards[fresh].version == 2
        assert cards[has_link].version == 1
        assert [(e.client_id, e.playbook_version, e.action) for e in events] == [
            (fresh, 2, "saved")
        ]
        assert set(events[0].changes) == {"documents"}
        # Na karcie (także sprzed kroku) = schodzi z Pomocy; bez karty zostaje.
        assert published == {
            s["a1"]: False,
            s["a2"]: False,
            s["b1"]: False,
            s["gone"]: True,
            s["tpl"]: False,
            s["prep"]: True,
        }

        async with AsyncSessionLocal() as db:
            again = await run_help_onboarding_to_client_cards(
                db, marker=marker, slug_to_client=mapping, replaced_slugs=(s["tpl"],)
            )
            await db.commit()
        assert again is None
    finally:
        async with AsyncSessionLocal() as db:
            ids = [fresh, has_link]
            for model in (ClientPlaybookEvent, ClientPlaybook):
                await db.execute(delete(model).where(model.client_id.in_(ids)))
            await db.execute(delete(Client).where(Client.id.in_(ids)))
            await db.execute(
                delete(HelpMaterial).where(HelpMaterial.slug.in_(list(s.values())))
            )
            await db.execute(delete(AppSetting).where(AppSetting.key == marker))
            await db.commit()
