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

**Wartość zmiennej w jednej linii (19.10.2026):** workflow „Coolify set env” odrzuca
wartość ze znakiem nowej linii (`\n` albo `\r`, także sam enter na końcu), z inputu
i z `value_from_secret`, zanim cokolwiek zapisze w Coolify. Bo Coolify wkleja wartość
do `.env` aplikacji compose bez cudzysłowów, a `docker compose` odrzuca wtedy cały
plik i żaden deploy nie przechodzi. 19.10.2026 do sekretu `JJIT_STATIC_ACCESS_TOKEN`
trafił tekst maila zamiast samego klucza; Deploy padł na
`.env: line 179: unexpected character ","`, dopóki zmiennej nie wyczyszczono ręcznie.
Żadna zmienna NEXUSA nie potrzebuje wielu linii, więc wyjątku (`allow_multiline`) nie ma.
Gdy kiedyś dojdzie klucz PEM albo podobny, zapisz go w jednej linii (base64 albo `\n`
jako dwa znaki) i rozkoduj w `config.py`, zamiast otwierać bramkę. Test:
`test_set_env_refuses_a_multiline_value_without_printing_it`.
