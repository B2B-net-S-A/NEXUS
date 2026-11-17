"""„Co się zmieniło w Profilu Championa” (17.11.2026).

Różnica po ludzku (bez bazy) i ścieżka API: zapis rekrutacji w pracy zostawia
wersję, rekruter widzi ją i klika „Przeczytane”, autor dopisuje zdanie dla
rekruterów. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.schemas.champion import ChampionProfile
from app.services.champion_profile_changes import describe_changes
from app.services.champion_requirement_rows import expand_patch


def _norm(profile: dict) -> dict:
    return ChampionProfile.model_validate(profile).model_dump(mode="json")


def _rows(*rows: tuple[str, list[str]]) -> dict:
    """Profil z wierszami tak, jak zapisuje go edytor (listy wyprowadzone z wierszy)."""
    return expand_patch(
        {"stack": {"rows": [{"level": level, "words": words} for level, words in rows]}}
    )


def _kinds(items: list[dict]) -> list[tuple[str, str, str]]:
    return [(i["kind"], i["text"], i["detail"]) for i in items]


# ── Różnica (bez bazy) ─────────────────────────────────────────────────────────


def test_removed_rows_are_reported_by_label_not_by_shifted_index():
    """Przypadek 789123: jedno usunięcie w „Musi mieć” przesuwa indeksy reszty."""
    old = _norm(
        _rows(
            ("must", ["UML"]),
            ("must", ["wzorce projektowe"]),
            ("must", ["SQL"]),
            ("must", ["Elasticsearch"]),
            ("nice", ["testowania", "testing"]),
            ("nice", ["scrum"]),
        )
    )
    new = _norm(
        _rows(
            ("must", ["UML"]),
            ("must", ["SQL"]),
            ("must", ["Elasticsearch"]),
            ("nice", ["testowania", "testing"]),
        )
    )
    assert _kinds(describe_changes(old, new)) == [
        ("removed", "wzorce projektowe", "usunięte z „Musi mieć”"),
        ("removed", "scrum", "usunięte z „Mile widziane”"),
    ]


def test_level_change_added_row_and_new_variant():
    old = _norm(_rows(("must", ["Elasticsearch"]), ("must", ["Kafka"])))
    new = _norm(
        _rows(
            ("nice", ["Elasticsearch"]),
            ("must", ["Kafka", "RabbitMQ"]),
            ("critical", ["Java"]),
        )
    )
    assert _kinds(describe_changes(old, new)) == [
        ("moved", "Elasticsearch", "„Musi mieć” → „Mile widziane”"),
        ("set", "Kafka", "teraz: kafka lub rabbitmq"),
        ("added", "Java", "nowe w „Krytyczne”"),
    ]


def test_row_order_and_letter_case_alone_are_not_a_change():
    old = _norm(_rows(("must", ["Java"]), ("must", ["SQL"])))
    new = _norm(_rows(("must", ["sql"]), ("must", ["Java"])))
    assert describe_changes(old, new) == []


def test_legacy_lists_compare_with_rows_without_false_churn():
    """Profil sprzed wierszy (same listy) a ten sam profil zapisany w wierszach."""
    old = {
        "stack": {
            "must": [{"name": "Java"}, {"name": "SQL"}],
            "nice": [{"name": "Docker"}],
            "critical": ["Java"],
            "rows": None,
        }
    }
    new = {
        "stack": {
            "rows": [
                {"level": "critical", "words": ["Java"]},
                {"level": "must", "words": ["SQL"]},
            ]
        }
    }
    assert _kinds(describe_changes(old, new)) == [
        ("removed", "Docker", "usunięte z „Mile widziane”"),
    ]


def test_conditions_deadline_and_questions():
    old = _norm(
        {
            "basics": {"rate_value": 110, "work_mode": "hybrid"},
            "screening_questions": [{"id": "q1", "question": "Ile lat z BPMN?"}],
        }
    )
    new = _norm(
        {
            "basics": {
                "rate_value": 105,
                "work_mode": "remote",
                "deadline": "2026-11-13",
                "deadline_time": "10:00",
            },
            "screening_questions": [
                {"id": "q2", "question": "Jak modelujesz integracje?"}
            ],
        }
    )
    assert _kinds(describe_changes(old, new)) == [
        ("set", "Budżet (PLN/h)", "110 → 105"),
        ("set", "Tryb pracy", "hybrydowo → zdalnie"),
        ("set", "Deadline na kandydatów", "13.11, 10:00 (wcześniej brak)"),
        ("added", "Pytanie na rozmowę", "Jak modelujesz integracje?"),
        ("removed", "Pytanie na rozmowę", "Ile lat z BPMN?"),
    ]


def test_closed_client_questions_are_counted_once():
    def ask(note_id: str, text: str, done: bool = False) -> dict:
        return {"id": note_id, "topic": "ask_client", "text": text, "done": done}

    old = _norm({"insights": [ask("a", "Jaki budżet?"), ask("b", "Ile dni w biurze?")]})
    new = _norm({"insights": [ask("a", "Jaki budżet?", done=True)]})
    assert _kinds(describe_changes(old, new)) == [
        (
            "set",
            "Do dopytania u klienta",
            "2 pytania zamknięte: Jaki budżet?; Ile dni w biurze?",
        )
    ]


def test_long_text_is_shortened_and_nothing_to_show_gives_empty_list():
    old = _norm({"project": {"about": "A"}})
    new = _norm({"project": {"about": "B"}, "search": {"requirements": [["Java"]]}})
    assert _kinds(describe_changes(old, new)) == [
        ("set", "O projekcie", "opis zmieniony")
    ]
    long_question = "Pytanie " * 40
    items = describe_changes(
        _norm({}),
        _norm({"screening_questions": [{"id": "q", "question": long_question}]}),
    )
    assert len(items[0]["detail"]) <= 140
    assert items[0]["detail"].endswith("…")
    assert describe_changes(_norm({}), _norm({})) == []


# ── API ────────────────────────────────────────────────────────────────────────


def _headers(user_id: int, role: UserRole) -> dict[str, str]:
    token = create_access_token(subject=user_id, role=role.value)
    return {"Authorization": f"Bearer {token}"}


async def _seed(status: JobStatus = JobStatus.published) -> tuple[int, int]:
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"zmiany-{marker}@example.com",
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
            title="Analityk systemowy (przykład)",
            status=status,
            client_id=client.id,
            recruiter_id=recruiter.id,
            champion_profile={
                "basics": {"role_name": "Analityk systemowy"},
                "stack": {
                    "rows": [
                        {"level": "must", "words": ["UML"]},
                        {"level": "must", "words": ["wzorce projektowe"]},
                        {"level": "nice", "words": ["scrum"]},
                    ]
                },
                "project": {"about": "Integracje systemów maklerskich."},
            },
        )
        db.add(job)
        await db.commit()
        return job.id, recruiter.id


@pytest.mark.asyncio
async def test_published_job_save_records_revision_and_recruiter_marks_it_seen(
    app_client, app_auth_headers
):
    job_id, recruiter_id = await _seed()
    route = f"/api/jobs/{job_id}/champion-profile"
    saved = await app_client.put(
        route,
        json={"stack": {"rows": [{"level": "must", "words": ["UML"]}]}},
        headers=app_auth_headers,
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["change_revision"]
    assert [(c["kind"], c["text"]) for c in revision["changes"]] == [
        ("removed", "wzorce projektowe"),
        ("removed", "scrum"),
    ]

    recruiter = _headers(recruiter_id, UserRole.recruiter)
    listed = await app_client.get(f"{route}/changes", headers=recruiter)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["last_seen_revision_id"] is None
    assert [r["id"] for r in body["revisions"]] == [revision["id"]]
    assert body["revisions"][0]["mine"] is False

    seen = await app_client.post(
        f"{route}/changes/seen", json={"revision_id": revision["id"]}, headers=recruiter
    )
    assert seen.status_code == 200, seen.text
    assert seen.json()["last_seen_revision_id"] == revision["id"]
    # „Przeczytane” jest per osoba: admin nadal ma zmianę jako nieprzeczytaną.
    admin_view = await app_client.get(f"{route}/changes", headers=app_auth_headers)
    assert admin_view.json()["last_seen_revision_id"] is None


@pytest.mark.asyncio
async def test_note_is_written_by_author_only(app_client, app_auth_headers):
    job_id, recruiter_id = await _seed()
    route = f"/api/jobs/{job_id}/champion-profile"
    saved = await app_client.put(
        route,
        json={"project": {"about": "Nowy zakres integracji."}},
        headers=app_auth_headers,
    )
    revision_id = saved.json()["change_revision"]["id"]

    noted = await app_client.patch(
        f"{route}/changes/{revision_id}",
        json={"note": "  Klient   najbardziej pyta o SQL.  "},
        headers=app_auth_headers,
    )
    assert noted.status_code == 200, noted.text
    assert noted.json()["note"] == "Klient najbardziej pyta o SQL."

    foreign = await app_client.patch(
        f"{route}/changes/{revision_id}",
        json={"note": "Nie moja zmiana."},
        headers=_headers(recruiter_id, UserRole.recruiter),
    )
    assert foreign.status_code == 403, foreign.text

    too_long = await app_client.patch(
        f"{route}/changes/{revision_id}",
        json={"note": "x" * 601},
        headers=app_auth_headers,
    )
    assert too_long.status_code == 422


@pytest.mark.asyncio
async def test_no_revision_before_handoff_or_without_visible_change(
    app_client, app_auth_headers
):
    draft_id, _ = await _seed(status=JobStatus.draft)
    draft = await app_client.put(
        f"/api/jobs/{draft_id}/champion-profile",
        json={"project": {"about": "Zmiana szkicu."}},
        headers=app_auth_headers,
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["change_revision"] is None

    job_id, _ = await _seed()
    rows_only = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        json={"search": {"requirements": [["UML"]]}},
        headers=app_auth_headers,
    )
    assert rows_only.status_code == 200, rows_only.text
    assert rows_only.json()["change_revision"] is None
    listed = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile/changes", headers=app_auth_headers
    )
    assert listed.json()["revisions"] == []


@pytest.mark.asyncio
async def test_seen_rejects_revision_from_another_job(app_client, app_auth_headers):
    job_a, _ = await _seed()
    job_b, _ = await _seed()
    saved = await app_client.put(
        f"/api/jobs/{job_a}/champion-profile",
        json={"project": {"about": "Inny opis."}},
        headers=app_auth_headers,
    )
    revision_id = saved.json()["change_revision"]["id"]
    wrong = await app_client.post(
        f"/api/jobs/{job_b}/champion-profile/changes/seen",
        json={"revision_id": revision_id},
        headers=app_auth_headers,
    )
    assert wrong.status_code == 404


def test_critical_row_with_alternatives_is_reported():
    """`stack.critical` trzyma etykietę wiersza („Kafka lub RabbitMQ”), nie pierwsze słowo."""
    old = {
        "stack": {
            "rows": [{"words": ["Kafka", "RabbitMQ"], "level": "must"}],
            "critical": [],
        }
    }
    new = {
        "stack": {
            "rows": [{"words": ["Kafka", "RabbitMQ"], "level": "must"}],
            "critical": ["Kafka lub RabbitMQ"],
        }
    }
    assert _kinds(describe_changes(old, new)) == [
        ("moved", "Kafka", "„Musi mieć” → „Krytyczne”"),
    ]


def test_legacy_alternative_label_matches_row_head():
    """Profil sprzed wierszy z etykietą „Kafka lub Docker” a ten sam wiersz po przejściu."""
    old = {
        "stack": {
            "must": [{"name": "Kafka lub Docker"}],
            "critical": ["Kafka lub Docker"],
            "rows": None,
        }
    }
    new = {
        "stack": {
            "rows": [{"words": ["Kafka", "Docker"], "level": "must"}],
            "critical": ["Kafka lub Docker"],
        }
    }
    assert describe_changes(old, new) == []
