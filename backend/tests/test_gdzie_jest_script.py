"""``scripts/gdzie_jest.py``: jeden wiersz na PR, od kolejki merge'ów do produkcji.

Nagrania w ``tests/data/gdzie_jest/`` to prawdziwe odpowiedzi GitHuba (GraphQL,
biegi ``deploy.yml`` i ``merge_group``, log joba), ``/api/health``, strony
``/login`` i ``git merge-base`` z nocy 25/26.11.2026, przycięte do pól, które
czyta skrypt:

* ``nagranie-2026-11-26.json`` — czw. 00:42, okno wdrożeń otwarte: #4035 na
  produkcji, #4036 tuż po scaleniu (Deploy w toku), #4037 w kolejce, #4040
  z migracją, #4032 z 225 plikami, wypadnięcie #4016 z 25.11 19:47 UTC
  (``failed_checks``, czerwony test Playwrighta w logu), #99999 nie istnieje;
* ``ostatnie-1h-503-2026-11-26.json`` — tryb bez numerów 00:44, gdy
  ``/api/health`` dawało 503 w trakcie wdrożenia #4036.

Sytuacje, których tej nocy nie było (PR wypadł i stoi, scalony w dzień,
Deploy czerwony, sam ``docs/``), powstają z tych nagrań przez zmianę jednego
pola: test mówi którego. Testy nie łączą się z siecią ani z gitem.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[2]
_PATH = _REPO / "scripts/gdzie_jest.py"
_SPEC = importlib.util.spec_from_file_location("gdzie_jest", _PATH)
gj = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gj
_SPEC.loader.exec_module(gj)

_DATA = Path(__file__).parent / "data" / "gdzie_jest"
NIGHT = json.loads((_DATA / "nagranie-2026-11-26.json").read_text(encoding="utf-8"))
RECENT = json.loads(
    (_DATA / "ostatnie-1h-503-2026-11-26.json").read_text(encoding="utf-8")
)
NIGHT_NUMBERS = [4035, 4036, 4037, 4040, 4017, 4032, 4016, 4025, 4031, 99999]
DEPLOY_RUNS = (
    "repos/B2B-net-S-A/NEXUS/actions/workflows/deploy.yml/runs?branch=main&per_page=20"
)
SHA_4035 = "467995771f4e8015063ccc6cabb0d0a7092f4813"
SHA_BEFORE_4035 = "5d9a855a649836e7dcbe6e78443822485c9e3578"
SHA_BEFORE_4017 = "1ed9ce0431ce6070c29eb3d4e5e40c2eff729c17"
SHA_BEFORE_4031 = "251daec592e6106811ba55624799841140874624"


def _key(op: str, variables: dict) -> str:
    return (
        op
        + "|"
        + json.dumps(
            {k: v for k, v in variables.items() if k not in ("owner", "name")},
            sort_keys=True,
        )
    )


class Replay(gj.Api):
    """Odtwarza nagranie. Zapytanie spoza nagrania = KeyError, czyli czerwony test."""

    def __init__(self, recording: dict):
        self.rec = copy.deepcopy(recording)
        self.calls: list[tuple[str, str]] = []
        self.fetched = 0

    def graphql(self, op, query, variables):
        key = _key(op, variables)
        self.calls.append(("graphql", key))
        return self.rec["graphql"][key]

    def rest(self, path):
        self.calls.append(("rest", path))
        return self.rec["rest"][path]

    def raw(self, path):
        self.calls.append(("raw", path))
        return self.rec["raw"][path]

    def http(self, url):
        self.calls.append(("http", url))
        value = self.rec["http"][url]
        if isinstance(value, dict):
            raise RuntimeError(value["error"])
        return value

    def fetch_main(self):
        self.fetched += 1

    def is_ancestor(self, commit, descendant):
        return self.rec["ancestor"].get(f"{commit}..{descendant}")

    # ── zmiany jednego pola ──
    def pr(self, number: int) -> dict:
        repo = next(iter(self.rec["graphql"].values()))["data"]["repository"]
        return next(v for v in repo.values() if v and v["number"] == number)

    def only(self, *prs: dict) -> None:
        """Odpowiedź GraphQL tylko z tymi PR-ami (po kolei, jak w zapytaniu)."""
        variables = {f"n{i}": pr["number"] for i, pr in enumerate(prs)}
        repo = {f"p{i}": pr for i, pr in enumerate(prs)}
        self.rec["graphql"][_key("GdzieJestPR", variables)] = {
            "data": {"repository": repo}
        }

    def health(self, version: str) -> None:
        self.rec["http"][gj.HEALTH_URL] = json.dumps(
            {"status": "healthy", "version": version}
        )

    def front(self, release: str) -> None:
        self.rec["http"][gj.LOGIN_URL] = (
            f'<meta name="baggage" content="sentry-environment=production,sentry-release={release}"/>'
        )


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _run(api: Replay, numbers, now: str = NIGHT["now"], extra=()) -> list[str]:
    lines: list[str] = []
    assert (
        gj.main([*map(str, numbers), *extra], api=api, now=_at(now), out=lines.append)
        == 0
    )
    return lines


def _line(api: Replay, pr: dict, now: str = NIGHT["now"]) -> str:
    api.only(pr)
    (line,) = _run(api, [pr["number"]], now)
    return line


def _reopened(pr: dict, until_reason: str) -> dict:
    """Ten PR otwarty, jakby stał tuż po zdarzeniu kolejki z tym powodem."""
    pr = copy.deepcopy(pr)
    nodes = pr["timelineItems"]["nodes"]
    cut = next(i for i, e in enumerate(nodes) if e.get("reason") == until_reason)
    pr["timelineItems"]["nodes"] = nodes[: cut + 1]
    pr.update(state="OPEN", mergedAt=None, mergeCommit=None, mergeQueueEntry=None)
    return pr


# ── całe nagranie: wiersze jak z nocy 25/26.11 ─────────────────────────


def test_nagranie_nocne_daje_te_same_wiersze():
    api = Replay(NIGHT)
    lines = _run(api, NIGHT_NUMBERS)
    assert lines == NIGHT["lines"]
    by_pr = {line.split()[0]: line for line in lines}
    assert by_pr["#4035"].startswith("#4035 ✓ na produkcji — backend 467995771 ·")
    assert (
        "wdrożenie w toku — https://github.com/B2B-net-S-A/NEXUS/actions/runs/45723125048"
        in by_pr["#4036"]
    )
    assert "w kolejce, pozycja 1, testy grupy w toku, od 00:14" in by_pr["#4037"]
    assert "pas migracji" in by_pr["#4040"]
    # 225 plików, GraphQL dał 100: nie wiemy, czy zmienia front, więc sprawdza oba
    assert "backend 467995771, front 467995771" in by_pr["#4032"]
    assert by_pr["#99999"] == "#99999 ? nie ma takiego PR-a w B2B-net-S-A/NEXUS"


def test_bez_isInMergeQueue_i_jedno_zapytanie_graphql():
    api = Replay(NIGHT)
    _run(api, NIGHT_NUMBERS)
    graphql = [c for c in api.calls if c[0] == "graphql"]
    assert len(graphql) == 1
    # health i /login raz na bieg, nie raz na PR
    assert [c for c in api.calls if c[0] == "http"] == [
        ("http", gj.HEALTH_URL),
        ("http", gj.LOGIN_URL),
    ]
    assert "isInMergeQueue" not in _PATH.read_text(encoding="utf-8").split('"""', 2)[2]


