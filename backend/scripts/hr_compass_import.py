"""Import z Compassa z wiersza poleceń: na sucho → raport → zapis.

Użycie (kontener backendu)::

    python scripts/hr_compass_import.py --bundle /ścieżka/paczka.json --module profiles
    python scripts/hr_compass_import.py --bundle /ścieżka/paczka.json --module profiles --apply <id partii>

Pierwsze wywołanie zakłada partię i drukuje raport (liczby, powody, id źródła
pozycji do decyzji — bez imion i e-maili). Drugie zapisuje tę samą paczkę
(sprawdza skrót SHA-256) i drukuje, co zapisano. Paczka zawiera dane osobowe:
trzymaj ją poza repozytorium, z dostępem tylko dla siebie, i skasuj po imporcie.
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
from app.models.hr_ops import HrImportBatch  # noqa: E402
from app.services.hr import compass_import  # noqa: E402


async def _run(bundle_path: Path, module: str, apply_batch: int | None) -> int:
    importer = compass_import.IMPORTERS.get(module)
    if importer is None:
        print(f"Nieznany moduł importu: {module}", file=sys.stderr)
        return 2
    try:
        bundle = compass_import.parse_bundle(bundle_path.read_bytes())
    except compass_import.BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    async with AsyncSessionLocal() as db:
        if apply_batch is None:
            batch, _ = await compass_import.dry_run(
                db,
                module=module,
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            await db.commit()
            print(
                json.dumps(
                    {"batch_id": batch.id, **batch.report}, ensure_ascii=False, indent=2
                )
            )
            return 0
        batch = await db.get(HrImportBatch, apply_batch)
        if batch is None or batch.module != module:
            print("Nie ma takiej partii dla tego modułu.", file=sys.stderr)
            return 2
        try:
            written = await compass_import.apply(
                db,
                batch=batch,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
        except compass_import.ImportFlowError as exc:
            await db.rollback()
            print(str(exc), file=sys.stderr)
            return 2
        await db.commit()
        print(
            json.dumps(
                {"batch_id": batch.id, "written": written}, ensure_ascii=False, indent=2
            )
        )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--module", required=True, choices=sorted(compass_import.IMPORTERS)
    )
    parser.add_argument("--apply", type=int, default=None, metavar="BATCH_ID")
    args = parser.parse_args()
    return asyncio.run(_run(args.bundle, args.module, args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
