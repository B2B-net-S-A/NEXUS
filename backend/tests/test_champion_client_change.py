"""„Klient coś zmienił” — walidacja zmian z modelu i ich zastosowanie (bez bazy)."""

from __future__ import annotations

from app.schemas.champion import ChampionProfile
from app.services import champion_client_change as cc
from app.services.champion_requirement_rows import expand_patch


def _profile() -> dict:
    return {
        "stack": {
            "rows": [
                {"words": ["Nasdaq AxiomSL ControllerView"], "level": "must"},
                {"words": ["Snowflake"], "level": "must"},
                {"words": ["SQL"], "level": "nice"},
                {"words": ["SAFe"], "level": "nice"},
            ],
            "must": [{"name": "Nasdaq AxiomSL ControllerView"}, {"name": "Snowflake"}],
            "nice": [{"name": "SQL"}, {"name": "SAFe"}],
            "critical": ["Snowflake"],
            "notes": "Raportowanie regulacyjne – KONIECZNE.",
        },
        "search": {"requirements": [["Nasdaq AxiomSL ControllerView"], ["Snowflake"]]},
        "experience": {
            "skills": [{"name": "Raportowanie regulacyjne", "level": "must"}]
        },
        "screening_questions": [
            {
                "id": "q1",
                "question": "Opisz COREP.",
                "ideal_answer": "",
                "deal_breaker": "",
            },
            {
                "id": "q2",
                "question": "AxiomSL?",
                "ideal_answer": "x",
                "deal_breaker": "y",
            },
        ],
        "project": {"about": "Rola analityka.", "responsibilities": "Analiza."},
        "client": {"selling_points": "Metodologia pracy: SAFe"},
    }


def test_python_case_cleans_and_numbers_changes():
    raw = [
        {
            "op": "row_add",
            "word": "Python",
            "level": "must",
            "quote": "Python is now a must",
        },
        {"op": "row_remove", "word": "safe", "quote": "SAFe is no longer relevant"},
        {
            "op": "notes_append",
            "text": "Python do kontroli jakości danych.",
            "quote": "q",
        },
        {"op": "question_add", "question": "Do czego używałeś Pythona?", "quote": "q"},
        {
            "op": "text_edit",
            "field": "client.selling_points",
            "after": "Metodologia pracy: Kanban",
            "quote": "moved to Kanban",
        },
    ]
    out = cc.clean_changes(raw, _profile())
    assert [c["id"] for c in out] == ["c1", "c2", "c3", "c4", "c5"]
    assert out[1] == {
        "id": "c2",
        "op": "row_remove",
        "quote": "SAFe is no longer relevant",
        "word": "SAFe",
        "before": "nice",
    }
    assert out[4]["before"] == "Metodologia pracy: SAFe"
    assert out[4]["label"] == "Co powiedzieć kandydatowi"


def test_refuses_unknown_ops_fields_and_missing_targets():
    raw = [
        {"op": "drop_table", "word": "x"},
        {"op": "row_level", "word": "Snowflake", "level": "critical"},  # krytyczne nie
        {"op": "row_remove", "word": "Kotlin"},  # nie ma takiego wiersza
        {"op": "question_remove", "id": "q9"},
        {"op": "text_edit", "field": "basics.rate_raw", "after": "999"},
        {
            "op": "text_edit",
            "field": "project.about",
            "after": "Rola analityka.",
        },  # bez zmiany
        {"op": "talk_add", "name": "raportowanie regulacyjne"},  # duplikat
        {"op": "notes_append", "text": "Raportowanie regulacyjne – KONIECZNE."},
        "not a dict",
        {"op": "question_edit", "id": "q2", "question": "AxiomSL?"},  # bez zmiany
    ]
    assert cc.clean_changes(raw, _profile()) == []
    assert cc.clean_changes(None, _profile()) == []


def test_adding_existing_row_becomes_level_change_and_dedupes():
    raw = [
        {"op": "row_add", "word": "sql", "level": "must"},
        {"op": "row_add", "word": "Python", "level": "must"},
        {"op": "row_add", "word": "python", "level": "nice"},
        {"op": "row_add", "word": "Snowflake", "level": "must"},  # już taki sam
    ]
    out = cc.clean_changes(raw, _profile())
    assert [(c["op"], c["word"], c["level"]) for c in out] == [
        ("row_level", "SQL", "must"),
        ("row_add", "Python", "must"),
    ]
    assert out[0]["before"] == "nice"


