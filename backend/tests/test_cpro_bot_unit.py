"""Bot Cpro bez bazy: pola oferty, braki, raport bota, stan karty.

Reguła: ``docs/claude/integracje/cpro-bot-grok.md``. Przykłady to wpisy
z nagrania osoby od Cpro (28.10.2026): „Gdynia, willing to come to the Nordea
office in Gdynia 3x/week, available from 01.12.2026, a Former employee…”.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.cpro_bot import CproBotRun
from app.services.cpro_bot import ingest, offer_text, runs, task_text
from app.services.cpro_bot import items as bot_items

TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)

WHY_HTML = (
    '<h2 data-cv-section="role">KYC – 3 x IT Automation Tester Senior</h2>'
    '<h2 data-cv-section="why_points">WHY OUR CANDIDATE?</h2>'
    "<ul><li><p>Over <strong>6 years</strong> at Nordea Bank</p></li>"
    "<li><p>Over 10 years of experience in test automation with C#</p></li></ul>"
    '<h2 data-cv-section="education">EDUCATION</h2><p>TU Wien</p>'
)


def _cv(**over) -> bot_items.CvFile:
    base = dict(
        candidate_stage_id=11,
        version=2,
        filename="B2B_KYC – Tester_Thomas Feest.pdf",
        why_points=("Over 6 years at Nordea Bank", "SQL skills"),
        job_id=5,
    )
    return bot_items.CvFile(**{**base, **over})


def _payload(**over):
    base = dict(
        stage_id=101,
        first_name="Thomas",
        last_name="Feest",
        job_title="PL_KYC_3 x IT Automation Tester Senior",
        job_location="Gdynia, Gdańsk lub Warszawa",
        delivery_lead_id=14,
        delivery_lead_active=True,
        remote_policy="hybrid",
        onsite_days_per_week=3,
        request_no="42511",
        rate=(163.0, "hourly", "PLN"),
        available_date=date(2026, 12, 1),
        card={
            "location": {"raw": "Gdynia"},
            "nationality": {"raw": "Austria"},
            "worked_at_client": {"raw": "pracował na UoP", "value": "uop"},
        },
        profile_city=None,
        cv=_cv(),
        accepted=True,
        qc_blocking_failed=0,
        today=TODAY,
    )
    return bot_items.build_payload(**{**base, **over})


# ── Pola oferty ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("delivery_lead_id", "name", "vault_entry"),
    [
        (14, "Igor", "Nordea Cpro – Igor"),
        (27, "Marcin", "Nordea Cpro – Marcin"),
        (32, "Dominik", "Nordea Cpro – Marcin"),
    ],
)
def test_account_belongs_to_the_target_jobs_delivery_lead(
    delivery_lead_id, name, vault_entry
) -> None:
    blockers, payload = _payload(delivery_lead_id=delivery_lead_id)
    assert blockers == ()
    assert payload["cpro_account"] == {
        "delivery_lead_id": delivery_lead_id,
        "delivery_lead_name": name,
        "vault_entry": vault_entry,
    }


@pytest.mark.parametrize(
    ("delivery_lead_id", "delivery_lead_active"),
    [(None, True), (999999, True), (14, False), (27, False), (32, False)],
)
def test_unknown_missing_or_inactive_delivery_lead_never_has_a_payload(
    delivery_lead_id, delivery_lead_active
) -> None:
    blockers, payload = _payload(
        delivery_lead_id=delivery_lead_id,
        delivery_lead_active=delivery_lead_active,
    )
    assert payload is None
    assert blockers == (bot_items.BLOCK_NO_CPRO_ACCOUNT,)


@pytest.mark.parametrize(
    "lead_id,hint,name",
    [
        (14, "Nordea Cpro – Igor", "Igor"),
        (27, "Nordea Cpro – Marcin", "Marcin"),
        (32, "Nordea Cpro – Marcin", "Marcin"),
        (32, "Nordea Cpro – Igor", None),
        (999999, "Nordea Cpro – Marcin", None),
        (None, "Nordea Cpro – Marcin", None),
        ("32", "Nordea Cpro – Marcin", None),
        (32, "unknown", None),
    ],
)
def test_portal_account_name_validates_real_owner_and_hint(lead_id, hint, name):
    assert (
        bot_items.cpro_account_name({"delivery_lead_id": lead_id, "vault_entry": hint})
        == name
    )


def test_dominik_task_preserves_real_owner_and_uses_only_marcins_account():
    _, item = _payload(delivery_lead_id=32)
    run, _ = runs.new_run([item], now=NOW, submit=False)
    run.id = 43
    snapshot = runs.task_body(run)["items"][0]["cpro_account"]
    assert snapshot == {
        "delivery_lead_id": 32,
        "delivery_lead_name": "Dominik",
        "vault_entry": "Nordea Cpro – Marcin",
    }
    assert "delivery_lead_id = 32" in task_text.TASK
    assert "Nie zamieniaj go na 27" in task_text.TASK


def test_location_cheat_sheet_matches_the_recording() -> None:
    blockers, payload = _payload()
    assert blockers == ()
    offer = payload["offer"]
    assert offer["physical_location"] == (
        "Gdynia, willing to come to the Nordea office in Gdynia 3x/week, "
        "available from 01.12.2026, a former employee at Nordea"
    )
    assert offer["available_from"] == "2026-12-01"
    assert offer["rate"] == "163"
    assert (offer["former_employee"], offer["former_consultant"]) == (True, False)
    assert payload["request_number"] == "42511"
    assert payload["candidate"]["citizenship"] == "Austria"
    assert offer["cv_format"] == "pdf" and offer["cv_version"] == 2
    assert offer["cv_file_name"].endswith(".pdf")


@pytest.mark.parametrize(
    ("card", "available", "phrase", "from_day"),
    [
        ({"asap": True}, None, "available ASAP", TODAY),
        ({}, None, "available ASAP", TODAY),
        (
            {"notice": {"value": 4, "unit": "weeks"}},
            None,
            "a 4-week notice period",
            TODAY + timedelta(weeks=4),
        ),
        (
            {"notice": {"value": 1, "unit": "months"}},
            None,
            "a 1-month notice period",
            date(2026, 12, 17),
        ),
        # Data z NEXUSA w przyszłości wygrywa z okresem z karty.
        (
            {"notice": {"value": 1, "unit": "months"}},
            date(2027, 1, 4),
            "available from 04.01.2027",
            date(2027, 1, 4),
        ),
        # Data z przeszłości to „od zaraz”.
        ({}, date(2026, 11, 1), "available ASAP", TODAY),
    ],
)
def test_availability_follows_the_notice_rules(
    card, available, phrase, from_day
) -> None:
    result = offer_text.availability(
        today=TODAY, available_date=available, card_value=card
    )
    assert (result.phrase, result.available_from) == (phrase, from_day)


def test_add_months_clamps_to_the_last_day() -> None:
    assert offer_text.add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert offer_text.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


@pytest.mark.parametrize(
    ("candidate", "job", "office"),
    [
        ("Gdynia", "Gdynia, Gdańsk lub Warszawa", "Gdynia"),
        ("Warszawa, Mokotów", "Gdynia, Gdańsk lub Warszawa", "Warsaw"),
        ("Sopot", "Gdańsk lub Warszawa", "Gdansk"),
        ("Kraków", "Warszawa", "Warsaw"),
        ("Łódź", None, "Lodz"),
    ],
)
def test_office_city(candidate, job, office) -> None:
    assert offer_text.office_city(candidate, job) == office


def test_remote_and_former_consultant_variants() -> None:
    former = offer_text.former_at_client({"value": "b2b"})
    text = offer_text.physical_location(
        city="Warsaw",
        office="Warsaw",
        remote_policy="remote",
        onsite_days_per_week=None,
        availability_phrase="available ASAP",
        former=former,
    )
    assert (
        text
        == "Warsaw, working remotely, available ASAP, a former consultant at Nordea"
    )
    unknown = offer_text.former_at_client({"raw": "tak", "value": "yes"})
    assert (unknown.employee, unknown.consultant) == (None, None)


def test_motivation_dashes_without_blank_lines() -> None:
    assert (
        offer_text.motivation(
            ["• **Over 6 years** at Nordea", "", "- SQL  skills\n", "2) CI/CD"]
        )
        == "- Over 6 years at Nordea\n- SQL skills\n- CI/CD"
    )


def test_filename_without_hash_and_citizenship_mapping() -> None:
    assert offer_text.safe_filename("CV_#C#_Dev.docx") == "CV_C_Dev.pdf"
    assert offer_text.safe_filename(None) == "CV.pdf"
    assert (
        offer_text.safe_filename("CV_#C#_Dev.docx", extension=".docx")
        == "CV_C_Dev.docx"
    )
    assert offer_text.safe_filename("CV_#C#_Dev.PDF") == "CV_C_Dev.pdf"
    assert len(offer_text.safe_filename("x" * 200)) == 180
    assert offer_text.safe_filename("x" * 200).endswith(".pdf")
    assert offer_text.citizenship("polskie") == "Poland"
    assert offer_text.citizenship("Polak") == "Poland"
    assert offer_text.citizenship("Austria") == "Austria"
    assert offer_text.citizenship(" - ") is None


def test_why_points_come_from_the_marked_section_only() -> None:
    assert bot_items.why_points_from_html(WHY_HTML) == [
        "Over 6 years at Nordea Bank",
        "Over 10 years of experience in test automation with C#",
    ]
    assert bot_items.why_points_from_html(None) == []


# ── Braki ───────────────────────────────────────────────────────────────────


def test_blockers_name_every_gap_and_hold_the_item() -> None:
    blockers, payload = _payload(
        accepted=False,
        rate=None,
        request_no=None,
        cv=None,
        qc_blocking_failed=2,
        card={},
    )
    assert payload is None
    assert blockers == (
        bot_items.BLOCK_NOT_ACCEPTED,
        bot_items.BLOCK_NO_RATE,
        bot_items.BLOCK_NO_REQUEST,
        bot_items.BLOCK_NO_CV,
        bot_items.BLOCK_QC,
        bot_items.BLOCK_NO_CITY,
        bot_items.BLOCK_NO_CITIZENSHIP,
    )


def test_daily_rate_and_cv_without_why_points_are_blockers() -> None:
    blockers, _ = _payload(rate=(1200.0, "daily", "PLN"), cv=_cv(why_points=()))
    assert blockers == (bot_items.BLOCK_RATE_UNIT, bot_items.BLOCK_NO_WHY)


def test_profile_city_fills_a_missing_card_location() -> None:
    blockers, payload = _payload(
        card={"nationality": {"raw": "polska"}}, profile_city="Warszawa"
    )
    assert blockers == ()
    assert payload["offer"]["physical_location"].startswith(
        "Warsaw, willing to come to the Nordea office in Warsaw 3x/week"
    )


def test_card_values_fall_back_to_the_freshest_other_card() -> None:
    values, used = bot_items.merge_card_values(
        {"location": {"raw": "Gdynia"}, "nationality": {"raw": "-"}},
        [
            (
                "42480",
                {"nationality": {"raw": "Austria"}, "location": {"raw": "Sopot"}},
            ),
            ("42301", {"worked_at_client": {"raw": "UoP", "value": "uop"}}),
        ],
    )
    assert values["location"]["raw"] == "Gdynia"
    assert values["nationality"]["raw"] == "Austria"
    assert values["worked_at_client"]["value"] == "uop"
    assert used == ["42480", "42301"]


def test_role_title_drops_client_prefix_and_request_number() -> None:
    assert (
        bot_items.role_title("Nordea: Senior IT Analyst for CBT unit (42930)")
        == "Senior IT Analyst for CBT unit"
    )
    assert bot_items.role_title("PL_KYC_3 x IT Automation Tester Senior") == (
        "PL_KYC_3 x IT Automation Tester Senior"
    )


def test_request_number_and_rate_text() -> None:
    assert bot_items.request_number("Request 42511 / KYC") == "42511"
    assert bot_items.request_number("ZOB") is None
    assert bot_items.rate_text(163.5) == "163.5"
    assert bot_items.rate_text(155.0) == "155"


# ── Raport bota ─────────────────────────────────────────────────────────────


def _run(**over) -> CproBotRun:
    run = CproBotRun(
        id=7,
        status="started",
        submit=True,
        stage_ids=[101, 102],
        request={"items": [], "cards": {}},
        report={},
        started_at=NOW,
    )
    for key, value in over.items():
        setattr(run, key, value)
    return run


def test_report_keeps_only_run_cards_and_safe_links() -> None:
    report = ingest.CproReport.model_validate(
        {
            "items": [
                {
                    "ref": 101,
                    "outcome": "submitted",
                    "cpro_status": "SELECTION",
                    "offer_url": "https://nordea.onevms.se/nordea/vendor/OfferController?action=view&id=160321",
                },
                {
                    "ref": 102,
                    "outcome": "failed",
                    "reason": "request_closed",
                    "message": "Request\x00 zamknięty",
                    "offer_url": "javascript:alert(1)",
                },
                {"ref": 999, "outcome": "submitted"},
            ]
        }
    )
    summary = ingest.summarize(_run(), report)
    assert set(summary["items"]) == {"101", "102"}
    assert summary["items"]["101"]["offer_url"].startswith("https://nordea.onevms.se/")
    assert summary["items"]["102"]["offer_url"] is None
    assert summary["items"]["102"]["message"] == "Request zamknięty"
    assert summary["counts"] == {
        "submitted": 1,
        "draft": 0,
        "failed": 1,
        "skipped": 0,
        "missing": 0,
        "unknown": 1,
    }


def test_trial_run_never_counts_as_sent() -> None:
    report = ingest.CproReport.model_validate(
        {"items": [{"ref": 101, "outcome": "submitted"}]}
    )
    summary = ingest.summarize(_run(submit=False), report)
    assert summary["items"]["101"]["outcome"] == "draft"


def test_report_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        ingest.CproReport.model_validate(
            {"items": [{"ref": 1, "outcome": "draft", "pesel": "1"}]}
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://nordea.onevms.se/x",
        "https://onevms.se.evil.example/x",
        "https://evil.example/onevms.se",
    ],
)
def test_offer_link_only_https_onevms(url) -> None:
    assert ingest.offer_link(url) is None


# ── Stan karty i pętla ──────────────────────────────────────────────────────


def test_item_state_from_runs() -> None:
    working = runs.state_for(_run(), 101, 1)
    assert working.state == "working"
    expired = runs.state_for(_run(status="expired"), 101, 1)
    assert expired.state == "retry"
    received = _run(
        status="received",
        received_at=NOW,
        report={
            "items": {
                "101": {
                    "outcome": "submitted",
                    "moved": False,
                    "move_problem": "Karta była już przesunięta.",
                }
            }
        },
    )
    sent = runs.state_for(received, 101, 1)
    assert (sent.state, sent.moved, sent.message) == (
        "submitted",
        False,
        "Karta była już przesunięta.",
    )
    missing = runs.state_for(received, 102, 1)
    assert missing.state == "failed"


def test_loop_never_resends_and_retries_at_most_three_times() -> None:
    later = NOW + timedelta(hours=1)
    assert runs.due_for_bot(None, now=later)
    for state in ("submitted", "failed", "skipped", "working"):
        assert not runs.due_for_bot(runs.ItemState(state, NOW, 1), now=later)
    assert runs.due_for_bot(runs.ItemState("draft", NOW, 1, submit=False), now=later)
    # Szkic z prawdziwego biegu: jak bieg, który padł — limit i przerwa.
    assert not runs.due_for_bot(
        runs.ItemState("draft", NOW, 1, attempts=10, submit=True),
        now=NOW + timedelta(minutes=5),
    )
    assert not runs.due_for_bot(
        runs.ItemState("draft", later - timedelta(minutes=5), 1, submit=True), now=later
    )
    assert runs.due_for_bot(runs.ItemState("draft", NOW, 1, submit=True), now=later)
    assert runs.due_for_bot(runs.ItemState("retry", NOW, 1, attempts=2), now=later)
    assert not runs.due_for_bot(runs.ItemState("retry", NOW, 1, attempts=3), now=later)
    assert not runs.due_for_bot(
        runs.ItemState("retry", later - timedelta(minutes=5), 1), now=later
    )


def test_webhook_is_a_small_envelope_without_candidate_data(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://api.example")
    _, payload = _payload()
    payload["candidate"]["first_name"] = "private-candidate-marker"
    payload["offer"]["motivation"] = "private-motivation-marker " * 10000
    run, token = runs.new_run([payload], now=NOW, submit=False)
    run.id = 42
    body = runs.webhook_body(run, token)
    assert body == {
        "run_id": 42,
        "kind": "cpro_offers",
        "token": token,
        "task_url": "https://api.example/api/integrations/cpro-bot/runs/42/task",
        "schema_version": 2,
    }
    encoded = json.dumps(body, ensure_ascii=False)
    assert len(encoded.encode("utf-8")) < 512
    assert "private-candidate-marker" not in encoded
    assert "private-motivation-marker" not in encoded


def test_task_body_sends_items_with_cv_url_but_not_token_or_internal_cards(
    monkeypatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://api.example")
    _, payload = _payload()
    run, token = runs.new_run(
        [payload], now=NOW, submit=True, cards={"101": {"target_stage_def_id": 9}}
    )
    run.id = 42
    body = runs.task_body(run)
    assert (
        body["callback_url"] == "https://api.example/api/integrations/cpro-bot/runs/42"
    )
    assert body["items"][0]["offer"]["cv_url"].endswith("/runs/42/cv/101")
    assert "cards" not in body and "cards" not in body["items"][0]
    assert "token" not in body
    assert body["schema_version"] == 2
    assert body["task"] == task_text.TASK and body["submit"] is True
    assert run.stage_ids == [101]
    assert run.token_hash == runs.hash_token(token)


def test_mixed_run_keeps_a_separate_account_on_every_item() -> None:
    _, igor = _payload(stage_id=101, delivery_lead_id=14)
    _, marcin = _payload(stage_id=102, delivery_lead_id=27)
    run, token = runs.new_run([igor, marcin], now=NOW, submit=False)
    run.id = 42
    body = runs.task_body(run)
    assert body["submit"] is False
    assert [(item["ref"], item["cpro_account"]) for item in body["items"]] == [
        (
            101,
            {
                "delivery_lead_id": 14,
                "delivery_lead_name": "Igor",
                "vault_entry": "Nordea Cpro – Igor",
            },
        ),
        (
            102,
            {
                "delivery_lead_id": 27,
                "delivery_lead_name": "Marcin",
                "vault_entry": "Nordea Cpro – Marcin",
            },
        ),
    ]
    assert "cpro_account" not in body
