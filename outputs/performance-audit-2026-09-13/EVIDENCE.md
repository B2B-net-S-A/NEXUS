# Dowody audytu NEXUS — 13.09.2026

Kod analizowany w izolowanym worktree: `ab10c8bba7e06e79a146f4dc48e6e70e168cf7f1`.
Brak zmian aplikacji, konfiguracji lub danych produkcyjnych. Wykonano odczyty HTTP, kodu, istniejących logów CI/deploy oraz uruchomiono istniejący read-only `Coolify Ops` z `action=list`.

## Zapisane pliki

- [public-probes.json](public-probes.json) — pierwsze odczyty sześciu URL-i, od 18:27:03 UTC; czas całego żądania z komputera audytora, statusy, wybrane nagłówki i odpowiedzi health.
- [probe-series.json](probe-series.json) — 12 rund, 18:28:20–18:30:15 UTC, po jednym kolejnym odczycie `/login` i `/api/health/live`; 24 HTTP 200, około 10 s przerwy między rundami. To sonda, nie test obciążeniowy.
- [deep-health.json](deep-health.json) — późniejszy odczyt poprawnie zdekodowanej gzip odpowiedzi `/api/health/deep`. Pierwszy prosty czytnik nie dekodował gzip; adnotacja w public-probes wyjaśnia to ograniczenie zapisu, nie błąd API.
- [uptime-history.json](uptime-history.json) — 100 ostatnich wyników Uptime probe od 05.09 do 13.09; 97 success, 3 failure. Nie przeliczać tego na uptime.
- [deploy-history.json](deploy-history.json) — 30 ostatnich wyników Deploy od 09.09 do 11.09; 29 success, 1 skipped. Nie jest to zapis czasów niedostępności podczas deploymentów.

## Logi workflow i ręcznie zweryfikowane fakty

| Źródło | Zaobserwowany wynik |
|---|---|
| [Coolify Ops 34774672219](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34774672219) | 13.09 18:27 UTC: kolejka `[]`, aplikacja `running:unknown`, skonfigurowany commit `HEAD`; brak metryk kontenerów w odpowiedzi |
| [Uptime 34051013024](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34051013024) | 06.09 18:13 UTC: frontend HTTP 503 |
| [Uptime 34194283592](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34194283592) | 08.09 06:21 UTC: frontend HTTP 503 |
| [Uptime 34203697193](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34203697193) | 08.09 08:17 UTC: frontend HTTP 200, failure dotyczył `voyage=unhealthy` |
| [Uptime 34773047014](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34773047014) | 13.09 17:55 UTC: frontend 200, API healthy na ab10c8bb; oddzielne warnings dla wyłączonych/nieznanych integracji |
| [Deploy 34621868326](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34621868326) | 11.09 16:30 UTC: healthy ab10c8bb, frontend 200, deep health healthy |
| [Sentry monitor 34756756967](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34756756967) | 13.09: status success, ale faktyczne ostrzeżenie `SENTRY_AUTH_TOKEN secret not set — skipping digest` |
| [E2E 34747273625](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34747273625) | 13.09: 13/83 przypadków, 1/14 plików, preview-chromium, brak konfiguracji konta; 13 passed z jednym workerem; brak uruchomionych authed flows |
| [Disk alert 34774255242](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34774255242) | 13.09 18:19 UTC: diskPercent=27, próg75; odczyt z /api/health, nie bezpośredni pomiar hosta |

Surowe logi nie są kopiowane do repo. Powyższe linki prowadzą do oryginalnych logów GitHub. Ich dostępność i retencja zależą od ustawień organizacji.

## Chrome i ograniczenia

W profilu Chrome Artur otwarto nową kartę NEXUS: zalogowany dashboard Admin Ops załadował dane i został sprawdzony wizualnie, następnie wykonano nawigację do kandydatów. Lista po załadowaniu pokazała 60 214 rekordów. Odczyt przechwyconych warning/error tej karty był pusty. Nie wykonywano zapisów biznesowych, nie pobierano CV, nie kopiowano tokenów. Nie wykonano pomiaru HAR/Web Vitals, czasu gotowości ani percentyli endpointów za logowaniem. Screenshot dashboardu był oglądany przez narzędzie, nie został zapisany w katalogu raportu.

Panel Coolify otworzył ekran logowania. Nie uzyskano historii OOM/restartów/healthchecków ani CPU/RAM/IO i aktywnych ustawień SQL. Status `running:unknown` z workflow nie zastępuje tych danych.

Użytkownik potwierdził: komunikat występuje podczas zwykłej pracy, bez konkretnej akcji. Nie podał czasu ostatniego epizodu. Historyczna przyczyna wszystkich zgłoszeń pozostaje nieustalona.
