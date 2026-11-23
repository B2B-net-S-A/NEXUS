# Porcja i „Nowi”: osoba wysłana w ostatnich 14 dniach do tego samego klienta idzie na początek kolejki jego innej rekrutacji
<!-- indeks: `known_queue_points.CLIENT_RECENT_DAYS` = 14, `CLIENT_RECENT_POINTS` = 20, `KnownFacts.client_recent_days` / `client_recent_job_id` / `client_recent_points`, `sent_before.sent_to_client_select`, `auto_full_review._sent_before_extras` (najpierw ten klient), pozycja kolejki `client_recent`, „Wysłany wczoraj do tego klienta: … Klient zna już to CV.”, „wysłany do tego klienta” w linii kolejności -->

Decyzja Artura z 22.11.2026 (R4 z raportu
https://claude.ai/artifact/Ec7UJD6UbQqwe4HgSiebZW).

## Dlaczego

- W 16–19.11 przepięcia między rekrutacjami jednego klienta to 41 ze 168
  wysłanych CV; 39 z nich to osoby wysłane wcześniej.
- 20.11 trzy osoby wysłane rano do 789224 poszły tego samego dnia do
  siostrzanej 789217. W 789217 stały na miejscach 545, 603 i 3 237 (od 65%
  ma tam 3 058 osób), więc wynik z CV ich nie wyróżniał, a dołożeni do puli
  to było 30 najlepszych z 1 752 „wysłanych wcześniej”.

## Jak działa

- **Fakt:** etap `cv_sent` w innej rekrutacji tego samego klienta w ostatnich
  `CLIENT_RECENT_DAYS` dniach (`known_queue_points.facts_for_jobs`). Osoba
  odrzucona przez tego klienta dalej nie dostaje żadnych punktów.
- **Kolejność:** `CLIENT_RECENT_POINTS` = 20 ponad wynik (stała, nie suwak),
  na Tablicy, w porcji i w dobieraniu. Łączy się z „u klienta” i „wysłany
  wcześniej”.
- **Pula:** `_sent_before_extras` bierze najpierw takie osoby (od 50%), potem
  resztę „wysłanych wcześniej” po wyniku, razem do `POOL_EXTRA`. Flaga
  `evidence.sent_before`, więc przycinanie po nowym CV ich nie wycina (#3722).
- **Porcja:** wchodzi od progu porcji jak inni (R3).
- **Karta porcji:** linia „Wysłany wczoraj do tego klienta: <rekrutacja>.
  Klient zna już to CV.” nad „Wysłany do klienta N×”; w linii kolejności
  „+ wysłany do tego klienta wczoraj”, ta sama etykieta w „Zadzwoń najpierw”
  na Tablicy (`knownFactLabels`).

## Czego nie robić

- Nie licz tu wysyłek do innych klientów (to `SENT_POINTS`) ani samego
  screeningu u tego klienta.
