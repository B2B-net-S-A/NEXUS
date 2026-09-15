# Naprawy po audycie integracji, monitoringu i wdrożeń (14.09.2026)

Stan na 15.09.2026. Audyt wskazał 12 ustaleń. Pięć było już naprawionych w kodzie przed tym PR-em. Ten PR zamyka część kodową pozostałych. Tego, co wymaga dostępów właściciela, kod nie zamknie.

## Stan ustaleń

| ID | Stan po tym PR | Gdzie |
|---|---|---|
| INT-01 kursor M365 | Naprawione wcześniej | #1531 |
| INT-02 dedup webhooków M365 | Naprawione wcześniej | `api/microsoft365.py` (klucz z `changeType`, TTL 10 min) |
| MON-03 M365 health | Naprawione wcześniej | `services/m365_health.py` |
| MON-06 błędy frontendu | Naprawione wcześniej | `lib/query-error-telemetry.ts` |
| DEP-03 wersja frontendu | Naprawione wcześniej; teraz równość z wydaniem | `deploy.yml` |
| **DEP-01** deploy dokładnego SHA | **Kod gotowy** — bramka HEAD przed buildem i bramka wdrożonego commitu po buildzie; dokładne przypięcie wymaga Coolify ≥ 4.2.0 | `select_release_sha.py`, `deploy.yml` |
| **DEP-02** nieudana migracja | **Kod gotowy** — widoczna, start bez zmian (decyzja 15.09) | `entrypoint.sh`, `services/migration_health.py` |
| **MON-04** zawieszone pętle | **Kod gotowy** — 14 pętli krytycznych, reszta w `EXEMPT` z powodem | `services/loop_heartbeat.py` |
| **MON-01** monitor Sentry | Kod gotowy (issue przy awarii); **brak sekretów** | `sentry-daily-monitor.yml` |
| **OPS-01** backup/restore | Kod gotowy (issue przy nieświeżej kopii); **brak sekretów w GitHub** | `uptime-probe.yml`, `backup-drill.yml` |
| **MON-02** E2E po zalogowaniu | Kod gotowy (`prod-smoke` po deployu); **brak konta E2E** | `e2e.yml` |
| **MON-05** sonda co minutę | **Do założenia** w Grafana Synthetic Monitoring | — |

## Co zmienia kod

### DEP-01: na produkcję wchodzi tylko commit z zieloną bramką

Pierwszy projekt zakładał przypięcie `git_commit_sha` w Coolify. Przegląd kodu Coolify 4.1.2 (produkcja) wykazał, że `check_git_if_build_needed` nadpisuje przypięty commit bieżącym HEAD maina. Poprawka jest dopiero w 4.2.0, więc wdrożono wariant działający na obecnej wersji (`select_release_sha.py`):

1. Job `select` puszcza deploy tylko wtedy, gdy HEAD maina ma zielony „CI Gate”.
   - Bramka w toku: deploy jest odraczany, a commit wdroży jego własny przebieg.
   - Bramka czerwona: deploy jest wstrzymany z ostrzeżeniem.
   - Ręczny dispatch przy niezielonym HEAD: błąd.
2. Smoke przyjmuje RELEASE_SHA albo jego potomka z **zieloną** bramką. Taki potomek pojawia się, gdy merge wszedł między wyborem wydania a klonem w Coolify. Na bramkę w toku smoke czeka do 10 minut.
3. Potomek z czerwoną bramką daje czerwony deploy z instrukcją wycofania. Na 4.1.2 nie da się temu zapobiec przed buildem, więc jest wykrywany i nazywany.
4. Frontend `version.json` i deep health muszą równać się wersji przyjętej przez smoke (ACCEPTED_SHA). Wywołania API GitHuba mają ponowienia.

Pełne domknięcie, czyli budowanie dokładnie zatwierdzonego commitu, wymaga aktualizacji Coolify do ≥ 4.2.0 i przypinania `git_commit_sha`.

### DEP-02: nieudana migracja jest widoczna

