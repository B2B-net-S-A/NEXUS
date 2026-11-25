#!/usr/bin/env python3
"""Jednorazowe zasilenie korpusu prawa asystenta prawnego (część A planu).

Pobiera najnowszy tekst jednolity każdego aktu z rejestru
(``app/services/legal/acts.py``) z API ELI Sejmu albo najnowszą wersję
skonsolidowaną z CELLAR UE, dzieli ją na jednostki redakcyjne, zapisuje
wersję i liczy wektory (Voyage → Qdrant ``nexus_legal_corpus``, gdy
``LEGAL_CORPUS_EMBEDDINGS_ENABLED`` i klucz Voyage są ustawione). Akt, którego
wersja już jest w korpusie, tylko odświeża datę sprawdzenia.

Na produkcji to samo robi pętla ``legal_corpus`` (worker). Na stagingu pętla
stoi, więc korpus zasila ten skrypt; zapora wyjścia potrzebuje wtedy
``STAGING_EXTRA_ALLOWED_HOSTS=api.sejm.gov.pl,publications.europa.eu``.

Uruchomienie (z ``backend/``)::

    python -m scripts.legal_corpus_seed
    python -m scripts.legal_corpus_seed --acts kc,kp
    python -m scripts.legal_corpus_seed --acts kc --force   # ta sama wersja od nowa

Wynik to liczby i identyfikatory wersji (dane publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional, Sequence

from app.core.database import engine
from app.services.legal import corpus
from app.services.legal.acts import ACT_KEYS


def _parse(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--acts", default="", help=f"lista kluczy: {','.join(ACT_KEYS)}"
    )
    parser.add_argument(
        "--force", action="store_true", help="zasil ponownie tę samą wersję"
    )
    return parser.parse_args(argv)


async def _run(keys: list[str], force: bool) -> int:
    try:
        results = await corpus.refresh_all(keys=keys or None, force=force)
    finally:
        await engine.dispose()
    failed = 0
    for result in results:
        failed += result.status == "failed"
        print(
            json.dumps(
                {
                    "act": result.act_key,
                    "status": result.status,
                    "version": result.version_ident,
                    "provisions": result.provisions,
                    "vectors": result.vectors,
                    "error": result.error,
                },
                ensure_ascii=False,
            )
        )
    return 1 if failed else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse(argv)
    keys = [k.strip() for k in args.acts.split(",") if k.strip()]
    unknown = [k for k in keys if k not in ACT_KEYS]
    if unknown:
        print(f"Nieznane akty: {', '.join(unknown)}", file=sys.stderr)
        return 2
    return asyncio.run(_run(keys, args.force))


if __name__ == "__main__":
    raise SystemExit(main())
