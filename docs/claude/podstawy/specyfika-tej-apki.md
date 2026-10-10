# Specyfika tej apki

- **Vector search (Qdrant):** używamy do matching kandydat ↔ stanowisko. Score harness: `scripts/eval_matching.py` lokalnie (waliduj precision/recall przed/po zmianach scoringu).
- **Migracje (Alembic):** `alembic upgrade head` na startup (Coolify entrypoint). Migracje testowane w CI (`alembic upgrade head` na test DB w `backend-lint-test` job).
- **Backup drill:** `.github/workflows/backup-drill.yml` — periodic test pg_dump → pg_restore. Działa, nie ruszamy w fazach 0-4.
- **E2E:** Playwright — stack w CI (`docker-compose.e2e.yml`, scenariusze `@stack`) + nocny `prod-smoke`; szczegóły w „CI gotchas”.
- **40+ feature branches:** historyczne, niektóre stale. Przed merge nowej feature branchy — sprawdź czy nie ma duplikatów.
