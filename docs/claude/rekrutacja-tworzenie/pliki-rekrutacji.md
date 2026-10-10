# Pliki rekrutacji (0428, 09.10.2026)

Decyzja Artura 09.10.2026: Delivery Lead dodaje pliki przy zakładaniu
rekrutacji (plik requestu z kroku 1 zapisuje się sam), a zespół widzi je potem
w menu „⋯” rekrutacji. Kod: `services/job_files.py`, `api/job_files.py`, trasy
plików formularza w `api/job_intake_forms.py`, front `lib/api/jobFiles.ts`,
`components/v2/jobs/files/JobFilesPanel.tsx` (jeden panel dla obu miejsc).

- **Tabela `job_files` ma DWÓCH możliwych właścicieli:** `job_id` (CASCADE)
  albo `intake_form_id` (SET NULL). Rekrutacji przed „Utwórz i przekaż” nie
  ma, więc plik z `/jobs/new` wisi na niedokończonym formularzu autora;
  `POST /api/jobs` przepina go (`job_files.attach_intake_files`) tuż PRZED
  `delete_intake_form`, w tej samej transakcji — odmowa 422 `job_not_ready`
  zostawia pliki przy formularzu. Ścieżka na dysku nie zależy od właściciela,
  więc przepięcie to sam UPDATE. Kopia rekrutacji (`from_job_id`) plików nie
  przenosi.
- **Pliki leżą na wolumenie uploadów** (`storage_service.save_job_file`, nazwa
  na dysku losowa — nazwa z przeglądarki jest tylko w kolumnie `filename`).
  20 MB na plik (pod limitem ciała 30 MB), 20 plików na właściciela (liczone
  pod blokadą właściciela), lista rozszerzeń w `job_files.CONTENT_TYPES`
  (lustro `JOB_FILE_EXTENSIONS` na froncie). Odczyt uploadu `read(LIMIT + 1)`.
- **Plik znika z dysku PO commicie** (usunięcie pliku, usunięcie rekrutacji —
  ścieżki zbierane przed `db.delete(job)`). Sieroty (formularz usunięty przez
  autora albo po 30 dniach — FK zeruje `intake_form_id`) kasuje
  `queue_retention` (`job_files.sweep_orphans`).
- **Uprawnienia:** pliki formularza — wyłącznie autor (`_own_form`, cudzy =
  404); pliki rekrutacji — odczyt i pobranie każda rola wewnętrzna z dostępem
  do rekrutacji, dodanie i usunięcie `ensure_job_editor` (także na zamkniętej
  rekrutacji), `Activity job_file_added` / `job_file_removed`. `can_edit`
  liczy serwer; front nie zgaduje po roli.
- **Pobranie:** `inline` tylko dla PDF i obrazów
  (`core/http_headers.safe_document_disposition` — wspólne z dokumentami
  kandydata), reszta zawsze jako załącznik. Nazwy plików i ścieżki nie idą do
  logów.
- **DDL ma jedno źródło** (`services/job_file_schema.py`) dla migracji 0428
  i `entrypoint.sh`; pilnuje `test_job_files_migration_mirror.py`. Sonda
  `job_files` w `/api/health/deep`.
- **Front:** `/jobs/new` — karta „Pliki” w lewej kolumnie pod requestem
  (pierwszy plik najpierw zapisuje formularz: `ensureFormId` → `persistForm`);
  po udanym odczycie pliku w kroku 1 ten sam plik idzie jako `source=request`
  (niepowodzenie = toast, odczyt zostaje). Strona rekrutacji — „⋯” → „Pliki
  (N)”, `?win=files`, `JobFilesSlideOver`. Awaria listy = komunikat z „Ponów”,
  nigdy pusta lista. Harnessy: `/preview/job-detail?files=1`,
  `/preview/new-job?state=review|manual`.
