# Login: przejście na model email+hasło (wyłączenie przycisku Microsoft)

> Data: 2026-07-13. Zmiana przenosi NEXUS na klasyczny model logowania
> email+hasło z whitelistą domeny `@b2bnetwork.pl`, ukrywa przycisk „Zaloguj się
> przez Microsoft" i **zachowuje** integrację M365 (kalendarz/Teams/mailbox).
> Naprawia też historyczny bug „cofających się uprawnień".

## TL;DR

Klasyczny login (email+hasło), rejestracja, reset hasła, weryfikacja e-mail i
panel admina do ról **już istniały** w kodzie. Ten PR:

1. **Rozprzęga** logowanie SSO od integracji M365 — nowy runtime-flag
   `MICROSOFT_SSO_LOGIN_ENABLED` (default `false`), gating tylko endpointów
   `/api/auth/microsoft/*`, **bez** ruszania kalendarza/Teams/mailbox.
2. **Ukrywa** przycisk „Zaloguj się przez Microsoft" na ekranie logowania.
3. **Egzekwuje** whitelistę domen na `/login` (dotąd tylko rejestracja i SSO ją
   sprawdzały) — fail-open gdy whitelista pusta, sprawdzana dopiero po weryfikacji
   hasła (brak enumeracji kont).
4. Nie zmienia bloku AAD-RBAC (źródła bugu z uprawnieniami) — jest nieszkodliwy
   przy `AAD_GROUP_RBAC_ENABLED=false`.

## Root cause: cofające się uprawnienia

`backend/app/api/auth_microsoft.py` — blok AAD-group-RBAC w callbacku SSO
(`if settings.AAD_GROUP_RBAC_ENABLED:`) na **każdym** logowaniu przez Microsoft
wyprowadzał `role`/`roles`/`is_active` z grup Azure AD, nadpisując zmiany admina
z panelu (a przy braku pasującej grupy ustawiał `is_active=False` = blokował
konto). Wyzwalany tylko gdy `AAD_GROUP_RBAC_ENABLED=true` (default `false`). Przy
`false` logowanie MS **nie dotyka** roli istniejącego usera. Wyłączenie SSO login
+ trzymanie tego flagu na `false` **całkowicie eliminuje** problem — rolami
zarządza wyłącznie admin w panelu i to jest trwałe.

## Zmiany w kodzie

| Plik | Zmiana |
|---|---|
| `backend/app/core/config.py` | Nowy `MICROSOFT_SSO_LOGIN_ENABLED: bool = False`. |
| `backend/app/main.py` | Komentarz: SSO router montowany obok integracji, ale gated runtime (jak Autenti). Mount nadal pod `M365_INTEGRATION_ENABLED`. |
| `backend/app/api/auth_microsoft.py` | `_require_sso_configured()` (→ `/authorize`), `/callback` i `/exchange` fail-closed 503/redirect gdy `MICROSOFT_SSO_LOGIN_ENABLED=false`. |
| `backend/app/api/auth.py` | `/login` egzekwuje `sso_allowed_domains_list` (helper `_domain_allowed`, fail-open gdy pusta, sprawdzana po haśle). |
| `frontend/src/app/login/page.tsx` | Usunięty przycisk „Zaloguj się przez Microsoft" + divider „lub" + martwy kod (`handleMicrosoftLogin`, `ssoLoading`). Generyczny `?error=` banner zostaje. |
| `backend/tests/test_auth_login_domain.py` | Nowe testy: domain block na `/login` + kill-switch SSO. Dodane do CI. |
| `backend/tests/test_auth_microsoft.py` | Fixture włącza `MICROSOFT_SSO_LOGIN_ENABLED=True` (SSO-flow testy). |
| `.github/workflows/ci.yml` | `test_auth_login_domain.py` w liście pytest. |
| `.env.example` | Nowe flagi + noty. |

**Nie ruszamy:** `M365_INTEGRATION_ENABLED` (musi zostać `true`), blok AAD-RBAC
(martwy = nieszkodliwy), `Microsoft365Card.tsx` (przycisk „Połącz" integracji
uderza w INNY endpoint `/api/microsoft365/authorize`).

## ⚠️ Rollout — kroki operacyjne (Coolify / prod, POZA kodem)

**Ten PR NIE jest mergowany automatycznie.** Merge → deploy dopiero po
wykonaniu poniższych kroków (bo inaczej można chwilowo zablokować userów
logujących się dziś tylko przez Microsoft — oni nie mają hasła).

Kolejność jest istotna:

1. **Odczytaj live env vault** (Coolify API `GET /applications/ocgkwcbovpve9wvf9smxl0kx/envs`):
   `AAD_GROUP_RBAC_ENABLED`, `M365_INTEGRATION_ENABLED`, `SMTP_ENABLED`,
   `PUBLIC_BASE_URL`, `SSO_ALLOWED_DOMAINS`, `SELF_REGISTRATION_ENABLED`.
