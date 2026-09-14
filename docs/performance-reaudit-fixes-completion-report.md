# Poprawki po reaudycie wydajności z 14.09.2026 — raport wykonania

**Źródło:** [reaudyt](performance-and-availability-reaudit-2026-09-14.md) (Codex) po
[PR #1502](https://github.com/B2B-net-S-A/NEXUS/pull/1502). Poprzedni raport:
[stabilizacja bez zmiany architektury](performance-stabilization-completion-report.md).

## Weryfikacja reaudytu

Wszystkie siedem nowych ustaleń potwierdzono w kodzie `2c00f7cb` (identyczny wykonawczo
z produkcyjnym `6504fef5`). Trzy są regresjami z PR #1502 (R01, R02, R03). R03
odtworzono na produkcji: po kliknięciu „Źródła” i doczytaniu danych nagłówek sekcji
był 3180 px pod ekranem. Dwa priorytety obniżono z P1 do P2: R04 i R05 nie są
regresjami, a R05 było wcześniej gorsze (każdy oczekujący liczył snapshot sam).

**Dowód ważniejszy od ustaleń kodu:** oba zarejestrowane 503 frontendu wypadły w trakcie
deployów, które zakończyły się sukcesem.

| Sonda z 503 (UTC) | Deploy w toku (UTC) |
|---|---|
| 06.09 18:13:14 | 18:08:52 – 18:13:37 |
| 08.09 06:21 | 06:17:24 – 06:22:17 |

W dniach 31.08–11.09 było 81 przebudów produkcji w godzinach pracy (do 17 jednego dnia).
Poprzedni raport przypisał te 503 wyścigowi Dockera „No such container” — logi tego nie
potwierdzają dla tych dat; to okna deployu.

**Korekty poprzedniego raportu:** model ruchu tła bezczynnego dashboardu to 1,8–2,0
GET/min na kartę, nie ~1,5. Obsługa `Retry-After` z #1502 była martwym kodem (CORS nie
wystawia nagłówka) i została usunięta. Zmiana filtra Sentry z #1502 nie obejmowała
błędów obsłużonych przez react-query.

**Nieudany deploy `2c00f7cb` (13.09 23:08 UTC):** Coolify nie wykonał `git ls-remote`
przez SSH (exit 128, bez treści błędu w logu). Klucz wdrożeniowy repozytorium istnieje,
a ta sama konfiguracja zadziałała 2,5 h wcześniej. Produkcja została na `6504fef5`
(zmiana dotyczyła tylko dokumentacji). Merge tego PR-a pokaże, czy problem wraca.

## Co zmieniono

| Ustalenie | Zmiana | Test |
|---|---|---|
| R01 KPI HoR gubi osoby wieloról | `team_kpis(operational_roles_only=False)` dla rosteru; brak wiersza osoby z rosteru = sekcja `partial` | `test_perf_reaudit_backend.py` (DB), `test_dashboard_v2.py` (+2) |
| R02 dzwonek po zerwaniu WS | `onopen` po zerwaniu odświeża powiadomienia i KPI | `useNotifications.test.tsx` |
| R03 kotwica Insights | `lib/anchor-pin.ts`: przypięcie celu przez 12 s lub do akcji użytkownika; kliknięcie, `#hash`, Wstecz/Dalej | `anchor-pin.test.ts` |
| R04 upload w całości do RAM | `_read_upload_bounded` (limit + 1 bajt) na trzech trasach uploadu | `test_candidates_from_cv_tempfile.py` (+1) |
| R05 połączenie trzymane podczas czekania | `release_idle_connection`; `cache_single_flight(db=)` zwalnia przy kontencji; przed rerankiem w podglądzie CV | `test_perf_reaudit_backend.py` |
| R06 retry i fallback | usunięte dwa lokalne `retry: 1` i martwy `Retry-After`; rozrzut ponownego łączenia 50–100%; fallback pomija ukrytą kartę | `QueryProvider.test.tsx` (strażnik), `useNotifications.test.tsx` |
| R07 telemetria | `lib/query-error-telemetry.ts` w QueryCache/MutationCache (sieć/timeout/5xx, 10%, deduplikacja); ChunkLoadError próbkowany 5% | `query-error-telemetry.test.ts` |
| F07 N+1 Delivery Lead | `_serialize_demands`: stała liczba zapytań zamiast ~5 na demand (plus cały plan per wiersz na dashboardzie DL) | `test_perf_reaudit_backend.py` (liczba zapytań + parytet) |

