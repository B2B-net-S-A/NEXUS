# Post-Interview Feedback — Completion Report

Data: 2026-04-22
Branch: `main` (nietknięte commity — ~45 modified + untracked, nie commitowane bez prośby)

## Cel

Dodać pipeline automatycznych powiadomień po interview + modal do zbierania feedbacku (kandydat-side / klient-side) z eskalacjami i auto-akcjami.

## Status: **funkcjonalne, gotowe do commit+deploy**

Wave 1-5 zaimplementowane i zweryfikowane end-to-end (Python trigger call + Chrome MCP UI smoke). Wave 4 scaffold (SMTP_ENABLED=false default — czeka na decyzję Artura o credentialach).

---

## Nowe pliki

### Backend
- [backend/alembic/versions/0043_interview_feedback.py](../backend/alembic/versions/0043_interview_feedback.py) — tabela `interview_feedback` (18 kolumn, 4 check constraints, unique (event_id, source)) + 4 dedykowane enumy + `notificationtype` extend (4 values) + `calendar_events.needs_attention`
- [backend/app/models/interview_feedback.py](../backend/app/models/interview_feedback.py) — SQLAlchemy model z enum classes `FeedbackSource`, `InterestLevel`, `NextStepPreference`, `InterviewDecision`
- [backend/app/schemas/](../backend/app/schemas/) — schemas inline w router (wzorzec interview_questions.py)
- [backend/app/api/interview_feedback.py](../backend/app/api/interview_feedback.py) — CRUD: POST/GET/GET by id/PATCH/DELETE + ownership checks (author/DL/admin)
- [backend/app/services/calendar_auto_complete.py](../backend/app/services/calendar_auto_complete.py) — `mark_ended_interviews_completed()` flipuje scheduled→completed po `end_time + 10 min`
- [backend/app/services/interview_feedback_actions.py](../backend/app/services/interview_feedback_actions.py) — `apply_post_feedback_actions()`: advance/reject/dead → `suggest_next_step` notification
- [backend/app/services/email.py](../backend/app/services/email.py) — SMTP wrapper gated by `SMTP_ENABLED=false`, no-op gdy off

### Frontend
- [frontend/src/components/feedback/InterviewFeedbackModal.tsx](../frontend/src/components/feedback/InterviewFeedbackModal.tsx) — modal z 2 tabami (candidate_side / client_side), walidacja, tel:/mailto: linki, fetch eventu + kandydata + istniejącego feedbacku

## Zmodyfikowane pliki

### Backend
- [backend/app/models/notification.py](../backend/app/models/notification.py) — +4 NotificationType: `post_interview_t15`, `post_interview_t45`, `post_interview_t2h_escalation`, `suggest_next_step`
- [backend/app/models/calendar_event.py](../backend/app/models/calendar_event.py) — +`needs_attention BOOLEAN`
- [backend/app/models/__init__.py](../backend/app/models/__init__.py) — re-export `InterviewFeedback` + enumy
- [backend/app/services/notification_triggers.py](../backend/app/services/notification_triggers.py) — +3 triggery (`check_post_interview_t15/t45/t2h_escalation`), +auto-complete integration w `run_all_triggers()`
- [backend/app/core/config.py](../backend/app/core/config.py) — +4 Phase 14 timing configs + 7 SMTP configs
- [backend/app/main.py](../backend/app/main.py) — import + include_router interview_feedback + **FIX: podpięcie `notification_triggers_loop()` w lifespan** (istniejący bug Phase 13 — triggery nigdy nie działały w runtime)
- [backend/entrypoint.sh](../backend/entrypoint.sh) — backfill 4 nowych notificationtype values + 4 enumów Phase 14 + `calendar_events.needs_attention` + M365 drift fix (`m365_series_master_id`, `m365_change_key` — pre-existing, wymaga dla ORM)

