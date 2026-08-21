"""Popup wtyczki musi czytać pola, które backend świadomie dokłada do odpowiedzi.

`assignment_skipped_reason` powstało po to, żeby „dodaj z LinkedIn" przestało
być cichym no-opem, gdy serwer zapisuje kandydata, ale NIE dopina go do
rekrutacji. Pole przeleżało nieprzeczytane w `modal-host.js`, więc pominięte
przypisanie renderowało się jako identyczny banner sukcesu. Ten test pilnuje
kierunku, w którym regresja jest cicha: schemat zostaje, a konsument znika.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.candidate import CandidateFromLinkedInResponse

_MODAL_HOST = (
    Path(__file__).resolve().parents[2] / "extension/src/content/modal-host.js"
)


def test_response_still_carries_the_skip_reason() -> None:
    assert "assignment_skipped_reason" in CandidateFromLinkedInResponse.model_fields


def test_popup_renders_the_skip_reason() -> None:
    if not _MODAL_HOST.exists():
        # Backend bywa uruchamiany z zamontowanym samym `backend/` — wtedy nie
        # ma czego sprawdzać. W CI repo jest kompletne i test biegnie.
        pytest.skip("brak drzewa extension/ w tym środowisku")
    source = _MODAL_HOST.read_text(encoding="utf-8")
    assert "assignment_skipped_reason" in source, (
        "modal-host.js przestał czytać assignment_skipped_reason — pominięte "
        "przypisanie znowu wygląda w popupie jak sukces"
    )
