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


def _stub_network_and_clock(tmp_path: Path, payloads: tuple[str, ...]) -> Path:
    """Katalog z `curl` i `sleep` na początek `PATH`; treść kroku zostaje 1:1.

    `curl` oddaje kolejne payloady (ostatni powtarza), `sleep` tylko zapisuje
    przerwę, żeby test nie czekał na nią naprawdę.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp_path / "reads").unlink(missing_ok=True)
    (tmp_path / "sleeps").unlink(missing_ok=True)
    for number, payload in enumerate(payloads, start=1):
        (tmp_path / f"health-{number}.json").write_text(payload, encoding="utf-8")
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/bin/bash\n"
        'echo x >> "$STUB_DIR/reads"\n'
        'read_no=$(wc -l < "$STUB_DIR/reads")\n'
        f'[ "$read_no" -le {len(payloads)} ] || read_no={len(payloads)}\n'
        'cat "$STUB_DIR/health-$((read_no)).json"\n',
        encoding="utf-8",
    )
    sleep = bin_dir / "sleep"
    sleep.write_text('#!/bin/bash\necho "$1" >> "$STUB_DIR/sleeps"\n', encoding="utf-8")
    curl.chmod(0o755)
    sleep.chmod(0o755)
    return bin_dir


def _reads(tmp_path: Path) -> int:
    return len((tmp_path / "reads").read_text(encoding="utf-8").splitlines())


def _sleeps(tmp_path: Path) -> list[int]:
    path = tmp_path / "sleeps"
    if not path.exists():
        return []
    return [int(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _run(tmp_path: Path, *payloads: str) -> tuple[int, dict[str, str], list[str]]:
    bin_dir = _stub_network_and_clock(tmp_path, payloads)
    script = tmp_path / "classify.sh"
    script.write_text(_classify_step()["run"], encoding="utf-8")
    outputs = tmp_path / "outputs.txt"
    summary = tmp_path / "summary.md"
    outputs.write_text("", encoding="utf-8")
    summary.touch()
    proc = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/local/bin",
            "STUB_DIR": str(tmp_path),
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
def test_paused_notification_policy_does_not_hide_provider_failure(
    tmp_path: Path,
) -> None:
    rc, outputs, annotations = _run(
        tmp_path,
        _payload(notification_email_policy="disabled", m365_mail="degraded"),
    )
    assert rc == 0
    assert any("m365_mail" in item for item in annotations)
    assert not any("notification_email_policy" in item for item in annotations)


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
def test_stalled_background_loop_opens_the_alarm(tmp_path: Path) -> None:
    """MON-04: wartość z `loop_heartbeat.health_value` musi trafić w regex severity.

    Pętla żyje (`done() == False`), ale nie iteruje — np. zawieszony await na
    dostawcy bez timeoutu. Bez tego alarmu synchronizacja stoi przy zielonym
    `status`.
    """
    from app.services.loop_heartbeat import health_value

    rc, outputs, annotations = _run(
        tmp_path, _payload(background_tasks=health_value(["m365"]))
    )
    assert rc == 0
    assert outputs["fail"] == "1"
    assert any(a.startswith("::error") and "background_tasks" in a for a in annotations)


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


# ── Drugi odczyt przed alarmem o checkach (#3215) ────────────────────────────
# Bieg 42531906696 z 08.11.2026 trafił w Deploy 42531136042 i zgłosił worker
# jako padnięty, choć 40 s później `/api/health` był zdrowy.

WORKER_DOWN = _payload(
    background_tasks="unhealthy: worker nie odpowiada (ConnectError)"
)


@requires_jq
def test_worker_restart_blip_does_not_open_the_alarm(tmp_path: Path) -> None:
    rc, outputs, annotations = _run(
        tmp_path, WORKER_DOWN, _payload(background_tasks="healthy")
    )
    assert rc == 0
    assert outputs["fail"] == "0"
    assert outputs["checked"] == "1", "zdrowy drugi odczyt ma móc zamknąć alarm"
    assert not [a for a in annotations if a.startswith("::error")]
    assert _reads(tmp_path) == 2
    assert len(_sleeps(tmp_path)) == 1
    assert 60 <= _sleeps(tmp_path)[0] <= 90


@requires_jq
def test_worker_still_down_on_second_read_opens_the_alarm(tmp_path: Path) -> None:
    rc, outputs, annotations = _run(tmp_path, WORKER_DOWN, WORKER_DOWN)
    assert rc == 0
    assert outputs["fail"] == "1"
    assert any(a.startswith("::error") and "background_tasks" in a for a in annotations)
    assert _reads(tmp_path) == 2


@requires_jq
def test_second_read_can_report_a_different_failure(tmp_path: Path) -> None:
    """Alarm opisuje stan z drugiego odczytu, nie ten sprzed przerwy."""
    rc, outputs, annotations = _run(
        tmp_path, WORKER_DOWN, _payload(background_tasks="healthy", voyage="unhealthy")
    )
    assert rc == 0
    assert outputs["fail"] == "1"
    errors = [a for a in annotations if a.startswith("::error")]
    assert len(errors) == 1 and "voyage" in errors[0]


@requires_jq
def test_healthy_first_read_does_not_wait(tmp_path: Path) -> None:
    rc, outputs, _ = _run(tmp_path, _payload(background_tasks="healthy"))
    assert rc == 0
    assert outputs["fail"] == "0"
    assert _reads(tmp_path) == 1
    assert _sleeps(tmp_path) == []


@requires_jq
def test_warning_alone_does_not_wait(tmp_path: Path) -> None:
    """`degraded` bywa stanem na całe dni, przerwa nic by mu nie dała."""
    rc, outputs, _ = _run(tmp_path, _payload(traffit="degraded"))
    assert rc == 0
    assert outputs["fail"] == "0"
    assert _sleeps(tmp_path) == []


@requires_jq
def test_backend_gone_on_second_read_stays_with_probe(tmp_path: Path) -> None:
    """Web w trakcie restartu: alarmuje job `probe`, a stary alarm nie jest zamykany."""
    rc, outputs, annotations = _run(
        tmp_path, WORKER_DOWN, "<html>502 Bad Gateway</html>"
    )
    assert rc == 0
    assert outputs["fail"] == "0"
    assert "checked" not in outputs
    assert not [a for a in annotations if a.startswith("::error")]


@requires_jq
def test_run_helper_starts_clean_on_the_same_tmp_path(tmp_path: Path) -> None:
    """`_run` importuje też `test_fix48_ws13_traffit_tails` i woła go dwa razy."""
    _, outputs, _ = _run(tmp_path, WORKER_DOWN, WORKER_DOWN)
    assert outputs["fail"] == "1"

    _, outputs, _ = _run(tmp_path, _payload(traffit="degraded"))
    assert outputs["fail"] == "0"
    assert _reads(tmp_path) == 1
    assert _sleeps(tmp_path) == []


def test_health_checks_timeout_covers_both_reads() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # Dwa odczyty po 20 s i przerwa 75 s to 115 s, do tego start, checkout i issue.
    # Ucięty job nie otworzyłby alarmu.
    assert workflow["jobs"]["health-checks"]["timeout-minutes"] >= 4


# ── Ponawianie w sondzie dostępności (#995) ──────────────────────────────────
# Restart przy wdrożeniu trwa kilkanaście sekund i daje prawdziwy 503. Jedna
# próba zgłaszała go jako awarię (bieg 40804600445 z 29.10.2026, w czasie
# Deploya 40803619177). Awaria trwa dłużej niż trzy próby co 20 s.


@pytest.mark.parametrize("step_name", ["Frontend", "Backend health"])
def test_probe_step_retries_before_it_fails(step_name: str) -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(s for s in workflow["jobs"]["probe"]["steps"] if s["name"] == step_name)
    assert "--retry 2 --retry-delay 20 --retry-all-errors" in step["run"]


def test_probe_timeout_covers_every_attempt() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # Dwa kroki po 3 próby (15 s) i 2 przerwy (20 s) to 170 s, do tego TLS i start.
    assert workflow["jobs"]["probe"]["timeout-minutes"] >= 5
