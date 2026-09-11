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
  ma odtworzyć baseline 18.08) vs ``--scorer canonical``.

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


@dataclass(frozen=True)
class Arm:
    label: str  # OFF / ON — nazwy sekcji, które czyta workflow
    env: dict[str, str]
    extra_args: tuple[str, ...]


ARMS: dict[str, tuple[Arm, Arm]] = {
    "hybrid": (Arm("OFF", _POOL_OFF, ()), Arm("ON", _POOL_ON, ())),
    "scorer": (
        Arm("OFF", _POOL_OFF, ("--scorer", "legacy")),
        Arm("ON", _POOL_OFF, ("--scorer", "canonical")),
    ),
}


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
    runner: Callable[[Sequence[str], dict[str, str], Path], int] = _run_arm,
    out: Callable[[str], None] = print,
) -> int:
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
        runner(arm_argv(arm, ids=ids, jobs=jobs, pool=pool, output=md), arm.env, log)
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
    parser.add_argument("--jobs", type=_bounded(1, 50), required=True)
    parser.add_argument("--pool", type=_bounded(100, 5000), required=True)
    parser.add_argument("--lock", type=_lock_path, required=True)
    args = parser.parse_args(argv)
    return run(
        arms=args.arms,
        eval_set=args.eval_set,
        jobs=args.jobs,
        pool=args.pool,
        lock=args.lock,
    )


if __name__ == "__main__":
    sys.exit(main())
