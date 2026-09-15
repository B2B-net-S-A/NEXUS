# Zewnętrzny monitoring dostępności (Grafana Synthetic Monitoring)

Stan na 15.09.2026. Konto: Grafana Cloud `arturt96`.

## Konfiguracja docelowa

| Nazwa checku | URL | Warunek sukcesu | Lokalizacje | Częstotliwość |
|---|---|---|---|---|
| `nexus-login-http` | `https://nexus.dynaminds.pl/login` | HTTP 2xx, podążanie za przekierowaniami | Frankfurt, Paris | 60 s |
| `nexus-api-live-http` | `https://api.nexus.dynaminds.pl/api/health/live` | HTTP 2xx i body zawiera `alive` | Frankfurt, Paris | 60 s |

Oba checki wysyłają `User-Agent: dynaminds-smoke-test/1.0`. Walidacja body
drugiego checku używa wyrażenia `alive` z odwróceniem warunku, więc brak tego
tekstu powoduje niezaliczenie wykonania.

Docelowy alert: dwa kolejne nieudane sprawdzenia, powiadomienie pocztą i do
Microsoft Teams oraz powiadomienie o powrocie. Test kontaktu ma być wykonany
bez wyłączania produkcji.

## Stan uruchomienia

- `nexus-login-http` (ID `89783`) jest aktywny: 60 s, Frankfurt i Paris. Test
  przed zapisem był zielony w obu lokalizacjach.
- `nexus-api-live-http` przeszedł test w obu lokalizacjach z walidacją body,
  ale nie został zapisany. Grafana odrzuciła zapis komunikatem
  `check executions quota exceeded (current: 86400, max: 100000)`.
- Wymagana konfiguracja zużywa 172 800 wykonań miesięcznie. Limit obecnego
  planu to 100 000; bez zmiany planu najbliższa konfiguracja mieszcząca się w
  limicie to oba checki co 2 minuty (86 400 wykonań miesięcznie).
- Istniejący punkt kontaktu `artur-email` jest domyślną trasą. Nie ma punktu
  kontaktu Teams. Alertów dla nowych checków ani testu kontaktu nie aktywowano.

MON-05 pozostaje **ZABLOKOWANE** do decyzji właściciela o interwale 2 minuty
albo płatnym planie oraz do bezpiecznego dostarczenia webhooka Teams i zgody na
aktywację powiadomień. Po domknięciu wymagane jest jeszcze co najmniej 1 h
zielonej obserwacji obu checków.
