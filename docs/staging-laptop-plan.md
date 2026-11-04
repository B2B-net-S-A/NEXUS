# Staging NEXUSA na laptopie i jedno wdrożenie dziennie — plan

Stan: plan zaakceptowany 22.10.2026. Etap 1 w kodzie: `docker-compose.staging.yml`,
`backend/app/core/staging.py`, `scripts/staging/`. Opis obsługi:
`docs/claude/podstawy/staging-na-laptopie.md`.

## Cel

- Na laptopie działa stały staging NEXUSA: ten sam kod, schemat i konfiguracja co
  produkcja, na pełnej kopii danych produkcyjnych.
- Claude i Codex budują i testują wszystko lokalnie, także testy z Postgresem.
- Produkcja dostaje jedno wdrożenie dziennie, około 18:05, i tylko commit, który
  przeszedł staging. Okno 18:00–08:00 zostaje na ponowienie tej samej wersji albo rollback.

## Decyzje podjęte 22.10.2026

| Decyzja | Wybór |
|---|---|
| Lokalny Docker | zakaz zdjęty całkiem (hook `no-local-docker.js` powstał dla MacBooka Air 24 GB; laptop to M5 Max, 128 GB, 3,2 TB wolnego) |
| Dane na stagingu | pełna kopia produkcji |
| Kolejność | najpierw ten plan, potem kod |

## Założenia, które różnią ten plan od propozycji Codexa

1. **Gałęzią integracyjną jest `main`.** Kolejka merge'ów już sprawdza zmiany razem,
   a produkcja i tak jest za `main` (okno wdrożeń). Staging idzie za `main`, a laptop
   oznacza SHA, który przeszedł. Nie ma osobnej gałęzi paczki ani ręcznego zamrażania.
2. **Na start Coolify dalej buduje obrazy, tylko z certyfikowanego SHA.** Laptop to ARM,
   produkcja x86, a front ma `NEXT_PUBLIC_*` wpisane w build (`frontend/Dockerfile:22–34`).
   Przenoszenie obrazów to osobny, późniejszy etap (6).
3. **Bez self-hosted runnera GitHuba na laptopie.** Repo jest publiczne, a runner
   uruchamiałby kod z obcych PR-ów na komputerze z kluczami SSH do produkcji. Laptop
   sprawdza wszystko sam i wystawia tylko commit status przez `gh api`.
4. **Jeden Postgres i jeden Qdrant na laptopie, bazy per worktree.** Agent nie stawia
   własnego stosu, tylko dostaje bazę `nexus_<worktree>` z szablonu.

## Układ

```
origin/main ──(po każdym merge'u)──▶ laptop: nexus-staging (rebuild, smoke, E2E)
                                          │
                       ok. 17:00 ostatni zielony SHA → commit status staging/verified
                                          │
serwer: budzik deploy-window 18:05 ──▶ Deploy wdraża tylko SHA z staging/verified
```

| Element | Co |
|---|---|
| Stos `nexus-staging` | Dockerfile'e z produkcji, `docker-compose.staging.yml` obok `docker-compose.e2e.yml` (tamten zostaje do jednorazowych testów), trwałe wolumeny, Postgres 16, Qdrant, Mailpit, lokalny S3 (versitygw — MinIO nie wydaje już obrazów) |
| Adres | front `http://localhost:3100`, API `http://localhost:8100`, poczta `http://localhost:8125` — tylko na 127.0.0.1; znacznik „STAGING” w rogu i w tytule karty. HTTPS (mkcert) niepotrzebny: `localhost` jest dla przeglądarki bezpiecznym kontekstem |
| Logowanie | hasłem (`PASSWORD_LOGIN_ENABLED`), bo SSO Microsoftu wymaga adresu zwrotnego zarejestrowanego w Entra |
| Dane | odtwarzane z kopii offsite (`backup/backup.sh`: pg_dump + uploady + snapshot Qdranta, age, S3) po nocnym backupie |
| Wyjście na świat | `NEXUS_ENV=staging` — domyślnie wyłączone wszystko, co pisze poza laptop |

