# Handoff dla Codexa — domknięcie audytu integracji, monitoringu i wdrożeń

Data przekazania: 15.09.2026. Autor stanu: sesja Claude Code w worktree `integrations-monitoring-deployment-audit-0c4de1`.

Zadanie: doprowadzić do końca naprawy z audytu z 14.09.2026, czyli **zmergować PR, zweryfikować produkcję i domknąć kroki konfiguracyjne**. Kod dla wszystkich punktów, które da się naprawić kodem, jest już w PR. Nie projektuj rozwiązań od nowa — decyzje podjęte przez Artura są wypisane niżej i obowiązują.

> **Repozytorium `B2B-net-S-A/NEXUS` jest PUBLICZNE, logi GitHub Actions też.** Żadnych sekretów, tokenów, haseł, adresów e-mail osób, nazwisk ani kwot w commitach, PR-ach, komentarzach i logach. Sekretów nie generujesz i nie wpisujesz w imieniu właściciela — patrz sekcja 5.

---

## 1. Źródła i stan wyjściowy

| Co | Gdzie |
|---|---|
| Audyt (lokalny, NIE w repo) | `/Users/arturtwardowski/NEXUS/docs/integrations-monitoring-deployment-audit-2026-09-14.md` (plik nieśledzony w głównym checkoucie — nie commituj go) |
| Raport napraw (w PR) | `docs/integrations-monitoring-deploy-fixes-completion-report.md` |
| PR | https://github.com/B2B-net-S-A/NEXUS/pull/1546 — gałąź `fix/audit-integrations-monitoring-deploy` |
| Stan PR przy przekazaniu | wszystkie wymagane checki zielone na `30e9eb50`; `mergeStateStatus = BEHIND` o 1 commit maina (`2c86d434`, #1542) |
| Produkcja przy przekazaniu | działa, bez zmian z tego PR (nic nie zmergowane) |

Zasady repo, które MUSISZ znać przed pracą, są w `CLAUDE.md` (sekcje „Deploy”, „Healthcheck endpoint”, „CI gotchas”). Najważniejsze:

- Branch protection: `strict=true` + `enforce_admins=true`. **Zero `gh pr merge --admin`, zero pushy na `main`.** Merge wyłącznie przez PR po zielonym CI.
- **Nie rebase'uj i nie force-pushuj.** Aktualizacja gałęzi = `git fetch origin main && git merge origin/main`.
- Każdy merge na `main` = deploy Coolify = ~1–2 min przerwy dla użytkowników. Merguj poza godzinami pracy (po 17:00 czasu polskiego albo przed 8:00).

---

## 2. Co już zrobiono (nie powtarzaj)

| ID audytu | Stan | Kod |
|---|---|---|
| INT-01, INT-02, MON-03, MON-06, DEP-03 | naprawione wcześniejszymi PR-ami (#1530–#1533 i wcześniej) | — |
| **DEP-01** — commit bez zielonej bramki wchodził na prod | naprawione w #1546 | `.github/scripts/select_release_sha.py`, `.github/workflows/deploy.yml` (job `select` + krok akceptacji w smoke), `.github/scripts/deploy_version_summary.py` |
| **DEP-02** — nieudana migracja niewidoczna | naprawione w #1546 | `backend/entrypoint.sh` (plik statusu alembica), `backend/app/services/migration_health.py`, `checks.migrations` w `backend/app/main.py` |
| **MON-04** — zawieszona pętla tła = „running” | naprawione w #1546 | `backend/app/services/loop_heartbeat.py`, `beat.tick()` w 14 pętlach, `checks.background_tasks = degraded: stalled …` |
| Alarmy o awarii samych monitorów | #1546 | job `alert` w `uptime-probe.yml` i `sentry-daily-monitor.yml`; `BACKUP_MAX_AGE_HOURS` w `backup-drill.yml` |
| **MON-02** — E2E po zalogowaniu po deployu | kod w #1546, **wyłączony zmienną** | `e2e.yml`: trigger `workflow_run` na „Deploy”, projekt `prod-smoke`, bramka `vars.E2E_POST_DEPLOY_ENABLED == 'true'` |
| **MON-01** (Sentry), **OPS-01** (backup), **MON-05** (sonda co minutę) | kod gotowy, **brak sekretów / konfiguracji zewnętrznej** | patrz sekcja 5 |

### Decyzje Artura (15.09.2026) — obowiązują, nie zmieniaj

1. **DEP-02:** nieudana migracja ma być **głośna, ale NIE zatrzymuje startu**. Nie dopisuj `exit` do bloku alembica w `entrypoint.sh` (Coolify compose nie ma rolling update → `exit 1` = pętla restartów; incydent deploy #702). Pilnuje tego `backend/tests/test_migration_health.py`.
2. **MON-05:** zewnętrzna sonda = **Grafana Synthetic Monitoring** (konto Grafana Cloud `arturt96`), nie UptimeRobot, nie gęstszy cron GitHuba.
3. **MON-02:** E2E po deployu na produkcji wyłącznie **odczytowe** (`prod-smoke` — bez `@stack`/`@writes`).

### Ważna korekta projektu DEP-01 (żeby jej nie „naprawić” z powrotem)

Pierwszy projekt przypinał `git_commit_sha` w Coolify. **Coolify 4.1.2 (produkcja) ignoruje przypięty commit** — `ApplicationDeploymentJob::check_git_if_build_needed` nadpisuje go wynikiem `git ls-remote` HEAD maina (poprawione dopiero w 4.2.0). Dlatego #1546 NIE przypina commitu, tylko:

- job `select`: deploy rusza tylko przy zielonym „CI Gate” **HEAD maina** (bramka w toku → odroczenie, wdroży go jego własny przebieg; czerwona → wstrzymanie z `::warning::`; ręczny dispatch przy niezielonym HEAD → błąd),
- smoke (`select_release_sha.py accept`): produkcja musi serwować RELEASE_SHA albo jego **potomka z zieloną bramką** (czeka ≤ 10 min na bramkę w toku); potomek z czerwoną bramką = czerwony deploy z instrukcją wycofania; wynik trafia do `ACCEPTED_SHA`, a `version.json` frontendu i deep health muszą mu być równe.

Konsekwencja zamierzona: **czerwony HEAD maina wstrzymuje wszystkie deploye**, dopóki nie przyjdzie zielony commit.

---

## 3. Zadanie A — zmergować PR #1546

1. Zaktualizuj gałąź PR (nie rebase):
   ```bash
   git fetch origin main
   git checkout fix/audit-integrations-monitoring-deploy
   git merge --no-edit origin/main
   ```
2. Jeśli są konflikty — zachowaj intencję obu stron. Znane miejsca kolizji z innymi PR-ami i jak je rozwiązywać:
   - `.github/workflows/deploy.yml` — kroki smoke muszą porównywać z `ACCEPTED_SHA`/`RELEASE_SHA`, nigdy przez GitHub `compare` API w samym workflow (liczy to wyłącznie skrypt). Zmiany innych PR-ów w raporcie przerwy / timingach startu przyjmij, podając im `"${RELEASE_SHA:-$TARGET_SHA}"`.
   - `backend/tests/test_ci_deploy_workflows_contract.py` — zachowaj testy obu stron.
   - Nowa pętla w `app.state.background_tasks` (`backend/app/main.py`) z maina → `test_loop_heartbeat.py` wywali CI. Dodaj `beat = loop_heartbeat.register(...)` + `beat.tick()` na początku iteracji ALBO wpis w `EXEMPT` w `backend/app/services/loop_heartbeat.py` z konkretnym powodem.
   - `backend/app/data/procedures/orders_procedure_stamp.json` — jeśli `test_orders_procedure_freshness.py` jest czerwony, przejrzyj zmiany i przestempluj: `cd backend && python scripts/stamp_orders_procedure.py`.
3. Sprawdzenia lokalne (lokalny Python to 3.9 — backend testuj w Dockerze, np. obraz `nexus-verify:img` z `--entrypoint bash`; testy bez bazy przez `--noconftest`):
   ```bash
   cd backend && ruff check app/ && ruff format --check app/
   ```
   ```bash
   cd backend && python -m pytest -q --noconftest tests/test_ci_deploy_workflows_contract.py tests/test_deploy_version_summary_script.py tests/test_migration_health.py tests/test_loop_heartbeat.py tests/test_delivery_contract.py tests/test_orders_procedure_freshness.py tests/test_sentry_daily_digest_script.py
   ```
   ```bash
   python3 -m unittest discover -s .github/scripts/tests -p 'test_*.py'
   ```
   Opcjonalnie `actionlint` (obraz `rhysd/actionlint:1.7.7`) na `deploy.yml`, `e2e.yml`, `uptime-probe.yml`, `sentry-daily-monitor.yml`, `backup-drill.yml` — nie może być nowych błędów poza istniejącymi uwagami shellcheck.
4. Commit (conventional, po polsku jak reszta repo), push, poczekaj na zielone CI na PR:
   ```bash
   gh pr checks 1546 --repo B2B-net-S-A/NEXUS
   ```
   Wymagane konteksty: `Gitleaks secret scan`, `Backend (lint + migrations)`, `Backend (pytest)`, `Frontend (typecheck + build)`. Pułapka gitleaks: w testach nie wpisuj adresów połączeń z hasłem jako jednego literału — składaj je w locie.
5. Merge po zielonym CI i **poza godzinami pracy**:
   ```bash
   gh pr merge 1546 --repo B2B-net-S-A/NEXUS --squash --delete-branch
   ```
   Jeśli w międzyczasie main znów ucieknie (`BEHIND`) — wróć do kroku 1. Przy kilku PR-ach naraz użyj `scripts/merge-train.sh`.

---

## 4. Zadanie B — weryfikacja pierwszego deployu po merge'u

Ten deploy jest jednocześnie testem nowego mechanizmu DEP-01. Obserwuj run workflow „Deploy” wyzwolony przez „CI Gate” dla squash-commitu:

```bash
gh run list --repo B2B-net-S-A/NEXUS --workflow Deploy --branch main --limit 3
```

Kryteria zaliczenia (wszystkie):

1. Job **`select`** zakończony sukcesem, w logu: `Wydanie = HEAD maina <sha7> z zieloną bramką CI Gate`. Jeśli pokazuje `Deploy odroczony` — to poprawne, gdy w międzyczasie wszedł kolejny merge; wtedy weryfikuj run tamtego commitu.
2. Job **`deploy`**: krok „Healthcheck” loguje `Produkcja serwuje wydanie <sha7>` (albo `potomek wydania … z zieloną bramką`), dalej zielone: frontend `version.json`, deep healthcheck, alembic revision check.
3. Podsumowanie runu („Wersje po deployu”) — werdykt `zgodny z wydaniem` dla backendu i frontendu.
4. Produkcja:
   ```bash
   curl -fsS https://api.nexus.dynaminds.pl/api/health | jq '{status, version, m: .checks.migrations, bg: .checks.background_tasks}'
   ```
   Oczekiwane: `status = healthy`, `version` = SHA z punktu 2, `checks.migrations = "healthy"`, `checks.background_tasks = "healthy"`.
5. Ponów punkt 4 po **ok. 2–3 godzinach** — `checks.background_tasks` nadal `healthy` (brak fałszywych `degraded: stalled …`). Jeśli pojawi się `stalled` dla konkretnej pętli: sprawdź w logach kontenera, czy pętla faktycznie stoi. Jeśli nie stoi, a jej iteracja jest po prostu dłuższa — podnieś `max_silence_seconds` przy `loop_heartbeat.register` tej pętli (osobny PR, z uzasadnieniem w komentarzu). Nie wyłączaj mechanizmu.

Jeśli deploy jest czerwony:
- `select` czerwony z `GitHub API HTTP …` → zwykle chwilowe, `gh run rerun <id> --failed`.
- Healthcheck czerwony z `Na produkcji stoi … z bramką CI Gate = failure` → na produkcję wszedł commit z czerwoną bramką (Coolify zbudował HEAD). Rollback: panel Coolify → nexus → Deployments → poprzedni → Redeploy; zgłoś Arturowi.
- Healthcheck czerwony z samymi `stale version` → build nie wstał; diagnoza wg `~/.claude/rules/deployment-runbook.md` §8 i workflow `Coolify Ops` (`action=list`).
- **Nie cofaj logiki DEP-01 do akceptacji dowolnego potomka.**

---

## 5. Zadanie C — konfiguracja wymagająca dostępów właściciela

Te kroki domykają MON-01, OPS-01, MON-02 i MON-05. **Sekrety musi dostarczyć Artur** (nie generuj ich sam, nie proś o wklejenie do czatu ani do repo). Twoja rola: przygotować dokładne polecenia, poprosić o ich wykonanie albo o przekazanie wartości bezpiecznym kanałem, a potem **zweryfikować** efekt.

Nazwy sekretów i zmiennych są jawne; wartości nigdy.

### C1. MON-01 — dzienny monitor Sentry

1. Artur tworzy w Sentry (`b2bnet-sa`) token: Settings → Auth Tokens, zakresy `org:read`, `project:read`, `event:read`.
2. Artur tworzy webhook Teams Workflows dla kanału alertów.
3. Artur ustawia sekrety repo:
   ```bash
   gh secret set SENTRY_READ_TOKEN --repo B2B-net-S-A/NEXUS
   ```
   ```bash
   gh secret set TEAMS_SENTRY_WEBHOOK_URL --repo B2B-net-S-A/NEXUS
   ```
4. Ty uruchamiasz i weryfikujesz:
   ```bash
   gh workflow run sentry-daily-monitor.yml --repo B2B-net-S-A/NEXUS --ref main
   ```
   Kryterium: run zielony (exit 0), karta digestu w Teams zawiera sekcje `nexus-be` i `nexus-fe` bez `MONITORING READ FAILED`. Istniejące issue „NEXUS dzienny monitor Sentry nie działa” (jeśli powstało z crona) zamknij z komentarzem, linkiem do zielonego runu.

### C2. OPS-01 — kopia off-site i restore drill

Stan odczytany 15.09 (`Coolify Ops` → `action=backup-status`): po stronie serwera `BACKUP_ENABLED=true`, klucze S3 i publiczny klucz `age` są w Coolify. **Brakuje wyłącznie sekretów w GitHubie**, więc drill i monitoring świeżości nie mają czym czytać.

1. Artur ustawia sekrety repo (procedura: `docs/runbook-backup-201.md`):
   - `BACKUP_AGE_PRIVATE_KEY` — prywatna połówka pary `age`, **której publiczny klucz jest już w Coolify** (nowa para nie odszyfruje istniejących archiwów),
   - `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY` — klucz aplikacyjny B2 z dostępem **read-only** do bucketa `dynaminds-nexus-offsite`.
   Zmienne `BACKUP_S3_BUCKET/ENDPOINT/REGION/PREFIX/PROVIDER` są już ustawione.
2. Ty sprawdzasz, że pierwsza kopia istnieje i uruchamiasz drill:
   ```bash
   gh workflow run coolify-ops.yml --repo B2B-net-S-A/NEXUS --ref main -f action=backup-status
   ```
   ```bash
   gh workflow run backup-drill.yml --repo B2B-net-S-A/NEXUS --ref main
   ```
   Kryterium: drill zielony we wszystkich krokach (świeży `LATEST.json`, odszyfrowanie, `pg_restore`, `alembic upgrade head`, kontrola tabel, spot-check korpusu CV). Uwaga na limity B2: odmowa limitem daje HTTP 403, a nie rachunek — przy 403 sprawdź limity konta B2, zanim uznasz klucz za zły.
3. Dopiero po zielonym drillu:
   ```bash
   gh variable set BACKUP_MONITORING_ENABLED --body true --repo B2B-net-S-A/NEXUS
   ```
   ```bash
   gh workflow run uptime-probe.yml --repo B2B-net-S-A/NEXUS --ref main
   ```
   Kryterium: job `Backup manifest is fresh and clean` zielony (nie `skipped`).
4. Uzupełnij `docs/disaster-recovery.md` o zmierzone RPO (wiek kopii) i RTO (czas trwania drillu od pobrania do zakończenia kontroli) — osobnym PR-em, bez danych osobowych.
5. Zamknij issue „NEXUS backup drill nie przechodzi” z linkiem do zielonego runu.

### C3. MON-02 — konto E2E i smoke po deployu

1. Artur (admin) zakłada dedykowane konto E2E z rolą **recruiter**, logowanie e-mail/hasło (bez SSO), z ukończonym onboardingiem. Nie nadawaj roli admin ani finance.
2. Artur ustawia sekrety:
   ```bash
   gh secret set E2E_USER_EMAIL --repo B2B-net-S-A/NEXUS
   ```
   ```bash
   gh secret set E2E_USER_PASSWORD --repo B2B-net-S-A/NEXUS
   ```
3. Ty uruchamiasz nocny bieg ręcznie:
   ```bash
   gh workflow run e2e.yml --repo B2B-net-S-A/NEXUS --ref main
   ```
   Kryterium: job `Playwright against production` zielony, w podsumowaniu `prod-smoke + preview` (nie „bieg CZĘŚCIOWY”). Jeśli testy `prod-smoke` padają przez nieaktualne asercje (np. twarde `/jobs/1`, `/candidates/1`), napraw testy osobnym PR-em — bez tagowania ich jako zapisujących, jeśli niczego nie zapisują.
4. Dopiero przy zielonym biegu:
   ```bash
   gh variable set E2E_POST_DEPLOY_ENABLED --body true --repo B2B-net-S-A/NEXUS
   ```
   Kryterium: następny udany Deploy wyzwala `E2E (Playwright)` z podsumowaniem „E2E po deployu — prod-smoke”, zielonym, z SHA backendu i frontendu równym wdrożonemu.

### C4. MON-05 — Grafana Synthetic Monitoring

Wymaga dostępu do `https://arturt96.grafana.net` (Artur w panelu albo token service account z rolą Editor przekazany bezpiecznie — nigdy do repo).

1. Testing & synthetics → dwie sondy HTTP, częstotliwość 60 s, co najmniej dwie lokalizacje w UE:
   - `https://nexus.dynaminds.pl/login` — sukces = HTTP 200 (z podążaniem za przekierowaniami),
   - `https://api.nexus.dynaminds.pl/api/health/live` — sukces = HTTP 200 i body zawiera `alive`.
   - Nagłówek `User-Agent` zawierający `dynaminds-smoke-test` (bypass reguły Cloudflare dla health).
2. Reguła alertu: 2 kolejne nieudane sprawdzenia → powiadomienie mailem i do Teams; powiadomienie o powrocie.
3. Weryfikacja: „Test contact point” w Grafanie dostarcza wiadomość (bez wyłączania produkcji); obie sondy zielone przez ≥ 1 h.
4. Opisz konfigurację (nazwy sond, URL-e, progi, kanał alertu — bez tokenów) w `docs/sentry-monitoring.md` albo nowym `docs/uptime-monitoring.md`, osobnym PR-em, i dopisz odnośnik w sekcji „Healthcheck endpoint” w `CLAUDE.md`.

---

## 6. Zadanie D — po tygodniu obserwacji (nie wcześniej niż 22.09.2026)

1. Jeśli przez 7 dni `checks.background_tasks` nie pokazał fałszywego `stalled` — w `backend/app/main.py` zmień prefiks `degraded: stalled` na `unhealthy: stalled` (uptime-probe zacznie otwierać issue). Zaktualizuj `CLAUDE.md` i test klasyfikacji. Osobny PR.
2. Rozważ objęcie heartbeatem pętli oznaczonych w `EXEMPT` jako „do objęcia po tygodniu obserwacji” (`notification_triggers`, `job_deadline_alerts`), z progiem ≥ 2× interwał + najdłuższy bieg.

## 7. Zadanie E — opcjonalne, wymaga zgody Artura: Coolify ≥ 4.2.0

Pełne domknięcie DEP-01 (budowanie dokładnie zatwierdzonego commitu) wymaga aktualizacji Coolify na serwerze NEXUS do wersji ≥ 4.2.0 i dopiero wtedy przypinania `git_commit_sha` przed triggerem. **Nie aktualizuj Coolify bez wyraźnej zgody Artura** — to operacja na produkcji z ryzykiem przestoju i nie ma rolling update. Jeśli dostaniesz zgodę: najpierw przygotuj plan (backup konfiguracji Coolify, okno serwisowe, rollback), dopiero potem wykonanie; po aktualizacji dodaj przypięcie commitu z odczytem kontrolnym i porównaniem `.commit` z deploymentu Coolify, a smoke zawęź do równości z przypiętym SHA.

---

## 8. Czego NIE robić

- Nie dopisywać `exit` do bloku alembica w `backend/entrypoint.sh`.
- Nie przywracać akceptacji dowolnego potomka TARGET_SHA w smoke deployu ani wywołań `compare` API w `deploy.yml`.
- Nie wyłączać heartbeatu, nie usuwać testu `test_loop_heartbeat.py`; nowa pętla = rejestracja albo `EXEMPT` z powodem.
- Nie włączać `E2E_POST_DEPLOY_ENABLED` przed zielonym ręcznym biegiem z kontem E2E.
- Nie włączać `BACKUP_MONITORING_ENABLED` przed zielonym drillem.
- Nie generować nowej pary `age` zamiast istniejącej — nie odszyfruje obecnych archiwów.
- Nie commitować sekretów, nazwisk, adresów e-mail osób ani kwot; nie wklejać ich do opisów PR i komentarzy.
- Nie mergować z `--admin`, nie pushować na `main`, nie rebase'ować, nie force-pushować.
- Nie aktualizować Coolify bez zgody Artura.

## 9. Raport końcowy

Po zakończeniu dopisz na końcu `docs/integrations-monitoring-deploy-fixes-completion-report.md` sekcję **„Stan po domknięciu”** (osobny PR, bez danych wrażliwych):

| ID | Stan | Dowód |
|---|---|---|
| DEP-01 | … | link do runu Deploy (select + smoke) |
| DEP-02 | … | `checks.migrations` z produkcji |
| MON-04 | … | `checks.background_tasks` po ≥ 2 h |
| MON-01 | … | link do zielonego runu Sentry |
| OPS-01 | … | link do zielonego drillu + RPO/RTO |
| MON-02 | … | link do runu E2E po deployu |
| MON-05 | … | nazwy sond, test contact point |

Jeśli któregoś kroku nie da się zakończyć (brak dostępu, brak decyzji) — wpisz „ZABLOKOWANE: <czego brakuje, od kogo>”, nie oznaczaj jako zrobione.
