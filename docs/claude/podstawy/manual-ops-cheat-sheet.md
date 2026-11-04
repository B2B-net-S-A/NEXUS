# Manual ops cheat sheet

```bash
cd "/Users/arturtwardowski/NEXUS (ATS)"

# Quick checks (lokalnie)
cd backend && ruff check app/ && pytest tests/test_scoring_service.py -v
cd ../frontend && npm run type-check && npm run lint && npm run build

# Local stack up (dev with ports)
docker compose up --build  # auto-loads override.yml

# Local prod simulation
docker compose -f docker-compose.yml -f docker-compose.prod.yml up

# Healthcheck (po Fazie 1)
curl -fsSL https://api.<nexus-url>/api/health | jq .
SHORT_SHA=$(git rev-parse --short=7 HEAD)
curl -fsSL https://api.<nexus-url>/api/health | jq -e ".version == \"$SHORT_SHA\""

# Deploy (Coolify ma webhook na main push)
git push origin main
# Sprawdź Coolify dashboard — build status

# Rollback przez Coolify dashboard (świadomie inny niż Compass/LeadGen):
# → resource → Deployments → wybierz poprzedni → Redeploy
```
