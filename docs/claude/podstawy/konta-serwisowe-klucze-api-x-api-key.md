# Konta serwisowe / klucze API (`X-API-Key`)

Druga klasa poświadczeń obok JWT użytkownika — dla automatyzacji (cron, CI, skrypty
operacyjne). Powstało, bo jedyną alternatywą było podszywanie się pod rekrutera tokenem
z przeglądarki albo podniesienie `ACCESS_TOKEN_EXPIRE_MINUTES`, które jest **globalne**
i osłabia sesje wszystkim. Migracja `0220_service_accounts` (+ lustro w `entrypoint.sh`).

- **Nagłówek `X-API-Key`, NIE `Authorization: Bearer`.** Na `Authorization` jadą już trzy
  poświadczenia (access JWT, refresh JWT, token OAuth klienta) rozróżniane claimem `type`
  **po** zdekodowaniu; klucz nie jest JWT, więc czwarty typ zmuszałby parser do zgadywania
  kształtu przed weryfikacją. Do tego front dokleja `Authorization` do KAŻDEGO wywołania
  (interceptor w `lib/api.ts`), więc klucz, który tam wyląduje, byłby wysyłany wszędzie.
  Precedens w repo: `X-Snapshot-Token` w `/api/admin/snapshot` — ten mechanizm jest jego
  uogólnieniem (tamten to jeden globalny sekret z env-a: bez terminu, rotacji, rewokacji
  i bez możliwości ustalenia, kto go użył).
- **Format `nxs_v2_<24 hex>_<sekret>`** — jawne id + sekret. SELECT idzie po jawnym id
  (więc wolno je logować → audyt „którym kluczem" w ogóle istnieje), a skróty porównuje
  `hmac.compare_digest`. Prefiks `nxs_` jest grepowalny — jest reguła w `.gitleaks.toml`.
- **SHA-256, świadomie NIE bcrypt jak `oauth_clients`.** Tam hash liczy się raz na godzinę
  przy wymianie na token, tu przy KAŻDYM requeście: bcrypt (~100 ms) byłby podatkiem na
  każde wywołanie i darmowym DoS-em. Rozciąganie chroni sekrety o niskiej entropii, a tu
  sekret ma 256 bitów.
- **Dwie tabele, bo rotacja.** `service_accounts` (tożsamość + scope'y) osobno od
  `service_account_keys` (N kluczy na konto): wydaj drugi → wdroż → rewokuj pierwszy,
  bez okna bez działającej automatyzacji i bez rozdwojenia tożsamości w audycie.
- **Uprawnienia własne, ZERO dziedziczenia roli właściciela.** Konto serwisowe nie jest
  wierszem w `users` (wyciekłoby do list userów, KPI, powiadomień, eksportów RODO) i nie ma
  `role` — żaden guard rolowy go nie przepuści. Dziedziczenie roli oznaczałoby ciche
  zyskiwanie uprawnień przy awansie właściciela i śmierć klucza przy jego odejściu, a rola
  `admin` = „wszystko", więc wykluczałoby najmniejsze uprawnienia z definicji.
- **Scope'y są własnym, wąskim słownikiem** (`ServiceScope`): `traffit:sync`, `traffit:read`,
  `ops:snapshot`. Świadomie NIE `OAuthScope` — tamten jest kontraktem zgodności dla integracji
  migrujących z Traffita i opisuje dane domenowe (`candidate:read`). **Nie ma scope'u na dane
  kandydatów**, więc klucz do syncu nie ma jak ich dotknąć; powierzchnie domenowe i tak wiszą
  na `get_current_user`, dla którego `X-API-Key` jest nieznanym nagłówkiem (→ 401).
- **Uprawnienia czytane z konta przy każdym requeście**, nie zapiekane w poświadczeniu —
  odebranie scope'u i rewokacja działają NATYCHMIAST. Tym różni się od `oauth_clients`, gdzie
  wystawiony JWT niesie scope'y ze sobą i żyje jeszcze godzinę po odebraniu dostępu.
- **`expires_at` NOT NULL** (domyślnie 90 dni, sufit `SERVICE_ACCOUNT_KEY_MAX_TTL_DAYS`=365;
  żądanie ponad sufit jest przycinane, nie odrzucane) — klucz bez terminu nie jest nigdy
  oglądany ponownie. `last_used_at` stemplowany z **dławieniem** (60 s), bo zapis przy każdym
  requeście robi z odczytu zapis do jednego gorącego wiersza; licznika wywołań świadomie brak
  (zdławiony kłamałby — od liczenia są logi).
- **Konto serwisowe NIE MOŻE impersonować** — `X-API-Key` + `X-Impersonate-User-Id` → 403.
  Połączenie poświadczenia bez wygasania sesji z cudzymi oczami znosiłoby sens scope'ów.
- **Kluczem nie da się zarządzać kontami serwisowymi** (CRUD za `AdminUser`) — inaczej klucz
  o wąskim scope'ie wydałby sobie szerszy.
- **Wpięte:** `POST /api/admin/traffit/sync` (`traffit:sync`), `GET .../sync/status`
  (`traffit:read`) oraz `GET /api/admin/snapshot` (`ops:snapshot`). Admin z JWT nadal działa —
  `require_service_scope(..., allow_admin_jwt=True)`, więc to nie jest zmiana zrywająca.
  W snapshotcie klucz jest sprawdzany **przed** legacy `X-Snapshot-Token` (w trakcie migracji
  lecą oba nagłówki naraz); `auth_mode` w odpowiedzi ma teraz trzecią wartość
  `service_account`. CRUD: `/api/settings/service-accounts` (+ `/scopes`, `/config`,
  `/{id}/keys`, `/{id}/keys/{key_id}/revoke`) — tylko API, bez ekranu w aplikacji
  (klucz wydaje admin żądaniem z tokenem admina).
- **`SNAPSHOT_TOKEN` jest do wycofania**, nie do rozbudowy — jeden globalny sekret bez
  terminu, rotacji, rewokacji i atrybucji. Zostaje, dopóki cron i ops-skille (`.claude/commands/
  ops-snapshot.md`) nie przejdą na klucz ze scope'em `ops:snapshot`.
- **Env:** `SERVICE_ACCOUNTS_ENABLED` (default `true` — przy pustej tabeli powierzchnia
  ataku jest zerowa; flaga to awaryjne odcięcie CAŁEJ klasy poświadczeń),
  `SERVICE_ACCOUNT_KEY_DEFAULT_TTL_DAYS`, `SERVICE_ACCOUNT_KEY_MAX_TTL_DAYS`,
  `SERVICE_ACCOUNT_LAST_USED_THROTTLE_SECONDS`, `SERVICE_ACCOUNT_RATE_LIMIT`.
- **Uwaga przy dokładaniu endpointów:** moduł z `@limiter.limit` **nie może** mieć
  `from __future__ import annotations` (PEP 563 + slowapi #579 → `Annotated` guardy lądują
  jako wymagane parametry QUERY, 422 na poprawnym body). Ten sam trap co
  w `candidate_activity_summary.py`.
