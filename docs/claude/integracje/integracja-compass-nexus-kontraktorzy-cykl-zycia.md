# Integracja COMPASS ↔ NEXUS (kontraktorzy + cykl życia)

**Wygaszona 22.11.2026.** Compass nie jest używany (potwierdzenie Artura
22.11.2026), serwer Compassa usunięto po snapshocie, a `compass.dynaminds.pl`
nie ma rekordu DNS. HR działa w „Ludziach w NEXUSIE” od przełączenia
(`ludzie/runbook-przelaczenia-z-compassa.md`). Nie proponuj prac w Compassie
ani przywracania tej integracji.

Co zniknęło z NEXUSA 22.11.2026:

- trasy `GET /api/integrations/compass/contractors` i `/roster` (moduł
  `api/integrations_compass.py`, `services/hr/roster_export.py`) — stare adresy
  odpowiadają 410 z komunikatem (`api/retired_modules.py`);
- zakładanie klucza konta serwisowego przy starcie
  (`COMPASS_INTEGRATION_BOOTSTRAP_KEY`, `compass_service_account_bootstrap.py`)
  razem z nagrobkiem `app_settings['service_account_retired_key_ids']`;
- pętle `compass_lifecycle_sync` i `compass_workdays_sync`, serwis
  `compass_lifecycle.py`, pobieranie dni roboczych z Compassa
  w `insights_workdays.py`, sondy `checks.compass_lifecycle`
  i `checks.compass_workdays`;
- źródło dostępności z Compassa (`COMPASS_AVAILABILITY_*`, workflow
  „Compass availability setup” i `scripts/configure-compass-availability.py`);
- wszystkie ustawienia `COMPASS_*` z `core/config.py`, rejestru flag,
  `.env.example` i plików compose;
- tabela `compass_workdays_sync_state` (model, lustro w `entrypoint.sh`, sonda
  schematu w `/api/health/deep`) i klucze `app_settings`
  `compass_lifecycle_state`, `service_account_retired_key_ids` — migracja
  0752 z `DROP TABLE` i `DELETE`, lustro DROP w siatce entrypointu.

Co zostało i dlaczego:

- zakresy `contractors:read` i `people_roster:read` w `ServiceScope` — mogą je
  mieć klucze w bazie; nic już nie otwierają (etykieta „wyłączony 22.11.2026”);
- import paczki z Compassa (`scripts/hr_compass_import.py`, ekran „Import
  z Compassa”, `services/hr/compass_import/`) — decyzja Artura 22.11.2026,
  na wypadek odtworzenia danych ze snapshotu;
- wiersze `user_workday_periods` ze źródłem `compass` (historia sprzed
  przełączenia) i etykieta `"compass"` w mianowniku wyścigów dla tych wierszy;
- wartość `"compass"` przełącznika `hr_availability_source` — znaczy dziś
  „wyłączone” (Ustawienia HR → Moduły: „Teraz: wyłączone”).

Zasady deaktywacji kont po odejściu (jawna decyzja, raz na sprawę, bez
masowego wyłączania) przejął `services/hr/deactivation.py`.

Raport, który mieszkał w tym pliku i dalej działa:

- **`GET /api/insights/reconciliation/placements`** (`app/api/insights_reconciliation.py`)
  — read-only raport uzgadniający placementy w OBU rodzinach atrybucji (FULL OUTER,
  LEFT JOIN na sieroty). Tłumaczy rozjazd 213/228/317/332, **nie usuwa go**; NIE
  rusza `VERIFIER_ANCHORED_CTE`. Nazwiska kandydatów tylko dla ról z odczytem
  kandydatów (`user_has_candidate_read`); pozostali dostają `candidate_id`
  i flagę `candidate_names_redacted`.