def test_caps_number_of_changes():
    raw = [{"op": "question_add", "question": f"Pytanie {i}?"} for i in range(40)]
    assert len(cc.clean_changes(raw, _profile())) == cc.CHANGES_MAX


def test_apply_builds_payload_only_for_touched_sections():
    profile = _profile()
    changes = cc.clean_changes(
        [
            {"op": "row_add", "word": "Python", "level": "must"},
            {"op": "row_remove", "word": "SAFe"},
            {"op": "question_add", "question": "Python?", "deal_breaker": "brak"},
            {"op": "question_edit", "id": "q1", "question": "Opisz COREP i Basel."},
            {"op": "question_remove", "id": "q2"},
            {"op": "text_edit", "field": "client.selling_points", "after": "Kanban"},
        ],
        profile,
    )
    payload = cc.apply_changes(profile, changes)
    assert set(payload) == {"stack", "screening_questions", "client"}
    words = [r["words"][0] for r in payload["stack"]["rows"]]
    assert words == ["Nasdaq AxiomSL ControllerView", "Snowflake", "SQL", "Python"]
    assert [q["id"] for q in payload["screening_questions"]] == ["q1", "q3"]
    assert payload["screening_questions"][0]["question"] == "Opisz COREP i Basel."
    assert payload["client"]["selling_points"] == "Kanban"
    # Zastosowanie nie zmienia profilu wejściowego.
    assert len(profile["stack"]["rows"]) == 4


def test_applied_payload_goes_through_the_save_pipeline_and_keeps_critical():
    profile = _profile()
    changes = cc.clean_changes(
        [{"op": "row_add", "word": "Python", "level": "must"}], profile
    )
    expanded = expand_patch(cc.apply_changes(profile, changes))
    assert expanded["stack"]["critical"] == ["Snowflake"]
    assert {"name": "Python"} in expanded["stack"]["must"]
    ChampionProfile.model_validate({**profile, **expanded})


def test_legacy_profile_without_rows_reads_must_and_nice():
    profile = {"stack": {"must": [{"name": "Java"}], "nice": [{"name": "Kafka"}]}}
    changes = cc.clean_changes([{"op": "row_remove", "word": "Kafka"}], profile)
    payload = cc.apply_changes(profile, changes)
    assert payload["stack"]["rows"] == [{"words": ["Java"], "level": "must"}]


def test_excerpt_marks_critical_and_hides_basics():
    excerpt = cc.profile_excerpt({**_profile(), "basics": {"rate_raw": "135"}})
    assert {"word": "Snowflake", "level": "critical"} in excerpt["requirements"]
    assert "basics" not in excerpt and "135" not in str(excerpt)


def test_gap_words_only_required_rows():
    changes = [
        {"op": "row_add", "word": "Python", "level": "must"},
        {"op": "row_add", "word": "Go", "level": "nice"},
        {"op": "row_level", "word": "SQL", "level": "must"},
        {"op": "row_remove", "word": "SAFe"},
    ]
    assert cc.gap_words(changes) == ["Python", "SQL"]


def test_stage_groups():
    assert cc._stage_group("identified") == "before_screening"
    assert cc._stage_group("screening_completed") == "after_screening"
    assert cc._stage_group("client_interview_scheduled") == "at_client"
    assert cc._stage_group("offer_sent") is None
    assert cc._stage_group(None) is None


def test_prompt_renders_with_fenced_text():
    from app.services.llm_prompts import CHAMPION_CLIENT_CHANGE

    rendered = CHAMPION_CLIENT_CHANGE.render(role="Analityk", profile="{}", text="<x>")
    assert "Analityk" in rendered and '"changes"' in rendered


# ── API (z bazą; dane fikcyjne) ────────────────────────────────────────────────

import uuid  # noqa: E402

import pytest  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models.client import Client  # noqa: E402
from app.models.job import Job, JobStatus  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services import champion_draft_service  # noqa: E402


def _headers(user_id: int, role: UserRole) -> dict[str, str]:
    token = create_access_token(subject=user_id, role=role.value)
    return {"Authorization": f"Bearer {token}"}


async def _seed() -> tuple[int, int]:
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"zmiana-klienta-{marker}@example.com",
            name=f"Rekruterka Przykładowa {marker}",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
            profile_completed=True,
        )
        client = Client(name=f"Bank Przykładowy {marker}")
        db.add_all([recruiter, client])
        await db.flush()
        job = Job(
            title="Analityk danych (przykład)",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter.id,
            champion_profile={
                "basics": {"role_name": "Analityk danych"},
                **expand_patch(
                    {
                        "stack": {
                            "rows": [
                                {"level": "must", "words": ["Snowflake"]},
                                {"level": "nice", "words": ["SAFe"]},
                            ]
                        }
                    }
                ),
                "screening_questions": [{"id": "q1", "question": "Snowflake?"}],
            },
        )
        db.add(job)
        await db.commit()
        return job.id, recruiter.id