## Świadomie poza zakresem

- **Bezprzerwowy deploy (F03)** — teraz z twardym uzasadnieniem w danych; wymaga decyzji
  i pracy w Coolify (osobne aplikacje FE/API). Do tego czasu: merge poza godzinami pracy.
- **Wydzielenie workera (F02), budżet pul (F06), readiness (F11), testy 50/100 (F12).**
- **Limit ciała żądania przed handlerem** i kolejka ciężkich importów/eksportów (R04, F05).
- **Pomiar faz startu** i przeniesienie napraw danych z entrypointu (F04).

## Kroki ręczne (nadal niewykonane)

1. Sekret `SENTRY_AUTH_TOKEN` w GitHub Actions — nadal go brak.
2. `COMPOSE_PROFILES=observability` + `GRAFANA_LOKI_*` przez workflow „Coolify set env”.
3. Zewnętrzny monitor co 1 min na `/login` i `/api/health/live` z alertem do właściciela.
4. Konfiguracja backup restore drill.

## Runda 3 — po reaudycie v2 (14.09.2026, druga kontrola)

**Źródło:** [reaudyt v2](performance-and-availability-reaudit-2026-09-14-v2.md). Potwierdzono:
deploy #1509 dał ~105 s 503 na froncie i ~52 s 502/503 na API przy zielonym workflow;
N01 i N02 są realne (N02 bez aktywnego wpływu na obecne wywołania). Dodatkowe ustalenie:
frontend leżał dwa razy dłużej, bo w `docker-compose.yml` czekał na zdrowy backend.

| Zmiana | Plik | Test |
|---|---|---|
| Pomiar przerwy widzianej przez użytkowników w każdym deployu (sonda co ~2 s, tabela w podsumowaniu, `::notice::`) | `.github/workflows/deploy.yml` | skrypty obu kroków uruchomione lokalnie z atrapą curla |
| Frontend bez `depends_on: backend` — odtwarza się niezależnie od migracji backendu | `docker-compose.yml` | `test_delivery_contract.py` (kontrakt odwrócony) |
| Czas faz startu backendu i podfaz siatki DDL w logach (`[startup-timing]`) | `backend/entrypoint.sh` | `bash -n`, testy luster entrypointu |
| Jednorazowe przeładowanie po ChunkLoadError | `lib/chunk-reload.ts`, `ChunkReloadGuard.tsx`, `app/error.tsx` | `chunk-reload.test.ts` |
| N01: sprzątanie blokady także przy anulowaniu w trakcie oddawania sesji | `core/cache.py` | `test_perf_reaudit_backend.py` (pada na poprzednim kodzie) |
| N02: helper odmawia po `flush()` i po instrukcji innej niż SELECT | `core/database.py` | `test_perf_reaudit_backend.py` (pada na poprzednim kodzie) |

**Oczekiwany efekt do potwierdzenia pomiarem:** krótsza przerwa frontendu (tylko jego własny
restart zamiast czekania na migracje backendu). Przerwa API się nie zmienia — jej fazy pokaże
`[startup-timing]`. Pierwszy deploy z tą zmianą da obie liczby w podsumowaniu biegu.

**Świadomie poza zakresem:** bezprzerwowy deploy (rozdzielenie FE/API w Coolify z rolling
update i blokadą lidera dla pętli tła), przywrócenie stagingu, testy 50/100.

