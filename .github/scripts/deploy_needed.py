#!/usr/bin/env python3
"""Czy ten bieg Deploy musi przebudować produkcję (18.10.2026).

18.10.2026 dwa przebiegi Deploy zbudowały ten sam commit 1644e9e30 jeden po
drugim i użytkownicy mieli dwie przerwy (~4 min każda):

1. 13:25Z merge #2313 — zmiana WYŁĄCZNIE w ``docs/`` — przebudował produkcję,
   bo koalescencja pomijała rebuild tylko przy równości SHA z produkcją;
2. 13:29Z dwa „Coolify set env” (``redeploy=false``) i ręczny Deploy — ręczny
   bieg NIGDY nie pomijał rebuildu, więc czekał w kolejce za pierwszym
   i przebudował wszystko drugi raz.

Reguła: rebuild jest potrzebny, gdy zmieniło się coś, co trafia do obrazu albo
do kontenera — kod (każda ścieżka poza ``INERT_PREFIXES`` i ``*.md`` w korzeniu
repo) albo zmienne w skarbcu Coolify od chwili, w której ostatni udany Deploy
wywołał Coolify. Coolify robi zrzut zmiennych na początku swojego wdrożenia
(``--env-file /artifacts/build-time.env``), więc zmienna ustawiona w trakcie
budowy wymaga kolejnego wdrożenia — i ono się odbędzie.

Wynik: ``skip=true|false`` w ``$GITHUB_OUTPUT``. Każdy błąd odczytu kończy się
``skip=false`` (fail-open do deployu), z jednym wyjątkiem opisanym przy
``--env-unknown-is-unchanged``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, NamedTuple, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from select_release_sha import SHA_RE, _append, _github_fetch  # noqa: E402

Fetch = Callable[[str], object]

# Ścieżki, które nie wchodzą do żadnego obrazu ani montowania z docker-compose.yml
# (konteksty budowy: backend/, frontend/, backup/, deploy-window/; montowania
# z korzenia, np. ./alloy/). `.github/scripts/` NIE jest obojętne — Coolify
# buduje przez `.github/scripts/release.sh`.
INERT_PREFIXES = ("docs/", ".github/workflows/", ".github/scripts/tests/")
COMPARE_FILES_LIMIT = 300
DEPLOY_JOB = "Deploy + smoke test"
TRIGGER_STEP = "Trigger deployment"
WAIT_STEP = "Wait for deployment to finish"
HISTORY_RUNS = 30


class Decision(NamedTuple):
    skip: bool
    reason: str


def parse_time(value: object) -> Optional[datetime]:
    """ISO 8601 z GitHuba (``…Z``) i z Laravela (``…000000Z``) → UTC."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"\.(\d{6})\d*", r".\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_inert(path: str) -> bool:
    return path.startswith(INERT_PREFIXES) or ("/" not in path and path.endswith(".md"))


def changed_code(
    fetch: Fetch, repo: str, live: str, release: str
) -> Optional[list[str]]:
    """Pliki live→release, które trafiają do obrazu; ``None`` = nie wiadomo."""
    if live == release:
        return []
    body = fetch(
        f"repos/{repo}/compare/{live}...{release}?per_page={COMPARE_FILES_LIMIT}"
    )
    if not isinstance(body, dict) or body.get("status") != "ahead":
        return None
    files = body.get("files")
    if not isinstance(files, list) or len(files) >= COMPARE_FILES_LIMIT:
        return None
    names: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            return None
        for key in ("filename", "previous_filename"):
            name = item.get(key)
            if isinstance(name, str) and name:
                names.append(name)
    return [name for name in names if not is_inert(name)]


def last_trigger_time(
    fetch: Fetch, repo: str, history: int = HISTORY_RUNS
) -> Optional[datetime]:
    """Start kroku „Trigger deployment” w ostatnim Deploy, którego wdrożenie się skończyło."""
    runs = fetch(
        f"repos/{repo}/actions/workflows/deploy.yml/runs?branch=main&status=completed&per_page={history}"
    )
    for item in (runs or {}).get("workflow_runs", []) if isinstance(runs, dict) else []:
        jobs = fetch(f"repos/{repo}/actions/runs/{item['id']}/jobs?per_page=50")
        for job in (jobs or {}).get("jobs", []) if isinstance(jobs, dict) else []:
            if job.get("name") != DEPLOY_JOB:
                continue
            steps = {str(s.get("name", "")): s for s in job.get("steps") or []}
            trigger = next(
                (s for n, s in steps.items() if n.startswith(TRIGGER_STEP)), None
            )
            wait = next((s for n, s in steps.items() if n.startswith(WAIT_STEP)), None)
            if (
                trigger
                and wait
                and trigger.get("conclusion") == "success"
                and wait.get("conclusion") == "success"
            ):
                return parse_time(trigger.get("started_at"))
    return None