- `entrypoint.sh` zapisuje wynik `alembic upgrade heads` do pliku statusu i nadal nie zatrzymuje startu.
- Przy starcie aplikacja robi `logger.error` z końcówką logu (hasła w adresach połączeń są wycinane), co trafia do Sentry.
- `checks.migrations` w `/api/health` przyjmuje wartość `healthy`, `degraded` (upgrade padł, ale rewizje się zgadzają), `unhealthy` (rozjazd rewizji) albo `unknown`. Stan `unhealthy` otwiera issue w uptime-probe.
- `/api/health/alembic` korzysta z tej samej funkcji porównania rewizji.

### MON-04: zawieszone pętle tła

Heartbeat w pamięci procesu. `checks.background_tasks = degraded: stalled …` pojawia się, gdy pętla nie zaczęła iteracji dłużej niż jej próg.

Objęte pętle: `microsoft365_sync`, `traffit_sync`, `order_mail_ingest`, `compass_workdays_sync`, `compass_lifecycle_sync`, `index_outbox`, `contract_alerts`, `dl_alerts`, `order_gaps`, `signing_sweeper`, `autenti_sweeper`, `rejection_email`, `calendar_reminder`, `cv_generation`.

Test kontraktowy wymusza decyzję dla każdej nowej pętli. Po tygodniu bez fałszywych `stalled` stan można podnieść z `degraded` do `unhealthy`.

### Alarmy o awarii samych monitorów

- Job `alert` w `uptime-probe.yml` otwiera issue przy awarii sondy dostępności albo świeżości kopii.
- Job `alert` w `sentry-daily-monitor.yml` nazywa przyczynę awarii: brak sekretów, Teams nie przyjął wiadomości albo odczyt Sentry jest niepełny.
- `backup-drill.yml` czyta próg wieku kopii ze zmiennej repo `BACKUP_MAX_AGE_HOURS`.

### MON-02: E2E po deployu

Po każdym udanym Deploy biegnie projekt Playwright `prod-smoke`: odczyty po zalogowaniu, bez scenariuszy `@stack` i `@writes`, które od #1544 biegną na efemerycznym stacku w PR-ach. Działa to tylko przy zmiennej repo `E2E_POST_DEPLOY_ENABLED=true`. Włącz ją dopiero po założeniu konta E2E — bez niego każdy deploy dawałby czerwony bieg.

## Kroki właściciela (bez nich kod nie zamknie MON-01 / OPS-01 / MON-02 / MON-05)

1. **Sentry (MON-01).**
   - Utwórz token w Sentry: Settings → Auth Tokens, zakresy `org:read`, `project:read`, `event:read`.
   - Utwórz webhook w Teams Workflows.
   - Zapisz oba jako sekrety repo:
     ```bash
     gh secret set SENTRY_READ_TOKEN
     ```
     ```bash
     gh secret set TEAMS_SENTRY_WEBHOOK_URL
     ```
   - Uruchom workflow `Sentry daily monitor` ręcznie. Oczekiwany wynik: zielony bieg i karta w Teams.
2. **Backup (OPS-01).**
   - Sidecar backupu na serwerze jest włączony (`BACKUP_ENABLED=true`, klucze S3 i publiczny klucz `age` są w Coolify — odczyt 15.09).
   - Brakuje sekretów GitHub: `BACKUP_AGE_PRIVATE_KEY` (prywatna połówka pary, której publiczny klucz jest w Coolify), `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY` (klucz read-only B2). Procedura: `docs/runbook-backup-201.md`.
   - Potem uruchom `backup-drill.yml` ręcznie. Po zielonym wyniku ustaw zmienną `BACKUP_MONITORING_ENABLED=true`.
3. **Konto E2E (MON-02).** Dedykowany użytkownik z rolą recruiter (bez SSO), sekrety `E2E_USER_EMAIL` i `E2E_USER_PASSWORD`, potem zmienna `E2E_POST_DEPLOY_ENABLED=true`.
4. **Sonda zewnętrzna (MON-05).** Grafana Cloud → Testing & synthetics:
   - dwie sondy HTTP co 60 s z dwóch lokalizacji w UE: `https://nexus.dynaminds.pl/login` (200) oraz `https://api.nexus.dynaminds.pl/api/health/live` (200, body `alive`);
   - alert po 2 kolejnych błędach, wysyłany mailem i do Teams, z powiadomieniem o powrocie.

