---
description: Deploy nexus przez workflow Deploy (okno 19:00–07:00) + weryfikacja /api/health
argument-hint: [--force] (rebuild bez cache Coolify)
allowed-tools: Bash(gh:*), Bash(curl:*), Bash(jq:*), Bash(git:*), Bash(sleep:*), Bash(date:*)
---

Wdrożenie **nexus** idzie WYŁĄCZNIE przez workflow „Deploy” (`.github/workflows/deploy.yml`):
bramka zielonego HEAD-a maina (DEP-01), smoke, deep health, kontrola migracji.
Bezpośrednie wywołanie API Coolify omija te kontrole — nie używaj go.

**Okno wdrożeń 19:00–07:00 pon–pt (Europe/Warsaw, decyzja Artura 14.10.2026).** W dzień
roboczy zwykły bieg kończy się błędem okna; w sobotę i niedzielę okna nie ma (17.10.2026). `emergency=true` (z powodem) omija okno —
**wyłącznie na wyraźne polecenie Artura w czacie**. Awaryjny deploy wypuszcza cały HEAD
maina, czyli wszystko scalone w ciągu dnia.

**Step 1 — sprawdź okno:**

```bash
TZ=Europe/Warsaw date '+%H:%M %Z'
python3 .github/scripts/select_release_sha.py in-freeze --freeze-window "$(gh variable get DEPLOY_FREEZE_WINDOW 2>/dev/null || echo 7-19)" \
  && echo "OKNO CISZY — bez polecenia Artura nie wdrażaj; zaległe zmiany wdroży wieczorny bieg." \
  || echo "Okno wdrożeń otwarte."
```

**Step 2 — uruchom Deploy (tylko w oknie wdrożeń):**

```bash
FORCE=false; [ "${ARGUMENTS:-}" = "--force" ] && FORCE=true
gh workflow run deploy.yml --ref main -f force_rebuild="$FORCE"
sleep 5
gh run list --workflow Deploy --branch main --limit 1 --json databaseId,status,url
```

Awaryjnie (tylko na polecenie Artura): `-f emergency=true -f reason="<powód>"`.

**Step 3 — poczekaj na koniec biegu i sprawdź wersję:**

```bash
RUN_ID=$(gh run list --workflow Deploy --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
curl -fsSL "https://api.nexus.dynaminds.pl/api/health" | jq -c '{status, version}'
git fetch -q origin main && git rev-parse origin/main
```

`version` ma być SHA z `origin/main` (albo jego zielonym potomkiem, jeśli w trakcie budowy coś weszło).

**Po sukcesie:** krótki raport (SHA, link do biegu, czas).
**Po błędzie:** `gh run view "$RUN_ID" --log-failed | tail -60`.
