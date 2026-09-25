"""Nowa rekrutacja z requestu klienta (/jobs/new) — odczyt przed zapisem."""

import pytest

from app.services import job_request_intake as intake
from app.services.job_request_intake import normalize_model_output

REQUEST = (
    "Szukamy Senior Java Developera do projektu migracji płatności. "
    "Wymagania: Java 17+, Spring Boot, Kafka. Mile widziane: Kubernetes. "
    "Praca hybrydowa — 2 dni w biurze w Warszawie. Budżet do 170 zł/h netto."
)

FULL = {
    "role_name": "Senior Java Developer",
    "must": ["Java 17+", "Spring Boot", "Kafka", "java 17+"],
    "nice": ["Kubernetes", "Kafka"],
    "rate_quote": "do 170 zł/h netto",
    "work_mode": "hybrydowo",
    "onsite_days_per_week": 2,
    "office_city": "Warszawa",
    "project_about": "Migracja systemu płatności.",
    "screening_questions": [
        {
            "question": "Jak skalowałeś Kafkę?",
            "ideal_answer": "partycje",
            "from_request": True,
        },
        {
            "question": "Czy 2 dni w biurze pasują?",
            "ideal_answer": "tak",
            "from_request": False,
        },
    ],
    "evidence": ["Java 17+", "Spring Boot", "zmyślony fragment"],
    # v5: wymagania do wyszukiwania w bazie — bez nich handoff ma brak.
    "search": {"requirements": [["Java 17+"], ["Spring Boot"], ["Kafka"]]},
}


def test_complete_request_has_nothing_missing() -> None:
    result = normalize_model_output(FULL, REQUEST)
    assert result.missing == []
    assert result.rate_budget_hourly == 170.0
    assert result.remote_policy == "hybrid"
    assert result.must == ["Java 17+", "Spring Boot", "Kafka"]
    # Must-have nie jest powtarzany w „mile widzianych”.
    assert result.nice == ["Kubernetes"]
    assert [q.from_request for q in result.screening_questions] == [True, False]


def test_budget_is_derived_from_the_quote_not_from_the_model() -> None:
    # Stawka dzienna nie jest budżetem PLN/h — żadnego przeliczania ÷ 8.
    text = "Stawka 1360 zł/MD netto, praca zdalna."
    result = normalize_model_output({"rate_quote": "1360 zł/MD netto"}, text)
    assert result.rate_budget_hourly is None
    assert "PLN/h" in (result.rate_note or "")
    assert intake.MISSING_BUDGET in result.missing


def test_bare_number_without_unit_is_not_a_budget() -> None:
    """REC-07: „1100” bez waluty i jednostki to często stawka za MD —
    nie wolno zapisać jej jako 1100 PLN/h."""
    text = REQUEST + "\nStawka: 1100"
    result = normalize_model_output({"rate_quote": "1100"}, text)
    assert result.rate_budget_hourly is None
    assert result.rate_note and "1100" in result.rate_note


def test_unit_and_currency_still_give_a_budget() -> None:
    text = REQUEST + "\nBudżet 150 PLN/h netto"
    result = normalize_model_output({"rate_quote": "150 PLN/h netto"}, text)
    assert result.rate_budget_hourly == 150


def test_quote_absent_from_the_request_is_ignored() -> None:
    result = normalize_model_output({"rate_quote": "do 200 zł/h"}, REQUEST)
    assert result.rate_budget_hourly is None
    assert result.rate_quote is None


def test_evidence_keeps_only_fragments_present_in_the_request() -> None:
    result = normalize_model_output(FULL, REQUEST)
    assert "zmyślony fragment" not in result.evidence
    assert "do 170 zł/h netto" in result.evidence


def test_remote_role_needs_no_office() -> None:
    raw = {**FULL, "work_mode": "zdalnie", "onsite_days_per_week": 3}
    result = normalize_model_output(raw, REQUEST)
    assert result.remote_policy == "remote"
    assert result.onsite_days_per_week is None and result.office_city is None
    assert result.missing == []


def test_hybrid_without_days_and_city_is_reported() -> None:
    raw = {**FULL, "onsite_days_per_week": None, "office_city": None}
    result = normalize_model_output(raw, REQUEST)
    assert intake.MISSING_OFFICE_DAYS in result.missing
    assert intake.MISSING_OFFICE_CITY in result.missing


def test_one_question_is_not_enough() -> None:
    raw = {**FULL, "screening_questions": FULL["screening_questions"][:1]}
    assert intake.MISSING_QUESTIONS in normalize_model_output(raw, REQUEST).missing


def _technologies(monkeypatch, *names: str) -> None:
    """Słownik umiejętności w pamięci — na nim kod poznaje technologię."""
    from app.services import keyword_suggest

    monkeypatch.setattr(keyword_suggest, "_catalog", ())
    keyword_suggest.load_catalog(
        [(i, name, "language") for i, name in enumerate(names, start=1)], []
    )


