---
description: Deploy nexus via Coolify webhook + 90s smoke test
argument-hint: [--force] (rebuild ignoring cache)
allowed-tools: Bash(source:*), Bash(curl:*), Bash(jq:*), Bash(git rev-parse:*), Bash(sleep:*)
---

Trigger deploy **nexus** na Coolify + smoke test version match.

**Step 1 — trigger deploy:**

```bash
source ~/.claude/secrets/dynaminds-tokens.env
TOKEN="$COOLIFY_NEXUS_TOKEN"
UUID="$COOLIFY_NEXUS_APP_UUID"
FORCE="${ARGUMENTS:-false}"
[ "$FORCE" = "--force" ] && FORCE="true" || FORCE="false"

RESPONSE=$(curl -sf -X GET \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json" \
  "https://coolify-nexus.dynaminds.pl/api/v1/deploy?uuid=$UUID&force=$FORCE")
DEPLOY_UUID=$(echo "$RESPONSE" | jq -r '.deployments[0].deployment_uuid // .deployment_uuid // empty')
echo "Deploy UUID: $DEPLOY_UUID (force=$FORCE)"
```

**Step 2 — poll deployment status (every 30s, max 10min):**

```bash
for i in {1..20}; do
  STATUS=$(curl -sf -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" \
    "https://coolify-nexus.dynaminds.pl/api/v1/deployments/$DEPLOY_UUID" | jq -r .status)
  echo "[$i/20] status=$STATUS"
  case "$STATUS" in
    finished) break ;;
    failed) echo "DEPLOY FAILED — fetch logs:"; curl -sf -H "Authorization: Bearer $TOKEN" "https://coolify-nexus.dynaminds.pl/api/v1/deployments/$DEPLOY_UUID" | jq -r .logs | tail -50; exit 1 ;;
  esac
  sleep 30
done
```

**Step 3 — smoke test (90s wait + version match, 12×15s retry):**

```bash
sleep 90
SHORT_SHA=$(git rev-parse --short=7 HEAD)
for i in {1..12}; do
  HEALTH=$(curl -fsSL "https://api.nexus.dynaminds.pl/api/health" 2>/dev/null)
  STATUS=$(echo "$HEALTH" | jq -r '.status // "unreachable"')
  VERSION=$(echo "$HEALTH" | jq -r '.version // "unknown"')
  if [ "$STATUS" != "unhealthy" ] && [[ "$VERSION" == "$SHORT_SHA"* ]]; then
    echo "✅ Smoke PASS — status=$STATUS, version=$VERSION"
    exit 0
  fi
  echo "[$i/12] status=$STATUS, version=$VERSION (expected ${SHORT_SHA}*)"
  sleep 15
done
echo "❌ Smoke FAIL — version stale or unhealthy"
exit 1
```

**Po sukcesie:** krótki raport (commit SHA, deploy UUID, total time).
**Po błędzie:** ostatnie 50 linii build logs (już wyciągnięte w Step 2).
