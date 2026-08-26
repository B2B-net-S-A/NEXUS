#!/usr/bin/env bash
# Container-local privacy boundary for the contract-merge CLI.
#
# The full report can contain names, rates and draft fields.  It never leaves
# this mode-0700 temporary directory.  A redacted report is emitted only after
# the Python process finishes, and the success sentinel is emitted only after
# every temporary file has been removed successfully.

set -euo pipefail
umask 077

mode="${1:-}"
run_id="${2:-}"
run_attempt="${3:-}"
shift 3 || true

case "$mode" in
  audit|apply) ;;
  *) echo "contract merge wrapper: invalid mode" >&2; exit 64 ;;
esac
case "$run_id:$run_attempt" in
  *[!0-9:]*|:|*:|0:*|*:0)
    echo "contract merge wrapper: invalid run identity" >&2
    exit 64
    ;;
esac

global_lock="/tmp/nexus-contract-merge-global-lock"
if ! mkdir -- "$global_lock"; then
  echo "contract merge wrapper: another or ambiguous run still owns the lock" >&2
  exit 75
fi

work_dir=""
full_report=""
redacted_report=""
process_log=""

cleanup() {
  if [ -n "$work_dir" ]; then
    rm -f -- "$full_report" "$redacted_report" "$process_log" || return 1
    rmdir -- "$work_dir" || return 1
  fi
  rmdir -- "$global_lock" || return 1
}

on_signal() {
  cleanup || true
  exit 143
}

trap 'cleanup || true' EXIT
trap on_signal HUP INT TERM

work_dir=$(mktemp -d "/tmp/nexus-contract-merge-${run_id}-${run_attempt}.XXXXXX")
full_report="$work_dir/full.json"
redacted_report="$work_dir/redacted.json"
process_log="$work_dir/process.log"

set +e
timeout --signal=TERM --kill-after=15s 12m python -m scripts.merge_duplicate_contracts \
  --mode "$mode" \
  --manifest app/data/contract_merge_2026_08.json \
  --output "$full_report" \
  --redacted-output "$redacted_report" \
  "$@" >"$process_log" 2>&1
operation_rc=$?
set -e

if [ ! -s "$redacted_report" ]; then
  echo "contract merge wrapper: no redacted report" >&2
  exit "${operation_rc:-70}"
fi

echo '===NEXUS-CONTRACT-MERGE-PAYLOAD-BEGIN==='
base64 -w 0 "$redacted_report"
echo
echo '===NEXUS-CONTRACT-MERGE-PAYLOAD-END==='

# Do not announce completion until sensitive files are demonstrably gone.
cleanup
trap - EXIT HUP INT TERM
echo '===NEXUS-CONTRACT-MERGE-END==='
exit "$operation_rc"
