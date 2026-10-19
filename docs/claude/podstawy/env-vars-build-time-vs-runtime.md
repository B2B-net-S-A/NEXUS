# Env vars (build-time vs runtime)

**Build args (FE):**
- `NEXT_PUBLIC_API_URL` (default `http://localhost:8000` w `docker-compose.yml`).
- `GIT_SHA`, `BUILT_AT` (po Fazie 1).

**Runtime env (BE — przez `.env` na serwerze, mapowany do compose `env_file:`):**
- `DATABASE_URL` (postgresql+asyncpg://...)
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (na serwerze override DATABASE_URL przez compose service names)
- `SECRET_KEY` (JWT signing, min 48 chars)
- `CANDIDATE_IDENTITY_FINGERPRINT_KEY` (osobny, stabilny klucz HMAC; nie może być równy `SECRET_KEY`)
- `QDRANT_HOST`, `QDRANT_PORT`
- `VOYAGE_API_KEY` (embeddings)
- `SENTRY_DSN` (opcjonalnie)
- inne per feature

**Walka z surprise:** compose `env_file: .env` — wszystkie sekrety w jednym pliku na serwerze (Coolify env vault).

**Wartość zmiennej w jednym wierszu (19.10.2026, #2395):** workflow „Coolify set env”
odrzuca wartość z kilku wierszy (`\n` albo `\r` w środku), z inputu i z
`value_from_secret`, zanim cokolwiek zapisze w Coolify. Końcowe znaki nowej linii
(np. sekret z `gh secret set < plik`) ucina. Bo Coolify wkleja wartość do `.env`
aplikacji compose bez cudzysłowów, a `docker compose` odrzuca wtedy cały plik
i żaden deploy nie przechodzi. 19.10.2026 do sekretu `JJIT_STATIC_ACCESS_TOKEN`
trafił tekst maila zamiast samego klucza; Deploy padł na
`.env: line 179: unexpected character ","`, dopóki zmiennej nie wyczyszczono ręcznie.
Żadna zmienna NEXUSA nie potrzebuje wielu wierszy, więc wyjątku (`allow_multiline`)
nie ma. Gdy kiedyś dojdzie klucz PEM albo podobny, zapisz go w jednym wierszu
(base64 albo `\n` jako dwa znaki) i rozkoduj w `config.py`, zamiast otwierać bramkę.
Test: `test_set_env_refuses_a_multiline_value`.
