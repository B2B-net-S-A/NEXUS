#!/usr/bin/env python3
"""QA-01 (plan poprawy po audycie 14.09.2026): bramka „pokrycie bez spadku".

Porównuje zmierzone pokrycie z wartością zapisaną w ``.github/coverage-baseline.json``.
Wynik poniżej ``baseline - tolerance_pp`` kończy się kodem 1 i adnotacją
``::error::``; wynik wyższy o więcej niż tolerancja daje ``::notice::`` z prośbą
o podbicie baseline'u (ratchet — próg rośnie razem z testami, nigdy sam nie spada).

Baseline jest w repo, a nie w zmiennej CI, żeby każda zmiana progu była zwykłą,
przeglądaną zmianą w PR z uzasadnieniem w opisie.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateResult:
    passed: bool
    actual: float
    baseline: float
    tolerance: float
    ratchet_hint: bool

    @property
    def floor(self) -> float:
        return round(self.baseline - self.tolerance, 2)


def evaluate(actual: float, baseline: float, tolerance: float) -> GateResult:
    if tolerance < 0:
        raise ValueError("tolerance_pp nie może być ujemna")
    passed = actual >= round(baseline - tolerance, 2)
    ratchet_hint = actual > baseline + tolerance
    return GateResult(passed, actual, baseline, tolerance, ratchet_hint)


def load_baseline(path: Path, key: str) -> tuple[float, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if key not in data:
        raise KeyError(f"{path} nie ma klucza {key!r}")
    return float(data[key]), float(data.get("tolerance_pp", 0.0))


def render(result: GateResult, key: str) -> str:
    verdict = "✅ bez spadku" if result.passed else "❌ SPADEK poniżej baseline"
    return "\n".join(
        [
            f"### Bramka pokrycia — `{key}`",
            "",
            "| zmierzone | baseline | tolerancja | minimum | wynik |",
            "|---|---|---|---|---|",
            f"| {result.actual:.2f}% | {result.baseline:.2f}% | {result.tolerance:.2f} pp"
            f" | {result.floor:.2f}% | {verdict} |",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--actual", type=float, required=True)
    parser.add_argument("--summary", type=Path, default=None)
    args = parser.parse_args(argv)

    baseline, tolerance = load_baseline(args.baseline, args.key)
    result = evaluate(args.actual, baseline, tolerance)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(render(result, args.key))

    if not result.passed:
        print(
            f"::error::Pokrycie {args.key} spadło do {result.actual:.2f}% — minimum to "
            f"{result.floor:.2f}% (baseline {result.baseline:.2f}% − {result.tolerance:.2f} pp). "
            "Dopisz testy albo uzasadnij obniżenie baseline'u w PR."
        )
        return 1
    if result.ratchet_hint:
        print(
            f"::notice::Pokrycie {args.key} wzrosło do {result.actual:.2f}% "
            f"(baseline {result.baseline:.2f}%) — podbij baseline w .github/coverage-baseline.json."
        )
    else:
        print(f"Pokrycie {args.key}: {result.actual:.2f}% (minimum {result.floor:.2f}%).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