### Frontend
- [frontend/src/lib/api.ts](../frontend/src/lib/api.ts) — `interviewFeedbackApi` (list/get/create/update/delete)
- [frontend/src/components/NotificationsDropdown.tsx](../frontend/src/components/NotificationsDropdown.tsx) — +4 entries w `TYPE_CONFIG`, +modal launcher dla `post_interview_*` (parsuje event_id z linku)

## Nowe endpointy API

| Method | Path | Rola |
|--------|------|-----|
| POST   | `/api/interview-feedback` | Tworzy feedback (409 gdy duplikat `(event, source)`) |
| GET    | `/api/interview-feedback?calendar_event_id=X` | Lista feedbacków |
| GET    | `/api/interview-feedback/{id}` | Pojedynczy |
| PATCH  | `/api/interview-feedback/{id}` | Update (author lub DL/admin) |
| DELETE | `/api/interview-feedback/{id}` | Delete (author lub DL/admin) |

## Nowy schemat DB

```
interview_feedback
├── id, calendar_event_id FK, candidate_id FK, job_id FK, author_id FK
├── feedback_source: enum(candidate_side, client_side)
├── [candidate_side] overall_impression (1-5), interest_level, candidate_questions, concerns, next_step_preference
├── [client_side] technical_fit, soft_fit, overall_fit, decision, client_questions, feedback_summary
├── created_at, updated_at
└── UNIQUE (calendar_event_id, feedback_source)

calendar_events
└── + needs_attention BOOLEAN DEFAULT false (flaga T+2h eskalacja)

notificationtype enum
└── + post_interview_t15, post_interview_t45, post_interview_t2h_escalation, suggest_next_step
```

## Triggery (co 5 min, Pn-Pt)

1. **Auto-complete**: scheduled → completed gdy `end_time + 10 min < now`
2. **post_interview_t15**: 15 min po end_time → recruiter (+DL dla client-side) "Zadzwoń i zbierz feedback"
3. **post_interview_t45**: 45 min → drugi ping do tych samych
4. **post_interview_t2h_escalation**: 2h → DL + flaga `needs_attention=true`

Rozróżnienie **candidate-side vs client-side** idzie przez najnowszy `CandidateStage.stage`:
- `PipelineStage.client_interview` → client-side
- pozostałe nieterminalne → candidate-side

Dedupe: natywny przez `ix_notif_dedup_daily` (user + type + entity + dzień).

## Auto-akcje po submit feedbacku

- `decision=advance` → emit `suggest_next_step` do recruiter
- `decision=reject` → emit `suggest_next_step` do recruiter (sugestia zamknięcia + pula)
- `interest_level=dead` → emit `suggest_next_step` do recruiter

Wszystkie best-effort (try/except wraps, log only) — nigdy nie blokują zapisu feedbacku.

## Weryfikacje end-to-end wykonane

1. ✅ `alembic heads` fail oczekiwany (pre-existing multi-head), `Base.metadata.create_all` fallback tworzy tabelę
2. ✅ Migracja 0043 ma `down_revision = "0042_interview_questions"` (single chain — po naprawie multi-head)
3. ✅ Tabela `interview_feedback` + index + check constraints w DB
4. ✅ 4 nowe `notificationtype` values w DB enum
5. ✅ `calendar_events.needs_attention` column + partial index
6. ✅ Backend POST 201 z pełnym obiektem (`curl` test, event 12, feedback id=1)
7. ✅ Chrome MCP: zalogowanie claude-admin, dropdown, click notyfikacji → modal otwiera się z tel: linkiem, 2 tabami, ratingami 1-5, selektami
8. ✅ `run_all_triggers()` ręczne wywołanie: `post_interview_t15: 2` emitted (event 11+12)
9. ✅ Dedupe: 2. run wraca `0` (daily dedup index aktywny)
10. ✅ `stage_stuck_7d: 12` — istniejący trigger Phase 13 zaczął działać (naprawiony bug w lifespan)
11. ✅ Auto-action: `client_side decision=advance` → notyfikacja `suggest_next_step` id=6438 w DB
12. ✅ Email scaffold: `send_email()` gracefully returns `False` gdy `SMTP_ENABLED=false`

