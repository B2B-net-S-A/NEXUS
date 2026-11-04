# Po Fazie 1

Update tej sekcji:
- `/health` zachować, `/api/health` standard shape.
- Update `uptime-probe.yml` na `/api/health` + nowy jq query.
- Dodać `pytest tests/test_health_v2.py` do `backend-lint-test` job.
