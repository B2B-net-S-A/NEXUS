"""Etykiety Traefika dla osobnych aplikacji Coolify (front B1, backend B2).

Cel Artura z 13.11.2026: zero błędów widocznych przy wdrożeniu. Rolling update
Coolify 4.5.3 startuje nowy kontener, czeka na healthcheck i ``drain`` sekund,
a potem robi ``docker stop`` starego z ``grace``. Gdy stary po SIGTERM zamknie
gniazdo, a Traefik jeszcze go ma w puli, żądanie dostaje odmowę połączenia —
middleware ``retry`` ponawia je na nowym kontenerze.

Pułapki z kodu Coolify 4.5.3 (``ApplicationsController::update_by_uuid``,
``ApplicationDeploymentJob::wait_for_proxy_to_route_new_container``):

- przy ``is_container_label_readonly_enabled=true`` Coolify przepisuje
  ``custom_labels`` z domen przy każdym PATCH domen — własne etykiety giną,
  więc po wygenerowaniu dokładamy retry i wyłączamy przepisywanie;
- gdy etykiety ``traefik.*`` starego i nowego kontenera się różnią
  (``proxyLabelsChanged``), Coolify zatrzymuje stary bez czekania — etykiety
  mają być stałe między wdrożeniami (ta funkcja jest idempotentna).
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any

# Coolify: czas na przejęcie ruchu przez nowy kontener i na dokończenie żądań starego.
SHUTDOWN_SETTINGS = {"rolling_update_drain_seconds": 10, "stop_grace_period": 30}
_ROUTER_RULE_RE = re.compile(r"traefik\.http\.routers\.([^.=]+)\.rule=")
_ROUTER_MIDDLEWARES_RE = re.compile(r"traefik\.http\.routers\.([^.=]+)\.middlewares=(.*)")


def retry_definition(middleware: str) -> tuple[str, ...]:
    return (
        f"traefik.http.middlewares.{middleware}.retry.attempts=3",
        f"traefik.http.middlewares.{middleware}.retry.initialinterval=100ms",
    )


def decode_labels(raw: Any) -> list[str]:
    """`custom_labels` z API: Coolify trzyma je raz jawnie, raz w base64."""
    text = str(raw or "")
    try:
        decoded = base64.b64decode(text, validate=True).decode("utf-8")
        if "traefik." in decoded:
            text = decoded
    except (binascii.Error, UnicodeDecodeError, ValueError):
        pass
    return [line for line in text.splitlines() if line.strip()]


def encode_labels(labels: list[str]) -> str:
    return base64.b64encode("\n".join(labels).encode("utf-8")).decode("ascii")


def with_retry(labels: list[str], middleware: str) -> list[str]:
    """Etykiety wygenerowane przez Coolify + retry na początku łańcucha każdego routera."""
    routers = list(dict.fromkeys(m.group(1) for m in map(_ROUTER_RULE_RE.match, labels) if m))
    if not routers:
        raise ValueError("etykiety aplikacji nie mają routerów — domeny nie zapisane?")
    out, chained = [], set()
    for line in labels:
        match = _ROUTER_MIDDLEWARES_RE.fullmatch(line)
        if match:
            chained.add(match.group(1))
            names = [name for name in match.group(2).split(",") if name]
            if middleware not in names:
                names.insert(0, middleware)
            line = f"traefik.http.routers.{match.group(1)}.middlewares={','.join(names)}"
        out.append(line)
    out += [f"traefik.http.routers.{r}.middlewares={middleware}" for r in routers if r not in chained]
    return out + [label for label in retry_definition(middleware) if label not in out]
