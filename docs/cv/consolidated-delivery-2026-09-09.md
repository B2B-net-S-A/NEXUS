# Jeden wspólny PR poprawek CV

Generator potrafił liczyć staż ze skróconej historii, przypisywać kandydatowi niepotwierdzone umiejętności i tworzyć podsumowania podporządkowane wymaganiom oferty. Wspólny pakiet oddziela pełne fakty źródłowe od redakcji CV i wymaga końcowego potwierdzenia twierdzeń przed wygenerowaniem DOCX.

## Zakres wspólnego PR

- Pełna historia źródłowa, dokładne obliczenia zakończonych lat bez tolerancji dodatkowego roku i bez podwójnego liczenia nakładających się okresów.
- Podsumowania oparte na dowodach, bez wymuszania branży IT, największej firmy i wszystkich wymagań MUST.
- Kontrola wszystkich końcowych twierdzeń po tłumaczeniu i redakcji; kompletność werdyktów, dokładne cytaty i schemat JSON odpowiedzi dostawcy. Błędy protokołu pozostają błędami.
- Skracanie zbyt długich obowiązków przez ograniczoną redakcję zamiast obcinania fragmentu tekstu, z ponowną kontrolą faktów.
- Próbki reguły klienta sprawdzane względem konkretnego szkicu i wariantu bazowego, wspólne źródła i jeden pełny zestaw faktów dla obu wariantów.
- Przechwycenie źródeł rekrutacji i wymagań przed przyjęciem zadania; kontrola pliku przed naliczeniem limitu.
- Jedna rezerwacja dwóch jednostek dla porównania reguł; prawidłowe przypisanie wywołań drugiego języka do jego własnej operacji.

To jedyny dalszy PR dla poprawek z obu audytów CV. Obejmuje kod wcześniejszych PR #1463, #1466, #1467, #1468 i #1469 oraz zastępuje wcześniejszy szkic #1441. Zmiany już scalone są częścią aktualnego main. Dalsze brakujące elementy CV-01–CV-20 będą dopisywane tutaj, bez kolejnych osobnych PR-ów.

## Weryfikacja i warunki odbioru

Po integracji aktualnego main: 133 testy źródeł, gotowości, redakcji, faktów, protokołu i rozliczeń przeszły lokalnie. Testy kontrolują odpowiedzi modeli; nie dowodzą jakości rzeczywistych CV. Pełne CI dla końcowego SHA pozostaje wymagane.

Ostatni pomiar starego wdrożonego weryfikatora: 1/4 przypadków, trzy błędy invalid_json, cztery rozliczone wywołania, USD 0.013773. Cztery mikroprzypadki nie są benchmarkiem kompletnego generatora. Zmiana wymuszająca schemat dostawcy wymaga nowego pomiaru.

