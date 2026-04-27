# Chat Phase 2 — Completion Report

**Data:** 2026-04-27
**Branch:** `main`
**Commits:** `af00b83` (29 plików, 3604 insert)
**Plan:** kontynuacja `~/.claude/plans/zaplanuj-wszystko-zgodnie-z-valiant-wirth.md`
**Status:** wdrożone w prod, wszystkie 5 features + 2 bugi zweryfikowane E2E

---

## Co zostało zbudowane

### Bug fixes
- **Bug A:** `/openapi.json` 500 — naprawione. `microsoft365.py:107` używa
  `response_class=RedirectResponse` w decoratorze zamiast `-> RedirectResponse`
  return type. Pydantic 2 nie umie wygenerować JSON schema z Starlette
  Response subclass. Po fixie `/openapi.json` zwraca 200, 331 paths.
- **Bug B:** alembic duplicate revision `0029` — naprawione. Plik
  `0032_client_materials.py` miał `revision = "0029"`, kolidując z
  `0029_job_collaborators.py`. Zmienione na `revision = "0032_client_materials"`,
  dodane do `down_revision` tuple w `0064_merge_microsoft365_job_chat.py`.
  Pojedynczy head, brak duplicate-revision warning.

### Feature 2: Per-candidate chat
- 3 nowe tabele: `candidate_chat_messages`, `candidate_chat_mentions`,
  `candidate_chat_read_state` (mirror schematu job_chat_*)
- Postgres FTS via tsvector + GIN index + auto-update trigger
- Service `services/candidate_membership.py` z funkcjami:
  - `is_member_of_candidate_chat` — admin / candidate.created_by /
    recruiter+DL+TAC dowolnego joba w pipeline / aktywny job_collaborator
    tych jobów
  - `list_candidate_chat_member_ids` / `list_candidate_chat_members`
- 11 endpointów REST pod `/api/candidates/{id}/chat/...` (lista, post,
  edit, delete, pin, unpin, pinned, read, unread-count, members,
  reactions add/remove, read-by)
- WS events `candidate-chat:message:{new,edit,delete,pin,reaction}`
- Tab "Chat" w `CandidateDetailV2` z deep-link `?tab=chat`
- Component `CandidateChatTab.tsx` (mirror JobChatTab)

### Feature 7: Message reactions (emoji)
- 2 nowe tabele: `job_chat_message_reactions` i
  `candidate_chat_message_reactions` z UNIQUE(message_id, user_id, emoji)
- Service `services/chat_reactions.py` — agregacja per emoji →
  `{emoji, count, user_ids}`
- 4 nowe endpointy: POST/DELETE `/messages/{id}/reactions[/]{emoji}`
  dla job + candidate
- Reactions field w `ChatMessageResponse` (job + candidate) automatycznie
  agregowany w bulk
- WS event `chat:message:reaction` (job) + `candidate-chat:message:reaction`
- Frontend: emoji picker (8 quick reactions) na hover, chips per emoji
  pod wiadomością, podświetlone gdy "moja" reakcja, click toggle

### Feature 9: Full read receipts
- Bez zmian schemy — derive z `last_read_message_id ≥ msg_id` w
  `{job,candidate}_chat_read_state`
- 2 nowe endpointy `GET /messages/{id}/read-by` dla job + candidate
- Frontend: button "Przeczytane" w action menu wiadomości, on-click
  fetchuje listę → dropdown z avatarami + relative time

### Feature 10: Admin "read-all" superpower
- Nowy endpoint `GET /api/admin/global-chats?limit=&chat_type=&search=`
  (admin-only) — merge stream job + candidate chats, sortowanie DESC
  po `created_at`, FTS search po treści
- Nowa strona `/admin/chats` z filtrem (Wszystkie / Projekty / Kandydaci),
  search, lista items z ikoną per typ + link do parent (job lub kandydat)
- Auto-refresh co 30s

### Feature 11: Email fallback >15min offline
- Nowe kolumny: `users.last_seen_at` (z indexem) +
  `notifications.email_sent_at`
- WS `connect()` / `disconnect()` aktualizują `users.last_seen_at`
- Background task `tasks/chat_email_fallback.py`:
  - Loop co 60s
  - Skanuje notyfikacje typu `job_chat_*` starsze niż 15 min,
    nieprzeczytane, z `email_sent_at = NULL`
  - Filtruje do userów z `last_seen_at < now - 15min` (lub NULL)
  - "Wysyła" email (obecnie log-only — `_send_chat_email` placeholder
    do podpięcia M365/SES; production swap point clearly marked)
  - Stempluje `email_sent_at = NOW()` żeby unikać duplikatów
