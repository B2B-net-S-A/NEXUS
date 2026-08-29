#!/usr/bin/env bash
# One-shot Coolify transport for the manifest-scoped Nexus.xlsx correction.
# Full values remain in a mode-0700 directory in the backend container. Only
# the backend-produced, closed redacted report is persisted by Actions.

set -euo pipefail

EXPECTED_TASK_NAME="nexus-data-correction-oneshot"
CO_CURL_CONNECT_TIMEOUT_SECONDS="${CO_CURL_CONNECT_TIMEOUT_SECONDS:-10}"
CO_CURL_MAX_TIME_SECONDS="${CO_CURL_MAX_TIME_SECONDS:-30}"
OPS_SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "::error::missing required environment variable: $name"
    exit 1
  fi
}

is_sha256() {
  case "$1" in
    ""|*[!0-9a-f]*) return 1 ;;
  esac
  [ "${#1}" -eq 64 ]
}

is_positive_integer() {
  case "$1" in
    ""|*[!0-9]*) return 1 ;;
    *[1-9]*) return 0 ;;
    *) return 1 ;;
  esac
}

ops_sleep() {
  sleep "$1"
}

coolify_curl() {
  curl \
    --connect-timeout "$CO_CURL_CONNECT_TIMEOUT_SECONDS" \
    --max-time "$CO_CURL_MAX_TIME_SECONDS" \
    "$@"
}

exact_task_uuids() {
  local response
  response=$(coolify_curl -fsS "${auth[@]}" \
    "$base/api/v1/applications/$APP_UUID/scheduled-tasks") || return 1
  jq -r --arg n "$TASK_NAME" \
    'if type=="array" then ([.[] | select(.name==$n) | .uuid] | join("\n")) else error("unexpected task list") end' \
    <<<"$response"
}

exact_task_count() {
  local response
  response=$(coolify_curl -fsS "${auth[@]}" \
    "$base/api/v1/applications/$APP_UUID/scheduled-tasks") || return 1
  jq -r --arg n "$TASK_NAME" \
    'if type=="array" then ([.[] | select(.name==$n)] | length) else error("unexpected task list") end' \
    <<<"$response"
}

cleanup_task() {
  local uuids="" uuid code still attempt found=false
  local attempts=1
  [ "${task_owned:-false}" = true ] || return 0
  # With no resolved UUID the POST outcome is ambiguous. Re-check the exact,
  # reserved task name a few times before concluding that Coolify created
  # nothing; a lost HTTP response must not leave a cron running every minute.
  [ -n "${task_uuid:-}" ] || attempts=3
  for attempt in $(seq 1 "$attempts"); do
    if ! uuids=$(exact_task_uuids); then
      echo "::error::could not reconcile the exact Coolify task name"
      [ "$attempt" -eq "$attempts" ] && return 1
      ops_sleep 2
      continue
    fi
    if [ -n "$uuids" ]; then
      found=true
      while IFS= read -r uuid; do
        [ -n "$uuid" ] || continue
        case "$uuid" in
          *[!A-Za-z0-9_-]*)
            echo "::error::Coolify returned an unsafe task UUID"
            return 1
            ;;
        esac
        code=$(coolify_curl -sS -o /dev/null -w "%{http_code}" -X DELETE \
          "${auth[@]}" \
          "$base/api/v1/applications/$APP_UUID/scheduled-tasks/$uuid" || true)
        code="${code:-000}"
        echo "delete HTTP $code (uuid=$uuid)"
      done <<<"$uuids"
    fi
    if ! still=$(exact_task_count); then
      echo "::error::could not verify deletion of the exact Coolify task"
      [ "$attempt" -eq "$attempts" ] && return 1
      ops_sleep 2
      continue
    fi
    if [ "$still" = "0" ] && { [ "$found" = true ] || [ "$attempt" -eq "$attempts" ]; }; then
      task_uuid=""
      task_owned=false
      return 0
    fi
    [ "$attempt" -eq "$attempts" ] || ops_sleep 2
  done
  echo "::error::$TASK_NAME still exists; delete this exact task before retrying"
  return 1
}

resolve_created_task_uuid() {
  local uuids="" count attempt
  for attempt in 1 2 3 4 5; do
    if uuids=$(exact_task_uuids); then
      count=$(awk 'NF { count += 1 } END { print count + 0 }' <<<"$uuids")
      if [ "$count" = "1" ]; then
        task_uuid=$(awk 'NF { print; exit }' <<<"$uuids")
        return 0
      fi
      if [ "$count" -gt 1 ]; then
        echo "::error::more than one exact Coolify task exists"
        return 1
      fi
    fi
    [ "$attempt" -eq 5 ] || ops_sleep 2
  done
  echo "::error::task creation is ambiguous; exact UUID was not resolved"
  return 1
}