@pytest.mark.asyncio
async def test_propose_then_apply_saves_once_with_note(
    app_client, app_auth_headers, monkeypatch
):
    job_id, recruiter_id = await _seed()
    route = f"/api/jobs/{job_id}/champion-profile/client-change"

    async def fake_call(**kwargs):
        assert "Python is now a must" in kwargs["prompt"]
        return {
            "changes": [
                {"op": "row_add", "word": "Python", "level": "must", "quote": "Python"},
                {"op": "row_remove", "word": "SAFe", "quote": "SAFe"},
                {"op": "question_add", "question": "Python?", "quote": "Python"},
                {"op": "row_remove", "word": "Kotlin"},
            ],
            "note": "Klient dokłada Pythona.",
        }

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", fake_call)
    proposed = await app_client.post(
        route,
        json={"text": "Python is now a must, SAFe out."},
        headers=app_auth_headers,
    )
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["status"] == "ready"
    assert [c["op"] for c in body["changes"]] == [
        "row_add",
        "row_remove",
        "question_add",
    ]
    assert body["gaps"] == [
        {
            "word": "Python",
            "open_total": 0,
            "missing": {"before_screening": 0, "after_screening": 0, "at_client": 0},
            "people": [],
        }
    ]

    applied = await app_client.post(
        f"{route}/apply",
        json={
            "changes": body["changes"][:2],
            "note": "Klient dokłada Pythona.",
            "expected_profile_hash": body["profile_hash"],
        },
        headers=app_auth_headers,
    )
    assert applied.status_code == 200, applied.text
    saved = applied.json()
    assert saved["applied"] == 2
    labels = [r["words"][0] for r in saved["champion_profile"]["stack"]["rows"]]
    assert labels == ["Snowflake", "Python"]
    changes = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile/changes", headers=app_auth_headers
    )
    assert changes.json()["revisions"][0]["note"] == "Klient dokłada Pythona."
    assert len(changes.json()["revisions"]) == 1

    # Ta sama zmiana drugi raz już nie pasuje do profilu.
    again = await app_client.post(
        f"{route}/apply",
        json={"changes": body["changes"][:2]},
        headers=app_auth_headers,
    )
    assert again.status_code == 422


@pytest.mark.asyncio
async def test_model_failure_is_200_with_message(
    app_client, app_auth_headers, monkeypatch
):
    job_id, _ = await _seed()

    async def boom(**kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", boom)
    res = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/client-change",
        json={"text": "Python is now a must."},
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "failed"
    assert res.json()["changes"] == []


@pytest.mark.asyncio
async def test_role_without_job_edit_is_refused(app_client):
    """Bramka jak `PUT …/champion-profile`: role spoza operacyjnych (np. pracownik).

    Rekruter i finanse mogą zapisać Profil każdej rekrutacji (staging 23.11) —
    nowa trasa tego nie zmienia.
    """
    job_id, _ = await _seed()
    async with AsyncSessionLocal() as db:
        outsider = User(
            email=f"spoza-{uuid.uuid4().hex[:8]}@example.com",
            name="Pracownik Przykładowy",
            role=UserRole.employee,
            roles=[UserRole.employee.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(outsider)
        await db.commit()
        outsider_id = outsider.id
    headers = _headers(outsider_id, UserRole.employee)
    route = f"/api/jobs/{job_id}/champion-profile/client-change"
    res = await app_client.post(
        route, json={"text": "Python is now a must."}, headers=headers
    )
    assert res.status_code == 403, res.text
    res = await app_client.post(
        f"{route}/apply",
        json={"changes": [{"op": "row_add", "word": "Python", "level": "must"}]},
        headers=headers,
    )
    assert res.status_code == 403, res.text


def test_gap_lead_falls_back_to_who_claimed_or_added_the_candidate():
    """Staging 23.11: owner_user_id puste w 85% otwartych procesów, dodał je rekruter."""
    assert cc.process_lead(owner=None, claimed=None, opened=155) == 155
    assert cc.process_lead(owner=None, claimed=7, opened=155) == 7
    assert cc.process_lead(owner=3, claimed=7, opened=155) == 3
    assert cc.process_lead(owner=None, claimed=None, opened=None) is None
