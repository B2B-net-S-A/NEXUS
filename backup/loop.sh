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

HOUR="${BACKUP_HOUR_UTC:-2}"
RUN_ON_START="${BACKUP_RUN_ON_START:-false}"

echo "[backup-loop] started; daily at ${HOUR}:00 UTC; enabled=${BACKUP_ENABLED:-false}"

# Running once at boot makes a misconfiguration visible within minutes of the
# deploy rather than at 02:00, when nobody is looking. Off by default so a
# routine redeploy does not trigger a full backup every time.
if [ "$RUN_ON_START" = "true" ]; then
    echo "[backup-loop] BACKUP_RUN_ON_START=true — running immediately"
    /usr/local/bin/backup.sh || echo "[backup-loop] initial run failed (see above)" >&2
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
    /usr/local/bin/backup.sh || echo "[backup-loop] run failed; will retry tomorrow" >&2

    # Guard against drift: if the run finished within the same hour, wait past
    # it so the loop cannot fire twice in one day.
    sleep 3600
done
