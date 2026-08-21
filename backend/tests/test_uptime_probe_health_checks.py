"""Sonda `/api/health` musi mieć czytelnika dla WSZYSTKICH checków, nie tylko bazy.

`/api/health` wylicza kilkanaście checków (`traffit`, `qdrant`, `voyage`,
`ai_features`, `background_tasks`, …), z których każdy powstał po konkretnym
incydencie. Żaden z nich nie przestawia `status` — to robi wyłącznie
`checks.database` (`app/main.py`: `overall = "healthy" if db_healthy else
"unhealthy"`). Jedyny automatyczny konsument endpointu asertował
`.status != "unhealthy"`, więc realnie wykrywał tylko martwą bazę — czyli tę
awarię, która i tak kładzie aplikację. Reszta pracy diagnostycznej szła do
kanału bez odbiorcy: `voyage: unhealthy` przy `status: healthy` znaczy, że
embeddingi przestały powstawać, a wyszukiwanie po cichu serwuje stary indeks.

Job `health-checks` w `.github/workflows/uptime-probe.yml` jest tym odbiorcą.
Ten plik odpala JEGO WŁASNY skrypt (wyjęty z YAML-a, z podmienionym wyłącznie
pobraniem z sieci) na ustalonych payloadach — bo regresja jest tu z gruntu
cicha: wystarczy dopisać stan do allowlisty albo poluzować regex severity, żeby
alarm przestał istnieć, a cron dalej świecił na zielono. Test na strukturze
(„job istnieje") tego nie łapie; test na zachowaniu — łapie.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/uptime-probe.yml"

# Stany, w których coś JEST zepsute i ma właściciela — muszą kończyć się
# otwarciem issue i czerwonym biegiem.
HARD_FAILURE_STATES = ("unhealthy", "misconfigured", "critical", "crashed: x")


def _classify_step() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["health-checks"]["steps"][0]


def _script(tmp_path: Path) -> Path:
    """Skrypt kroku 1:1, z podmienionym TYLKO `curl` na odczyt fixture'u."""
    run = _classify_step()["run"]
    patched, subs = re.subn(
        r"body=\$\(curl.*?\|\| true\)", 'body=$(cat "$FIXTURE")', run, flags=re.S
    )
    assert subs == 1, "nie rozpoznano pobrania /api/health w kroku 'Classify .checks'"
    path = tmp_path / "classify.sh"
    path.write_text(patched, encoding="utf-8")
    return path


def _run(tmp_path: Path, payload: str) -> tuple[int, dict[str, str], list[str]]:
    fixture = tmp_path / "health.json"
    fixture.write_text(payload, encoding="utf-8")
    outputs = tmp_path / "outputs.txt"
    summary = tmp_path / "summary.md"
    outputs.touch()
    summary.touch()
    proc = subprocess.run(
        ["bash", str(_script(tmp_path))],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "FIXTURE": str(fixture),
            "GITHUB_OUTPUT": str(outputs),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
    )
    parsed: dict[str, str] = {}
    for line in outputs.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(("-", "CLASSIFIED_EOF")):
            key, _, value = line.partition("=")
            parsed.setdefault(key, value)
    annotations = [
        line
        for line in proc.stdout.splitlines()
        if line.startswith(("::error", "::warning"))
    ]
    return proc.returncode, parsed, annotations


def _payload(**checks: str) -> str:
    # `status` zawsze "healthy" — o to w tym całym znalezisku chodzi: awaria
    # dowolnego checku poza bazą NIE rusza `status`, więc payload, na którym
    # alarm ma zadziałać, jest z punktu widzenia starej sondy nie do odróżnienia
    # od zdrowego.
    return json.dumps(
        {"status": "healthy", "checks": {"database": "healthy", **checks}}
    )


requires_jq = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("bash") is None,
    reason="krok używa jq+bash; runner GitHuba ma oba, lokalny obraz nie zawsze",
)


