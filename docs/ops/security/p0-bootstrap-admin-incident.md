# P0: bootstrap admin and committed credentials

Status: **OPEN P0** until every required rotation below has an owner, timestamp,
and verification evidence in the incident system. Merging/deploying the code fix
does not close the incident.

This runbook is deliberately operator-driven. It does not contain credentials,
does not perform production operations, and does not authorize a history rewrite.

## What happened

Two production-reachable startup paths created login-capable users:

- `scripts/ensure_claude_admin.py` created or reactivated a synthetic admin and
  reset its password on every backend start. A password was committed in Git.
- `seed.py` ran unconditionally from `entrypoint.sh` and could create five demo
  users, including an admin, with committed passwords.

The patch removes the synthetic-admin script and startup call. Demo seeding is
off by default, allowed only with `NEXUS_ENABLE_DEMO_SEED=true` and `DEBUG=true`,
and requires two distinct passwords of at least 16 characters from environment
variables. Production opt-in fails startup.

A full Gitleaks history scan also found committed environment backups, production
secret material, and a deploy private key. The value-free inventory is in
[`gitleaks-history-findings-2026-07-13.md`](gitleaks-history-findings-2026-07-13.md).
Only the six fixed bootstrap/demo-password findings have exact fingerprint
entries in `.gitleaksignore`; the other 23 findings are intentionally not
baselined.

## Required containment and deployment sequence

Perform these steps in a declared maintenance window with one incident commander
and one verifier. Record commands and results, never secret values.

1. Freeze deploys and disable any scheduled or external E2E flow that signs in to
   production. Production smoke tests are limited to `/api/health` and the
   authenticated admin snapshot endpoint using its dedicated machine token.
2. Preserve evidence before mutation: current image digest/commit, backend and
   proxy logs, Coolify audit events, the affected `users` row, relevant
   `activities` and `user_activities`, and the GitHub deploy-key metadata.
3. Inventory active work owned/assigned to the synthetic user and reassign it to
   named employees before quarantine. Preserve historical `created_by`/audit
   foreign keys; the quarantine keeps the original user id for that purpose.
4. Restrict public access to authenticated application routes for the maintenance
   window. A backend restart is required to terminate already-open WebSockets.
5. If any old image could still start, set `CLAUDE_ADMIN_BOOTSTRAP_PWD` in Coolify
   to a cryptographically random value of at least 64 characters. This is a
   temporary containment control only; do not disclose or reuse the value.
6. Build and deploy the patched commit. Verify the expected image digest and that
   startup logs say `Demo seed disabled.` with no synthetic-admin/seed activity.
7. From a private PostgreSQL session, run:

   ```bash
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
     -f docs/ops/security/quarantine-bootstrap-admin.sql
   ```

   The SQL is fail-closed, preserves the historic user id and foreign keys,
   renames the identity, disables and demotes it, removes password/SSO bindings,
   and writes an idempotent incident activity. It aborts if it sees an unexpected
   number of matching rows.
8. Restart the **patched** backend, rerun the quarantine SQL, and repeat the
   verification below. The second run proves startup does not recreate/reactivate
   the identity. Keep public access restricted until this passes.
9. Remove the temporary `CLAUDE_ADMIN_BOOTSTRAP_PWD` only after every runnable old
   image is barred. Delete the variable rather than leaving an unused secret.
10. Re-enable traffic. Do not restore production E2E login automation.

### Verification

- No row exists with the original synthetic email.
- Exactly one quarantine row exists; it has `is_active=false`, `role=user`,
  `roles=["user"]`, `password_hash IS NULL`, and no Microsoft identity binding.
- Login using the retired identity fails; a pre-quarantine access token and
  refresh token both fail. `get_current_user` and refresh load the row and reject
  inactive users.
- Existing WebSockets were terminated by the backend restart.
- `/api/health` is healthy and contains the expected build metadata.
- Current-tree and event-range Gitleaks scans pass. A full-history scan may remain
  red until every non-baselined historical finding is classified and remediated.

