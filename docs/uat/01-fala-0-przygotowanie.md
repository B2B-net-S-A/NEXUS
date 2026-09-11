# 01 — Fala 0: przygotowanie (1 dzień, człowiek + 1 agent)

> Bez zielonych punktów §1–§3 nie zaczyna się Fali 1. Punkty §4–§6 można robić równolegle.

## 1. Decyzje (człowiek) — wpisz do `manifest.yaml` → `decisions`

| Decyzja | Opcje | Skutek dla planu |
|---|---|---|
| Kto zaczyna pierwszy | role + liczba osób | moduły ich ról dostają `depth: full`, reszta `depth: overview` |
| DynaReporter | testujemy / wygaszamy | wygaszamy → M10 bez sekcji DR, M00 sprawdza tylko brak białych stron |
| Okres przejściowy Traffit | cięcie / równolegle N tyg. / zapis zwrotny | równolegle → M13 dodaje scenariusz „zmiana w Trafficie widoczna w NEXUS-ie po nocy” |
| Budżet AI na UAT | liczby | wpisz do `manifest.yaml` → `ai_budget` |
| Głębokość DR-modułu finansów `/finance` | full / overview | zależy od tego, czy Finanse są w pilotażu |

## 2. Warunki wstępne infrastruktury (agent sprawdza, człowiek naprawia)

Wykonaj i wklej wynik do `wyniki/F0/warunki.md`.

### 2.1 Health

```bash
UA="dynaminds-smoke-test/1.0 (+uat)"
curl -fsS -A "$UA" https://api.nexus.dynaminds.pl/api/health | jq '{status, version, deployedAt, checks}'
```

Oczekiwane: `status: healthy`, w `checks` żadne `degraded`/`unhealthy`/`misconfigured`.
Dozwolone: `unconfigured`/`disabled`/`unknown` dla `autenti`, `priority_work`,
`recruitment_allocation`, `workforce_availability`, `reranker`, `voyage`.

**Stan 2026-09-11:** `traffit = degraded`. Sprawdź powód:
`GET /api/admin/traffit/sync/status` (admin, Bearer) → pole `last_status`, `errors`,
`phases`. Typowe przyczyny: watermark `__daily__` wstrzymany błędem fazy; brak świeżego
biegu > 36 h. Decyzja: naprawić przed Falą 1 albo zapisać jako znany stan z powodem.

```bash
curl -fsS -A "$UA" -H "Authorization: Bearer $TOK" https://api.nexus.dynaminds.pl/api/health/deep | jq '.status, [.checks[]? | select(.status != "healthy")]'
```

Oczekiwane: `healthy`, pusta lista niezdrowych.

### 2.2 Backup — BLOCKER startu produkcyjnego

```bash
gh run list --workflow backup-drill.yml --limit 4 --json conclusion,createdAt --jq '.[] | "\(.createdAt[0:10]) \(.conclusion)"'
```

Stan 2026-09-11: `failure` × 3 (24.08, 31.08, 07.09). Powód z logu: drill nie ma
dostępu do kopii off-site ani klucza `age` do odszyfrowania (brak secrets
`BACKUP_S3_*`/`BACKUP_AGE_*` w repo). Do zrobienia przez człowieka:

1. Sprawdź, czy kontener `backup` na serwerze w ogóle wysyła kopie (`BACKUP_ENABLED`,
   `BACKUP_S3_BUCKET` w env Coolify — przez workflow „Coolify set env”, nie panel).
2. Uzupełnij secrets/variables repo wymagane przez `backup-drill.yml`.
3. Uruchom drill ręcznie: `gh workflow run backup-drill.yml` i doczekaj zielonego.
4. Osobno: korpus CV (object storage) nie jest objęty żadnym backupem — zapisz jako
   ryzyko do decyzji, nie blokuje UAT, blokuje „koniec Traffita”.

### 2.3 Sentry — czysty punkt startu

Zanotuj listę nierozwiązanych issue z ostatnich 7 dni (`is:unresolved lastSeen:-7d`,
sort `freq`) dla `nexus-be` i `nexus-fe`. To jest **baseline**: karta
[przekrojowe/C-sentry.md](przekrojowe/C-sentry.md) porównuje z nim po każdym module.
Issue już obecne w baseline nie są „znalezione przez UAT”, ale idą do Fali 3 jak każde inne.

### 2.4 Nocny Playwright

```bash
gh run list --workflow e2e.yml --limit 5 --json conclusion,createdAt --jq '.[] | "\(.createdAt[0:10]) \(.conclusion)"'
```

