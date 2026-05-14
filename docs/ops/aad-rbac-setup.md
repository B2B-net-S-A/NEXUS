# AAD group-based RBAC — operational setup

Phase 7.2 of the M365 expansion plan. Makes Azure Active Directory the
authoritative source for NEXUS user roles: on every Microsoft SSO login the
callback reads the user's AAD group memberships and assigns a NEXUS role
from a configurable map. Users not in any mapped group are denied.

The code is already deployed (PR #181 + hotfix PR #187, commits `17b72b0` +
`464e2fd`), but the feature is **dormant** until the steps below are
finished. Default state on prod: `AAD_GROUP_RBAC_ENABLED=false` — SSO works
exactly like before Phase 7.2.

## Why dormant by default

Flipping the flag without completing all of the steps below is an outage:

- Without admin consent for the new Graph scope, every fresh login hits
  AADSTS65001/65004 at Microsoft's consent screen.
- Without AAD groups populated and the role map filled in, every login
  fails the "no matching group" check and gets `is_active=false`.

Run through the checklist top-to-bottom before flipping the flag.

## One-time Azure AD setup

1. **Grant admin consent for `GroupMember.Read.All`.**
   - Azure Portal → Microsoft Entra ID → App registrations → search for the
     NEXUS app by client ID `b5be7c77-eb7b-46ee-89b3-c6fa0f5ea7d9` (= the
     `M365_CLIENT_ID` env var).
   - API permissions → Add a permission → Microsoft Graph → Delegated
     permissions → search `GroupMember.Read.All` → check it → Add
     permissions.
   - Back on the permissions list, click **Grant admin consent for
     b2bnetwork.pl**. The row should turn green with "Granted for
     b2bnetwork.pl".
   - This scope is delegated (acts on behalf of the signed-in user), not
     application — NEXUS never reads groups for someone who isn't actively
     logging in.

2. **Create AAD security groups for each NEXUS role.** Suggested names
   (match the `AAD_GROUP_ROLE_MAP_JSON` example below):

   | AAD group | NEXUS role |
   |-----------|------------|
   | `NEXUS-Admins` | `admin` |
   | `NEXUS-HeadOfRecruitment` | `head_of_recruitment` |
   | `NEXUS-DeliveryLeads` | `delivery_lead` |
   | `NEXUS-TACs` | `tac` |
   | `NEXUS-Recruiters` | `recruiter` |
   | `NEXUS-Sourcers` | `sourcer` |

   Azure Portal → Microsoft Entra ID → Groups → New group → Security →
   members assigned manually. Copy the **Object ID** of each new group.

3. **Add members.** Put each NEXUS user into exactly one group. If someone
   ends up in two groups (e.g. a DL who also admins), the first matching
   key in `AAD_GROUP_ROLE_MAP_JSON` wins — order the JSON keys so the
   highest-privilege role appears first.

## Coolify env vault

In the NEXUS Coolify app environment:

```text
AAD_GROUP_ROLE_MAP_JSON={"<uuid-admins>":"admin","<uuid-head>":"head_of_recruitment","<uuid-dl>":"delivery_lead","<uuid-tac>":"tac","<uuid-rec>":"recruiter","<uuid-src>":"sourcer"}
AAD_GROUP_RBAC_ENABLED=true
```

Both env vars are `is_runtime=true, is_buildtime=false` — no rebuild
required. Coolify auto-restarts the backend container when env vars
change, which is enough for the new values to take effect.

Order matters in `AAD_GROUP_ROLE_MAP_JSON`: Python preserves dict
insertion order, and the role mapper returns the first match. Put admin
GUID first, then HoR, then DL, etc.

A misspelled role (e.g. `"admiin"` instead of `"admin"`) raises a 500
the first time a user logs in — the lazy validator in
`settings.aad_group_role_map` rejects anything that isn't a real
`UserRole`. Better to find this in staging than in prod.

## Verification

After Coolify finishes the restart:

```bash
# Authorize URL should now request the extra scope.
UA="dynaminds-smoke-test/1.0 (+manual; AAD-RBAC)"
curl -fsSL -A "$UA" "https://api.nexus.dynaminds.pl/api/auth/microsoft/authorize" \
  | jq -r '.authorize_url' | grep -o 'scope=[^&]*'
# Expect: scope=openid+profile+email+User.Read+GroupMember.Read.All+offline_access
```

Then log in as a known user (e.g. `claude-admin@b2bnet.pl` if you placed
them in `NEXUS-Admins`):

```sql
-- On the prod DB after their first SSO login post-flip:
SELECT email, role, is_active, aad_group_ids
FROM users
WHERE email = 'claude-admin@b2bnet.pl';
-- Expect: role=admin, is_active=true,
-- aad_group_ids contains {"id":"<uuid-admins>","displayName":"NEXUS-Admins"}
```

Audit rows for role changes/denials live in the `activity` table with
`action IN ('sso_aad_role_assigned', 'sso_aad_role_denied')`.

## Day-2 operations

**Move a user between groups in AAD without forcing logout.** Update the
group membership in Azure, then call the admin endpoint to re-evaluate
their stored snapshot:

```bash
TOKEN="<admin JWT>"
USER_ID="<target user id>"
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "https://api.nexus.dynaminds.pl/api/admin/users/$USER_ID/resync-aad-groups"
```

Caveat: the resync endpoint re-runs the **mapping** against already-stored
`aad_group_ids` — it does NOT call Graph. For a fresh group fetch the user
must log in via SSO again. Use this endpoint primarily after
`AAD_GROUP_ROLE_MAP_JSON` changes (e.g. promoting an existing group to a
higher role).

**Change `AAD_GROUP_ROLE_MAP_JSON`.** Update in Coolify env vault, wait for
the container restart, then optionally run the resync endpoint on each
affected user. No SSO logout required.

**Rollback.** Flip `AAD_GROUP_RBAC_ENABLED=false`. SSO immediately reverts
to legacy behaviour (everyone keeps their last assigned role; new users
get the default `recruiter`). The `users.aad_group_ids` column stays
populated for audit but is no longer read at login.

## Known limits

- `fetch_user_groups` does not follow `@odata.nextLink`. Realistic NEXUS
  users have under a few dozen group memberships and the default Graph
  page size is 100, so the first page is always complete. If a user with
  > 100 groups logs in we miss the tail — add pagination here when that
  becomes relevant.
- Directory roles (Global Admin etc.) are filtered out by `@odata.type`
  inspection. Only `#microsoft.graph.group` entries grant NEXUS roles.
- The hotfix in PR #187 reads the kill-switch per request, so flipping
  the flag in Coolify takes effect on the next API call without redeploy.
  But the env-var change still triggers a Coolify container restart;
  there is a ~5s window where requests during the restart can fail with
  502.
