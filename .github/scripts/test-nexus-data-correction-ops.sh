#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test_dir=$(mktemp -d)
cleanup_test() {
  rm -f -- \
    "$test_dir/curl.log" \
    "$test_dir/delete.done" \
    "$test_dir/ownership.ok" \
    "$test_dir/create.json" \
    "$test_dir/audit.json" \
    "$test_dir/apply.json" \
    "$test_dir/projected.json" \
    "$test_dir/large-report.json" \
    "$test_dir/large-report-plain.b64" \
    "$test_dir/large-report.b64" \
    "$test_dir/large-report-roundtrip.json" \
    "$test_dir/corrupt-report.b64" \
    "$test_dir/corrupt-report.json" \
    "$test_dir/transport-message.txt" \
    "$test_dir/invalid-transport-message.txt"
  rmdir -- "$test_dir"
}
trap cleanup_test EXIT

export NEXUS_DATA_CORRECTION_OPS_LIB_ONLY=1
# shellcheck source=nexus-data-correction-ops.sh
source "$script_dir/nexus-data-correction-ops.sh"

# These values are interpolated into the scheduled command, so the transport
# validates them before command construction instead of relying on the
# container-side wrapper alone.
is_positive_integer 1
is_positive_integer 001
for invalid_run_identity in "" 0 00 "1:2" -1 1.2 " " "1;touch" "1|true"; do
  if is_positive_integer "$invalid_run_identity"; then
    echo "invalid run identity unexpectedly passed" >&2
    exit 1
  fi
done

# The container wrapper parses named apply arguments independently of order;
# the reconciliation receipt must always receive the plan, never the unlock.
export NEXUS_DATA_CORRECTION_WRAPPER_LIB_ONLY=1
# shellcheck source=../../backend/scripts/run_nexus_data_correction_once.sh
source "$script_dir/../../backend/scripts/run_nexus_data_correction_once.sh"
wrapper_plan=$(printf 'f%.0s' {1..64})
wrapper_approval=$(printf 'a%.0s' {1..64})
parse_cli_args apply \
  --approval-fingerprint "$wrapper_approval" \
  --fingerprint "$wrapper_plan"
[ "$plan_fingerprint" = "$wrapper_plan" ]
[ "$approval_fingerprint" = "$wrapper_approval" ]
[ "${cli_args[*]}" = "--approval-fingerprint $wrapper_approval --fingerprint $wrapper_plan" ]
parse_cli_args audit
if parse_cli_args apply \
  --fingerprint "$wrapper_plan" \
  --fingerprint "$wrapper_plan" \
  --approval-fingerprint "$wrapper_approval" 2>/dev/null; then
  echo "duplicate wrapper fingerprint unexpectedly passed" >&2
  exit 1
fi

# The real audit contains 471 contract entries and exceeded the bounded
# Coolify execution message after plain base64 encoding. Verify that the
# container encoder and Actions decoder round-trip a representative report and
# materially reduce its transport size.
jq -n '
  {
    contracts: [
      range(0; 471) as $id
      | {
          id: $id,
          changed_fields: [
            "contract_type",
            "start_date",
            "end_date",
            "client_order_end_date",
            "rate_client"
          ]
        }
    ]
  }
' > "$test_dir/large-report.json"
base64 < "$test_dir/large-report.json" \
  | tr -d '\r\n' > "$test_dir/large-report-plain.b64"
emit_redacted_payload "$test_dir/large-report.json" > "$test_dir/large-report.b64"
decode_redacted_payload \
  "$test_dir/large-report.b64" \
  "$test_dir/large-report-roundtrip.json"
cmp "$test_dir/large-report.json" "$test_dir/large-report-roundtrip.json"
raw_report_bytes=$(wc -c < "$test_dir/large-report.json")
plain_encoded_report_bytes=$(wc -c < "$test_dir/large-report-plain.b64")
encoded_report_bytes=$(wc -c < "$test_dir/large-report.b64")
[ "$plain_encoded_report_bytes" -gt 65536 ] || {
  echo "representative plain-base64 audit did not reproduce the message risk" >&2
  exit 1
}
[ "$encoded_report_bytes" -lt 65536 ] \
  && [ "$encoded_report_bytes" -lt "$raw_report_bytes" ] || {
  echo "compressed audit transport did not fit the bounded message" >&2
  exit 1
}
printf 'not-valid-base64' > "$test_dir/corrupt-report.b64"
if decode_redacted_payload \
  "$test_dir/corrupt-report.b64" \
  "$test_dir/corrupt-report.json" 2>/dev/null; then
  echo "corrupt compressed audit transport unexpectedly decoded" >&2
  exit 1
fi
{
  echo '===NEXUS-DATA-CORRECTION-PAYLOAD-BEGIN==='
  cat "$test_dir/large-report.b64"
  echo
  echo '===NEXUS-DATA-CORRECTION-PAYLOAD-END==='
  echo '===NEXUS-DATA-CORRECTION-OPERATION-RC=2==='
  echo '===NEXUS-DATA-CORRECTION-END==='
} > "$test_dir/transport-message.txt"
[ "$(operation_rc_from_message "$test_dir/transport-message.txt")" = "2" ]
{
  echo '===NEXUS-DATA-CORRECTION-OPERATION-RC=2==='
  echo '===NEXUS-DATA-CORRECTION-OPERATION-RC=0==='
} > "$test_dir/invalid-transport-message.txt"
if operation_rc_from_message "$test_dir/invalid-transport-message.txt" >/dev/null; then
  echo "ambiguous operation result unexpectedly passed" >&2
  exit 1
