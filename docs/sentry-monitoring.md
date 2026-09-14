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

Docelowo build, upload map i runtime muszą korzystać z rzeczywistego SHA kompilacji. Przeglądarka, Node i Edge używają projektu frontendu. Uwaga operacyjna: #1519 zmienił brak SHA/tokenu w kontroli builda na ostrzeżenie. Zatem ukończony build nie dowodzi publikacji poprawnych map. Kontrola błędu samego uploadu pozostaje odrębna. CI bez DSN może jawnie budować bez telemetrii. Nie ujawniać map w publicznym artefakcie.

Nowy frontend najpierw wykonuje prosty GET health bez dodatkowych nagłówków. Propagację do API i X-Operation-Id włącza po otrzymaniu eksponowanego X-Request-Id. Dzięki temu równoległy restart usług nie powoduje błędów CORS wobec starego backendu. Niepowodzenie sondy nie zatrzymuje aplikacji; kolejne żądanie może ponowić sondę.

Replay po błędzie pozostaje próbkowany na 10%, sesyjny na 0%. Pełne maskowanie obejmuje tekst, pola i atrybuty odnośników; dodatkowe payloady konsoli/sieci/nawigacji nie są zapisywane. Nagranie obejmujące stronę z tokenem udostępnienia, query stringiem lub fragmentem URL jest odrzucane także w kolejnych segmentach — samo maskowanie DOM nie chroni metadanych rrweb. Typy wyjątków i linie źródłowe pozostają w osobnych, redagowanych zdarzeniach błędów.

## Triage

Każde issue ma właściciela, werdykt, link do PR i release oraz dowód odtworzenia/odbioru. Regresja ponownie otwiera problem. Codzienny digest sygnalizuje brak właściciela; kontekst operacji i linki do PR należy sprawdzić w issue, jeśli API listy ich nie zwraca.

Brak nowych zdarzeń nie dowodzi poprawności: kontrolować accepted/filtered/invalid/rate-limited, działanie ingestu i rzeczywiste użycie procesu. Po wdrożeniu ocena przez 7 dni oraz pełny cykl krytycznych zadań. Nie zamykać historycznych timeoutów bez sprawdzenia aktualnego generatora/czatu.

## Status konfiguracji

Kod i ta instrukcja nie są dowodem konfiguracji panelu. Odbiór wymaga osobnego potwierdzenia: Teams workflow, sekrety, mapowanie GitHub, ownership, filtry, reguły alertów, dostarczenie e-mail oraz rzeczywista symbolikacja zdarzenia. Niewyjaśnione Invalid badać według outcome reason; nie zakładać duplikatów lub błędu SDK.

Odczyt `stats_v2` z 14.09.2026 dla `nexus-be` (projekt 4511350854647888,
`category=error`, `outcome=invalid`, grupowanie po `reason`, okno
31.08 00:00 UTC–15.09 00:00 UTC) wykazał 12 odrzuceń, wszystkie
`too_large:event`. To dowód przekroczenia rozmiaru zdarzenia, nie błędu
transportu. Wyłączenie zmiennych lokalnych i ograniczenie treści payloadu
wymaga odbioru przez ponowny odczyt nowych odrzuceń po wdrożeniu.
## Diagnostyka wersji produkcyjnej

14.09.2026 wdrożenie [34878577552](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34878577552)
ze źródłem `c80a7230d741e79e641307ec1b23b270a112b1cb` zakończyło się błędem odbioru:
API i frontend zgłaszały `unknown`. Nie potwierdza to rzeczywistej rewizji obrazu.

`Coolify Ops` → `release-config-audit` wykonuje wyłącznie GET konfiguracji aplikacji
i zmiennych. Zwraca obecność wybranych kluczy, flagi build/runtime i rozpoznane
odwołania między zmiennymi SHA; nigdy wartości sekretów. Test redakcji poprzedza
odczyt konfiguracji. Brak pola ustawień w starszym API ma wartość `null`, a nie
`false`: nie można z niego wnioskować, że opcja jest wyłączona.

Odczyty 34882689840 i 34882846625 potwierdziły token source map dostępny podczas
builda oraz odwołanie `GIT_SHA` do `SOURCE_COMMIT`. Pole
`include_source_commit_in_build` nie jest wystawiane przez używany odczyt API,
a jego PATCH został wcześniej odrzucony HTTP 422. Stan opcji trzeba sprawdzić
w zalogowanym panelu Coolify przed ponowieniem standardowego wdrożenia.

Nie wpisywać SHA uruchomienia Actions jako zastępczej wersji obrazu: Coolify może
pobrać nowszy `main`. Po naprawie konfiguracji odbiór wymaga zgodnego SHA API,
`version.json`, runtime Sentry i symbolikacji nowego zdarzenia. Ostrzeżenie o
`unknown` nie spełnia tego warunku.
