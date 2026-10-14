"""Umowa API integracyjnego v1 z automatyzacjami (bez bazy).

Automatyzacje (n8n, Power Automate, Make, skrypty) budują się na kształcie
odpowiedzi v1. Trasy ekranów zmieniają się kilka razy dziennie — v1 nie może
się zmienić po cichu. Dlatego:

* snapshot specyfikacji v1 (``tests/data/integrations_v1_openapi.json``):
  każda zmiana kształtu = czerwony test i diff w PR-ze. Dodanie pola jest
  zgodne wstecz; usunięcie albo zmiana znaczenia pola = nowa wersja (v2).
  Odświeżenie: ``INTEGRATIONS_V1_SNAPSHOT_WRITE=1 python -m pytest
  tests/test_integrations_v1_contract.py``;
* każda trasa v1 ma kopertę błędu v1, bramkę klucza API i NIE zależy od
  JWT użytkownika (``get_current_user``) — inaczej klucz dziedziczyłby
  ścieżkę ekranu.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.routing import APIRoute

from app.api.integrations_v1.common import PREFIX, IntegrationRoute
from app.api.integrations_v1.meta import integrations_openapi
from app.main import app
from tests._route_introspection import iter_api_routes

SNAPSHOT = Path(__file__).parent / "data" / "integrations_v1_openapi.json"


def _v1_routes() -> list[tuple[str, APIRoute]]:
    return [
        (path, route) for path, route in iter_api_routes(app) if path.startswith(PREFIX)
    ]


def _dependency_names(dependant) -> set[str]:
    names: set[str] = set()
    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        call = dep.call
        names.add(getattr(call, "__qualname__", repr(call)))
        stack.extend(dep.dependencies)
    return names


def test_v1_spec_matches_the_snapshot() -> None:
    spec = integrations_openapi(app.openapi())
    rendered = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if os.environ.get("INTEGRATIONS_V1_SNAPSHOT_WRITE") == "1":
        SNAPSHOT.write_text(rendered, encoding="utf-8")
    assert SNAPSHOT.exists(), (
        "brak snapshotu — uruchom z INTEGRATIONS_V1_SNAPSHOT_WRITE=1"
    )
    assert rendered == SNAPSHOT.read_text(encoding="utf-8"), (
        "Kształt API v1 zmienił się. Zmiana zgodna wstecz (nowe pole, nowa trasa): "
        "odśwież snapshot (INTEGRATIONS_V1_SNAPSHOT_WRITE=1) i pokaż diff w PR-ze. "
        "Usunięcie albo zmiana znaczenia pola: to jest v2, nie v1."
    )


def test_every_v1_route_uses_the_v1_envelope_and_a_key_gate() -> None:
    routes = _v1_routes()
    assert len(routes) >= 30, "test przestał widzieć trasy v1"
    for path, route in routes:
        assert isinstance(route, IntegrationRoute), path
        names = _dependency_names(route.dependant)
        assert any("require_service_scope" in name for name in names), (path, names)
        assert not any(name.endswith("get_current_user") for name in names), (
            path,
            names,
        )
        assert not any(name.endswith("get_authenticated_user") for name in names), (
            path,
            names,
        )


def test_writes_are_documented_with_idempotency() -> None:
    """Każdy zapis v1 jest w specyfikacji — integrator wie, że potrzebuje
    ``Idempotency-Key`` (opis w ``info.description`` i w dokumentacji)."""
    spec = integrations_openapi(app.openapi())
    writes = [
        (path, method)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"post", "put", "patch"}
    ]
    assert writes, "brak zapisów w specyfikacji v1"
    assert "Idempotency-Key" in spec["info"]["description"]


def _caller(*scopes: str):
    from app.api.deps import Caller
    from app.services.service_account_auth import ServicePrincipal

    return Caller(
        service=ServicePrincipal(
            account_id=1, slug="test", key_id="v2$00", scopes=frozenset(scopes)
        )
    )


def test_md_import_rows_hide_invoice_amounts_without_amounts_read() -> None:
    """``md:read`` jest operacyjny: kwoty faktur z wierszy kosztowych, surowe
    „Uwagi” i pominięte wiersze arkusza tylko z ``amounts:read`` (przegląd
    bezpieczeństwa PR 2A)."""
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.api.integrations_v1.md import _without_amounts
    from app.schemas.md_consumption import ImportDetail, ImportRowRead

    detail = ImportDetail(
        id=1,
        period_month="2026-09",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        rows=[
            ImportRowRead(
                id=1,
                row_number=2,
                consultant_name="Osoba Testowa",
                md_reported=Decimal("3"),
                status="cost_only",
                status_label="Koszt",
                notes_raw="faktura 12 300 zł",
                invoice_amount=Decimal("12300.00"),
            )
        ],
        skipped_rows=[{"row": 5, "values": ["x", "9 999 zł"]}],
    )
    hidden = _without_amounts(detail, _caller("md:read"))
    assert hidden.rows[0].invoice_amount is None
    assert hidden.rows[0].notes_raw is None
    assert hidden.skipped_rows == []
    assert hidden.rows[0].md_reported == Decimal("3")

    shown = _without_amounts(detail, _caller("md:read", "amounts:read"))
    assert shown.rows[0].invoice_amount == Decimal("12300.00")
