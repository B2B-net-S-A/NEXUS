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

**Stan 2026-09-13:** wszystkie pozycje zdrowe (Traffit wrócił do `healthy` po zmianie z 11.09 —
błędy wierszy faz wzbogacania są doradcze). Jeśli `traffit = degraded` wróci, sprawdź powód:
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

Stan 2026-09-13: `failure` co tydzień od co najmniej 17.08. Powód z logu: krok „Not configured —
drill cannot run”. Zmienne repo `BACKUP_S3_BUCKET/ENDPOINT/REGION/PREFIX/PROVIDER` SĄ ustawione
(27.07), ale **brakuje trzech sekretów**: `BACKUP_AGE_PRIVATE_KEY` (osobny klucz „drill”, NIE klucz
główny), `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY` (klucz aplikacyjny Backblaze B2 z prawem
odczytu bucketu `dynaminds-nexus-offsite`). Agent tego nie zrobi — to poświadczenia. Do zrobienia przez człowieka:

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

Oczekiwane: `success` **i pełny zakres**. Stan 2026-09-13: „zielony” każdej nocy, ale log mówi
„E2E CZĘŚCIOWE — 13 z 83 przypadków (1 z 14 plików)”: brak sekretów `E2E_USER_EMAIL`/`E2E_USER_PASSWORD`,
więc projekt `setup` się pomija i nic po zalogowaniu nie jest sprawdzane. **Zielony wynik nie jest
dowodem.** Sprawdzaj zakres komendą:

```bash
RID=$(gh run list --workflow e2e.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view "$RID" --log | grep -E 'E2E CZĘŚCIOWE|[0-9]+ passed'
```

Do zrobienia przez człowieka: dedykowane konto testowe z hasłem (w `PASSWORD_LOGIN_BREAK_GLASS_EMAILS`,
jeśli logowanie hasłem jest wyłączone) + sekrety repo `E2E_USER_EMAIL`, `E2E_USER_PASSWORD`.

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
- [ ] `/api/health` bez `degraded` (2026-09-13: ✅)
- [ ] `/api/health/deep` zielony
- [ ] backup drill zielony **albo** zapisany jako blocker startu produkcyjnego z właścicielem i terminem
- [ ] Sentry baseline zapisany
- [ ] `tested_sha` wpisany, main zamrożony (komunikat do zespołu)
- [ ] `state.json` zapisany, lista person gotowa
- [ ] dane testowe założone, klient testowy w `MULTI_CONSULTANT_ORDER_CLIENT_IDS`
- [ ] `ai-przed.json` zapisany

## 8. Wynik wykonania — 2026-09-13 (agent, sesja admina)

| Punkt | Wynik |
|---|---|
| §2.1 `/api/health` | ✅ `healthy`, SHA `ab10c8b`, żadnej pozycji `degraded` |
| §2.1 `/api/health/deep` | ✅ `healthy`, zero niezdrowych checków |
| §2.2 backup drill | ❌ **BLOCKER** — brak 3 sekretów (patrz §2.2); do zrobienia przez człowieka |
| §2.3 Sentry baseline | ⏸ nie wykonano — brak narzędzia Sentry w sesji agenta; `sentry-daily-monitor.yml` zielony |
| §2.4 nocny Playwright | ⚠️ zielony, ale 13/83 przypadków — brak sekretów E2E; do zrobienia przez człowieka |
| §2.5 SHA | `ab10c8b` na prodzie = `origin/main` (przed merge planu UAT) — **zamrożenie niewprowadzone**, wymaga komunikatu do zespołu |
| Traffit | ✅ `__daily__` i `__full__` `ok` (13.09 04:01 UTC), kwarantanna 0; faza `candidates_enrich_names`: 1 błąd wiersza (doradczy) |
| Poczta zamówień | ✅ włączona, co 60 min, auto-zapis włączony, brak biegu w toku |
| Workflowy | ✅ uptime-probe, disk-alert, sentry-daily-monitor, deploy; ⚠️ `coolify-queue-maintenance.yml` czerwony od 16.07 (nieużywany? do sprawdzenia) |
| Uprawnienia sekcji | odczytane (`revision 4`) — różnią się od pierwotnej wersji macierzy; `03-macierz-rol.md` poprawiony |
| Limity AI | wszystkie funkcje włączone, `monthly_limit = 0` (bez limitu) — budżet UAT pilnuje wyłącznie dyscyplina kart, nie system |
| Persony | wybrane konta z jedną rolą (ID w `wyniki/F0/persony.md`, lokalnie); **brak aktywnego konta roli `user`** — scenariusze USR = SKIP |
| Dane testowe | ✅ D1–D12 założone (poniżej); ⏸ `MULTI_CONSULTANT_ORDER_CLIENT_IDS` nieustawione — przed P3 wg `02-dane-testowe.md` |

**Dane testowe (fikcyjne, bezpieczne do publikacji):** klient D1 `64636` (DL 30 przypisany), klient D2
`64637` (bez DL), rekrutacja D3 `603652` (u D1, Champion D10 zapisany, must Python/PostgreSQL/Docker,
160 PLN/h), rekrutacja D4 `603653` (u D2), kandydaci D5 `502836`, D6 `502837`, D7 `502838`, D8 `502839`,
D9 `502840` (bez CV), karta klienta D11 (D1, v1), reguła CV D12 (D1, zatwierdzona, `CV_{IMIE_NAZWISKO}`).

**Obserwacje z Fali 0 (wejście do Fali 1, nie zgłoszenia):**
1. Wszystkich 9 Delivery Leadów ma przypisanych wszystkich klientów → w praktyce każdy DL widzi kwoty
   każdego klienta. Decyzja produktowa, czy tak ma zostać.
2. Rola HoR nie ma sekcji Delivery, choć kod zamówień przewiduje dla niej akcje cyklu życia
   (`_ORDER_LIFECYCLE_ROLES`) — karta M07 S09 to weryfikuje.
3. Wgranie CV do kandydata o innym nazwisku kończy się decyzją `inconclusive` i profil po cichu
   się nie uzupełnia; nadpisanie decyzji zwraca 409 („no confirmed identity mismatch to override”).
   Karta M01 powinna sprawdzić, czy użytkownik widzi, że CV nie zasiliło profilu.
4. **Do odtworzenia w Fali 1 (M01, możliwy błąd P1/P2):** po poprawieniu nazwiska wgrano nową wersję
   CV (inny SHA) kandydatom D5 `502836` (dokument `109439`) i D7 `502838` (dokument `109440`). Decyzja
   tożsamości zapisała się jako `confirmed_match`, ale profil NIE został uzupełniony (brak umiejętności
   i doświadczenia, `cv_extracted_data` puste, `updated_at` bez zmian) — także po 15 minutach. Te same
   pliki z tego samego generatora u D6 i D8 zasiliły profile w ~40 s. Ścieżka w kodzie, która
   zapisuje recenzję i kończy bez aktualizacji, to gałąź „nowszy dokument główny”
   (`_enrich_candidate_from_document_task`); bez logów nie da się rozstrzygnąć, czy to ona.
   Skutek dla danych testowych: D5 i D7 nie mają umiejętności, więc scenariusze M02 oczekujące
   D5 w rankingu dla D3 opierają się na D6/D8, dopóki ten punkt nie zostanie wyjaśniony.