create_one_shot_task() {
  local code cleanup_rc=0
  # Ownership intent precedes the POST. Even when curl returns HTTP 000, the
  # EXIT trap now searches and deletes only the reserved exact task name.
  task_owned=true
  code=$(coolify_curl -sS -o "$create_response" -w "%{http_code}" -X POST \
    "${auth[@]}" -H "Content-Type: application/json" -d "$payload" \
    "$base/api/v1/applications/$APP_UUID/scheduled-tasks" || true)
  code="${code:-000}"
  case "$code" in
    [0-9][0-9][0-9]) ;;
    *) code="000" ;;
  esac
  echo "create HTTP $code"
  if [ "$code" -lt 200 ] 2>/dev/null || [ "$code" -ge 300 ] 2>/dev/null; then
    echo "::error::could not prove creation of the one-shot task (HTTP $code); body suppressed"
    cleanup_task || cleanup_rc=$?
    [ "$cleanup_rc" -eq 0 ] || echo "::error::ambiguous task cleanup also failed"
    return 1
  fi
  if ! resolve_created_task_uuid; then
    cleanup_task || cleanup_rc=$?
    [ "$cleanup_rc" -eq 0 ] || echo "::error::ambiguous task cleanup also failed"
    return 1
  fi
}

if [ "${NEXUS_DATA_CORRECTION_OPS_LIB_ONLY:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

for required in CO_URL CO_TOKEN APP_UUID MODE TASK_NAME SENTINEL PAYLOAD_BEGIN PAYLOAD_END OPS_RUN_ID OPS_RUN_ATTEMPT RUNNER_TEMP; do
  require_env "$required"
done
is_positive_integer "$OPS_RUN_ID" && is_positive_integer "$OPS_RUN_ATTEMPT" || {
  echo "::error::OPS_RUN_ID and OPS_RUN_ATTEMPT must be positive integers"
  exit 1
}
[ "$TASK_NAME" = "$EXPECTED_TASK_NAME" ] || {
  echo "::error::unexpected Coolify task name"
  exit 1
}

case "$MODE" in
  audit)
    if [ -n "${PLAN_FINGERPRINT:-}${APPLY_UNLOCK:-}" ] \
      || [ "${APPLY_CONFIRMATION:-NO}" != "NO" ]; then
      echo "::error::audit does not accept an apply fingerprint, unlock or confirmation"
      exit 1
    fi
    ;;
  apply)
    [ "${APPLY_CONFIRMATION:-NO}" = "APPLY" ] || {
      echo "::error::apply requires nexus_data_correction_confirm=APPLY"
      exit 1
    }
    is_sha256 "${PLAN_FINGERPRINT:-}" || {
      echo "::error::apply requires a 64-character lowercase plan fingerprint"
      exit 1
    }
    # This secret is the approval hash emitted by the accepted audit. The
    # backend recomputes it from the locked live plan before any mutation.
    is_sha256 "${APPLY_UNLOCK:-}" || {
      echo "::error::apply is locked; configure the approved 64-character lowercase unlock"
      exit 1
    }
    ;;
  *)
    echo "::error::unsupported Nexus data correction mode"
    exit 1
    ;;
esac

base="${CO_URL%/}"
auth=(-H "Authorization: Bearer ${CO_TOKEN}" -H "Accept: application/json")
report_dir="$RUNNER_TEMP/nexus-data-correction"
raw_redacted="$RUNNER_TEMP/nexus-data-correction-redacted-raw.json"
report="$report_dir/report.json"
summary="$report_dir/run-summary.txt"
mkdir -p "$report_dir"

task_uuid=""
task_owned=false
trap 'cleanup_task || true' EXIT

existing_count=$(exact_task_count)
if [ "$existing_count" != "0" ]; then
  echo "::error::$TASK_NAME already exists; the prior run is ambiguous"
  exit 1
fi

cli_args=""
if [ "$MODE" = "apply" ]; then
  cli_args=" --fingerprint $PLAN_FINGERPRINT --approval-fingerprint $APPLY_UNLOCK"
fi
once_dir="/tmp/nexus-data-correction-once-${OPS_RUN_ID}-${OPS_RUN_ATTEMPT}"
cmd="if mkdir ${once_dir} ; then cd /app && bash scripts/run_nexus_data_correction_once.sh ${MODE} ${OPS_RUN_ID} ${OPS_RUN_ATTEMPT}${cli_args} ; fi"
case "$cmd" in
  *"'"*|*'$'*|*'`'*|*$'\n'*)
    echo "::error::generated command contains a shell-wrapper-sensitive character"
    exit 1
    ;;
esac
echo "mode=$MODE; fixed command prepared; names and amounts remain inside the production container"

