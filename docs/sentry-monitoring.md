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

Build, upload map i runtime korzystają z SHA faktycznego checkoutu Coolify. Przy włączonym DSN brak pełnego SHA lub tokenu source map przerywa build. Kontrola błędu samego uploadu pozostaje odrębna; odbiór wymaga symbolikacji nowego zdarzenia. Przeglądarka, Node i Edge używają projektu frontendu. CI bez DSN może jawnie budować bez telemetrii. Nie ujawniać map w publicznym artefakcie.

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

Audyt [34893466506](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34893466506)
potwierdził Coolify 4.1.2, token map dostępny podczas builda i cykl:
`GIT_SHA=$SOURCE_COMMIT`, `SOURCE_COMMIT=${GIT_SHA:-unknown}`.
Pole `include_source_commit_in_build` nie jest obsługiwane przez używane API.
Wygenerowane przez Coolify tagi obrazów backendu i frontendu zawierały jednak
zgodny SHA rzeczywistego checkoutu `db4a807b21d3d7cf5e17ac70751015f869b9891c`.

Standardowy deploy naprawia konfigurację przez istniejący token API Actions,
bez logowania do panelu. Skrypt `configure_coolify_release.py` ustawia wyłącznie
stałą komendę budowania `sh .github/scripts/release.sh --project-directory . --env-file /artifacts/build-time.env`
i usuwa dokładnie rozpoznany produkcyjny override `SOURCE_COMMIT` powodujący cykl.
Sprawdza wynik ponownym GET; obcy custom command lub inna wartość override
zatrzymuje operację. Sekrety i konfiguracja preview pozostają zachowane.

Wrapper działa na zdalnym builderze po wygenerowaniu Compose. Odczytuje tylko
`config --images`, wymaga zgodnych tagów backend/frontend z pełnym SHA i przekazuje
ten SHA jako oba argumenty builda. Nie używa SHA wyzwalającego Actions ani `.git`,
który Coolify usuwa przed buildem. Nie wypisuje pełnego Compose lub pliku env.
Backend zapisuje SHA w obrazie i odczytuje go przy starcie przed uruchomieniem aplikacji,
aby zmienne platformy nie mogły zmienić raportowanej wersji istniejącego obrazu.
Nieznane albo niespójne tagi przerywają build. `version.json=unknown` przerywa odbiór.

Po merge wymagany jest standardowy deploy i zgodność SHA API, `version.json`,
runtime Sentry oraz symbolikacja nowego zdarzenia. Sam audyt konfiguracji i testy
wrappera nie są dowodem wdrożenia. Po aktualizacji Coolify uruchomić ponownie
`release-config-audit`; nie wyłączać walidacji w przypadku zmiany formatu tagów.

Weryfikacja lokalna bez Dockera:
`python3 -m unittest discover -s .github/scripts/tests -p 'test_coolify_release*.py'`.
Testy używają własnego substytutu CLI w katalogu tymczasowym; nie uruchamiają silnika
Docker, buildów ani kontenerów na komputerze użytkownika.
