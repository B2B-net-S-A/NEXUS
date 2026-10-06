"""Cofnięcie stawek profilu wpisanych przez scrapery (audyt 06.10.2026, D5).

Scraper (klient OAuth) wpisywał „szacunek” z widełek UoP (÷ 168 h) jako ręczną
stawkę B2B. Narzędzie cofa każdy taki zapis, którego nikt później nie zmienił:
przywraca stawkę sprzed scrapera z jej datą, zdejmuje znacznik „ręcznie”
(chyba że wcześniej wpisał ją człowiek) i wyłącza kwotę scrapera z „Stawki od”.
Nocny odczyt notatek nie widzi linii „szacunek stawki B2B …”.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import scraper_rate_revert as revert
from app.services.notes_insights_extractor import (
    build_notes_blob,
    strip_scraper_rate_estimate,
)
from tests.test_job_board_proposals import (
    _seed_admin,
    _seed_candidate,
    _seed_integration_user,
)

_T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def _write(aid: int, old: str | None, new: str, old_v: int, minutes: int = 0):
    return revert.ScraperWrite(
        activity_id=aid,
        created_at=_T0 + timedelta(minutes=minutes),
        old_amount=Decimal(old) if old else None,
        new_amount=Decimal(new),
        old_version=old_v,
        new_version=old_v + 1,
    )


# ── bez bazy ─────────────────────────────────────────────────────────────────


def test_chain_of_scraper_writes_reverts_to_the_first_old_amount():
    writes = [_write(1, "120.00", "48.00", 3), _write(2, "48.00", "52.00", 4, 5)]
    chain, reason = revert.plan_for_candidate(writes, current_version=5)
    assert reason == "to_revert"
    assert [w.activity_id for w in chain] == [1, 2]
    item = revert.PlannedRevert(candidate_id=7, chain=chain)
    assert item.restore_amount == Decimal("120.00")
    assert item.expected_version == 5


def test_later_human_change_keeps_the_rate():
    writes = [_write(1, "120.00", "48.00", 3)]
    chain, reason = revert.plan_for_candidate(writes, current_version=5)
    assert chain is None and reason == "changed_after_scraper"
    assert revert.plan_for_candidate(writes, None) == (None, "candidate_missing")


def test_previous_rate_in_foreign_currency_is_left_for_a_human():
    # `write_profile_rate` zapisuje zawsze PLN/h — „50 EUR” nie może wrócić
    # jako 50 zł/h.
    eur = _write(1, "50.00", "48.00", 3)
    eur.old_currency = "EUR"
    assert revert.plan_for_candidate([eur], current_version=4) == (
        None,
        "non_pln_previous",
    )
    pln = _write(2, "50.00", "48.00", 3)
    pln.old_currency = "PLN"
    chain, reason = revert.plan_for_candidate([pln], current_version=4)
    assert reason == "to_revert" and chain == [pln]
    empty = _write(3, None, "48.00", 3)
    empty.old_currency = None
    assert revert.plan_for_candidate([empty], current_version=4)[1] == "to_revert"


def test_only_the_latest_scraper_run_counts_after_a_human_gap():
    # Scraper (v1→2), człowiek (v2→3), scraper (v3→4): cofa się tylko ostatni.
    writes = [_write(1, None, "40.00", 1), _write(2, "150.00", "48.00", 3, 9)]
    chain, _ = revert.plan_for_candidate(writes, current_version=4)
    assert [w.activity_id for w in chain] == [2]
    assert revert.PlannedRevert(candidate_id=1, chain=chain).restore_amount == Decimal(
        "150.00"
    )


@pytest.mark.parametrize(
    "note",
    [
        "Oczekiwania finansowe netto: 8000 / mies.\n"
        "→ szacunek stawki B2B: 48 zł/h netto (dolny próg widełek ÷ 168 h) — wpisano\n"
        "Termin rozpoczęcia pracy: od zaraz",
        "<p>Oczekiwania finansowe netto: 8000 / mies.</p>"
        "<p>→ szacunek stawki B2B: 48 zł/h netto (dolny próg widełek ÷ 168 h)</p>"
        "<p>Termin rozpoczęcia pracy: od zaraz</p>",
    ],
)
def test_scraper_estimate_line_never_reaches_the_model(note):
    stripped = strip_scraper_rate_estimate(note)
    assert "szacunek" not in stripped and "48 zł/h" not in stripped
    assert "8000" in stripped and "od zaraz" in stripped
    blob = build_notes_blob([(1, None, "2026-10-01", note)])
    assert "48 zł/h" not in blob and "8000" in blob


def test_strip_keeps_notes_without_estimate():
    note = "Rozmowa: chce 160 zł/h na B2B"
    assert strip_scraper_rate_estimate(note) == note


# ── z bazą (CI) ──────────────────────────────────────────────────────────────


async def _set_rate(candidate_id: int, amount: str | None, actor_id: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.candidate_profile_facts import update_candidate_profile_rate

    async with AsyncSessionLocal() as db:
        version = await db.scalar(
            text("SELECT profile_rate_version FROM candidates WHERE id = :c"),
            {"c": candidate_id},
        )
        await update_candidate_profile_rate(
            db,
            candidate_id=candidate_id,
            amount=Decimal(amount) if amount is not None else None,
            expected_version=version or 0,
            actor_id=actor_id,
        )
        await db.commit()
        assert await db.get(Candidate, candidate_id) is not None


async def _own_plan(candidate_ids: set[int]):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        plan, counts = await revert.build_plan(db)
    return [p for p in plan if p.candidate_id in candidate_ids], counts


async def _state(candidate_id: int) -> dict:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT expected_rate_hourly, profile_rate_updated_at, "
                    "profile_rate_version, cv_extracted_data "
                    "FROM candidates WHERE id = :c"
                ),
                {"c": candidate_id},
            )
        ).mappings().one()
        decisions = (
            await db.execute(
                text(
                    "SELECT observation_key, observed_amount, observed_at "
                    "FROM candidate_rate_decisions WHERE candidate_id = :c"
                ),
                {"c": candidate_id},
            )
        ).mappings().all()
        earliest = await db.scalar(
            text(
                "SELECT min(created_at) FROM activities WHERE entity_type = "
                "'candidate' AND entity_id = :c AND action = 'profile_rate_changed'"
            ),
            {"c": candidate_id},
        )
        return {**dict(row), "decisions": list(decisions), "first_change": earliest}


@pytest.mark.asyncio
async def test_revert_restores_human_rate_with_its_date(app_client):
    from app.core.database import AsyncSessionLocal

    admin = await _seed_admin()
    scraper = await _seed_integration_user()
    cand = await _seed_candidate()
    await _set_rate(cand, "120", admin)  # człowiek
    await _set_rate(cand, "48", scraper)  # scraper
    plan, counts = await _own_plan({cand})
    assert len(plan) == 1 and counts["to_revert"] >= 1

    async with AsyncSessionLocal() as db:
        await revert.lock_for_apply(db)
        run = await revert.apply_plan(db, plan, counts, user_id=admin)
        await db.commit()
    assert run["counts"]["reverted"] == 1

    state = await _state(cand)
    assert state["expected_rate_hourly"] == Decimal("120.00")
    # Data stawki = data zapisu człowieka, nie dzisiejsza.
    assert state["profile_rate_updated_at"] == state["first_change"]
    # Stawkę wpisał wcześniej człowiek — znacznik „ręcznie” zostaje.
    assert state["cv_extracted_data"].get("_manual_override_rate") is True
    (decision,) = state["decisions"]
    assert decision["observation_key"].startswith("profile:")
    assert decision["observed_amount"] == Decimal("48.00")

    again, _ = await _own_plan({cand})
    assert again == []


@pytest.mark.asyncio
async def test_revert_to_empty_drops_the_manual_flag(app_client):
    from app.core.database import AsyncSessionLocal

    admin = await _seed_admin()
    scraper = await _seed_integration_user()
    cand = await _seed_candidate()
    await _set_rate(cand, "48", scraper)
    plan, counts = await _own_plan({cand})
    async with AsyncSessionLocal() as db:
        await revert.apply_plan(db, plan, counts, user_id=admin)
        await db.commit()
    state = await _state(cand)
    assert state["expected_rate_hourly"] is None
    assert "_manual_override_rate" not in (state["cv_extracted_data"] or {})


@pytest.mark.asyncio
async def test_human_change_after_scraper_is_left_alone(app_client):
    admin = await _seed_admin()
    scraper = await _seed_integration_user()
    cand = await _seed_candidate()
    await _set_rate(cand, "48", scraper)
    await _set_rate(cand, "140", admin)
    plan, counts = await _own_plan({cand})
    assert plan == []
    assert counts.get("changed_after_scraper", 0) >= 1


@pytest.mark.asyncio
async def test_endpoint_requires_matching_expected(app_client):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.api.admin_candidates import revert_scraper_rates
    from app.core.database import AsyncSessionLocal

    admin = SimpleNamespace(id=await _seed_admin())
    async with AsyncSessionLocal() as db:
        dry = await revert_scraper_rates(admin=admin, dry_run=True, expected=None, db=db)
    assert dry["dry_run"] is True and "counts" in dry
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await revert_scraper_rates(
                admin=admin,
                dry_run=False,
                expected=dry["counts"].get("to_revert", 0) + 10_000,
                db=db,
            )
        assert exc.value.status_code == 409
