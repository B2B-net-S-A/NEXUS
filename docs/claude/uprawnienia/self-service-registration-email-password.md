# Self-service registration (email/password — alternatywa dla Microsoft SSO)

Rejestracja bez logowania przez Microsoft, ograniczona do domen z whitelisty
`SSO_ALLOWED_DOMAINS` (te same co SSO, np. `b2bnetwork.pl`). Nowe konta są
**Recruiterem** (`UserRole.recruiter`) i zaczynają z dwiema zamkniętymi bramami:
`email_verified=false` do kliknięcia linku aktywacyjnego oraz
`profile_completed=false` do ukończenia obowiązkowego onboardingu Recruitera.
Najpierw użytkownik weryfikuje email, następnie po pierwszym loginie aplikacja
kieruje go na `/onboarding`; dopiero ukończenie onboardingu odblokowuje shell i
powierzchnie kandydatów/RODO. Legacy `UserRole.user` jest wycofywany przez
migrację 0210 i nie może być już nadawany. Pełny opis pierwotnego mechanizmu:
`docs/self-registration-completion-report.md`; aktualny cutover:
`docs/role-dashboard-rbac-cutover.md`.

- **Kill-switch:** `SELF_REGISTRATION_ENABLED` (default `false`). Off → `POST /api/auth/register` zwraca 503, strona `/register` pokazuje "rejestracja wyłączona".
- **Endpoint `POST /api/auth/register`** (`app/api/auth.py`): gate → domain whitelist (fail-closed, pusta lista = reject-all) → rola **wymuszona `recruiter`** server-side (`SelfRegisterRequest` NIE ma pola `role`) i `profile_completed=false` → `email_verified=False` → token + mail. **Anti-enumeration:** zawsze generyczne `201` (nigdy `409`), bcrypt liczony na obu ścieżkach (no timing leak); duplikat na niezweryfikowanym koncie re-wysyła link, na zweryfikowanym — cicho no-op.
- **`POST /api/auth/verify-email`** — jednorazowy 64-hex token (SHA-256 hash, TTL 24 h) → `email_verified=True`. **`POST /api/auth/resend-verification`** — anti-enum (zawsze 200).
- **Login + onboarding gate:** `login` blokuje konta z `email_verified=False` (czytelny komunikat PL). Po weryfikacji Recruiter może się zalogować, ale `profile_completed=false` kieruje go na `/onboarding` i blokuje domenowe endpointy do chwili ukończenia formularza. Istniejący userzy email/hasło + SSO mają `email_verified=True` (backfill migracji + SSO ustawia), więc **nie są dotknięci bramą emailową**.
- **Frontend:** `/register` (formularz) + `/register/verify` (auto-verify on mount) + link na `/login`; `/register` w `PUBLIC_PATHS` (`middleware.ts`).
- **DB:** `users.email_verified` (BOOLEAN NOT NULL DEFAULT true) + tabela `email_verification_tokens` (bliźniacza do `password_reset_tokens`) — migracja `0139_email_verification` (na bazie `0138_candidate_expected_hourly_rate`; aplikowana przez `alembic upgrade heads`).
- **Aktywacja na prod:** Coolify → `SSO_ALLOWED_DOMAINS` zawiera `b2bnetwork.pl` (już z SSO) + `SMTP_ENABLED=true` (+ SMTP creds, żeby mail aktywacyjny wyszedł) + `SELF_REGISTRATION_ENABLED=true`.
