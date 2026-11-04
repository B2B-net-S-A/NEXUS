# Hiring manager rekrutacji: lista albo nowa osoba (25.09.2026)

Do 25.09 HM wybierało się tylko z kontaktów klienta, a kontakt zakładał
wyłącznie admin/DL — produkcja miała HM na 0 z 4349 rekrutacji. Decyzja
Artura: osobę wpisuje każdy, kto redaguje rekrutację (także rekruter).

- **Zapis tylko `PUT /api/jobs/{id}/hiring-manager`** (`contact_id` |
  `new_person` | `clear`, dokładnie jedno). Nowa osoba idzie przez
  `services/job_hiring_manager.find_or_create_contact`: najpierw dopasowanie
  do kontaktów klienta (imię i nazwisko w dowolnej kolejności, bez wielkości
  liter i polskich znaków; e-mail wyłącznie bez pełnego imienia i nazwiska —
  wspólna skrzynka klienta nie może podpiąć innej osoby; kilka trafień →
  najniższe id),
  trafienie uzupełnia tylko puste stanowisko/e-mail. Weto HM działa po id
  kontaktu — duplikat osoby rozbiłby je na dwie. Bramka = `ensure_job_editor`,
  bez `can_edit_contacts`; audyt `contact_created` z `source=job_hiring_manager`.
- **HM musi być kontaktem klienta rekrutacji** — POST/PATCH `/api/jobs` z
  cudzym kontaktem = 422, zmiana klienta w PATCH zeruje HM.
- **Lista wyboru = `GET /api/jobs/hiring-manager-options?client_id=`** (id, imię
  i nazwisko, stanowisko — bez e-maila i telefonu, alfabetycznie, żeby kolejność
  nie zdradzała kluczowych relacji), bo rekruter nie dostaje
  `GET /api/clients/{id}/contacts`.
- **Front: jeden `components/jobs/HiringManagerCombobox`** (dok gotowości i okno
  Zlecenie przez `HiringManagerPicker`, `EditJobModal`, `/jobs/new`). Popover
  jest portalem, więc mini-formularz nowej osoby to `div`, nie `<form>`
  (`submit` wysłałby formularz edycji rekrutacji).
- **Odczyt maila (`JOB_REQUEST_INTAKE` v4)** podaje `hiring_manager_*` wyłącznie
  jako dosłowny cytat (zwykle podpis) i dopasowuje go KODEM do kontaktów
  klienta (`hiring_manager_contact_id`); nazwy kontaktów nie idą do promptu.
  `/jobs/new` zapisuje HM zaraz po `POST /api/jobs` — awaria = toast, rekrutacja
  zostaje.
- **Duplikaty kontaktów z Traffita scala się ALIASEM, nie samym usunięciem**
  (`services/contact_duplicate_merge.py`): faza `contacts` nocnego syncu
  przegląda wszystkie `/crm_persons/` i robi upsert po `external_id`, więc
  usunięty duplikat wróciłby następnej nocy. Scalenie przepina rekrutacje
  i kontrakty na kontakt o niższym id, uzupełnia jego puste pola i zapisuje
  `app_settings['traffit_contact_aliases']` (id rekordu Traffita → kontakt),
  a import pomija rekordy z aliasem (`skipped`). Pierwsze 3 pary: blok
  `repair-contact-duplicates` w entrypoincie (25.09.2026).
