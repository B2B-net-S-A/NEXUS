#!/usr/bin/env bash
# One-shot Coolify transport for the duplicate-contract planner.
#
# The production script writes a full report only to /tmp inside the backend
# container. Only its separately generated, redacted report (record IDs,
# codes, counts and fingerprint; no names or amounts) crosses into Actions.

set -euo pipefail

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "::error::missing required environment variable: $name"
    exit 1
  fi
}

validate_rate_sources() {
  local label="$1" value="$2" pair group source seen="," old_ifs
  [ -z "$value" ] && return 0
  if [ "${#value}" -gt 2000 ]; then
    echo "::error::$label is too long"
    return 1
  fi
  case "$value" in
    *[!0-9=,]*|,*|*,|*,,*)
      echo "::error::$label must use group=source,... with digits only"
      return 1
      ;;
  esac
  old_ifs="$IFS"
  IFS=,
  for pair in $value; do
    case "$pair" in
      *=*=*|=*|*=)
        echo "::error::$label contains an invalid ID pair"
        IFS="$old_ifs"
        return 1
        ;;
    esac
    group="${pair%%=*}"
    source="${pair#*=}"
    if [ "${#group}" -gt 10 ] || [ "${#source}" -gt 10 ]; then
      echo "::error::$label contains an ID longer than 10 digits"
      IFS="$old_ifs"
      return 1
    fi
    case "$group:$source" in
      *[!0-9:]*)
        echo "::error::$label contains a non-numeric ID"
        IFS="$old_ifs"
        return 1
        ;;
    esac
    if [ "$group" -eq 0 ] || [ "$source" -eq 0 ]; then
      echo "::error::$label IDs must be positive"
      IFS="$old_ifs"
      return 1
    fi
    case "$seen" in
      *",$group,"*)
        echo "::error::$label repeats group $group"
        IFS="$old_ifs"
        return 1
        ;;
    esac
    seen="${seen}${group},"
  done
  IFS="$old_ifs"
}

validate_field_sources() {
  local label="$1" value="$2" pair lhs group field source seen="," old_ifs
  [ -z "$value" ] && return 0
  if [ "${#value}" -gt 4000 ]; then
    echo "::error::$label is too long"
    return 1
  fi
  case "$value" in
    *[!0-9a-z_=.,]*|,*|*,|*,,*)
      echo "::error::$label must use group.field=source,... with safe characters"
      return 1
      ;;
  esac
  old_ifs="$IFS"
  IFS=,
  for pair in $value; do
    case "$pair" in
      *=*=*|=*|*=)
        echo "::error::$label contains an invalid field decision"
        IFS="$old_ifs"
        return 1
        ;;
    esac
    lhs="${pair%%=*}"
    source="${pair#*=}"
    case "$lhs" in
      *.*.*|.*|*.)
        echo "::error::$label contains an invalid group.field key"
        IFS="$old_ifs"
        return 1
        ;;
      *.*) ;;
      *)
        echo "::error::$label requires a group.field key"
        IFS="$old_ifs"
        return 1
        ;;
    esac
    group="${lhs%%.*}"
    field="${lhs#*.}"
    case "$group:$source" in
      *[!0-9:]*)
        echo "::error::$label contains a non-numeric ID"
        IFS="$old_ifs"
        return 1
        ;;
    esac
    if [ -z "$group" ] || [ -z "$field" ] || [ "$group" -eq 0 ] || [ "$source" -eq 0 ]; then
      echo "::error::$label requires positive IDs and a field"
      IFS="$old_ifs"
      return 1
    fi
    case "$seen" in
      *",$group.$field,"*)
        echo "::error::$label repeats group.field $group.$field"
        IFS="$old_ifs"
        return 1
        ;;
    esac
    seen="${seen}${group}.${field},"
  done
  IFS="$old_ifs"
}

for required in CO_URL CO_TOKEN APP_UUID MODE TASK_NAME SENTINEL PAYLOAD_BEGIN PAYLOAD_END OPS_RUN_ID OPS_RUN_ATTEMPT RUNNER_TEMP; do
  require_env "$required"
done

