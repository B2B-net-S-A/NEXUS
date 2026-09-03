"""Każda definicja ``ck_dl_alerts_type`` w safety-necie musi znać typy z modelu.

Incydent 03.09.2026: safety-net miał DWIE definicje tej domeny w jednej liście —
lustro 0265 (z ``order_mail_review``) i starszy blok atomowy bez niego, wykonywany
PÓŹNIEJ. Każdy deploy zwężał więz z powrotem, więc alert „zamówienie z maila do
weryfikacji" nigdy nie dał się zapisać na produkcji, a błąd wychodził dopiero
jako ``CheckViolationError`` w ``notify_review``. Zielone testy nie mogły tego
złapać: baza testowa dostaje więz z alembica, nie z entrypointu.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.dl_alert import DlAlert

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _model_types() -> set[str]:
    for constraint in DlAlert.__table__.constraints:
        if constraint.name == "ck_dl_alerts_type":
            return set(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))
    raise AssertionError("model nie ma ck_dl_alerts_type")


def test_every_entrypoint_definition_of_the_type_check_matches_the_model():
    model_types = _model_types()
    assert "order_mail_review" in model_types
    source = ENTRYPOINT.read_text(encoding="utf-8")
    definitions = re.findall(
        r"ck_dl_alerts_type CHECK \(alert_type IN \(([^)]*)\)", source
    )
    assert definitions, "safety-net nie definiuje ck_dl_alerts_type"
    for raw in definitions:
        found = set(re.findall(r"'([a-z_]+)'", raw))
        assert found == model_types, (
            "definicja ck_dl_alerts_type w entrypoint.sh rozjechała się z modelem: "
            f"brakuje {sorted(model_types - found)}, nadmiar {sorted(found - model_types)}"
        )