def last_env_change(envs: object) -> Optional[datetime]:
    """Najpóźniejsze ``updated_at`` ze skarbca Coolify; ``None`` = nie wiadomo."""
    if not isinstance(envs, list) or not envs:
        return None
    times = [
        parse_time(env.get("updated_at")) if isinstance(env, dict) else None
        for env in envs
    ]
    if any(t is None for t in times):
        return None
    return max(times)  # type: ignore[type-var]


def decide(
    code: Optional[list[str]],
    env_changed_at: Optional[datetime],
    deployed_at: Optional[datetime],
    env_unknown_is_unchanged: bool,
) -> Decision:
    if code is None:
        return Decision(False, "nie da się porównać produkcji z wydaniem — wdrażamy")
    if code:
        shown = ", ".join(code[:5]) + (" …" if len(code) > 5 else "")
        return Decision(
            False, f"zmiana w kodzie obrazu ({len(code)} pl.: {shown}) — wdrażamy"
        )
    if env_changed_at is None or deployed_at is None:
        if env_unknown_is_unchanged:
            return Decision(
                True,
                "kod bez zmian w obrazie, stan zmiennych nieznany — jak dotąd pomijamy",
            )
        return Decision(
            False,
            "kod bez zmian w obrazie, ale stanu zmiennych nie da się ustalić — wdrażamy",
        )
    if env_changed_at > deployed_at:
        return Decision(
            False,
            f"zmienna w Coolify zmieniona {env_changed_at:%Y-%m-%dT%H:%M:%SZ}, "
            f"po ostatnim wdrożeniu {deployed_at:%Y-%m-%dT%H:%M:%SZ} — wdrażamy",
        )
    return Decision(
        True,
        f"produkcja ma już ten kod obrazu, a zmienne są sprzed ostatniego wdrożenia "
        f"({deployed_at:%Y-%m-%dT%H:%M:%SZ}) — pomijamy rebuild",
    )


def evaluate(
    fetch: Fetch,
    repo: str,
    live: str,
    release: str,
    envs: object,
    env_unknown_is_unchanged: bool,
) -> Decision:
    if not SHA_RE.fullmatch(live or "") or not SHA_RE.fullmatch(release or ""):
        return Decision(False, f"produkcja zgłasza wersję {live or 'brak'} — wdrażamy")
    code = changed_code(fetch, repo, live, release)
    env_changed_at = last_env_change(envs)
    deployed_at = last_trigger_time(fetch, repo) if code == [] else None
    return decide(code, env_changed_at, deployed_at, env_unknown_is_unchanged)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--live", required=True, help="wersja z /api/health")
    parser.add_argument("--release", required=True, help="RELEASE_SHA z joba select")
    parser.add_argument(
        "--envs-file",
        help="JSON z GET /applications/{uuid}/envs (wystarczą pola key i updated_at)",
    )
    parser.add_argument(
        "--env-unknown-is-unchanged",
        action="store_true",
        help=(
            "biegi automatyczne: brak odczytu zmiennych nie wymusza rebuildu "
            "(zachowanie sprzed 18.10 — inaczej każda awaria API Coolify dawałaby rebuild na każdym merge'u)"
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None, fetch: Optional[Fetch] = None) -> int:
    args = parse_args(argv)
    try:
        envs: object = None
        if args.envs_file:
            try:
                envs = json.loads(Path(args.envs_file).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                envs = None
        if fetch is None:
            fetch = _github_fetch(
                os.environ.get("GITHUB_API_URL", "https://api.github.com"),
                os.environ["GH_TOKEN"],
            )
        decision = evaluate(
            fetch,
            args.repo,
            args.live,
            args.release,
            envs,
            args.env_unknown_is_unchanged,
        )
    except Exception as error:  # noqa: BLE001 — fail-open do deployu
        decision = Decision(
            False, f"błąd sprawdzenia ({type(error).__name__}) — wdrażamy"
        )
    print(("✅ " if decision.skip else "") + decision.reason)
    _append(
        os.environ.get("GITHUB_OUTPUT"),
        [f"skip={'true' if decision.skip else 'false'}"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
