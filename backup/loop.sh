#!/bin/sh
# Scheduler for the backup sidecar.
#
# An in-container loop rather than a host cron or a GitHub Actions schedule:
# host cron would need SSH to install (which we do not have), and GHA bills
# rounded-up minutes per run for something that must happen daily forever.
# This also keeps the schedule versioned in the repo instead of living as
# undocumented state on a VPS -- the exact failure mode that left the previous
# backup script unreviewable.
set -eu
# Spójnie z backup.sh: brak potoków dziś, ale gdyby ktoś dopisał `a | b`,
# pipefail od razu daje poprawny status zamiast maskowania błędu ostatnim etapem.
set -o pipefail

# Godzina startu jest JEDYNĄ liczbą, którą operator wpisuje ręcznie do vaulta
# Coolify — i trafia wprost do `$(( HOUR * 3600 ))` niżej. Dwie pułapki, obie
# kończące się tak samo:
#
#   • `08`/`09` — w arytmetyce POSIX-owej wiodące zero znaczy ÓSEMKOWO, a te
#     dwie wartości nie są poprawnymi liczbami ósemkowymi. `$(( 08 * 3600 ))`
#     to błąd składni, na którym powłoka KOŃCZY się natychmiast.
#   • cokolwiek nieliczbowego (`2:00`, `02:00 UTC`, spacja) — to samo.
#
# Skutek jest za każdym razem ten sam i przewrotnie cichy: kontener wstaje,
# umiera przed pierwszym `sleep`, `restart: unless-stopped` podnosi go znowu,
# i tak w kółko. Backup nie powstaje nigdy, a jedynym śladem jest licznik
# restartów w `docker ps`, którego nikt nie ogląda. Kod niżej strzeże się przed
# ósemkami przy odczycie ZEGARA (`now_h`), ale nie strzegł się przy wartości,
# którą naprawdę wpisuje człowiek.
HOUR="${BACKUP_HOUR_UTC:-2}"
HOUR="${HOUR#0}"; HOUR="${HOUR:-0}"
case "$HOUR" in
    ''|*[!0-9]*)
        echo "[backup-loop] BACKUP_HOUR_UTC='${BACKUP_HOUR_UTC:-}' nie jest liczbą — używam 2:00 UTC" >&2
        HOUR=2
        ;;
esac
if [ "$HOUR" -gt 23 ]; then
    echo "[backup-loop] BACKUP_HOUR_UTC='${BACKUP_HOUR_UTC:-}' poza 0-23 — używam 2:00 UTC" >&2
    HOUR=2
fi
RUN_ON_START="${BACKUP_RUN_ON_START:-false}"
RETRIES="${BACKUP_RETRIES:-3}"
RETRY_DELAY="${BACKUP_RETRY_DELAY_SECONDS:-900}"

HEARTBEAT=/tmp/backup-heartbeat
RUN_MARKER=/tmp/backup-run-started

# Liveness signal for the compose healthcheck (backup/healthcheck.sh). A
# detached ticker rather than a touch inside the main loop, because the main
# loop spends ~24h in a single `sleep` and hours inside a run: without an
# independent tick, "container wedged" and "container waiting, as designed"
# look identical from outside, which is why a hung rclone was invisible.
: > "$HEARTBEAT"
while true; do
    : > "$HEARTBEAT"
    sleep 30
done &

# A run in progress is marked with a file, so the healthcheck can distinguish
# "working" from "stuck working" (see BACKUP_MAX_RUN_SECONDS).
run_backup() {
    date -u +%s > "$RUN_MARKER"
    _rc=0
    /usr/local/bin/backup.sh || _rc=$?
    rm -f "$RUN_MARKER"
    return "$_rc"
}

# One night's transient failure (S3 blip, Qdrant restarting mid-snapshot) used
# to cost a whole day of backups: the run was attempted exactly once and the
# loop then slept until tomorrow. Retry a few times before giving up.
run_backup_with_retries() {
    _attempt=1
    while true; do
        if run_backup; then
            return 0
        fi
        if [ "$_attempt" -ge "$RETRIES" ]; then
            echo "[backup-loop] run failed after ${_attempt} attempt(s); giving up until tomorrow" >&2
            return 1
        fi
        echo "[backup-loop] attempt ${_attempt}/${RETRIES} failed; retrying in ${RETRY_DELAY}s" >&2
        sleep "$RETRY_DELAY"
        _attempt=$((_attempt + 1))
    done
}

echo "[backup-loop] started; daily at ${HOUR}:00 UTC; enabled=${BACKUP_ENABLED:-false}; retries=${RETRIES}"

# Running once at boot makes a misconfiguration visible within minutes of the
# deploy rather than at 02:00, when nobody is looking. Off by default so a
# routine redeploy does not trigger a full backup every time.
if [ "$RUN_ON_START" = "true" ]; then
    echo "[backup-loop] BACKUP_RUN_ON_START=true — running immediately"
    run_backup_with_retries || echo "[backup-loop] initial run failed (see above)" >&2
fi

while true; do
    now_h="$(date -u +%H)"
    now_m="$(date -u +%M)"
    now_s="$(date -u +%S)"
    # Strip leading zeros so `08` is not parsed as invalid octal by $(( )).
    now_h="${now_h#0}"; now_h="${now_h:-0}"
    now_m="${now_m#0}"; now_m="${now_m:-0}"
    now_s="${now_s#0}"; now_s="${now_s:-0}"

    now_secs=$(( now_h * 3600 + now_m * 60 + now_s ))
    target_secs=$(( HOUR * 3600 ))
    sleep_secs=$(( target_secs - now_secs ))
    [ "$sleep_secs" -le 0 ] && sleep_secs=$(( sleep_secs + 86400 ))

    echo "[backup-loop] next run in ${sleep_secs}s"
    sleep "$sleep_secs"

    # A failing backup must not kill the scheduler, or one bad night silently
    # ends all future backups -- the container would sit "restarting" or exited
    # and the next failure would never even be attempted.
    run_backup_with_retries || echo "[backup-loop] run failed; will retry tomorrow" >&2

    # Guard against drift: if the run finished within the same hour, wait past
    # it so the loop cannot fire twice in one day.
    sleep 3600
done
