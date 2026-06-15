# Raport ukończenia — Admin „Podgląd jako użytkownik" (view-as / impersonacja)

**Data:** 2026-06-15
**Zakres:** Admin może oglądać aplikację oczami dowolnego użytkownika (rekruter,
delivery lead, TAC, …) — widzi jego sidebar, „moje rekrutacje", KPI i dashboardy.
Tryb **wyłącznie do odczytu**, **admin only**, **audytowany**.

## Jak to działa

1. **Start:** Ustawienia → Administracja → Użytkownicy → ikona oka („Podgląd jako")
   przy aktywnym użytkowniku. Frontend woła `POST /api/admin/impersonate/{id}`
   (zapis audytu + autorytatywny profil), wchodzi w tryb podglądu i przeładowuje
   stronę główną już jako podglądany user.
2. **W trakcie:** każdy request niesie nagłówek `X-Impersonate-User-Id`. Backend
   (`get_current_user`) po normalnej autoryzacji tokenu admina podmienia efektywny
   `current_user` na podglądanego usera — więc wszystkie filtry `current_user.id`
   i `has_role()` widzą jego dane i uprawnienia. Token przez cały czas należy do
   admina (podmiana żyje tylko w obrębie requestu).
3. **Baner:** żółty pasek u góry („Podgląd jako … — tylko do odczytu") + przycisk
   „Wróć do swojego konta".
4. **Wyjście:** przycisk w banerze → czyści stan + przeładowuje jako admin.

## Bezpieczeństwo

- **Admin only** — nagłówek od nie-admina = 403 (anomalia, audytowalna).
- **Tylko odczyt** — dozwolone `GET/HEAD/OPTIONS` + read-only `POST /api/search/*`
  (wyszukiwarki). Każda inna mutacja w trybie podglądu → 403, żeby admin nie
  stworzył/nie zmienił danych „jako ktoś inny".
- **Audyt** — `Activity(action="impersonation_started", user_id=<admin>,
  entity_id=<target>, details={admin_email, target_email, target_role})`.
- **Heurystyka wygaśnięcia sesji** (≥3×403/5s → logout) jest **wyłączona** w trybie
  podglądu — admin celowo dostaje 403 na endpointach niedostępnych dla podglądanej
  roli i nie wolno go z tego powodu wylogować.

## Zmienione pliki

| Plik | Zmiana |
|---|---|
| `backend/app/api/deps.py` | `get_current_user` honoruje `X-Impersonate-User-Id` (admin-only, read-only) |
| `backend/app/api/admin.py` | `POST /api/admin/impersonate/{user_id}` — start + audyt, zwraca `UserResponse` |
| `backend/app/main.py` | CORS `allow_headers` += `X-Impersonate-User-Id` |
| `frontend/src/store/auth.ts` | stan `realUser` + akcje `impersonate` / `stopImpersonating` + persystencja |
| `frontend/src/lib/api.ts` | interceptor dokleja nagłówek; guard 403 w trybie podglądu; `adminApi.startImpersonation` |
| `frontend/src/components/v2/shell/ImpersonationBanner.tsx` | nowy baner podglądu |
| `frontend/src/components/v2/shell/AppShellV2.tsx` | baner nad Topbarem |
| `frontend/src/components/settings/admin/AdminUsersTab.tsx` | przycisk „Podgląd jako" per user |

## Znane ograniczenia / możliwe rozszerzenia

- **Read-only POST allowlist** = `/api/search/*`. Jeśli jakiś widok ładuje się przez
  inny POST i „nie działa" w trybie podglądu — rozszerzyć
  `_IMPERSONATION_POST_ALLOW_PREFIXES` w `deps.py`.
- **`allowed_sections` (DynaReporter)** nie jest w `UserResponse`, więc w trybie
  podglądu sekcje raportów per-user są puste (gating jak dla usera bez nadań).
- **Middleware FE** używa tokenu admina (rola admin), więc admin może wpisać URL
  dowolnej strony — ale API zwraca dane podglądanego usera, a panele admina pokazują
  „brak dostępu". Wyjście zawsze przez baner.
- Tryb pełnego „działaj jako" (mutacje) świadomie poza zakresem — do dodania na
  życzenie.
