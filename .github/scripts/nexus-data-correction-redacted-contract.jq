type=="object"
and .mode==$mode
and (.ok | type=="boolean")
and ((.fingerprint==null and .ok==false)
     or ((.fingerprint | type)=="string"
         and (.fingerprint | test("^[0-9a-f]{64}$"))))
and ((.summary // {}) | type=="object")
and ((.ok==false) or .fingerprint==null
     or (((.summary.approval_fingerprint // "") | type)=="string"
         and ((.summary.approval_fingerprint // "")
              | test("^[0-9a-f]{64}$"))))
and ((.contracts // []) | type=="array")
and ((.orders // []) | type=="array")
and ((.legacy_null_orders // []) | type=="array")
and ((.blockers // []) | type=="array")
and (if $mode=="apply" then
       ((.reconciliation // null) | type)=="object"
       and (.reconciliation.status=="verified"
            or .reconciliation.status=="verified_after_cli_failure"
            or .reconciliation.status=="not_committed"
            or .reconciliation.status=="verification_failed")
       and ((.reconciliation.precommit_intent | type)=="boolean")
       and ((.reconciliation.apply_report_present | type)=="boolean")
       and ((.reconciliation.apply_report_matches_intent | type)=="boolean")
       and ((.reconciliation.desired_state_verified | type)=="boolean")
       and ((.reconciliation.apply_exit_code | type)=="number")
       and (.reconciliation.apply_exit_code >= 0)
       and (.reconciliation.apply_exit_code
            == (.reconciliation.apply_exit_code | floor))
       and ((.reconciliation.post_apply_audit_exit_code | type)=="number")
       and (.reconciliation.post_apply_audit_exit_code >= 0)
       and (.reconciliation.post_apply_audit_exit_code
            == (.reconciliation.post_apply_audit_exit_code | floor))
       and (.reconciliation.post_apply_fingerprint==null
            or (((.reconciliation.post_apply_fingerprint | type)=="string")
                and (.reconciliation.post_apply_fingerprint
                     | test("^[0-9a-f]{64}$"))))
       and (if .ok then
              .reconciliation.desired_state_verified==true
              and (.reconciliation.status=="verified"
                   or .reconciliation.status=="verified_after_cli_failure")
            else
              .reconciliation.status=="not_committed"
              or .reconciliation.status=="verification_failed"
            end)
     else
       .reconciliation==null
     end)
