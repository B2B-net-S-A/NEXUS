"""Trasy ``/api/legal``: bramka Generatora umów B2B, odmowy i kształt odpowiedzi.

Bez bazy: konto z polityką jak na produkcji (``tests/_authz_matrix.build_user``),
a korpus i asystent podstawione. Pełny werdykt bramek dla 29 person leży we
wzorcu ``tests/data/authz_golden/legal.json``.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.api import deps
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.services.legal import assistant, citations, corpus, sources, template_review
from tests._authz_matrix import PERSONAS, build_user, routes_only

_PERSONA = {persona.key: persona for persona in PERSONAS}


class _NoDb:
    async def commit(self) -> None:  # pragma: no cover - nieużywane
        return None


def _hit() -> corpus.ProvisionHit:
    return corpus.ProvisionHit(
        id=1,
        act_key="kc",
        act_short_name="KC",
        ref="art. 61 § 1",
        ref_key="61 §1",
        kind="par",
        heading="TYTUŁ IV — Czynności prawne",
        text="§ 1. Oświadczenie woli … " + "x" * 3000,
        repealed=False,
        version_id=1,
        version_ident="DU/2026/795",
        valid_from=date(2026, 5, 19),
        valid_to=None,
        url="https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20260000795",
    )


@pytest.fixture
def stubbed(monkeypatch):
    calls: dict[str, object] = {}

    async def _sources(_db):
        return {"acts": [], "acts_total": 0, "acts_ready": 0, "provisions_total": 0}

    async def _search(_db, q, *, acts=None, on_date=None, limit=8):
        calls["search"] = (q, acts, on_date, limit)
        return corpus.SearchResult([_hit()], corpus.RETRIEVAL_KEYWORDS)

    async def _verify(_db, text, passages=(), *, on_date=None):
        calls["verify"] = (text, list(passages), on_date)
        return citations.verify(text, [*passages, corpus.as_passage(_hit())])

    async def _draft(_db, **kwargs):
        calls["draft"] = kwargs
        return assistant.Draft(
            text="", citations=[], checks=[], blocked=True, error="bez modelu"
        )

    async def _db_counts(_db):
        return {
            "case_law": 12,
            "case_law_latest": "2026-11-20T03:00:00+00:00",
            "custom_templates": 2,
            "framework_contracts": 5,
            "framework_amendments": 7,
        }

    async def _review_status(_db):
        return {"open": 1, "last_created_at": "2026-11-24T06:00:00+00:00"}

    monkeypatch.setattr(corpus, "sources_status", _sources)
    monkeypatch.setattr(sources, "db_counts", _db_counts)
    monkeypatch.setattr(template_review, "review_status", _review_status)
    monkeypatch.setattr(corpus, "search", _search)
    monkeypatch.setattr(corpus, "verify_text", _verify)
    monkeypatch.setattr(assistant, "draft", _draft)
    monkeypatch.setattr(limiter, "enabled", False)
    return calls


@pytest.fixture
async def client_as(stubbed):
    from app.main import app

    holder: dict[str, object] = {}

    async def _current_user():
        return holder["user"]

    async def _db():
        return _NoDb()

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[deps.get_current_user] = _current_user
    app.dependency_overrides[deps.get_authenticated_user] = _current_user
    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=routes_only(app), raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://legal"
    ) as client:

        def _as(key: str, *, generator: str | None = None):
            user = build_user(_PERSONA[key], user_id=910_000)
            if generator is not None:
                user.effective_action_access = {
                    **(user.effective_action_access or {}),
                    "b2b_contract_generator": generator,
                }
            holder["user"] = user
            return client

        yield _as
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


@pytest.mark.asyncio
async def test_generator_user_reads_sources_and_searches(client_as, stubbed) -> None:
    client = client_as("recruiter")
    assert (await client.get("/api/legal/sources")).status_code == 200
    resp = await client.get(
        "/api/legal/provisions/search",
        params={"q": "wypowiedzenie umowy forma", "acts": "kc,kp", "limit": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["retrieval"] == "keywords"
    hit = body["hits"][0]
    assert hit["ref"] == "art. 61 § 1" and hit["act"] == "KC"
    assert hit["truncated"] is True and len(hit["text"]) == 2000
    assert stubbed["search"] == ("wypowiedzenie umowy forma", ["kc", "kp"], None, 5)


@pytest.mark.asyncio
async def test_sources_carry_document_counters_and_template_review(client_as) -> None:
    resp = await client_as("recruiter").get("/api/legal/sources")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["acts_total"] == 0
    assert body["documents"] == {
        "case_law": {"count": 12, "latest_fetched_at": "2026-11-20T03:00:00+00:00"},
        "templates": {
            "repo": len(template_review.repo_templates()),
            "client_clauses": len(template_review.clause_sources()),
            "custom_approved": 2,
        },
        "framework_contracts": {"contracts": 5, "amendments": 7},
    }
    assert body["documents"]["templates"]["repo"] > 10
    assert body["template_review"] == {
        "open": 1,
        "last_created_at": "2026-11-24T06:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_unknown_act_in_search_is_422(client_as) -> None:
    resp = await client_as("admin").get(
        "/api/legal/provisions/search", params={"q": "forma", "acts": "kc,lex"}
    )
    assert resp.status_code == 422
    assert "lex" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_verify_returns_checks_and_blocks_on_missing(client_as) -> None:
    resp = await client_as("back_office").post(
        "/api/legal/verify",
        json={
            "text": "Zgodnie z art. 61 § 1 KC oraz § 9 Umowy i art. 999 KC.",
            "passages": [
                {"kind": "contract", "ref": "§ 9", "text": "§ 9. Forma pisemna."}
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [c["status"] for c in body["checks"]] == ["ok", "ok", "missing"]
    assert body["blocked"] is True
    assert body["counts"] == {"ok": 2, "missing": 1, "mismatch": 0}
    assert body["checks"][0]["source"]["act_key"] == "kc"


@pytest.mark.asyncio
async def test_verify_refuses_unknown_passage_kind(client_as) -> None:
    resp = await client_as("admin").post(
        "/api/legal/verify",
        json={
            "text": "art. 1 KC",
            "passages": [{"kind": "lex", "ref": "x", "text": "y"}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("persona", ["employee", "board", "automation", "user"])
async def test_roles_without_generator_are_refused(client_as, persona) -> None:
    client = client_as(persona)
    assert (await client.get("/api/legal/sources")).status_code == 403
    resp = await client.post("/api/legal/verify", json={"text": "art. 61 § 1 KC"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_draft_needs_generation_level_of_the_generator(
    client_as, stubbed
) -> None:
    payload = {
        "kind": "termination",
        "instruction": "Wypowiedzenie umowy z zachowaniem okresu",
        "entities": [{"label": "PARTNER", "value": "Jan Testowy", "inflect": True}],
    }
    viewer = client_as("recruiter", generator="view")
    assert (
        await viewer.post("/api/legal/verify", json={"text": "art. 61 § 1 KC"})
    ).status_code == 200
    denied = await viewer.post("/api/legal/draft", json=payload)
    assert denied.status_code == 403
    assert denied.json()["detail"]["required"] == "generate"
    assert "draft" not in stubbed

    allowed = await client_as("recruiter", generator="generate").post(
        "/api/legal/draft", json=payload
    )
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["blocked"] is True and body["error"] == "bez modelu"
    assert "nie jest poradą prawną" in body["disclaimer"]
    entity = stubbed["draft"]["entities"][0]
    assert (entity.label, entity.value, entity.inflect) == (
        "PARTNER",
        "Jan Testowy",
        True,
    )


@pytest.mark.asyncio
async def test_draft_refuses_bad_kind_and_label(client_as) -> None:
    client = client_as("admin")
    bad_kind = await client.post(
        "/api/legal/draft", json={"kind": "pozew", "instruction": "abc"}
    )
    assert bad_kind.status_code == 422
    bad_label = await client.post(
        "/api/legal/draft",
        json={
            "kind": "letter",
            "instruction": "abc",
            "entities": [{"label": "imię i nazwisko", "value": "Jan"}],
        },
    )
    assert bad_label.status_code == 422