case "$MODE" in
  audit)
    if [ -n "${PLAN_FINGERPRINT:-}${CANDIDATE_RATE_SOURCES:-}${CLIENT_RATE_SOURCES:-}${FRAMEWORK_RATE_SOURCES:-}${RATE_METADATA_SOURCES:-}${FIELD_SOURCES:-}" ] \
      || [ "${ALLOW_RATE_EMPTY_METADATA:-NO}" != "NO" ] \
      || [ "${APPLY_CONFIRMATION:-NO}" != "NO" ]; then
      echo "::error::audit does not accept an apply fingerprint, rate decisions or confirmation"
      exit 1
    fi
    ;;
  apply)
    [ "${APPLY_CONFIRMATION:-NO}" = "APPLY" ] || {
      echo "::error::apply requires contract_merge_confirm=APPLY"
      exit 1
    }
    case "${PLAN_FINGERPRINT:-}" in
      ""|*[!0-9a-f]*)
        echo "::error::apply fingerprint must be lowercase hexadecimal"
        exit 1
        ;;
    esac
    [ "${#PLAN_FINGERPRINT}" -eq 64 ] || {
      echo "::error::apply fingerprint must contain exactly 64 characters"
      exit 1
    }
    # This secret is the approval fingerprint calculated from the audited plan
    # *and* all normalized rate/metadata source maps plus the rate-empty ALLOW.
    # The backend recomputes it before touching data, so changing any choice
    # invalidates the one-shot unlock.
    case "${APPLY_UNLOCK:-}" in
      ""|*[!0-9a-f]*)
        echo "::error::apply is locked; configure the approved lowercase hexadecimal unlock"
        exit 1
        ;;
    esac
    [ "${#APPLY_UNLOCK}" -eq 64 ] || {
      echo "::error::apply unlock must contain exactly 64 characters"
      exit 1
    }
    case "${ALLOW_RATE_EMPTY_METADATA:-NO}" in
      NO|ALLOW) ;;
      *)
        echo "::error::contract_merge_allow_rate_empty_metadata must be NO or ALLOW"
        exit 1
        ;;
    esac
    ;;
  *)
    echo "::error::unsupported contract merge mode"
    exit 1
    ;;
esac

validate_rate_sources contract_merge_candidate_rate_sources "${CANDIDATE_RATE_SOURCES:-}"
validate_rate_sources contract_merge_client_rate_sources "${CLIENT_RATE_SOURCES:-}"
validate_rate_sources contract_merge_framework_rate_sources "${FRAMEWORK_RATE_SOURCES:-}"
validate_rate_sources contract_merge_rate_metadata_sources "${RATE_METADATA_SOURCES:-}"
validate_field_sources contract_merge_field_sources "${FIELD_SOURCES:-}"

base="${CO_URL%/}"
auth=(-H "Authorization: Bearer ${CO_TOKEN}" -H "Accept: application/json")
report_dir="$RUNNER_TEMP/contract-merge"
raw_redacted="$RUNNER_TEMP/contract-merge-redacted-raw.json"
report="$report_dir/report.json"
summary="$report_dir/run-summary.txt"
mkdir -p "$report_dir"

task_uuid=""
task_owned=false
cleanup_task() {
  local uuid="$task_uuid" still code
  # Never delete a task merely because it has the same fixed name.  Name-based
  # discovery is allowed only after this run received HTTP 2xx for CREATE and
  # therefore owns the task it is trying to clean up.
  [ "$task_owned" = true ] || return 0
  if [ -z "$uuid" ]; then
    uuid=$(curl -sS "${auth[@]}" "$base/api/v1/applications/$APP_UUID/scheduled-tasks" \
      | jq -r --arg n "$TASK_NAME" 'if type=="array" then (map(select(.name==$n)) | .[0].uuid // "") else "" end' 2>/dev/null || true)
  fi
  [ -n "$uuid" ] || return 0
  code=$(curl -sS -o /dev/null -w "%{http_code}" -X DELETE "${auth[@]}" \
    "$base/api/v1/applications/$APP_UUID/scheduled-tasks/$uuid" || true)
  code="${code:-000}"
  echo "delete HTTP $code (uuid=$uuid)"
  still=$(curl -sS "${auth[@]}" "$base/api/v1/applications/$APP_UUID/scheduled-tasks" \
    | jq -r --arg n "$TASK_NAME" 'if type=="array" then (map(select(.name==$n)) | length) else 1 end' 2>/dev/null || echo 1)
  if [ "$still" != "0" ]; then
    echo "::error::$TASK_NAME still exists; delete it in Coolify before another run"
    return 1
  fi
  task_uuid=""
  task_owned=false
}
trap 'cleanup_task || true' EXIT

