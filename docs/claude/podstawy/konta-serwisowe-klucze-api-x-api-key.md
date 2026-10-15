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
  `/{id}/keys`, `/{id}/keys/{key_id}/revoke`, `/{id}/writes`) — od 14.10.2026 także
  ekran „Ustawienia → Klucze API” (`/settings/api-keys`, tylko admin).
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

## API integracyjne v1 (`/api/integrations/v1`, 0443, 14.10.2026)

Decyzja Artura 14.10.2026: procesy firmy (na start rozliczanie klientów) podpina
się pod NEXUSA przez osobne, stabilne API na kluczach `X-API-Key`. Dokumentacja dla
integratora: `docs/api/integracje-v1.md` (bez nazwisk — repo jest publiczne).

- **Pakiet `app/api/integrations_v1/`**, każdy moduł z własnym `router`
  (`route_class=IntegrationRoute` — koperta błędu `{"error": {code, message, details}}`),
  montowany w pętli `integrations_v1.ROUTERS` w `main.py` (NIE `app.mount` — testy
  kontraktowe przestałyby widzieć trasy). Trasy ekranów dla klucza nadal 401.
- **Scope'y v1** w `ServiceScope`: `clients:read`, `contracts:read|write`,
  `orders:read|write`, `md:read|write`, `finance:read|write`,
  `invoices:read|write`, `sales_amounts:read`, `amounts:read|write`.
  `X:write` obejmuje `X:read`, a `amounts:read` obejmuje `sales_amounts:read`
  (`implied_scopes`, liczone przy budowie `ServicePrincipal`, nie w `granted_scopes()`).
- **Kwoty w dwóch poziomach (decyzja Artura 14.10.2026):** `sales_amounts:read` =
  to, co płaci klient (stawka do klienta, wartość i budżet zamówienia, przychód,
  faktury do klientów); stawka konsultanta, koszt i marża **wyłącznie z `amounts:read`**,
  bo automatyzacja rozliczająca faktury klientów nie ma widzieć kosztów. Każde pole
  z kwotą w v1 idzie przez `common.amount_level` (`AmountLevel.none|sales|all`),
  nie przez sprawdzenie scope'u w trasie. Ukryte pole = `null`; `amounts_redacted`
  (żadnych kwot) i `costs_redacted` (bez kosztów i marży). Finanse i faktury
  pokazują sprzedaż z samego `finance:read`/`invoices:read`, koszty dopiero
  z `amounts:read` — także w napisach: klucz pozycji szkicu w Zmianach (skrót HMAC)
  i opisy historii (`finance._summary_without_costs`, test buduje opisy prawdziwymi
  funkcjami ekranu). Klasyfikacja pól: tabela „Kwoty” w `docs/api/integracje-v1.md`.
- **Nowa trasa v1 = scope (zależność `require_service_scope(..., allow_admin_jwt=False)`
  albo `require_service_scope_any` dla meta) + `@limiter.limit(read_rate_limit|write_rate_limit,
  key_func=principal_rate_key)` + test klasy scope'u w `tests/test_integrations_v1_api.py`
  + odświeżony snapshot (`INTEGRATIONS_V1_SNAPSHOT_WRITE=1`,
  `tests/data/integrations_v1_openapi.json`).** Handler v1 nie bierze `CurrentUser`.
  Moduły v1 są w `_RATE_LIMITED_MODULES` i `_DOCSTRING_MODULES` — docstring trasy
  trafia do publikowanej specyfikacji.
- **Zgodność:** dodanie pola/trasy = v1; usunięcie albo zmiana znaczenia pola = v2.
  Projekcje v1 są własne i wąskie (np. `order_facts` dla zamówień), nie kopie DTO ekranów.
- **Zapis = `idempotent_write`** (`Idempotency-Key`, `services/integration_receipts.py`,
  tabela `integration_write_receipts`): paragon `pending` w tej samej transakcji co zmiana,
  4xx nie jest zapamiętywane, `dry_run` nie zostawia paragonu (`dry_run_response` = 200
  i `rollback`). `dry_run` tylko tam, gdzie skutki są wyłącznie w bazie (import MD po
  wyjęciu commita do `run_md_import`, faktury); import arkusza wyników zapisuje plik
  PRZED wierszem, więc jego `dry_run` to tylko odczyt arkusza i konflikt okresu.
- **Autor zapisu = konto serwisowe.** `_authenticate_service_key` stempluje sesję
  (`integration_actor.stamp_integration`): `order_change_events.source='integration'`
  + `created_by_service_account_id` (ekran Finanse → Zmiany pokazuje „Integracja: <nazwa>”),
  `Activity.details.via = "integration:<slug>"`, `request.state.service_principal`
  (log `http_outcome` → `actor`, tag Sentry `integration`). Tam, gdzie kod oczekuje osoby
  (`critical_events.record_executed`, `order_change_checks.set_check`, handlery ekranu
  czytające wyłącznie `user.id`), idzie `IntegrationActor` — bez ról, więc każda bramka
  uprawnień na nim pada, zamiast przepuścić. **Nigdy syntetyczny `User`.**
- **Czego v1 świadomie nie robi:** twarde usuwanie
  (faktura → `cancel`), zatwierdzanie przekroczeń salda MD i wspólnych pul
  (`409 requires_screen_approval`), status „Pobrane” PDF-ów ludzi, historia grupy zamówień.
