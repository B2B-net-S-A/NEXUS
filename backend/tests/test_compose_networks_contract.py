"""Sieci compose, które Coolify 4.5.3 faktycznie podłącza.

Coolify nie przenosi sieci z najwyższego poziomu compose do usług
(`parsers.php:1735` wstawia `null`, `:1775` bierze tylko napis i tablicę), więc
usługa bez jawnego `networks:` po cichu nie ma sieci, którą widać w pliku.
13.11.2026 front po przepięciu nie widział `backend:8000` (#3389). Etap B2:
osobne aplikacje backendu i workera potrzebują tak samo `postgres` i `qdrant`.
→ docs/claude/podstawy/nakladanie-kontenerow-backendu.md („Sieci”)
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
SHARED_NETWORK = "nexus-front"
# Usługi, do których łączy się aplikacja spoza compose'a (front, a od części 2
# etapu B2 także backend i worker — wtedy dochodzą tu `postgres` i `qdrant`).
REACHABLE_FROM_OTHER_APPS = {"backend"}


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _service_networks(service: dict) -> dict[str, object]:
    networks = service.get("networks") or []
    if isinstance(networks, list):
        return {name: {} for name in networks}
    return dict(networks)


def test_every_top_level_network_is_named_in_a_service() -> None:
    compose = _compose()
    services = compose.get("services") or {}
    used = {name for svc in services.values() for name in _service_networks(svc)}
    unused = sorted(set(compose.get("networks") or {}) - used)
    assert not unused, (
        f"sieci {unused} są tylko na najwyższym poziomie compose'a; Coolify 4.5.3 "
        "nie dopisze ich do usług — wpisz je w `networks:` usługi"
    )


def test_services_reached_from_other_apps_join_the_shared_network() -> None:
    services = _compose().get("services") or {}
    missing = sorted(
        name
        for name in REACHABLE_FROM_OTHER_APPS
        if SHARED_NETWORK not in _service_networks(services.get(name) or {})
    )
    assert not missing, f"{missing} bez jawnego `networks: [{SHARED_NETWORK}]`"


def test_service_networks_in_map_form_are_not_null() -> None:
    """`nexus-front:` bez wartości to `null` — ten sam kształt, który Coolify gubi."""
    services = _compose().get("services") or {}
    nulls = sorted(
        f"{name}.{net}"
        for name, svc in services.items()
        if isinstance(svc.get("networks"), dict)
        for net, value in svc["networks"].items()
        if value is None
    )
    assert not nulls, f"{nulls}: użyj listy `- {SHARED_NETWORK}` albo mapy z wartością"


@pytest.mark.parametrize(
    ("networks", "expected"),
    [
        (["a", "b"], {"a": {}, "b": {}}),
        ({"a": {"aliases": ["x"]}}, {"a": {"aliases": ["x"]}}),
        (None, {}),
    ],
)
def test_service_networks_reader(networks: object, expected: dict) -> None:
    assert _service_networks({"networks": networks}) == expected
