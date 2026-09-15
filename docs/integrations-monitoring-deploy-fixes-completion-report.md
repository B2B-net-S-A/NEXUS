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

## Aktualizacja operacyjna 15.09.2026 (stan na 19:45 CEST)

Ta sekcja zastępuje starsze statusy powyżej. Produkcja serwuje
`8b6b739ed82d8976002aa6346cc73b8447f48a37` (#1549, zmergowany o 17:17 CEST
przez inną sesję po wdrożeniu `2542987`). Oba wdrożenia przeszły tę samą
bramkę DEP-01.

| ID | Stan | Dowód i dalszy krok |
|---|---|---|
| DEP-01 | **ZALICZONE** | [Deploy 34985517944](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34985517944) (`2542987`) i [Deploy 34987664618](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34987664618) (`8b6b739`): job `select` — „Wydanie = HEAD maina 8b6b739 z zieloną bramką CI Gate”, smoke — „Produkcja serwuje wydanie 8b6b739”, backend i frontend „zgodny z wydaniem”. |
| DEP-02 | **ZALICZONE** | Odczyt 19:36 CEST: `/api/health` i `/api/health/deep` zwracają dokładne SHA `8b6b739e…`, `checks.migrations=healthy`. `/api/health/alembic`: DB i kod na `0310_dl_alerts_my_clients_panel`, `orphaned=[]`, `reconcilable=true`. |
| MON-04 | **ZALICZONE (drugi odczyt)**; podniesienie progu **ZABLOKOWANE CZASOWO do 22.09.2026** | Pierwszy odczyt po wdrożeniu `2542987`: `healthy`. Wdrożenie #1549 zrestartowało backend (Postgres odtworzony 17:23:46 CEST), a restart zeruje rejestr heartbeatów, więc okno 2 h liczono od nowa. Drugi odczyt 19:36:44 CEST, po ponad 2 h bez restartu: `checks.background_tasks=healthy`, żadna sonda nie jest `degraded` ani `unhealthy`. Zmiana `degraded: stalled` → `unhealthy: stalled` (Zadanie D) nie wcześniej niż 22.09.2026: w Codexie nie było automatyzacji dla tego kroku, dlatego założono jednorazowe zadanie zaplanowane w Claude Code na 22.09.2026 09:00 (przegląd ostrzeżeń uptime-probe z tygodnia, PR bez merge'u). |
| MON-01 | **ZALICZONE** | [Sentry daily monitor 34980098469](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34980098469) zakończył się zielono. W Teams, w kanale `NEXUS — alerty`, wizualnie potwierdzono kartę `NEXUS Sentry` z digestem obu projektów i bez komunikatu `MONITORING READ FAILED`. |
| OPS-01 | **ZABLOKOWANE: właściciel musi dodać trzy sekrety GitHub** | [Coolify Ops 34980172655](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34980172655) potwierdził kompletną konfigurację serwerową. Brakuje `BACKUP_AGE_PRIVATE_KEY` (istniejący klucz prywatny pasujący do publicznego w Coolify), `BACKUP_S3_ACCESS_KEY` i `BACKUP_S3_SECRET_KEY` (klucz B2 tylko do odczytu). `BACKUP_MONITORING_ENABLED=false`, restore drill nie został uruchomiony. Śledzenie: [issue #1247](https://github.com/B2B-net-S-A/NEXUS/issues/1247). |
| MON-02 | **ZABLOKOWANE: konto E2E i logowanie hasłem na produkcji** | [E2E 34986200229](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34986200229) i [E2E 34988319871](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34988319871) (po wdrożeniu #1549, gdy zmienna była jeszcze włączona) zakończyły się błędem bez sekretów konta; alert w [issue #1551](https://github.com/B2B-net-S-A/NEXUS/issues/1551). `E2E_POST_DEPLOY_ENABLED=false` od 17:29:58 CEST (potwierdzone odczytem API). Nowe ustalenie: produkcja ma wyłączone logowanie hasłem (`/api/auth/methods` → `password:false`), a `/login` renderuje formularz hasła tylko przy `password:true`; `frontend/e2e/auth.setup.ts` loguje się właśnie tym formularzem. Same sekrety nie wystarczą — potrzebne są: konto E2E z rolą recruiter, jego adres dopisany do `PASSWORD_LOGIN_BREAK_GLASS_EMAILS` w Coolify (wyjątek działa tylko dla `POST /api/auth/login`), sekrety `E2E_USER_EMAIL` i `E2E_USER_PASSWORD` oraz zmiana `auth.setup.ts` na logowanie przez API. Dopiero zielony ręczny bieg pozwala ustawić zmienną z powrotem na `true`. |
| MON-05 | **ZALICZONE poza Teams**; kanał Teams **ZABLOKOWANE: webhook musi dodać właściciel** | Wybrano wariant bez zmiany planu: oba checki co 120 s z Frankfurtu i Paryża (89 280 wykonań miesięcznie przy limicie 100 000). `nexus-login-http` (ID `89783`) i `nexus-api-live-http` (ID `89793`, walidacja body `"status":"alive"`). Alert per check: co najmniej 3 z 4 nieudanych wykonań w 5 min (reguła `ProbeFailedExecutionsTooHigh [5m]`, `health=ok`), trasa domyślna do punktu kontaktu e-mail z włączonymi powiadomieniami o powrocie; test punktu kontaktu wysłany z sukcesem ok. 19:40 CEST. Obserwacja 17:58–19:37 CEST: oba checki 100% uptime i 100% osiągalności. Szczegóły: `docs/uptime-monitoring.md`. |

Wdrożenie #1549 ponownie pokazało przerwę podczas wymiany kontenerów:
najdłuższa przerwa widziana przez użytkowników 66 s, kontener Postgresa został
odtworzony. Aktualizacja Coolify (zadanie E) nie była wykonywana — wymaga
osobnej, wyraźnej zgody właściciela.
