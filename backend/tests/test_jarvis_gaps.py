"""„Tego nie zrobię” (27.10.2026): karta braku, zgłoszenie i lista dla admina.

Ludzie mówili, że Jarvis „nic nie wie”: odpowiadał „nie ma”, gdy rola nie
widziała klientów, albo kończył na „nie mogę”. Teraz woła ``report_gap``:
karta mówi, czego brakuje i co zrobić, a „Zgłoś” trafia na listę admina.
Pętla przez prawdziwą aplikację, model podmieniony — jak ``test_jarvis_help_mode``.
"""

from __future__ import annotations

import pytest

from app.models.user import UserRole
from tests._jarvis_helpers import (
    ScriptedModel,
    enable_jarvis,
    fake_message,
    make_user,
    parse_sse,
    text_block,
    tool_block,
)

pytestmark = pytest.mark.asyncio

_GAP = {
    "kind": "no_access",
    "need": "kto jest Delivery Leadem klienta",
    "why": "Rola rekrutera nie widzi klientów.",
    "workaround": "Zapytaj Head of Recruitment.",
}


async def _gap_turn(app_client, monkeypatch, gap=None):
    model = ScriptedModel(
        [
            fake_message(tool_block("report_gap", gap or _GAP, "toolu_gap")),
            fake_message(text_block("Mogę sprawdzić rekrutacje tego klienta.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    resp = await app_client.post(
        "/api/jarvis/chat", json={"message": "kto jest DL?"}, headers=headers
    )
    return model, headers, parse_sse(resp.text)


async def test_gap_card_is_streamed_saved_and_rebuilt(app_client, monkeypatch):
    _model, headers, events = await _gap_turn(app_client, monkeypatch)
    gaps = [e["gap"] for e in events if e["type"] == "gap"]
    assert len(gaps) == 1
    assert {k: gaps[0][k] for k in ("kind", "need", "why", "workaround")} == _GAP
    assert gaps[0]["reported"] is False

    detail = await app_client.get(
        f"/api/jarvis/conversations/{events[0]['conversation_id']}", headers=headers
    )
    rebuilt = [i["gap"] for i in detail.json()["items"] if i["kind"] == "gap"]
    assert rebuilt == gaps


async def test_gap_without_reason_goes_back_to_the_model(app_client, monkeypatch):
    model, _headers, events = await _gap_turn(
        app_client, monkeypatch, {"kind": "no_access", "need": "x", "why": ""}
    )
    assert not [e for e in events if e["type"] == "gap"]
    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True


async def test_report_is_owner_only_and_reaches_the_admin_list(
    app_client, monkeypatch, app_auth_headers
):
    _model, headers, events = await _gap_turn(app_client, monkeypatch)
    gap_id = next(e["gap"]["id"] for e in events if e["type"] == "gap")

    _, stranger = await make_user(UserRole.recruiter)
    denied = await app_client.post(
        f"/api/jarvis/gaps/{gap_id}/report", headers=stranger
    )
    assert denied.status_code == 404

    for _ in range(2):  # idempotentnie
        ok = await app_client.post(f"/api/jarvis/gaps/{gap_id}/report", headers=headers)
        assert ok.status_code == 204, ok.text

    forbidden = await app_client.get("/api/jarvis/gaps", headers=headers)
    assert forbidden.status_code == 403
    listing = await app_client.get("/api/jarvis/gaps", headers=app_auth_headers)
    assert listing.status_code == 200, listing.text
    row = next(i for i in listing.json()["items"] if i["id"] == gap_id)
    assert row["reported"] is True
    assert row["role"] == "recruiter"
    assert "name" not in row and "user_id" not in row


async def test_status_lists_what_this_role_can_do(app_client, monkeypatch):
    enable_jarvis(monkeypatch, ScriptedModel([]))
    _, headers = await make_user(UserRole.recruiter)
    resp = await app_client.get("/api/jarvis/status", headers=headers)
    assert resp.status_code == 200, resp.text
    caps = resp.json()["capabilities"]
    assert "przesunięcie na tablicy" in caps["write"]
    assert "klienci, kontrakty i zamówienia" not in caps["read"]
    assert "wysyłka maila" in caps["never"]