## Pełna kopia produkcji: co trzeba zrobić, żeby była bezpieczna

Pełna kopia ma prawdziwe dane osobowe i stan integracji. Bez poniższych kroków staging
zacząłby wysyłać maile do kandydatów, odnawiać subskrypcje M365 i pisać do Compassa.

1. **Odtworzenie z backupu offsite.** Skrypt
   `scripts/staging/restore_from_backup.sh` pobiera ostatni zestaw z S3 (rclone),
   odszyfrowuje kluczem prywatnym age z pęku kluczy macOS i odtwarza Postgresa,
   uploady i Qdranta. Produkcja nie dostaje żadnego dodatkowego obciążenia, a przy okazji
   każdego dnia sprawdzamy, że backup naprawdę daje się odtworzyć (dziś robi to tylko
   `backup-drill.yml`).
   Alternatywa zatwierdzona przez Artura 22.10.2026: świeży `pg_dump` przez SSH
   (`scripts/staging/clone_from_hetzner.py`) do prywatnego katalogu, a następnie
   odtworzenie i sanitizacja w nowej lokalnej bazie `nexus_staging_*`. Nie wymaga
   klucza age. Ten wariant kopiuje tylko PostgreSQL, nie pliki ani Qdranta.
2. **Inne sekrety niż na produkcji.** Własny `SECRET_KEY`/klucz JWT, inne klucze
   szyfrowania tokenów: zapisane w bazie tokeny OAuth i sesje stają się nieczytelne.
3. **Sanitizacja po odtworzeniu** (`scripts/staging/sanitize.sql`, test sprawdza listę
   tabel): kolejki wysyłek (`notification_email_outbox`, kolejka kontaktu z kandydatem,
   maile odrzuceń), subskrypcje webhooków M365, kursory synchronizacji, zadania w toku,
   klucze API kont serwisowych.
4. **Pętle w tle domyślnie wyłączone.** W `backend/app/main.py` startuje dziś
   ok. 90 zadań (`asyncio.create_task`, linie 848–990). Przy `NEXUS_ENV=staging`
   działa tylko jawna lista dozwolonych (wewnętrzne przeliczenia, retencja, indeks).
   Test pada, gdy w lifespanie pojawi się zadanie bez wpisu „wolno / nie wolno”, więc
   nowa pętla nie zacznie po cichu wysyłać ze stagingu.
5. **Klienci zewnętrzni zablokowani na poziomie HTTP.** Wspólny transport `httpx` przy
   `NEXUS_ENV=staging` odrzuca hosty spoza listy (Graph, CloudTalk, KSeF, JJIT,
   Compass, Slack, Autenti…). Poczta idzie do Mailpita. AI (Anthropic, Voyage) zostaje
   włączone, bo bez niego większość ścieżek nie da się sprawdzić.
6. **Laptop jako miejsce przetwarzania danych.** FileVault jest włączony (sprawdzone
   22.10). Wolumeny stagingu wyłączone z Time Machine i iCloud. Wpis w rejestrze
   czynności przetwarzania to sprawa Artura, nie kodu.

## Praca agentów

- Każdy worktree dostaje bazę `nexus_<worktree>`: `CREATE DATABASE … TEMPLATE nexus_seed`.
  `nexus_seed` = kopia produkcji po sanitizacji. Rozmiar bazy produkcji niepotwierdzony;
  sprawdzić w etapie 1, czy kopia z szablonu zajmuje sekundy czy minuty.
- Uploady: wspólny katalog tylko do odczytu + katalog zapisu per worktree. Qdrant:
  prefiks kolekcji per worktree.
- pytest z Postgresem lokalnie na bazie testowej per worktree (nie na kopii produkcji).
- Do zmiany w instrukcjach: `CLAUDE.md` repo („Lokalnie bez Dockera”),
  `~/.claude/rules/common/testing.md` (sekcja „Bez Dockera”), `AGENTS.md` dla Codexa.
  Nowa meta zadania w dzień: „PR w kolejce + zielone na stagingu”.

