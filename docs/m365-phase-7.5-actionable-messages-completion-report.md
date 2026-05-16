# Phase 7.5 — Outlook Actionable Messages — completion report

Wdrożenie: PR [#184](https://github.com/artur-t-96/Nexus/pull/184), merged
2026-05-14, deployed at SHA `310706e`. Post-deploy weryfikacja: 2026-05-16
(round-trip + idempotency + 3 negatywne ścieżki — wszystkie green na prod).

## Co dostarczone

### Nowe pliki

| Ścieżka | Rola |
|---|---|
| `backend/app/services/m365/actionable_messages.py` | JSON-LD `OpenAction` card builder + JWT sign/verify (HS256, 7d TTL, purpose-scoped `interview_confirmation`). Escapuje `</` → `<\/` w JSON-LD żeby crafted `button_label` z `</script>` nie wybił się ze `<script type="application/ld+json">` bloku. |
| `backend/app/api/public_interview_confirmation.py` | `POST /api/public/interview-confirmation` — JWT verify → CalendarEvent lookup → cross-check `candidate_id` z payloadu → UPDATE `candidate_confirmed_at` + `candidate_confirmation_source='outlook_actionable'`. Idempotent (drugi klik zwraca oryginalny timestamp). Rate-limit `10/hour/IP` via slowapi. Wszystkie błędy → generyczne `403` (no info leak). |
| `backend/alembic/versions/0106_calendar_event_confirmation.py` | `ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS candidate_confirmed_at TIMESTAMPTZ` + `candidate_confirmation_source VARCHAR(50)`. Idempotent. |
| `backend/tests/test_actionable_messages.py` | 17 testów: 10 pure (JWT round-trip, expired/tampered/wrong-purpose/missing-claim rejection, card shape, `</script>` escape, fallback link, HTML escape labelu) + 7 integration (happy path, idempotency, expired, wrong action, candidate mismatch, unknown event, garbage token). |
| `docs/ops/actionable-messages-setup.md` | Runbook dla Outlook Actionable Email Developer Dashboard (https://outlook.office.com/connectors/oam/publish) — kroki rejestracji, smoke test, znane limitacje (iOS/Android, klasyczny Outlook, tenant policies). |

### Zmienione pliki

| Ścieżka | Zmiana |
|---|---|
| `backend/app/services/m365/sender.py` | Dodano `send_interview_invitation()` — sanityzuje recruiter body, dokleja JSON-LD card + visible fallback `<a>`, ustawia `X-MS-Actionable-Message: true` Graph internet header. Reużywa `_build_idempotency_key` (Phase 2.6) — frontend double-click w tej samej minucie zwraca ten sam row, nie wysyła drugiego JWT. |
| `backend/app/models/calendar_event.py` | Dodano `candidate_confirmed_at: Mapped[Optional[datetime]]` + `candidate_confirmation_source: Mapped[Optional[str]]`. |
| `backend/app/main.py` | Wired `public_interview_confirmation.router` pod `/api`. |
| `backend/app/core/config.py` | `PUBLIC_API_BASE_URL: str = "https://api.nexus.dynaminds.pl"` (default na prod — fallback na wypadek braku env vara). |
| `.github/workflows/ci.yml` | Dorzucono `tests/test_actionable_messages.py` do listy pytestów. |

## Nowe endpointy

| Method | Path | Auth | Rate-limit | Co robi |
|---|---|---|---|---|
| `POST` | `/api/public/interview-confirmation?token=<jwt>` | JWT w query | `10/hour/IP` | Potwierdza interview po stronie kandydata. Idempotent. |

## Migracje DB

- `0106_calendar_event_confirmation` (head) — applied on prod (zweryfikowane 2026-05-16: kolumny istnieją).

## Acceptance criteria — status

- [x] **Migracja zaaplikowana.** Sprawdzone na prod via `\d calendar_events` — kolumny `candidate_confirmed_at` + `candidate_confirmation_source` obecne.
- [x] **Email wysłany przez `send_interview_invitation()` zawiera JSON-LD action w body.** Pure-test `test_card_contains_jsonld_block` + `test_card_jsonld_target_carries_signed_token`.
- [x] **Klik przycisku w Outlook → request leci do `/api/public/interview-confirmation` → DB update + thank-you reply.** Endpoint live na prod; round-trip smoke przez `curl` z prawdziwym JWT (event #4) potwierdzony — `200 OK` + DB `candidate_confirmed_at` ustawione + idempotency works.
- [x] **CI green.** 3/3 checks (`Gitleaks`, `Backend ruff+pytest`, `Frontend typecheck+build`) passed na PR #184.
- [x] **OAM Provider registration.** Zarejestrowany 2026-05-16 autonomicznie przez Claude w https://outlook.office.com/connectors/oam/publish. Provider `NEXUSATS`, MsEntra auth (App ID `b5be7c77-eb7b-46ee-89b3-c6fa0f5ea7d9` = `M365_CLIENT_ID`), Test Users tier (auto-approved, status: **Approved**), sender + test user `artur.twardowski@b2bnetwork.pl`, target URL `https://api.nexus.dynaminds.pl/api/public/`. Setting applies w ciągu ~1h. Pełna recepta + edits w `docs/ops/actionable-messages-setup.md`.
- [ ] **Live Outlook click test.** Po ~1h od rejestracji — Artur wysyła testowy invite do `artur.twardowski@b2bnetwork.pl`, otwiera w Outlook, klika button, assert że `event.candidate_confirmed_at` flipnie. Wymaga ludzkiego klika (browser/M365 mailbox).

## Post-deploy weryfikacja (2026-05-16)

```bash
# 1. Migracja
docker exec postgres ... psql -c "SELECT column_name FROM information_schema.columns
  WHERE table_name='calendar_events' AND column_name LIKE 'candidate_confirm%'"
# → candidate_confirmation_source | candidate_confirmed_at  ✓

# 2. Round-trip — happy path (event 4, candidate 33)
TOKEN=$(docker exec backend python -c 'from app.services.m365.actionable_messages
  import sign_confirmation_token; print(sign_confirmation_token(event_id=4, candidate_id=33))')
curl -X POST "https://api.nexus.dynaminds.pl/api/public/interview-confirmation?token=$TOKEN"
# → 200 {"success":true,"message":"Dziękujemy za potwierdzenie. Do zobaczenia!","confirmed_at":"2026-05-16T11:31:09.486567Z"}  ✓

# 3. Idempotency — drugi klik
curl -X POST "https://api.nexus.dynaminds.pl/api/public/interview-confirmation?token=$TOKEN"
# → 200 confirmed_at NIEZMIENIONY  ✓

# 4. Candidate mismatch → 403
# 5. Unknown event → 403
# 6. Garbage token → 403
# wszystkie generyczne "Link nieprawidłowy lub wygasł." — no info leak  ✓

# Cleanup smoke side-effect na event 4
UPDATE calendar_events SET candidate_confirmed_at=NULL,
  candidate_confirmation_source=NULL WHERE id=4;
```

## Znane ograniczenia

- **Outlook iOS / Android** — partial support. Większość buildów renderuje
  fallback link, nie button. To akceptowalne (link działa).
- **Outlook on the web** + **new Outlook desktop** — pełne wsparcie.
- **Klasyczny Outlook 2019/2021** — zależy od cumulative updates. Newer →
  button. Older → fallback link.
- **Tenant policies** — niektóre korporacyjne tenanty disable'ują Actionable
  Messages globalnie. Kandydat widzi wtedy tylko fallback link. Nie ma sposobu
  wykryć tego po stronie servera.
- **Provider approval lag** — dopóki Microsoft nie zatwierdzi providera dla
  `Organization` scope, tylko recruiter używający `My mailbox` rejestracji
  zobaczy button. Reszta widzi fallback link.
- **Brak UI integracji** — `send_interview_invitation()` to nowa funkcja, ale
  jeszcze nie podpięta pod żaden user-facing przycisk w UI. Wywołać można
  programatycznie z innych miejsc backendu. UI wire-up to follow-up task.

## Bezpieczeństwo

- **JWT trust boundary**: shared `M365_STATE_SIGNING_KEY` z OAuth state JWT,
  ale `purpose` claim (`interview_confirmation` vs `m365_oauth_state`) jest
  cross-use guardem. Test `test_wrong_purpose_rejected` pinuje to.
- **JSON-LD `</script>` injection**: zabezpieczone przez escape `</` → `<\/`
  w `json.dumps` output (tak samo jak Django `json_script`).
- **Brute-force**: `10/hour/IP` slowapi rate-limit + 7-dniowy HMAC-SHA256
  token z 256-bit signing key → impractical do guesswork.
- **Info leak**: wszystkie token failures (bad signature, expired, wrong
  purpose, wrong candidate, missing event) zwracają identyczne `403 {"detail":
  "Link nieprawidłowy lub wygasł."}`.
- **Idempotency**: drugi klik nie nadpisuje `candidate_confirmed_at` — Outlook
  re-renderuje POST response inline, więc zmiana timestampu na drugim kliku
  myli usera.
- **CalendarEvent FK integrity**: `event.candidate_id != payload.candidate_id`
  → 403. Defense-in-depth na wypadek bugu w mincie tokena lub replayu na
  re-assigned event.

## Follow-up (poza scope Phase 7.5)

1. **UI wire-up**: dodać przycisk "Wyślij invite z potwierdzeniem" w
   profilu kandydata → wywołuje `send_interview_invitation()`. Obecnie
   funkcja czeka nieużywana.
2. ~~**Outlook Actionable Email Developer Dashboard rejestracja**~~ —
   ✅ DONE 2026-05-16 (Test Users tier). Promote do Organization scope
   po pomyślnym Live Outlook click test (#5 acceptance).
3. **CalendarEvent.candidate_confirmation_source** w UI — pokazać w event
   detail card (`Potwierdzony przez kandydata 14:32 (Outlook)`).
4. **Powiadomienie recruiterowi** po potwierdzeniu — np. in-app notification
   lub Slack webhook gdy `candidate_confirmed_at` flipnie z NULL na NOW().
5. **Cancel/reschedule actions** — analogiczna implementacja dla "Nie mogę
   potwierdzić" i "Zaproponuj inny termin". `action` claim w JWT już zostawia
   miejsce na te scenariusze.
