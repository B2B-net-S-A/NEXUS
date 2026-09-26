"""Jednorazowy A/B matchingu na produkcji — oba ramiona w jednym procesie.

Uruchamia go zadanie Coolify zakładane przez ``coolify-ops.yml``
(``action=eval-ab`` / ``action=eval-ab-scorer``)::

    cd /app && python -m scripts.eval_ab_run --arms scorer --set A \
        --jobs 50 --pool 2000 --lock /tmp/nexus-eval-<run id>

Po co osobny skrypt: Coolify trzyma komendę zadania w
``scheduled_tasks.command``, czyli ``VARCHAR(255)`` (migracja
``create_scheduled_tasks_table``: ``$table->string('command')``). Stara
komenda z workflow niosła DWA razy listę 50 ofert i cały potok ``head``/``grep``
(~1,6 tys. znaków), więc każde założenie zadania kończyło się HTTP 500
(11.09.2026) — oba kanały A/B były martwe. Tu żyje cała logika dwóch ramion,
a workflow wysyła krótką komendę i pilnuje limitu.

Ramiona:

* ``hybrid`` — ta sama pula i scorer, ``HYBRID_POOL_ENABLED`` false vs true
  (reranker wyłączony w obu, bo mierzymy członkostwo puli);
* ``scorer`` — ta sama pula wektorowa, ``--scorer legacy`` (kontrola —
  ma odtworzyć baseline 18.08) vs ``--scorer canonical``;
* ``text`` — ten sam scorer (canonical) i pula, różni się WEKTOR KANDYDATA:
  OFF = aktywna kolekcja (tekst v1), ON = kolekcja-cień ``SHADOW_V3``
  (``AI_TEXT_SCHEMA_V3`` + ``QDRANT_COLLECTION`` w env procesu ramienia);
* ``text-notes`` — kontrola przecieku etykiety z notatek: OFF = cień v3,
  ON = cień v3 bez sekcji [NOTES] (``SHADOW_V3_NO_NOTES``).

Kolekcje-cienie buduje ``scripts.reembed_collections --collection …
--text-schema …`` (docs/embedding-v3-ab-runbook.md). Nazwy są stałymi tutaj,
a nie argumentem, żeby komenda Coolify (VARCHAR 255) nie niosła tekstu od
operatora.

``--harness manual`` (tylko ramiona ``text*``) uruchamia w każdym ramieniu
``scripts.eval_manual_search_order`` zamiast ``eval_matching``; sekcja raportu
to wtedy tabela z końca logu. Ten harness nie zna zamrożonego zbioru ani puli
(``--set``/``--pool`` są dla niego bez znaczenia), a ``--jobs`` to liczba
rekrutacji z historii (do 300).

Wyjście: dokładnie te sekcje, które czyta krok workflow, i sentinel na końcu.
Zamrożony zbiór ofert czytamy z ``scripts.eval_frozen_set`` — tej samej listy
co cotygodniowy strażnik, więc nie może się rozjechać z kopią w YAML-u.

Katalog ``--lock`` jest zakładany na starcie: cron Coolify odpala zadanie co
minutę, dopóki workflow go nie skasuje, a kolejne wykonania muszą odbić się od
istniejącego katalogu zamiast liczyć eval drugi raz.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

SENTINEL = "===NEXUS-EVAL-END==="
_LOCK_RE = re.compile(r"\A/tmp/nexus-eval-[0-9]{1,20}\Z")

_POOL_OFF = {"HYBRID_POOL_ENABLED": "false", "RERANKER_ENABLED": "false"}
_POOL_ON = {"HYBRID_POOL_ENABLED": "true", "RERANKER_ENABLED": "false"}

# Kolekcje-cienie kandydatów (budowane przez scripts.reembed_collections).
SHADOW_V3 = "nexus_candidates_v3"
SHADOW_V3_NO_NOTES = "nexus_candidates_v3_nonotes"

# Ramię tekstu = ta sama pula co _POOL_OFF + przełącznik schematu i kolekcji.
# `QDRANT_COLLECTION` celowo NIE w ramieniu v1: ma zostać to, czym żyje
# produkcja, a nie nasze założenie o nazwie aktywnej kolekcji.
_TEXT_V1 = {**_POOL_OFF, "AI_TEXT_SCHEMA_V3": "false"}
_TEXT_V3 = {
    **_POOL_OFF,
    "AI_TEXT_SCHEMA_V3": "true",
    "AI_TEXT_SCHEMA_V3_NOTES": "true",
    "QDRANT_COLLECTION": SHADOW_V3,
}
_TEXT_V3_NO_NOTES = {
    **_POOL_OFF,
    "AI_TEXT_SCHEMA_V3": "true",
    "AI_TEXT_SCHEMA_V3_NOTES": "false",
    "QDRANT_COLLECTION": SHADOW_V3_NO_NOTES,
}
# Oba ramiona tekstu na TYM SAMYM scorerze — metryk między scorerami nie
# porównujemy. Canonical, bo to on stoi za ekranami C2 od #1428.
_CANONICAL = ("--scorer", "canonical")


@dataclass(frozen=True)
class Arm:
    label: str  # OFF / ON — nazwy sekcji, które czyta workflow
    env: dict[str, str]
    extra_args: tuple[str, ...]


ARMS: dict[str, tuple[Arm, ...]] = {
    "hybrid": (Arm("OFF", _POOL_OFF, ()), Arm("ON", _POOL_ON, ())),
    "scorer": (
        Arm("OFF", _POOL_OFF, ("--scorer", "legacy")),
        Arm("ON", _POOL_OFF, ("--scorer", "canonical")),
    ),
    "text": (
        Arm("OFF", _TEXT_V1, _CANONICAL),
        Arm("ON", _TEXT_V3, _CANONICAL),
    ),
    "text-notes": (
        Arm("OFF", _TEXT_V3, _CANONICAL),
        Arm("ON", _TEXT_V3_NO_NOTES, _CANONICAL),
    ),
}

HARNESSES = ("matching", "manual")
# Harness „manual” nie ma --scorer ani zamrożonego zbioru — ma sens wyłącznie
# tam, gdzie ramiona różnią się wektorem kandydata.
MANUAL_ARMS = frozenset({"text", "text-notes"})
MAX_MATCHING_JOBS = 50
MAX_MANUAL_JOBS = 300


def frozen_ids(eval_set: str) -> str:
    from scripts.eval_frozen_set import frozen_ids_csv, frozen_ids_csv_b

    return frozen_ids_csv_b() if eval_set == "B" else frozen_ids_csv()


def arm_argv(arm: Arm, *, ids: str, jobs: int, pool: int, output: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scripts.eval_matching",
        "--job-ids",
        ids,
        "--jobs",
        str(jobs),
        "--min-gt",
        "3",
        "--pool",
        str(pool),
        *arm.extra_args,
        "--output",
        str(output),
    ]


def manual_argv(*, jobs: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scripts.eval_manual_search_order",
        "--jobs",
        str(jobs),
    ]


def manual_table(log: Path) -> list[str]:
    """Tabela wyników ``eval_manual_search_order`` — od „Rekrutacje:” do końca.

    Skrypt drukuje wynik na stdout (bez pliku ``--output``), więc sekcję
    raportu wycinamy z logu ramienia. Brak linii = harness padł: sekcja
    zostaje pusta, a przyczynę pokazuje ogon logu.
    """
    lines = _lines(log)
    starts = [i for i, line in enumerate(lines) if line.startswith("Rekrutacje:")]
    return lines[starts[-1] :] if starts else []


def _run_arm(argv: Sequence[str], env: dict[str, str], log: Path) -> int:
    with log.open("w", encoding="utf-8") as handle:
        return subprocess.run(
            list(argv),
            env={**os.environ, **env},
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        ).returncode


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def report(label: str, md: Path, log: Path) -> list[str]:
    """Sekcje ``head -n 32 md`` / ``grep bm25=`` / ``tail -n 12 log``.

    Ogon logu leci ZAWSZE: gdy harness się wywróci, raportu nie ma, więc sama
    sekcja z raportem wyglądałaby jak „zero wyników" zamiast jak awaria.
    """
    log_lines = _lines(log)
    bm25 = [line for line in log_lines if "bm25=" in line]
    return [
        f"===NEXUS-EVAL-{label}===",
        *_lines(md)[:32],
        f"===NEXUS-EVAL-BM25-{label}===",
        str(len(bm25)),
        *bm25[:3],
        f"===NEXUS-EVAL-TAIL-{label}===",
        *log_lines[-12:],
    ]


def run(
    *,
    arms: str,
    eval_set: str,
    jobs: int,
    pool: int,
    lock: Path,
    harness: str = "matching",
    runner: Callable[[Sequence[str], dict[str, str], Path], int] = _run_arm,
    out: Callable[[str], None] = print,
) -> int:
    if harness == "manual" and arms not in MANUAL_ARMS:
        raise ValueError(
            f"harness manual działa tylko z ramionami {sorted(MANUAL_ARMS)}"
        )
    try:
        lock.mkdir(parents=False)
    except FileExistsError:
        # Kolejne odpalenie crona tego samego zadania — eval już trwa albo
        # skończył się; bez sentinela, więc workflow go nie pomyli z wynikiem.
        print(f"lock {lock} exists — eval already ran", file=sys.stderr)
        return 3
    ids = frozen_ids(eval_set)
    lines: list[str] = []
    for arm in ARMS[arms]:
        md = lock / f"{arm.label.lower()}.md"
        log = lock / f"{arm.label.lower()}.log"
        if harness == "manual":
            runner(manual_argv(jobs=jobs), arm.env, log)
            md.write_text("\n".join(manual_table(log)), encoding="utf-8")
        else:
            runner(
                arm_argv(arm, ids=ids, jobs=jobs, pool=pool, output=md), arm.env, log
            )
        lines.extend(report(arm.label, md, log))
    lines.append(SENTINEL)
    for line in lines:
        out(line)
    return 0


def _bounded(low: int, high: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"poza zakresem {low}-{high}")
        return number

    return parse


def _lock_path(value: str) -> Path:
    if not _LOCK_RE.match(value):
        raise argparse.ArgumentTypeError(
            "lock musi mieć postać /tmp/nexus-eval-<liczba>"
        )
    return Path(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arms", choices=sorted(ARMS), required=True)
    parser.add_argument("--set", dest="eval_set", choices=("A", "B"), required=True)
    parser.add_argument("--jobs", type=_bounded(1, MAX_MANUAL_JOBS), required=True)
    parser.add_argument("--pool", type=_bounded(100, 5000), required=True)
    parser.add_argument("--lock", type=_lock_path, required=True)
    parser.add_argument("--harness", choices=HARNESSES, default="matching")
    args = parser.parse_args(argv)
    if args.harness == "matching" and args.jobs > MAX_MATCHING_JOBS:
        parser.error(f"--jobs dla eval_matching: 1-{MAX_MATCHING_JOBS}")
    if args.harness == "manual" and args.arms not in MANUAL_ARMS:
        parser.error(f"--harness manual działa tylko z --arms {sorted(MANUAL_ARMS)}")
    return run(
        arms=args.arms,
        eval_set=args.eval_set,
        jobs=args.jobs,
        pool=args.pool,
        lock=args.lock,
        harness=args.harness,
    )


if __name__ == "__main__":
    sys.exit(main())
