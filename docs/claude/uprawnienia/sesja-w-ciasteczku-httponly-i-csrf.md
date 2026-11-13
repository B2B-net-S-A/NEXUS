# Sesja przeglądarki w ciasteczku HttpOnly, CSRF i CSP z nonce
<!-- indeks: nexus_access HttpOnly, X-Nexus-CSRF, POST /api/auth/session (adopcja), /api/auth/logout, WebSocket z Origin, bezpiecznik starej ścieżki, CSP Report-Only z nonce w middleware -->

Decyzja Artura z 13.11.2026: token dostępu nie może być czytelny z JS, bo
każda luka XSS kończyła się wyniesieniem JWT (do 11.2026 leżał w
`localStorage.access_token` i w ciasteczku `nexus_access` pisanym przez
`document.cookie`). Jeden PR zgodny wstecz, CSP z nonce na razie w Report-Only.

- **Ciasteczko ustawia backend** (`app/core/session_cookie.py`):
  `nexus_access; HttpOnly; Secure; SameSite=Lax; Path=/`, 8 h, przy
  `/api/auth/login`, `/api/auth/microsoft/exchange`, `/api/auth/change-password`.
  `Domain` = host frontu z `Origin`, gdy API jest jego poddomeną
  (produkcja: `nexus.b2bnetwork.pl`, bo bramka routingu `src/middleware.ts`
  czyta to samo ciasteczko na hoście frontu); staging/testy — tylko host.
  Bez nowej zmiennej środowiskowej.
- **Bearer ma pierwszeństwo i zostaje** (dodatek Outlooka, e2e, skrypty,
  Jarvis woła API tokenem pytającego). Odpowiedzi logowania dalej niosą
  `access_token` w ciele — front go nie zapisuje.
- **CSRF tylko przy ciasteczku:** POST/PUT/PATCH/DELETE uwierzytelnione
  ciasteczkiem wymagają nagłówka `X-Nexus-CSRF` i `Origin` z `CORS_ORIGINS`,
  inaczej 403 (`get_authenticated_user` w `api/deps.py`, przed dekodowaniem
  tokenu). Nowa trasa niczego nie dopisuje — wystarczy zwykła zależność
  `CurrentUser`. Trasa z własnym czytaniem `Authorization` musi użyć
  `request_bearer_token` (jak `core/rate_limit.py`, `api/jarvis.py`).
- **WebSocket** (`/ws/notifications`) przyjmuje ciasteczko tylko z `Origin`
  z listy CORS — handshake nie zna CORS-u (CSWSH).
- **Front:** axios ma `withCredentials`, a nagłówek CSRF dokleja przy zapisie;
  natywny `fetch` do API = `credentials: "include"` +
  `getAuthenticatedRequestHeaders()` (`lib/session.ts`). Nowy `fetch` bez
  `credentials` = 401 = wylogowanie w środku pracy. W store'ze auth
  `token === COOKIE_SESSION` oznacza „sesja w ciasteczku”.
- **Przejście bez wylogowania:** token starej ścieżki z localStorage front
  przenosi `POST /api/auth/session` (Bearer → ciasteczko) na `/login`.
  `POST /api/auth/logout` usuwa ciasteczko (JS go nie skasuje).
- **Bezpiecznik do usunięcia w następnym PR-ze:** gdy `/me` z samym
  ciasteczkiem da 401 (API sprzed zmiany), front wraca do starej ścieżki
  (`lib/session-establish.ts`). Wtedy nie wysyła `X-Nexus-CSRF`, bo stare API
  odrzuciłoby preflight z nieznanym nagłówkiem.
- **CSP:** `script-src 'self' 'nonce-…' 'strict-dynamic'` bez `'unsafe-inline'`
  w `Content-Security-Policy-Report-Only` z middleware (`src/lib/csp.ts`);
  egzekwowane minimum zostaje w `next.config.ts`. Layout czyta nonce
  z `x-nonce` (`headers()`), więc strony renderują się per żądanie.
  Przeniesienie `script-src` do egzekwowanej polityki dopiero po przejrzeniu
  raportów w Sentry; beacon Cloudflare Insights (wstrzykuje proxy bez nonce)
  będzie raportowany — decyzja o nim przed egzekwowaniem.