payload=$(jq -n --arg n "$TASK_NAME" --arg c "$cmd" --arg ct backend \
  '{name:$n, command:$c, frequency:"* * * * *", container:$ct, enabled:true}')
create_response="$RUNNER_TEMP/nexus-data-correction-create.json"
create_one_shot_task

deadline=$(( $(date -u +%s) + 15 * 60 ))
message_file="$RUNNER_TEMP/nexus-data-correction-message.txt"
: > "$message_file"
executions_file="$RUNNER_TEMP/nexus-data-correction-executions.json"
while [ "$(date -u +%s)" -lt "$deadline" ]; do
  sleep 20
  if coolify_curl -fsS "${auth[@]}" "$base/api/v1/applications/$APP_UUID/scheduled-tasks/$task_uuid/executions" \
    -o "$executions_file"; then
    if jq -e --arg b "$PAYLOAD_BEGIN" --arg s "$SENTINEL" \
      'type=="array" and any(.[]; (((.message // "") | contains($b)) and ((.message // "") | contains($s))))' \
        "$executions_file" >/dev/null 2>&1; then
      jq -r --arg b "$PAYLOAD_BEGIN" --arg s "$SENTINEL" \
        'map(select((((.message // "") | contains($b)) and ((.message // "") | contains($s))))) | .[0].message' \
        "$executions_file" > "$message_file"
      break
    fi
    if jq -e --arg s "$SENTINEL" \
      'type=="array" and any(.[]; ((.message // "") | contains($s)))' \
        "$executions_file" >/dev/null 2>&1; then
      echo "::error::production command finished without a redacted report"
      exit 1
    fi
  fi
  statuses=$(jq -r 'if type=="array" then ([.[].status] | join(",")) else "?" end' \
    "$executions_file" 2>/dev/null || echo "?")
  echo "$(date -u +%H:%M:%S) waiting; statuses: $statuses"
done
[ -s "$message_file" ] || {
  echo "::error::no execution produced a redacted report within 15 minutes"
  exit 1
}

encoded="$RUNNER_TEMP/nexus-data-correction-payload.b64"
awk -v begin="$PAYLOAD_BEGIN" -v end="$PAYLOAD_END" '
  index($0, begin) { capture=1; next }
  index($0, end) { exit }
  capture { printf "%s", $0 }
' "$message_file" | tr -d '\r\n ' > "$encoded"
[ -s "$encoded" ] || {
  echo "::error::execution did not contain a redacted payload"
  exit 1
}
base64 --decode "$encoded" > "$raw_redacted" 2>/dev/null || {
  echo "::error::redacted payload was truncated or invalid"
  exit 1
}

if ! jq -e --arg mode "$MODE" \
  -f "$OPS_SCRIPT_DIR/nexus-data-correction-redacted-contract.jq" \
  "$raw_redacted" >/dev/null; then
  echo "::error::redacted output has an invalid JSON contract"
  exit 1
fi

# A second closed projection prevents free-form values from crossing into the
# artifact if the backend redactor ever regresses.
jq -f "$OPS_SCRIPT_DIR/nexus-data-correction-redacted-project.jq" \
  "$raw_redacted" > "$report"

fingerprint=$(jq -r '.fingerprint // "none"' "$report")
approval_fingerprint=$(jq -r '.summary.approval_fingerprint // "none"' "$report")
ok=$(jq -r '.ok' "$report")
contract_changes=$(jq '[.contracts[] | select((.changed_fields | length) > 0)] | length' "$report")
order_deletes=$(jq '.orders | length' "$report")
legacy_null_orders=$(jq '.legacy_null_orders | length' "$report")
set_null_dependencies=$(jq '.summary.set_null_dependency_rows' "$report")
set_null_deleted_dependencies=$(jq '.summary.set_null_deleted_dependency_rows' "$report")
blockers=$(jq '.blockers | length' "$report")
reconciliation_status=$(jq -r '.reconciliation.status // "not_applicable"' "$report")
{
  echo "mode=$MODE"
  echo "ok=$ok"
  echo "fingerprint=$fingerprint"
  echo "approval_fingerprint=$approval_fingerprint"
  echo "contracts_with_changes=$contract_changes"
  echo "periodic_orders_to_delete=$order_deletes"
  echo "set_null_dependency_rows=$set_null_dependencies"
  echo "set_null_deleted_dependency_rows=$set_null_deleted_dependencies"
  echo "legacy_null_orders_preserved=$legacy_null_orders"
  echo "blockers=$blockers"
  echo "reconciliation_status=$reconciliation_status"
} > "$summary"
cat "$summary"

cleanup_task
trap - EXIT
[ "$ok" = "true" ] || exit 2
