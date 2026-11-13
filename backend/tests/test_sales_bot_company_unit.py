"""G-A i G-B bez bazy: raporty ``enrich`` i ``question``, filtr pytań, przyjęcie pól."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.models.sales import SalesCompany
from app.services.sales import bot_tasks, signals
from app.services.sales.bot_tasks import enrich, question
from app.services.sales.bot_tasks.base import refuse_accept
from app.tasks import sales_signals as loop

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
SRC = "https://rejestr.example/firma"
# Poprawna suma kontrolna (wagi 6,5,7,2,3,4,5,6,7), numer fikcyjny.
NIP = "1234563218"


def _field(value: str, **over: Any) -> dict[str, Any]:
    return {"value": value, "source": SRC, **over}


def _company(**over: Any) -> SalesCompany:
    base = {"id": 7, "name": "Firma Testowa", "normalized_name": "firma testowa"}
    return SalesCompany(**{**base, **over})


# ── raport enrich ────────────────────────────────────────────────────────


def test_enrich_report_refuses_unknown_fields_and_non_http_sources() -> None:
    with pytest.raises(ValidationError):
        enrich.EnrichReport.model_validate(
            {"checked_firms": 1, "firms": [{"company_ref": 7, "email": _field("a")}]}
        )
    with pytest.raises(ValidationError):
        enrich.EnrichReport.model_validate(
            {
                "checked_firms": 1,
                "firms": [
                    {
                        "company_ref": 7,
                        "domain": {"value": "a.pl", "source": "javascript:alert(1)"},
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        enrich.EnrichReport.model_validate(
            {"checked_firms": 1, "firms": [{"company_ref": 7, "size": _field("500")}]}
        )


def test_plan_normalizes_domain_nip_and_size() -> None:
    firm = enrich.EnrichFirm.model_validate(
        {
            "company_ref": 7,
            "domain": _field("https://www.Firma-Testowa.pl/kariera"),
            "website_url": _field("firma-testowa.pl", published="2026-10-01"),
            "nip": _field(f"PL {NIP[:3]}-{NIP[3:6]}-{NIP[6:8]}-{NIP[8:]}"),
            "hq_city": _field("Kraków"),
            "size": _field("1000+"),
            "parent_name": _field("Grupa Testowa S.A."),
        }
    )
    fields, invalid, same = enrich.plan_fields(firm, _company())
    assert (invalid, same) == (0, 0)
    assert fields["domain"]["value"] == "firma-testowa.pl"
    assert fields["website_url"] == {
        "value": "https://firma-testowa.pl",
        "source": SRC,
        "published": "2026-10-01",
    }
    assert fields["nip"]["value"] == NIP
    assert fields["tier"]["value"] == "enterprise"
    assert fields["tier"]["employees"] == "1000+"
    assert list(fields) == [
        "domain",
        "website_url",
        "nip",
        "hq_city",
        "parent_name",
        "tier",
    ]


def test_plan_drops_bad_values_and_values_equal_to_the_card() -> None:
    firm = enrich.EnrichFirm.model_validate(
        {
            "company_ref": 7,
            "domain": _field("gmail.com"),
            "nip": _field("1234563219"),  # zła suma kontrolna
            "website_url": _field("ftp://firma.pl"),
            "hq_city": _field("WARSZAWA"),
            "size": _field("50-249"),
            "parent_name": _field("Firma Testowa sp. z o.o."),  # ta sama firma
        }
    )
    company = _company(hq_city="Warszawa", tier="smb")
    fields, invalid, same = enrich.plan_fields(firm, company)
    assert fields == {}
    assert (invalid, same) == (4, 2)


def test_plan_counts_parent_with_the_same_canonical_name_as_same() -> None:
    firm = enrich.EnrichFirm.model_validate(
        {"company_ref": 7, "parent_name": _field("Grupa Testowa SA")}
    )
    fields, invalid, same = enrich.plan_fields(
        firm, _company(), parent_name="Grupa Testowa S.A."
    )
    assert (fields, invalid, same) == ({}, 0, 1)


def test_normalize_nip() -> None:
    assert enrich.normalize_nip(NIP) == NIP
    assert enrich.normalize_nip(f"pl{NIP}") == NIP
    assert enrich.normalize_nip("123456321") is None
    assert enrich.normalize_nip(f"{NIP}x") is None


def test_enrich_fingerprint_depends_on_values_not_sources() -> None:
    a = {"domain": {"value": "a.pl", "source": "https://x/1"}}
    b = {"domain": {"value": "a.pl", "source": "https://x/2"}}
    assert enrich.fingerprint(7, a) == enrich.fingerprint(7, b)
    assert enrich.fingerprint(7, a) != enrich.fingerprint(8, a)


# ── zapis od razu (decyzja Artura 13.11.2026) ────────────────────────────


FIELDS = {
    "domain": {"value": "firma-testowa.pl", "source": SRC},
    "nip": {"value": NIP, "source": SRC},
    "hq_city": {"value": "Kraków", "source": SRC},
    "tier": {"value": "enterprise", "employees": "1000+", "source": SRC},
    "parent_name": {"value": "Grupa Testowa", "source": SRC},
}


@pytest.fixture
def no_conflicts(monkeypatch):
    async def taken(db, company_id, column, value):  # noqa: ANN001
        return None

    async def parent(db, company, name):  # noqa: ANN001
        return 99, None

    monkeypatch.setattr(enrich, "_taken_by", taken)
    monkeypatch.setattr(enrich, "_parent_match", parent)


@pytest.mark.asyncio
async def test_empty_fields_go_on_the_card_and_human_fields_stay(no_conflicts) -> None:
    company = _company(hq_city="Gdańsk")
    out = await enrich.apply_now(object(), company, FIELDS, {})
    assert (company.domain, company.nip, company.hq_city) == (
        "firma-testowa.pl",
        NIP,
        "Gdańsk",
    )
    assert (company.tier, company.size_range, company.parent_company_id) == (
        "enterprise",
        "1000+",
        99,
    )
    assert out["hq_city"] == {"result": "kept", "current": "Gdańsk"}
    assert out["nip"] == {"result": "applied", "previous": None}
    assert out["parent_name"] == {"result": "applied", "parent_company_id": 99}


@pytest.mark.asyncio
async def test_bot_updates_its_own_value_but_not_a_manual_edit(no_conflicts) -> None:
    company = _company(hq_city="Kraków")
    fields = {"hq_city": {"value": "Wrocław", "source": SRC}}
    out = await enrich.apply_now(object(), company, fields, {"hq_city": "kraków"})
    assert company.hq_city == "Wrocław"
    assert out["hq_city"] == {"result": "applied", "previous": "Kraków"}

    # Handlowiec poprawił miasto ręcznie: inna wartość niż wpisana przez bota.
    company = _company(hq_city="Gdynia")
    out = await enrich.apply_now(object(), company, fields, {"hq_city": "Kraków"})
    assert company.hq_city == "Gdynia"
    assert out["hq_city"]["result"] == "kept"


@pytest.mark.asyncio
async def test_domain_or_nip_of_another_card_is_not_written(monkeypatch) -> None:
    other = _company(id=8, name="Inna Karta")

    async def taken(db, company_id, column, value):  # noqa: ANN001
        return other

    monkeypatch.setattr(enrich, "_taken_by", taken)
    company = _company()
    fields = {key: FIELDS[key] for key in ("domain", "nip", "hq_city")}
    out = await enrich.apply_now(object(), company, fields, {})
    assert (company.domain, company.nip, company.hq_city) == (None, None, "Kraków")
    for key in ("domain", "nip"):
        assert out[key] == {
            "result": "taken",
            "other_id": 8,
            "other_name": "Inna Karta",
        }


@pytest.mark.asyncio
async def test_domain_from_website_only_when_no_other_card_has_it(monkeypatch) -> None:
    site = {"website_url": {"value": "https://firma-testowa.pl", "source": SRC}}
    other = _company(id=8, name="Inna Karta")
    holder: dict[str, Any] = {"card": other}

    async def taken(db, company_id, column, value):  # noqa: ANN001
        return holder["card"]

    monkeypatch.setattr(enrich, "_taken_by", taken)
    company = _company()
    await enrich.apply_now(object(), company, site, {})
    assert (company.website_url, company.domain) == ("https://firma-testowa.pl", None)

    holder["card"] = None
    company = _company()
    await enrich.apply_now(object(), company, site, {})
    assert company.domain == "firma-testowa.pl"


@pytest.mark.asyncio
async def test_parent_without_a_single_match_is_skipped_with_a_note(
    monkeypatch, no_conflicts
) -> None:
    async def parent(db, company, name):  # noqa: ANN001
        return None, "Do „Grupa Testowa” pasuje kilka kart."

    monkeypatch.setattr(enrich, "_parent_match", parent)
    company = _company()
    out = await enrich.apply_now(
        object(), company, {"parent_name": FIELDS["parent_name"]}, {}
    )
    assert company.parent_company_id is None
    assert out["parent_name"]["result"] == "skipped"
    assert "kilka kart" in out["parent_name"]["note"]


def test_enrich_has_no_accept_step() -> None:
    assert enrich.ENRICH.accept is refuse_accept


# ── pytanie ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Czy jan.kowalski@firma.pl nadal tam pracuje?",
        "Kto odbiera pod +48 600 700 800?",
        "Czyj to numer 600-700-800?",
        "Kto ma PESEL 90010112345?",
        "Na jakie konto PL61 1090 1014 0000 0712 1981 2874 płacić?",
        "Czy firma ma numer (22) 123 45 67?",
    ],
)
def test_personal_data_is_refused(text: str) -> None:
    assert question.personal_data_reason(text)
    with pytest.raises(ValueError, match="danych osobowych"):
        question.clean_question(text)


@pytest.mark.parametrize(
    "text",
    [
        "Czy mają centrum IT w Polsce i kogo teraz rekrutują?",
        "Co zmieniło się od 1.10.2026 w zarządzie?",
        "Jakie projekty ogłosili po 2026-10-01?",
        "Ile zarobili w 2025 i 2026 roku?",
    ],
)
def test_ordinary_questions_pass(text: str) -> None:
    assert question.personal_data_reason(text) is None
    assert question.clean_question(f"  {text}\n") == text


def test_question_length_limits() -> None:
    with pytest.raises(ValueError, match="co najmniej"):
        question.clean_question("  co?  ")
    with pytest.raises(ValueError, match="najwyżej"):
        question.clean_question("a" * 301)


def test_question_request_allows_only_the_question() -> None:
    task = bot_tasks.REGISTRY["question"]
    assert task.validate_request({"question": "Kogo rekrutują w IT?"}) == {
        "question": "Kogo rekrutują w IT?"
    }
    with pytest.raises(ValueError):
        task.validate_request({"question": "Kogo rekrutują?", "user": "Ewa"})
    with pytest.raises(ValueError):
        task.validate_request({"question": "Zadzwoń 600 700 800"})
    with pytest.raises(ValueError):
        bot_tasks.REGISTRY["enrich"].validate_request({"question": "Kogo?"})


def test_question_report_limits() -> None:
    line = {"text": "Nowe centrum w Krakowie", "url": "firma.pl/news"}
    report = question.QuestionReport.model_validate(
        {"answer": [line, {"text": "Wniosek: rosną"}]}
    )
    assert report.answer[0].url == "https://firma.pl/news"
    assert report.answer[1].url is None
    for bad in (
        {"answer": [line] * 7},
        {"answer": [{"text": "a" * 401}]},
        {"answer": [{"text": "x", "email": "a@b.pl"}]},
        {"answer": [{"text": "\x00\x01"}]},
    ):
        with pytest.raises(ValidationError):
            question.QuestionReport.model_validate(bad)


def test_question_webhook_sends_question_only_in_request() -> None:
    run, token = signals.new_run(
        "question",
        [7],
        now=NOW,
        request={"question": "Kogo rekrutują w IT?"},
        requested_by_user_id=5,
    )
    run.id = 21
    body = signals.webhook_body(
        run, token, [_company(nip=NIP)], {"rejected": [], "seen_urls": []}
    )
    assert body["request"] == {"question": "Kogo rekrutują w IT?"}
    assert "Kogo rekrutują" not in body["task"]
    assert NIP not in str(body)
    assert "requested_by" not in str(body) and "5" not in str(body["request"])
    assert set(body["report_format"]) == {"answer"}


@pytest.mark.asyncio
async def test_partial_enrich_records_researched_refs_without_changed_fields(
    monkeypatch,
) -> None:
    async def companies(_db, ids):
        assert ids == [7]
        return {7: _company(hq_city="Gdańsk")}

    async def parent_names(_db, _companies):
        return {}

    async def save_results(_db, _run, results, _now, **kw):
        assert results == [] and kw == {"status": "accepted"}
        return 0

    async def owned(_db, _ids):
        return {}

    monkeypatch.setattr(signals, "_companies", companies)
    monkeypatch.setattr(enrich, "_bot_owned", owned)
    monkeypatch.setattr(enrich, "_parent_names", parent_names)
    monkeypatch.setattr(enrich, "save_results", save_results)
    run, _token = signals.new_run("enrich", [7, 8, 9], now=NOW)
    report = enrich.EnrichReport.model_validate(
        {
            "checked_firms": 2,
            "firms": [
                {"company_ref": 7, "hq_city": _field("Gdańsk")},
                {"company_ref": 99, "hq_city": _field("Poznań")},
            ],
            "not_found": [8, 99],
        }
    )
    summary = await enrich._ingest(object(), run, report, NOW)
    assert summary["researched_company_ids"] == [7, 8]
    assert summary["results"] == 0
    assert summary["not_found"] == 1


def test_new_kinds_are_registered_with_their_rules() -> None:
    assert bot_tasks.REGISTRY["enrich"].request_model is None
    assert bot_tasks.REGISTRY["question"].request_model is question.QuestionRequest
    assert bot_tasks.REGISTRY["question"].accept is bot_tasks.base.refuse_accept
    assert not bot_tasks.REGISTRY["enrich"].lead_feedback


# ── noc ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_night_enrich_waits_for_the_flag_and_the_night(monkeypatch) -> None:
    class _NoDb:
        async def execute(self, *a, **kw):  # noqa: ANN002, ANN003
            raise AssertionError("bez flagi i poza nocą nie pytamy bazy")

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    night = datetime(2026, 11, 12, 2, 0)
    assert await loop._night_enrich(_NoDb(), now=NOW, local=night) == 0
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    day = datetime(2026, 11, 12, 10, 0)
    assert await loop._night_enrich(_NoDb(), now=NOW, local=day) == 0