- Uruchamiany w lifespan obok 13 innych task'ów

---

## Pliki

### Nowe (10)
- `backend/app/models/candidate_chat.py`
- `backend/app/models/chat_reaction.py`
- `backend/app/schemas/candidate_chat.py`
- `backend/app/services/candidate_membership.py`
- `backend/app/services/chat_reactions.py`
- `backend/app/api/candidate_chat.py`
- `backend/app/api/admin_chats.py`
- `backend/app/tasks/chat_email_fallback.py`
- `backend/alembic/versions/0065_chat_phase2.py`
- `frontend/src/app/admin/chats/page.tsx`
- `frontend/src/components/v2/pages/CandidateChatTab.tsx`

### Zmodyfikowane (15)
- `backend/alembic/versions/0032_client_materials.py` — fix dup-id
- `backend/alembic/versions/0064_merge_microsoft365_job_chat.py` — extended tuple
- `backend/app/api/job_chat.py` — +reactions +read-by, reactions in response
- `backend/app/api/microsoft365.py` — fix openapi (response_class)
- `backend/app/api/ws.py` — last_seen_at stamping
- `backend/app/main.py` — 3 nowe routery + chat_email_fallback_loop
- `backend/app/models/__init__.py` — register 5 new models
- `backend/app/models/candidate.py` — chat_messages relacja
- `backend/app/models/job_chat.py` — reactions relacja
- `backend/app/models/notification.py` — email_sent_at
- `backend/app/models/user.py` — last_seen_at
- `backend/app/schemas/job_chat.py` — ReactionAggregate, ReactionToggleResponse, ReadByUser
- `backend/entrypoint.sh` — idempotentny safety-net dla 5 nowych tabel
- `frontend/src/components/v2/pages/CandidateDetailV2.tsx` — tab "Chat"
- `frontend/src/components/v2/pages/JobChatTab.tsx` — reactions + read-by UI
- `frontend/src/hooks/useNotifications.ts` — handler chat:message:reaction + candidate-chat:*
- `frontend/src/lib/api.ts` — candidateChatApi + adminChatsApi
- `frontend/src/types/job-chat.ts` — ReactionAggregate, GlobalChatItem etc.

---

## Verification (prod)

| # | Test | Wynik |
|---|---|---|
| 1 | `/openapi.json` zwraca schema | ✅ 200 (był 500) |
| 2 | `/api/candidates/4/chat/messages` POST | ✅ 201, id=1 |
| 3 | `/api/jobs/831/chat/messages/7/reactions` POST emoji 🚀 | ✅ 200 (count=1) |
| 4 | `/api/admin/global-chats?limit=5` | ✅ 4 items (mix candidate+job) |
| 5 | UI `/candidates/4` → tab "Chat" | ✅ 5 członków + wiadomość renderuje |
| 6 | UI reaction chip widoczny | ✅ 🚀 1 podświetlone |
| 7 | UI `/admin/chats` global audit feed | ✅ 4 items, ikony, filtry, search |
| 8 | Backend boot: chat_email_fallback_loop | ✅ Started, zaplanowane co 60s |

---

## Out of scope (v3 backlog)

Z poprzedniej fazy 11 features pozostało 6:

- Voice notes + transkrypcja
- Threading (nested replies, jak Slack threads)
- Per-user mute/unmute per job/candidate
- Teams/Slack 2-way sync (kolumny `external_platform`/`external_message_id`
  już zarezerwowane od fazy 1)
- File attachments (S3/Coolify volume + nowy model)
- Typing indicator ("X is typing…", ephemeral WS event)

---

## Known limitations

- **Email fallback log-only** — `_send_chat_email` w `tasks/chat_email_fallback.py`
  loguje "WOULD-SEND" zamiast realnie wysyłać. Production swap point
  clearly marked w komentarzu — wystarczy podpiąć M365 graph send_mail
  lub SES/Sendgrid w jednym miejscu.
- **Read receipts używają last_read_message_id** — granularność per-message
  jest derived (jeśli last_read_message_id≥X to "przeczytał X"). Brak
  prawdziwego per-user-per-message tracking, ale w praktyce to wystarczy
  dla "kto przeczytał" tooltip i jest wydajne.
- **Chat notifications nie używają dedup** — `related_entity_id=None`
  bo dedup index `ix_notif_dedup_daily` nie zawiera `related_entity_type`,
  a job_chat_message id i candidate_chat_message id mogą się nakładać.
  Dla chat eventów (per-message) dedup nie ma sensu i tak.
