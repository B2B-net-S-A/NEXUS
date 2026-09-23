"""Plakietki sekcji 4 Championa — ślad dziedziny/certyfikatu w CV (09.2026).

`met` tylko z konkretnym źródłem, a brak śladu to `unknown`, NIGDY „brak” —
branża w CV bywa pusta, więc plakietka nie może udawać dowodu braku.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.experience_evidence import domain_forms, evaluate

PROFILE = {
    "experience": {
        "domains": [
            {"name": "płatności kartowe", "level": "must", "min_years": 2},
            {"name": "ubezpieczenia", "level": "nice"},
        ],
        "certifications": [{"name": "ISTQB Foundation", "level": "must"}],
        "regulations": [{"name": "PSD2", "level": "nice"}],
    }
}


def _candidate(**kw) -> SimpleNamespace:
    return SimpleNamespace(
        cv_extracted_data=kw.get("data") or {}, raw_cv_text=kw.get("raw")
    )


def _by_name(results: list[dict]) -> dict[str, dict]:
    return {r["name"]: r for r in results}


def test_structured_sector_beats_raw_text_and_synonyms_match() -> None:
    cand = _candidate(
        data={
            "sectors": ["Payments"],
            "certifications": [{"name": "ISTQB CTFL Foundation Level"}],
        },
        raw="Testowałem przelewy SEPA i PSD2 w banku.",
    )
    out = _by_name(evaluate(PROFILE, cand))
    assert out["płatności kartowe"]["status"] == "met"
    assert out["płatności kartowe"]["source"] == "sektor w CV"
    assert out["płatności kartowe"]["min_years"] == 2
    assert out["ISTQB Foundation"]["source"] == "certyfikat w CV"
    assert out["PSD2"]["source"] == "tekst CV"


def test_no_trace_is_unknown_never_missing() -> None:
    out = _by_name(evaluate(PROFILE, _candidate(raw="Java developer, Spring, Kafka")))
    assert {r["status"] for r in out.values()} == {"unknown"}
    assert all(r["source"] is None for r in out.values())


def test_certificate_needs_every_distinctive_token() -> None:
    out = _by_name(evaluate(PROFILE, _candidate(raw="Certyfikat ISTQB Advanced")))
    assert out["ISTQB Foundation"]["status"] == "unknown"


def test_polish_inflection_is_matched_as_word_prefix() -> None:
    out = _by_name(
        evaluate(
            PROFILE,
            _candidate(
                data={
                    "projects": [
                        {
                            "name": "Portal",
                            "description": "Likwidacja szkód w ubezpieczeniach komunikacyjnych",
                        }
                    ]
                }
            ),
        )
    )
    assert out["ubezpieczenia"]["status"] == "met"
    assert out["ubezpieczenia"]["source"] == "projekt: Portal"


def test_profile_without_experience_gives_nothing() -> None:
    assert evaluate({}, _candidate(raw="payments")) == []


def test_unknown_domain_still_matches_its_own_name() -> None:
    assert "kolejnictwo" in domain_forms("Kolejnictwo")


@pytest.mark.asyncio
async def test_scores_column_carries_the_badges_even_without_a_measurement(
    app_client, app_auth_headers, monkeypatch
) -> None:
    import uuid
    from unittest.mock import AsyncMock

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job
    from app.services import canonical_fit

    monkeypatch.setattr(canonical_fit, "request_vector", AsyncMock(return_value=None))
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Badges {tag}")
        db.add(client)
        await db.flush()
        job = Job(title=f"Tester {tag}", client_id=client.id, champion_profile=PROFILE)
        candidate = Candidate(
            name="Plakietka",
            lastname=f"Dowód {tag}",
            raw_cv_text="Tester w projekcie acquiringu kartowego, ISTQB Foundation.",
        )
        db.add_all([job, candidate])
        await db.commit()
        job_id, cand_id = job.id, candidate.id

    resp = await app_client.post(
        "/api/search/candidates/scores",
        json={"job_id": job_id, "candidate_ids": [cand_id]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    badges = _by_name(resp.json()["breakdowns"][str(cand_id)]["experience"])
    assert badges["płatności kartowe"]["status"] == "met"
    assert badges["ISTQB Foundation"]["source"] == "tekst CV"
    assert badges["ubezpieczenia"]["status"] == "unknown"
