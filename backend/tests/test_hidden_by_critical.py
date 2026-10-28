"""Ukryci przez „musi mieć”, choć w CV jest coś bliskiego (28.10.2026).

Kontrakty (``services/hidden_by_critical.py``):

- bliskie słowo = człon nazwy krytycznej, który sam nie jest pełną nazwą
  (≥ 4 znaki, bez ogólnych słów i parasoli producentów);
- sekcja bierze tylko osoby ukryte przez ``missing_must`` w najnowszym
  przeglądzie automatycznym, które mają bliskie słowo w profilu, CV albo
  notatce — osoba bez śladu, ukryta innym powodem, pominięta albo już
  w rekrutacji nie wchodzi;
- cytat liczy się przy odczycie i ma najwyżej ``SNIPPET_CHARS`` znaków;
- „wariant = krytyczna” to zwykły zapis Championa: wolno go temu, komu wolno
  ``PUT …/champion-profile`` (``can_add_variant``), a po zapisie osoba
  przechodzi bramkę i wypada z sekcji.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun
from app.models.note import Note, NoteType
from app.models.user import UserRole
from app.services import job_proposals as proposals
from app.services.hidden_by_critical import SNIPPET_CHARS, close_words
from app.services.must_text_evidence import word_snippet
from tests.test_job_proposals import _user


# ── Reguła bliskiego słowa i cytat (bez bazy) ───────────────────────────────


@pytest.mark.parametrize(
    ("label", "words"),
    [
        ("SailPoint IIQ", ("SailPoint",)),
        ("Spring Boot", ("Spring",)),
        # Jedno słowo nie ma członów — wariant pisowni to sprawa słownika.
        ("Kafka", ()),
        # Ogólne człony i parasole producentów nic nie mówią.
        ("SQL Server", ()),
        ("Microsoft Dynamics 365", ("Dynamics",)),
    ],
)
def test_close_words_are_label_parts_that_are_not_a_full_name(label, words):
    assert close_words(label) == words


def test_row_words_add_their_parts_but_not_themselves():
    assert close_words("SailPoint IIQ", {"SailPoint IIQ": ("IIQ",)}) == ("SailPoint",)
    # Wariant z wiersza, który jest całą nazwą, nie jest „bliski”.
    assert close_words("SailPoint IIQ", {"SailPoint IIQ": ("SailPoint",)}) == ()


def test_snippet_is_short_and_needs_a_whole_word():
    text = (
        "Od 2019 roku w banku: Maintenance of Sailpoint IAM application "
        "IdentityIQ, onboarding aplikacji i przeglądy uprawnień."
    )
    snippet = word_snippet("SailPoint", text, chars=SNIPPET_CHARS)
    assert snippet is not None and "Sailpoint" in snippet
    assert len(snippet.strip("…")) <= SNIPPET_CHARS
    assert snippet.startswith("…") and snippet.endswith("…")
    assert word_snippet("SailPoint", "SailPointer to nie to samo") is None


# ── Sekcja na bazie ─────────────────────────────────────────────────────────


@pytest.fixture
def offline_matching(monkeypatch):
    from app.services import canonical_fit, embedding_service

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)


_CRITICAL = "SailPoint IIQ"
# Bramka czyta etykiety kanoniczne (`job_explicit_must_skills`).
_GATE_LABEL = "sailpoint iiq"


async def _job_with_critical(app_client, headers) -> dict:
    from app.models.client import Client
    from tests._job_factory import complete_job_payload

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Ukryci-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        client_id = client.id
    created = await app_client.post(
        "/api/jobs",
        json=await complete_job_payload(client_id),
        headers=headers,
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    read = await app_client.get(f"/api/jobs/{job_id}/champion-profile", headers=headers)
    saved = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        json={
            "stack": {
                "rows": [
                    {"level": "must", "words": [_CRITICAL]},
                    {"level": "must", "words": ["Python"]},
                ],
                "critical": [_CRITICAL],
            },
            "expected_profile_hash": read.json()["profile_hash"],
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    return {"job_id": job_id, "client_id": client_id}


async def _people(cvs: list[str]) -> list[int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        people = [
            Candidate(
                name="Ukryty",
                lastname=f"{index}-{tag}",
                email=f"hidden-{index}-{tag}@example.com",
                raw_cv_text=cv,
            )
            for index, cv in enumerate(cvs)
        ]
        db.add_all(people)
        await db.commit()
        return [p.id for p in people]


async def _auto_run(world: dict, owner_id: int, excluded: dict[int, str]) -> str:
    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSearchRun(
                id=run_id,
                created_by=owner_id,
                client_id=world["client_id"],
                job_id=world["job_id"],
                state="complete",
                request_fingerprint="h" * 64,
                request_context={},
                version_trace={"origin": "auto"},
                population_size=len(excluded),
                metrics={},
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.flush()
        db.add_all(
            [
                CandidateSearchResult(
                    run_id=run_id,
                    candidate_id=cid,
                    candidate_version="v",
                    state="evaluated",
                    eligible=False,
                    fit_score=None,
                    measurement="unavailable",
                    exclusion_reasons=[reason],
                )
                for cid, reason in excluded.items()
            ]
        )
        await db.commit()
    return run_id


async def test_section_lists_only_people_hidden_by_must_with_a_trace(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    world = await _job_with_critical(app_client, app_auth_headers)
    owner_id, recruiter_headers = await _user(UserRole.recruiter)
    in_cv, in_note, no_trace, over_budget, dismissed = await _people(
        [
            "Python developer. Onboarding applications to Sailpoint IdentityIQ.",
            "Python, Django, Okta.",
            "Python developer, Okta and Azure AD only.",
            "Python, SailPoint IdentityIQ administration.",
            "Python, SailPoint Identity Security Cloud.",
        ]
    )
    async with AsyncSessionLocal() as db:
        db.add(
            Note(
                candidate_id=in_note,
                note_type=NoteType.call,
                content="Rozmowa: 3 lata z SailPoint w banku, wdrożenia ról.",
            )
        )
        # Pominięta wcześniej z innego źródła — „Pomiń” obowiązuje wszędzie.
        await proposals.upsert_proposals(
            db, world["job_id"], [{"candidate_id": dismissed}], "recommendation"
        )
        await proposals.dismiss(
            db, job_id=world["job_id"], candidate_id=dismissed, user_id=owner_id
        )
        await db.commit()
    await _auto_run(
        world,
        owner_id,
        {
            in_cv: "missing_must",
            in_note: "missing_must",
            no_trace: "missing_must",
            over_budget: "over_budget",
            dismissed: "missing_must",
        },
    )

    resp = await app_client.get(
        f"/api/jobs/{world['job_id']}/proposal-inbox/hidden-by-critical",
        headers=recruiter_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_id = {item["candidate"]["id"]: item for item in body["items"]}
    # Bez śladu, ukryty budżetem i pominięty — nie wchodzą.
    assert set(by_id) == {in_cv, in_note}
    assert body["total"] == 2 and body["truncated"] is False
    assert by_id[in_cv]["critical"] == _GATE_LABEL
    # Pisownia z CV, nie z bramki.
    assert by_id[in_cv]["word"] == "Sailpoint"
    assert by_id[in_cv]["source"] == "cv"
    assert "Sailpoint IdentityIQ" in by_id[in_cv]["snippet"]
    assert len(by_id[in_cv]["snippet"].strip("…")) <= SNIPPET_CHARS
    assert by_id[in_note]["source"] == "note"
    assert body["searched"] == [{"critical": _GATE_LABEL, "words": ["sailpoint"]}]
    # Dwie pisownie po jednej osobie: remis wygrywa pisownia producenta.
    assert body["variants"] == [
        {"critical": _GATE_LABEL, "word": "SailPoint", "people": 2}
    ]
    assert body["can_add_variant"] is True


async def test_variant_goes_through_the_champion_save_and_clears_the_section(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    world = await _job_with_critical(app_client, app_auth_headers)
    owner_id, recruiter_headers = await _user(UserRole.recruiter)
    [person] = await _people(["Python, SailPoint Identity Security Cloud."])
    await _auto_run(world, owner_id, {person: "missing_must"})
    url = f"/api/jobs/{world['job_id']}/proposal-inbox/hidden-by-critical"
    assert [
        i["candidate"]["id"]
        for i in (await app_client.get(url, headers=recruiter_headers)).json()["items"]
    ] == [person]

    # Ten sam zapis co „+ lub” w wierszu: cały `stack`, wiersz z wariantem.
    read = await app_client.get(
        f"/api/jobs/{world['job_id']}/champion-profile", headers=recruiter_headers
    )
    stack = read.json()["champion_profile"]["stack"]
    rows = [
        {**row, "words": [*row["words"], "SailPoint"]}
        if row["words"][0] == _CRITICAL
        else row
        for row in stack["rows"]
    ]
    saved = await app_client.put(
        f"/api/jobs/{world['job_id']}/champion-profile",
        json={
            "stack": {**stack, "rows": rows},
            "expected_profile_hash": read.json()["profile_hash"],
        },
        headers=recruiter_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["champion_profile"]["stack"]["critical"] == [_CRITICAL]

    # Bramka liczy wariant od razu — osoba przechodzi i znika z sekcji.
    after = (await app_client.get(url, headers=recruiter_headers)).json()
    assert after["items"] == []
    # „SailPoint” jest już słowem wiersza, więc nie jest „bliski”.
    assert after["searched"] == []


async def test_read_only_role_sees_the_section_without_the_variant_button(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    world = await _job_with_critical(app_client, app_auth_headers)
    _automation_id, automation_headers = await _user(UserRole.automation)
    resp = await app_client.get(
        f"/api/jobs/{world['job_id']}/proposal-inbox/hidden-by-critical",
        headers=automation_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["can_add_variant"] is False
    # …i zapis Championa, którym idzie przycisk, też odmawia.
    denied = await app_client.put(
        f"/api/jobs/{world['job_id']}/champion-profile",
        json={"project": {"about": "x"}},
        headers=automation_headers,
    )
    assert denied.status_code == 403, denied.text


async def test_job_without_an_auto_review_has_an_empty_section(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    world = await _job_with_critical(app_client, app_auth_headers)
    resp = await app_client.get(
        f"/api/jobs/{world['job_id']}/proposal-inbox/hidden-by-critical",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] is None and body["items"] == [] and body["variants"] == []
