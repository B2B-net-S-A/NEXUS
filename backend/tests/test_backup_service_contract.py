"""Safety contract for the off-site backup sidecar (`backup` in compose).

This service is unusual in that it reads every dataset NEXUS holds — the
database, the candidate CV files and the vector store — and ships them off the
host. That makes a handful of its properties load-bearing for security and for
not repeating past outages, and none of them are enforced by anything else.

Pinning them here rather than trusting review, because each has a plausible
"harmless" edit that quietly breaks it: dropping `:ro` while debugging a
permissions problem, defaulting the kill-switch to true to "make it work", or
pasting a real key while testing.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO / "docker-compose.yml"
_BACKUP_SH = _REPO / "backup" / "backup.sh"
_LOOP_SH = _REPO / "backup" / "loop.sh"
_DRILL = _REPO / ".github" / "workflows" / "backup-drill.yml"
_UPTIME = _REPO / ".github" / "workflows" / "uptime-probe.yml"


def _backup_service() -> dict:
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    services = compose.get("services") or {}
    assert "backup" in services, "the backup sidecar is missing from docker-compose.yml"
    return services["backup"]


def test_data_volumes_are_mounted_read_only() -> None:
    """The sidecar reads application data; it must never be able to write it."""
    volumes = _backup_service().get("volumes") or []
    # Without this the test passes vacuously when the `volumes:` block is
    # deleted altogether: the loop below simply never runs, and the mount it
    # exists to protect is gone while CI stays green.
    assert volumes, (
        "the backup service declares no volume mounts — uploads_data must be "
        "mounted read-only, or the CV files are not being backed up at all"
    )
    for volume in volumes:
        # Only string short-syntax mounts are used here.
        assert isinstance(volume, str), f"unexpected mount syntax: {volume!r}"
        assert volume.endswith(":ro"), (
            f"backup mount {volume!r} is writable. This container exists to read "
            "data, and a write-capable mount turns a backup bug into data loss."
        )


def test_kill_switch_defaults_to_disabled() -> None:
    """Shipping enabled-by-default would start shipping PII off-host on merge."""
    env = _backup_service().get("environment") or {}
    enabled = str(env.get("BACKUP_ENABLED", ""))
    assert "false" in enabled, (
        "BACKUP_ENABLED must default to false. Candidate personal data leaves "
        f"the host when this is on; got {enabled!r}."
    )


def test_no_credentials_are_hardcoded() -> None:
    """Every secret must come from the environment, never from the file."""
    env = _backup_service().get("environment") or {}
    for key in (
        "BACKUP_S3_ACCESS_KEY",
        "BACKUP_S3_SECRET_KEY",
        "BACKUP_AGE_PUBLIC_KEY",
        "POSTGRES_PASSWORD",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        value = str(env.get(key, ""))
        assert value.startswith("${"), (
            f"{key} must be an env substitution, got {value!r} — a literal here "
            "would be committed to the repository."
        )


def test_backup_does_not_publish_ports() -> None:
    """Nothing about this service should be reachable from outside."""
    service = _backup_service()
    assert not service.get("ports"), (
        "the backup sidecar must not publish ports; it initiates outbound "
        "connections only."
    )


def test_scripts_refuse_to_run_without_configuration() -> None:
    """The script must fail closed on missing config, not back up to nowhere."""
    script = (_COMPOSE.parent / "backup" / "backup.sh").read_text(encoding="utf-8")
    for required in (
        "BACKUP_AGE_PUBLIC_KEY",
        "BACKUP_S3_BUCKET",
        "BACKUP_S3_ENDPOINT",
        "BACKUP_S3_ACCESS_KEY",
        "BACKUP_S3_SECRET_KEY",
    ):
        assert f'[ -n "${{{required}:-}}" ] || fail' in script, (
            f"backup.sh must hard-fail when {required} is unset — silently "
            "skipping configuration is how a backup job ends up writing nothing."
        )


def test_retention_is_gated_on_a_clean_run() -> None:
    """Never delete old backups on a night the new ones failed."""
    script = _BACKUP_SH.read_text(encoding="utf-8")
    assert 'if [ "$FAILURES" -eq 0 ]; then' in script, (
        "retention must be conditional on zero failures, otherwise a failing "
        "run prunes the last known-good backups and turns this into a "
        "data-loss system."
    )


# ── The candidate CV corpus ──────────────────────────────────────────────────
# Everything below exists because this dataset — ~136k files, ~37 GB, living
# only in the OBJECT_STORAGE bucket — was backed up by nothing at all while
# docs/disaster-recovery.md claimed it was covered. `pg_dump` preserves
# `candidate_documents.storage_key` and not one byte of the files it points at.


def test_cv_corpus_is_a_backed_up_artefact() -> None:
    script = _BACKUP_SH.read_text(encoding="utf-8")
    assert '"cv_corpus"' in script, (
        "backup.sh no longer records a `cv_corpus` artefact. The candidate CV "
        "files exist in exactly one place; without this the database restores "
        "into rows pointing at documents that no longer exist anywhere."
    )
    assert "cvsrc:" in script, (
        "the CV corpus must be mirrored from the application's own object "
        "storage bucket (rclone remote `cvsrc`); tarring the uploads volume "
        "does NOT cover it — that volume holds generated contract documents."
    )


def test_cv_corpus_credentials_reach_the_sidecar() -> None:
    """A missing variable here silently drops the irreplaceable dataset."""
    env = _backup_service().get("environment") or {}
    for key in (
        "OBJECT_STORAGE_ENDPOINT",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
        "OBJECT_STORAGE_BUCKET",
    ):
        assert key in env, (
            f"{key} is not passed to the backup service, so it cannot read the "
            "CV corpus bucket. The sidecar would back up everything except the "
            "one dataset that cannot be regenerated."
        )


def test_missing_object_storage_config_is_a_failure_not_a_skip() -> None:
    script = _BACKUP_SH.read_text(encoding="utf-8")
    assert 'record "cv_corpus" "error"' in script, (
        "unconfigured object storage must be recorded as a FAILED artefact. "
        "Skipping it quietly reproduces the original bug: a green run whose "
        "manifest simply does not mention the CV files."
    )


def test_cv_mirror_is_not_deleted_by_retention() -> None:
    """The mirror is a live copy of immutable objects, not dated snapshots."""
    script = _BACKUP_SH.read_text(encoding="utf-8")
    assert "--exclude" in script and "candidate-documents/current" in script, (
        "the retention pass deletes by age. Without excluding the CV mirror it "
        "would erase every CV older than the retention window — the backup "
        "would erode into uselessness one day at a time."
    )


def test_cv_sync_cannot_propagate_deletions() -> None:
    script = _BACKUP_SH.read_text(encoding="utf-8")
    assert "--backup-dir" in script, (
        "`rclone sync` mirrors deletions. Without --backup-dir, purging the "
        "source bucket (by accident or otherwise) destroys the only off-site "
        "copy on the very next run."
    )


# ── Failure must be visible ──────────────────────────────────────────────────


def test_every_artefact_has_a_size_gate() -> None:
    """Qdrant shipped without one and recorded a missing object as ok/0 bytes."""
    script = _BACKUP_SH.read_text(encoding="utf-8")
    for artefact, obj in (
        ("postgres", "$pg_object"),
        ("uploads", "$up_object"),
        ("qdrant:${c}", "$q_object"),
    ):
        assert f'gate_and_record "{artefact}" "{obj}"' in script, (
            f"the {artefact} artefact does not run through the shared size "
            "gate. `remote_size` returns 0 when the object is absent, so an "
            "ungated artefact records `ok` with `bytes: 0` — and that clean "
            "run then unblocks retention, deleting the last good copies."
        )
    assert 'record "qdrant:${c}" "ok"' not in script, (
        "the Qdrant branch is recording success without checking the uploaded "
        "object's size."
    )


def test_manifest_upload_failure_is_not_swallowed() -> None:
    script = _BACKUP_SH.read_text(encoding="utf-8")
    assert 'echo "$manifest" | rclone rcat "${DEST}/LATEST.json"' in script
    assert "could not write ${DEST}/LATEST.json" in script, (
        "a failed manifest upload must affect the exit code. Monitoring alarms "
        "on this object's age, so losing it looks identical to the backup "
        "service having died — hours later and with the wrong cause."
    )


def test_loop_retries_before_giving_up_for_the_day() -> None:
    loop = _LOOP_SH.read_text(encoding="utf-8")
    assert "run_backup_with_retries" in loop, (
        "one transient S3 blip must not cost a whole day of backups; the run "
        "is attempted several times before the loop sleeps until tomorrow."
    )
    assert "BACKUP_RETRY_DELAY_SECONDS" in loop, (
        "retries must be spaced out, not immediate"
    )


def test_backup_service_has_a_healthcheck() -> None:
    """A dead scheduler and a hung rclone both showed as `Up N weeks`."""
    service = _backup_service()
    healthcheck = service.get("healthcheck") or {}
    test = healthcheck.get("test") or []
    assert test, (
        "the backup sidecar declares no healthcheck, so neither a dead "
        "scheduler loop nor a run hung inside rclone is visible anywhere."
    )
    assert any("healthcheck.sh" in str(part) for part in test), (
        f"unexpected healthcheck command {test!r}; expected backup/healthcheck.sh"
    )
    assert (_REPO / "backup" / "healthcheck.sh").is_file()


# ── The drill must exercise the real system ──────────────────────────────────


def _uncommented(text: str) -> str:
    """Drop `#` comment lines so prose about a mistake does not read as the mistake."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_drill_restores_the_offsite_backup_not_the_legacy_vps_copy() -> None:
    drill = _uncommented(_DRILL.read_text(encoding="utf-8"))
    assert "/var/backups/nexus" not in drill, (
        "the drill is reading the legacy VPS-local dump again. That copy lives "
        "on the same disk as production and is explicitly disowned by "
        "docs/disaster-recovery.md — restoring it proves nothing about the "
        "off-site backup this repository actually produces."
    )
    assert "LATEST.json" in drill, (
        "the drill must assert the backup is recent and clean"
    )


