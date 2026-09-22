#!/usr/bin/env python3
"""Buduje ``backend/tests/ci_test_durations.json`` z logów shardów pytest.

Po co: shardy CI dzielą pliki testowe tak, żeby każdy trwał tyle samo
(``_apply_ci_shard_filter`` w ``backend/tests/conftest.py``). Do tego potrzeba
zmierzonego czasu każdego PLIKU. Dzielenie „po kolei” (round-robin) dawało
16,5 min w jednym shardzie i 6 min w innym, a całość czeka na najwolniejszy.

Źródło: surowy log joba z GitHub Actions. Każda linia ma znacznik czasu,
a ``pytest -v`` wypisuje jedną linię na test, więc czas testu (z fixture'ami)
to różnica między jego linią a linią poprzedniego testu w tym samym jobie.

Użycie (logi per job, bo log zbiorczy ``gh run view --log`` bywa obcięty):

    for id in $(gh run view <RUN_ID> --json jobs \\
        --jq '.jobs[] | select(.name|test("shard")) | .databaseId'); do
      gh api repos/{owner}/{repo}/actions/jobs/$id/logs > job_$id.log
    done
    python .github/scripts/build_test_durations.py job_*.log

Kilka przebiegów = średnia per plik. Plik bez pomiaru dostaje w conftest
medianę, więc nieaktualna mapa tylko pogarsza równowagę — nigdy nie gubi testu.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_OUT = _REPO / "backend" / "tests" / "ci_test_durations.json"

# 2026-09-22T15:09:12.1234567Z tests/test_x.py::test_y PASSED   [ 1%]
_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z\s+"
    r"(?P<file>tests/[^:\s]+\.py)::\S+\s+"
    r"(?P<status>PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS|RERUN)\b"
)


def _parse_ts(raw: str) -> datetime:
    # GitHub daje 7 cyfr ułamka, fromisoformat przyjmuje najwyżej 6.
    if "." in raw:
        head, frac = raw.split(".", 1)
        raw = f"{head}.{frac[:6]}"
    return datetime.fromisoformat(raw)


def durations_from_log(path: Path) -> dict[str, float]:
    per_file: dict[str, float] = defaultdict(float)
    previous: datetime | None = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = _LINE.match(line.lstrip("\ufeff"))
        if not match:
            continue
        ts = _parse_ts(match["ts"])
        # Pierwszy test w jobie niesie też czas kolekcji — pomijamy go.
        if previous is not None:
            per_file[match["file"]] += max(0.0, (ts - previous).total_seconds())
        previous = ts
    return dict(per_file)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=_OUT)
    args = parser.parse_args()

    samples: dict[str, list[float]] = defaultdict(list)
    for log in args.logs:
        for name, seconds in durations_from_log(log).items():
            samples[name].append(seconds)
    if not samples:
        raise SystemExit("Żaden log nie zawierał wyników pytest -v.")

    result = {
        name: round(statistics.fmean(values), 1)
        for name, values in sorted(samples.items())
    }
    args.out.write_text(
        json.dumps(result, indent=0, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    total = sum(result.values())
    print(f"{len(result)} plików, łącznie {total / 60:.1f} min → {args.out}")


if __name__ == "__main__":
    main()