Oczekiwane: `success`. Stan 2026-09-11: zielony 6 nocy z rzędu.

### 2.5 Zamrożenie SHA

```bash
git fetch origin && git rev-parse --short=7 origin/main
curl -fsS -A "$UA" https://api.nexus.dynaminds.pl/api/health | jq -r .version | cut -c1-7
```

Oba muszą być równe. Wpisz do `manifest.yaml` → `tested_sha`. Od tej chwili do końca
Fali 2 na `main` wchodzą wyłącznie poprawki z UAT (merge train, jeden PR na moduł).
Każdy merge = redeploy = restart kontenera = przerwane zadania w tle (przeglądy bazy,
generacje CV w kolejce). Jeśli SHA się zmieni w trakcie fali — karty w toku dopisują
nowy SHA do raportu i powtarzają scenariusze AI-asynchroniczne.

## 3. Konta i sesje

- **Konto admina** z hasłem (nie tylko SSO) — do zapisu stanu Playwright. Jeśli
  `PASSWORD_LOGIN_ENABLED=false`, konto musi być w `PASSWORD_LOGIN_BREAK_GLASS_EMAILS`.
- Zapisz stan logowania: `cd frontend && E2E_USER_EMAIL=… E2E_USER_PASSWORD=… npx playwright test --project=setup`
  → `frontend/e2e/.auth/state.json`. Każdy agent Fali 1 dostaje KOPIĘ tego pliku
  (osobny profil = osobny `localStorage` = osobna persona podglądu).
- **Lista person do podglądu** (ID użytkowników, nie nazwiska — zapisz w
  `wyniki/F0/persony.md`, plik lokalny): po jednej aktywnej osobie z każdej roli:
  `admin`, `head_of_recruitment`, `delivery_lead` (z przypisanym co najmniej 1 klientem),
  `talent_community_manager`, `finance`, `tac`, `recruiter`, `sourcer`. Rola `user`
  (legacy viewer) — jeśli istnieje aktywne konto, dodaj; jeśli nie, zapisz „brak”.
  Źródło: `GET /api/admin/users` (admin).
- Sprawdź, że dla DL z listy `GET /api/my-clients` (w podglądzie) zwraca ≥ 1 klienta.

## 4. Dane testowe

Wykonaj [02-dane-testowe.md](02-dane-testowe.md) §2 (zestaw bazowy). Zapisz ID do
`wyniki/F0/dane-testowe.json`. Dopisz ID klienta testowego do
`MULTI_CONSULTANT_ORDER_CLIENT_IDS` (workflow „Coolify set env”, `redeploy=false`,
potem jeden zwykły deploy) — bez tego M07 nie przetestuje zamówień wielo-konsultantowych.

## 5. Budżet AI — stan wyjściowy

```bash
curl -fsS -H "Authorization: Bearer $TOK" https://api.nexus.dynaminds.pl/api/settings/ai | jq '.features[] | {feature, enabled, monthly_limit, used: .usage_this_month}'
```

Zapisz do `wyniki/F0/ai-przed.json`. Jeśli któraś funkcja ma `used ≥ 0.8 × monthly_limit`,
zdecyduj z człowiekiem: podnieść limit na czas UAT czy pominąć scenariusze AI tej funkcji.

## 6. Katalog wyników

```bash
mkdir -p docs/uat/wyniki/F0 && grep -q 'docs/uat/wyniki/' .gitignore || echo 'docs/uat/wyniki/' >> .gitignore
```

`wyniki/` nigdy nie trafia do repo. Jeśli wyniki mają być współdzielone między
maszynami — zsynchronizuj katalog prywatnym kanałem (dysk firmowy), nie przez git.

## 7. Lista „gotowe do Fali 1”

- [ ] §1 decyzje wpisane do `manifest.yaml`
- [ ] `/api/health` bez `degraded` **albo** `traffit = degraded` z zapisanym powodem i decyzją
- [ ] `/api/health/deep` zielony
- [ ] backup drill zielony **albo** zapisany jako blocker startu produkcyjnego z właścicielem i terminem
- [ ] Sentry baseline zapisany
- [ ] `tested_sha` wpisany, main zamrożony (komunikat do zespołu)
- [ ] `state.json` zapisany, lista person gotowa
- [ ] dane testowe założone, klient testowy w `MULTI_CONSULTANT_ORDER_CLIENT_IDS`
- [ ] `ai-przed.json` zapisany
