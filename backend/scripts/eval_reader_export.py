"""Korpus lokalny czytników z kopii produkcji: ``~/.nexus-staging/corpus/<czytnik>/``.

Przypadki z prawdziwymi danymi osób nie trafiają do repo (jest publiczne); leżą na
laptopie obok stagingu i ``scripts/eval_reader.py`` dokłada je do korpusu z repo.

* ``cv`` — zatwierdzone CV etapu (``candidate_stage_cvs.branded_status = finalized``)
  z HTML-em edytora i zapisem generatora z kopii stagingu.
* ``rozliczenia`` — maile z archiwum skrzynki rozliczeń (``~/NEXUS-dane/…``), które
  w powtórce próby rozliczeń szły do czytnika; przypadek biegnie na kopii produkcji
  (kartoteka, klienci, zamówienia) w transakcji cofanej na końcu (``"baza": "kopia"``).

Oczekiwania to wynik czytnika na HEAD w chwili eksportu (``etykieta``): eval
porównuje przed i po na tej samej kopii, więc każda zmiana odczytu prawdziwego
pliku wychodzi jako spadek albo naprawa do obejrzenia. Dokument, którego osoba
i miesiąc zgadzają się z fakturą w ``--prawda`` (``cases_v*.csv`` z powtórki,
``md_match``), ma ``"prawda": "faktura"``.

Użycie (z ``backend/``)::

    python scripts/eval_reader_export.py cv --limit 120
    python scripts/eval_reader_export.py rozliczenia --limit 120 \\
        --prawda ~/NEXUS-dane/przekazanie-klodko-2026-11-22/wynik-proby/powtorka-10/cases_v10.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Optional

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

STAGING = Path(os.environ.get("NEXUS_STAGING_DIR", Path.home() / ".nexus-staging"))
PG_CONTAINER = "nexus-staging-postgres-1"
BACKEND_CONTAINER = "nexus-staging-backend-1"
DATA = Path.home() / "NEXUS-dane"
DEFAULT_MAILS = DATA / "przekazanie-klodko-2026-11-22/harness-v6/out/mails_v6r2.jsonl"
DEFAULT_ARCHIVE = DATA / "archiwum-home-pl-pelne"
# Ustawienia produkcji, które zmieniają odczyt poczty (bez sekretów).
_SETTING_KEYS = re.compile(r"^[A-Z0-9_]+_ENABLED$|^CONSULTANT_PORTAL_PERSONAL_DOMAINS$")


def _runner():
    path = Path(__file__).resolve().parent / "eval_reader_runner.py"
    spec = importlib.util.spec_from_file_location("eval_reader_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _docker_env(container: str) -> dict[str, str]:
    out = subprocess.run(
        ["docker", "exec", container, "printenv"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def copy_url(database: str) -> str:
    """Adres kopii stagingu; hasło z kontenera, tylko w pamięci procesu."""

    from sqlalchemy.engine import URL

    return URL.create(
        "postgresql+asyncpg",
        username="nexus",
        password=_docker_env(PG_CONTAINER).get("POSTGRES_PASSWORD", ""),
        host="127.0.0.1",
        port=5433,
        database=database,
    ).render_as_string(hide_password=False)


def newest_copy() -> str:
    names = subprocess.run(
        [
            "docker", "exec", PG_CONTAINER, "psql", "-U", "nexus", "-d", "postgres", "-At",
            "-c", "SELECT datname FROM pg_database WHERE datname LIKE 'nexus_staging_nightly_%' ORDER BY 1",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()  # fmt: skip
    if not names:
        raise SystemExit("brak kopii nexus_staging_nightly_* na stagingu")
    return names[-1]


def production_settings() -> tuple[dict[str, Any], list[str]]:
    """Flagi ``*_ENABLED`` i domeny skrzynek z backendu stagingu (nocna kopia
    bierze je z produkcji) oraz domeny adresów rozliczeń jako domeny firmy."""

    env = _docker_env(BACKEND_CONTAINER)
    settings: dict[str, Any] = {}
    for key, value in env.items():
        if not _SETTING_KEYS.match(key):
            continue
        low = value.strip().lower()
        settings[key] = low == "true" if low in ("true", "false") else value.strip()
    domains = sorted(
        {
            part.strip().rsplit("@", 1)[1].lower()
            for part in env.get("CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", "").split(
                ","
            )
            if "@" in part
        }
    )
    return settings, domains


def _private_dir(path: Path) -> Path:
    """Katalog z danymi osób: tylko właściciel czyta i wchodzi (rwx------)."""
    path.mkdir(parents=True, exist_ok=True)
    for folder in (path, path.parent):
        os.chmod(folder, stat.S_IRWXU)
    return path


def _write(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    os.chmod(path, 0o600)


def business_today() -> date:
    from app.core.scheduling import business_today as today

    return today()


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short=10", "HEAD"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    ).stdout.strip()


# ── CV ─────────────────────────────────────────────────────────────────────────


async def export_cv(database: str, limit: int, out: Path) -> int:
    import asyncpg

    runner = _runner()
    url = copy_url(database).replace("postgresql+asyncpg", "postgresql")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("SET default_transaction_read_only = on")
        rows = await conn.fetch(
            """
            SELECT s.id, s.branded_draft_html, s.branded_language, s.branded_finalized_at,
                   d.render_payload, d.language, d.blind
            FROM candidate_stage_cvs s
            LEFT JOIN cv_generated_documents d ON d.id = s.generated_document_id
            WHERE s.branded_status = 'finalized' AND s.branded_draft_html IS NOT NULL
            ORDER BY s.branded_finalized_at DESC NULLS LAST
            LIMIT $1
            """,
            limit,
        )
    finally:
        await conn.close()
    stamp = f"stan HEAD {_head()} z {business_today().isoformat()}"
    written = 0
    for row in rows:
        payload = row["render_payload"]
        payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
        case = {
            "id": f"prod-cv-{row['id']}",
            "zrodlo_danych": f"{database}: candidate_stage_cvs.id={row['id']}",
            "etykieta": stamp,
            "dzis": (row["branded_finalized_at"] or datetime.now(timezone.utc))
            .date()
            .isoformat(),
            "wejscie": {
                "jezyk": row["language"] or row["branded_language"] or "pl",
                "blind": bool(row["blind"]),
                "generator": payload,
                "html": row["branded_draft_html"],
            },
            "_katalog": str(out),
        }
        try:
            got = runner._cv_fields(case)
        except (
            Exception
        ) as exc:  # zapis, którego czytnik dziś nie czyta, też jest przypadkiem
            print(f"  cv {row['id']}: {type(exc).__name__} — pomijam", file=sys.stderr)
            continue
        case.pop("_katalog")
        case["oczekiwane"] = {
            **{field: got[field] for field in ("daty", "edukacja", "nazwa", "jezyki")},
            **{
                f"liczba_{field}": len(got[field])
                for field in ("daty", "edukacja", "jezyki")
            },
        }
        _write(out / f"prod-{row['id']}.json", case)
        written += 1
    return written


# ── Rozliczenia ───────────────────────────────────────────────────────────────


def _truth(path: Optional[Path]) -> set[tuple[int, str]]:
    if not path or not path.is_file():
        return set()
    good = set()
    for row in csv.DictReader(path.open(encoding="utf-8")):
        if str(row.get("md_match", "")).lower() in ("true", "1", "tak") and row.get(
            "contract_id"
        ):
            good.add((int(row["contract_id"]), row["period"]))
    return good


def _pick_mails(mails: Path, since: str, until: str, limit: int) -> list[dict]:
    """Maile z plikami, które szły do czytnika rozliczeń, po równo z każdej domeny
    nadawcy (inaczej korpus to sam Nordea i BNP)."""

    by_domain: dict[str, list[dict]] = defaultdict(list)
    for line in mails.open(encoding="utf-8"):
        item = json.loads(line)
        day = (item.get("received") or "")[:10]
        if not (
            item.get("route_settlements")
            and item.get("files")
            and since <= day <= until
        ):
            continue
        if not str(item.get("key", "")).startswith("rozliczenia:INBOX:"):
            continue
        by_domain[str(item.get("from", "")).rsplit("@", 1)[-1].lower()].append(item)
    picked: list[dict] = []
    while len(picked) < limit and any(by_domain.values()):
        for domain in sorted(by_domain):
            if by_domain[domain] and len(picked) < limit:
                picked.append(by_domain[domain].pop(0))
    return picked


async def export_settlements(
    database: str, limit: int, out: Path, mails: Path, archive: Path,
    since: str, until: str, truth_file: Optional[Path],
) -> int:  # fmt: skip
    from sqlalchemy.ext.asyncio import create_async_engine

    runner = _runner()
    settings, domains = production_settings()
    truth = _truth(truth_file)
    inbox = archive / "rozliczenia" / "INBOX"
    folder = _private_dir(out / "maile")
    engine = create_async_engine(copy_url(database))
    stamp = f"stan HEAD {_head()} z {business_today().isoformat()}"
    written = 0
    try:
        for item in _pick_mails(mails, since, until, limit):
            uid = item["key"].rsplit(":", 1)[1]
            found = sorted(inbox.glob(f"*-{uid}.eml"))
            if not found:
                continue
            shutil.copyfile(found[0], folder / f"{uid}.eml")
            os.chmod(folder / f"{uid}.eml", 0o600)
            case = {
                "id": f"prod-rozl-{uid}",
                "zrodlo_danych": f"archiwum rozliczenia@ INBOX uid {uid}; baza {database}",
                "etykieta": stamp,
                "baza": "kopia",
                "dzis": item["received"][:10],
                "domeny_firmy": domains,
                "ustawienia": settings,
                "maile": [{"id": uid, "eml_plik": f"maile/{uid}.eml"}],
                "_katalog": str(out),
            }
            today = date.fromisoformat(case["dzis"])
            moment = datetime.combine(today, time(12), tzinfo=timezone.utc)
            try:
                documents, _ = await _with_patches(runner, case, today, moment, engine)
            except Exception as exc:
                print(
                    f"  mail {uid}: {type(exc).__name__}: {exc}"[:200], file=sys.stderr
                )
                continue
            case.pop("_katalog")
            expected = []
            for doc in documents:
                period = f"{doc.period_year:04d}-{doc.period_month:02d}"
                entry = {
                    "plik": doc.file_name,
                    "rodzaj": doc.kind,
                    "osoba": doc.contract_id,
                    "okres": period,
                }
                if doc.contract_id and (doc.contract_id, period) in truth:
                    entry["prawda"] = "faktura"
                expected.append(entry)
            case["oczekiwane"] = expected
            case["liczba_dokumentow"] = len(documents)
            _write(out / f"prod-{uid}.json", case)
            written += 1
    finally:
        await engine.dispose()
    return written


async def _with_patches(runner, case: dict, today: date, moment: datetime, engine):
    """Jak ``_settlement_case``, ale oddaje dokumenty zamiast ocen."""

    import tempfile

    from app.core.config import settings
    from app.services import storage_service
    from app.services.consultant_portal import identity

    domains = frozenset(case["domeny_firmy"])
    patches = [
        (settings, k, v) for k, v in case["ustawienia"].items() if hasattr(settings, k)
    ]
    with tempfile.TemporaryDirectory(prefix="eval-export-") as tmp:
        patches += [
            (storage_service, "STORAGE_ROOT", Path(tmp)),
            (identity, "_company_domains", lambda: domains),
        ]
        previous = [(t, n, getattr(t, n)) for t, n, _ in patches]
        for target, name, value in patches:
            setattr(target, name, value)
        try:
            return await runner._read_mail(case, today, moment, engine)
        finally:
            for target, name, value in reversed(previous):
                setattr(target, name, value)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("czytnik", choices=("cv", "rozliczenia"))
    parser.add_argument(
        "--baza", help="kopia na stagingu (domyślnie najnowsza nexus_staging_nightly_*)"
    )
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument(
        "--maile",
        type=Path,
        default=DEFAULT_MAILS,
        help="mails_v*.jsonl z powtórki próby",
    )
    parser.add_argument("--archiwum", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--od", default="2026-09-01")
    parser.add_argument("--do", default="2026-11-20")
    parser.add_argument(
        "--prawda",
        type=Path,
        help="cases_v*.csv z powtórki (md_match per osoba i miesiąc)",
    )
    args = parser.parse_args(argv)

    database = args.baza or newest_copy()
    out = _private_dir(STAGING / "corpus" / args.czytnik)
    for old in out.glob("prod-*.json"):
        old.unlink()
    if args.czytnik == "cv":
        written = asyncio.run(export_cv(database, args.limit, out))
    else:
        written = asyncio.run(
            export_settlements(
                database,
                args.limit,
                out,
                args.maile,
                args.archiwum,
                args.od,
                args.do,
                args.prawda,
            )
        )
    _write(out / "_srodowisko.json", {"baza_kopii": database, "eksport": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                      "head": _head(), "przypadki": written})  # fmt: skip
    print(f"{args.czytnik}: {written} przypadków w {out} (kopia {database})")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