# A fixed task name makes a crashed previous invocation discoverable. Delete
# only that exact one-shot task; never touch application cron jobs generally.
tasks=$(curl -fsS "${auth[@]}" "$base/api/v1/applications/$APP_UUID/scheduled-tasks")
existing=$(echo "$tasks" | jq -r --arg n "$TASK_NAME" 'if type=="array" then (map(select(.name==$n)) | .[0].uuid // "") else "" end')
if [ -n "$existing" ]; then
  echo "::error::$TASK_NAME already exists (uuid=$existing); an earlier run is operationally ambiguous"
  echo "::error::do not retry apply; wait for the 12-minute remote timeout, run a fresh audit, and remove only this exact task after verification"
  exit 1
fi

cli_args=""
[ -n "${PLAN_FINGERPRINT:-}" ] && cli_args="$cli_args --fingerprint $PLAN_FINGERPRINT"
[ "$MODE" = "apply" ] && cli_args="$cli_args --approval-fingerprint $APPLY_UNLOCK"
[ -n "${CANDIDATE_RATE_SOURCES:-}" ] && cli_args="$cli_args --candidate-rate-sources $CANDIDATE_RATE_SOURCES"
[ -n "${CLIENT_RATE_SOURCES:-}" ] && cli_args="$cli_args --client-rate-sources $CLIENT_RATE_SOURCES"
[ -n "${FRAMEWORK_RATE_SOURCES:-}" ] && cli_args="$cli_args --framework-rate-sources $FRAMEWORK_RATE_SOURCES"
[ -n "${RATE_METADATA_SOURCES:-}" ] && cli_args="$cli_args --rate-metadata-sources $RATE_METADATA_SOURCES"
[ -n "${FIELD_SOURCES:-}" ] && cli_args="$cli_args --field-sources $FIELD_SOURCES"
[ "${ALLOW_RATE_EMPTY_METADATA:-NO}" = "ALLOW" ] && cli_args="$cli_args --allow-rate-empty-metadata ALLOW"

once_dir="/tmp/nexus-contract-merge-once-${OPS_RUN_ID}-${OPS_RUN_ATTEMPT}"
# A cron tick that arrives while the first invocation is still running must be
# silent. Only the process that created ``once_dir`` may run the checked-in
# wrapper. The wrapper owns its mode-0700 tempdir and emits the sentinel only
# after the full PII/rate report and process log have been removed.
#
# The checked-in wrapper applies the hard timeout to the Python child while
# remaining alive to remove its private report/log directory and global lock.
# If the runner disappears, the child transaction still rolls back after 12m.
cmd="if mkdir ${once_dir} ; then cd /app && bash scripts/run_contract_merge_once.sh ${MODE} ${OPS_RUN_ID} ${OPS_RUN_ATTEMPT}${cli_args} ; fi"
case "$cmd" in
  *"'"*|*'$'*|*'`'*|*$'\n'*)
    echo "::error::generated command contains a shell-wrapper-sensitive character"
    exit 1
    ;;
esac
echo "mode=$MODE; fixed command prepared; names and amounts remain inside the production container"

payload=$(jq -n --arg n "$TASK_NAME" --arg c "$cmd" --arg ct backend \
  '{name:$n, command:$c, frequency:"* * * * *", container:$ct, enabled:true}')
code=$(curl -sS -o /tmp/contract-merge-create.json -w "%{http_code}" -X POST "${auth[@]}" \
  -H "Content-Type: application/json" -d "$payload" \
  "$base/api/v1/applications/$APP_UUID/scheduled-tasks" || true)
code="${code:-000}"
echo "create HTTP $code"
if [ "$code" -ge 400 ] 2>/dev/null || [ "$code" = "000" ]; then
  echo "::error::could not create the one-shot task (HTTP $code); response body suppressed"
  exit 1
fi
task_owned=true
task_uuid=$(jq -r '(.uuid // .task.uuid // .data.uuid // "")' /tmp/contract-merge-create.json 2>/dev/null || true)
if [ -z "$task_uuid" ]; then
  task_uuid=$(curl -fsS "${auth[@]}" "$base/api/v1/applications/$APP_UUID/scheduled-tasks" \
    | jq -r --arg n "$TASK_NAME" 'if type=="array" then (map(select(.name==$n)) | .[0].uuid // "") else "" end')