def test_bez_numerow_szuka_otwartych_i_scalonych_z_okna_godzin():
    api = Replay(RECENT)
    lines = _run(api, [], RECENT["now"], extra=["--godziny", "1"])
    assert lines == RECENT["lines"]
    (key,) = [c[1] for c in api.calls if c[0] == "graphql"]
    assert "is:pr is:open updated:>=2026-11-25T22:44" in key
    assert "is:pr is:merged merged:>=2026-11-25T22:44" in key
    numbers = [int(line.split()[0][1:]) for line in lines]
    assert numbers == sorted(set(numbers)), "bez powtórzeń, rosnąco"


def test_health_503_w_trakcie_wdrozenia_wersja_z_frontu():
    """00:44: /api/health 503 przy restarcie, front już z 467995771."""
    by_pr = {line.split()[0]: line for line in RECENT["lines"]}
    assert by_pr["#4035"].startswith(
        "#4035 ✓ na produkcji wg frontu 467995771 (/api/health: HTTP Error 503: Service Unavailable)"
    )
    assert (
        "#4036 ⏳ scalony 00:36, wdrożenie w toku (/api/health: HTTP Error 503"
        in by_pr["#4036"]
    )


def test_health_i_front_nie_odpowiadaja_nie_zgaduje():
    api = Replay(RECENT)
    api.rec["http"][gj.LOGIN_URL] = {"error": "timed out"}
    api.rec["rest"][DEPLOY_RUNS] = {"workflow_runs": []}
    lines = _run(api, [], RECENT["now"], extra=["--godziny", "1"])
    line = next(line for line in lines if line.startswith("#4035 "))
    assert line.startswith(
        "#4035 ? scalony 00:22, nie umiem odczytać wersji produkcji (/api/health: HTTP Error 503"
    )


