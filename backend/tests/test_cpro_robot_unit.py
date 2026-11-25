"""Robot Cpro (``cpro_robot``): reguły, kontrola wejścia, pobudka. Bez bazy i przeglądarki."""

from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer

import pytest

from app.core.config import settings
from app.models.cpro_bot import CproBotRun
from app.services.cpro_bot import accounts, runs, task_text
from cpro_robot import nexus, rules, server

ORIGIN = "https://api.nexus.dynaminds.pl"
ENV = {
    "CPRO_ROBOT_IGOR_USERNAME": "u1",
    "CPRO_ROBOT_IGOR_PASSWORD": "p1",
    "CPRO_ROBOT_IGOR_DISPLAY_NAME": "I. Kowal",
    "CPRO_ROBOT_MARCIN_USERNAME": "u2",
    "CPRO_ROBOT_MARCIN_PASSWORD": "p2",
    "CPRO_ROBOT_MARCIN_DISPLAY_NAME": "M. Nowak",
}


def test_account_constants_match_backend():
    assert rules.IGOR_HINT == accounts.IGOR_HINT
    assert rules.MARCIN_HINT == accounts.MARCIN_HINT
    assert rules.SUBCONTRACTOR_COMPANY == task_text.SUBCONTRACTOR_COMPANY
    assert (nexus.KIND, nexus.SCHEMA_VERSION) == (runs.KIND, runs.SCHEMA_VERSION)


@pytest.mark.parametrize(
    ("dl", "entry", "key"),
    [
        (14, accounts.IGOR_HINT, "IGOR"),
        (27, accounts.MARCIN_HINT, "MARCIN"),
        (32, accounts.MARCIN_HINT, "MARCIN"),
    ],
)
def test_account_by_delivery_lead(dl, entry, key):
    account = rules.account_for({"delivery_lead_id": dl, "vault_entry": entry}, ENV)
    assert account.key == key


@pytest.mark.parametrize(
    "cpro_account",
    [
        None,
        {"delivery_lead_id": 99, "vault_entry": accounts.IGOR_HINT},
        {
            "delivery_lead_id": 14,
            "vault_entry": accounts.MARCIN_HINT,
        },  # wpis nie z tej trasy
        {"delivery_lead_id": "14", "vault_entry": accounts.IGOR_HINT},
    ],
)
def test_account_refused_without_guessing(cpro_account):
    with pytest.raises(rules.AccountProblem) as exc:
        rules.account_for(cpro_account, ENV)
    assert exc.value.reason == "account_unknown"


def test_account_missing_credentials_is_unknown():
    env = {k: v for k, v in ENV.items() if not k.endswith("MARCIN_PASSWORD")}
    with pytest.raises(rules.AccountProblem):
        rules.account_for(
            {"delivery_lead_id": 32, "vault_entry": accounts.MARCIN_HINT}, env
        )


def test_same_person_ignores_case_accents_and_commas():
    assert rules.same_person(" Paweł  Żółć, ", "pawel", "zolc")
    assert not rules.same_person("Paweł Żółćek", "Paweł", "Żółć")


def test_offer_rows_from_list():
    cells = [
        "X Y",
        "2026-11-10",
        "Nordea Bank Abp",
        "42283 Replacement- PL",
        "Jan Kowalski",
        "163,00 PLN",
        "N/A",
        "DRAFT",
        "In Progress",
    ]
    row = rules.offer_row(
        cells,
        "https://nordea.onevms.se/nordea/vendor/OfferController?action=view&offer&id=161330",
    )
    assert row == rules.OfferRow(161330, "42283", "Jan Kowalski", "DRAFT")
    assert rules.is_draft(row)
    other = rules.OfferRow(1, "42284", "Jan Kowalski", "Selection")
    assert rules.offers_of([row, other], "42283", "Jan", "Kowalski") == [row]
    assert rules.offer_row(cells[:5], None) is None


@pytest.mark.parametrize(
    ("citizenship", "expected"),
    [("Poland", "10"), ("PL", "10"), ("Ukranie", "31"), ("Narnia", None), ("", None)],
)
def test_country_option(citizenship, expected):
    options = [
        ("0", "--- Select a value ---"),
        ("10", "PL - Poland"),
        ("72", "BY - Belarus"),
        ("31", "UA - Ukranie"),
    ]
    assert rules.country_option(options, citizenship) == expected


