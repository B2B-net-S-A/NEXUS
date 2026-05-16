# LinkedIn Chrome Extension — Completion Report

**Data:** 2026-05-14
**Branch:** `claude/jolly-bose-e8c0db`
**PR:** https://github.com/artur-t-96/Nexus/pull/188
**Plan source:** `/Users/arturtwardowski/.claude/plans/zaplanuj-wszystko-woolly-mango.md`

## Co zostało dostarczone

Wtyczka Chrome (Manifest V3) + endpoint backendu pozwalające dodać kandydata
z otwartego profilu LinkedIn (`https://www.linkedin.com/in/*`) jednym
kliknięciem do NEXUS, z opcjonalnym przypisaniem do rekrutacji i tagami.

### Backend (`backend/`)

| Plik | Zmiana |
|---|---|
| `app/api/candidates.py` | Nowy `POST /api/candidates/from-linkedin` (status 201/200) + 4 prywatne helpery (`_slug_from_linkedin_url`, `_derive_names_from_preview`, `_enrich_linkedin_background`, `_assign_candidate_to_job`, `_is_sync_stale`). Reused: `find_candidate_duplicates`, `normalize_linkedin_url`, `sync_candidate_linkedin`. |
| `app/schemas/candidate.py` | 3 nowe Pydantic schemas: `LinkedInPreview`, `CandidateFromLinkedInCreate`, `CandidateFromLinkedInResponse`. Import `PipelineStage`. |
| `app/main.py` | CORS `allow_origin_regex=r"^chrome-extension://[a-p]{32}$"` dla extension service worker. |
| `tests/test_candidates_from_linkedin.py` | 11 testów TDD (in-process `app_client` fixture). |

**Logika endpointu:**
1. `normalize_linkedin_url` → 400 jeśli malformed/company/jobs URL
2. `find_candidate_duplicates(linkedin=...)` → jeśli match: zwróć `action="existing"` + opcjonalnie assign to job + odpal resync jeśli `linkedin_synced_at` > 7d
3. Inaczej: utwórz Candidate stub (name/lastname z preview lub fallback "LinkedIn"/slug), source=`linkedin_extension`, opcjonalnie `_assign_candidate_to_job` (atomicznie, 404 jeśli Job nie istnieje → automatyczny rollback przez `get_db`)
4. `background_tasks.add_task(_enrich_linkedin_background, candidate.id)` — Proxycurl enrichment uruchamia się PO zwróceniu response, w try/except (nie blokuje, nie propaguje błędów)

### Extension (`extension/`)

Vanilla JS Manifest V3, ~1700 linii, brak npm/buildu/TS.

```
extension/
├── manifest.json
├── README.md                            # 12-point smoke checklist
├── .gitignore
├── icons/icon-{16,32,48,128}.png        # solid violet z "N" (programmatic gen via stdlib)
└── src/
    ├── background/service-worker.js     # JWT, refresh, central fetch dispatcher
    ├── content/
    │   ├── content-script.js            # FAB injection + MutationObserver (SPA)
    │   ├── modal-host.js                # Shadow DOM modal (auth gate, form, success/existing view)
    │   ├── linkedin-scraper.js          # DOM extraction multi-selector fallback
    │   └── modal.css                    # Linear theme tokens, scoped to shadow root
    ├── options/options.{html,js,css}    # login + backend URL config
    └── shared/
        ├── messages.js                  # MSG_TYPE constants
        ├── storage.js                   # chrome.storage.local wrappers
        └── api-client.js                # fetch + 401 refresh + envelope
```

**Architektura:**
- **Action icon w toolbarze → otwiera options page** (nie popup — chrome.runtime.openOptionsPage())
- **Content script** detektuje `linkedin.com/in/*`, wstrzykuje floating FAB "+ NEXUS" (inline-styled, poza Shadow DOM żeby był wszędzie widoczny). MutationObserver re-injectuje po SPA navigation.
- **Modal** w Shadow DOM (`mode: "closed"`, `all: initial` na :host). Klik FAB → dynamic `import(chrome.runtime.getURL("src/content/modal-host.js"))` (web-accessible-resources).
- **Wszystkie network calls przez SW** — content script i options używają `chrome.runtime.sendMessage`. JWT nigdy w content scripcie.
- **Auth flow:** options → POST `/api/auth/login` → store tokens → broadcast `AUTH_CHANGED` do wszystkich kart `linkedin.com`. 401 podczas pracy → silent `/api/auth/refresh?refresh_token=...` → retry.

## Co NIE zostało dostarczone (świadome decyzje + follow-ups)

### Świadome decyzje (z planu / Phase 3 review)