# ── kolejka ────────────────────────────────────────────────────────────


def test_wypadl_failed_checks_czerwony_test_z_logu_merge_group():
    api = Replay(NIGHT)
    line = _line(api, _reopened(api.pr(4016), "failed_checks"))
    assert line.startswith(
        "#4016 ✗ wypadł z kolejki 25.11 20:47: czerwone checki grupy — "
        "e2e/responsive-preview.spec.ts › responsywność harnessów — brak poziomego scrolla strony › "
        "/preview/client-invoicing?state=finance mieści się w 360/390/768/1024/1280 px; "
        "bieg https://github.com/B2B-net-S-A/NEXUS/actions/runs/45683206716"
    )
    assert (
        "raw",
        "repos/B2B-net-S-A/NEXUS/actions/jobs/139448859773/logs",
    ) in api.calls


def test_wypadl_log_bez_testow_bierze_blad_joba_a_bez_logu_krok():
    api = Replay(NIGHT)
    pr = _reopened(api.pr(4016), "failed_checks")
    log_path = "repos/B2B-net-S-A/NEXUS/actions/jobs/139448859773/logs"
    api.rec["raw"][log_path] = "\n".join(
        line
        for line in api.rec["raw"][log_path].splitlines()
        if "failed" not in line and "›" not in line
    )
    assert (
        "Frontend (lint + typecheck + build): Harnessy /preview/* nie przechodzą"
        in _line(api, pr)
    )

    api = Replay(NIGHT)
    del api.rec["raw"][log_path]  # log wygasł: odczyt pada, zostaje nazwa joba i kroku
    assert (
        "Frontend (lint + typecheck + build) › Harnessy /preview/* — preview-chromium (Playwright); bieg"
        in _line(api, pr)
    )


def test_wypadl_konflikt_i_recznie_bez_szukania_biegow():
    api = Replay(NIGHT)
    line = _line(api, _reopened(api.pr(4025), "merge_conflict"))
    assert "✗ wypadł z kolejki 25.11 21:21: konflikt z mainem ·" in line
    assert not [
        c for c in api.calls if c[0] in ("rest", "raw") and "merge_group" in c[1]
    ]

    pr = _reopened(api.pr(4035), "manual")
    pr["autoMergeRequest"] = {"enabledAt": "2026-11-25T22:55:00Z"}
    assert (
        "wypadł z kolejki 25.11 23:52: zdjęty ręcznie albo przez pas migracji; auto-merge znów włączony"
        in _line(api, pr)
    )