## Weryfikacja

- Testy jednostkowe: `.github/scripts/tests/test_select_release_sha.py`, `test_coolify_release.py`, `backend/tests/test_migration_health.py` (wykonuje blok entrypointu z podstawionym `alembic`), `test_loop_heartbeat.py`, `test_deploy_version_summary_script.py`, `test_ci_deploy_workflows_contract.py`.
- `actionlint` na zmienionych workflowach bez nowych błędów.
- Na produkcji po merge:
  - job `select` pokazuje „Wydanie = HEAD maina … z zieloną bramką”;
  - `/api/health.version`, `version.json.sha` i ACCEPTED_SHA są równe;
  - `checks.migrations` i `checks.background_tasks` mają stan `healthy`.

## Stan po domknięciu

Stan dowodów: 15.09.2026, po pierwszym wdrożeniu commitu
`e55a901984b9b3ff8f658d1c1831e64f7cc7a971`.

| ID | Stan | Dowód |
|---|---|---|
| DEP-01 | **ZALICZONE** | [Deploy 34979326940](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34979326940): `select` wybrał HEAD `e55a901` z zieloną bramką, smoke przyjął to samo SHA, backend i frontend były zgodne z wydaniem. |
| DEP-02 | **ZALICZONE** | Produkcyjne `/api/health`: `version=e55a901984b…`, `checks.migrations=healthy`; `/api/health/alembic`: DB i kod na `0310_dl_alerts_my_clients_panel`, bez osieroconych rewizji. |
| MON-04 | **ZABLOKOWANE CZASOWO: trwa wymagane okno obserwacji** | Pierwszy pomiar po deployu: `checks.background_tasks=healthy`. Drugi pomiar może być wykonany dopiero po co najmniej 2 godzinach; zmiana klasyfikacji na `unhealthy` nie wcześniej niż po pełnych 7 dniach, czyli 22.09.2026. |
| MON-01 | **ZABLOKOWANE: brak dostępu do Teams do wizualnego potwierdzenia karty** | [Sentry daily monitor 34980098469](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34980098469) zakończył digest i wysyłkę bez ścieżki awaryjnej. Odbiór oraz zawartość karty w Teams wymagają potwierdzenia właściciela. |
| OPS-01 | **ZABLOKOWANE: właściciel musi ustawić trzy sekrety GitHub** | [Coolify Ops 34980172655](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34980172655): konfiguracja serwerowa kompletna, ale brak `BACKUP_AGE_PRIVATE_KEY`, `BACKUP_S3_ACCESS_KEY` i `BACKUP_S3_SECRET_KEY`; monitoring pozostaje poprawnie wyłączony, drill nie został uruchomiony. |
| MON-02 | **ZABLOKOWANE: właściciel musi włączyć zmienną repo** | Ręczny [E2E 34980234631](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34980234631): produkcyjny job `Playwright against production` zielony. Automatyczny [E2E po deployu 34979987249](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34979987249) pominął `prod-smoke`, ponieważ `E2E_POST_DEPLOY_ENABLED` nie jest `true`. |
| MON-05 | **ZABLOKOWANE: właściciel musi uwierzytelnić sesję Grafana Cloud** | Wejście do `arturt96.grafana.net` kończy się na ekranie logowania. Sondy i test contact point nie zostały utworzone. |

Pierwszy deploy po merge był zielony, ale potwierdził znaną cechę obecnego
wdrożenia bez rolling update: najdłuższa przerwa API wyniosła 75 s, frontendu
7 s, a kontener Postgresa został odtworzony. To nie wpływa na zaliczenie bramki
DEP-01, ale pozostaje dowodem ryzyka operacyjnego dla ewentualnej aktualizacji
Coolify.