fi
[ -n "$task_uuid" ] || {
  echo "::error::task was created but its UUID is unknown; remove $TASK_NAME manually"
  exit 1
}

deadline=$(( $(date -u +%s) + 15 * 60 ))
message_file=/tmp/contract-merge-message.txt
: > "$message_file"
while [ "$(date -u +%s)" -lt "$deadline" ]; do
  sleep 20
  if curl -fsS "${auth[@]}" "$base/api/v1/applications/$APP_UUID/scheduled-tasks/$task_uuid/executions" \
    -o /tmp/contract-merge-executions.json; then
    if jq -e --arg b "$PAYLOAD_BEGIN" --arg s "$SENTINEL" \
      'type=="array" and any(.[]; (((.message // "") | contains($b)) and ((.message // "") | contains($s))))' \
        /tmp/contract-merge-executions.json >/dev/null 2>&1; then
      jq -r --arg b "$PAYLOAD_BEGIN" --arg s "$SENTINEL" \
        'map(select((((.message // "") | contains($b)) and ((.message // "") | contains($s))))) | .[0].message' \
        /tmp/contract-merge-executions.json > "$message_file"
      break
    fi
    if jq -e --arg s "$SENTINEL" \
      'type=="array" and any(.[]; ((.message // "") | contains($s)))' \
        /tmp/contract-merge-executions.json >/dev/null 2>&1; then
      echo "::error::production command finished without a redacted report; execution body suppressed"
      exit 1
    fi
  fi
  statuses=$(jq -r 'if type=="array" then ([.[].status] | join(",")) else "?" end' \
    /tmp/contract-merge-executions.json 2>/dev/null || echo "?")
  echo "$(date -u +%H:%M:%S) waiting; statuses: $statuses"
done
[ -s "$message_file" ] || {
  echo "::error::no execution produced a redacted report within 15 minutes"
  exit 1
}

# Never echo the message: it carries the encoded report. The report is already
# redacted by the production script, and the jq projection below is a second,
# closed allowlist before the artifact is persisted.
awk -v begin="$PAYLOAD_BEGIN" -v end="$PAYLOAD_END" '
  index($0, begin) { capture=1; next }
  index($0, end) { exit }
  capture { printf "%s", $0 }
' "$message_file" | tr -d '\r\n ' > /tmp/contract-merge-payload.b64
[ -s /tmp/contract-merge-payload.b64 ] || {
  echo "::error::execution did not contain a redacted payload"
  exit 1
}
base64 --decode /tmp/contract-merge-payload.b64 > "$raw_redacted" 2>/dev/null || {
  echo "::error::redacted payload was truncated or invalid"
  exit 1
}

if ! jq -e --arg mode "$MODE" '
  type=="object"
  and .mode==$mode
  and (.ok | type=="boolean")
  and ((.fingerprint==null and .ok==false)
       or ((.fingerprint | type)=="string" and (.fingerprint | test("^[0-9a-f]{64}$"))))
' "$raw_redacted" >/dev/null; then
  echo "::error::redacted output has an invalid JSON contract"
  exit 1
fi

# Closed projection: no free-form messages, candidate/client names, field
# values or rates can enter the uploaded artifact even if the producer regresses.
jq '
def id_or_null:
  if type=="number" and . > 0 and floor == . then . else null end;
def ids:
  if type=="array" then [.[] | id_or_null | select(. != null)] else [] end;
