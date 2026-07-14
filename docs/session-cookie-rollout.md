# Browser session rollout (P1, phase 1)

This change moves the NEXUS web application from JavaScript-readable JWTs to
backend-issued browser cookies. It does not change roles or multi-role rules.
Bearer auth remains temporarily available for the Chrome extension, Outlook
add-in and automation clients.

## Required staging configuration

Set these before deploying the branch to staging:

```dotenv
SESSION_COOKIE_PREFIX=nexus_staging
SESSION_COOKIE_DOMAIN=.nexus.dynaminds.pl
SESSION_COOKIE_SECURE=true
JWT_ALLOW_LEGACY_VERSIONLESS=true
JWT_ALLOW_LEGACY_WS_QUERY_TOKEN=true
NEXT_PUBLIC_SESSION_COOKIE_PREFIX=nexus_staging
```

Production uses `nexus` for both prefix variables. The permanent staging
environment must use `nexus_staging`; because both environments share the
parent cookie domain, reusing a name would make staging and production sessions
overwrite each other. Backend and frontend prefixes must match exactly.

Run the Playwright setup contract against staging with
`E2E_SESSION_COOKIE_PREFIX=nexus_staging`; it asserts the cookie flags, absence
of a new localStorage JWT, token-free login response and a 403 logout attempt
without CSRF.

`CORS_ORIGINS` must contain the exact staging web origin. Production and
staging must not use wildcard origins when cookie auth is enabled.

Validate all three `Set-Cookie` headers after password and Microsoft login:

- `<prefix>_access`: `HttpOnly; Secure; SameSite=Lax; Path=/`;
- `<prefix>_refresh`: `HttpOnly; Secure; SameSite=Lax; Path=/api/auth`;
- `<prefix>_csrf`: `Secure; SameSite=Lax; Path=/` and intentionally not HttpOnly.

The access and refresh JWTs must never occur in a browser-session response
body. A cookie-authenticated `POST`, `PUT`, `PATCH` or `DELETE` must fail with
403 when either the exact Origin or `X-CSRF-Token` double-submit value is
missing. Session login and Microsoft exchange have no CSRF cookie yet, so they
require the same exact Origin and are the only Origin-only exceptions. Explicit
Bearer clients keep their non-ambient credential contract.

## Compatibility window and contract

The frontend never writes a new `access_token` to localStorage. It may read an
already-present token until that pre-rollout session ends. The Outlook add-in
migrates its old localStorage JWT once into sessionStorage and deletes the
persistent copy.

Every newly minted access and refresh JWT carries the user's integer
`token_version`. Logout, password reset, role/multi-role changes and account
state changes increment that value. Tokens without `ver` are accepted only
when both conditions hold:

1. `JWT_ALLOW_LEGACY_VERSIONLESS=true`;
2. the user's current `token_version` is still zero.

This means a security event revokes old versionless JWTs immediately even
during the compatibility window.

## Contract phase

After at least 30 days (the maximum legacy refresh-token lifetime), with no
query-token WebSocket clients observed:

1. set `JWT_ALLOW_LEGACY_VERSIONLESS=false`;
2. set `JWT_ALLOW_LEGACY_WS_QUERY_TOKEN=false`;
3. verify password login, Microsoft login, refresh, logout, WebSocket and all
   browser download/export flows on staging;
4. remove the localStorage Bearer read fallbacks in a separate contract PR.

Rollback of this phase must keep migration `0162_user_token_version`; it is an
expand-only column and older application code safely ignores it. Rolling back
to code that writes new browser JWTs to localStorage is not an approved
security rollback.
