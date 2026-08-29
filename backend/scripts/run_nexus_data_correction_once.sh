#!/usr/bin/env bash
# Container-local privacy boundary for the Nexus.xlsx correction audit/apply.

set -euo pipefail
umask 077

parse_cli_args() {
  local selected_mode="$1"
  shift
  cli_args=("$@")
  plan_fingerprint=""
  approval_fingerprint=""
  if [ "$selected_mode" = "apply" ]; then
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --fingerprint)
          [ -z "$plan_fingerprint" ] && [ "$#" -ge 2 ] || {
            echo "nexus data correction wrapper: invalid fingerprint arguments" >&2
            return 64
          }
          plan_fingerprint="$2"
          shift 2
          ;;
        --approval-fingerprint)
          [ -z "$approval_fingerprint" ] && [ "$#" -ge 2 ] || {
            echo "nexus data correction wrapper: invalid approval arguments" >&2
            return 64
          }
          approval_fingerprint="$2"
          shift 2
          ;;
        *)
          echo "nexus data correction wrapper: invalid apply arguments" >&2
          return 64
          ;;
      esac
    done
    [ -n "$plan_fingerprint" ] && [ -n "$approval_fingerprint" ] || {
      echo "nexus data correction wrapper: incomplete apply arguments" >&2
      return 64
    }
  elif [ "$#" -ne 0 ]; then
    echo "nexus data correction wrapper: audit does not accept apply arguments" >&2
    return 64
  fi
}

if [ "${NEXUS_DATA_CORRECTION_WRAPPER_LIB_ONLY:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

mode="${1:-}"
run_id="${2:-}"
run_attempt="${3:-}"
shift 3 || true

case "$mode" in
  audit|apply) ;;
  *) echo "nexus data correction wrapper: invalid mode" >&2; exit 64 ;;
esac
case "$run_id:$run_attempt" in
  *[!0-9:]*|:|*:|0:*|*:0)
    echo "nexus data correction wrapper: invalid run identity" >&2
    exit 64
    ;;
esac

parse_cli_args "$mode" "$@" || exit $?

global_lock="/tmp/nexus-data-correction-global-lock"
if ! mkdir -- "$global_lock"; then
  echo "nexus data correction wrapper: another or ambiguous run owns the lock" >&2
  exit 75
fi

work_dir=""
full_report=""
redacted_report=""
apply_redacted_report=""
intent_report=""
post_audit_full_report=""
post_audit_redacted_report=""
process_log=""
post_audit_log=""

cleanup() {
  if [ -n "$work_dir" ]; then
    rm -f -- \
      "$full_report" \
      "$redacted_report" \
      "$apply_redacted_report" \
      "$intent_report" \
      "$post_audit_full_report" \
      "$post_audit_redacted_report" \
      "$process_log" \
      "$post_audit_log" || return 1
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

work_dir=$(mktemp -d "/tmp/nexus-data-correction-${run_id}-${run_attempt}.XXXXXX")
full_report="$work_dir/full.json"
redacted_report="$work_dir/redacted.json"
apply_redacted_report="$work_dir/apply-redacted.json"
intent_report="$work_dir/precommit-intent.json"
post_audit_full_report="$work_dir/post-audit-full.json"
post_audit_redacted_report="$work_dir/post-audit-redacted.json"
process_log="$work_dir/process.log"
post_audit_log="$work_dir/post-audit.log"

cli_redacted_report="$redacted_report"
intent_args=()
operation_timeout="12m"
if [ "$mode" = "apply" ]; then
  cli_redacted_report="$apply_redacted_report"
  intent_args=(--intent-output "$intent_report")
  operation_timeout="8m"
fi

set +e
timeout --signal=TERM --kill-after=15s "$operation_timeout" python -m scripts.correct_nexus_orders_contracts \
  --mode "$mode" \
  --manifest app/data/nexus_contract_correction_2026_08.json \
  --output "$full_report" \
  --redacted-output "$cli_redacted_report" \
  "${intent_args[@]}" \
  "${cli_args[@]}" >"$process_log" 2>&1
operation_rc=$?
set -e

if [ "$mode" = "apply" ]; then
  # Reconciliation is mandatory after every APPLY attempt. The first process
  # may have died after COMMIT but before its normal report; the fsynced intent
  # plus this fresh read-only audit makes that outcome observable without a new
  # database table or schema change.
  set +e
  timeout --signal=TERM --kill-after=15s 4m python -m scripts.correct_nexus_orders_contracts \
    --mode audit \
    --manifest app/data/nexus_contract_correction_2026_08.json \
    --output "$post_audit_full_report" \
    --redacted-output "$post_audit_redacted_report" \
    >"$post_audit_log" 2>&1
  post_audit_rc=$?
  python -m scripts.reconcile_nexus_data_correction \
    --intent "$intent_report" \
    --apply-report "$apply_redacted_report" \
    --post-audit-report "$post_audit_redacted_report" \
    --output "$redacted_report" \
    --plan-fingerprint "$plan_fingerprint" \
    --apply-exit-code "$operation_rc" \
    --post-audit-exit-code "$post_audit_rc"
  operation_rc=$?
  set -e
fi

if [ ! -s "$redacted_report" ]; then
  echo "nexus data correction wrapper: no redacted report" >&2
  exit "${operation_rc:-70}"
fi

echo '===NEXUS-DATA-CORRECTION-PAYLOAD-BEGIN==='
base64 -w 0 "$redacted_report"
echo
echo '===NEXUS-DATA-CORRECTION-PAYLOAD-END==='

cleanup
trap - EXIT HUP INT TERM
echo '===NEXUS-DATA-CORRECTION-END==='
exit "$operation_rc"
