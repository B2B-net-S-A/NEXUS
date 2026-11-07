#!/usr/bin/env python3
"""Ręczny bieg mapy wiedzy IT: powiązania haseł słownika (poza nocną pętlą).

Użycie (w kontenerze backendu)::

    python -m scripts.skill_relations_run            # pary + ocena modelem, zatwierdza
    python -m scripts.skill_relations_run --no-model # same pary z danych, nic nie zatwierdza

Z modelem powiązania, które przejdą bezpieczniki, są od razu zatwierdzane
(decyzja Artura z 07.11.2026). Model z rejestru (F45), koszt w ``ai_usage_log``.
Wypisuje same liczby, bez danych osób.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services import skill_relations  # noqa: E402


async def main(use_model: bool) -> dict:
    async with AsyncSessionLocal() as db:
        return await skill_relations.run(db, use_model=use_model)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-model", action="store_true", help="bez oceny modelem")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main(not args.no_model)), ensure_ascii=False))