## Mandatory credential rotation

Treat lack of confirmed rotation as an open P0 blocker. Rotate/revoke at the
provider first, update Coolify through the secret vault, redeploy, verify use of
the new credential, and then remove the old credential. Do not paste values into
GitHub, chat, tickets, CI logs, or this repository.

- GitHub/Coolify deploy key committed under `.local-state/`: revoke it in GitHub,
  create a new read-only deploy key, and update Coolify.
- Coolify API/panel tokens and every value from the committed Coolify backups and
  `prod_secrets.env`: revoke/rotate and verify Coolify audit history.
- Production PostgreSQL password/connection credentials: rotate, update all
  services and backup jobs, and verify old credentials are rejected.
- Voyage and Fireflies API keys found in history: revoke and replace.
- Every other provider credential identified by the unredacted provider-side
  inventory (for example Anthropic, Microsoft 365, SMTP, Sentry, storage, or
  snapshot tokens): rotate if the committed files contained a non-placeholder.
- The synthetic/bootstrap and demo-account credentials: quarantine as above;
  never reuse them.

Rotate global `SECRET_KEY` if suspicious activity is found or continuity of the
quarantine cannot be proven. Rotation invalidates every JWT and must be planned as
a global sign-out. Otherwise, disabling the row blocks access and refresh tokens
without disrupting all users.

## Incident analysis

Use the preserved user id, not only its renamed email.

- Review `users.created_at`, `updated_at`, `last_seen_at`, role history, password
  resets, SSO fields, and account activation/deactivation events.
- Review `activities` where `user_id` or `entity_id` equals the affected user id,
  including `impersonation_started` and admin/user-management actions.
- Review `user_activities` and correlate candidate, client, contract, pipeline,
  note, CV, email, invoice, and export activity with reverse-proxy/application
  logs and object-storage access logs.
- Review Coolify deploy/restart events and GitHub access for every committed
  token/key, starting at its first reachable commit. For the bootstrap identity,
  the review window must start no later than **2026-04-22**.
- Search for bulk candidate/CV downloads, CSV exports, presigned URLs, mailbox
  attachment access, and impersonation headers.

Audit limitation: not every read, export, download, presigned URL, or WebSocket
event has a durable application audit row. Absence from `activities` is not proof
that access did not occur. Use proxy, object-storage, Microsoft 365, provider, and
host logs; document retention gaps explicitly.

### DPO decision record

P0 cannot be closed until the incident owner and DPO record the decision below
in the controlled incident system. Store only its identifier here, not raw logs
or personal data.

```text
Incident record ID:
Owner:
DPO reviewer:
Decision date:
Evidence window (must begin by 2026-04-22):
Unexplained account activity: yes / no / undetermined
Personal-data breach: yes / no / undetermined
Notification required: yes / no
SECRET_KEY rotation/full logout required: yes / no
Reasoning and legal basis:
Follow-up actions, owners and deadlines:
```

Any unexplained activity requires `SECRET_KEY` rotation, global session
invalidation and a documented DPO assessment; do not close the incident on the
basis of missing application audit rows.

## Rollback

Never roll back to an image containing either startup credential path. If the new
application code must be reverted, forward-build the prior application commit
with this security patch applied, then deploy that new image. The database
quarantine and credential rotations are never rolled back.

Before any rollback, verify that the candidate image:

- has no `ensure_claude_admin.py` or call to it;
- keeps demo seed disabled by default and production-fail-closed;
- contains the hardened Gitleaks configuration and P0 tests.

## Long-term controls

- Run authenticated E2E only in staging with one-time, least-privilege accounts.
- Keep production verification non-mutating and health/snapshot based.
- Keep CI secret scan blocking all build lanes, checksum the scanner binary, and
  scan both the working tree and commits introduced by each event.
- Do not rewrite repository history during containment. Decide separately after
  rotations, clone inventory, legal/forensic review, and a coordinated reclone
  plan. A history rewrite is not a substitute for rotation.
