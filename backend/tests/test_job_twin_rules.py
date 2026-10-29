"""Zasady bliźniaków w Ustawieniach (decyzje Artura z 29.10.2026).

„Wymagane” tylko filtruje listę „Możliwe bliźniaki” (łączyć ręcznie wolno),
zasady startowe jak w makiecie. Bez bazy: walidacja, ocena pary, miasta.
Z bazą: kto zmienia, ślad zmiany, filtr listy HoR, limit bliźniaków, podgląd.
"""

from __future__ import annotations


import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.job import Job
from app.models.user import UserRole
from app.services import job_twin_rules as rules_mod
from app.services import job_twins
from app.services.job_twin_rules import JobFacts, TwinRules

from tests.test_job_twins import _job, _user


def _facts(**over) -> JobFacts:
    base = dict(
        id=1,
        title="Analityk Systemowy",
        critical=(),
        must=("REST API", "SOAP", "Kafka"),
        cities=frozenset({"warszawa"}),
        remote_policy="hybrid",
        onsite_days=1,
        work_mode="1 dni z biura",
        budget=110.0,
        client_id=1,
        category_id=5,
        delivery_lead_id=10,
    )
    base.update(over)
    return JobFacts(**base)


# ── Bez bazy ──────────────────────────────────────────────────────────────


def test_defaults_match_the_mockup() -> None:
    rules = rules_mod.defaults()
    assert rules.min_similarity == 80
    assert (rules.critical.mode, rules.different_dl.mode) == ("required", "required")
    assert {
        rules.must.mode,
        rules.location.mode,
        rules.work_mode.mode,
        rules.budget.mode,
    } == {"warning"}
    assert (rules.client.mode, rules.category.mode) == ("off", "off")
    assert (rules.max_twins, rules.open_similar_limit, rules.pair_hint) == (
        3,
        8,
        "default",
    )


def test_rules_refuse_values_outside_the_panel() -> None:
    with pytest.raises(ValidationError):
        TwinRules(min_similarity=60)
    with pytest.raises(ValidationError):
        TwinRules(max_twins=4)
    with pytest.raises(ValidationError):
        TwinRules.model_validate({"critical": {"mode": "maybe"}})


def test_city_parsing_ignores_free_text_and_streets() -> None:
    assert rules_mod._cities("Warszawa, ul. Chmielna 89") == {"warszawa"}  # noqa: SLF001
    assert rules_mod._cities("Kraków/Gdańsk/Warszawa") == {
        "krakow",
        "gdansk",
        "warszawa",
    }  # noqa: SLF001
    assert (
        rules_mod._cities("Sporadycznie, 1-2 dni w miesiącu, możliwa 100% praca zdalna")
        == frozenset()
    )  # noqa: SLF001


def test_critical_rule_on_the_real_pair_and_title_option() -> None:
    # ZOB-2852 (krytyczna „analiza systemowa”) ↔ 6755 („Analityk Systemowy
    # Integracyjny”, bez krytycznych) — na kopii produkcji 84%.
    pko = _facts(
        critical=("analiza systemowa",), must=("Analiza systemowa", "REST API", "SOAP")
    )
    alior = _facts(
        id=2, title="Analityk Systemowa Integracyjny", must=("REST API", "SOAP")
    )
    checks = {c.key: c for c in rules_mod.evaluate(TwinRules(), pko, alior)}
    assert checks["critical"].ok is False
    assert "analiza systemowa" in checks["critical"].detail
    assert rules_mod.required_failures(list(checks.values()))[0].key == "critical"
    with_title = TwinRules.model_validate(
        {"critical": {"mode": "required", "include_title": True}}
    )
    assert {c.key: c.ok for c in rules_mod.evaluate(with_title, pko, alior)}[
        "critical"
    ] is True


def test_warnings_location_work_mode_budget_and_off_rules() -> None:
    a = _facts()
    b = _facts(
        id=2,
        cities=frozenset({"krakow"}),
        remote_policy="remote",
        onsite_days=None,
        work_mode="zdalnie",
        budget=125.0,
        client_id=2,
    )
    checks = {c.key: c for c in rules_mod.evaluate(TwinRules(), a, b)}
    assert [k for k, c in checks.items() if not c.ok] == [
        "location",
        "work_mode",
        "budget",
    ]
    assert not rules_mod.required_failures(list(checks.values()))
    assert "client" not in checks and "category" not in checks  # wyłączone
    strict = TwinRules.model_validate({"client": {"mode": "required"}})
    assert (
        rules_mod.required_failures(rules_mod.evaluate(strict, a, b))[0].key == "client"
    )


# ── Z bazą ────────────────────────────────────────────────────────────────


@pytest.fixture
async def clean_rules():
    rules_mod.reset_cache()
    job_twins.reset_suggestion_cache()
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == rules_mod.SETTING_KEY)
        )
        await db.commit()
    yield
    rules_mod.reset_cache()
    job_twins.reset_suggestion_cache()
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == rules_mod.SETTING_KEY)
        )
        await db.commit()


