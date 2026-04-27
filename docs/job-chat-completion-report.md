# Job Chat — Completion Report

**Data:** 2026-04-27
**Branch:** `main`
**Commits:** `fadc160` (job-chat,engagement bundle), `247ccaf` (job-chat clean), `23fad97` (model registry)
**Plan:** `~/.claude/plans/zaplanuj-wszystko-zgodnie-z-valiant-wirth.md`
**Status:** wdrożone, testy backend 12/12 PASS, push do `main` → Coolify auto-deploy

---

## Co zostało zbudowane

Wewnętrzny czat zespołu per rekrutacja. Zakładka "Chat" w widoku joba,
widoczna dla: admin / recruiter (owner) / delivery_lead / TAC / aktywni
job_collaborators. Klient i kandydat NIE mają dostępu.

### Funkcje v1 (zgodnie z planem)

- Tekst (voice = v2)
- @mention z parserem `@email` / `@userId`, filtruje do członków projektu
- Reply-to (cytowanie poprzedniej wiadomości), bez threading
- Edit/delete własne (soft delete). Admin może usuwać cudze
- Pinned messages (max 3/job, DL + admin)
- Postgres FTS przez `tsvector` + GIN index + auto-update trigger
- Realtime przez istniejący WS (`chat:message:{new,edit,delete,pin}`)
- Notyfikacje w-app (persistent + WS) + rezerwacja kolumn na Teams/Slack v2
- Unread badge per tab + mark-read on open
- Rate limit 30 msg/min/user (slowapi)

---

## Pliki

### Nowe
- `backend/app/models/job_chat.py` — 3 modele SQLAlchemy
- `backend/app/schemas/job_chat.py` — Pydantic Create/Update/Response/List
- `backend/app/api/job_chat.py` — 10 REST endpointów
- `backend/app/services/job_membership.py` — `is_member_of_job`, `list_job_member_ids`
- `backend/app/services/mention_parser.py` — regex parser `@email` / `@userId`
- `backend/alembic/versions/0063_job_chat.py` — migracja: 3 tabele, FTS trigger, enum extensions
- `backend/tests/test_job_chat.py` — 12 scenariuszy pytest
- `frontend/src/types/job-chat.ts` — typy TS + `CHAT_BUS_EVENT`
- `frontend/src/components/v2/pages/JobChatTab.tsx` — kompletny komponent UI

### Zmodyfikowane
- `backend/app/models/__init__.py` — rejestracja JobChat\*
- `backend/app/models/job.py` — relacja `chat_messages`
- `backend/app/models/notification.py` — enum `job_chat_message`, `job_chat_mention`
- `backend/app/models/user_activity.py` — `chat_message_added`
- `backend/app/main.py` — `include_router(job_chat_api.router, ...)`
- `frontend/src/lib/api.ts` — namespace `jobChatApi`
- `frontend/src/hooks/useNotifications.ts` — handler eventów `chat:message:*`
- `frontend/src/app/jobs/[id]/page.tsx` — nowy tab "Chat" z unread badge

---

## Endpointy API

| Method | Path | Auth | Opis |
|---|---|---|---|
| GET | `/api/jobs/{job_id}/chat/messages` | member | paginacja `before_id`, search FTS |
| POST | `/api/jobs/{job_id}/chat/messages` | member, 30/min | parse @mentions, push WS+Notif |
| PATCH | `/api/jobs/{job_id}/chat/messages/{id}` | autor | edit (re-parse mentions) |
| DELETE | `/api/jobs/{job_id}/chat/messages/{id}` | autor lub admin | soft delete |
| POST | `/api/jobs/{job_id}/chat/messages/{id}/pin` | DeliveryLeadPlus | max 3/job |
| DELETE | `/api/jobs/{job_id}/chat/messages/{id}/pin` | DeliveryLeadPlus | unpin |
| GET | `/api/jobs/{job_id}/chat/pinned` | member | lista przypiętych |
| PUT | `/api/jobs/{job_id}/chat/read` | member | mark-as-read pointer |
| GET | `/api/jobs/{job_id}/chat/unread-count` | member | badge w UI |
| GET | `/api/jobs/{job_id}/chat/members` | member | autocomplete @mention |

---

## Testy

```
pytest tests/test_job_chat.py -p no:cacheprovider
================= 12 passed, 107 warnings in 61.95s ==================
```

