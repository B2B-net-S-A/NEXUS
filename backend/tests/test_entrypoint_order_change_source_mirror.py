"""Każda definicja ``ck_order_change_events_source`` w safety-necie zna źródła z modelu.

0441 (API integracyjne v1) poszerza domenę o ``integration``. Lekcja z
``ck_dl_alerts_type`` (03.09.2026): starsza, węższa definicja wykonywana PO
nowszej zwężała więz przy każdym deployu, a zielone testy tego nie widziały —
baza testowa dostaje więz z alembica, nie z entrypointu. Tu wąski więz
oznaczałby CheckViolation przy KAŻDYM zapisie zamówienia kluczem API.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.order_change_event import OrderChangeEvent

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _model_sources() -> set[str]:
    for constraint in OrderChangeEvent.__table__.constraints:
        if constraint.name == "ck_order_change_events_source":
            return set(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))
    raise AssertionError("model nie ma ck_order_change_events_source")


def test_every_entrypoint_definition_of_the_source_check_matches_the_model():
    model_sources = _model_sources()
    assert model_sources == {"user", "system", "integration"}
    source = ENTRYPOINT.read_text(encoding="utf-8")
    definitions = re.findall(
        r"ck_order_change_events_source\s+CHECK \(source IN \(([^)]*)\)\)", source
    )
    # CREATE TABLE + jawne poszerzenie w `_CONSTRAINT_STATEMENTS`.
    assert len(definitions) == 2, definitions
    for raw in definitions:
        found = set(re.findall(r"'([a-z_]+)'", raw))
        assert found == model_sources, (
            "definicja ck_order_change_events_source w entrypoint.sh rozjechała się "
            f"z modelem: brakuje {sorted(model_sources - found)}, "
            f"nadmiar {sorted(found - model_sources)}"
        )