PR pozostaje szkicem do zakończenia prac i odbioru. Otwarte: pełny korpus CV PL/EN i primary/fallback, koszt/opóźnienie/fałszywe odrzucenia, trwałe zadania i źródła, jawny wybór źródła, brakujące przepływy zatwierdzania, pełna weryfikacja UI oraz odbiór DL i potwierdzone standardy klientów. Rejestr wymagań: docs/cv/remediation-2026-09-09.md i szczegółowe dowody docs/cv/*delivery-2026-09-09.md. Zielone testy nie oznaczają zamknięcia całego zakresu.

## Dalsze poprawki w tym samym PR

Obie wersje językowe zwykłej generacji korzystają z jednego niezmiennego zestawu pełnych faktów (pipeline i upload). Wywołania redakcji i końcowej kontroli nadal są osobne. Po integracji 31 testów źródeł, pełnej historii i obu workerów przeszło.

Ocena instrukcji DL wymaga teraz kompletnej, jednoznacznej odpowiedzi o zadanym schemacie. Duplikat, brak indeksu, indeks logiczny/tekstowy, obcy werdykt, dodatkowe pola i błędny JSON oznaczają wszystkie linie jako wymagające sprawdzenia. Wcześniej parser mógł pominąć nieprawidłowy lub sprzeczny werdykt. 20 testów protokołu i wymuszenia schematu przeszło; nie jest to pomiar jakości modelu. Ocena instrukcji pozostaje poradą; twarda kontrola faktów następuje osobno przed DOCX.

## Pełnodokumentowy korpus v1

`backend/app/data/cv_quality/full_documents_v1.json` zawiera 20 ręcznie opisanych syntetycznych historii z 40 wariantami języka wyniku (PL/EN). Źródła są polskie; wariant EN obejmuje tłumaczenie. Pliki wejściowe DOCX mają akapity lub tabele, doświadczenie, wykształcenie i języki. Kryteria dotyczą m.in. podwójnego liczenia okresów, przerw, brakujących miesięcy, negacji, kursów, certyfikatów, danych prywatnych i instrukcji klienta dopisujących fakty. Etykiety nie pochodzą z ocenianego generatora.

`python -m scripts.prepare_cv_document_corpus --output /tmp/cv-document-corpus` tworzy 40 źródłowych DOCX oraz manifest z hashami i stanem `not_run`. Weryfikacja roundtrip potwierdza zachowanie wszystkich akapitów także w tabelach. Nie wykonuje wywołań modelu ani nie przyznaje ocen jakości. Korpus nie zawiera jeszcze skanów/OCR ani anglojęzycznych źródeł; nie zastępuje niezależnego odbioru DL. Pomiar pełnego pipeline i przegląd wyników pozostają otwarte.

## Runner pełnej generacji

`backend/scripts/eval_cv_full_documents.py` uruchamia zwykły pipeline uploadu na syntetycznym korpusie: ekstrakcja, redakcja, końcowa kontrola i DOCX. Wymaga dokładnego SHA, normalnego ai_feature/limitu oraz trwałej tożsamości próby. Nie ponawia próby z istniejącym paragonem, także niedokończonej. Modele primary/fallback sprawdza oddzielnie bez ukrytego fallbacku. Zapisuje DOCX, prywatny payload, czas, modele, tokeny i koszt; sprawdza oczekiwany staż, ale pozostawia human_accepted=null. Nie zapisuje kandydatów ani klientów.

Runner i korpus mają 7 testów lokalnych, obejmujących zachowanie źródeł, zgodność/niezgodność stażu, zmianę wejścia oraz ochronę przed ponownym przyjęciem próby i błędnym SHA. Nie wykonano rzeczywistych wywołań: lokalne środowisko nie ma klucza dostawcy ani konfiguracji aplikacji. Podłączenie do kontrolowanego uruchomienia w środowisku aplikacji, eksport artefaktów, pomiar oraz odbiór wyników pozostają otwarte.

## Ponowna weryfikacja produkcji

Health i deep health potwierdziły zdrową wersję 561f02ca383a8c94cab5268839d434db4d043825; baza i kod mają migrację 0289_cv_approved_docx, bez osieroconych rewizji. W historii tego SHA są scalenia #1458, #1460 i #1461. Poprzedni nieudany deploy nie blokuje już ich obecności na produkcji.

W uwierzytelnionym Chrome wykonano wybór konsultanta i procesu oraz zmianę Redakcja → Pod rekrutację, bez generowania ani zapisu danych kandydata. Etykiety źródeł zmieniają wymaganie Championa zgodnie z trybem; notatki pozostają opcjonalne przy braku reguły klienta. Wykryty sprzeczny, stały opis wymagający zawsze Championa i notatek poprawiono w tym PR. To dowód działania wyboru/etykiet, nie pełnego przepływu zatwierdzania DOCX.

Diagnostyka Coolify list miała osobny błąd: pomijała /api/v1 przy budowie URL. Poprawiono prefiks zgodnie z istniejącym działającym deploy.yml. Składnia bash sprawdzona; potwierdzenie żądań w środowisku GitHub pozostaje po dostarczeniu tej zmiany. Nie zmieniano tokenów ani uprawnień.

## Jawny wybór pliku źródłowego

Wspólny formularz samodzielny/osadzony pobiera listę obsługiwanych plików kandydata, pokazuje nazwę, datę oraz oznaczenie głównego i wymaga wyboru przed generacją. Wysyła cv_document_id; loader ogranicza zapytanie jednocześnie do tego ID i kandydata. Usunięty lub obcy wybrany dokument nie uruchamia zastępczego pliku. Wybór jest powiązany ze wskazanym kandydatem. Źródłowe bajty pozostają przechwytywane przed przyjęciem zadania i wspólne dla obu języków.

Dla zgodności starszych wywołań API cv_document_id pozostaje opcjonalne; stary osobny modal i próbki reguł wymagają jeszcze wyrównania. Nie jest to trwały snapshot zadania. 29 regresji źródeł/gotowości, następnie 7 testów wyboru/przyjęcia oraz 16 testów formularza przeszło; TypeScript i Ruff bez błędów. Produkcyjny wybór konkretnego pliku czeka na wdrożenie tego PR.

Wybór źródła jest wspólnym komponentem i hookiem także w starszym CVGeneratorV2. Starszy modal przesyła wybrane ID, blokuje start bez niego i czyści wybór przy zamknięciu. Zmiana kandydata resetuje proces, zgodę, wynik i błąd; wybór źródła jest dodatkowo powiązany z ID osoby. 16 testów formularza i TypeScript przeszły po współdzieleniu kodu. Osobny test zmiany osoby sprawdza wyłączenie generacji i konieczność wyboru nowego dokumentu.

## Źródło podglądu reguł klienta

Podgląd korzysta z tego samego wyboru konkretnego pliku co generator. API przechwytuje źródła przed rezerwacją dwóch jednostek, sprawdza czytelność pliku i zgodność kandydata/procesu/klienta, a potem przekazuje snapshot do workera. Oba warianty używają tych samych bajtów i jednego zestawu faktów. Normalna ścieżka workera nie odczytuje ponownie bieżącego CV; zgodność starszych bezpośrednich wywołań zachowano przez opcjonalny argument. Snapshot nadal znajduje się w pamięci procesu — trwałe zadania i odtworzenie po restarcie pozostają osobnym, otwartym wymaganiem.

19 testów publikacji/gotowości/wyboru oraz test interfejsu podglądu przeszły; TypeScript i Ruff bez błędów. Test backendowy weryfikuje brak ponownego odczytu źródła, test UI wymaga wyboru pliku i sprawdza przekazanie jego ID. Test API z bazą używa poprawnego syntetycznego DOCX i będzie wykonany w hosted CI.

## Durable generation work (branch only, not production acceptance)

Commits 99887af5 through c5a4514f introduce a versioned private input format,
SHA-256 integrity checks, a job table (0290), atomic lease claims, renewal,
queued-attempt recovery and expired-owner write fencing. Normal candidate,
upload and client-rule preview admission now save captured inputs before
returning 202. Both language result IDs belong to their parent attempt. An
expired running attempt is interrupted rather than automatically making a new
paid provider request. Preview reads no longer invent a failure at 15 minutes
for a durable attempt.

Evidence: focused host-native snapshot, SQLite state-transition, executor and
admission tests passed. Separate PostgreSQL concurrent-claim tests are added;
CI on cdd7eb8d had lint/migrations, frontend typecheck and secret scanning green
at inspection, while full backend shards were still running. These are not
restart or real-provider acceptance tests.

Still required before this is complete: real restart/concurrent-worker proof,
retry/idempotency/progress UI and API, storage failure before quota admission,
input retention/orphan cleanup, transitional legacy processing rows, and full
coverage of cancellation during the secondary provider call. Snapshot schema
compatibility across deployments and exact model/prompt/template provenance
also remain to be completed. Do not treat CV-09 or either audit as closed.
