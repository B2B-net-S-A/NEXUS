#!/usr/bin/env python3
"""Ręczny bieg propozycji do słownika umiejętności (poza nocną pętlą).

Użycie (w kontenerze backendu)::

    python -m scripts.skill_proposals_run            # liczby + klasyfikacja modelem
    python -m scripts.skill_proposals_run --no-model # same liczby i reguły, bez modelu

Bieg niczego nie wpisuje do słownika: zapisuje propozycje w ``skill_proposals``,
które zatwierdza Head of Recruitment albo admin. Model z rejestru (F45), więc
koszt idzie do ``ai_usage_log`` jak w nocy. Wypisuje same liczby, bez danych osób.
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
from app.services import skill_proposals  # noqa: E402


async def main(use_model: bool) -> dict:
    async with AsyncSessionLocal() as db:
        return await skill_proposals.run(db, use_model=use_model)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-model", action="store_true", help="bez klasyfikacji modelem"
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main(not args.no_model)), ensure_ascii=False))
