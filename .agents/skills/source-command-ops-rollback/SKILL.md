---
name: "source-command-ops-rollback"
description: "Rollback nexus to previous Coolify deployment"
---

# source-command-ops-rollback

Use this skill when the user asks to run the migrated source command `ops-rollback`.

## Command Template

Rollback **nexus** do poprzedniego deployment.

**Opcja A — Coolify panel (preferowane, ETA 1 min):**

URL: https://coolify-nexus.dynaminds.pl

Steps:
1. Otwórz URL → login
2. Resources → nexus → Deployments tab
3. Kliknij "Redeploy" na deployment przed najnowszym

**Opcja B — Coolify API (z terminala):**

List ostatnich 5 deployment-ów:

```bash
source ~/.Codex/secrets/dynaminds-tokens.env
TOKEN="$COOLIFY_NEXUS_TOKEN"
UUID="$COOLIFY_NEXUS_APP_UUID"

curl -fsSL -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" \
  "https://coolify-nexus.dynaminds.pl/api/v1/applications/$UUID/deployments?limit=5" | \
  jq '.[] | {uuid, commit, status, finished_at}'
```

Wybierz `uuid` poprzedniego (status="finished") i redeploy:

```bash
PREV_UUID="<wklej uuid>"
curl -X GET -H "Authorization: Bearer $TOKEN" \
  "https://coolify-nexus.dynaminds.pl/api/v1/applications/$UUID/deployments/$PREV_UUID/redeploy"
```

**Opcja C — git revert (ETA 5-10min):**

```bash
git log --oneline -5
git revert <bad_commit_sha>
git push origin main
```

GH Actions auto-deployuje reverted version.

**Po rollback — verify:**
```bash
sleep 90
SHORT_SHA=$(git rev-parse --short=7 HEAD~1 2>/dev/null || echo "<previous>")
curl -fsSL "https://api.nexus.dynaminds.pl/api/health" | jq -e ".version | startswith(\"$SHORT_SHA\")"
```

Patrz `~/.Codex/rules/deployment-runbook.md` §2 dla pełnej procedury rollback.
