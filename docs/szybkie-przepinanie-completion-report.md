# Szybkie przepinanie kandydatów — completion report

**Data:** 2026-06-11
**Problem biznesowy:** wolne „przepinanie" osób — gdy wpada nowy request podobny
do historycznego, te same osoby, które wcześniej poszły do klienta, powinny być
wysłane ponownie w minuty, nie dni.

**Diagnoza:** silnik istniał w ~70% (sekcja „Kandydaci z podobnych projektów",
endpoint `/candidates-from-similar`, bulk-add `/proposals/bulk`), ale był
reaktywny (trzeba wiedzieć, że istnieje), jednoklikowy per kandydat i bez
priorytetu „ten sam klient".

## Faza 1 — proaktywna notyfikacja przy nowym requeście

- **Nowy serwis** [backend/app/services/similar_job_notify.py](../backend/app/services/similar_job_notify.py):
  po `POST /jobs` (background task, po embeddingu) sprawdza podobne historyczne
  requesty; jeśli istnieje Tier A (cosine ≥ 0.70) z kandydatami po etapach
  klienckich (`CLIENT_FACING_STAGES`: cv_sent → hired) — emituje in-app
  notyfikację do `recruiter_id`/`tac_id`/`created_by`.
- Treść: „Request X wygląda jak Y (87%) — N kandydatów poszło już do klienta,
  w tym M u tego klienta; K dostępnych" + deep-link `/jobs/{id}?tab=similar`.
- **Anty-szum:** tylko Tier A, tylko historia kliencka (sam screening nie
  liczy się), odrzuceni u tego klienta nie liczą się do progu, dedup
  per (user, typ, job, dzień) przez `ix_notif_dedup_daily`.
- **Kill-switch:** `SIMILAR_JOB_NOTIFY_ENABLED=false` (Coolify env, bez
  redeploya); próg `SIMILAR_JOB_NOTIFY_MIN_CANDIDATES` (default 1).
- Nowy `NotificationType.similar_job_candidates` + safety-net
  `ALTER TYPE ... ADD VALUE` w `entrypoint.sh` (wzorzec kpi_coach).
- Ikona/kolor w `NotificationsDropdown.tsx` (Sparkles, indigo).

## Faza 2 — hurtowe „przepnij zaznaczonych"

- `HistoricalCandidatesSection.tsx`: checkbox per kandydat, „Zaznacz
  wszystkich", przycisk **„Dodaj zaznaczonych (N) do pipeline"** →
  `POST /api/jobs/{id}/proposals/bulk` z job-scoped notatką „Przepięty hurtowo…".
- Toast zbiorczy „Dodano X, pominięto Y"; wiersze dodane (lub już obecne)
  zielenieją „W pipeline"; kanban invaliduje się natychmiast.
- „Zaznacz wszystkich" pomija osoby już w pipeline i odrzucone przez tego
  klienta (świadoma pojedyncza decyzja zamiast hurtu).
- Deep-link `?tab=similar`: przełącza job page na zakładkę AI Matching,
  scrolluje do sekcji i podświetla ją (ring 3 s).

### Dlaczego BEZ fast-tracku na etap „Zweryfikowany"

Gate z migracji 0056: ruch na `verified` **wymaga** `expected_rate_value`
(stawka per rekrutacja — u każdego klienta inna) i przy stawce > budżetu
tworzy pending-verification do akceptacji DL. Hurtowe lądowanie na `verified`
ominęłoby proces stawek. Przepięci lądują więc na pierwszym etapie szablonu
z notatką-kontekstem; dodatkowo `proposals/bulk` odrzuca teraz override na
etap terminalny lub `verified` (422).

## Faza 3 — priorytet „ten sam klient"

- `similar_job_candidates.py`: źródła niosą `client_id`; kandydat dostaje
  `same_client` i `rejected_by_same_client` (liczone vs `client_id` nowego
  joba, przekazywane z endpointu — zero dodatkowych zapytań).
- UI grupuje: **„Znani temu klientowi (N)"** na górze (badge „znany
  klientowi"), niżej „Z podobnych projektów u innych klientów".
- `rejected_by_same_client` → czerwony badge **„klient odrzucił wcześniej"**
  (mocniejszy niż generyczne „uwaga") + wykluczenie z select-all.

## Pliki zmienione

Backend: `services/similar_job_candidates.py`, `services/similar_job_notify.py`
(nowy), `api/recommendations.py`, `api/jobs.py`, `api/proposals_bulk.py`,
`schemas/similar_job_candidates.py`, `models/notification.py`,
`core/config.py`, `entrypoint.sh`.

Frontend: `components/HistoricalCandidatesSection.tsx`,
`components/NotificationsDropdown.tsx`, `app/jobs/[id]/page.tsx`, `lib/api.ts`.

Testy: `tests/test_similar_job_candidates.py` (3-kolumnowe wiersze + 3 nowe
testy flag), `tests/test_similar_job_notify.py` (nowy — build_alert /
build_message). Lokalnie: 28 passed (unit).

## Znane ograniczenia / TODO

- Notyfikacja odpala się tylko przy **utworzeniu** joba (nie przy update —
  świadomie, marketplace pokrywa significant-update; dedup dzienny i tak by
  ograniczał szum).
- `test_similar_job_notify.py` nie jest w liście pytest w `ci.yml` (lista
  selektywna; ci.yml nietykane przez gotcha workflow-scope). Testy przechodzą
  lokalnie.
- Availability badge bazuje na `availability_status` (ręcznie ustawiane) —
  „dostępny" znaczy „oznaczony jako dostępny", nie zweryfikowany telefonicznie.
- Przyszłość (nice-to-have): przycisk „Wygeneruj CV pod ten request" przy
  przepiętych; potwierdzenie dostępności (CloudTalk/mail) przed wysłaniem.