- **Zapis zamówień i kontraktów (PR 2B, 14.10.2026) = jedno ciało, dwie polityki.**
  Ciała tras ekranu są wydzielone obok tras jako `apply_*`
  (`client_order_groups.apply_group_close|cancel|extend`,
  `client_orders.apply_order_close|update|file`,
  `contracts.apply_contract_update|status`) i biorą `policy: WritePolicy`
  (`app/api/write_policy.py`) zamiast `User`. Trasa ekranu jest cienką otoczką:
  `UserWritePolicy(user, db)` woła DOKŁADNIE te same bramki co przedtem (te same
  argumenty, przez atrybut modułu trasy), a redakcję odpowiedzi robi otoczka.
  Trasy v1 (`integrations_v1/order_writes.py`, `contract_writes.py`) biorą
  `IntegrationWritePolicy` (`common.write_policy`): decyzje ze scope'ów, cała
  firma (bez portfela DL), kwoty tylko z `amounts:write`, status kontraktu
  i data końca, która kończy albo przywraca współpracę, tylko z `contracts:status`
  (lustro uprawnienia „Status kontraktu”, wspólna reguła
  `contracts.contract_update_changes_status`), odmowa `insufficient_scope` z `fields`. Nowa bramka w ciele `apply_*` = metoda polityki
  w OBU klasach; trasa ekranu nie woła `IntegrationWritePolicy`, v1 nie woła
  `UserWritePolicy` (`tests/test_write_policy.py`). Testy źródłowe blokad
  i `for_write` patrzą na ciała `apply_*`, nie na otoczki.
- **v1 węziej niż ekran:** bez zakładania i usuwania; przedłużenie tylko z osobami
  z kontraktem (`contract_id`, bez szkiców kontraktów z `candidate_id`);
  `PATCH /orders/{id}` = `end_date`, `notes` + stawki/waluty z `amounts:write`,
  inne pole 422 (`extra="forbid"`), linia grupy 409; `PATCH /contracts/{id}` =
  tylko `end_date` (stawki kontraktu zostają na ekranie — zapis harmonogramu
  zastępuje cały harmonogram). Bez `dry_run`: zamówienia commitują
  w `commit_order_write`, PDF ląduje na dysku przed commitem. Encji nie ładuj
  przed ciałem (`db.get`) — `SELECT … FOR UPDATE` ciała zwróciłby obiekt z mapy
  tożsamości z wartościami sprzed blokady; odczytuj same kolumny.
- **Rekrutacja i kandydaci w v1 (15.10.2026):** scope'y `recruitments:read|write`,
  `candidates:read|contact|cv|write`, `notes:read|write` — jedyne scope'y danych
  osobowych (`test_no_candidate_data_scope_exists`). Kontakt to POLA profilu
  (`sees_candidate_contact`), nie osobne trasy; koszt (oczekiwania kandydata,
  budżet rekrutacji, stawka Championa) przez `amount_level`. Klucz to integracja
  (`candidate_claim.is_integration_request` zna `service_principal`): osoba, która
  się nie zgłosiła, idzie do propozycji, notatka jest systemowa (`source_ref =
  integration:<slug>`), bez 12 h blokady i bez `UserActivity`. Ruch karty:
  `pipeline.apply_move` z polityką (`services/recruitment_move_policy.py`) —
  `UserMovePolicy` = stare bramki ekranu, `IntegrationMovePolicy` odmawia
  zatrudnienia, wysyłki do klienta, Cpro, stawek i decyzji DL (403
  `requires_screen_decision`); `IntegrationActor` nigdy nie trafia do bramek ról
  (`NO_RIGHTS_VIEWER`). Nowy kandydat z klucza: duplikat e-mail 409
  `duplicate_candidate`, nagrobek RODO 409 `candidate_erased`. Opis dla
  integratora: `docs/api/integracje-v1.md`.
- **Reszta procesów w v1 (15.10.2026, „rób wszystko”):** zakładanie rekrutacji
  (`recruitments:create`, `job_lifecycle.apply_job_create` wspólne z `POST /api/jobs`;
  konto serwisowe omija w rdzeniach tylko zakres DL i redaktora Championa przez
  `is_service_account`, budżet wymaga `amounts:write`), CV dla klienta (`cv:generate`,
  plik także z `candidates:cv`), rozmowy u klienta (`calendar:read`), zgłoszenia
  z linku (`applications:read|write`, `resolve_application_submission` bez commita),
  Insights (`insights:read` — tylko to, co ekran pokazuje wszystkim), Akademia
  (`academy:read`), zdarzenia i webhooki (`events:read`, `webhooks:manage`, 0448).
- **Zdarzenia v1 powstają same:** listener `after_flush` w
  `services/integration_events.py` dopisuje do poczekalni (SAVEPOINT — błąd nie psuje
  zapisu biznesowego), pętla `integration_webhooks` publikuje do kanału w kolejności
  commitów i wysyła webhooki. Nowy rodzaj zmiany, który automatyzacje mają widzieć =
  wpis w `EVENT_TYPES` (typ → scope) i budowa `refs` z SAMYCH identyfikatorów. Zmiany
  hurtowe przez Core `UPDATE` zdarzeń nie dają.
- **Nazwa modelu v1 musi być unikalna w całej aplikacji** — kolizja klas Pydantic
  zmienia nazwę istniejącego schematu w specyfikacji
  (`test_no_new_module_prefixed_schema_names`).
