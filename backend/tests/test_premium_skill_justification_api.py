"""„Zaproponuj uzasadnienie” (F5): atrapa modelu, odmowa i błąd. Dane fikcyjne, bez sieci."""

from __future__ import annotations

from httpx import AsyncClient

from app.services import premium_skill_justification as justification
from tests.test_framework_rates_api import _headers, _seed
from tests.test_premium_skills_api import _with_skills_and_card


async def _open_claim(app_client: AsyncClient, note: str | None = None):
    client_id, contract_id, senior_id = await _seed()
    await _with_skills_and_card(contract_id, senior_id)
    dl = await _headers(app_client, "delivery_lead", assigned_client_id=client_id)
    await app_client.put(
        f"/api/contracts/{contract_id}/framework-category",
        headers=dl,
        json={"rate_card_id": senior_id},
    )
    base = f"/api/contracts/{contract_id}/premium-skills/claims"
    claim = (
        await app_client.post(
            base,
            headers=dl,
            json={"technology": "Kafka", "knows": True, "uses": True, "note": note},
        )
    ).json()["claims"][0]
    return client_id, contract_id, dl, f"{base}/{claim['id']}"


async def test_draft_comes_from_the_model_without_name_client_or_rate(
    app_client: AsyncClient, monkeypatch
):
    _, _, dl, claim_url = await _open_claim(
        app_client, note="Ola codziennie utrzymuje strumienie płatności."
    )
    prompts: list[str] = []

    def fake_model(chain, prompt):
        prompts.append(prompt)
        return (
            "Here is the justification:\nKafka is used every day on this assignment "
            "for 5 years. Please include Kafka and apply the 20% adder."
        )

    monkeypatch.setattr(justification, "call_model", fake_model)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda _model: True
    )
    res = await app_client.post(f"{claim_url}/justification-draft", headers=dl)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["model_used"] is True and body["message"] is None
    assert body["text"].startswith("Kafka is used every day")
    assert any("(5)" in w for w in body["warnings"])
    (prompt,) = prompts
    assert "Kafka" in prompt and "20%" in prompt and "IT Developer - Senior" in prompt
    assert "the consultant codziennie" in prompt
    for absent in ("Ola", "Testowa", "Bank Ramowy", "115"):
        assert absent not in prompt


async def test_no_key_means_template_and_a_polish_message(
    app_client: AsyncClient, monkeypatch
):
    _, _, dl, claim_url = await _open_claim(app_client)
    called: list[object] = []
    monkeypatch.setattr(justification, "call_model", lambda *a: called.append(a))
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda _model: False
    )
    res = await app_client.post(f"{claim_url}/justification-draft", headers=dl)
    assert res.status_code == 200
    assert res.json() == {
        "text": None,
        "model_used": False,
        "warnings": [],
        "message": "Model AI nie jest teraz dostępny — popraw szablon uzasadnienia albo napisz je sam.",
    }
    assert called == []


async def test_model_error_or_empty_answer_falls_back_to_the_template(
    app_client: AsyncClient, monkeypatch
):
    _, _, dl, claim_url = await _open_claim(app_client)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda _model: True
    )

    def broken(chain, prompt):
        raise RuntimeError("provider down")

    monkeypatch.setattr(justification, "call_model", broken)
    res = await app_client.post(f"{claim_url}/justification-draft", headers=dl)
    assert res.status_code == 200
    assert res.json()["text"] is None
    assert res.json()["message"].startswith("Nie udało się przygotować szkicu")

    monkeypatch.setattr(justification, "call_model", lambda chain, prompt: "  ")
    empty = await app_client.post(f"{claim_url}/justification-draft", headers=dl)
    assert empty.json()["text"] is None and empty.json()["model_used"] is False


async def test_closed_claim_and_other_delivery_lead_are_refused(
    app_client: AsyncClient, monkeypatch
):
    _, contract_id, dl, claim_url = await _open_claim(app_client)
    monkeypatch.setattr(justification, "call_model", lambda *a: "Kafka daily.")
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda _model: True
    )
    other = await _headers(
        app_client, "delivery_lead", assigned_client_id=(await _seed())[0]
    )
    assert (
        await app_client.post(f"{claim_url}/justification-draft", headers=other)
    ).status_code == 403
    missing = await app_client.post(
        f"/api/contracts/{contract_id}/premium-skills/claims/999999/justification-draft",
        headers=dl,
    )
    assert missing.status_code == 404

    await app_client.post(f"{claim_url}/action", headers=dl, json={"action": "drop"})
    closed = await app_client.post(f"{claim_url}/justification-draft", headers=dl)
    assert closed.status_code == 422 and "zamknięty" in closed.json()["detail"]
