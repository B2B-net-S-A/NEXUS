# Audyt 22.09.2026 — reguły po naprawie

<!-- indeks: tokeny OAuth per trasa, wysyłka maila M365 jednorazowa, podpis, kanonizacja umiejętności, analityka kontraktów -->

Raport: `docs/audyt-nexus-2026-09-22.md`, naprawa: `docs/audit-2026-09-22-remediation-report.md`.

- **Tokeny klientów OAuth mają zakres per TRASA** (`services/oauth_route_scopes.py`,
  wpięte w `deps._resolve_client_principal`). Szablon trasy jest odbudowywany
  z drzewa aplikacji (FastAPI 0.141 nie dokleja prefiksu `include_router` do
  `scope["route"].path`). Odczyt/zapis wyznacza `is_read_only_http_request`.
  Flaga `OAUTH_ROUTE_SCOPES_ENFORCE` (domyślnie `false`) = tryb cienia: odmowa
  tylko w logu WARNING. Nową trasę dla integracji dopisz do mapy PRZED
  włączeniem flagi. Zakresy z JWT są przecinane z BIEŻĄCYMI `client.scopes`,
  a `require_scope` (ATLAS) czyta klienta z bazy przy każdym żądaniu.
- **Token z `fpc` nie wykonuje operacji biznesowych** (403 `password_change_required`
  w `get_current_user`); `/auth/me` i zmiana hasła idą przez `get_authenticated_user`.
  Konto bez hasła (SSO, zaślepka Traffita) dostaje 400 przy zmianie hasła,
  `/auth/me` niesie `has_password`.
- **Wysyłka maila M365 jest jednorazowa**: wiersz `Email` rezerwowany PRZED
  Graphem (`send_state` pending/sent/uncertain, migracja 0342), klucz =
  użytkownik + `client_request_id` z okna compose/reply. `uncertain` NIE jest
  „do ponowienia" — to „nie wiadomo, czy wyszło". `GraphClient` nie ponawia POST
  po `ReadTimeout`/`ReadError` (tylko `retry_unsafe=True` dla odczytów jak
  `getSchedule`); tworzenie wydarzenia niesie stały `transactionId`.
- **Sync M365 dopasowuje wiadomość także po `(user_id, internetMessageId)`** —
  domyślne ID Graphu zmienia się przy przeniesieniu z Drafts do Sent Items.
  Błąd listowania załączników jest błędem wiadomości (kursor delty stoi);
  nieudane pobranie (`download_failed[n]`) ponawia pętla `m365_cv_parse`.
- **Podpis kończy się tylko jawnie pozytywnym wynikiem KAŻDEGO podpisu**, plik
  podpisany musi zaczynać się bajtami wydanego źródła (odciski w
  `validation_report.source_pdfs`), kandydat musi być wśród podpisujących.
  „Obie strony" = 2 RÓŻNE tożsamości. Moduł jest wyłączony na prodzie
  (`SIGNING_ENABLED=false` od 22.09.2026) — umowy podpisujemy offline.
- **`_canon_skill` zachowuje C/C++/C#/F#/.NET jako różne umiejętności**
  (`cpp`, `csharp`, `fsharp`, `dotnet`). Zmiana kanonizacji skilli albo
  lokalizacji = podbicie znaczników w `scoring_algorithm_version()` i
  `MUST_GATE_POLICY_VERSION`. Połowa „miasto" w `_score_location` liczy się
  tylko przy wspólnym MIEŚCIE (`location_utils.city_tokens`), kraj nie wystarcza.
- **Analityka kontraktów liczy stawki z harmonogramów na dzień** i pomija
  kontrakty, które jeszcze się nie zaczęły (`current_contracts`); prognoza
  bierze stawkę obowiązującą w danym miesiącu. Aneks zmieniający jednostkę lub
  godziny z przyszłą datą = 422.
- **GET brandowanego CV niczego nie zapisuje** — status `none` zwraca podgląd;
  szkic zakłada pierwsza edycja, a `finalize`/`review` przyjmują też `none`.
