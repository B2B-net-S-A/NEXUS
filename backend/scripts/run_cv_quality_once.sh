#!/usr/bin/env bash
# Fixed synthetic diagnostic runner; only metrics leave the backend.
set -euo pipefail
umask 077
run_id="${1:-}"; attempt="${2:-}"; models="${3:-}"; count="${4:-}"; revision="${5:-}"
[[ "$run_id" =~ ^[1-9][0-9]{0,19}$ ]] || exit 64
[[ "$attempt" =~ ^[1-9][0-9]{0,2}$ ]] || exit 64
case "$models" in primary|all) ;; *) exit 64;; esac
[[ "$count" =~ ^[1-9][0-9]?$ ]] && [ "$count" -le 40 ] || exit 64
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 64
work_dir=$(mktemp -d "/tmp/nexus-cv-quality-${run_id}-${attempt}.XXXXXX")
cleanup() { rm -f -- "$work_dir/report.json" "$work_dir/report.json.tmp" "$work_dir/process.log"; rmdir -- "$work_dir"; }
trap cleanup EXIT
set +e
timeout --signal=TERM --kill-after=15s 32m python -m scripts.eval_cv_factual_gate \
  --models "$models" --limit "$count" --run-key "${run_id}-${attempt}" \
  --expected-sha "$revision" --output "$work_dir/report.json" >"$work_dir/process.log" 2>&1
rc=$?
set -e
if [ ! -s "$work_dir/report.json" ]; then
  printf '%s\n' '{"complete":false,"stop_reason":"missing_report","results":[]}' >"$work_dir/report.json"
fi
echo '===NEXUS-CV-QUALITY-PAYLOAD-BEGIN==='
base64 -w 0 "$work_dir/report.json"
echo
echo '===NEXUS-CV-QUALITY-PAYLOAD-END==='
echo "CV_QUALITY_EXIT=$rc"
cleanup
trap - EXIT
echo '===NEXUS-CV-QUALITY-END==='
exit "$rc"
