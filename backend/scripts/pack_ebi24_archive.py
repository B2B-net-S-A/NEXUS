"""Pakuje eksport archiwum eBI24 w paczki ZIP do ``POST /api/finance/archive-ebi24/import`` (E5).

Wejście: katalog eksportu (domyślnie ``~/NEXUS-ebi24-export``) z
``archiwum/metadane-*.json`` i ``archiwum/dokumenty/<rok>/<nr>-<id>.<rozszerzenie>``.
Wyjście: ``paczka-NNN.zip`` (``metadane.json`` + ``pliki/<id>.<rozszerzenie>``),
każda do ``--max-mb`` MB. Metadane obcięte do ``archive.KEEP_META``.

Uruchom z ``backend/`` (w obrazie testowym backendu, bo skrypt importuje ``app``):
``python -m scripts.pack_ebi24_archive --src <eksport> --out <katalog paczek>``.
Dane (nazwiska, kwoty) nie trafiają do repo — paczki leżą poza nim.

Przyrost przed wyłączeniem eBI24 (``--known`` = plik z ``source_id`` już w NEXUSIE,
jeden na linię, pierwsza linia może być nagłówkiem CSV): ``--print-new-ids`` wypisuje
JSON z id nowych dokumentów (do pętli pobierania w karcie eBI24), a samo ``--known``
pakuje tylko nowe. Procedura: ``docs/claude/finanse-insights/archiwum-ebi24-przyrost-i-kopia.md``.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import zipfile
from pathlib import Path

from app.services.finance_ledger.archive import EXTENSIONS, trim_meta

#: Paczka musi zmieścić się w ``MAX_REQUEST_BODY_MB`` (30 MB) — limit ciała
#: żądania odrzuca większe 413, zanim import je przeczyta (16.11.2026: 60 MB = 413).
DEFAULT_MAX_MB = 25
#: Import przyjmuje do 5 000 plików w paczce (``archive.MAX_ENTRIES``).
DEFAULT_MAX_FILES = 4000
_SOURCE_ID = re.compile(r"^[0-9a-f]{24}$")


def _files(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in (root / "archiwum" / "dokumenty").glob("*/*"):
        stem, _, ext = path.name.rpartition(".")
        source_id = stem.split("-", 1)[-1]
        if ext.lower() in EXTENSIONS:
            out[source_id] = path
    return out


def _rows(root: Path) -> list[dict]:
    rows: list[dict] = []
    for name in sorted(glob.glob(str(root / "archiwum" / "metadane-*.json"))):
        rows.extend(json.loads(Path(name).read_text(encoding="utf-8")))
    return rows


def read_known(path: Path) -> set[str]:
    """``source_id`` już w NEXUSIE (wynik SELECT-u z produkcji); pusty plik = błąd."""

    known = {
        line.split(",", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
    }
    known = {value for value in known if _SOURCE_ID.match(value)}
    if not known:
        sys.exit(f"{path}: brak id eBI24 — przyrost bez listy pobrałby całe archiwum.")
    return known


def new_ids(root: Path, known: set[str]) -> list[str]:
    """Id dokumentów z metadanych, których NEXUS jeszcze nie ma (kolejność eBI24)."""

    seen: set[str] = set()
    out: list[str] = []
    for row in sorted(_rows(root), key=lambda r: r.get("_bucketNumber") or 0):
        source_id = str(row.get("_id"))
        if source_id not in known and source_id not in seen:
            seen.add(source_id)
            out.append(source_id)
    return out


def pack(
    root: Path,
    out: Path,
    max_mb: int,
    max_files: int = DEFAULT_MAX_FILES,
    known: set[str] | None = None,
) -> list[Path]:
    rows = _rows(root)
    already = 0
    if known is not None:
        already = sum(1 for row in rows if str(row.get("_id")) in known)
        rows = [row for row in rows if str(row.get("_id")) not in known]
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
    prefix = f"już w NEXUSIE: {already}, " if known is not None else ""
    print(
        f"{prefix}dokumenty: {len(rows)}, bez pliku: {missing}, paczek: {len(packages)}"
    )
    return packages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", default=os.path.expanduser("~/NEXUS-ebi24-export"))
    parser.add_argument("--out")
    parser.add_argument("--max-mb", type=int, default=DEFAULT_MAX_MB)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--known", help="plik z source_id już w NEXUSIE (przyrost)")
    parser.add_argument("--print-new-ids", action="store_true")
    args = parser.parse_args()
    known = read_known(Path(args.known)) if args.known else None
    if args.print_new_ids:
        if known is None:
            parser.error("--print-new-ids wymaga --known")
        print(json.dumps(new_ids(Path(args.src), known)))
        return
    if not args.out:
        parser.error("--out jest wymagane przy pakowaniu")
    pack(Path(args.src), Path(args.out), args.max_mb, args.max_files, known)


if __name__ == "__main__":
    main()