def allowed_blocker_code:
  . as $value | ([
    "active_order_missing_start_date",
    "candidate_identity_mismatch",
    "candidate_rate_current_value_conflict",
    "candidate_rate_schedule_conflict",
    "client_identity_mismatch",
    "client_order_client_mismatch",
    "client_rate_current_value_conflict",
    "client_rate_schedule_conflict",
    "contract_document_unique_collision",
    "contract_field_conflicts",
    "contract_lifecycle_metadata_present",
    "duplicate_client_order_group_lines",
    "explicit_delete_candidate_mismatch",
    "explicit_delete_client_snapshot_drift",
    "explicit_delete_clients_not_distinct",
    "explicit_delete_has_children",
    "explicit_delete_has_completed_signature",
    "explicit_delete_has_historical_references",
    "explicit_delete_has_signed_generated_contract",
    "explicit_delete_status_snapshot_drift",
    "explicit_keep_client_snapshot_drift",
    "explicit_keep_status_snapshot_drift",
    "financial_metadata_conflict",
    "framework_rate_current_value_conflict",
    "framework_rate_schedule_conflict",
    "missing_contracts",
    "missing_expected_contract_foreign_keys",
    "multiple_b2b_contract_details",
    "noop_clients_not_distinct",
    "noop_ended_order_period_ambiguous",
    "noop_not_sequential_status_pattern",
    "noop_periods_overlap_or_are_incomplete",
    "overlapping_current_orders",
    "rate_empty_financial_metadata_conflict",
    "unclassified_contract_columns",
    "unknown_contract_foreign_keys",
    "unscoped_duplicate_contract",
    "void_contract_in_merge_group"
  ] | index($value)) != null;
def safe_codes:
  if type!="array" then []
  elif all(.[]; type=="string" and allowed_blocker_code) then .
  else error("contract merge report contains a non-allowlisted blocker code") end;
def allowed_field:
  . as $value | ([
    "candidate_subject_ref", "job_id", "start_date", "end_date",
    "contract_type", "documents", "client_pm_name", "client_pm_email",
    "client_pm_contact_id", "work_mode", "line_manager", "office_location",
    "team_name", "project_name", "handover_notes", "termination_reason",
    "termination_lessons", "terminated_at", "target_rate_min",
    "target_rate_max", "project_code", "prolongation_status",
    "engagement_model", "hours_pool_total", "hours_pool_consumed",
    "order_consumption", "order_consumption_unit", "draft_content_html",
    "draft_template_id", "draft_updated_at", "draft_updated_by"
  ] | index($value)) != null;
def safe_fields:
  if type!="array" then []
  elif all(.[]; type=="string" and allowed_field) then .
  else error("contract merge report contains a non-allowlisted field") end;
def safe_count:
  if type=="number" and . >= 0 and floor == . then . else 0 end;
def safe_operation:
  if .=="merge_same_client" or .=="explicit_delete_wrong_project" or .=="sequential_history_noop"
  then . else error("contract merge report contains an invalid operation") end;
def safe_bool:
  if type=="boolean" then . else false end;
def safe_rate_scopes:
  if type!="array" then []
  elif all(.[]; .=="past" or .=="future") then .
  else error("contract merge report contains an invalid schedule-conflict scope") end;
def safe_financial_metadata_fields:
  if type!="array" then []
  elif all(.[]; .=="rate_unit" or .=="currency" or .=="billing_hours_per_month") then .
  else error("contract merge report contains an invalid financial metadata field") end;
def safe_field_id_object:
  if type!="object" then {}
  elif all(to_entries[]; (.key | allowed_field) and ((.value | id_or_null) != null)) then .
  else error("contract merge report contains an invalid field-source map") end;
def allowed_child_key:
  . as $value | ([
    "b2b_contract_details", "b2b_generated_contracts", "calls",
    "client_orders", "contract_amendments", "contract_candidate_rates",
    "contract_client_rates", "contract_documents", "contract_equipment",
    "contract_framework_rates", "contract_onboarding_items",
    "document_signatures", "invoices", "notes"
  ] | index($value)) != null;
def allowed_history_key:
  . as $value | ([
    "activities", "notifications", "notification_link_refs", "alert_dedup"
  ] | index($value)) != null;
def safe_child_id_object:
  if type!="object" then {}
  elif all(to_entries[]; (.key | allowed_child_key) and (.value | type=="array") and all(.value[]; (id_or_null != null))) then .
  else error("contract merge report contains an invalid child ID map") end;
def safe_history_id_object:
  if type!="object" then {}
  elif all(to_entries[]; (.key | allowed_history_key) and (.value | type=="array") and all(.value[]; (id_or_null != null))) then .
  else error("contract merge report contains an invalid history ID map") end;
def safe_child_count_object:
  if type!="object" then {}
  elif all(to_entries[]; (.key | allowed_child_key) and (.value | type=="number" and . >= 0 and floor == .)) then .
  else error("contract merge report contains an invalid child count map") end;
def safe_history_count_object:
  if type!="object" then {}
  elif all(to_entries[]; (.key | allowed_history_key) and (.value | type=="number" and . >= 0 and floor == .)) then .
  else error("contract merge report contains an invalid history count map") end;
