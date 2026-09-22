# NEXUS — błędy i powiadomienia, 22.09.2026

## Potwierdzone przyczyny

| Obszar | Dowód produkcyjny | Stan naprawy |
|---|---|---|
| Poczta systemowa | `m365_mail=degraded`; heartbeat z 08:28:48 UTC: `http_403`, 76 prób / 76 niepowodzeń, `pending_retry=4`, `ready_candidates_upper_bound=3`, `uncertain=0`. | Wymaga operacji Exchange oraz zmiany nadawcy. Kod obwodu ponowień jest już wdrożony. |
| Podwójne powiadomienia Sentry | R3 `593111`, pomimo nazwy „5xx escalation”, ma `Any event` i identyczne warunki oraz odbiorców jak R6 `593061` dla backendu. | R3 wyłączona w panelu 22.09; potwierdzono komunikat `This alert is disabled`. R6, Teams oraz właściwa detekcja 5xx w Grafanie pozostają aktywne. |
| Błędy sieciowe podczas wdrożenia | FE-X `148499419`, 21.09 20:48:15 UTC, `GET /api/calendar/events`; niezależna sonda tego wdrożenia wykazała 78 s przerwy API i odpowiedzi 502/503. | Potwierdzona przerwa w aktualnym procesie Compose. Nie jest usunięta przez zmianę alertów ani telemetrii. |
| Utrata diagnostyki Reacta | FE-Y `148541928`, `/kariera/:rest*`, jedyny frame `onRecoverableError`; treść zawiera tylko `Error (private details omitted)`. | Poprawka zachowuje wyłącznie bezpieczny numer błędu Reacta, z odrębną klasyfikacją hydracji i odzyskiwalnego renderowania. Nie dowodzi to naprawy źródła błędu strony. |
| Błędna klasyfikacja lokalnych wyjątków mutacji | FE-S `148400451`: `server / MUTATION / unknown`, bez statusu HTTP. Reporter klasyfikował każdy zwykły `Error` mutacji jako awarię serwera i zastępował jego stack. | Poprawka raportuje klasę `client`, zachowuje oczyszczone źródło stosu i numer Reacta, nie dodaje fikcyjnych tagów HTTP. Raportowanie wszystkich końcowych niepowodzeń zapisów pozostaje aktywne. |

Liczników `pending_retry` i `ready_candidates_upper_bound` nie sumować: zbiory mogą się nakładać. Najstarsza odroczona próba ma wiek `9756389` sekund. Nie kasowano ani nie resetowano powiadomień.

## Stan monitoringu

Grafana: 11 reguł, 10 w stanie Normal, jedna Firing — `NEXUS system mail delivery unhealthy`, UID `efyxdf63jqltsc`. Odczytano agregację `max(max_over_time(... [3m]))`, pending 1 min, powtórzenie 30 min, No Data oraz Error = Alerting. Alarm odpowiada trwającej awarii 403; nie został wyciszony.

Sentry: w ostatniej dobie odczytano 8 nierozwiązanych issue backendu oraz 13 frontendu. Same statusy issue nie dowodzą występowania defektu w aktualnym wydaniu. Dzienny monitor [35605253349](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35605253349) odczytał oba projekty; Teams przyjął raport. To nie jest dawny problem braku tokena.

Pozostał alert o wyczerpaniu limitu Replay. Nie zmieniono opłat ani próbkowania bez przypisania zużycia do projektów; limit Replay nie jest dowodem zatrzymania odbioru zdarzeń błędów.

## Istniejące poprawki aplikacji

- Champion: ostatni odczytany `BadRequestError` BE-3W pochodzi z `5e91da98`, 21.09 13:07:56 UTC. Poprawka [#1640](https://github.com/B2B-net-S-A/NEXUS/pull/1640), `809345e6`, normalizuje parametry każdego wybranego modelu i jest w sprawdzonym wydaniu produkcyjnym. 71 skupionych testów parsowania/modeli przeszło lokalnie. Nie wykonano nowej produkcyjnej operacji importu.
- Generator CV: ostatnie zdarzenie FE-R, 21.09 21:41 UTC, dotyczy `70e3d87b`, sprzed poprawki [#1668](https://github.com/B2B-net-S-A/NEXUS/pull/1668), `b21fb0ef9`. Poprawka usuwa pętlę zmiany domyślnego trybu przy odświeżeniu listy rekrutacji; jest w sprawdzonym wydaniu. Istniejący test regresji przeszedł. Nie oznaczono issue jako naprawionego tylko na podstawie jego wieku.
- Poczta: 33 skupione testy trwałego obwodu ponowień, health i monitora przeszły. Ponawiany ten sam 403 nie tworzy nowego zdarzenia Sentry przy każdej próbie. Nie wysłano nowej sondy pocztowej.

## Pozostałe operacje produkcyjne

[Audyt nadawcy 35704456657](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35704456657) z 22.09 potwierdził, że aplikacja nadal ma jako nadawcę osobistą skrzynkę Artura, a nie przygotowaną `nexus-powiadomienia@b2bnetwork.pl`. Audyt niczego nie wysłał. Potrzebne jest osobno zatwierdzone, ograniczone do dedykowanej skrzynki `Application Mail.Send`, odczyt zapisanych uprawnień, przełączenie nadawcy, jedna kontrolna dostawa i naturalne odzyskanie wysyłki. Nie rozszerzać grupy odczytu zamówień ani praw do osobistej skrzynki.

[Deploy 35652782635](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35652782635) potwierdza przerwę z FE-X. [Audyt konfiguracji 35705713397](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35705713397) potwierdził Coolify 4.1.2. W tej wersji ścieżka Compose zatrzymuje stare kontenery przed uruchomieniem nowych. Usunięcie przerwy wymaga przygotowania i sprawdzenia zmiany cyklu życia usług, obejmującej bazę, migracje, singletonowe zadania i rollback. Zmiana filtrów Sentry nie rozwiąże niedostępności.

## Kryteria zamknięcia

Weryfikacja lokalna poprawki telemetrii: 34 skupione testy oraz ukierunkowany TypeScript przeszły; `git diff --check` czysty. Lokalny cache zależności ma Vitest 3.2.6, podczas gdy lockfile wymaga 5.0.1. Pełny lokalny TypeScript zgłasza niezwiązane braki/stare zależności (`react-grid-layout`, `pdfjs`, Tiptap); wymagane CI instalujące dokładny lockfile pozostaje bramką wdrożenia. Nie używano lokalnego Dockera.

1. Wymagane CI, merge i zgodny SHA API oraz frontendu dla poprawki telemetrii; health/deep/Alembic odczytane osobno.
2. Diagnostyka zachowuje numer Reacta oraz oczyszczone źródło lokalnego wyjątku; wiadomości, parametry URL, dane kandydatów i treści odpowiedzi nie trafiają do Sentry.
3. Wysyłka ma potwierdzoną dostawę, naturalny sukces aplikacji, `uncertain=0`, brak zaległych kwalifikujących się prób i `alarm=0`; Grafana wraca do Normal.
4. Przerwa podczas wdrożenia ma osobny pomiar po rzeczywistej zmianie procesu. Zielony deploy potwierdza odzyskanie poprawnej wersji, a nie ciągłość ruchu.

Do spełnienia tych kryteriów nie należy deklarować wszystkich problemów jako rozwiązanych.
