# Zewnętrzny monitoring dostępności (Grafana Synthetic Monitoring)

Stan na 15.09.2026, 19:45 CEST. Konto: Grafana Cloud `arturt96`.

## Konfiguracja

| Nazwa checku | ID | URL | Warunek sukcesu | Lokalizacje | Częstotliwość |
|---|---|---|---|---|---|
| `nexus-login-http` | `89783` | `https://nexus.dynaminds.pl/login` | HTTP 2xx, podążanie za przekierowaniami | Frankfurt, Paris | 120 s |
| `nexus-api-live-http` | `89793` | `https://api.nexus.dynaminds.pl/api/health/live` | HTTP 2xx i body zawiera `"status":"alive"` | Frankfurt, Paris | 120 s |

Oba checki wysyłają `User-Agent: dynaminds-smoke-test/1.0` (reguła Cloudflare
dla sond zdrowia). Walidacja body drugiego checku to wyrażenie regularne
`"status":"alive"` z odwróconym warunkiem: brak tego tekstu w odpowiedzi
oznacza nieudane wykonanie.

### Dlaczego 120 s, a nie 60 s

Darmowy plan Grafana Cloud ma limit 100 000 wykonań miesięcznie. Dwa checki co
60 s z dwóch lokalizacji to 178 560 wykonań (31 dni), więc drugi check został
odrzucony komunikatem `check executions quota exceeded`. Przy 120 s oba checki
zużywają łącznie 89 280 wykonań. Zmiana planu nie była potrzebna.

## Alert

Per-check alert „Failed Checks” na obu checkach: **co najmniej 3 z 4 nieudanych
wykonań w ostatnich 5 min**. Grafana tworzy z tego regułę
`ProbeFailedExecutionsTooHigh [5m]` (folder `Grafana Synthetic Monitoring`,
grupa `Failed Checks [5m]`, ewaluacja co 60 s).

Próg wynika z interwału 120 s i dwóch lokalizacji:

- przerwa krótsza niż 2 min daje najwyżej jedno nieudane wykonanie na
  lokalizację, czyli najwyżej 2 łącznie — alert się nie uruchamia. Tak wyglądają
  zwykłe wdrożenia bez rolling update: w pomiarach 52–75 s dla API i do 105 s
  dla frontendu;
- awaria dłuższa niż 4 min daje co najmniej 2 kolejne nieudane wykonania
  w każdej lokalizacji — alert uruchamia się zawsze. Trzecie nieudane wykonanie
  przypada najpóźniej 4 min od początku awarii; z ewaluacją reguły i grupowaniem
  powiadomień wiadomość przychodzi po około 5–6 min;
- przy awarii trwającej 2–4 min alert uruchamia się, gdy jedna lokalizacja
  odnotuje dwa kolejne błędy, a druga co najmniej jeden.

Reguła liczy logi nieudanych wykonań. Brak takich logów to stan
`Normal (NoData)` — poprawny wtedy, gdy wszystko działa.

## Powiadomienia

- Trasa domyślna (default policy) prowadzi do punktu kontaktu `artur-email`
  (integracja e-mail). Ten sam punkt kontaktu obsługuje osiem wcześniejszych
  reguł alertów NEXUS opartych na logach (przypisanych do niego bezpośrednio).
- Powiadomienie o powrocie jest włączone („Disable resolved message” odznaczone).
- Test punktu kontaktu 15.09.2026 ok. 19:40 CEST: „Test notification sent
  successfully”.
- **Brak kanału Microsoft Teams.** Adres webhooka Teams jest poświadczeniem,
  dlatego dodaje go właściciel: Alerting → Contact points → `artur-email` → Edit →
  „Add contact point integration” → Microsoft Teams → wkleić adres webhooka
  Workflows kanału `NEXUS — alerty` → Test → Save. Dopisanie integracji do
  istniejącego punktu kontaktu kieruje do Teams także osiem wcześniejszych reguł.
  Jeśli ma to dotyczyć tylko sond, trzeba utworzyć osobny punkt kontaktu
  i politykę dopasowaną do etykiety `namespace=synthetic_monitoring`.

## Obserwacja

15.09.2026, 17:58–19:37 CEST: oba checki 100% uptime i 100% osiągalności,
wszystkie wykonania udane z obu lokalizacji, reguła alertu `health=ok`.

## Stan MON-05

Zaliczone poza kanałem Teams. Teams pozostaje **ZABLOKOWANE** do czasu dodania
webhooka przez właściciela (poświadczenie nie może trafić do czatu, repo ani
logów).