Pokrycie scenariuszy:
1. ✅ member_can_post
2. ✅ non_member_forbidden (403 na GET i POST)
3. ✅ admin_sees_all (z app_auth_headers)
4. ✅ mention_creates_notification (job_chat_mention + job_chat_message)
5. ✅ soft_delete (placeholder, content nie wycieka)
6. ✅ edit_sets_flag (`is_edited=true`, `edited_at` ustawione)
7. ✅ recruiter_cannot_pin (403)
8. ✅ dl_can_pin_max_3 (4. pin → 400)
9. ✅ pagination_before_id (60 msg, limit=50, has_more=true)
10. ✅ fts_search ("Python" matches 3/4)
11. ✅ unread_count (po mark_read=0, po 2 nowych=2)
12. ✅ ws_dispatched_on_send (mock notify_user, weryfikacja eventów)

---

## Migracja

```sql
-- 0063_job_chat (down_revision: 0062_engagement_declaration_tokens)
ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_chat_message';
ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_chat_mention';
ALTER TYPE useractiontype ADD VALUE IF NOT EXISTS 'chat_message_added';

CREATE TABLE job_chat_messages (...) -- z search_vector tsvector
CREATE INDEX ix_job_chat_messages_search ON ... USING gin (search_vector)
CREATE INDEX ix_job_chat_messages_pinned ON ... WHERE pinned AND NOT is_deleted
CREATE TRIGGER job_chat_messages_search_update -- BEFORE INSERT/UPDATE OF content

CREATE TABLE job_chat_mentions (...)
CREATE TABLE job_chat_read_state (...)
```

Migracja zastosowana w lokalnym dev. Coolify entrypoint wywoła `alembic
upgrade head` przy starcie kontenera w prod.

---

## Out of scope (v2 backlog)

Świadomie pominięte w v1, do zaadresowania w kolejnych fazach:

- Voice notes + transkrypcja (Whisper / Voyage)
- Per-candidate chat (osobny model `CandidateChatMessage`)
- Threading (nested replies)
- Per-user mute/unmute per job
- Teams/Slack 2-way sync (kolumny `external_platform`, `external_message_id`
  już zarezerwowane w schemacie)
- File attachments (S3/Coolify volume)
- Message reactions (emoji)
- Typing indicator ("X is typing…")
- Full read receipts per-user-per-message
- Email fallback dla offline > 15 min
- Admin "read-all" superpower (dziś admin widzi tylko gdzie jest collab/recruiter/DL)

---

## Known limitations / followups

- **Pre-existing /openapi.json 500** w prod backend — nie blokuje pracy ani nie
  powstał w tej feature; problem `RedirectResponse` ForwardRef gdzieś w
  innym module. Endpointy chatu działają normalnie (zwracają 401/403/200).
- **Multi-head alembic** (`0036_microsoft365` vs główna gałąź) — pre-existing
  tech debt; dodanie merge migracji to osobna faza cleanup.
- **No email fallback v1** — TODO w kodzie. Trigger loop z Phase 14 jest
  naturalnym miejscem do dodania.

---

## Verification flow

1. Lokalny dev: `docker exec nexusats-backend-1 pytest tests/test_job_chat.py` — 12/12 ✅
2. Migracja: `alembic upgrade head` — zastosowana, tabele + FTS index obecne
3. Endpointy: `curl /api/jobs/1/chat/messages` → 401/403 (auth required) ✅
4. Push `main` → Coolify auto-deploy w toku
5. **Done:** Chrome MCP UI smoke test ✅
   - Tab "Chat" widoczny i klikalny w `/jobs/831`
   - Deep-link `?tab=chat` aktywuje zakładkę od razu
   - Lista członków: 4 admini (poprawnie agregowani z list_job_members)
   - Wysłanie wiadomości przez frontend → backend → list refresh OK (3 wiadomości)
   - Backend POST przez curl → 201, FTS search "hotfix" → 1 match

---

## Hotfix shipped (commit 0b2ced2)

Po pierwszym push'u prod alembic upgrade pad'ł na pre-existing duplicate
revision id `0029` (file 0029_job_collaborators + 0032_client_materials oba
mają `revision="0029"`). Entrypoint fallback `Base.metadata.create_all`
stworzył tabele JC ale NIE zastosował:
  - `ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_chat_message'`
  - `ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_chat_mention'`
  - `ALTER TYPE useractiontype ADD VALUE IF NOT EXISTS 'chat_message_added'`
  - `CREATE TRIGGER job_chat_messages_search_update`
  - `CREATE INDEX … USING gin (search_vector)`

→ POST /api/jobs/{id}/chat/messages crashował z 500.

**Fix:** dodanie powyższych statementów do `backend/entrypoint.sh`
(`_ENUM_STATEMENTS` + `_COLUMN_STATEMENTS`) — wszystkie idempotentne
(`IF NOT EXISTS` / `OR REPLACE`). Plus `0064_merge_microsoft365_job_chat.py`
no-op merge dla future-deploy stability.

Verified post-redeploy: POST 201, GET list 200, FTS 200, UI smoke ✅.