def test_drill_actually_decrypts() -> None:
    """Encryption is the failure mode with no other symptom."""
    drill = _uncommented(_DRILL.read_text(encoding="utf-8"))
    assert "age -d" in drill, (
        "the drill must decrypt a real artefact. A wrong or lost recipient key "
        "produces backups that upload cleanly, pass every size check, and are "
        "permanently unreadable — `age -d` is the only thing that catches it."
    )
    assert "BACKUP_AGE_PRIVATE_KEY" not in _BACKUP_SH.read_text(encoding="utf-8"), (
        "the private key must never reach the server: the sidecar encrypts to a "
        "public recipient and must not be able to read its own backups."
    )


def test_drill_verifies_the_cv_mirror_against_restored_rows() -> None:
    drill = _uncommented(_DRILL.read_text(encoding="utf-8"))
    assert "storage_key" in drill, (
        "restoring the database proves nothing about the CV files it references. "
        "The drill must sample storage_keys and confirm those objects exist in "
        "the off-site mirror."
    )


def test_drill_fails_when_it_cannot_run() -> None:
    drill = _DRILL.read_text(encoding="utf-8")
    assert "drill cannot run (FAIL)" in drill and "exit 1" in drill, (
        "an unconfigured drill must fail. It previously warned and passed, so "
        "it reported green weekly while restoring nothing, and the DR document "
        "cited those runs as proof the restore path worked."
    )