async def test_only_hor_and_admin_change_rules_and_the_change_is_logged(
    app_client: AsyncClient,
    clean_rules,
) -> None:
    _dl_id, dl = await _user(UserRole.delivery_lead)
    hor_id, hor = await _user(UserRole.head_of_recruitment)
    got = await app_client.get("/api/job-twins/rules", headers=dl)
    assert got.status_code == 200, got.text
    assert (
        got.json()["can_edit"] is False and got.json()["rules"]["min_similarity"] == 80
    )
    body = {
        **got.json()["rules"],
        "min_similarity": 75,
        "location": {"mode": "required"},
    }
    refused = await app_client.put("/api/job-twins/rules", headers=dl, json=body)
    assert refused.status_code == 403, refused.text
    saved = await app_client.put("/api/job-twins/rules", headers=hor, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["rules"]["location"]["mode"] == "required"
    again = await app_client.get("/api/job-twins/rules", headers=dl)
    assert again.json()["rules"]["min_similarity"] == 75
    async with AsyncSessionLocal() as db:
        trace = (
            (
                await db.execute(
                    select(Activity).where(
                        Activity.action == "job_twin_rules_changed",
                        Activity.user_id == hor_id,
                    )
                )
            )
            .scalars()
            .one()
        )
    assert trace.details["changed"]["min_similarity"] == {"before": 80, "after": 75}
    bad = await app_client.put(
        "/api/job-twins/rules", headers=hor, json={**body, "min_similarity": 50}
    )
    assert bad.status_code == 422


async def _two_pairs(monkeypatch) -> dict:
    """Dwie pary otwartych rekrutacji różnych DL-i, obie po 85% — jedna
    z krytyczną, której druga nie ma."""
    dl_a, _ = await _user(UserRole.delivery_lead)
    dl_b, _ = await _user(UserRole.delivery_lead)
    ids = {k: await _job(dl_id=dl_a if k in ("a", "c") else dl_b) for k in "abcd"}
    async with AsyncSessionLocal() as db:
        for key, must, critical in (
            ("a", ["Python", "Django"], None),
            ("b", ["Python", "Django"], None),
            ("c", ["Analiza systemowa", "REST API"], ["Analiza systemowa"]),
            ("d", ["REST API", "SOAP"], None),
        ):
            job = await db.get(Job, ids[key])
            job.must_skills = must
            job.champion_profile = (
                {"stack": {"critical": critical}} if critical else None
            )
        await db.commit()

    async def fake_nearest(refs, candidates, *, limit):
        pairs = {(ids["a"], ids["b"]), (ids["c"], ids["d"])}
        out: dict[int, list] = {}
        for x, y in pairs:
            out.setdefault(x, []).append((y, 0.85))
            out.setdefault(y, []).append((x, 0.85))
        return {r: out.get(r, []) for r in refs}

    monkeypatch.setattr(job_twins, "_nearest", fake_nearest)
    return ids


async def test_required_rule_filters_the_hor_list_but_linking_still_works(
    app_client: AsyncClient, monkeypatch, clean_rules
) -> None:
    ids = await _two_pairs(monkeypatch)
    _hor_id, hor = await _user(UserRole.head_of_recruitment)
    listed = await app_client.get("/api/job-twins/suggestions", headers=hor)
    pairs = {
        frozenset((i["job"]["id"], i["other"]["id"])) for i in listed.json()["items"]
    }
    assert frozenset((ids["a"], ids["b"])) in pairs
    assert frozenset((ids["c"], ids["d"])) not in pairs  # krytyczna — wymagana

    preview = await app_client.get(
        f"/api/jobs/{ids['c']}/twins/preview?other_job_id={ids['d']}", headers=hor
    )
    rule = {r["key"]: r for r in preview.json()["rules"]}["critical"]
    assert rule["ok"] is False and rule["mode"] == "required"
    linked = await app_client.post(
        f"/api/jobs/{ids['c']}/twins", headers=hor, json={"other_job_id": ids["d"]}
    )
    assert linked.status_code == 200, linked.text  # „Wymagane” nie blokuje łączenia

    rules = (await app_client.get("/api/job-twins/rules", headers=hor)).json()["rules"]
    preview_off = await app_client.post(
        "/api/job-twins/rules/preview",
        headers=hor,
        json={**rules, "critical": {"mode": "off", "include_title": False}},
    )
    assert preview_off.status_code == 200, preview_off.text
    body = preview_off.json()
    assert body["suggestions"] >= 1 and "per_rule" in body


async def test_max_twins_from_rules(app_client: AsyncClient, clean_rules) -> None:
    _hor_id, hor = await _user(UserRole.head_of_recruitment)
    rules = (await app_client.get("/api/job-twins/rules", headers=hor)).json()["rules"]
    await app_client.put(
        "/api/job-twins/rules", headers=hor, json={**rules, "max_twins": 1}
    )
    a = await _job(dl_id=None)
    first = await app_client.post(
        f"/api/jobs/{a}/twins",
        headers=hor,
        json={"other_job_id": await _job(dl_id=None)},
    )
    assert first.status_code == 200, first.text
    second = await app_client.post(
        f"/api/jobs/{a}/twins",
        headers=hor,
        json={"other_job_id": await _job(dl_id=None)},
    )
    assert second.status_code == 422
    assert second.json()["detail"]["code"] == "twin_limit"
