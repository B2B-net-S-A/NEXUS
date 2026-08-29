def positive_id:
  if type=="number" and . > 0 and floor == . then . else null end;
def safe_count:
  if type=="number" and . >= 0 and floor == . then . else 0 end;
def safe_fields:
  if type!="array" then []
  elif all(.[];
    .=="contract_type" or .=="start_date" or .=="end_date"
    or .=="client_order_end_date" or .=="rate_client") then .
  else error("non-allowlisted correction field") end;
def safe_status:
  if .=="draft" or .=="active" or .=="paused" or .=="completed"
     or .=="cancelled" then . else null end;
def safe_effective_type:
  if .=="md" or .=="cost" or .=="periodic" then . else null end;
def safe_dependency_counts:
  if type!="object" then {}
  elif all(keys[];
    test("^[a-z_][a-z0-9_]{0,62}\\.[a-z_][a-z0-9_]{0,62}\\.[a-z_][a-z0-9_]{0,62}$"))
  then with_entries(.value |= safe_count)
  else error("invalid dependency identity") end;
def safe_fk_issue:
  if .=="unsafe_identifier" or .=="foreign_schema"
     or .=="composite_foreign_key" or .=="unexpected_primary_key"
     or .=="unexpected_target_column"
     or .=="unknown_foreign_key" or .=="unexpected_delete_action" then .
  else null end;
def safe_bool:
  if type=="boolean" then . else error("invalid boolean") end;
def safe_reconciliation_status:
  if .=="verified" or .=="verified_after_cli_failure"
     or .=="not_committed" or .=="verification_failed" then .
  else error("invalid reconciliation status") end;
def safe_optional_sha256:
  if .==null then null
  elif type=="string" and test("^[0-9a-f]{64}$") then .
  else error("invalid optional fingerprint") end;
{
  schema_version: 4,
  mode,
  ok,
  fingerprint,
  summary: {
    manifest_contracts: (.summary.manifest_contracts | safe_count),
    contracts_found: (.summary.contracts_found | safe_count),
    contracts_with_changes: (.summary.contracts_with_changes | safe_count),
    contract_field_changes: {
      contract_type: (.summary.contract_field_changes.contract_type | safe_count),
      start_date: (.summary.contract_field_changes.start_date | safe_count),
      end_date: (.summary.contract_field_changes.end_date | safe_count),
      client_order_end_date: (
        .summary.contract_field_changes.client_order_end_date | safe_count
      ),
      rate_client: (.summary.contract_field_changes.rate_client | safe_count)
    },
    periodic_orders_to_delete: (.summary.periodic_orders_to_delete | safe_count),
    legacy_null_orders_preserved: (
      .summary.legacy_null_orders_preserved | safe_count
    ),
    disallowed_standalone_order_types: (
      .summary.disallowed_standalone_order_types | safe_count
    ),
    disallowed_group_order_types: (
      .summary.disallowed_group_order_types | safe_count
    ),
    dependency_rows: (.summary.dependency_rows | safe_count),
    set_null_dependency_rows: (.summary.set_null_dependency_rows | safe_count),
    set_null_deleted_dependency_rows: (
      .summary.set_null_deleted_dependency_rows | safe_count
    ),
    legacy_null_dependency_rows: (
      .summary.legacy_null_dependency_rows | safe_count
    ),
    blockers: (.summary.blockers | safe_count),
    approval_fingerprint: (
      if ((.summary.approval_fingerprint // "") | type)=="string"
         and ((.summary.approval_fingerprint // "")
              | test("^[0-9a-f]{64}$"))
      then .summary.approval_fingerprint
      else null
      end
    )
  },
  contracts: [(.contracts // [])[] | {
    id: (.id | positive_id),
    changed_fields: ((.changed_fields // []) | safe_fields)
  } | select(.id != null)],
  orders: [(.orders // [])[] | {
    id: (.id | positive_id),
    client_id: (.client_id | positive_id),
    status: (.status | safe_status),
    has_file: (if (.has_file | type)=="boolean" then .has_file else false end),
    dependency_counts: (
      (.dependency_counts // {}) | safe_dependency_counts
    ),
    set_null_dependency_counts: (
      (.set_null_dependency_counts // {}) | safe_dependency_counts
    ),
    set_null_deleted_dependency_counts: (
      (.set_null_deleted_dependency_counts // {}) | safe_dependency_counts
    )
  } | select(.id != null and .client_id != null)],
  legacy_null_orders: [(.legacy_null_orders // [])[] | {
    id: (.id | positive_id),
    client_id: (.client_id | positive_id),
    status: (.status | safe_status),
    has_file: (if (.has_file | type)=="boolean" then .has_file else false end),
    dependency_counts: (
      (.dependency_counts // {}) | safe_dependency_counts
    )
  } | select(.id != null and .client_id != null)],
  blockers: [(.blockers // [])[] | {
    code: (
      if (.code | type)=="string" and (.code | test("^[a-z0-9_]{1,80}$"))
      then .code else error("invalid blocker code") end
    ),
    contract_id: ((.contract_id // null) | positive_id),
    order_id: ((.order_id // null) | positive_id),
    group_id: ((.group_id // null) | positive_id),
    client_id: ((.client_id // null) | positive_id),
    effective_type: ((.effective_type // null) | safe_effective_type),
    schema: (
      if ((.schema // null) | type)=="string"
         and ((.schema // "") | test("^[a-z_][a-z0-9_]{0,62}$"))
      then .schema else null end
    ),
    table: (
      if ((.table // null) | type)=="string"
         and ((.table // "") | test("^[a-z_][a-z0-9_]{0,62}$"))
      then .table else null end
    ),
    column: (
      if ((.column // null) | type)=="string"
         and ((.column // "") | test("^[a-z_][a-z0-9_]{0,62}$"))
      then .column else null end
    ),
    issue: ((.issue // null) | safe_fk_issue)
  }],
  reconciliation: (
    if .mode=="apply" then {
      status: (.reconciliation.status | safe_reconciliation_status),
      precommit_intent: (.reconciliation.precommit_intent | safe_bool),
      apply_report_present: (.reconciliation.apply_report_present | safe_bool),
      apply_report_matches_intent: (
        .reconciliation.apply_report_matches_intent | safe_bool
      ),
      apply_exit_code: (.reconciliation.apply_exit_code | safe_count),
      post_apply_audit_exit_code: (
        .reconciliation.post_apply_audit_exit_code | safe_count
      ),
      post_apply_fingerprint: (
        .reconciliation.post_apply_fingerprint | safe_optional_sha256
      ),
      desired_state_verified: (
        .reconciliation.desired_state_verified | safe_bool
      )
    } else null end
  )
}
