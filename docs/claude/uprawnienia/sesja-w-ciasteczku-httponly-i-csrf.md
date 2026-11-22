# Sesja przeglądarki w ciasteczku HttpOnly, CSRF i CSP z nonce
<!-- indeks: nexus_access HttpOnly, X-Nexus-CSRF, POST /api/auth/session (Bearer → ciasteczko dla harnessu), /api/auth/logout, WebSocket z Origin, stara ścieżka tokenu w JS usunięta 22.11.2026, egzekwowana CSP z nonce w middleware -->

Decyzja Artura z 13.11.2026: token dostępu nie może być czytelny z JS, bo
każda luka XSS kończyła się wyniesieniem JWT (do 11.2026 leżał w
`localStorage.access_token` i w ciasteczku `nexus_access` pisanym przez
`document.cookie`). PR #3407 (14.11) zgodny wstecz, CSP z nonce w Report-Only;
po tygodniu (22.11.2026) stara ścieżka usunięta i CSP egzekwowana.

- **Ciasteczko ustawia backend** (`app/core/session_cookie.py`):
  `nexus_access; HttpOnly; Secure; SameSite=Lax; Path=/`, 8 h, przy
  `/api/auth/login`, `/api/auth/microsoft/exchange`, `/api/auth/change-password`.
  `Domain` = host frontu z `Origin`, gdy API jest jego poddomeną
  (produkcja: `nexus.b2bnetwork.pl`, bo bramka routingu `src/middleware.ts`
  czyta to samo ciasteczko na hoście frontu); staging/testy — tylko host.
  Bez nowej zmiennej środowiskowej.
- **Bearer ma pierwszeństwo i zostaje** po stronie API (dodatek Outlooka,
  wtyczka Chrome, e2e, skrypty, klucze kont serwisowych, Jarvis woła API
  tokenem pytającego). Odpowiedzi logowania dalej niosą `access_token`
  w ciele — front go nie zapisuje ani nie wysyła; callback SSO oddaje go
  wyłącznie wtyczce Chrome (`postMessage`, gdy to ona zaczęła logowanie).
- **CSRF tylko przy ciasteczku:** POST/PUT/PATCH/DELETE uwierzytelnione
  ciasteczkiem wymagają nagłówka `X-Nexus-CSRF` i `Origin` z `CORS_ORIGINS`,
  inaczej 403 (`get_authenticated_user` w `api/deps.py`, przed dekodowaniem
  tokenu). Nowa trasa niczego nie dopisuje — wystarczy zwykła zależność
  `CurrentUser`. Trasa z własnym czytaniem `Authorization` musi użyć
  `request_bearer_token` (jak `core/rate_limit.py`, `api/jarvis.py`).
- **WebSocket** (`/ws/notifications`) przyjmuje ciasteczko tylko z `Origin`
  z listy CORS — handshake nie zna CORS-u (CSWSH). Klient spoza przeglądarki
  podaje token w podprotokole `["access_token", <jwt>]`; `?token=` w URL-u
  jest ignorowany (usunięty 22.11.2026 — JWT w URL-u ląduje w logach).
- **Front:** axios ma `withCredentials`, a nagłówek CSRF dokleja przy zapisie;
  natywny `fetch` do API = `credentials: "include"` +
  `getAuthenticatedRequestHeaders()` (`lib/session.ts`). Nowy `fetch` bez
  `credentials` = 401 = wylogowanie w środku pracy. W store'ze auth
  `token` to `COOKIE_SESSION` albo `null`, nigdy JWT; `setAuth(user)` nie
  przyjmuje tokenu.
- **Stara ścieżka zamknięta (22.11.2026).** Front nie czyta, nie pisze i nie
  wysyła tokenu: bez `localStorage.access_token`, bez ciasteczka z
  `document.cookie`, bez Bearera z interceptora, bez adopcji na `/login`.
  Resztkę z localStorage `/login` tylko sprząta. Testy pilnujące tego:
  `lib/__tests__/session.test.ts` („stara ścieżka … zamknięta”),
  `api-auth-header.test.ts`, `app/login/__tests__/session-cookie.test.tsx`,
  `backend/tests/test_ws_token_subprotocol.py`. Dowód przed usunięciem: JWT
  żyje 8 h, a `#3407` jest na produkcji od 15.11; w logach `http_outcome`
  21–22.11 zero wywołań `POST /api/auth/session`.
- **Harness i staging** (E2E, „Zaloguj jako”) wymieniają Bearer na ciasteczko
  `POST /api/auth/session` z karty frontu i otwierają `/login`
  (`frontend/e2e/helpers/session.ts::adoptBrowserSession`,
  `podstawy/test-calej-sciezki-na-stagingu.md`). Endpoint zostaje — kto ma
  Bearer, i tak ma dostęp. `POST /api/auth/logout` usuwa ciasteczko (JS go
  nie skasuje).
- **CSP egzekwowana od 22.11.2026:** `script-src 'self' 'nonce-…'
  'strict-dynamic'` bez `'unsafe-inline'` w `Content-Security-Policy`
  z middleware (`src/lib/csp.ts`), z `report-uri` do Sentry — każde
  zablokowanie widać tam jako zdarzenie `csp`. Next czyta nonce z nagłówka
  żądania `content-security-policy`; layout bierze go z `x-nonce`, więc strony
  renderują się per żądanie. `next.config.ts` dalej dokłada minimum dla
  każdej odpowiedzi (także `_next/static`, którego middleware nie widzi —
  dlatego worker pdf.js z WebAssembly nie potrzebuje `'wasm-unsafe-eval'`).
  Nowy zewnętrzny skrypt, ramka, font albo `fetch` do obcego hosta wymaga
  dopisania źródła w `csp.ts` — bez tego przeglądarka go zablokuje, a nie
  tylko zaraportuje. Beacon Cloudflare Web Analytics Artur wyłączył (14.11).
- **Element JSX z `nonce={…}` dostaje `suppressHydrationWarning`.** Przeglądarka
  zeruje atrybut `nonce` w DOM-ie, więc React w `next dev` widzi `nonce=""`
  i zgłasza niezgodność („1 Issue” na każdej stronie, 14.11.2026). Prop wycisza
  tylko to porównanie na elemencie; nonce zostaje w HTML-u, CSP bez zmian.
  Dziś jedyny taki element to bootstrap motywu w `app/layout.tsx`
  (test: `lib/__tests__/csp-nonce-hydration.test.tsx`).
