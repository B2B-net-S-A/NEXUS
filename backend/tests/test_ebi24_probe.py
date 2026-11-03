"""Sonda EBI24: same liczniki, bez nazw, NIP-ów, numerów i kwot. Dane fikcyjne."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from app.services.ebi24.client import Ebi24Client
from app.services.ebi24.environment import Ebi24Config
from scripts import ebi24_probe

KSEF_NUMBER = "9876543210-20261103-A1180C0FFEE1-5C"
XML_DIR = Path(__file__).parent / "data" / "ksef" / "sales"
CONFIG = Ebi24Config(
    mode="uat",
    user_uuid="00000000-0000-4000-8000-000000000001",
    account_uuid="00000000-0000-4000-8000-000000000002",
    communication_key=base64.b64encode(bytes(range(32))).decode(),
    secret_phrase="fikcyjny-sekret",
)
SENSITIVE_ROW = {
    "_id": "DOKUMENT-1",
    "_schemaName": "INCOME_INVOICE",
    "_ksefStatus": "COMPLETED",
    "_ksefReferenceNumber": KSEF_NUMBER,
    "_origin": {
        "channel": "SELF",
        "name": "Fikcyjna Spółka",
        "officialId": "1111111111",
    },
    "_partner": {"name": "Fikcyjny Klient", "officialId": "2222222222"},
    "invoiceNumber": "FV/1/11/2026",
    "invoiceType": "INVOICE",
    "issuedDate": "2026-11-03T10:00:00.000",
    "_createdDate": "2026-11-03T10:00:00.000",
    "grossAmount": 123456,
    "paid": True,
    "paidDate": "2026-11-10",
    "customFields": {"filia": "tajna"},
    "_documentTags": ["TAG"],
    "_documentFolder": "KATALOG",
}


def test_podsumowanie_liczy_pola_bez_danych_wrazliwych() -> None:
    rows = [
        SENSITIVE_ROW,
        {
            "_schemaName": "INCOME_INVOICE",
            "_origin": {"channel": "MAILBOX"},
            "issuedDate": "2026-10-01",
            "_createdDate": "2026-10-01",
            "invoiceType": "CORRECTIVE_INVOICE",
            "paid": False,
        },
        {
            "_schemaName": "INCOME_INVOICE",
            "_ksefStatus": "tekst z <html>",
            "_createdDate": "tekst z <html>",
        },
        {"_schemaName": "INCOME_INVOICE"},
    ]

    summary = ebi24_probe.summarize(rows)

    assert summary["rows"] == 4
    assert summary["ksef_status"] == {"COMPLETED": 1, "(brak)": 2, "INNY": 1}
    assert summary["valid_ksef_number"] == 1
    assert summary["origin_channel"] == {"SELF": 1, "MAILBOX": 1, "(brak)": 2}
    assert summary["created_date_shape"] == {
        "9999-99-99T99:99:99.999": 1,
        "9999-99-99": 1,
        "INNY": 1,
        "(brak)": 1,
    }
    assert summary["invoice_type"]["CORRECTIVE_INVOICE"] == 1
    assert summary["paid_true"] == 1
    assert summary["paid_with_date"] == 1
    assert summary["issued_month"] == {"2026-10": 1, "2026-11": 1}
    assert summary["with_custom_fields"] == 1
    assert summary["with_tags"] == 1
    assert summary["with_folder"] == 1
    text = json.dumps(summary, ensure_ascii=False)
    for forbidden in (
        "Fikcyjn",
        "1111111111",
        "2222222222",
        KSEF_NUMBER,
        "FV/1",
        "123456",
        "tajna",
        "DOKUMENT-1",
    ):
        assert forbidden not in text


async def test_sonda_przechodzi_strony_i_czyta_probke_xml(monkeypatch) -> None:
    requests: list[tuple[str, dict]] = []
    xml = (XML_DIR / f"{KSEF_NUMBER}.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.path.split("/system/api/v1/")[1]
        payload = json.loads(request.content)
        requests.append((action, payload))
        if action == "bucket/getKsefData":
            return httpx.Response(
                200, headers={"content-type": "application/xml"}, content=xml
            )
        data = payload["data"]
        if data.get("_constructor") == "AdvancedCriteria":
            return httpx.Response(
                200,
                json={
                    "response": {
                        "status": 0,
                        "data": [],
                        "startRow": 0,
                        "endRow": 0,
                        "actualTotalRows": 1,
                    }
                },
            )
        rows = [SENSITIVE_ROW] if data.get("_schemaName") == "INCOME_INVOICE" else []
        start = payload["startRow"]
        return httpx.Response(
            200,
            json={
                "response": {
                    "status": 0,
                    "data": rows if start == 0 and payload["endRow"] > 1 else [],
                    "startRow": start,
                    "endRow": payload["endRow"],
                    "actualTotalRows": len(rows),
                }
            },
        )

    async def no_sleep(_seconds: float) -> None:
        return None

    async with Ebi24Client(
        CONFIG, transport=httpx.MockTransport(handler), sleep=no_sleep
    ) as client:
        report = await ebi24_probe.probe(client, max_rows=1000, xml_sample=5)

    assert report["totals"]["INCOME_INVOICE"] == 1
    assert report["totals"]["FILE"] == 0
    assert report["newest"]["INCOME_INVOICE"]["rows"] == 1
    assert report["date_filter"]["days"] == 30
    assert report["date_filter"]["date"]["accepted"] is True
    assert report["date_filter"]["datetime"]["accepted"] is True
    assert report["xml_sample"]["INCOME_INVOICE"] == {
        "ok": 1,
        "not_found": 0,
        "unreadable": 0,
    }
    # Kolejne strony muszą mieć stabilne sortowanie (zalecenie podręcznika).
    pages = [
        payload
        for action, payload in requests
        if action == "bucket/index" and payload["endRow"] > 1
    ]
    assert all(page["sortBy"] == ["-_bucketNumber"] for page in pages)
    assert all(action != "bucket/create" for action, _ in requests)
    text = json.dumps(report, ensure_ascii=False)
    assert KSEF_NUMBER not in text
    assert "Fikcyjn" not in text


async def test_format_daty_odrzucony_przez_serwer_to_wynik_a_nie_awaria() -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        criteria = payload["data"]
        total = 40
        if criteria.get("_constructor") == "AdvancedCriteria":
            created = criteria["criteria"][1]
            sent.append(created)
            if "T" in created["value"]:
                return httpx.Response(
                    200, json={"response": {"status": -1, "data": "x"}}
                )
            total = 7
        return httpx.Response(
            200,
            json={
                "response": {
                    "status": 0,
                    "data": [],
                    "startRow": 0,
                    "endRow": 0,
                    "actualTotalRows": total,
                }
            },
        )

    async def no_sleep(_seconds: float) -> None:
        return None

    async with Ebi24Client(
        CONFIG, transport=httpx.MockTransport(handler), sleep=no_sleep
    ) as client:
        report = await ebi24_probe.probe(client, max_rows=500, xml_sample=0)

    assert report["date_filter"] == {
        "days": 30,
        "date": {"accepted": True, "total": 7, "narrowed": True},
        "datetime": {"accepted": False},
    }
    assert [item["fieldName"] for item in sent] == ["_createdDate", "_createdDate"]
    assert {item["operator"] for item in sent} == {"greaterOrEqual"}


def test_wylaczona_konfiguracja_konczy_kodem_2(monkeypatch, capsys) -> None:
    disabled = Ebi24Config("off", "", "", "", "")
    monkeypatch.setattr(ebi24_probe, "load_config", lambda: disabled)

    assert ebi24_probe.main([]) == ebi24_probe.EXIT_DISABLED
    assert json.loads(capsys.readouterr().out) == {"error": "mode_off"}