def test_search_requirements_keep_only_whole_words_from_the_request(monkeypatch) -> None:
    """v5 (25.09.2026): słowo spoza maila odpada, kawałek słowa też („go”
    w „google” to nie Go), puste wiersze znikają, najwyżej 4 wiersze.
    Technologia spoza maila („Kotlin”) nie jest angielskim odpowiednikiem."""
    _technologies(monkeypatch, "Kotlin", "Go")
    text = "Szukamy dewelopera: Java, Kafka albo RabbitMQ. Znajomość google cloud."
    raw = {
        "search": {
            "requirements": [
                ["Java", "Kotlin"],
                ["Kafka", "RabbitMQ", "kafka"],
                ["go"],
                ["a|b"],
                "Java",
                ["Google"],
                ["cloud"],
            ]
        }
    }
    result = normalize_model_output(raw, text)
    assert result.search_requirements == [["Java"], ["Kafka", "RabbitMQ"], ["Google"], ["cloud"]]
    assert result.provenance.get("search_requirements") == "request"
    assert intake.MISSING_SEARCH not in result.missing


def test_search_requirements_accept_a_stem_of_a_word_from_the_request(monkeypatch) -> None:
    """v6 (25.09.2026): polskie słowo się odmienia, a wyszukiwarka szuka całych
    słów — wiersz „bankowości” z maila „doświadczenie w bankowości” znalazł na
    produkcji 55 osób, „bankow*” 323. Rdzeń z gwiazdką przechodzi, gdy zaczyna
    słowo z maila i ma co najmniej 4 litery. Gwiazdka przy nazwie technologii
    ze słownika znika („Java*” łapałoby JavaScript)."""
    _technologies(monkeypatch, "Java")
    text = "Doświadczenie w bankowości i płatnościach kartowych. Java, Kafka."
    raw = {
        "search": {
            "requirements": [
                ["bankow*"],
                ["płatnoś*", "Kafka"],
                ["Java*"],
                ["Kafka"],
            ]
        }
    }
    result = normalize_model_output(raw, text)
    assert result.search_requirements == [
        ["bankow*"],
        ["płatnoś*", "Kafka"],
        ["Java"],
        ["Kafka"],
    ]
    assert result.provenance.get("search_requirements") == "request"
    # Za krótki rdzeń, rdzeń ze środka słowa i gwiazdka z przodu nie są
    # słowami z maila — sam taki wiersz odpada.
    for bad in ("ban*", "kowości*", "*kartow", "ubezpiecz*"):
        alone = normalize_model_output({"search": {"requirements": [[bad]]}}, text)
        assert alone.search_requirements == [], bad


def test_search_rows_take_one_english_equivalent_next_to_a_word_from_the_request(
    monkeypatch,
) -> None:
    """Decyzja Artura 25.09.2026: w wierszu może stać JEDEN angielski
    odpowiednik polskiego słowa z maila („bankow* lub banking” — 903 osoby
    zamiast 323). Tylko obok słowa z maila, nigdy technologia; wtedy wiersze
    są „propozycją AI”, a nie „z maila”."""
    _technologies(monkeypatch, "Kotlin")
    text = "Doświadczenie w bankowości i ubezpieczeniach. Java."
    raw = {
        "search": {
            "requirements": [
                ["bankow*", "banking", "finance"],
                ["insurance"],
                ["Java", "Kotlin"],
                ["ubezpiecz*", "insuranc*"],
            ]
        }
    }
    result = normalize_model_output(raw, text)
    assert result.search_requirements == [
        ["bankow*", "banking"],
        ["Java"],
        ["ubezpiecz*", "insuranc*"],
    ]
    assert result.provenance.get("search_requirements") == "ai"
    # Polska forma spoza maila nie jest odpowiednikiem — zostaje samo słowo
    # z maila, a wiersz jest „z maila”.
    polish = normalize_model_output(
        {"search": {"requirements": [["bankow*", "finansów", "kowości*"]]}}, text
    )
    assert polish.search_requirements == [["bankow*"]]
    assert polish.provenance.get("search_requirements") == "request"


def test_missing_search_requirements_are_reported() -> None:
    raw = {**FULL, "search": {"keywords": "Java Developer"}}
    result = normalize_model_output(raw, REQUEST)
    assert result.missing == [intake.MISSING_SEARCH]
    assert result.search_requirements == []


def test_garbage_from_the_model_yields_an_empty_honest_form() -> None:
    result = normalize_model_output("nie JSON", REQUEST)
    assert result.role_name is None and result.must == []
    assert intake.MISSING_ROLE in result.missing


