# Naprawy jednorazowe w `backend/scripts/repairs/` · nie w `entrypoint.sh`, po 14 dniach od znacznika

Audyt z 07.11.2026 (pozycja D3). Naprawa danych, której znacznik w `app_settings`
ma na produkcji ponad 14 dni, nie jest krokiem startu kontenera.

- `backend/scripts/repairs/run_<krok>.py` to dawny blok z `entrypoint.sh` (z jego
  komentarzem), `<moduł>_repair.py` obok to logika. Uruchomienie ręczne, z backendu:
  `python -m scripts.repairs.run_<krok>`. Znacznik i advisory lock zostały w
  logice, więc drugi przebieg nic nie zmienia.
- Moduły importowane przez migracje zostają w `app/services`
  (`order_separation_repair`, `contract_ended_tab_repair`,
  `pfron_renewal_split_repair`, `candidate_name_marker_repair`). Migracji się
  nie rusza: PR z plikiem w `backend/alembic/versions` trafia na pas migracji
  i jest traktowany jak dokładający nową rewizję.
- **Nowa naprawa** dalej trafia do `entrypoint.sh` przez `run_unless_marked`
  (`test_entrypoint_repair_markers.py`), bo musi wejść razem z wdrożeniem. Po
  14 dniach od znacznika można ją przenieść tutaj.
- Daty sprawdzasz na kopii stagingu, tylko do odczytu:
  `SELECT key, updated_at FROM app_settings WHERE key = '<znacznik>'`.

Co świadomie zostało w `entrypoint.sh` (stan z 08.11.2026):

- `repair-contract-hourly-rates`: działa przy każdym starcie, łapie kontrakty
  zapisane później starą ścieżką.
- `repair-contract-order-sync`: znacznik `0304_contract_order_sync_repair` włącza
  codzienną synchronizację (`contract_order_sync.py`), a na pustej bazie nie
  zapisuje go migracja.
- `competence-categories-four`, `seed-placement-exclusions`: zasiewają dane.
- `repair-contract-duplicate-2026-10`, `repair-stale-termination`,
  `cv-service-title-repair`: znaczniki młodsze niż 14 dni.

Moduły `traffit_*_repair` obsługują endpointy `admin_traffit` i zostają w
`app/services`, dopóki żyje moduł Traffita.
