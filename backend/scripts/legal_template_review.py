#!/usr/bin/env python3
"""Ręczny przebieg „Przejrzyj wzór” (asystent prawny, część H).

Nowe wersje aktów w korpusie prawa zapisane po ``--since`` porównuje
z przepisami cytowanymi we wzorach (szablony umów i dokumentów z repo,
klauzule klientów, zatwierdzone wzory własne) i zakłada w Przepisach zmianę
z zadaniami „Przejrzyj wzór X — zmienił się art. Y” (rola ``contracts``).
Drugi przebieg nie dubluje zmian ani zadań. Bez maili.

To samo robi pętla ``legal_corpus`` (worker) po każdym odświeżeniu; na
stagingu pętla stoi, więc po ``scripts.legal_corpus_seed`` uruchamia się ten
skrypt.

Uruchomienie (z ``backend/``)::

    python -m scripts.legal_template_review                 # ostatnie 3 dni
    python -m scripts.legal_template_review --since 2026-11-01
    python -m scripts.legal_template_review --dry-run       # bez zapisu

Wynik to same liczby i oznaczenia przepisów (bez nazw wzorów — logi bywają
publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime, time, timezone
from typing import Optional, Sequence

from app.core.database import AsyncSessionLocal, engine
from app.core.scheduling import local_now
from app.services.legal import template_review


def _parse(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--since", type=date.fromisoformat, default=None, help="RRRR-MM-DD"
    )
    parser.add_argument("--dry-run", action="store_true", help="tylko plan")
    return parser.parse_args(argv)


async def _run(since: datetime, dry_run: bool) -> int:
    now = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as db:
            if dry_run:
                plans = await template_review.build_plans(db, since=since)
                result = template_review.ReviewResult(versions=len(plans), plans=plans)
            else:
                result = await template_review.run(db, since=since, now=now)
                await db.commit()
    finally:
        await engine.dispose()
    for plan in result.plans:
        print(
            json.dumps(
                {
                    "act": plan.act_key,
                    "version": plan.version_ident,
                    "refs": sorted({c.ref for c in plan.hits}),
                    "templates": len({c.template_key for c in plan.hits}),
                },
                ensure_ascii=False,
            )
        )
    print(json.dumps({"dry_run": dry_run, **result.counts()}))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse(argv)
    if args.since is None:
        since = datetime.now(timezone.utc) - template_review.LOOKBACK
    else:
        since = datetime.combine(args.since, time.min, tzinfo=local_now().tzinfo)
    if since > datetime.now(timezone.utc):
        print("--since nie może być w przyszłości", file=sys.stderr)
        return 2
    return asyncio.run(_run(since, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