@pytest.mark.asyncio
async def test_read_route_returns_the_intake_without_creating_a_job(
    app_client, app_auth_headers, monkeypatch
) -> None:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async def fake_read(db, *, client_id, request_text):
        return normalize_model_output(FULL, request_text)

    monkeypatch.setattr(intake, "read_request", fake_read)

    async with AsyncSessionLocal() as db:
        client = Client(name="Intake Test Sp. z o.o.")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        jobs_before = await db.scalar(select(func.count(Job.id)))

    resp = await app_client.post(
        "/api/job-intake/read",
        json={"client_id": client.id, "text": REQUEST},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intake"]["rate_budget_hourly"] == 170.0
    assert body["intake"]["missing"] == []

    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count(Job.id))) == jobs_before


@pytest.mark.asyncio
async def test_read_route_rejects_unknown_client(app_client, app_auth_headers) -> None:
    resp = await app_client.post(
        "/api/job-intake/read",
        json={"client_id": 987654321, "text": REQUEST},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


# ── v2: cały profil Championa z requestu (09.2026) ───────────────────────────

PAYMENTS_REQUEST = (
    "Szukamy testera manualnego z doświadczeniem w płatnościach kartowych "
    "(min. 2 lata). Wymagany certyfikat ISTQB Foundation, znajomość PSD2 "
    "mile widziana. Praca zdalna, stawka do 120 zł/h netto."
)


def test_experience_items_need_a_quote_present_in_the_request() -> None:
    result = normalize_model_output(
        {
            "experience": {
                "domains": [
                    {
                        "name": "płatności kartowe",
                        "level": "must",
                        "min_years": 2,
                        "quote": "doświadczeniem w płatnościach kartowych",
                    },
                    # Wywnioskowane z nazwy klienta — brak cytatu w mailu.
                    {"name": "bankowość", "level": "must", "quote": "bank"},
                ],
                "certifications": [
                    {
                        "name": "ISTQB Foundation",
                        "level": "must",
                        "quote": "certyfikat ISTQB Foundation",
                    },
                    {"name": "AWS SAA", "level": "nice", "quote": ""},
                ],
                "regulations": [
                    {"name": "PSD2", "level": "nice", "quote": "znajomość PSD2"}
                ],
            }
        },
        PAYMENTS_REQUEST,
    )
    assert [d["name"] for d in result.experience["domains"]] == ["płatności kartowe"]
    assert result.experience["domains"][0]["min_years"] == 2
    assert [c["name"] for c in result.experience["certifications"]] == [
        "ISTQB Foundation"
    ]
    assert result.experience["regulations"][0]["level"] == "nice"
    # Cytaty trafiają do podświetleń maila.
    assert "certyfikat ISTQB Foundation" in result.evidence
    assert result.provenance["experience"] == "request"


def test_proposals_carry_their_basis_and_facts_are_marked_as_request() -> None:
    result = normalize_model_output(
        {
            **FULL,
            "search": {
                "keywords": "Java, Spring, Kafka, płatności",
                "target_companies": "Asseco, Comarch",
                "disqualifiers": ["brak polskiego"],
                "basis": "client_history",
            },
            "selling_points": {"text": "Greenfield, nowy zespół", "basis": "zmyślone"},
            "ask_client": ["Ile etapów ma rekrutacja?", "Ile etapów ma rekrutacja?"],
        },
        REQUEST,
    )
    assert result.provenance["role"] == "request"
    assert result.provenance["search_keywords"] == "client_history"
    assert result.provenance["target_companies"] == "client_history"
    # Nieznana podstawa to propozycja AI, nie fakt z maila.
    assert result.provenance["selling_points"] == "ai"
    assert result.ask_client == ["Ile etapów ma rekrutacja?"]
    assert result.provenance["questions"] == "ai"
    assert result.disqualifiers == ["brak polskiego"]


@pytest.mark.asyncio
async def test_prompt_carries_client_history_but_no_consultant_notes(
    monkeypatch,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job
    from app.services import champion_draft_service

    captured: dict = {}

    async def fake_call(*, prompt, system_prompt, max_tokens, **_):
        captured["prompt"] = prompt
        captured["max_tokens"] = max_tokens
        return {"role_name": "Tester"}

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", fake_call)

    async with AsyncSessionLocal() as db:
        client = Client(name="Intake Context Test Sp. z o.o.")
        db.add(client)
        await db.flush()
        db.add(
            Job(
                title="Tester manualny płatności",
                client_id=client.id,
                champion_profile={
                    "project": {"about": "Testy procesów kartowych w bankowości."},
                    "search": {"keywords": "tester, karty, acquiring"},
                    "client": {
                        "consultant_insight": "Rozmawiałem z Janem Kowalskim z zespołu",
                    },
                },
            )
        )
        await db.commit()
        result = await intake.read_request(
            db, client_id=client.id, request_text=PAYMENTS_REQUEST
        )

    assert result.role_name == "Tester"
    assert captured["max_tokens"] == 6000
    assert "Testy procesów kartowych" in captured["prompt"]
    assert "tester, karty, acquiring" in captured["prompt"]
    assert "Kowalski" not in captured["prompt"]