def test_wypadal_kilka_razy_i_wrocil_do_kolejki():
    api = Replay(NIGHT)
    pr = _reopened(api.pr(4016), "failed_checks")
    pr["timelineItems"]["nodes"] += [
        {"__typename": "AddedToMergeQueueEvent", "createdAt": "2026-11-25T19:55:00Z"},
        {
            "__typename": "RemovedFromMergeQueueEvent",
            "createdAt": "2026-11-25T19:59:00Z",
            "reason": "merge_conflict",
        },
    ]
    assert "✗ wypadł z kolejki 25.11 20:59 (2×): konflikt z mainem" in _line(api, pr)

    pr["mergeQueueEntry"] = {
        "state": "QUEUED",
        "position": 3,
        "enqueuedAt": "2026-11-25T20:05:00Z",
    }
    assert (
        "⏳ w kolejce, pozycja 3, czeka na grupę, od 25.11 21:05; wypadał 2×"
        in _line(api, pr)
    )


def test_kolejka_z_migracja_to_pas_migracji():
    api = Replay(NIGHT)
    pr = copy.deepcopy(api.pr(4040))
    pr["mergeQueueEntry"] = {
        "state": "AWAITING_CHECKS",
        "position": 1,
        "enqueuedAt": "2026-11-25T23:30:00Z",
    }
    assert (
        "⏳ w kolejce (pas migracji), pozycja 1, testy grupy w toku, od 00:30"
        in _line(api, pr)
    )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"isDraft": True}, "#4040 ⏸ draft — do kolejki nie wejdzie ·"),
        (
            {"labels": {"nodes": [{"name": "wstrzymaj"}]}},
            "#4040 ⏸ wstrzymany (etykieta `wstrzymaj`) ·",
        ),
        (
            {"labels": {"nodes": [{"name": "czeka-na-migracje"}]}},
            "#4040 ⏸ pas migracji — czeka na swoją kolej (etykieta `czeka-na-migracje`) ·",
        ),
        (
            {"mergeable": "CONFLICTING"},
            "#4040 ✗ otwarty, konflikt z mainem — do kolejki nie wejdzie ·",
        ),
        ({"state": "CLOSED"}, "#4040 · zamknięty bez scalenia ·"),
        (
            {"autoMergeRequest": None},
            "#4040 · otwarty, bez auto-merge — checki PR-a: czerwone; z migracją — do kolejki wprowadzi go pas migracji ·",
        ),
    ],
)
def test_otwarty_pr_stany_przed_kolejka(change, expected):
    api = Replay(NIGHT)
    pr = copy.deepcopy(api.pr(4040))
    pr.update(change)
    assert _line(api, pr).startswith(expected)


# ── scalony: produkcja, okno, Deploy ─────────────────────────────────


def _daytime(api: Replay) -> None:
    """Produkcja sprzed #4035, biegi Deploy bez tego w toku (w dzień Deploy jest odraczany)."""
    api.health(SHA_BEFORE_4035)
    runs = api.rec["rest"][DEPLOY_RUNS]["workflow_runs"]
    api.rec["rest"][DEPLOY_RUNS] = {
        "workflow_runs": [r for r in runs if r["status"] == "completed"]
    }


def test_scalony_w_dzien_czeka_na_okno_18():
    api = Replay(NIGHT)
    _daytime(api)
    line = _line(
        api, api.pr(4035), now="2026-11-26T09:00:00Z"
    )  # czw. 10:00 w Warszawie
    assert line.startswith(
        "#4035 ⏳ scalony 00:22, czeka na okno 18:00 (produkcja 5d9a855a6) ·"
    )


def test_scalony_okno_otwarte_czeka_na_deploy():
    api = Replay(NIGHT)
    _daytime(api)
    line = _line(api, api.pr(4035), now="2026-11-26T17:30:00Z")  # czw. 18:30
    assert line.startswith(
        "#4035 ⏳ scalony 00:22, okno otwarte — czeka na Deploy (produkcja 5d9a855a6) ·"
    )


