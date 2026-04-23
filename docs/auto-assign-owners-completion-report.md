# Auto-assign TAC + Delivery Lead — Completion Report

**Data:** 2026-04-24
**Commits:** c57c944 (backend) · a550194 (frontend+testy) · afbc65f (safety-net) · b860f4d (fix POST 500)
**Branch:** main (Coolify auto-deploy OK)

## Cel

Zautomatyzować przydzielanie TAC (Talent Acquisition Consultant) i Delivery
Lead przy tworzeniu projektu (POST /jobs), na podstawie przypisań klienta.

- `Job.tac_id` ← `client_tac_assignments.is_primary=true` dla `client_id`
- `Job.delivery_lead_id` ← `delivery_lead_client_assignments.is_head=true`
- Override: jawne pola w request wygrywają.
- Fallback: `NULL` + żółty alert "Brak TAC" w UI.

## Zmiany

### Backend

- **Migracje:** `0059_add_job_tac_id`, `0060_client_tac_assignments`
  (partial unique index `uq_client_primary_tac` — max 1 primary per klient).
- **Model `ClientTacAssignment`** (analogicznie do `DeliveryLeadClientAssignment`).
- **Pole `Job.tac_id`** + relationship `Job.tac`.
- **Serwis `app.services.auto_assign_owners.resolve_default_owners`** —
  immutable DTO `ResolvedOwners`, filtruje po `User.is_active=True`.
- **Integracja w `POST /jobs`** + walidacja ról override (400 dla sourcer/recruiter).
- **Router `app.api.clients_team`:**
  - `GET /api/clients/{id}/team` (CurrentUser)
  - `POST /api/clients/{id}/tacs` (HeadOfRecruitmentPlus)
  - `DELETE /api/clients/{id}/tacs/{user_id}`
  - `PUT /api/clients/{id}/tacs/{user_id}/toggle-primary`
- **Script `scripts/backfill_job_owners.py`** — `--dry-run` / `--commit`.
- **Safety-net w `entrypoint.sh`** — ALTER jobs.tac_id + CREATE TABLE
  client_tac_assignments z partial unique index (multi-head alembic
  nie wchodzi na prod, bez tego crash GET /api/jobs).
- **Fix POST /jobs 500** — `await db.refresh(job)` przed return.
  Upstream commity (classify_job_to_cc, auto_cc_collaborators, snapshot)
  expire-owały obiekt → MissingGreenlet w response_model walidacji.

### Frontend

- **AddJobModal / EditJobModal (`AppShell.tsx`):** pola TAC + Delivery Lead
  z auto-fill po wyborze klienta (fetch `/api/clients/{id}/team`), badge
  "Domyślny / Nadpisane", żółty alert gdy klient bez primary TAC.
- **`clients/[id]/OwnersTab.tsx`** — nowa zakładka "Opiekunowie" z CRUD
  TAC (używa `/api/clients/{id}/tacs`) i DL (istniejące
  `/api/team-structure/dl-clients`). Edycja tylko dla admin + head_of_recruitment.
- **`JobsListV2`:** badge "Brak TAC" (variant warning) gdy `job.tac_id IS NULL`.

### Testy

`backend/tests/test_auto_assign_owners.py` — 5/5 passed:
- Primary TAC + head DL dla kompletnego teamu
- `client_id=None` → `(None, None)` bez SQL
- Brak primary TAC → fallback NULL
- Skipped inactive user
- Partial unique index blokuje 2 primary TAC-ów (IntegrityError)

Inne testy bez regresji (test_jobs.py, test_auto_cc_collaborators.py).

## Weryfikacja prod

### API smoke
```
POST /api/clients/1/tacs {user_id: 9, is_primary: true} → 201
POST /api/team-structure/dl-clients {delivery_lead_user_id: 5, client_id: 1, is_head: true} → 201
GET /api/clients/1/team → {tacs: [Claude Admin primary], delivery_leads: [Dominik head]}
POST /api/jobs {title:"SMOKE", client_id:1} → 201 {tac_id:9, delivery_lead_id:5}
POST /api/jobs {title:"OVR", client_id:1, tac_id:11} → 201 {tac_id:11, delivery_lead_id:5}  # override
```

### Backfill
```
python -m scripts.backfill_job_owners --dry-run
→ Summary: candidates=38 updated=5 skipped_no_client=21 skipped_no_assignments=12
python -m scripts.backfill_job_owners --commit
→ Committed 5 job updates
```

Weryfikacja: Job 1 ("Senior Angular Developer", client=1) po backfill:
`tac_id=9, delivery_lead_id=5`.

## Znane ograniczenia / TODO

- Prod ma 0 userów z rolą `tac` — do przypisania TAC-ów klientom można
  używać adminów / delivery_leadów (walidacja to dopuszcza). Real TAC
  accounts do stworzenia przez Artura.
- `DeliveryLeadClientAssignment` nadal nie ma partial unique index
  `WHERE is_head = TRUE` — `ClientTacAssignment` dostał tę poprawkę,
  DL zostaje na aplikacyjnym guardzie. Można ująć w kolejnej iteracji.
- Chrome MCP smoke UI (klikalna ścieżka od Coolify frontend → klient →
  Opiekunowie → utworzenie projektu) nie został wykonany — tylko API
  smoke. UI zweryfikowany przez SSR 200 na `http://localhost:3001/clients/1`.

## Krytyczne pliki

| Plik | Typ |
|---|---|
| `backend/alembic/versions/0059_add_job_tac_id.py` | NEW |
| `backend/alembic/versions/0060_client_tac_assignments.py` | NEW |
| `backend/app/models/team_structure.py` | `+ClientTacAssignment` |
| `backend/app/models/job.py` | `+tac_id` |
| `backend/app/models/client.py` | `+tac_assignments` relationship |
| `backend/app/services/auto_assign_owners.py` | NEW |
| `backend/app/api/clients_team.py` | NEW |
| `backend/app/api/jobs.py` | auto-assign + walidacja + `refresh` przed return |
| `backend/app/schemas/job.py` | `+tac_id/delivery_lead_id` |
| `backend/app/schemas/client_team.py` | NEW |
| `backend/scripts/backfill_job_owners.py` | NEW |
| `backend/entrypoint.sh` | safety-net ALTER + CREATE TABLE |
| `backend/tests/test_auto_assign_owners.py` | NEW (5 testów) |
| `frontend/src/components/AppShell.tsx` | `AddJobModal`/`EditJobModal` TAC+DL |
| `frontend/src/app/clients/[id]/OwnersTab.tsx` | NEW |
| `frontend/src/app/clients/[id]/page.tsx` | zakładka Opiekunowie |
| `frontend/src/components/v2/pages/JobsListV2.tsx` | badge "Brak TAC" |
