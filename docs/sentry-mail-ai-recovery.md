# NEXUS — AI i systemowa wysyłka maili

## Zakres i kontrakty

Sonnet 5 i Opus od 4.7 nie otrzymują `temperature`, `top_p`, `top_k`, również
przez `extra_body`. Normalizacja następuje po wybraniu modelu każdej próby;
DeepSeek zachowuje obsługiwane parametry. Prompty, scoring i wybór modeli bez zmian.

App-only Graph ma trwały stan per nadawca/aplikacja/tenant w
`mail_delivery_state`; w kluczu jest SHA-256, w wartościach tylko liczniki,
kody i czas. Krótkie transakcje nie trzymają blokady podczas HTTP. Awaria
magazynu stanu wstrzymuje wysyłkę i zapala niezależny monitor.
403/401/token blokują ponawianie na 15 minut (401 ma wcześniej jedno
odświeżenie tokenu). Przejściowe awarie mają rosnący odstęp 60–900 s;
429 respektuje także dłuższy `Retry-After`. Tylko jeden worker dostaje próbę
odzyskania, a spóźniony sukces sprzed awarii jej nie zamyka.

Chat fallback zachowuje rekordy, limituje partię do 10 prób na przebieg,
sprawdza ponownie odczytanie powiadomienia, aktywność/obecność i uprawnienia.
Definitywne niepowodzenie odkłada rekord minimum 5 minut. Przed zewnętrznym
wywołaniem zapisuje `email_delivery_uncertain=true`; sukces lub definitywne
odrzucenie rozstrzyga ten stan. Timeout po rozpoczęciu POST, crash lub
niespodziewany wyjątek pozostawiają rekord do wyjaśnienia. Zapobiega to
automatycznemu duplikatowi kosztem możliwego ręcznego wznowienia niewysłanego
maila. Nie ma gwarancji dokładnie jednej dostawy. SMTP zachowuje dotychczasowy
kontrakt bool; pełne rozróżnienie wyników transportu dotyczy Grapha.

## Grafana — reguła systemowej wysyłki

Źródło: rzeczywisty heartbeat `event_kind=app_mail_monitor` co 60 s.
`alarm=1`: włączony kanał nieskonfigurowany, utrzymująca się awaria,
niepewna dostawa, retry starsze niż godzinę lub błąd odczytu monitora.
Wyłączony celowo kanał emituje `alarm=0`. Liczba `pending_retry` obejmuje
próbowane, nieprzeczytane powiadomienia aktywnych użytkowników, nie wszystkie
wiadomości wymagające decyzji uprawnień. Nie jest liczbą wszystkich maili NEXUS.

Zapytanie Loki (złożenie do jednej serii zapobiega alarmowi per timestamp):

```logql
max(max_over_time({app="nexus",service="backend"} | json | event_kind="app_mail_monitor" | unwrap alarm | __error__="" [3m]))
```

Próg `> 0`, pending 1 min, ewaluacja 1 min, No Data = Alerting,
Error = Alerting. Jawnie ustaw repeat interval 30 min, group interval 5 min,
group wait 30 s. Przetestuj alarm, recovery i brak próbek; samo zapisanie
formularza nie potwierdza dostawy. Nie zastępuj No Data przez zero.
Natywne Sentry Teams informuje o pierwszej awarii/zmianie przyczyny;
Grafana odpowiada za utrzymujące się przypomnienia. Odbiór na firmowy email
pozostaje wymagany niezależnie od sukcesu prywatnego kontaktu Grafany.

## Odbiór i czynności administracyjne

- Uruchomić testy jednostkowe oraz CI testujące Postgres: przetrwanie restartu,
  wyłączność próby odzyskania, opóźnienie ponowienia i niepewny wynik.
- Potwierdzić migrację 0331 i dokładny SHA API/FE, bez zmiany liveness.
- W Chrome sprawdzić podgląd Championa na dokumencie wymagającym AI i pełne
  generowanie CV. Word parsowany bez AI nie potwierdza naprawy dostawcy.
- Exchange: zweryfikować aktualnego nadawcę i zakres istniejącej polityki.
  Nie poszerzać dostępu do całego tenantu ani nie tworzyć nowej skrzynki
  bez osobnej decyzji. Kontrolna dostawa wymaga odbioru, nie tylko Graph 202.
- Nie usuwać zaległości. Rekordy z `email_delivery_uncertain=true` wymagają
  ustalenia w Exchange, czy wiadomość została przyjęta/dostarczona.
  Dopiero po tej decyzji operator może celowo oznaczyć wynik albo zaplanować
  ponowienie konkretnych rekordów. Brak automatycznego masowego resetu.
- Obserwować naturalny cykl po wdrożeniu, stan alarmu oraz tempo ubywania
  zaległości. Upływ kalendarzowych 7 dni nie kończy aktywnej awarii.

Nie zmieniamy teraz próbkowania replayów ani transportu Sentry: limit replay
jest wspólny dla organizacji i wymaga najpierw przypisania zużycia do projektów.