def test_cv_label_and_former_and_closed():
    assert rules.cv_label_matches(
        "B2B_Java Dev_Jan Kowalski", "B2B_Java Dev_Jan Kowalski.pdf"
    )
    assert not rules.cv_label_matches(
        "B2B_Java Dev_Jan Kowalski_old", "B2B_Java Dev_Jan Kowalski.pdf"
    )
    assert rules.former_from_cv_text("Bank Pekao 2019-2024") == (False, False)
    assert rules.former_from_cv_text("Nordea Bank, Gdynia") is None
    assert rules.request_closed("Request: X (42283) CLOSED Nordea Bank Abp")
    assert not rules.request_closed("Request: X (42283) IN PROGRESS")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/api/integrations/cpro-bot/runs/7/task",
        "http://api.nexus.dynaminds.pl/api/integrations/cpro-bot/runs/7/task",
        "https://u:p@api.nexus.dynaminds.pl/api/integrations/cpro-bot/runs/7/task",
        "https://api.nexus.dynaminds.pl/api/integrations/cpro-bot/runs/7/task?x=1",
        "https://api.nexus.dynaminds.pl/api/integrations/cpro-bot/runs/8/task",
        "https://api.nexus.dynaminds.pl.evil.example/api/integrations/cpro-bot/runs/7/task",
    ],
)
def test_token_never_leaves_the_run(url):
    with pytest.raises(nexus.TaskRejected):
        nexus.check_url(url, ORIGIN, "/api/integrations/cpro-bot/runs/7/task")


def _run_with_item(run_id: int = 7) -> CproBotRun:
    now = datetime.now(UTC)
    run = CproBotRun(
        id=run_id,
        status="started",
        submit=False,
        stage_ids=[123],
        request={
            "items": [
                {"ref": 123, "request_number": "42283", "offer": {"cv_format": "pdf"}}
            ]
        },
        token_expires_at=now + timedelta(hours=2),
    )
    return run


def test_backend_wake_and_task_pass_robot_checks():
    """Kontrakt: to, co NEXUS wysyła rutynie, robot przyjmuje bez zmian."""

    run = _run_with_item()
    origin = settings.PUBLIC_API_BASE_URL.rstrip("/")
    wake = nexus.parse_wake(runs.webhook_body(run, "tok"), origin)
    assert (wake.run_id, wake.token) == (7, "tok")
    task = json.loads(json.dumps(runs.task_body(run)))
    assert nexus.check_task(task, wake, origin)["items"][0]["ref"] == 123


def test_task_of_other_run_or_incomplete_is_rejected():
    run = _run_with_item()
    origin = settings.PUBLIC_API_BASE_URL.rstrip("/")
    wake = nexus.parse_wake(runs.webhook_body(run, "tok"), origin)
    task = json.loads(json.dumps(runs.task_body(run)))
    with pytest.raises(nexus.TaskRejected):
        nexus.check_task({**task, "run_id": 8}, wake, origin)
    with pytest.raises(nexus.TaskRejected):
        nexus.check_task({**task, "items": []}, wake, origin)
    bad = json.loads(json.dumps(task))
    bad["items"][0]["offer"]["cv_url"] = "https://evil.example/cv.pdf"
    with pytest.raises(nexus.TaskRejected):
        nexus.check_task(bad, wake, origin)


def test_item_without_known_account_is_skipped_before_portal():
    item = {
        "ref": 5,
        "cpro_account": {"delivery_lead_id": 99, "vault_entry": "x"},
        "offer": {},
    }
    report = server.process_item(item, "tok", False, browser=None, env=ENV)
    assert report == {
        "ref": 5,
        "outcome": "skipped",
        "reason": "account_unknown",
        "message": report["message"],
    }


@pytest.fixture
def wake_server():
    jobs: queue.Queue = queue.Queue()
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), server.make_handler("klucz", ORIGIN, jobs)
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", jobs
    httpd.shutdown()