## Jedno wdrożenie dziennie

- Dziś (`.github/workflows/deploy.yml`): cron 16:23–21:23Z i 04:23Z oraz budzik
  `deploy-window` 18:05, 20:05, 22:05. Każdy z nich może wdrożyć nowszy zielony `main`,
  a w weekend okna nie ma.
- Po zmianie: `select_release_sha.py` wybiera najnowszy SHA z commit statusem
  `staging/verified`, a nie najnowszy zielony `main`. Status wystawia laptop około 17:00.
  Kolejne sloty tej doby nic nie robią, bo produkcja ma już ten SHA (rebuild jest
  pomijany już dziś). Ta sama reguła w weekend.
- Brak certyfikatu (laptop uśpiony, staging czerwony) = brak wdrożenia tego dnia.
  „Wdróż teraz” od Artura (`emergency`) działa dalej bez laptopa.
- Uśpiony laptop: certyfikacja uruchamiana z `launchd`; budzenie (`pmset repeat`)
  ustawia Artur, bo to ustawienie systemu.

## Etapy

| # | Etap | Meta |
|---|---|---|
| 0 | Zdjęcie zakazu Dockera | hook wyrejestrowany w `~/.claude/settings.json`, reguły i `CLAUDE.md` zaktualizowane |
| 1 | Stos `nexus-staging` + `NEXUS_ENV=staging` (lista pętli, blokada HTTP, Mailpit) + odtworzenie z backupu + sanitizacja | staging z kopią produkcji działa pod `localhost:3100`; Mailpit i log blokady HTTP po godzinie pracy pokazują zero wyjść na świat; test listy pętli zielony |
| 2 | Staging idzie za `main` | po merge'u staging ma nowy SHA w `/api/health` w ciągu 15 min; smoke + krytyczne E2E po każdym rebuildzie |
| 3 | Bazy per worktree + nowe instrukcje dla Claude'a i Codexa | agent w nowym worktree przechodzi pytest z bazą lokalnie bez CI |
| 4 | Certyfikacja na sucho, tydzień | codzienny raport: który SHA laptop by certyfikował, który faktycznie wdrożono, co się różniło |
| 5 | Deploy tylko z `staging/verified` | przez tydzień jedno wdrożenie dziennie, `/api/health` = certyfikowany SHA |
| 6 | (opcjonalnie) obrazy z rejestru budowane w CI na x86, deploy bez rebuildu | wymaga runtime'owej konfiguracji frontu zamiast `NEXT_PUBLIC_*` z buildu |

## Wdrażanie wybranych zmian danych

Decyzja Artura z 22.10.2026: oprócz kodu i migracji mają być przenoszone także
jawnie wybrane dane biznesowe. Nie oznacza to synchronizacji całej lokalnej bazy
z produkcją. Punkt odniesienia zapisujemy przed edycją, paczka wskazuje konkretne
rekordy i pola, a świeży podgląd jest związany z bazą docelową i operatorem.
Zapis wymaga zatwierdzenia skrótu podglądu i ponownego sprawdzenia stanu pod
blokadą wierszy. Konflikt zatrzymuje całą transakcję; nowe dane produkcyjne nie
są zastępowane lokalnym dumpem. Dostępne pola i ograniczenia handlerów opisuje
`docs/staging-data-promotion-runbook.md`. Dane paczek pozostają poza Git i CI.

## Czego staging nie sprawdzi

SSO Microsoftu, webhooki przychodzące (M365, CloudTalk), prawdziwe wysyłki i integracje,
infrastruktura Coolify/Hetznera. Dlatego krótka weryfikacja na produkcji po wdrożeniu zostaje.

## Otwarte sprawy dla Artura

- Klucz prywatny age jest potrzebny do wariantu offsite; bez niego dostępny jest
  świeży zrzut PostgreSQL przez SSH. Nie zastępuje to testu odtworzenia backupu.
- Czy staging ma mieć SSO (nowy adres zwrotny w Entra) czy wystarczy logowanie hasłem.
- Budzenie laptopa przed 17:00 (`pmset`).
