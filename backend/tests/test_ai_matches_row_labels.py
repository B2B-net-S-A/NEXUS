"""Etykiety rubryk (0278) na wierszu `/ai-matches`: skąd wzięło się „wymagane",
status stawki i biura, lista brakujących must-have — jako część odpowiedzi
`_build_match_info`, nie tylko wewnętrznego stanu bramki.

`missing_must` jest ŚWIADOMIE węższe niż `gaps`: `gaps` porównuje z tym, co
wyświetla wiersz (może pochodzić z regexa po prozie), `missing_must` — tylko
z `inputs.must_skills` (kolumna/Tier 0 Championa), czyli dokładnie z listą,
którą egzekwuje twarda bramka na pięciu powierzchniach.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.api.matching import _build_match_info, _required_skills_with_source
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.job import Job
from app.services.dealbreaker_filters import (
    DealbreakerInputs,
    office_fit_status,
    rate_fit_status,
)


def _candidate(**overrides) -> SimpleNamespace:
    base = dict(
        id=1,
        name="Jan",
        lastname="Kowalski",
        email="jan@example.com",
        phone=None,
        location=None,
        status=None,
        competence_category=None,
        tags=None,
        skills=None,
        verified_tech=None,
        cv_extracted_data=None,
        raw_cv_text=None,
        ai_summary=None,
        avatar_url=None,
        expected_rate_hourly=None,
        expected_rate_currency=None,
        max_onsite_days_per_week=None,
        linkedin_current_title=None,
        linkedin_current_company=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _job(**overrides) -> SimpleNamespace:
    base = dict(
        must_skills=None,
        champion_profile=None,
        requirements=None,
        description=None,
        title=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _lower(names) -> list[str]:
    """Porównanie źródeł bez wielkości liter — casing kanonicznej nazwy z
    taksonomii ("Kubernetes" vs "kubernetes") nie jest tym, co te testy badają."""
    return [str(n).lower() for n in names]


@pytest.mark.unit
class TestRequiredSkillsSource:
    def test_structured_column_wins_over_champion_and_text(self) -> None:
        job = _job(
            must_skills=[{"name": "Python"}],
            champion_profile={"stack": {"must": [{"name": "Kubernetes"}]}},
            requirements="java, spring",
        )
        skills, source = _required_skills_with_source(job)
        assert _lower(skills) == ["python"]
        assert source == "must_skills"

    def test_champion_stack_wins_over_narrative_and_text_when_column_empty(
        self,
    ) -> None:
        job = _job(
            must_skills=None,
            champion_profile={"stack": {"must": [{"name": "Kubernetes"}]}},
            requirements="java, spring",
        )
        skills, source = _required_skills_with_source(job)
        assert _lower(skills) == ["kubernetes"]
        assert source == "champion_stack"

    def test_champion_narrative_wins_over_text_when_no_explicit_must(self) -> None:
        """Champion obecny (`role_name`), ale bez sekcji 3 „Stack" — Tier 1-3
        `_extract_skills_from_champion` spada na treść wymagań oferty.

        `ALIAS_MAP` jest domyślnie PUSTA poza testowanym procesem aplikacji
        (hydrowana z bazy dopiero przy starcie realnej aplikacji/przez Cortex),
        więc Tier 1-3 (regex po taksonomii) nie ma czego dopasować bez
        jawnego wpisu — `_isolate_skill_taxonomy` (autouse) przywraca stan
        po teście, więc nie trzeba sprzątać ręcznie.
        """
        from app.services import scoring_service as ss

        # `set_alias_map` normalizuje WARTOŚCI do lowercase (tak samo robi
        # realna hydratacja z bazy) — kanoniczne nazwy w tym systemie są
        # zawsze małymi literami, niezależnie od wielkości liter w prozie.
        ss.set_alias_map({"kubernetes": "Kubernetes"})
        job = _job(
            must_skills=None,
            champion_profile={"role_name": "Senior Backend"},
            requirements="Wymagana znajomość Kubernetes.",
        )
        skills, source = _required_skills_with_source(job)
        assert skills == ["kubernetes"]
        assert source == "champion_narrative"

    def test_requirements_text_is_the_last_resort(self) -> None:
        from app.services import scoring_service as ss

        ss.set_alias_map({"java": "java", "spring boot": "spring boot"})
        job = _job(
            must_skills=None,
            champion_profile=None,
            requirements="java, spring boot",
        )
        skills, source = _required_skills_with_source(job)
        assert skills == ["java", "spring boot"]
        assert source == "requirements_text"


@pytest.mark.unit
class TestRateFitStatus:
    def test_ok_over_budget_and_unknown(self) -> None:
        inputs = DealbreakerInputs(budget_hourly=180.0)
        in_budget = _candidate(expected_rate_hourly=150, expected_rate_currency="PLN")
        over_budget = _candidate(expected_rate_hourly=200, expected_rate_currency="PLN")
        unknown_rate = _candidate(expected_rate_hourly=None)

        assert rate_fit_status(in_budget, inputs) == "ok"
        assert rate_fit_status(over_budget, inputs) == "over_budget"
        assert rate_fit_status(unknown_rate, inputs) == "unknown"

    def test_unknown_when_job_has_no_budget(self) -> None:
        inputs = DealbreakerInputs(budget_hourly=None)
        cand = _candidate(expected_rate_hourly=150, expected_rate_currency="PLN")
        assert rate_fit_status(cand, inputs) == "unknown"


@pytest.mark.unit
class TestOfficeFitStatus:
    def test_not_required_for_a_fully_remote_job(self) -> None:
        inputs = DealbreakerInputs(onsite_days_per_week=None)
        cand = _candidate(max_onsite_days_per_week=1)
        assert office_fit_status(cand, inputs) == "not_required"

    def test_days_exceeded(self) -> None:
        inputs = DealbreakerInputs(onsite_days_per_week=3)
        cand = _candidate(max_onsite_days_per_week=1)
        assert office_fit_status(cand, inputs) == "days_exceeded"

    def test_city_mismatch(self) -> None:
        inputs = DealbreakerInputs(
            onsite_days_per_week=3, office_tokens=frozenset({"warszawa"})
        )
        cand = _candidate(max_onsite_days_per_week=3, location="Kraków")
        assert office_fit_status(cand, inputs) == "city_mismatch"

    def test_ok_when_days_and_city_both_satisfied(self) -> None:
        inputs = DealbreakerInputs(
            onsite_days_per_week=3, office_tokens=frozenset({"warszawa"})
        )
        cand = _candidate(max_onsite_days_per_week=3, location="Warszawa")
        assert office_fit_status(cand, inputs) == "ok"

    def test_unknown_when_declaration_is_missing(self) -> None:
        inputs = DealbreakerInputs(onsite_days_per_week=3)
        cand = _candidate(max_onsite_days_per_week=None)
        assert office_fit_status(cand, inputs) == "unknown"


@pytest.mark.unit
class TestBuildMatchInfoRubricLabels:
    def test_missing_must_lists_gaps_only_for_candidates_with_a_skill_signal(
        self,
    ) -> None:
        inputs = DealbreakerInputs(must_skills=("python",))
        has_signal = _candidate(skills=[{"name": "Java"}])
        info = _build_match_info(has_signal, ["java"], inputs=inputs)
        assert info["missing_must"] == ["python"]

        no_signal = _candidate()
        info_no_signal = _build_match_info(no_signal, ["java"], inputs=inputs)
        assert info_no_signal["missing_must"] == []

    def test_missing_must_is_empty_when_gate_has_nothing_to_require(self) -> None:
        """`gaps` (regex/prosa) może coś pokazać, `missing_must` — nigdy, gdy
        bramka nie ma jawnego must-have (kolumna/Tier 0 Championa puste)."""
        inputs = DealbreakerInputs(must_skills=())
        cand = _candidate(skills=[{"name": "Java"}])
        info = _build_match_info(cand, ["python", "kafka"], inputs=inputs)
        assert info["gaps"] == ["kafka", "python"]
        assert info["missing_must"] == []

    def test_rubric_fields_default_to_unknown_and_empty_without_inputs(self) -> None:
        """Wywołanie bez `inputs=` (stare testy jednostkowe) nie wybucha i
        zwraca bezpieczne wartości domyślne."""
        cand = _candidate(skills=[{"name": "Java"}, {"name": "Kafka"}])
        info = _build_match_info(cand, ["java", "kafka"])
        assert info["matching_skills"] == ["java", "kafka"]
        assert info["gaps"] == []
        assert info["rate_fit"] == "unknown"
        assert info["office_fit"] == "unknown"
        assert info["missing_must"] == []

    def test_matching_skills_and_gaps_shape_is_unchanged_by_rubric_fields(
        self,
    ) -> None:
        """Smoke test na zgodność wsteczną: dołożenie `rate_fit`/`office_fit`/
        `missing_must` nie rusza `matching_skills`/`gaps`/`nice_matching`/
        `nice_gaps` — kontrakt sprzed 0278 zostaje bajt w bajt."""
        inputs = DealbreakerInputs(must_skills=("java",))
        cand = _candidate(skills=[{"name": "Java"}])
        info = _build_match_info(
            cand, ["java", "kafka"], nice_skills=["docker"], inputs=inputs
        )
        assert info["matching_skills"] == ["java"]
        assert info["gaps"] == ["kafka"]
        assert info["nice_matching"] == []
        assert info["nice_gaps"] == ["docker"]
        for key in ("rate_fit", "office_fit", "missing_must"):
            assert key in info


# ── HTTP: etykiety na wierszu, obie gałęzie ─────────────────────────────────
#
# `warn` (NDA) jest ZWOLNIONY z dealbreakerów, więc jest to jedyny sposób,
# żeby zobaczyć etykiety rubryk na wierszu kandydata, który wszystkie trzy
# rubryki NARUSZA — kandydat spełniający je zostałby po prostu ukryty i nic
# by nie było widać. Wzorzec fixture'a jak `gated_over_budget_fixture`
# w test_ai_matches_fallback_eligibility.py.


@pytest_asyncio.fixture
async def rubric_labels_fixture():
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"AIMatch RowLabels Client {unique}")
        db.add(client)
        await db.flush()

        job = Job(
            requirements_reviewed=True,
            matching_requirements={
                "version": 1,
                "reviewed": True,
                "missing_evidence_policy": "exclude",
                "all_of": [
                    {
                        "any_of": ["python"],
                        "level": "must",
                        "source": "manual",
                        "evidence": "",
                    }
                ],
            },
            title=f"AIMatch RowLabels Job {unique}",
            client_id=client.id,
            description="Python backend engineer",
            requirements="python",
            hiring_manager_contact_id=None,
            must_skills=[{"name": "python"}],
            rate_budget_hourly=Decimal("100.00"),
            onsite_days_per_week=3,
            location="Warszawa",
        )
        ok_candidate = Candidate(
            name="Pasuje",
            lastname=f"Wszystko{unique}",
            email=f"row-labels-ok-{unique}@example.com",
            status=CandidateStatus.active,
            skills=[{"name": "python"}],
            expected_rate_hourly=Decimal("80.00"),
            expected_rate_currency="PLN",
            max_onsite_days_per_week=3,
            location="Warszawa, mazowieckie",
        )
        warn_candidate = Candidate(
            # `warn` (NDA) — jedyny sposób, by zobaczyć na wierszu kandydata
            # naruszającego rubryki (byłby inaczej ukryty). Lokalizacja
            # ŚWIADOMIE "Warszawa" — job.location podwaja rolę rubryki biura
            # I domyślnego filtra lokalizacji `/ai-matches` (gdy `location`
            # nie jest podane w query, handler pada na `job.location`); inne
            # miasto wycięłoby ten wiersz PRZED dealbreakerami, przez filtr
            # lokalizacji, nie przez rubrykę biura — city_mismatch jest już
            # pokryty jednostkowo w `TestOfficeFitStatus` wyżej.
            name="Narusza",
            lastname=f"Wszystko{unique}",
            email=f"row-labels-warn-{unique}@example.com",
            status=CandidateStatus.active,
            skills=[{"name": "java"}],
            expected_rate_hourly=Decimal("200.00"),
            expected_rate_currency="PLN",
            max_onsite_days_per_week=1,
            location="Warszawa",
        )
        db.add_all([job, ok_candidate, warn_candidate])
        await db.flush()
        db.add(
            CandidateConflict(
                candidate_id=warn_candidate.id,
                client_id=client.id,
                type=ConflictType.nda,
                reason="pytest — etykiety rubryk na wierszu warn",
                active=True,
            )
        )
        await db.commit()
        ids = (job.id, ok_candidate.id, warn_candidate.id, client.id)

    yield ids

    job_id, ok_id, warn_id, client_id = ids
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateConflict).where(CandidateConflict.client_id == client_id)
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_([ok_id, warn_id])))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


def _match(body: dict, cid: int) -> dict | None:
    for m in body["matches"]:
        if m["candidate"]["id"] == cid:
            return m
    return None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_matches_rows_carry_rubric_labels_on_both_branches(
    app_client: AsyncClient,
    app_auth_headers: dict,
    rubric_labels_fixture,
    monkeypatch,
):
    job_id, ok_id, warn_id, _client_id = rubric_labels_fixture
    monkeypatch.setattr(settings, "MATCH_POOL_SIZE", 100_000)

    # ── gałąź fallback (droga 3: pusty wynik Qdranta, cicho) ────────────────
    async def _no_hits(*_a, **_kw):
        return []

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _no_hits
    )
    resp_fallback = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 500},
        headers=app_auth_headers,
    )
    assert resp_fallback.status_code == 200, resp_fallback.text
    body_fallback = resp_fallback.json()
    assert body_fallback["required_skills_source"] == "must_skills"
    assert body_fallback["rubrics"] == {
        "budget_hourly": 100.0,
        "onsite_days_per_week": 3,
        "office_location": "Warszawa",
        "must_skills": ["python"],
        # 0278 + naprawa 08.09: rubryki mówią, które must-have REALNIE bramkują,
        # a które są punktem wymagań i zostają wyłącznie sygnałem scoringowym.
        # Bramka, która po cichu nie działa, jest tym samym błędem co ciche
        # ukrywanie — patrz test_must_gate_prose_regression.py.
        "must_skills_gating": ["python"],
        "must_skills_ignored": [],
    }
    ok_row = _match(body_fallback, ok_id)
    assert ok_row is not None
    assert ok_row["rate_fit"] == "ok"
    assert ok_row["office_fit"] == "ok"
    assert ok_row["missing_must"] == []
    warn_row = _match(body_fallback, warn_id)
    assert warn_row is not None, (
        "warn musi zostać wierszem, żeby dało się zobaczyć etykiety"
    )
    assert warn_row["rate_fit"] == "over_budget"
    assert warn_row["office_fit"] == "days_exceeded"
    assert warn_row["missing_must"] == ["python"]

    # ── gałąź semantyczna (prawdziwe trafienia z Qdranta) ───────────────────
    async def _hits(*_a, **_kw):
        return [
            {"candidate_id": ok_id, "score": 0.9},
            {"candidate_id": warn_id, "score": 0.8},
        ]

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _hits
    )
    resp_semantic = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 500},
        headers=app_auth_headers,
    )
    assert resp_semantic.status_code == 200, resp_semantic.text
    body_semantic = resp_semantic.json()
    assert body_semantic["search_type"] == "semantic+composite"
    ok_row2 = _match(body_semantic, ok_id)
    assert ok_row2 is not None
    assert ok_row2["rate_fit"] == "ok"
    assert ok_row2["office_fit"] == "ok"
    assert ok_row2["missing_must"] == []
    warn_row2 = _match(body_semantic, warn_id)
    assert warn_row2 is not None
    assert warn_row2["rate_fit"] == "over_budget"
    assert warn_row2["office_fit"] == "days_exceeded"
    assert warn_row2["missing_must"] == ["python"]


@pytest.mark.parametrize("currency", ["EUR", "PLN", None])
def test_match_payload_preserves_hourly_rate_currency(currency):
    candidate = _candidate(
        expected_rate_hourly=Decimal("100.50"), expected_rate_currency=currency
    )
    result = _build_match_info(
        candidate, [], inputs=DealbreakerInputs(budget_hourly=150)
    )
    assert result["candidate"]["expected_rate_hourly"] == 100.5
    assert result["candidate"]["expected_rate_currency"] == currency
    assert result["candidate"]["expected_rate_unit"] == "hour"
    assert result["rate_fit"] == ("ok" if currency == "PLN" else "unknown")