2. **Wymuś `AAD_GROUP_RBAC_ENABLED=false`** (jeśli gdzieś `true`) — zamyka root
   cause zanim cokolwiek innego.
3. **Skonfiguruj SMTP** (`SMTP_ENABLED=true` + host/user/pass/from) i
   **`PUBLIC_BASE_URL=https://nexus.dynaminds.pl`**. Bez tego self-service reset
   to cichy no-op (user widzi „wysłaliśmy link", mail nie wychodzi).
   **Smoke-test na żywo:** realny `/forgot-password` na prawdziwą skrzynkę →
   potwierdź dostarczenie ORAZ że link wskazuje na prod host i przechodzi
   reset→login. **Nie idź dalej, dopóki mail nie dotrze.**
4. **Ustaw `SELF_REGISTRATION_ENABLED=true`** i `SSO_ALLOWED_DOMAINS=b2bnetwork.pl`
   (decyzja: self-service rejestracja ON, rola wymuszona `user`).
5. **AUDYT domeny (przed twardym blokiem na /login):**
   `SELECT email FROM users WHERE is_active AND password_hash IS NOT NULL AND email NOT LIKE '%@b2bnetwork.pl'`
   → potwierdź, że nie ma legalnych kont admin/serwisowych spoza domeny (albo
   dodaj je do `SSO_ALLOWED_DOMAINS`, albo załóż im konta @b2bnetwork.pl). Kod
   jest fail-open przy pustej whiteliscie, ale z `b2bnetwork.pl` blokada jest
   aktywna od razu po deployu.
6. **Policz konta do bootstrapu:**
   `SELECT count(*) FROM users WHERE password_hash IS NULL AND is_active AND email LIKE '%@b2bnetwork.pl'`
   → skala okna przejściowego.
7. **Ustaw `MICROSOFT_SSO_LOGIN_ENABLED=true`** (okno przejściowe: endpoint SSO
   żywy jako awaryjne wejście, przycisk już ukryty przez FE) i **zmerguj PR**
   → Coolify deploy → smoke-test `/api/health` nowy `GIT_SHA`.
8. **Masowy bootstrap haseł:** dla `(password_hash IS NULL AND is_active AND @b2bnetwork.pl)`
   odpal reset (link mailem — `create_reset_token` + `send_password_reset_email`
   per user, albo admin `send-reset-link` w pętli). Alternatywa pilna: admin
   temp-hasła (`POST /api/admin/users/{id}/reset-password`, `force_password_change=True`,
   działa bez SMTP). Reconciluj z `Activity('password_changed_via_token')`.
9. **Zamknij okno:** po potwierdzeniu, że userzy ustawili hasła →
   **`MICROSOFT_SSO_LOGIN_ENABLED=false`** (restart) → wszystkie `/api/auth/microsoft/*`
   zwracają 503.
10. **Monitoruj:** Sentry `nexus-be` (401/403 na `/login`), skargi o mailach,
    `/api/health`.

## Dlaczego bootstrap jest bezpieczny (mechanika)

- `/forgot-password` gate'uje TYLKO na `is_active` — user SSO-only
  (`password_hash IS NULL`) MOŻE poprosić o reset.
- `/reset-password` ustawia `password_hash`, nie dotyka `email_verified`.
- Wszyscy SSO userzy mają `email_verified=True` (backfill migracji 0139 + ORM
  default), więc pułapka email_verified ich nie dotyka.
- **Jedyna twarda blokada = SMTP.** Dlatego krok 3 jest warunkiem koniecznym.

**Edge case Traffit (~131 kont, migr. 0076):** `password_hash='!imported-from-traffit-no-login!'`
+ `is_active=false`. NIE aktywuj takiego konta bez uprzedniego admin reset-password
(login guard woła `verify_password` przed `is_active` → bcrypt rzuci na
non-bcrypt sentinelu → 500).

## Rollback

- **Przywróć SSO login:** `MICROSOFT_SSO_LOGIN_ENABLED=true` (endpoint żywy) +
  revert commita FE (przycisk wraca). Integracja M365 nietknięta przez cały czas.
- **Jeśli reset maili nie działa:** wróć do okna dual-auth (SSO `true`) + admin
  temp-hasła, aż SMTP naprawiony.
- **Nigdy** nie ruszaj `M365_INTEGRATION_ENABLED` w rollbacku — to nie login,
  a zabiłoby integrację.

## Weryfikacja

- Backend: `curl -X POST https://api.nexus.dynaminds.pl/api/auth/login` z
  @b2bnetwork.pl → 200; z obcej domeny (po haśle) → 403; SSO `/authorize` po
  wyłączeniu → 503.
- Chrome MCP `nexus.dynaminds.pl/login`: formularz email+hasło primary, brak
  przycisku Microsoft, linki „Zapomniałeś hasła?" + „Zarejestruj się" działają.
- Chrome MCP Settings → Microsoft365Card „Połącz" nadal działa (integracja żywa).
- CI: `test_auth_login_domain.py` + `test_auth_microsoft.py` zielone.