1. **Brak migracji DB** — partial unique index na `linkedin_slug` odłożone do
   follow-up. Dedup działa via `find_candidate_duplicates` (zwraca
   `linkedin_slug_match` score 0.95). Tiny race condition risk gdy dwa
   kliknięcia w tym samym czasie → 2 duplikaty. Realnie zero dla solo-rekrutera.
2. **Brak `pending` status w `LinkedinSyncStatus`** — używamy istniejącego
   `disabled` jako stanu początkowego. Migracja enum-a byłaby ciężka, a `disabled`
   + `linkedin_synced_at IS NULL` to wystarczający sygnał "czeka na pierwszą sync".
3. **Brak quick-add (silent batch)** — świadoma decyzja, mniej śmieci w bazie.
4. **Chrome Web Store** — load-unpacked dla Artura na start. Web Store wymaga
   privacy policy URL + screenshots + ~3 dni review.

### Follow-ups (Phase 2)

| Priorytet | Item | Effort |
|---|---|---|
| **P1** | Audyt duplikatów na prod + migracja partial unique index na `linkedin_slug` | ~30 min |
| **P2** | Hetzner Object Storage dla ikon wtyczki (gdy będzie Web Store) | ~10 min |
| **P2** | Privacy policy URL na `nexus.dynaminds.pl/legal/extension-privacy` | ~30 min |
| **P3** | Sentry w extension (`@sentry/browser` standalone CDN load) | ~1h |
| **P3** | Smart detection "czy mam otwarte /jobs/{id} w innej karcie NEXUS" → pre-fill job dropdown | ~2h |
| **P3** | LinkedIn Sales Navigator support (`linkedin.com/sales/...`) | ~1h |

## Smoke test plan

### Backend (po merge + Coolify deploy)

```bash
# 1. Health check (90s po push do main)
curl -fsSL "https://api.nexus.dynaminds.pl/api/health" \
  -A "dynaminds-smoke-test/1.0 (+github-actions; Nexus)" | jq .

# 2. Get fresh JWT
JWT=$(curl -sf -X POST "https://api.nexus.dynaminds.pl/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"<EMAIL>","password":"<PASS>"}' | jq -r .access_token)

# 3. Create candidate from a real public LinkedIn profile
curl -X POST "https://api.nexus.dynaminds.pl/api/candidates/from-linkedin" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"linkedin_url":"https://www.linkedin.com/in/satyanadella/","preview":{"name":"Satya","lastname":"Nadella","headline":"Chairman & CEO Microsoft"}}'
# expect: 201 + {"action":"created","candidate_id":N,...}

# 4. Second call → existing
curl -X POST "https://api.nexus.dynaminds.pl/api/candidates/from-linkedin" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"linkedin_url":"https://pl.linkedin.com/in/satyanadella?utm=test"}'
# expect: 200 + {"action":"existing","candidate_id":<same N>,...}

# 5. Wait ~30s, verify Proxycurl enrichment ran
curl -fsSL "https://api.nexus.dynaminds.pl/api/candidates/<N>" \
  -H "Authorization: Bearer $JWT" | jq '{linkedin, linkedin_sync_status, linkedin_synced_at, linkedin_current_company}'
# expect: linkedin_sync_status == "ok" (after Proxycurl finishes)
```

### Extension (load-unpacked dla Artura)

12-point checklist w [`extension/README.md`](../extension/README.md#smoke-test-checklist-12-punktów).

Kluczowe punkty:
- [ ] `chrome://extensions` → Tryb dewelopera → Load unpacked → wybierz `extension/`
- [ ] Klik ikony w toolbarze → options page → login → "Zalogowano jako: <email>"
- [ ] Otwórz `linkedin.com/in/satyanadella` → "+ NEXUS" floats bottom-right
- [ ] Klik FAB → modal z imieniem/headline/location z DOM
- [ ] "Senior" w job search → debounce 300ms → wyniki
- [ ] Submit → success toast z `[otwórz profil]` linkiem do nexus.dynaminds.pl
- [ ] Drugi raz → "Już w bazie" + button "Odśwież z LinkedIn"

## Files changed

- 4 plików backendu (3 modified, 1 new test file)
- 18 plików extension (wszystkie new)
- 1 nowy plik docs (ten raport)

**Łącznie ~2400 linii dodanych, 0 usuniętych.**

## Co dalej

1. **Merge PR** (Artur, po smoke teście backendu)
2. **Coolify auto-deploy** (~2 min webhook + 90s smoke)
3. **Load extension** w Chrome (load-unpacked, jednorazowo)
4. **Login** w options page
5. **Otwórz LinkedIn** dowolny profil → klik "+ NEXUS" → 🎉
