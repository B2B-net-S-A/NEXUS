"""Źródło „Microsoft Defender” bez bazy: parser odpowiedzi Graph, scrub, wagi,
zamykanie, dzwonek i bezpieczeństwo odczytu (link, nextLink, opis błędu).

Dane fikcyjne: ``tests/data/security/defender_*_example.json`` (example.com,
adresy z zakresów dokumentacyjnych).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.services import security_defender as d
from app.services.m365 import defender_auth
from app.services.security_ingest import IngestFinding

DATA = Path(__file__).resolve().parent / "data" / "security"
INCIDENTS = json.loads((DATA / "defender_incidents_example.json").read_text())
SCORE = json.loads((DATA / "defender_secure_score_example.json").read_text())

# Wartości z przykładu, które nie mogą trafić do bazy ani na ekran.
PRIVATE = (
    "osoba@example.com",
    "analityk@example.com",
    "Osoba Przykładowa",
    "203.0.113.7",
    "198.51.100.20",
    "192.0.2.15",
    "laptop-01",
    "Faktura do zapłaty",
    "tenant-fikcyjny",
    "osoba-fikcyjna-id",
    "Opis",
)


def _parsed() -> d.DefenderParsed:
    return d.parse_incidents(INCIDENTS["value"])


def test_open_incidents_become_findings_with_incident_id_as_fingerprint() -> None:
    parsed = _parsed()
    by_fp = {f.fingerprint: f for f in parsed.open_findings}
    assert set(by_fp) == {"101", "102"}
    assert by_fp["101"].severity == "high"
    assert by_fp["102"].severity == "info"
    assert by_fp["101"].detected_at == datetime(
        2026, 11, 22, 9, 14, 55, 123456, tzinfo=timezone.utc
    )
    assert by_fp["101"].steps == d.STEPS


def test_resolved_and_redirected_incidents_close() -> None:
    parsed = _parsed()
    assert parsed.resolved == ["103", "104"]
    assert {f.fingerprint for f in parsed.open_findings}.isdisjoint(parsed.resolved)


def test_id_outside_pattern_is_skipped() -> None:
    parsed = _parsed()
    assert parsed.skipped == 1
    assert all(".." not in ref for ref in parsed.links)


def test_title_is_scrubbed_of_upn_and_ip() -> None:
    title = {f.fingerprint: f for f in _parsed().open_findings}["101"].title
    assert title == "Password Spray i nietypowe logowanie dla [e-mail] z [adres IP]"


def test_evidence_is_category_and_resource_counts_without_values() -> None:
    by_fp = {f.fingerprint: f for f in _parsed().open_findings}
    assert by_fp["101"].evidence == (
        "Kategoria: dostęp do poświadczeń, wstępny dostęp · alerty: 2 · "
        "zasoby: 3 (adres IP 2, konto 1) · nieprzypisany"
    )
    assert by_fp["102"].evidence == (
        "Kategoria: zarządzanie zagrożeniem · alerty: 1 · "
        "zasoby: 3 (skrzynka 1, wiadomość 2) · przypisany"
    )
    assert by_fp["101"].location == "Entra ID Protection"
    assert d.incident_location({"alerts": []}) == "Defender XDR"


def test_nothing_private_leaves_the_parser() -> None:
    parsed = _parsed()
    blob = json.dumps(
        [f.model_dump(mode="json") for f in parsed.open_findings]
        + [e.model_dump(mode="json") for e in parsed.events]
        + list(parsed.links.values()),
        ensure_ascii=False,
    )
    for value in PRIVATE:
        assert value not in blob, value


def test_events_once_per_incident_and_state_with_portal_links() -> None:
    parsed = _parsed()
    refs = [e.ref for e in parsed.events]
    assert refs == [
        "defender:101:open",
        "defender:102:open",
        "defender:103:open",
        "defender:103:resolved",
        "defender:104:open",
        "defender:104:resolved",
    ]
    resolved = next(e for e in parsed.events if e.ref == "defender:103:resolved")
    assert resolved.kind == "incident_resolved" and resolved.severity == "info"
    assert parsed.links["defender:101:open"] == (
        "https://security.microsoft.com/incidents/101"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("informational", "info"),
        ("low", "low"),
        ("Medium", "medium"),
        ("high", "high"),
        ("critical", "critical"),
        ("unknownFutureValue", "medium"),
        (None, "medium"),
    ],
)
def test_severity_mapping(raw: object, expected: str) -> None:
    assert d.defender_severity(raw) == expected


def test_incident_url_never_carries_tenant_or_foreign_path() -> None:
    assert d.incident_url("854") == "https://security.microsoft.com/incidents/854"
    assert d.incident_url("../admin") is None
    assert d.incident_url("1?tid=x") is None
    assert d.finding_link("defender", "854") == d.incident_url("854")
    assert d.finding_link("grafana", "854") is None


def test_secure_score_as_percent() -> None:
    assert d.secure_score_percent(SCORE) == {"percent": 69.45, "on": "2026-11-28"}
    assert d.secure_score_percent({"value": []}) is None
    assert (
        d.secure_score_percent({"value": [{"currentScore": 1, "maxScore": 0}]}) is None
    )


def _finding(severity: str) -> IngestFinding:
    return IngestFinding(fingerprint="1", severity=severity, title="x")


@pytest.mark.parametrize(
    ("severity", "before", "rings"),
    [
        ("high", None, True),
        ("critical", None, True),
        ("medium", None, False),
        ("high", ("open", "high"), False),
        ("high", ("excepted", "high"), False),
        ("high", ("fixed", "high"), True),
        ("high", ("open", "medium"), True),
        ("low", ("fixed", "low"), False),
    ],
)
def test_bell_only_for_new_reopened_or_raised_high(
    severity: str, before: tuple[str, str] | None, rings: bool
) -> None:
    assert d.needs_bell(_finding(severity), before) is rings


def test_filters_cover_open_states_and_thirty_days() -> None:
    now = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
    assert d.incident_filters(now) == [
        "status eq 'active'",
        "status eq 'inProgress'",
        "status eq 'awaitingAction'",
        "lastUpdateDateTime ge 2026-10-29T12:00:00Z",
    ]


def test_error_label_has_no_response_body() -> None:
    request = httpx.Request(
        "GET", "https://graph.microsoft.com/v1.0/security/incidents"
    )
    response = httpx.Response(403, request=request, text="tenant 0000 secret details")
    exc = httpx.HTTPStatusError("x", request=request, response=response)
    assert d.error_label(exc) == "HTTP 403"
    assert d.error_label(defender_auth.DefenderTokenError("invalid_client")) == (
        "token: invalid_client"
    )


def _graph(handler) -> d._Graph:
    graph = d._Graph(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    graph.token = "test-token"
    return graph


async def test_pages_follow_next_link_only_to_graph() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "skiptoken" in str(request.url):
            return httpx.Response(200, json={"value": [{"id": "2"}]})
        return httpx.Response(
            200,
            json={
                "value": [{"id": "1"}],
                "@odata.nextLink": f"{d.GRAPH}/security/incidents?$skiptoken=a",
            },
        )

    rows, complete = await _graph(handler).pages(f"{d.GRAPH}/security/incidents", {})
    assert [r["id"] for r in rows] == ["1", "2"] and complete is True

    def evil(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"value": [], "@odata.nextLink": "https://attacker.example/steal"}
        )

    with pytest.raises(d.DefenderReadError):
        await _graph(evil).pages(f"{d.GRAPH}/security/incidents", {})


async def test_page_cap_marks_read_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "MAX_PAGES", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [{"id": "1"}],
                "@odata.nextLink": f"{d.GRAPH}/security/incidents?$skiptoken=n",
            },
        )

    _, complete = await _graph(handler).pages(f"{d.GRAPH}/security/incidents", {})
    assert complete is False


async def test_401_refreshes_token_once(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = iter(["old", "new"])
    monkeypatch.setattr(
        defender_auth,
        "acquire_defender_token",
        lambda force_refresh=False: next(tokens),
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer old":
            return httpx.Response(401)
        return httpx.Response(200, json={"value": []})

    graph = d._Graph(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await graph.get(f"{d.GRAPH}/security/secureScores") == {"value": []}
    assert seen == ["Bearer old", "Bearer new"]


async def test_without_registration_sync_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(defender_auth.settings, "DEFENDER_CLIENT_ID", "")
    monkeypatch.setattr(defender_auth.settings, "DEFENDER_CLIENT_SECRET", "")
    result = await d.sync_defender(None, None)  # type: ignore[arg-type]
    assert result == d.DefenderSyncResult(configured=False)


def test_common_tenant_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    s = defender_auth.settings
    monkeypatch.setattr(s, "DEFENDER_CLIENT_ID", "id")
    monkeypatch.setattr(s, "DEFENDER_CLIENT_SECRET", "secret")
    monkeypatch.setattr(s, "DEFENDER_TENANT_ID", "common")
    assert defender_auth.credentials_configured() is False
    monkeypatch.setattr(s, "DEFENDER_TENANT_ID", "example.onmicrosoft.com")
    assert defender_auth.credentials_configured() is True
