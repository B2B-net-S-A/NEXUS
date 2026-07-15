#!/usr/bin/env python3
"""Golden-dataset evaluation harness for candidate search (Phase 0).

Measures retrieval quality of the manual candidate search against a labelled
set of requests, so every later phase (canonical facts, unified scoring,
Qdrant lifecycle) can be validated for regressions instead of guessed at.

Two runners:

* ``reference`` — a pure, deterministic matcher over the synthetic golden
  fixture that encodes the *intended* hard-filter semantics (exact-skill
  matching, hourly-rate NULL inclusion, CEFR language levels, …). Runs in CI
  with no DB/Qdrant. It is the oracle the fixture is labelled against.
* ``api`` — POSTs each request to a live ``/api/search/candidates`` and reports
  the same metrics for the real engine. Pointed at staging/prod, env-gated,
  NEVER run in CI. This is how you get the real baseline and spot the gap
  between intended and actual behaviour.

The module is import-safe (no side effects, no app import) so it runs on any
Python and is unit-testable. CLI lives under ``__main__``.

Usage::

    # CI / offline self-check against the reference oracle
    python scripts/eval_candidate_search.py --mode reference

    # real engine baseline (needs a JWT with search access)
    NEXUS_TOKEN=... python scripts/eval_candidate_search.py \
        --mode api --base-url https://api.nexus.dynaminds.pl
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# CEFR ladder — mirrors app.schemas.candidate_search / structured search.
_LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2", "native"]

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "golden_candidate_search.json"
)


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GoldenQuery:
    id: str
    request: dict[str, Any]
    expected_ids: list[int]
    description: str = ""
    rationale: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GoldenDataset:
    candidates: list[dict[str, Any]]
    queries: list[GoldenQuery]


def load_dataset(path: Path = DEFAULT_FIXTURE) -> GoldenDataset:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    queries = [
        GoldenQuery(
            id=q["id"],
            request=q["request"],
            expected_ids=list(q.get("expected_ids", [])),
            description=q.get("description", ""),
            rationale=q.get("rationale", ""),
            tags=list(q.get("tags", [])),
        )
        for q in raw["queries"]
    ]
    return GoldenDataset(candidates=list(raw["candidates"]), queries=queries)


# --------------------------------------------------------------------------- #
# Metrics — pure functions on ranked id lists
# --------------------------------------------------------------------------- #
def recall_at_k(retrieved: list[int], expected: list[int], k: int) -> float:
    """Fraction of expected ids present in the top-k. Vacuously 1.0 when there
    is nothing to retrieve (zero-result queries are scored separately)."""
    if not expected:
        return 1.0
    top = set(retrieved[:k])
    return len(top & set(expected)) / len(expected)


def precision_at_k(retrieved: list[int], expected: list[int], k: int) -> float:
    top = retrieved[:k]
    if not top:
        return 1.0 if not expected else 0.0
    return len(set(top) & set(expected)) / len(top)


def reciprocal_rank(retrieved: list[int], expected: list[int]) -> float:
    exp = set(expected)
    for i, rid in enumerate(retrieved):
        if rid in exp:
            return 1.0 / (i + 1)
    return 0.0


def duplicate_rate(retrieved: list[int]) -> float:
    if not retrieved:
        return 0.0
    return (len(retrieved) - len(set(retrieved))) / len(retrieved)


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in [0, 100]). Empty → 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


# --------------------------------------------------------------------------- #
# Reference runner — the oracle
# --------------------------------------------------------------------------- #
def _skill_set(candidate: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for s in candidate.get("skills") or []:
        if isinstance(s, str):
            out.add(s.strip().lower())
        elif isinstance(s, dict) and isinstance(s.get("name"), str):
            out.add(s["name"].strip().lower())
    return out


def _language_ok(candidate: dict[str, Any], req_lang: dict[str, Any]) -> bool:
    code = str(req_lang.get("code", "")).upper()
    min_level = req_lang.get("min_level", "B2")
    try:
        min_idx = _LEVEL_ORDER.index(min_level)
    except ValueError:
        return False
    for lang in candidate.get("languages") or []:
        if not isinstance(lang, dict):
            continue
        if str(lang.get("code", "")).upper() != code:
            continue
        try:
            if _LEVEL_ORDER.index(str(lang.get("level"))) >= min_idx:
                return True
        except ValueError:
            continue
    return False


def _matches(candidate: dict[str, Any], request: dict[str, Any]) -> bool:
    skills = _skill_set(candidate)

    must = [s.lower() for s in request.get("skills_must", [])]
    if any(m not in skills for m in must):
        return False
    any_skills = [s.lower() for s in request.get("skills_any", [])]
    if any_skills and not any(s in skills for s in any_skills):
        return False
    none_skills = [s.lower() for s in request.get("skills_none", [])]
    if any(s in skills for s in none_skills):
        return False

    # Hourly rate — NULL is unknown → included (SEARCH-P0-01).
    rate = candidate.get("expected_rate_hourly")
    rmin = request.get("rate_hourly_min")
    rmax = request.get("rate_hourly_max")
    if rate is not None:
        if rmin is not None and rate < rmin:
            return False
        if rmax is not None and rate > rmax:
            return False

    cities = request.get("location_cities") or []
    if cities:
        hay = f"{candidate.get('city') or ''} {candidate.get('location') or ''}".lower()
        if not any(c.lower() in hay for c in cities):
            return False

    countries = request.get("location_countries") or []
    if countries and str(candidate.get("country", "")).upper() not in {
        c.upper() for c in countries
    }:
        return False

    for req_lang in request.get("languages", []):
        if not _language_ok(candidate, req_lang):
            return False

    status = request.get("status") or []
    if status and candidate.get("status") not in status:
        return False

    avail = request.get("availability_status") or []
    if avail and candidate.get("availability_status") not in avail:
        return False

    cc = request.get("competence_category_ids") or []
    if cc and candidate.get("competence_category_id") not in cc:
        return False

    ymin = request.get("experience_years_min")
    ymax = request.get("experience_years_max")
    yrs = candidate.get("years_it_experience")
    if ymin is not None and (yrs is None or yrs < ymin):
        return False
    if ymax is not None and (yrs is None or yrs > ymax):
        return False

    return True


def make_reference_runner(
    candidates: list[dict[str, Any]],
) -> Callable[[dict[str, Any]], list[int]]:
    """Return a runner that applies the intended hard-filter semantics and
    returns matching ids sorted ascending (deterministic ordering)."""

    def run(request: dict[str, Any]) -> list[int]:
        return sorted(
            c["id"] for c in candidates if _matches(c, request)
        )

    return run


# --------------------------------------------------------------------------- #
# API runner — the real engine (staging/prod only)
# --------------------------------------------------------------------------- #
def make_api_runner(
    base_url: str, token: Optional[str], timeout: float = 20.0
) -> Callable[[dict[str, Any]], list[int]]:
    url = base_url.rstrip("/") + "/api/search/candidates"

    def run(request: dict[str, Any]) -> list[int]:
        body = dict(request)
        body.setdefault("page_size", 200)
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "dynaminds-eval-candidate-search/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        return [item["id"] for item in payload.get("items", [])]

    return run


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
@dataclass
class QueryResult:
    id: str
    tags: list[str]
    retrieved: list[int]
    expected: list[int]
    recall_20: float
    recall_50: float
    precision_20: float
    mrr: float
    duplicate_rate: float
    zero_result_ok: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


def evaluate(
    dataset: GoldenDataset,
    runner: Callable[[dict[str, Any]], list[int]],
    measure_latency: bool = False,
) -> list[QueryResult]:
    results: list[QueryResult] = []
    for q in dataset.queries:
        started = time.monotonic()
        error: Optional[str] = None
        try:
            retrieved = runner(q.request)
        except Exception as exc:  # noqa: BLE001 — report, don't crash the run
            retrieved = []
            error = f"{type(exc).__name__}: {exc}"
        latency = (time.monotonic() - started) * 1000 if measure_latency else None
        expect_empty = len(q.expected_ids) == 0
        results.append(
            QueryResult(
                id=q.id,
                tags=q.tags,
                retrieved=retrieved,
                expected=q.expected_ids,
                recall_20=recall_at_k(retrieved, q.expected_ids, 20),
                recall_50=recall_at_k(retrieved, q.expected_ids, 50),
                precision_20=precision_at_k(retrieved, q.expected_ids, 20),
                mrr=reciprocal_rank(retrieved, q.expected_ids),
                duplicate_rate=duplicate_rate(retrieved),
                zero_result_ok=(len(retrieved) == 0) == expect_empty,
                latency_ms=latency,
                error=error,
            )
        )
    return results


def aggregate(results: list[QueryResult]) -> dict[str, Any]:
    scored = [r for r in results if r.expected]  # recall/mrr need positives
    latencies = [r.latency_ms for r in results if r.latency_ms is not None]

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return {
        "queries": len(results),
        "recall_at_20": _mean([r.recall_20 for r in scored]),
        "recall_at_50": _mean([r.recall_50 for r in scored]),
        "precision_at_20": _mean([r.precision_20 for r in scored]),
        "mrr": _mean([r.mrr for r in scored]),
        "zero_result_accuracy": _mean([1.0 if r.zero_result_ok else 0.0 for r in results]),
        "duplicate_rate": _mean([r.duplicate_rate for r in results]),
        "errors": sum(1 for r in results if r.error),
        "latency_p50_ms": percentile([float(x) for x in latencies], 50),
        "latency_p95_ms": percentile([float(x) for x in latencies], 95),
    }


def _print_report(results: list[QueryResult], summary: dict[str, Any]) -> None:
    print(f"{'query':<28} {'recall@20':>9} {'prec@20':>8} {'zero_ok':>7} {'n':>4}")
    print("-" * 62)
    for r in results:
        flag = "" if not r.error else f"  ERROR {r.error}"
        print(
            f"{r.id:<28} {r.recall_20:>9.2f} {r.precision_20:>8.2f} "
            f"{str(r.zero_result_ok):>7} {len(r.retrieved):>4}{flag}"
        )
    print("-" * 62)
    for key, val in summary.items():
        print(f"{key:<24} {val}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["reference", "api"], default="reference")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--base-url", default=os.environ.get("NEXUS_BASE_URL", ""))
    parser.add_argument("--token", default=os.environ.get("NEXUS_TOKEN", ""))
    parser.add_argument("--json", action="store_true", help="emit JSON summary")
    args = parser.parse_args()

    dataset = load_dataset(args.fixture)

    if args.mode == "api":
        if not args.base_url:
            parser.error("--mode api requires --base-url (or NEXUS_BASE_URL)")
        runner = make_api_runner(args.base_url, args.token or None)
        measure_latency = True
    else:
        runner = make_reference_runner(dataset.candidates)
        measure_latency = False

    results = evaluate(dataset, runner, measure_latency=measure_latency)
    summary = aggregate(results)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print_report(results, summary)

    # Non-zero exit if the reference oracle can't reproduce its own labels —
    # that means the fixture is internally inconsistent.
    if args.mode == "reference" and summary["recall_at_20"] < 1.0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