def allowed_hard_delete_count_key:
  . as $value | (["contracts", "detached_generated_contracts", "settled_order_groups"] | index($value)) != null;
def safe_hard_delete_counts:
  if type!="object" then {}
  elif all(to_entries[]; (.key | allowed_hard_delete_count_key) and (.value | type=="number" and . >= 0 and floor == .)) then .
  else error("contract merge report contains an invalid hard-delete counter") end;
def allowed_reparent_key:
  . as $value | ([
    "activities", "b2b_contract_details", "b2b_generated_contracts",
    "calls", "client_orders", "contract_amendments",
    "contract_candidate_rates", "contract_client_rates",
    "contract_alert_dedup_aliases", "contract_documents", "contract_equipment", "contract_framework_rates",
    "contract_onboarding_items", "document_signatures", "invoices", "notes",
    "notification_links", "notifications", "notifications_retained_historical"
  ] | index($value)) != null;
def safe_counts_object:
  if type!="object" then {}
  elif all(to_entries[]; (.key | allowed_reparent_key) and (.value | type=="number" and . >= 0 and floor == .))
  then .
  else error("contract merge report contains a non-allowlisted reparent counter") end;
{
  schema_version: 2,
  mode,
  ok,
  fingerprint,
  summary: {
    group_count: (if (.groups | type)=="array" then (.groups | length) else 0 end),
    blocker_count: ((.summary.blocking_issues // (if (.blockers | type)=="array" then (.blockers | length) else 0 end)) | safe_count),
    delete_count: ((.summary.delete_count // .summary.contracts_to_delete // .summary.contracts_deleted // 0) | safe_count),
    unchanged_count: ((.summary.unchanged_count // 0) | safe_count),
    same_client_group_count: ((.summary.same_client_groups // 0) | safe_count),
    explicit_delete_count: ((.summary.explicit_deletes // 0) | safe_count),
    rate_conflict_group_count: ((.summary.rate_conflict_groups // 0) | safe_count),
    current_rate_conflict_group_count: ((.summary.current_rate_conflict_groups // 0) | safe_count),
    schedule_rate_conflict_group_count: ((.summary.schedule_rate_conflict_groups // 0) | safe_count),
    financial_metadata_conflict_group_count: ((.summary.financial_metadata_conflict_groups // 0) | safe_count),
    rate_empty_metadata_conflict_group_count: ((.summary.rate_empty_metadata_conflict_groups // 0) | safe_count),
    applied_group_count: ((.summary.groups_applied // 0) | safe_count)
  },
  groups: [(.groups // [])[] | {
    group_key: ((.group_key // .group_id // null) | id_or_null),
    contract_ids: ((.contract_ids // []) | ids),
    survivor_id: ((.survivor_id // null) | id_or_null),
    delete_ids: ((.delete_ids // []) | ids),
    operation: ((.operation // null) | safe_operation),
    blocker_codes: ((.blocker_codes // []) | safe_codes),
    field_conflicts: ((.field_conflicts // []) | safe_fields),
    rate_conflicts: {
      candidate: {
        current_value: ((.rate_conflicts.candidate.current_value // false) | safe_bool),
        schedule: ((.rate_conflicts.candidate.schedule // false) | safe_bool),
        schedule_scopes: ((.rate_conflicts.candidate.schedule_scopes // []) | safe_rate_scopes)
      },
      client: {
        current_value: ((.rate_conflicts.client.current_value // false) | safe_bool),
        schedule: ((.rate_conflicts.client.schedule // false) | safe_bool),
        schedule_scopes: ((.rate_conflicts.client.schedule_scopes // []) | safe_rate_scopes)
      },
      framework: {
        current_value: ((.rate_conflicts.framework.current_value // false) | safe_bool),
        schedule: ((.rate_conflicts.framework.schedule // false) | safe_bool),
        schedule_scopes: ((.rate_conflicts.framework.schedule_scopes // []) | safe_rate_scopes)
      }
    },
    financial_metadata_conflict: ((.financial_metadata_conflict // false) | safe_bool),
    financial_metadata_conflict_fields: ((.financial_metadata_conflict_fields // []) | safe_financial_metadata_fields),
    financial_metadata_rate_bearing_contract_ids: ((.financial_metadata_rate_bearing_contract_ids // []) | ids),
    rate_empty_metadata_conflict: ((.rate_empty_metadata_conflict // false) | safe_bool),
    rate_empty_metadata_conflict_fields: ((.rate_empty_metadata_conflict_fields // []) | safe_financial_metadata_fields),
    rate_empty_metadata_contract_ids: ((.rate_empty_metadata_contract_ids // []) | ids),
    same_day_schedule_conflicts: {
      candidate: ((.same_day_schedule_conflicts.candidate // false) | safe_bool),
      client: ((.same_day_schedule_conflicts.client // false) | safe_bool),
      framework: ((.same_day_schedule_conflicts.framework // false) | safe_bool)
    },
    notification_repoint: {
      retained_historical_ids: ((.notification_repoint.retained_historical_ids // []) | ids),
      retained_historical_count: ((.notification_repoint.retained_historical_count // 0) | safe_count)
    },
    hard_delete: {
      child_row_ids: ((.hard_delete.child_row_ids // {}) | safe_child_id_object),
      child_row_counts: ((.hard_delete.child_row_counts // {}) | safe_child_count_object),
      historical_row_ids: ((.hard_delete.historical_row_ids // {}) | safe_history_id_object),
      historical_row_counts: ((.hard_delete.historical_row_counts // {}) | safe_history_count_object),
      protective_completed_signature_ids: ((.hard_delete.protective_completed_signature_ids // []) | ids),
      protective_signed_generated_contract_ids: ((.hard_delete.protective_signed_generated_contract_ids // []) | ids)
    },
    source_rate_snapshot_matches: (if (.source_rate_snapshot_matches | type)=="boolean" then .source_rate_snapshot_matches else null end)
  }],
  global_blocker_codes: ((.global_blocker_codes // []) | safe_codes),
  blockers: [(.blockers // [])[] | {
    group_key: ((.group_key // null) | id_or_null),
    contract_ids: ((.contract_ids // []) | ids),
    codes: ((.codes // []) | safe_codes),
    fields: ((.fields // []) | safe_fields)
  }],
  applied: [(.applied // [])[] | {
    group_key: ((.group_key // null) | id_or_null),
    operation: ((.operation // null) | safe_operation),
    survivor_id: ((.survivor_id // null) | id_or_null),
    deleted_ids: ((.deleted_ids // []) | ids),
    reparented_counts: ((.reparented_counts // {}) | safe_counts_object),
    candidate_rate_source_contract_id: ((.candidate_rate_source_contract_id // null) | id_or_null),
    client_rate_source_contract_id: ((.client_rate_source_contract_id // null) | id_or_null),
    framework_rate_source_contract_id: ((.framework_rate_source_contract_id // null) | id_or_null),
    rate_metadata_source_contract_id: ((.rate_metadata_source_contract_id // null) | id_or_null),
    allow_rate_empty_metadata: ((.allow_rate_empty_metadata // false) | safe_bool),
    field_source_contract_ids: ((.field_source_contract_ids // {}) | safe_field_id_object),
    hard_delete_counts: ((.hard_delete_counts // {}) | safe_hard_delete_counts)
  }],
  # Exception class names are not needed operationally and a regex is not a
  # semantic privacy boundary (a person-like PascalCase string would pass).
  error_type: (if .error_type == null then null else "operation_error" end)
}' "$raw_redacted" > "$report"
rm -f "$raw_redacted"

fingerprint=$(jq -r '.fingerprint // "none"' "$report")
group_count=$(jq -r '.summary.group_count' "$report")
blocker_count=$(jq -r '.summary.blocker_count' "$report")
{
  echo "mode=$MODE"
  echo "fingerprint=$fingerprint"
  echo "groups=$group_count"
  echo "blockers=$blocker_count"
} > "$summary"
echo "fingerprint=$fingerprint; groups=$group_count; blockers=$blocker_count"

operation_ok=true
if ! jq -e '.ok == true' "$report" >/dev/null; then
  operation_ok=false
  echo "::error::operation refused; redacted diagnostic is in the repository artifact"
fi
if [ "$MODE" = "apply" ] && [ "$fingerprint" != "$PLAN_FINGERPRINT" ]; then
  operation_ok=false
  echo "::error::returned fingerprint does not match the approved plan"
fi

cleanup_task
trap - EXIT
[ "$operation_ok" = true ]
