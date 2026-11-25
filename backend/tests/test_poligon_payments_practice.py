"""Plan przelewów na Poligonie (`scripts/poligon_payments_practice.py`).

Bez bazy. 25.11.2026 lekcja „Zajęcia i spory” była nie do zrobienia: Poligon
odpowiadał 409 na POST planu przelewów, więc przycisku „Zajęcie” nie było.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import poligon_client_practice as client
from scripts import poligon_payments_practice as pay

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "frontend/src/lib/poligon/dataset.json"


def test_zestaw_w_repo_jest_aktualny():
    data = json.loads(DATASET.read_text())
    responses, fiction = pay.payments_practice()
    for key, body in responses.items():
        assert data["responses"][key] == body, (
            f"przebuduj: python3 scripts/build_poligon_dataset.py --practice-only ({key})"
        )
    assert set(fiction) <= set(data["meta"]["fiction_responses"])


def test_faktura_kontraktora_cwiczebnego_ma_kontrakt_i_nie_trafi_do_paczki():
    (item,) = pay.payment_plan()["items"]
    # „Zajęcie” stoi tylko przy fakturze z kontraktem (`PaymentsTab.tsx`).
    assert item["contract_id"] == client.ACTIVE["contract_id"]
    assert item["seller_name"] == client.ACTIVE["name"]
    assert item["selectable"] is False and item["account"] is None
