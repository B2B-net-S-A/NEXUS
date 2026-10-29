#!/usr/bin/env python3
"""Alarm „slot bez dispatchu” budzika okna wdrożeń (29.10.2026).

Budzik ``deploy-window`` (kontener w compose) o 18:05, 20:05 i 22:05 czasu
warszawskiego uruchamia Deploy przez API GitHuba z ``window_slot=true``. Od
15.10 do 29.10.2026 nie uruchomił go ani razu, bo na serwerze nie było pliku
z tokenem. Jedyny ślad, wpis „brak czytelnego tokenu” w logu kontenera, ginął
przy każdym deployu, a wieczorne wdrożenia robiono ręcznie, więc alarm „noc bez
wdrożenia” milczał.

Sprawdzamy, czy od ostatniego wieczoru (18:00 dnia, którego slot 18:05 minął co
najmniej 15 min temu) przyszedł bieg Deploy z budzika. API nie zwraca inputów
biegu, więc rozpoznajemy go po tytule: ``run-name`` w ``deploy.yml`` nadaje
biegom z ``window_slot`` tytuł ``SLOT_RUN_NAME``. Budzik strzela codziennie,
także w weekend, więc sprawdzamy każdy dzień.

Wynik w ``$GITHUB_OUTPUT``: ``checked`` (czy jest werdykt) i ``slot_alert``
(powód alarmu albo pusty). Błąd API = brak werdyktu, kod 0.
"""

from __future__ import annotations

import argparse
import os
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

SLOT_RUN_NAME = "Deploy — slot budzika okna wdrożeń"
TZ = ZoneInfo("Europe/Warsaw")
# Pierwszy slot budzika to 18:05; liczymy od 18:00 z zapasem na zegar.
EVENING_FROM = 18
# Slot 18:05 z dwoma ponowieniami co minutę kończy się przed 18:08.
FIRST_SLOT_DONE = timedelta(minutes=20)

Fetch = Callable[[str], object]


def slots_since(now_utc: datetime) -> datetime:
    """Początek ostatniego wieczoru, którego pierwszy slot już powinien przyjść."""
    local = now_utc.astimezone(TZ)
    start = local.replace(hour=EVENING_FROM, minute=0, second=0, microsecond=0)
    if local < start + FIRST_SLOT_DONE:
        start = start - timedelta(days=1)
    return start.astimezone(timezone.utc)


def check(fetch: Fetch, repo: str, now_utc: datetime) -> str:
    """Powód alarmu albo pusty napis, gdy budzik uruchomił Deploy."""
    since = slots_since(now_utc)
    query = urllib.parse.urlencode(
        {
            "event": "workflow_dispatch",
            "created": f">={since:%Y-%m-%dT%H:%M:%SZ}",
            "per_page": "100",
        }
    )
    body = fetch(f"repos/{repo}/actions/workflows/deploy.yml/runs?{query}")
    runs = body.get("workflow_runs") if isinstance(body, dict) else None
    if not isinstance(runs, list):
        raise ValueError("nieoczekiwana odpowiedź API")
    if any(run.get("display_title") == SLOT_RUN_NAME for run in runs):
        return ""
    return (
        f"od {since.astimezone(TZ):%d.%m %H:%M} budzik deploy-window nie uruchomił Deploy "
        f"(ręcznych biegów: {len(runs)}); najczęściej brak albo wygasły token"
    )


def _append(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("".join(f"{line}\n" for line in lines))


def main(
    argv: Optional[list[str]] = None,
    fetch: Optional[Fetch] = None,
    now: Optional[datetime] = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    if fetch is None:
        from select_release_sha import _github_fetch

        token = os.environ.get("GH_TOKEN", "")
        if not token:
            print("::warning::GH_TOKEN nie jest ustawiony — budzik nie oceniony.")
            _append(["checked=false", "slot_alert="])
            return 0
        fetch = _github_fetch(
            os.environ.get("GITHUB_API_URL", "https://api.github.com"), token
        )
    try:
        alert = check(fetch, args.repo, now or datetime.now(timezone.utc))
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        print(
            f"::warning::Nie udało się odczytać biegów Deploy ({type(error).__name__}) — budzik nie oceniony."
        )
        _append(["checked=false", "slot_alert="])
        return 0
    _append(["checked=true", f"slot_alert={alert}"])
    print(alert or "Budzik uruchomił Deploy od ostatniego wieczoru.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