def test_scalony_deploy_czerwony():
    api = Replay(NIGHT)
    _daytime(api)
    runs = api.rec["rest"][DEPLOY_RUNS]["workflow_runs"]
    newest = max(runs, key=lambda r: r["created_at"])
    newest["conclusion"] = "failure"
    line = _line(api, api.pr(4035), now="2026-11-26T09:00:00Z")
    assert line.startswith(
        f"#4035 ✗ scalony 00:22, Deploy czerwony — {newest['html_url']} ·"
    )


def test_same_dokumenty_nie_czekaja_na_wdrozenie():
    api = Replay(NIGHT)
    api.health(SHA_BEFORE_4017)
    line = _line(api, api.pr(4017), now="2026-11-25T20:00:00Z")
    assert line.startswith(
        "#4017 ✓ scalony 20:39, same pliki poza obrazem — wdrożenie niepotrzebne (produkcja 1ed9ce043) ·"
    )


def test_front_zostal_w_tyle_za_backendem():
    api = Replay(NIGHT)
    api.front(SHA_BEFORE_4031)
    assert _line(api, api.pr(4031)).startswith(
        "#4031 ⏳ backend na produkcji (467995771), front jeszcze nie (front 251daec59) ·"
    )

    api = Replay(NIGHT)
    api.rec["http"][gj.LOGIN_URL] = "<html>bez baggage</html>"
    assert (
        "? backend na produkcji (467995771), wersji frontu nie umiem odczytać"
        in _line(api, api.pr(4031))
    )


def test_pr_bez_frontu_nie_pyta_o_front():
    api = Replay(NIGHT)
    api.front(SHA_BEFORE_4031)  # stary front nie zmienia nic dla PR-a bez frontend/
    assert _line(api, api.pr(4035)).startswith(
        "#4035 ✓ na produkcji — backend 467995771 ·"
    )


def test_nieznany_sha_jeden_fetch_na_bieg():
    api = Replay(NIGHT)
    api.health("0" * 40)
    pr_a, pr_b = api.pr(4035), api.pr(4017)
    api.only(pr_a, pr_b)
    lines = _run(api, [4035, 4017])
    assert api.fetched == 1
    assert all("git nie zna" in line for line in lines)


# ── okno wdrożeń i drobiazgi ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("local", "open_"),
    [
        ("2026-11-23T07:59", True),  # pon. przed 8:00 — jeszcze noc
        ("2026-11-23T08:00", False),
        ("2026-11-23T17:59", False),
        ("2026-11-23T18:00", True),
        ("2026-11-27T19:00", True),  # pt. wieczór
        ("2026-11-28T12:00", True),  # sobota
        ("2026-11-29T15:00", True),  # niedziela
        ("2026-11-30T09:00", False),  # pon. rano po weekendzie
        ("2026-07-01T07:30", True),  # czas letni
        ("2026-07-01T08:30", False),
    ],
)
def test_okno_wdrozen_pon_pt_18_08_weekend_zawsze(local, open_):
    moment = (
        datetime.fromisoformat(local).replace(tzinfo=gj.WARSAW).astimezone(timezone.utc)
    )
    assert gj.window_open(moment) is open_


def test_numer_z_krzyzykiem_i_blad_numeru():
    assert gj.parse_args(["#4035", "4036"]).numbers == [4035, 4036]
    with pytest.raises(SystemExit):
        gj.parse_args(["abc"])


def test_dlugi_tytul_skrocony():
    api = Replay(NIGHT)
    pr = copy.deepcopy(api.pr(4035))
    pr["title"] = "x" * 100
    assert _line(api, pr).endswith(" · " + "x" * 59 + "…")


def test_blad_graphql_bez_danych_kod_2(capsys):
    class Broken(Replay):
        def graphql(self, op, query, variables):
            raise RuntimeError("gh api graphql: HTTP 502")

    assert (
        gj.main(["4035"], api=Broken(NIGHT), now=_at(NIGHT["now"]), out=lambda _l: None)
        == 2
    )
    assert "HTTP 502" in capsys.readouterr().err