fi

# Every Coolify request, including cleanup, receives bounded network timeouts.
curl() {
  printf '%s\n' "$*" >> "$test_dir/curl.log"
}
coolify_curl -sS https://coolify.invalid/health
grep -q -- '--connect-timeout 10 --max-time 30' "$test_dir/curl.log"

# A lost POST response still owns the attempt before curl runs, resolves only
# the exact reserved task name, and deletes that task before returning failure.
base="https://coolify.invalid"
APP_UUID="app-1"
TASK_NAME="$EXPECTED_TASK_NAME"
auth=(-H "Authorization: Bearer test-token")
payload='{}'
create_response="$test_dir/create.json"
task_uuid=""
task_owned=false
ops_sleep() { :; }
coolify_curl() {
  printf '%s\n' "$*" >> "$test_dir/curl.log"
  case " $* " in
    *" -X POST "*)
      [ "$task_owned" = true ] || return 90
      : > "$test_dir/ownership.ok"
      printf '000'
      return 7
      ;;
    *" -X DELETE "*)
      : > "$test_dir/delete.done"
      printf '204'
      ;;
    *)
      if [ -f "$test_dir/delete.done" ]; then
        printf '[{"name":"unrelated-task","uuid":"other-uuid"}]\n'
      else
        printf '[{"name":"unrelated-task","uuid":"other-uuid"},'
        printf '{"name":"%s","uuid":"exact-uuid"}]\n' "$TASK_NAME"
      fi
      ;;
  esac
}

if create_one_shot_task; then
  echo "ambiguous POST unexpectedly succeeded" >&2
  exit 1
fi
[ -f "$test_dir/ownership.ok" ]
[ -f "$test_dir/delete.done" ]
[ "$task_owned" = false ]
grep -q -- '-X DELETE .*scheduled-tasks/exact-uuid' "$test_dir/curl.log"
if grep -q -- '-X DELETE .*scheduled-tasks/other-uuid' "$test_dir/curl.log"; then
  echo "cleanup deleted a non-owned task" >&2
  exit 1
fi

fingerprint=$(printf 'f%.0s' {1..64})
approval=$(printf 'a%.0s' {1..64})
post_fingerprint=$(printf 'e%.0s' {1..64})
jq -n --arg fp "$fingerprint" --arg approval "$approval" '
  {
    mode: "audit",
    ok: true,
    fingerprint: $fp,
    summary: {
      manifest_contracts: 471,
      contracts_found: 471,
      contracts_with_changes: 0,
      contract_field_changes: {
        contract_type: 0,
        start_date: 0,
        end_date: 0,
        client_order_end_date: 0,
        rate_client: 0
      },
      periodic_orders_to_delete: 0,
      legacy_null_orders_preserved: 2,
      disallowed_standalone_order_types: 0,
      disallowed_group_order_types: 0,
      dependency_rows: 0,
      set_null_dependency_rows: 0,
      set_null_deleted_dependency_rows: 0,
      legacy_null_dependency_rows: 0,
      blockers: 0,
      approval_fingerprint: $approval
    },
    contracts: [],
    orders: [],
    legacy_null_orders: [],
    blockers: [],
    secret: "must-not-cross"
  }
' > "$test_dir/audit.json"

# Audit intentionally has no reconciliation object and remains valid.
jq -e --arg mode audit \
  -f "$script_dir/nexus-data-correction-redacted-contract.jq" \
  "$test_dir/audit.json" >/dev/null
jq -f "$script_dir/nexus-data-correction-redacted-project.jq" \
  "$test_dir/audit.json" > "$test_dir/projected.json"
jq -e '
  .schema_version==4
  and .reconciliation==null
  and (has("secret") | not)
' "$test_dir/projected.json" >/dev/null

jq --arg post "$post_fingerprint" '
  .mode="apply"
  | .reconciliation={
      status: "verified_after_cli_failure",
      precommit_intent: true,
      apply_report_present: false,
      apply_report_matches_intent: false,
      apply_exit_code: 1,
      post_apply_audit_exit_code: 0,
      post_apply_fingerprint: $post,
      desired_state_verified: true,
      secret: "must-not-cross"
    }
' "$test_dir/audit.json" > "$test_dir/apply.json"
jq -e --arg mode apply \
  -f "$script_dir/nexus-data-correction-redacted-contract.jq" \
  "$test_dir/apply.json" >/dev/null
jq -f "$script_dir/nexus-data-correction-redacted-project.jq" \
  "$test_dir/apply.json" > "$test_dir/projected.json"
jq -e --arg post "$post_fingerprint" '
  .reconciliation.status=="verified_after_cli_failure"
  and .reconciliation.post_apply_fingerprint==$post
  and (.reconciliation | has("secret") | not)
  and (has("secret") | not)
' "$test_dir/projected.json" >/dev/null

# APPLY cannot pass the raw contract without a reconciliation proof.
jq '.mode="apply" | del(.reconciliation)' \
  "$test_dir/audit.json" > "$test_dir/apply.json"
if jq -e --arg mode apply \
  -f "$script_dir/nexus-data-correction-redacted-contract.jq" \
  "$test_dir/apply.json" >/dev/null; then
  echo "apply without reconciliation unexpectedly passed" >&2
  exit 1
fi
