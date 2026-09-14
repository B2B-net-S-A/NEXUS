# NEXUS — docelowe reguły alertów i ich odbiór

Ta specyfikacja zastępuje nieaktualny runbook deklarujący reguły, których panel nie realizował. Zapis w repozytorium NIE oznacza aktywowania alarmów.

Wspólny filtr Sentry: environment=production, projekty nexus-be/nexus-fe. Właściciel: artur.twardowski@b2bnetwork.pl. Pilne powiadomienia: kanał Teams „NEXUS — alerty” i e-mail właściciela. Plan Team bez zwiększania opłat.

| Detekcja | Warunek | Powtórzenie |
|---|---|---|
| Terminal failure | terminal=true; nowe issue, regresja lub kolejne zdarzenie końcowej awarii | najwyżej raz/30 min przy dalszych zdarzeniach |
| 5xx | >=5 błędów, >5% wszystkich odpowiedzi, >=20 żądań/5 min | 30 min |
| Zadania | brak sukcesu >2 interwały, wyłącznie zadania włączone | 30 min |
| Brak danych | zanik strumienia/sam monitor niedostępny | alarm operacyjny |
| Nowy defekt FE/BE | nowe/regresyjne issue poza oczekiwanymi odmowami | triage |

R1 (593116) dotyczy ATLAS — pozostawić. Nie przepinać go pod NEXUS. Zastępujące reguły sprawdzić przed wyłączeniem dublujących się R2–R6/high-priority. Nie odrzucać globalnie 503/HTTPException ani wszystkich awarii Anthropic.

## Liczniki pełnego ruchu w Loki

Middleware emituje `event_kind=http_outcome`, `route` (szablon, nie URL z tokenem), `method`, `status_code`, `duration_ms`, `request_id`, `operation_id`. To pełne odpowiedzi z aplikacji, niezależne od samplingu Sentry. Błędy proxy przed aplikacją wymagają osobnego strumienia proxy i sondy zewnętrznej.

W istniejącym źródle Loki dla backendu NEXUS obliczyć:

- R = sum(count_over_time({app="nexus",service="backend"} | json | event_kind="http_outcome" [5m]))
- E = sum(count_over_time({app="nexus",service="backend"} | json | event_kind="http_outcome" | status_code >= 500 [5m]))
- Alarm: E >= 5 AND R >= 20 AND E / R > 0.05.

Rzeczywiste etykiety `service` i obecność strumienia muszą zostać potwierdzone w Grafanie; konfiguracja Alloy w repo nie dowodzi działającego odbioru. Dla braku danych skonfigurować stan No Data jako wymagający reakcji i potwierdzić niezależnym health probe.

## Ukończenie zadań

`event_kind=job_outcome` zawiera job, outcome, expected_interval_seconds i operation_id. Sukces oznacza zwalidowany wynik biegu, nie samo obudzenie pętli. Osobno monitorować włączenie zadania i brak wywołania; reset procesu nie może zerować wieku ostatniego sukcesu w historii Loki. Notes i Traffit są dzienne — nie używać częstotliwości sprawdzania harmonogramu jako częstotliwości wymaganych sukcesów.

Stan M365 wymaga rozróżnienia pojedynczych połączeń i ostatniego wyniku: udana skrzynka nie może ukryć niesprawnej. Przyrost notifications mierzyć po zatwierdzonych zapisach w DB; liczba wyjątków ani wywołań helpera nie jest równoważna liczbie INSERT-ów. Tych alarmów nie oznaczać jako odebrane bez potwierdzonego źródła i testu.

## Test odbiorowy

Sprawdzić kontrolowane zdarzenie bez danych prywatnych, wyzwolenie reguły, otrzymanie Teams i e-mail, brak duplikatu, recovery i No Data. Syntetyczne awarie procesów oraz danych wykonywać poza produkcją. Zdarzenie testowe w produkcji musi być jasno oznaczone i nie zmieniać rekordów biznesowych.

Filtry hydracji i ChunkLoadError wyłączyć dopiero po wdrożeniu scrubbingu. Replays session=0, onError=0.1. Po 7 dniach porównać budżet i użyteczność; nie zmieniać opłat automatycznie.
