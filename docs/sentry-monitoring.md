# NEXUS Sentry: obsługa operacyjna

Właściciel triage: artur.twardowski@b2bnetwork.pl. Docelowy kanał: prywatny zespół Teams NEXUS, kanał „NEXUS — alerty”.

## Dzienny digest

Workflow `Sentry daily monitor` uruchamia się o 06:47 UTC. Czyta nexus-be i nexus-fe w production, pełną paginację unresolved oraz oznacza nowe i regresyjne issue. Oba projekty mają jedno wspólne, jawne okno start/end ostatnich 24 godzin. Liczba zdarzeń pochodzi wyłącznie z `filtered.count` dla tego zapytania; brak wartości oznacza unavailable, nigdy lifetime count ani przybliżenie z szeregu stats. Tytuły wyjątków i dane kandydatów nie trafiają do wiadomości ani logów Actions.

Wymagane sekrety repozytorium B2B-net-S-A/NEXUS:

- `SENTRY_READ_TOKEN`: osobny token odczytowy z project:read i event:read; nie token publikowania source map.
- `TEAMS_SENTRY_WEBHOOK_URL`: URL workflow „When a Teams webhook request is received” publikującego Adaptive Card w kanale. Właścicielem workflow jest Artur.

Brak sekretu, niekompletny odczyt któregokolwiek projektu, błędna paginacja albo odrzucona wysyłka powoduje niezerowy exit. `DRY_RUN=1` jest wyłącznie ręcznym, jawnym testem. Nigdy nie wypisuj URL webhooka lub tokenu w logu ani komendzie CLI. Ustawienia sekretów należy wprowadzać przez bezpieczne wejście lub panel.

Testy lokalne: `python3 -m unittest discover -s .github/scripts/tests -p test_sentry_daily_digest.py`.

Odbiór: ręczny run, poprawny odczyt obu projektów, karta rzeczywiście widoczna w Teams. HTTP 2xx webhooka oznacza przyjęcie; przy pierwszej konfiguracji trzeba sprawdzić wykonanie workflow i publikację karty.

## Release i wdrożenie

Build, upload map i runtime korzystają z rzeczywistego SHA kompilacji. Przeglądarka, Node i Edge używają projektu frontendu. Produkcyjny build z DSN wymaga tokenu uploadu oraz pełnego SHA; brak któregokolwiek lub błąd uploadu przerywa build. CI bez DSN może jawnie budować bez telemetrii. Nie ujawniać map w publicznym artefakcie.

Nowy frontend najpierw wykonuje prosty GET health bez dodatkowych nagłówków. Propagację do API i X-Operation-Id włącza po otrzymaniu eksponowanego X-Request-Id. Dzięki temu równoległy restart usług nie powoduje błędów CORS wobec starego backendu. Niepowodzenie sondy nie zatrzymuje aplikacji; kolejne żądanie może ponowić sondę.

## Triage

Każde issue ma właściciela, werdykt, link do PR i release oraz dowód odtworzenia/odbioru. Regresja ponownie otwiera problem. Codzienny digest sygnalizuje brak właściciela; kontekst operacji i linki do PR należy sprawdzić w issue, jeśli API listy ich nie zwraca.

Brak nowych zdarzeń nie dowodzi poprawności: kontrolować accepted/filtered/invalid/rate-limited, działanie ingestu i rzeczywiste użycie procesu. Po wdrożeniu ocena przez 7 dni oraz pełny cykl krytycznych zadań. Nie zamykać historycznych timeoutów bez sprawdzenia aktualnego generatora/czatu.

## Status konfiguracji

Kod i ta instrukcja nie są dowodem konfiguracji panelu. Odbiór wymaga osobnego potwierdzenia: Teams workflow, sekrety, mapowanie GitHub, ownership, filtry, reguły alertów, dostarczenie e-mail oraz rzeczywista symbolikacja zdarzenia. Niewyjaśnione Invalid badać według outcome reason; nie zakładać duplikatów lub błędu SDK.