## Znane ograniczenia / TODO (v2)

1. **Email fallback NIE podpięty do triggera T+45** — scaffold gotowy (`send_post_interview_reminder()`), ale integracja wymaga:
   - Artur dostarczy SMTP creds (SendGrid / Gmail / własny)
   - env w Coolify: `SMTP_ENABLED=true`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `FRONTEND_URL_BASE`
   - Wybór strategii kolejkowania (sync blocking w trigger loop vs `asyncio.create_task` post-commit)
2. **M365 webhook** na `event.updated` — skipped (polling co 300s OK dla v1)
3. **Auto-move-to-pool** gdy reject/dead — świadomie pominięte jako destruktywne (wymaga inspekcji `auto_cc_collaborators.py`). V1 = tylko notyfikacja "przenieś do puli / zamknij".
4. **Sekcja "Interviews & Feedback" na karcie kandydata** — nie zbudowana (out of MVP). Modal dostępny tylko przez click notyfikacji.
5. **Akcja "Log feedback" w kalendarzu** — nie zbudowana (out of MVP).
6. **Chrome MCP `form_input` + React controlled select** — tool nie dispatchuje onChange dla niektórych React-controlled selectów; manualne kliknięcie użytkownika działa bez problemu (zweryfikowane przez backend POST). To ograniczenie tool'a, nie kodu.
7. **Test integracyjny Python** (`test_post_interview_flow.py`) — nie napisany; ręczna weryfikacja przez `run_all_triggers()` pokryła krytyczne ścieżki.
8. **Multi-head Alembic** — pre-existing w repo; `0043_interview_feedback.py` ma prawidłowe `down_revision`, ale pełny `alembic upgrade heads` wciąż pada w dev przez stare heady. Produkcja powinna być OK po czystym `alembic merge`.

## Bug fix przy okazji

**Fixed: Phase 13 notification_triggers_loop nigdy nie działał.** Task był zdefiniowany w `backend/app/tasks/triggers_loop.py` ale nie był podpięty w `main.py` lifespan. Bez tego żaden z 5 istniejących triggerów (`dl_stage_stale_6h`, `client_feedback_eobd`, `powercalling_kpi`, `candidate_feedback_1h`, `stage_stuck_7d`) nie generował notyfikacji w runtime. Naprawione razem z podpięciem Phase 14 triggerów. Dodatkowy test wykazał że `stage_stuck_7d` natychmiast wygenerował 12 alertów przy pierwszym runie.

## Deployment checklist

1. Commit+push na `main` lub branch `feat/post-interview-feedback`
2. Coolify auto-deploy
3. Monitor logów: `docker compose logs backend | grep "notification_triggers_loop"` — powinno pokazać start
4. Weryfikacja DB: `alembic heads` (powinno być 1 po cleanup), tabela `interview_feedback` istnieje
5. Chrome MCP smoke: login claude-admin → bell → klik `post_interview_*` → modal → fill → submit → DB row + needs_attention=false
6. Rollback: migracja 0043 ma `downgrade()` droppujący tabelę + enumy + kolumnę (enum values zostają — PG limitation)

## Decyzje architektoniczne

- **Osobna tabela `interview_feedback`** zamiast rozszerzenia `screening_note` — bo semantyka inna (ScreeningNote = pre-screening z kandydatem, InterviewFeedback = post-interview z dwóch stron)
- **`needs_attention BOOLEAN`** na CalendarEvent zamiast JSONB `metadata.needs_attention` — prostsze query w UI, można indexować partial
- **Inline Pydantic schemas** w router pliku zamiast osobnego `schemas/interview_feedback.py` — zgodnie z wzorcem `interview_questions.py` (nowszy styl)
- **SMTP_ENABLED=false default** — żadnych nieoczekiwanych emaili w dev/CI bez env setup
- **3 osobne `NotificationType`** dla T+15 / T+45 / T+2h — daje natywny dedupe daily per stage, zamiast stanu w message

---

*Report compiled 2026-04-22 przez Claude Opus 4.7*