def test_manifest_has_a_consumer() -> None:
    """LATEST.json with no reader is a log line, not monitoring."""
    uptime = _UPTIME.read_text(encoding="utf-8")
    assert "LATEST.json" in uptime, (
        "nothing reads the backup manifest. 'The backups stopped' must have a "
        "symptom somewhere; without a consumer it has none at all."
    )
    assert "cv_corpus" in uptime, (
        "monitoring must assert the CV corpus artefact is PRESENT, not merely "
        "that the run had no failures — a manifest missing a whole dataset is "
        "otherwise indistinguishable from a clean one."
    )


def _run_sh(snippet: str) -> str:
    """Odpal fragment powłoki w POSIX ``sh`` — tej samej, którą ma kontener.

    ``bash`` NIE nadaje się do tej weryfikacji: dla ``$(( 08 ))`` zachowuje się
    inaczej niż ``ash`` z Alpine, więc test pod bashem przechodziłby dla kodu,
    który na produkcji wywala kontener.
    """
    out = subprocess.run(
        ["sh", "-c", snippet], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, f"powłoka padła: {out.stderr.strip()}"
    return out.stdout.strip()


def _extract_num() -> str:
    """Wytnij PRAWDZIWĄ definicję ``num()`` z backup.sh, nie jej kopię.

    Test na przepisanej ręcznie kopii dowodziłby wyłącznie tego, że kopia
    działa — a to jest dokładnie ta klasa błędu, którą ten plik ma wyłapywać.
    """
    src = (_REPO / "backup" / "backup.sh").read_text(encoding="utf-8")
    m = re.search(r"^num\(\) \{.*?^\}", src, re.S | re.M)
    assert m, "nie znaleziono definicji num() — zmienił się kształt backup.sh"
    return m.group(0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1024", "1024"),
        ("0", "0"),
        # Wiodące zera: bez ich zdjęcia wartość trafia do `$(( ))` jako
        # niepoprawna ósemka i powłoka KOŃCZY się błędem składni.
        ("08", "8"),
        ("09", "9"),
        # Jedno zdjęte zero nie wystarcza — `009` zostawało jako `09`.
        ("009", "9"),
        ("000", "0"),
        # Nie-liczby mają dawać 0, żeby awaria odczytu nie zapisała się
        # jako czysty artefakt (patrz komentarz przy num()).
        ("", "0"),
        ("abc", "0"),
        ("0x10", "0"),
        ("12abc", "0"),
    ],
)
def test_num_normalises_leading_zeros_so_arithmetic_cannot_explode(
    raw: str, expected: str
) -> None:
    body = _extract_num()
    got = _run_sh(f'{body}\nnum "{raw}"')
    assert got == expected, f"num({raw!r}) = {got!r}, oczekiwano {expected!r}"
    # Dowód właściwy: wynik MUSI przejść przez arytmetykę bez wybuchu.
    _run_sh(f'{body}\nv=$(num "{raw}"); : $(( v + 1 ))')


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2", "2"),
        ("08", "8"),
        ("009", "9"),
        ("00", "0"),
        ("0", "0"),
        ("23", "23"),
        ("24", "2"),  # poza zakresem -> domyślna
        ("02:00", "2"),  # nie-liczba -> domyślna
        ("", "2"),
    ],
)
def test_backup_hour_survives_every_value_a_human_may_type(
    raw: str, expected: str
) -> None:
    """``BACKUP_HOUR_UTC=08`` ZABIJAŁ kontener — i to była cicha śmierć.

    Błąd arytmetyki ósemkowej kończył ``loop.sh`` przed pierwszym ``sleep``,
    ``restart: unless-stopped`` podnosił kontener, i tak w kółko. Kopia nie
    powstawała NIGDY, a jedynym śladem był licznik restartów w ``docker ps``,
    którego nikt nie ogląda. ``08`` to zupełnie naturalna rzecz do wpisania
    w pole „godzina", więc to nie jest przypadek brzegowy.
    """
    src = (_REPO / "backup" / "loop.sh").read_text(encoding="utf-8")
    m = re.search(r'^HOUR="\$\{BACKUP_HOUR_UTC:-2\}".*?^fi$', src, re.S | re.M)
    assert m, "nie znaleziono normalizacji HOUR — zmienił się kształt loop.sh"
    snippet = f'BACKUP_HOUR_UTC="{raw}"\n{m.group(0)}\necho "$HOUR"'
    got = _run_sh(snippet + "\n: $(( HOUR * 3600 ))")
    assert got.splitlines()[-1] == expected, f"HOUR({raw!r}) -> {got!r}"
