"""Import JJIT w NEXUS (etap 2): kontrakty, których złamanie jest defektem.

1. **Kształt panelu** — kanban `columns[].applications[]` spłaszcza się z
   `statusKey`; `appliedFrom` zawsze pełne ISO (sama data = HTTP 500 w panelu);
   aplikacje usunięte / zanonimizowane / bez CV są pomijane.
2. **Payload Traffit** — e-mail z CV ma pierwszeństwo, ale niepoprawny wraca
   do e-maila z panelu; lata doświadczenia trafiają w kubełki Traffita;
   nieznane języki nie psują listy ID.
3. **Reguła dopasowania jest ta sama, co w scraperze** — próg + published +
   co najmniej jedno trafione must-have.
4. **dry_run nic nie zapisuje** poza raportem runu: run w bazie ma liczniki,
   Traffit i NEXUS nie dostają żadnego zapisu, stan aplikacji nie jest
   zapamiętywany (ten sam kandydat policzy się ponownie w prawdziwym runie).
5. **Drugi run w trakcie pierwszego jest odrzucany** (`RunInProgress`).
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.integration_external_item import IntegrationExternalItem
from app.models.integration_run import IntegrationRun
from app.services.integrations.jjit import runner
from app.services.integrations.jjit.cv_payload import (
    build_traffit_payload,
    language_ids,
)
from app.services.integrations.jjit.nexus_client import is_good_match
from app.services.integrations.jjit.panel_client import (
    CvFile,
    application_skip_reason,
    flatten_kanban,
    to_iso_timestamp,
)

# ── 1. kształt panelu ───────────────────────────────────────────────────────


def test_flatten_kanban_carries_status():
    data = {
        "columns": [
            {"key": "new", "name": "Nowe", "applications": [{"id": "a"}]},
            {"key": "rejected", "name": "Odrzuceni", "applications": [{"id": "b"}]},
        ]
    }
    flat = flatten_kanban(data)
    assert [(a["id"], a["statusKey"]) for a in flat] == [
        ("a", "new"),
        ("b", "rejected"),
    ]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-09-15", "2026-09-15T00:00:00Z"),
        ("2026-09-15T10:00:00+00:00", "2026-09-15T10:00:00Z"),
        ("2026-09-15T10:00:00.123456", "2026-09-15T10:00:00Z"),
    ],
)
def test_applied_from_is_full_iso(raw, expected):
    assert to_iso_timestamp(raw) == expected


def test_skip_reasons():
    assert application_skip_reason({"deletedAt": "2026-01-01"}) == "deleted"
    assert application_skip_reason({"isAnonymized": True}) == "anonymized"
    assert application_skip_reason({"hasCv": False}) == "no_cv"
    assert application_skip_reason({"hasCv": True}) is None


# ── 2. payload Traffit ──────────────────────────────────────────────────────


def test_payload_prefers_cv_email_but_falls_back_to_panel():
    parsed = {
        "first_name": "Jan",
        "last_name": "Kowalski",
        "email": "not-an-email",
        "years_it_experience": 7,
    }
    payload = build_traffit_payload(
        parsed,
        fallback={"first_name": "J.", "last_name": "K.", "email": "jan@example.com"},
        offer_title="DevOps",
    )
    assert payload["email"] == "jan@example.com"
    assert payload["name"] == "Jan" and payload["lastname"] == "Kowalski"
    assert payload["_experience"] == ["5+"]
    assert payload["_Position"] == "DevOps"


def test_language_ids_ignore_unknown():
    assert language_ids(["English (C1)", "Klingon", {"language": "Polski"}]) == [1, 0]


# ── 3. reguła dopasowania ───────────────────────────────────────────────────


def test_match_rule_requires_must_have_when_job_has_them():
    semantic_only = {
        "score": 66.0,
        "status": "published",
        "matching_must": [],
        "gap_must": ["java", "kotlin"],
    }
    real = {
        "score": 66.0,
        "status": "published",
        "matching_must": ["python"],
        "gap_must": ["kafka"],
    }
    no_musts = {
        "score": 66.0,
        "status": "published",
        "matching_must": [],
        "gap_must": [],
    }
    draft = {
        "score": 90.0,
        "status": "draft",
        "matching_must": ["python"],
        "gap_must": [],
    }
    assert is_good_match(semantic_only, min_score=65, require_must=True) is False
    assert is_good_match(real, min_score=65, require_must=True) is True
    assert is_good_match(no_musts, min_score=65, require_must=True) is True
    assert is_good_match(draft, min_score=65, require_must=True) is False
    assert is_good_match(real, min_score=70, require_must=True) is False


# ── 4/5. dry_run i lock (z atrapami panelu / Traffit / NEXUS) ──────────────


class _FakePanel:
    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def login(self):
        return None

    async def list_job_ads(self, state="published"):
        return [{"id": "ad-1", "title": "DevOps Engineer"}]

    async def list_applications(self, job_ad_id, applied_from=None):
        return [
            {
                "id": "app-1",
                "candidateName": "Anna Nowa",
                "candidateEmail": "anna@example.com",
                "hasCv": True,
            },
            {
                "id": "app-2",
                "candidateName": "Jan Znany",
                "candidateEmail": "jan@example.com",
                "hasCv": True,
            },
            {
                "id": "app-3",
                "candidateName": "Bez CV",
                "candidateEmail": "x@example.com",
                "hasCv": False,
            },
        ]

    async def download_cv(self, application_id):
        return CvFile(
            data=b"%PDF-1.4 " + b"x" * 200,
            filename=f"{application_id}.pdf",
            mime="application/pdf",
        )


class _FakeTraffit:
    writes: list = []

    def __init__(self, *_a, **_k):
        pass

    configured = True

    async def search_by_email(self, email):
        return {"id": 777} if email == "jan@example.com" else None

    async def create_candidate(self, payload):
        _FakeTraffit.writes.append(("create", payload))
        return {"status": 201, "data": {"id": 1}}

    async def upload_cv(self, *a, **k):
        _FakeTraffit.writes.append(("upload", a))


class _FakeNexus:
    calls: list = []
    #: Id ISTNIEJĄCEGO kandydata, zakładanego przez fixture `fakes`.
    #: `integration_run_events.candidate_id` ma FK do `candidates`, więc
    #: zmyślone id wywraca prawdziwy run na `ForeignKeyViolationError`.
    candidate_id: int | None = None

    def __init__(self, *_a, **_k):
        pass

    async def push_candidate(self, *a, **k):
        _FakeNexus.calls.append((a, k))
        from app.services.integrations.jjit.nexus_client import MatchResult

        return MatchResult(candidate_id=_FakeNexus.candidate_id, action="created")


async def _seed_candidate() -> int:
    """Kandydat, na którego wskaże `_FakeNexus` — własne dane tego pliku.

    Do 09.2026 fake zwracał na sztywno `candidate_id=1` i prawdziwy run
    przechodził TYLKO wtedy, gdy kandydata o id 1 założył wcześniej inny plik
    testowy w tym samym shardzie. Baza testowa jest współdzielona i nie jest
    czyszczona, więc test zieleniał albo czerwieniał zależnie od tego, z kim
    wylądował w shardzie — a podział shardów przesuwa się przy KAŻDYM nowym
    pliku testowym (`sorted(files)` + `pos % count` w `conftest`).
    """
    import uuid

    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Anna",
            lastname=f"Nowa-jjit-{uuid.uuid4().hex[:8]}",
            email=f"jjit-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)
        return candidate.id


@pytest.fixture
async def fakes(monkeypatch):
    monkeypatch.setenv("JJIT_EMAIL", "test@example.com")
    monkeypatch.setenv("JJIT_PASSWORD", "secret")
    monkeypatch.setattr(runner, "PanelClient", _FakePanel)
    monkeypatch.setattr(runner, "TraffitWriter", _FakeTraffit)
    monkeypatch.setattr(runner, "NexusLoopbackClient", _FakeNexus)
    monkeypatch.setattr(
        runner, "_cv_text", lambda cv: "Anna Nowa anna@example.com Python 5 lat"
    )

    _PARSE_CALLS.clear()

    async def _parse(text, **kwargs):
        _PARSE_CALLS.append(kwargs)
        return {
            "first_name": "Anna",
            "last_name": "Nowa",
            "email": "anna@example.com",
            "years_it_experience": 5,
        }

    monkeypatch.setattr(runner, "parse_cv", _parse)
    monkeypatch.setattr(runner, "PAUSE_BETWEEN_CANDIDATES_SEC", 0)
    _FakeTraffit.writes.clear()
    _FakeNexus.calls.clear()
    _FakeNexus.candidate_id = await _seed_candidate()
    yield
    _FakeNexus.candidate_id = None


_PARSE_CALLS: list[dict] = []


@pytest.mark.asyncio
async def test_dry_run_reports_but_writes_nothing(fakes):
    result = await runner.run_once(
        dry_run=True, since="2026-09-01", states=["published"]
    )
    assert result["status"] == "ok", result
    assert result["created"] == 1  # Anna — nowa w Traffit
    assert result["duplicates"] == 1  # Jan — znany
    assert result["skipped"] == 1  # bez CV
    assert _FakeTraffit.writes == [], "dry_run nie zapisuje w Traffit"
    assert _FakeNexus.calls == [], "dry_run nie woła NEXUS-a"
    async with AsyncSessionLocal() as db:
        run = await db.get(IntegrationRun, result["run_id"])
        assert run.mode == "dry_run" and run.stats["created"] == 1
        remembered = await db.scalar(
            select(IntegrationExternalItem).where(
                IntegrationExternalItem.source == "jjit",
                IntegrationExternalItem.external_id.in_(["app-1", "app-2"]),
            )
        )
        assert remembered is None, "dry_run nie zapamiętuje aplikacji"


@pytest.mark.asyncio
async def test_real_run_writes_and_remembers(fakes):
    result = await runner.run_once(
        dry_run=False, since="2026-09-01", states=["published"]
    )
    assert result["status"] == "ok", result
    assert result["created"] == 1 and result["duplicates"] == 1
    assert [w[0] for w in _FakeTraffit.writes] == ["create", "upload", "upload"], (
        "nowy: create + upload; duplikat dostaje nowe CV"
    )
    assert len(_FakeNexus.calls) == 2
    async with AsyncSessionLocal() as db:
        items = (
            (
                await db.execute(
                    select(IntegrationExternalItem).where(
                        IntegrationExternalItem.source == "jjit",
                        IntegrationExternalItem.external_id.in_(["app-1", "app-2"]),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {i.external_id: i.last_action for i in items} == {
            "app-1": "created",
            "app-2": "cv_refreshed",
        }
    # Drugi prawdziwy run: obie aplikacje już widziane → pominięte, zero zapisów.
    _FakeTraffit.writes.clear()
    _FakeNexus.calls.clear()
    again = await runner.run_once(
        dry_run=False, since="2026-09-01", states=["published"]
    )
    assert (
        again["skipped"] == 3 and _FakeTraffit.writes == [] and _FakeNexus.calls == []
    )


@pytest.mark.asyncio
async def test_concurrent_run_is_rejected(fakes):
    async with runner._RUN_LOCK:
        with pytest.raises(runner.RunInProgress):
            await runner.run_once(
                dry_run=True, since="2026-09-01", states=["published"]
            )
    await asyncio.sleep(0)


async def _forget_seen_applications(monkeypatch) -> None:
    """Wcześniejszy prawdziwy run zapamiętał aplikacje — bez tego są pomijane.

    Tekst CV z fixture'a ma < 50 znaków, więc parser w ogóle by nie ruszył.
    """
    from sqlalchemy import delete

    monkeypatch.setattr(
        runner,
        "_cv_text",
        lambda cv: (
            "Anna Nowa anna@example.com Python 5 lat, AWS, Kubernetes, Terraform"
        ),
    )
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(IntegrationExternalItem).where(
                IntegrationExternalItem.source == "jjit",
                IntegrationExternalItem.external_id.in_(["app-1", "app-2", "app-3"]),
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_dry_run_never_calls_the_paid_model(fakes, monkeypatch):
    """AI-05 (audyt 22.09 r2): wynik odczytu w dry_run jest wyrzucany, więc
    płatne wywołanie modelu (poza licznikiem kosztów) nie ma sensu."""
    await _forget_seen_applications(monkeypatch)
    result = await runner.run_once(
        dry_run=True, since="2026-09-01", states=["published"]
    )
    assert _PARSE_CALLS, f"odczyt CV w ogóle nie pobiegł: {result}"
    assert all(call.get("prefer_llm") is False for call in _PARSE_CALLS)


@pytest.mark.asyncio
async def test_real_run_parses_through_the_ai_quota_gate(fakes, monkeypatch):
    """AI-05: tryb importu idzie przez ``parse_cv(db=…)`` — bramka
    ``ai_feature(cv_parser)``, koszt widoczny w Ustawieniach → AI."""
    await _forget_seen_applications(monkeypatch)
    await runner.run_once(dry_run=False, since="2026-09-01", states=["published"])
    assert _PARSE_CALLS
    assert all(call.get("db") is not None for call in _PARSE_CALLS)
    # Nie zostawiaj zapamiętanych aplikacji dla kolejnych biegów na tej bazie.
    await _forget_seen_applications(monkeypatch)