def _post(url: str, body: dict, key: str) -> int:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_wake_needs_key_and_valid_body(wake_server):
    base, jobs = wake_server
    body = {
        "schema_version": 2,
        "kind": "cpro_offers",
        "run_id": 7,
        "token": "tok",
        "task_url": f"{ORIGIN}/api/integrations/cpro-bot/runs/7/task",
    }
    assert _post(f"{base}/wake", body, "zly") == 401
    assert (
        _post(f"{base}/wake", {**body, "task_url": "https://evil.example/x"}, "klucz")
        == 400
    )
    assert jobs.empty()
    assert _post(f"{base}/wake", body, "klucz") == 202
    assert jobs.get_nowait().run_id == 7


def test_dry_run_stops_before_any_portal_write():
    from cpro_robot.portal import ItemRun, Outcome

    item = {"candidate": {}, "offer": {}, "request_number": "42283"}
    account = rules.Account("IGOR", "u", "p", "I. Kowal")
    run = ItemRun(
        None, server.PORTAL_BASE, item, account, b"%PDF-", False, dry_run=True
    )
    for step in (run.add_consultant, run.upload_cv, run.save_draft):
        with pytest.raises(Outcome) as exc:
            step()
        assert (exc.value.outcome, exc.value.reason) == ("failed", "other")
        assert "nic nie zmienił" in exc.value.message


def test_submit_run_is_refused_by_robot():
    from cpro_robot.portal import ItemRun, Outcome

    item = {"candidate": {}, "offer": {}, "request_number": "42283"}
    run = ItemRun(
        None, server.PORTAL_BASE, item, rules.Account("IGOR", "u", "p", "x"), b"", True
    )
    with pytest.raises(Outcome) as exc:
        run.run()
    assert exc.value.outcome == "failed"


def test_saved_values_must_match_the_order():
    view = "Offered rate 196,00 PLN ... Available from 2026-12-04"
    assert rules.rate_label("196") == "196,00"
    assert rules.rate_label("163.5") == "163,50"
    assert rules.saved_values_visible(view, "196", "2026-12-04")
    assert not rules.saved_values_visible(view, "195", "2026-12-04")
    assert not rules.saved_values_visible(view, "196", "2026-12-05")


@pytest.mark.parametrize(
    ("citizenship", "expected"),
    [
        ("Amerykanin", "200"),
        ("amerykańskie", "200"),
        ("Ukrainka", "31"),
        ("ukraińskie", "31"),
        ("Białorusin", "72"),
        ("Polak", "10"),
        ("polskie", "10"),
        ("Poland", "10"),
        ("Marsjanin", None),
    ],
)
def test_country_from_polish_nationality(citizenship, expected):
    options = [
        ("0", "--- Select a value ---"),
        ("10", "PL - Poland"),
        ("72", "BY - Belarus"),
        ("31", "UA - Ukranie"),
        ("200", "US - USA"),
        ("201", "UY - Uruguay"),
    ]
    assert rules.country_option(options, citizenship) == expected


def test_error_hint_drops_quoted_values():
    exc = TimeoutError(
        'Locator.fill: Timeout 30000ms exceeded.\nCall log:\n  - fill("tajne-haslo")'
    )
    hint = server.error_hint(exc)
    assert hint.startswith("TimeoutError: Locator.fill: Timeout 30000ms exceeded.")
    assert "tajne" not in hint
    assert "tajne" not in server.error_hint(ValueError("bad value 'tajne-haslo' x"))


def test_save_draft_button_never_picks_submit():
    pick = rules.save_draft_button
    assert (
        pick(
            [
                {"name": "BUT_SaveAndSubmit", "label": "Save and submit"},
                {"name": "BUT_SaveAsDraft", "label": ""},
            ]
        )
        == 1
    )
    # input bez nazwy, sam napis
    assert (
        pick(
            [{"name": "", "label": "Cancel"}, {"name": "", "label": " Save as draft "}]
        )
        == 1
    )
    assert (
        pick([{"name": "", "label": "Save and submit"}, {"name": "", "label": "Save"}])
        is None
    )
    assert pick([{"name": "BUT_Submit", "label": "Save as draft"}]) is None
    assert pick([]) is None
