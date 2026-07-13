# Automatyczne powiadomienia email o odrzuceniu kandydata — raport ukończenia

**Status:** implementacja ukończona, testy zielone (21/21), brak UI smoke-testu (czeka na rebuild frontendu / deploy).

## Co zostało zrobione

Feature: po odrzuceniu kandydata, który był już widoczny dla klienta (`cv_sent`, `client_interview`, `acceptance`, `negotiation`, `onboarding`), system **planuje wysyłkę emaila** ze skrzynki rekrutera (MS365 Graph) z delay 15 min i możliwością anulowania. Email zawiera listę innych aktywnych procesów kandydata u nas (tylko stanowiska, bez nazw klientów — NDA).

### Backend

| Warstwa | Plik | Rola |
|---|---|---|
| Migracja | [0045_rejection_emails.py](backend/alembic/versions/0045_rejection_emails.py) | tabela `scheduled_rejection_emails` + enum `rejectionemailstatus` + 5 nowych wartości `notificationtype` |
| Model | [rejection_email.py](backend/app/models/rejection_email.py) | `ScheduledRejectionEmail` + `RejectionEmailStatus` enum |
| Scheduler | [rejection_email_scheduler.py](backend/app/services/rejection_email_scheduler.py) | `maybe_schedule()` + `dispatch()` + renderer z `{{#if other_processes}}` |
| Background loop | [rejection_email_loop.py](backend/app/tasks/rejection_email_loop.py) | asyncio loop co 30 s (wzorzec `microsoft365_sync.py`), rejestracja w `main.py` lifespan |
| Hook | [pipeline.py](backend/app/api/pipeline.py) (`POST /api/pipeline/move`) | po `rejected` wywołuje `maybe_schedule`; response zawiera `scheduled_rejection_email_id` |
| HTTP endpoint | [rejection_emails.py](backend/app/api/rejection_emails.py) | `GET /{id}`, `POST /{id}/cancel`, `GET /by-candidate/{id}` |
| Schema | [schemas/pipeline.py](backend/app/schemas/pipeline.py) | `StageMove.send_rejection_email`, `rejection_email_template_id` + response pole |
| Template seed | [emails.py DEFAULT_TEMPLATES](backend/app/api/emails.py) | nowy szablon "Auto-odrzucenie (po widoczności u klienta)" |
| Enum | [notification.py](backend/app/models/notification.py) | 5 nowych `NotificationType` wartości (scheduled/sent/cancelled/skipped/failed) |

### Frontend

| Plik | Zmiana |
|---|---|
| [Toast.tsx](frontend/src/components/Toast.tsx) | nowy typ `action` + `showActionToast()` z undo button |
| [RejectionV2.tsx](frontend/src/components/v2/modals/RejectionV2.tsx) | checkbox "Wyślij email za 15 min", domyślnie on dla `external` previous stage |
| [KanbanBoardV2.tsx](frontend/src/components/v2/pages/KanbanBoardV2.tsx) | wyliczanie `previousStageCategory`, przekazywanie `send_rejection_email`, toast z "Cofnij wysyłkę" |
| [CandidateDetailV2.tsx](frontend/src/components/v2/pages/CandidateDetailV2.tsx) | polskie labele timeline dla 5 action types |

### Testy — 21/21 PASS

- **14 unit testów** (`test_rejection_email_scheduler.py`) — trigger set, renderer, conditional if-block, no client-name leak
- **7 integration testów** (`test_rejection_email_integration.py`) — maybe_schedule + cancel endpoint + "other processes" window query

## Kluczowe decyzje (vs plan)

1. **Trigger `cv_sent`** — włączony (mimo `STAGE_CATEGORY.internal`), bo biznesowo "CV wysłane klientowi" = widoczne.
2. **`_load_other_active_processes`** — używa window function `ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY id DESC)`, aby brać TYLKO latest stage per job. Naiwna wersja z subquery + DISTINCT miała bug (kandydat z `[screening, hired]` trafiał do wyniku).
3. **Snapshot body_html** — zamrożony w `maybe_schedule`, więc zmiany szablonu / innych procesów w oknie 15 min nie wpłyną na wysyłaną treść.
4. **Fallback brak M365 connection** — email NIE idzie, status `skipped`, notification do rekrutera "podłącz skrzynkę" (zachowuje personal touch, żadnego noreply@).
5. **Cancel authZ** — rekruter (owner), admin lub delivery_lead. Chroni przed misfire gdy właściciel na L4.
6. **Renderer** — brak Jinja2 (reguła "minimum changes"); własny string-replace + regex dla `{{#if other_processes}}...{{/if}}`.

## Uwagi techniczne

- **Alembic multi-heads**: repo ma 3 heads (`0036_microsoft365`, `0046_backfill_contractor_drafts`, `0029` orphan). Moja migracja `0045_rejection_emails` jest na chainie 0044→0045→0046. Problem wieloheads nie w moim scope.
- **main.py zmiany** podjęły też nieintencjonalny `import app.models as _models` (wymusza załadowanie metadata — `m365.Email` nie miał routingu, więc bez tego FK `scheduled_rejection_emails.email_id → emails.id` nie rozwiązywał się w `create_all` DEBUG). Zmiana Artura/lintera po moim pierwszym restarcie.
- **Pre-existing ORM/DB drift** na tabeli `jobs` (`closed_at` w ORM, brak w DB) — integration testy używają raw INSERT żeby to obejść. Drift nie do naprawienia w tym PR.

## Co zostało NIE zrobione / odłożone

1. **UI smoke-test przez Chrome MCP** — frontend draftany jest production-build w Dockerze, potrzebuje rebuildu. Nie zrobiono bez explicit zgody (reguła autonomous-verification).
2. **E2E Playwright** — wyłączone ze scope'u tej sesji.
3. **Rebuild + Coolify deploy** — czeka na zgodę Artura na commit+push.

## Weryfikacja lokalna

```bash
# Backend zdrowy, loop wstał
docker compose logs --tail=200 backend | grep -iE "rejection_email"
# → co 30 s SELECT z scheduled_rejection_emails

# Endpoint działa
: "${NEXUS_DEV_ADMIN_EMAIL:?Set a local demo email}"
: "${NEXUS_DEV_ADMIN_PASSWORD:?Set a local demo password}"
TOKEN=$(jq -n --arg email "$NEXUS_DEV_ADMIN_EMAIL" \
  --arg password "$NEXUS_DEV_ADMIN_PASSWORD" \
  '{email:$email,password:$password}' | \
  curl -s -X POST http://localhost:8000/api/auth/login \
    -H 'Content-Type: application/json' -d @- | jq -r .access_token)
curl -s "http://localhost:8000/api/rejection-emails/999999" \
  -H "Authorization: Bearer $TOKEN"
# → {"detail":"Scheduled rejection email not found"}

# Testy
docker compose exec -T backend pytest tests/test_rejection_email_*.py -v
# → 21 passed
```

## Następne kroki (propozycja)

1. Artur daje `git add` + commit — wtedy Coolify auto-deploy.
2. Po deployu: UI smoke-test przez Chrome MCP — drag'n'drop kandydata `cv_sent → rejected`, sprawdzenie toast "Cofnij wysyłkę", weryfikacja w timeline.
3. Follow-up (inny PR): naprawić ORM drift `jobs.closed_at` + merge 3 Alembic heads.
