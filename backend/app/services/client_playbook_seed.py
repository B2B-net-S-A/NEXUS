"""Wczytanie seeda kart klienta (``client_playbooks``) w runtime.

Źródło prawdy to ``app/data/client_playbooks/seed.json`` — treść dawnych 14
wzorów „Profil Championa" per klient. Ten sam plik zasiewa migracja 0272 i
lustro w ``entrypoint.sh`` (``_read_playbook_seed``). Tutaj czytamy go, żeby
backfill (``POST /clients/{id}/playbook/seed``) mógł przypisać GOTOWĄ treść
seeda klientowi, którego wzorzec nazwy pasował do WIĘCEJ niż jednego żywego
rekordu (rodziny BNP/PKO/Bank Pocztowy) i dlatego automatyczny seed 0272 go
pominął (wstawia wyłącznie przy DOKŁADNIE jednym trafieniu).

Dwie ścieżki jak w entrypoincie: obraz montuje kod pod ``/app/app/...``, a dev
uruchamia z ``backend/`` (``cwd/app/...``). Brak pliku albo zepsuty JSON daje
pustą listę, nie wyjątek — endpoint odpowie wtedy czytelnym 400, a nie 500.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

_SEED_DIRS: tuple[str, ...] = (
    "/app/app/data/client_playbooks",
    os.path.join(os.getcwd(), "app", "data", "client_playbooks"),
    # Względem tego pliku — działa niezależnie od cwd (CI/testy uruchamiane
    # spoza `backend/`); `parents[1]` == `backend/app`.
    str(pathlib.Path(__file__).resolve().parents[1] / "data" / "client_playbooks"),
)


def load_playbook_seed() -> list[dict[str, Any]]:
    """Wpisy seeda albo pusta lista (nieczytelny plik nie wywala serwera)."""
    for base in _SEED_DIRS:
        path = os.path.join(base, "seed.json")
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(data, list):
            return [entry for entry in data if isinstance(entry, dict)]
    return []


def seed_entry(seed_key: str) -> dict[str, Any] | None:
    """Wpis seeda po ``seed_key`` albo None, gdy nie ma takiego szablonu."""
    for entry in load_playbook_seed():
        if entry.get("seed_key") == seed_key:
            return entry
    return None
