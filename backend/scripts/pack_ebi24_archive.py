"""Pakuje eksport archiwum eBI24 w paczki ZIP do ``POST /api/finance/archive-ebi24/import`` (E5).

Wejście: katalog eksportu (domyślnie ``~/NEXUS-ebi24-export``) z
``archiwum/metadane-*.json`` i ``archiwum/dokumenty/<rok>/<nr>-<id>.<rozszerzenie>``.
Wyjście: ``paczka-NNN.zip`` (``metadane.json`` + ``pliki/<id>.<rozszerzenie>``),
każda do ``--max-mb`` MB. Metadane obcięte do ``archive.KEEP_META``.

Uruchom z ``backend/`` (w obrazie testowym backendu, bo skrypt importuje ``app``):
``python -m scripts.pack_ebi24_archive --src <eksport> --out <katalog paczek>``.
Dane (nazwiska, kwoty) nie trafiają do repo — paczki leżą poza nim.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import zipfile
from pathlib import Path

from app.services.finance_ledger.archive import EXTENSIONS, trim_meta


def _files(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in (root / "archiwum" / "dokumenty").glob("*/*"):
        stem, _, ext = path.name.rpartition(".")
        source_id = stem.split("-", 1)[-1]
        if ext.lower() in EXTENSIONS:
            out[source_id] = path
    return out


def pack(root: Path, out: Path, max_mb: int, max_files: int = 4000) -> list[Path]:
    rows: list[dict] = []
    for name in sorted(glob.glob(str(root / "archiwum" / "metadane-*.json"))):
        rows.extend(json.loads(Path(name).read_text(encoding="utf-8")))
    files = _files(root)
    out.mkdir(parents=True, exist_ok=True)
    limit = max_mb * 1024 * 1024
    packages: list[Path] = []
    batch: list[dict] = []
    size = 0

    def flush() -> None:
        nonlocal batch, size
        if not batch:
            return
        target = out / f"paczka-{len(packages) + 1:03d}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadane.json", json.dumps(batch, ensure_ascii=False))
            for row in batch:
                path = files[row["_id"]]
                archive.write(
                    path, f"pliki/{row['_id']}.{path.name.rpartition('.')[2].lower()}"
                )
        packages.append(target)
        batch, size = [], 0

    missing = 0
    for row in sorted(rows, key=lambda r: r.get("_bucketNumber") or 0):
        path = files.get(str(row.get("_id")))
        if path is None:
            missing += 1
            continue
        weight = os.path.getsize(path)
        if batch and (size + weight > limit or len(batch) >= max_files):
            flush()
        batch.append(trim_meta(row))
        size += weight
    flush()
    print(f"dokumenty: {len(rows)}, bez pliku: {missing}, paczek: {len(packages)}")
    return packages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", default=os.path.expanduser("~/NEXUS-ebi24-export"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-mb", type=int, default=60)
    # Import przyjmuje do 5 000 plików w paczce (archive.MAX_ENTRIES).
    parser.add_argument("--max-files", type=int, default=4000)
    args = parser.parse_args()
    pack(Path(args.src), Path(args.out), args.max_mb, args.max_files)


if __name__ == "__main__":
    main()
