#!/usr/bin/env python3
"""Ręczny bieg propozycji odpowiedzi w „Pytaniach z rozmów” (poza nocną pętlą, F55).

Użycie (w kontenerze backendu)::

    python -m scripts.interview_answer_proposals_run              # limit z configu (1000)
    python -m scripts.interview_answer_proposals_run --limit 40   # próbka: 40 najstarszych

Bieg zapisuje odpowiedź tylko pod pytaniem, które nie ma odpowiedzi ani
rozstrzygnięcia (``ideal_answer_source IS NULL``), ze źródłem ``ai``; nagłówki
działów dostają ``none``. Nie stempluje nocy, więc nocna pętla i tak pobiegnie
(weźmie to, co zostało). Model z rejestru (F55), koszt idzie do
``ai_usage_log`` jak w nocy. Wypisuje same liczby, bez treści pytań.
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
from app.services import interview_answer_proposals  # noqa: E402


async def main(limit: int | None) -> dict:
    async with AsyncSessionLocal() as db:
        return await interview_answer_proposals.run(db, limit=limit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--limit", type=int, default=None, help="ile pytań (domyślnie z configu)"
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main(args.limit)), ensure_ascii=False))