def test_job_exists_and_never_reads_status() -> None:
    """Job musi istnieć i NIE MOŻE bramkować się na `.status`.

    Gdyby czytał `.status`, byłby kopią starej sondy: `.status` zależy wyłącznie
    od bazy, więc każdy inny check dalej nie miałby czytelnika. Osobno: `.status`
    steruje kodem 503, który restartuje kontener i wywala deploy — ten job ma
    otwierać issue, a nie kłaść produkcji.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["health-checks"]
    assert job["permissions"]["issues"] == "write", "bez tego nie otworzy issue"
    body = _classify_step()["run"]
    assert ".checks" in body
    assert ".status" not in body, (
        "job ma czytać `.checks`, nie `.status` (patrz docstring)"
    )


def test_allowlist_cannot_silence_a_real_failure() -> None:
    """Allowlista wycisza stany OCZEKIWANE (wyłączony kill-switch), nie awarie.

    Dopisanie tu `unhealthy` byłoby jednolinijkowym, niewidocznym wyłączeniem
    całego alarmu — dokładnie ta klasa regresji, dla której ten plik powstał.
    """
    body = _classify_step()["run"]
    match = re.search(r"ALLOWLIST='(\{.*?\})'", body)
    assert match, "nie znaleziono literału ALLOWLIST"
    allowlist = json.loads(match.group(1))
    for check, states in allowlist.items():
        for state in states:
            assert not state.startswith(
                ("unhealthy", "misconfigured", "critical", "crashed")
            ), f"allowlista wycisza realną awarię: {check}={state}"


@requires_jq
def test_production_payload_stays_green_but_reports_warnings(tmp_path: Path) -> None:
    """Payload produkcji z 2026-08-21: żadnej awarii, ale trzy rzeczy do wiedzenia.

    `voyage`/`reranker` = `unknown` (dostawca nietknięty od startu procesu — w
    `app/main.py` świadomie NIE jest to zaliczone jako sukces) oraz
    `ai_features: uncapped: …` (brak sufitu wydatków przy fail-open quota).
    Twarde padanie na tych stanach dałoby czerwień permanentną, a stały alarm
    jest tak samo niewidoczny jak brak alarmu — stąd tylko ostrzeżenia.
    """
    payload = _payload(
        m365="healthy",
        autenti="unconfigured",
        traffit="healthy",
        qdrant="healthy",
        priority_work="disabled",
        anthropic="configured",
        voyage="unknown",
        reranker="unknown",
        ai_features="uncapped: scoring,cv_parser",
        disk="healthy",
    )
    rc, outputs, annotations = _run(tmp_path, payload)
    assert rc == 0
    assert outputs["fail"] == "0"
    assert not [a for a in annotations if a.startswith("::error")]
    warned = " ".join(annotations)
    assert "voyage" in warned and "ai_features" in warned


@requires_jq
def test_expected_off_states_are_silent(tmp_path: Path) -> None:
    """`autenti=unconfigured` i `priority_work=disabled` to wyłączone kill-switche.

    Bez allowlisty hałasowałyby przy KAŻDYM biegu, a nowy check zaczynałby życie
    już na czerwono — czyli ucząc, żeby ignorować ten kanał.
    """
    rc, outputs, annotations = _run(
        tmp_path,
        _payload(
            autenti="unconfigured", priority_work="disabled", anthropic="configured"
        ),
    )
    assert rc == 0
    assert outputs["fail"] == "0"
    assert annotations == []


@requires_jq
@pytest.mark.parametrize("state", HARD_FAILURE_STATES)
def test_hard_failure_opens_the_alarm(tmp_path: Path, state: str) -> None:
    """Scenariusz z audytu: Voyage pada, `status` nadal `healthy`.

    Embeddingi przestają powstawać, wyszukiwanie serwuje stary indeks i wygląda
    na działające. To jest ten sam kształt co awaria Qdranta z 2026-07-28.
    """
    rc, outputs, annotations = _run(tmp_path, _payload(voyage=state))
    assert rc == 0, "sam krok klasyfikujący nie pada — pada dopiero krok 'Fail run'"
    assert outputs["fail"] == "1", f"stan {state!r} musi otwierać alarm"
    assert any(a.startswith("::error") and "voyage" in a for a in annotations)


@requires_jq
def test_degraded_warns_but_does_not_page(tmp_path: Path) -> None:
    """`degraded` bywa stanem operacyjnym na całe dni (np. sync Traffita).

    Gdyby otwierał issue, kanał zostałby zapchany na stałe i przestałby cokolwiek
    znaczyć — a wtedy `unhealthy` obok też nikogo by nie wywołał.
    """
    rc, outputs, annotations = _run(
        tmp_path, _payload(traffit="degraded", fx="degraded: stale 9d")
    )
    assert rc == 0
    assert outputs["fail"] == "0"
    assert len([a for a in annotations if a.startswith("::warning")]) == 2


@requires_jq
def test_unreachable_backend_does_not_double_alarm(tmp_path: Path) -> None:
    """Backend leżący ma już głośnego czytelnika: job `probe` wyżej.

    Drugi alarm o innej treści na to samo zdarzenie tylko utrudnia diagnozę,
    więc tutaj zostaje ostrzeżenie i zielony bieg.
    """
    rc, outputs, annotations = _run(tmp_path, "<html>502 Bad Gateway</html>")
    assert rc == 0
    assert outputs["fail"] == "0"
    assert all(a.startswith("::warning") for a in annotations)
